# listings/services/sms_service.py

import logging
import time

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class TextSMSService:
    """Provider-aware SMS service used across the project."""

    def __init__(self, retries=3):
        self.retries = retries
        self.provider = getattr(settings, "SMS_PROVIDER", "textsms").lower()

        self.textsms_url = settings.TEXTSMS_API_URL
        self.textsms_partner_id = settings.TEXTSMS_PARTNER_ID
        self.textsms_api_key = settings.TEXTSMS_API_KEY
        self.textsms_sender_id = settings.TEXTSMS_SENDER_ID

        self.opensms_url = settings.OPENSMS_API_URL
        self.opensms_token = settings.OPENSMS_API_TOKEN
        self.opensms_sender_id = settings.OPENSMS_SENDER_ID

        self.session = requests.Session()
        retry_strategy = Retry(
            total=retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)

        logger.info("SMS service initialized with provider=%s retries=%s", self.provider, retries)

    @staticmethod
    def _format_number(number):
        number = str(number).strip().replace(" ", "")
        if number.startswith("+"):
            number = number[1:]
        if number.startswith("0"):
            number = "254" + number[1:]
        if number.startswith("7"):
            number = "254" + number
        return number

    def _resolve_opensms_url(self):
        base_url = (self.opensms_url or "").rstrip("/")
        if base_url.endswith("/api/v3") or base_url.endswith("/v3"):
            return f"{base_url}/sms/send"
        return base_url

    @staticmethod
    def _safe_json(response):
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    def _log_sms(self, *, provider, phone, message, status_code, success, response_body, message_id=""):
        try:
            from notifications.models import SMSLog

            SMSLog.objects.create(
                provider=provider,
                phone=phone,
                message=message,
                status_code=status_code,
                success=success,
                message_id=message_id,
                response_body=response_body,
            )
        except Exception:
            logger.exception("Could not persist SMS log")

    def _send_via_textsms(self, mobile, message):
        payload = {
            "apikey": self.textsms_api_key,
            "partnerID": self.textsms_partner_id,
            "message": message,
            "shortcode": self.textsms_sender_id,
            "mobile": mobile,
        }
        headers = {"Content-Type": "application/json"}
        response = self.session.post(
            self.textsms_url,
            headers=headers,
            json=payload,
            timeout=10,
        )
        result = self._safe_json(response)
        if response.status_code in (200, 201):
            message_id = ""
            if isinstance(result, dict):
                resp_list = result.get("responses") or []
                if resp_list and isinstance(resp_list, list):
                    message_id = str(resp_list[0].get("messageid", ""))
            self._log_sms(
                provider="textsms",
                phone=mobile,
                message=message,
                status_code=response.status_code,
                success=True,
                response_body=result,
                message_id=message_id,
            )
            return {
                "success": True,
                "data": result,
                "message": "SMS sent successfully",
            }

        self._log_sms(
            provider="textsms",
            phone=mobile,
            message=message,
            status_code=response.status_code,
            success=False,
            response_body=result,
        )
        return {
            "success": False,
            "error": f"API returned {response.status_code}",
            "data": result,
        }

    @staticmethod
    def _extract_provider_error(result, default_status):
        if isinstance(result, dict):
            return (
                result.get("message")
                or result.get("error")
                or result.get("detail")
                or f"API returned {default_status}"
            )
        return f"API returned {default_status}"

    def _send_via_opensms(self, mobile, message, include_sender_id=True):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.opensms_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "recipient": mobile,
            "phone": mobile,
            "message": message,
        }
        if include_sender_id and self.opensms_sender_id:
            payload["sender_id"] = self.opensms_sender_id

        response = self.session.post(
            self._resolve_opensms_url(),
            headers=headers,
            json=payload,
            timeout=10,
        )
        result = self._safe_json(response)
        if response.status_code in (200, 201) and not (
            isinstance(result, dict) and result.get("status") == "error"
        ):
            message_id = ""
            if isinstance(result, dict):
                message_id = str(
                    result.get("message_id")
                    or result.get("id")
                    or result.get("reference")
                    or ""
                )
            self._log_sms(
                provider="opensms",
                phone=mobile,
                message=message,
                status_code=response.status_code,
                success=True,
                response_body=result,
                message_id=message_id,
            )
            return {
                "success": True,
                "data": result,
                "message": "SMS sent successfully",
            }

        if response.status_code == 403 and include_sender_id and self.opensms_sender_id:
            logger.warning(
                "OpenSMS rejected sender_id=%s for %s with 403. Retrying without sender_id.",
                self.opensms_sender_id,
                mobile,
            )
            retry_result = self._send_via_opensms(mobile, message, include_sender_id=False)
            if retry_result.get("success"):
                return retry_result

        self._log_sms(
            provider="opensms",
            phone=mobile,
            message=message,
            status_code=response.status_code,
            success=False,
            response_body=result,
        )
        return {
            "success": False,
            "error": self._extract_provider_error(result, response.status_code),
            "data": result,
        }

    def send_sms(self, phone_numbers, message, attempt=1):
        """Send SMS with provider switching and retry on failures."""
        if isinstance(phone_numbers, str):
            phone_numbers = [phone_numbers]

        formatted_numbers = [self._format_number(n) for n in phone_numbers]
        recipient_blob = ",".join(formatted_numbers)

        try:
            logger.info(
                "Attempt %s sending SMS via %s to %s",
                attempt,
                self.provider,
                formatted_numbers,
            )
            if self.provider == "opensms":
                # OpenSMS examples/documentation are single-recipient oriented.
                if len(formatted_numbers) == 1:
                    return self._send_via_opensms(formatted_numbers[0], message)

                results = []
                for number in formatted_numbers:
                    results.append(self._send_via_opensms(number, message))
                all_success = all(item.get("success") for item in results)
                return {
                    "success": all_success,
                    "data": results,
                    "message": f"SMS processed for {len(formatted_numbers)} recipient(s)",
                }

            return self._send_via_textsms(recipient_blob, message)

        except Exception as exc:
            logger.error("SMS attempt %s failed: %s", attempt, exc)
            if attempt < self.retries:
                wait_time = attempt * 2
                logger.info("Retrying SMS in %s seconds", wait_time)
                time.sleep(wait_time)
                return self.send_sms(phone_numbers, message, attempt + 1)

            failure_body = {"error": str(exc)}
            self._log_sms(
                provider=self.provider,
                phone=recipient_blob,
                message=message,
                status_code=None,
                success=False,
                response_body=failure_body,
            )
            return {
                "success": False,
                "error": f"Failed after {self.retries} attempts: {exc}",
                "data": failure_body,
            }

    def send_otp(self, phone_number, otp_code):
        if getattr(settings, "USE_SMS_MOCK", False):
            logger.info("[SMS MOCK] OTP for %s: %s", phone_number, otp_code)
            return {
                "success": True,
                "data": {"mock": True},
                "message": "SMS mocked in dev",
            }
        message = f"Your AgriPlot verification code is: {otp_code}. Valid for 10 minutes."
        return self.send_sms(phone_number, message)

    def send_task_assigned(self, phone_number, officer_name, plot_title):
        message = f"NEW TASK: Hi {officer_name}, you have been assigned to verify plot '{plot_title}'."
        return self.send_sms(phone_number, message)

    def send_plot_approved(self, phone_number, plot_title):
        message = f"GREAT NEWS! Your plot '{plot_title}' has been APPROVED and is now live!"
        return self.send_sms(phone_number, message)

    def send_plot_rejected(self, phone_number, plot_title, reason):
        message = f"PLOT UPDATE: Your plot '{plot_title}' was not approved. Reason: {reason[:100]}"
        return self.send_sms(phone_number, message)

    def send_reminder(self, phone_number, task_type, plot_title):
        message = f"REMINDER: You have a pending {task_type} for plot '{plot_title}'."
        return self.send_sms(phone_number, message)

    def send_changes_requested(self, phone_number, plot_title, requested_by):
        message = f"CHANGES REQUESTED: {requested_by} has requested changes to your plot '{plot_title}'."
        return self.send_sms(phone_number, message)
