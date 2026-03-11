# listings/services/sms_service.py

import logging
import time
import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class TextSMSService:
    """Service for sending SMS via TextSMS API with retry logic."""

    def __init__(self, retries=3):
        self.base_url = settings.TEXTSMS_API_URL
        self.partner_id = settings.TEXTSMS_PARTNER_ID
        self.api_key = settings.TEXTSMS_API_KEY
        self.sender_id = settings.TEXTSMS_SENDER_ID
        self.retries = retries

        # Create session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)

        logger.info(f"📱 TextSMS Service initialized with {retries} retries")

    @staticmethod
    def _format_number(number):
        number = str(number).strip().replace(' ', '')
        if number.startswith('+'):
            number = number[1:]
        if number.startswith('0'):
            number = '254' + number[1:]
        if number.startswith('7'):
            number = '254' + number
        return number

    def send_sms(self, phone_numbers, message, attempt=1):
        """Send SMS with automatic retry on failure"""
        if isinstance(phone_numbers, str):
            phone_numbers = [phone_numbers]

        formatted_numbers = [self._format_number(n) for n in phone_numbers]
        mobile = ','.join(formatted_numbers)

        payload = {
            'apikey': self.api_key,
            'partnerID': self.partner_id,
            'message': message,
            'shortcode': self.sender_id,
            'mobile': mobile
        }

        headers = {
            'Content-Type': 'application/json'
        }

        try:
            logger.info(f"📤 Attempt {attempt}: Sending SMS to {formatted_numbers}")
            response = self.session.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=10
            )

            if response.status_code in (200, 201):
                result = response.json()
                logger.info("✅ SMS sent successfully")
                try:
                    from notifications.models import SMSLog
                    message_id = ""
                    if isinstance(result, dict):
                        resp_list = result.get('responses') or []
                        if resp_list and isinstance(resp_list, list):
                            message_id = str(resp_list[0].get('messageid', ''))
                    SMSLog.objects.create(
                        provider='textsms',
                        phone=mobile,
                        message=message,
                        status_code=response.status_code,
                        success=True,
                        message_id=message_id,
                        response_body=result
                    )
                except Exception:
                    pass
                return {
                    'success': True,
                    'data': result,
                    'message': f"SMS sent to {len(formatted_numbers)} recipient(s)"
                }

            logger.error(f"❌ SMS failed: {response.status_code} {response.text}")
            try:
                from notifications.models import SMSLog
                SMSLog.objects.create(
                    provider='textsms',
                    phone=mobile,
                    message=message,
                    status_code=response.status_code,
                    success=False,
                    response_body={'raw': response.text}
                )
            except Exception:
                pass
            return {
                'success': False,
                'error': f"API returned {response.status_code}"
            }

        except Exception as e:
            logger.error(f"❌ Attempt {attempt} failed: {str(e)}")
            if attempt < self.retries:
                wait_time = attempt * 2
                logger.info(f"⏳ Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                return self.send_sms(phone_numbers, message, attempt + 1)
            return {
                'success': False,
                'error': f"Failed after {self.retries} attempts: {str(e)}"
            }

    def send_otp(self, phone_number, otp_code):
        if getattr(settings, "USE_SMS_MOCK", False):
            logger.info(f"[SMS MOCK] OTP for {phone_number}: {otp_code}")
            return {
                'success': True,
                'data': {'mock': True},
                'message': 'SMS mocked in dev'
            }
        message = f"Your AgriPlot verification code is: {otp_code}. Valid for 10 minutes."
        return self.send_sms(phone_number, message)

    def send_task_assigned(self, phone_number, officer_name, plot_title):
        message = f"🔔 NEW TASK: Hi {officer_name}, you have been assigned to verify plot '{plot_title}'."
        return self.send_sms(phone_number, message)

    def send_plot_approved(self, phone_number, plot_title):
        message = f"✅ GREAT NEWS! Your plot '{plot_title}' has been APPROVED and is now live!"
        return self.send_sms(phone_number, message)

    def send_plot_rejected(self, phone_number, plot_title, reason):
        message = f"📝 PLOT UPDATE: Your plot '{plot_title}' was not approved. Reason: {reason[:100]}"
        return self.send_sms(phone_number, message)

    def send_reminder(self, phone_number, task_type, plot_title):
        message = f"⏰ REMINDER: You have a pending {task_type} for plot '{plot_title}'."
        return self.send_sms(phone_number, message)

    def send_changes_requested(self, phone_number, plot_title, requested_by):
        message = f"📋 CHANGES REQUESTED: {requested_by} has requested changes to your plot '{plot_title}'."
        return self.send_sms(phone_number, message)
