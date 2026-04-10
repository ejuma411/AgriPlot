import base64
import logging
from datetime import datetime

import requests
from requests import RequestException
from django.conf import settings


logger = logging.getLogger(__name__)


class DarajaError(Exception):
    """Raised when Daraja authentication or STK push fails."""


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        raw = (response.text or "").strip()
        logger.error(
            "Daraja returned non-JSON response [%s]: %s",
            response.status_code,
            raw[:300] or "<empty body>",
        )
        return {"raw": raw}


def daraja_ready():
    return bool(
        settings.MPESA_CONSUMER_KEY
        and settings.MPESA_CONSUMER_SECRET
        and settings.MPESA_BUSINESS_SHORTCODE
        and settings.MPESA_PASSKEY
    )


def _base_url():
    if settings.MPESA_ENVIRONMENT == "production":
        return "https://api.safaricom.co.ke"
    return "https://sandbox.safaricom.co.ke"


def _format_phone(number):
    number = str(number or "").strip().replace(" ", "")
    if number.startswith("+"):
        number = number[1:]
    if number.startswith("0"):
        number = f"254{number[1:]}"
    if number.startswith("7"):
        number = f"254{number}"
    return number


def _timestamp():
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _password(timestamp):
    raw = f"{settings.MPESA_BUSINESS_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}"
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")


def _access_token():
    consumer = settings.MPESA_CONSUMER_KEY
    secret = settings.MPESA_CONSUMER_SECRET
    auth = base64.b64encode(f"{consumer}:{secret}".encode("utf-8")).decode("utf-8")
    try:
        response = requests.get(
            f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials",
            headers={"Authorization": f"Basic {auth}"},
            timeout=20,
        )
    except RequestException as exc:
        logger.exception("Daraja auth connection failed")
        raise DarajaError(
            "Unable to reach Safaricom Daraja right now. Please try again shortly."
        ) from exc
    data = _safe_json(response)
    token = data.get("access_token")
    if response.status_code >= 400 or not token:
        message = (
            data.get("errorMessage")
            or data.get("error_description")
            or data.get("raw")
            or "Unable to authenticate with Daraja."
        )
        logger.error("Daraja auth failed: %s", message)
        raise DarajaError(message)
    return token


def initiate_stk_push(payment, callback_url):
    phone_number = _format_phone(payment.phone_number)
    timestamp = _timestamp()
    token = _access_token()
    payload = {
        "BusinessShortCode": settings.MPESA_BUSINESS_SHORTCODE,
        "Password": _password(timestamp),
        "Timestamp": timestamp,
        "TransactionType": settings.MPESA_TRANSACTION_TYPE,
        "Amount": int(payment.amount),
        "PartyA": phone_number,
        "PartyB": settings.MPESA_BUSINESS_SHORTCODE,
        "PhoneNumber": phone_number,
        "CallBackURL": callback_url,
        "AccountReference": payment.internal_reference[:12],
        "TransactionDesc": (payment.title or payment.internal_reference)[:182],
    }
    try:
        response = requests.post(
            f"{_base_url()}/mpesa/stkpush/v1/processrequest",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
    except RequestException as exc:
        logger.exception("Daraja STK connection failed for payment %s", payment.internal_reference)
        raise DarajaError(
            "Safaricom Daraja is temporarily unreachable. Please try again shortly."
        ) from exc
    data = _safe_json(response)
    if response.status_code >= 400 or data.get("errorCode"):
        message = (
            data.get("errorMessage")
            or data.get("errorCode")
            or data.get("raw")
            or "Unable to initiate Daraja STK push."
        )
        logger.error("Daraja STK push failed: %s", message)
        raise DarajaError(message)
    return data


def extract_callback_metadata(callback):
    metadata_items = (
        callback.get("CallbackMetadata", {}) or {}
    ).get("Item", [])
    extracted = {}
    for item in metadata_items:
        name = item.get("Name")
        if not name:
            continue
        extracted[name] = item.get("Value")
    return extracted
