import logging

import requests
from django.conf import settings


logger = logging.getLogger(__name__)


class PaystackError(Exception):
    """Raised when Paystack initialization or verification fails."""


def paystack_ready():
    return bool(
        settings.PAYSTACK_ENABLED
        and settings.PAYSTACK_SECRET_KEY
        and settings.PAYSTACK_PUBLIC_KEY
    )


def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def initialize_transaction(payment, callback_url):
    amount_subunit = int(payment.amount * 100)
    buyer_email = (
        payment.buyer.email
        if payment.buyer and payment.buyer.email
        else f"{payment.internal_reference.lower()}@example.com"
    )
    payload = {
        "amount": amount_subunit,
        "email": buyer_email,
        "currency": settings.PAYSTACK_CURRENCY,
        "reference": payment.internal_reference,
        "callback_url": callback_url,
        "channels": ["mobile_money"],
        "metadata": {
            "payment_id": payment.pk,
            "plot_id": payment.plot_id,
            "transaction_type": payment.transaction_type,
            "category": payment.category,
            "phone_number": payment.phone_number,
            "custom_fields": [
                {
                    "display_name": "Phone Number",
                    "variable_name": "phone_number",
                    "value": payment.phone_number,
                }
            ],
        },
    }
    response = requests.post(
        f"{settings.PAYSTACK_BASE_URL}/transaction/initialize",
        json=payload,
        headers=_headers(),
        timeout=20,
    )
    data = response.json()
    if response.status_code >= 400 or not data.get("status"):
        message = data.get("message") or "Unable to initialize Paystack transaction."
        logger.error("Paystack initialize failed: %s", message)
        raise PaystackError(message)
    return data["data"]


def verify_transaction(reference):
    response = requests.get(
        f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}",
        headers=_headers(),
        timeout=20,
    )
    data = response.json()
    if response.status_code >= 400 or not data.get("status"):
        message = data.get("message") or "Unable to verify Paystack transaction."
        logger.error("Paystack verify failed: %s", message)
        raise PaystackError(message)
    return data["data"]
