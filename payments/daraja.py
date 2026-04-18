import base64
import logging
import time
from datetime import datetime

import requests
from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)

TOKEN_CACHE_KEY = "payments:daraja:access_token"
TOKEN_TTL_SECONDS = 3300
REQUEST_RETRY_ATTEMPTS = 2


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


def _request_with_retry(method, url, **kwargs):
    last_exception = None
    for attempt in range(1, REQUEST_RETRY_ATTEMPTS + 1):
        try:
            return requests.request(method, url, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exception = exc
            logger.warning(
                "Daraja %s request failed on attempt %s/%s: %s",
                method.upper(),
                attempt,
                REQUEST_RETRY_ATTEMPTS,
                exc,
            )
            if attempt < REQUEST_RETRY_ATTEMPTS:
                time.sleep(attempt)
    raise DarajaError("Daraja provider request timed out. Payment is awaiting provider confirmation.") from last_exception


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
    cached_token = cache.get(TOKEN_CACHE_KEY)
    if cached_token:
        return cached_token

    auth = base64.b64encode(
        f"{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}".encode("utf-8")
    ).decode("utf-8")
    response = _request_with_retry(
        "get",
        f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {auth}"},
        timeout=(5, 12),
    )
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
    cache.set(TOKEN_CACHE_KEY, token, TOKEN_TTL_SECONDS)
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
    response = _request_with_retry(
        "post",
        f"{_base_url()}/mpesa/stkpush/v1/processrequest",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(5, 15),
    )
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
    metadata_items = ((callback.get("CallbackMetadata") or {}).get("Item") or [])
    extracted = {}
    for item in metadata_items:
        name = item.get("Name")
        if name:
            extracted[name] = item.get("Value")
    return extracted
