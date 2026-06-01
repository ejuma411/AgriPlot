import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


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
        return (
            payload.get("reference")
            or payload.get("transferReference")
            or payload.get("transactionReference")
            or payload.get("providerReference")
            or payload.get("conversationId")
            or payload.get("ConversationID")
            or payload.get("requestReference")
        )


class JengaBankTransferProvider(BaseBankTransferProvider):
    provider_name = "jenga"
    default_endpoint = "/v3/transaction/sendmoney"

    def _config(self, name, default=""):
        return getattr(settings, name, default)

    def choose_rail(self, amount):
        limit = Decimal(str(self._config("BANK_TRANSFER_PESALINK_LIMIT", "999999.00")))
        if amount <= limit:
            return "pesalink"
        return "rtgs"

    def _canonical_string(self, payload):
        transfer = payload.get("transfer", {})
        destination = payload.get("destination", {})
        return "".join(
            [
                str(destination.get("accountNumber", "")),
                str(destination.get("bankCode", "")),
                str(transfer.get("amount", "")),
                str(transfer.get("currencyCode", "")),
                str(transfer.get("reference", "")),
            ]
        )

    def _sign_rsa(self, canonical_string):
        key_path = self._config("BANK_TRANSFER_PRIVATE_KEY_PATH", "").strip()
        if not key_path:
            raise ValidationError("BANK_TRANSFER_PRIVATE_KEY_PATH is required for RSA signing.")

        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:
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
        destination_country = self._config("BANK_TRANSFER_DESTINATION_COUNTRY_CODE", "KE").strip() or "KE"
        payload = {
            "source": {
                "countryCode": source_country,
                "accountNumber": source_account,
                "name": source_name,
            },
            "destination": {
                "type": "bank",
                "countryCode": destination_country,
                "name": transfer.beneficiary_name,
                "bankCode": transfer.bank_code,
                "accountNumber": transfer.account_number,
            },
            "transfer": {
                "amount": str(transfer.amount),
                "currencyCode": transfer.currency,
                "reference": transfer.reference,
                "description": transfer.payment.title[:180],
                "rail": transfer.rail,
            },
        }
        return payload

    def submit(self):
        transfer = self.transfer
        if not transfer:
            raise ValidationError("A bank transfer request is required.")
        base_url = self._config("BANK_TRANSFER_API_BASE_URL", "https://jengaapi.io").rstrip("/")
        endpoint = self._config("BANK_TRANSFER_API_PATH", self.default_endpoint)
        token = self._config("BANK_TRANSFER_BEARER_TOKEN", "").strip()
        source_account = self._config("BANK_TRANSFER_SOURCE_ACCOUNT_NUMBER", "").strip()
        source_name = self._config("BANK_TRANSFER_SOURCE_ACCOUNT_NAME", "").strip()
        if not token:
            raise ValidationError("BANK_TRANSFER_BEARER_TOKEN is required before submitting bank transfers.")
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
                "Signature": signature,
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
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding
            except ImportError:
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
