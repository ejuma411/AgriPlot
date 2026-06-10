import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

JENGA_AUTH_TOKEN_CACHE_KEY = "payments:jenga:access_token"
JENGA_AUTH_TOKEN_TTL_SECONDS = 3300


class BankTransferProviderError(Exception):
    """Raised when a bank transfer provider rejects or cannot process a request."""


class BaseBankTransferProvider:
    provider_name = "manual"

    def __init__(self, transfer=None):
        self.transfer = transfer

    def choose_rail(self, amount):
        raise NotImplementedError

    def build_payload(self):
        raise NotImplementedError

    def sign_payload(self, payload):
        return ""

    def submit(self):
        raise NotImplementedError

    def verify_callback(self, payload, headers):
        return True

    def extract_reference(self, payload):
        transaction = payload.get("transaction", {}) or {}
        data = payload.get("data", {}) or {}
        return (
            payload.get("reference")
            or payload.get("transferReference")
            or payload.get("transactionReference")
            or payload.get("providerReference")
            or payload.get("conversationId")
            or payload.get("ConversationID")
            or payload.get("requestReference")
            or transaction.get("reference")
            or transaction.get("transactionReference")
            or data.get("transactionId")
            or data.get("reference")
        )


class JengaBankTransferProvider(BaseBankTransferProvider):
    provider_name = "jenga"
    default_endpoint = "/v3-apis/transaction-api/v3.0/remittance/internalBankTransfer/imt"
    pesalink_endpoint = "/v3-apis/transaction-api/v3.0/remittance/pesalinkacc/imt"
    rtgs_endpoint = "/v3-apis/transaction-api/v3.0/remittance/internalBankTransfer/imt"

    def _config(self, name, default=""):
        return getattr(settings, name, default)

    def choose_rail(self, amount):
        limit = Decimal(str(self._config("BANK_TRANSFER_PESALINK_LIMIT", "999999.00")))
        if amount <= limit:
            return "pesalink"
        return "rtgs"

    def _auth_base_url(self):
        return self._config("BANK_TRANSFER_AUTH_API_BASE_URL", "https://api.finserve.africa").rstrip("/")

    def _auth_endpoint(self):
        return self._config(
            "BANK_TRANSFER_AUTH_API_PATH",
            "/authentication/api/v3/authenticate/merchant",
        )

    def _access_token(self):
        configured_token = self._config("BANK_TRANSFER_BEARER_TOKEN", "").strip()
        if configured_token:
            return configured_token

        cached_token = cache.get(JENGA_AUTH_TOKEN_CACHE_KEY)
        if cached_token:
            return cached_token

        api_key = (
            self._config("JENGA_API_KEY", "").strip()
            or self._config("JENGA_CONSUMER_KEY", "").strip()
        )
        merchant_code = self._config("JENGA_MERCHANT_CODE", "").strip()
        consumer_secret = self._config("JENGA_CONSUMER_SECRET", "").strip()
        if not (api_key and merchant_code and consumer_secret):
            raise ValidationError(
                "JENGA_API_KEY/JENGA_CONSUMER_KEY, JENGA_MERCHANT_CODE, and JENGA_CONSUMER_SECRET are required to generate a bearer token."
            )

        response = requests.post(
            f"{self._auth_base_url()}{self._auth_endpoint()}",
            json={
                "merchantCode": merchant_code,
                "consumerSecret": consumer_secret,
            },
            timeout=int(self._config("BANK_TRANSFER_TIMEOUT_SECONDS", 30)),
            headers={
                "Content-Type": "application/json",
                "Api-Key": api_key,
            },
        )
        data = self._safe_json(response)
        token = data.get("accessToken") or data.get("access_token")
        if response.status_code >= 400 or not token:
            message = (
                data.get("message")
                or data.get("errorMessage")
                or data.get("error_description")
                or data.get("raw")
                or "Unable to authenticate with Jenga."
            )
            raise ValidationError(message)

        cache.set(JENGA_AUTH_TOKEN_CACHE_KEY, token, JENGA_AUTH_TOKEN_TTL_SECONDS)
        return token

    def _canonical_string(self, payload):
        rail = (payload.get("transfer", {}) or {}).get("rail", "") or self._rail_from_payload(payload)
        transfer = payload.get("transfer", {})
        destination = payload.get("destination", {})
        source = payload.get("source", {})
        if rail == "rtgs":
            return "".join(
                [
                    str(source.get("accountNumber", "")),
                    str(transfer.get("amount", "")),
                    str(transfer.get("currencyCode", "")),
                    str(transfer.get("reference", "")),
                ]
            )
        if rail == "pesalink":
            return "".join(
                [
                    str(transfer.get("amount", "")),
                    str(transfer.get("currencyCode", "")),
                    str(transfer.get("reference", "")),
                    str(destination.get("name", "")),
                    str(source.get("accountNumber", "")),
                ]
            )
        return "".join(
            [
                str(source.get("accountNumber", "")),
                str(transfer.get("amount", "")),
                str(transfer.get("currencyCode", "")),
                str(transfer.get("reference", "")),
            ]
        )

    def _rail_from_payload(self, payload):
        return (
            payload.get("transfer", {}).get("rail")
            or getattr(self.transfer, "rail", "")
            or "eft"
        ).lower()

    def _submit_endpoint(self, rail):
        custom_path = self._config("BANK_TRANSFER_API_PATH", "").strip()
        if custom_path:
            return custom_path
        if rail == "pesalink":
            return self.pesalink_endpoint
        return self.rtgs_endpoint

    def _sender_payload(self):
        sender_name = self._config("BANK_TRANSFER_SENDER_NAME", "").strip()
        if not sender_name:
            sender_name = self._config("BANK_TRANSFER_SOURCE_ACCOUNT_NAME", "").strip()
        sender_document_type = self._config("BANK_TRANSFER_SENDER_DOCUMENT_TYPE", "").strip()
        sender_document_number = self._config("BANK_TRANSFER_SENDER_DOCUMENT_NUMBER", "").strip()
        sender_country = self._config("BANK_TRANSFER_SENDER_COUNTRY_CODE", "KE").strip() or "KE"
        sender_mobile_number = self._config("BANK_TRANSFER_SENDER_MOBILE_NUMBER", "").strip()
        sender_email = self._config("BANK_TRANSFER_SENDER_EMAIL", "").strip()
        sender_address = self._config("BANK_TRANSFER_SENDER_ADDRESS", "").strip()
        if not sender_name:
            raise ValidationError("BANK_TRANSFER_SENDER_NAME or BANK_TRANSFER_SOURCE_ACCOUNT_NAME is required.")

        sender = {
            "name": sender_name,
            "countryCode": sender_country,
        }
        if sender_document_type:
            sender["documentType"] = sender_document_type
        if sender_document_number:
            sender["documentNumber"] = sender_document_number
        if sender_mobile_number:
            sender["mobileNumber"] = sender_mobile_number
        if sender_email:
            sender["email"] = sender_email
        if sender_address:
            sender["address"] = sender_address
        return sender

    def _destination_payload(self):
        transfer = self.transfer
        destination = {
            "type": "bank",
            "countryCode": self._config("BANK_TRANSFER_DESTINATION_COUNTRY_CODE", "KE").strip() or "KE",
            "name": transfer.beneficiary_name,
            "bankCode": transfer.bank_code,
            "accountNumber": transfer.account_number,
        }
        destination_mobile = self._config("BANK_TRANSFER_DESTINATION_MOBILE_NUMBER", "").strip()
        destination_doc_type = self._config("BANK_TRANSFER_DESTINATION_DOCUMENT_TYPE", "").strip()
        destination_doc_number = self._config("BANK_TRANSFER_DESTINATION_DOCUMENT_NUMBER", "").strip()
        destination_email = self._config("BANK_TRANSFER_DESTINATION_EMAIL", "").strip()
        destination_address = self._config("BANK_TRANSFER_DESTINATION_ADDRESS", "").strip()
        if destination_mobile:
            destination["mobileNumber"] = destination_mobile
        if destination_doc_type:
            destination["documentType"] = destination_doc_type
        if destination_doc_number:
            destination["documentNumber"] = destination_doc_number
        if destination_email:
            destination["email"] = destination_email
        if destination_address:
            destination["address"] = destination_address
        return destination

    def _sign_rsa(self, canonical_string):
        key_path = self._config("BANK_TRANSFER_PRIVATE_KEY_PATH", "").strip()
        if not key_path:
            raise ValidationError("BANK_TRANSFER_PRIVATE_KEY_PATH is required for RSA signing.")

        try:
            import importlib
            hashes = importlib.import_module("cryptography.hazmat.primitives.hashes")
            serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
            padding = importlib.import_module("cryptography.hazmat.primitives.asymmetric.padding")
        except Exception as exc:
            raise ValidationError("cryptography is required for RSA bank transfer signing.") from exc

        with open(key_path, "rb") as handle:
            private_key = serialization.load_pem_private_key(
                handle.read(),
                password=self._config("BANK_TRANSFER_PRIVATE_KEY_PASSWORD", "").encode("utf-8") or None,
            )
        signature = private_key.sign(
            canonical_string.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _sign_hmac(self, canonical_string):
        secret = self._config("BANK_TRANSFER_SHARED_SECRET", "").strip()
        if not secret:
            raise ValidationError("BANK_TRANSFER_SHARED_SECRET is required for HMAC signing.")
        signature = hmac.new(
            secret.encode("utf-8"),
            canonical_string.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def sign_payload(self, payload):
        algorithm = self._config("BANK_TRANSFER_SIGNATURE_ALGORITHM", "rsa").lower()
        canonical_string = self._canonical_string(payload)
        if algorithm == "hmac":
            return self._sign_hmac(canonical_string)
        return self._sign_rsa(canonical_string)

    def build_payload(self):
        transfer = self.transfer
        source_account = self._config("BANK_TRANSFER_SOURCE_ACCOUNT_NUMBER", "").strip()
        source_name = self._config("BANK_TRANSFER_SOURCE_ACCOUNT_NAME", "").strip()
        source_country = self._config("BANK_TRANSFER_SOURCE_COUNTRY_CODE", "KE").strip() or "KE"
        transfer_date = timezone.localdate().isoformat()
        rail = (transfer.rail or "").lower()
        sender_payload = self._sender_payload()
        destination_payload = self._destination_payload()
        source_payload = {
            "countryCode": source_country,
            "accountNumber": source_account,
            "name": source_name or sender_payload["name"],
        }
        if transfer.currency:
            source_payload["currencyCode"] = transfer.currency
        payload = {
            "source": source_payload,
            "sender": sender_payload,
            "destination": destination_payload,
            "transfer": {
                "amount": str(transfer.amount),
                "currencyCode": transfer.currency,
                "reference": transfer.reference,
                "date": transfer_date,
                "description": transfer.payment.title[:180],
                "rail": rail,
                "type": "Pesalink" if rail == "pesalink" else "InternalFundsTransfer",
            },
        }
        return payload

    def submit(self):
        transfer = self.transfer
        if not transfer:
            raise ValidationError("A bank transfer request is required.")
        base_url = self._config("BANK_TRANSFER_API_BASE_URL", "https://api.finserve.africa").rstrip("/")
        endpoint = self._submit_endpoint(transfer.rail.lower())
        token = self._access_token()
        source_account = self._config("BANK_TRANSFER_SOURCE_ACCOUNT_NUMBER", "").strip()
        source_name = self._config("BANK_TRANSFER_SOURCE_ACCOUNT_NAME", "").strip()
        if not source_account:
            raise ValidationError("BANK_TRANSFER_SOURCE_ACCOUNT_NUMBER is required before submitting bank transfers.")
        if not source_name:
            raise ValidationError("BANK_TRANSFER_SOURCE_ACCOUNT_NAME is required before submitting bank transfers.")
        payload = self.build_payload()
        signature = self.sign_payload(payload)
        response = requests.post(
            f"{base_url}{endpoint}",
            json=payload,
            timeout=int(self._config("BANK_TRANSFER_TIMEOUT_SECONDS", 30)),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "signature": signature,
                "Idempotency-Key": transfer.idempotency_key or transfer.reference,
            },
        )
        data = self._safe_json(response)
        if response.status_code >= 400:
            raise BankTransferProviderError(
                data.get("message")
                or data.get("errorMessage")
                or data.get("error")
                or response.reason
            )
        if isinstance(data.get("data"), dict) and data["data"].get("transactionId"):
            data.setdefault("providerReference", data["data"]["transactionId"])
        return data

    def _safe_json(self, response):
        try:
            return response.json()
        except ValueError:
            return {"raw": (response.text or "").strip()}

    def verify_callback(self, payload, headers):
        header_name = self._config("BANK_TRANSFER_CALLBACK_SIGNATURE_HEADER", "X-Signature")
        provided_signature = headers.get(header_name) or headers.get(header_name.lower())
        if not provided_signature:
            return not bool(self._config("BANK_TRANSFER_CALLBACK_VERIFY_SIGNATURE", False))

        secret = self._config("BANK_TRANSFER_WEBHOOK_SECRET", "").strip()
        public_key_path = self._config("BANK_TRANSFER_CALLBACK_PUBLIC_KEY_PATH", "").strip()
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

        if secret:
            expected = base64.b64encode(
                hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
            ).decode("utf-8")
            return hmac.compare_digest(expected, provided_signature)

        if public_key_path:
            try:
                import importlib
                hashes = importlib.import_module("cryptography.hazmat.primitives.hashes")
                serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
                padding = importlib.import_module("cryptography.hazmat.primitives.asymmetric.padding")
            except Exception:
                raise ValidationError("cryptography is required to verify signed bank callbacks.")
            with open(public_key_path, "rb") as handle:
                public_key = serialization.load_pem_public_key(handle.read())
            try:
                public_key.verify(
                    base64.b64decode(provided_signature),
                    body,
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
                return True
            except Exception:
                return False

        return True


def get_bank_transfer_provider(name=None, transfer=None):
    provider_name = (name or getattr(settings, "BANK_TRANSFER_PROVIDER", "jenga")).lower()
    if provider_name == "jenga":
        return JengaBankTransferProvider(transfer=transfer)
    return BaseBankTransferProvider(transfer=transfer)
