import base64
import logging
import time
from datetime import datetime

import requests
# from cryptography.hazmat.primitives.asymmetric import padding  # type: ignore
# from cryptography.hazmat.primitives.serialization import load_pem_public_key  # type: ignore
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from payments.models import PaymentRequest


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

    base_url = _base_url()
    auth = base64.b64encode(
        f"{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}".encode("utf-8")
    ).decode("utf-8")
    response = _request_with_retry(
        "get",
        f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
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
        if response.status_code in {401, 403} and message == "Unable to authenticate with Daraja.":
            env_hint = (
                "sandbox" if settings.MPESA_ENVIRONMENT != "production" else "production"
            )
            message = (
                f"Daraja rejected the {env_hint} access token request (HTTP {response.status_code}). "
                "Check that the M-Pesa consumer key and secret match the selected Daraja environment."
            )
        logger.error(
            "Daraja auth failed (env=%s, url=%s, status=%s): %s",
            settings.MPESA_ENVIRONMENT,
            base_url,
            response.status_code,
            message,
        )
        raise DarajaError(message)
    cache.set(TOKEN_CACHE_KEY, token, TOKEN_TTL_SECONDS)
    return token


def initiate_stk_push(payment, callback_url):
    """
    Initiate STK push for M-Pesa payment.
    Funds go directly to platform's escrow account.
    
    Args:
        payment: PaymentRequest instance
        callback_url: URL to receive payment confirmation
        
    Returns:
        dict: STK push response with MerchantRequestID and CheckoutRequestID
    """
    phone_number = _format_phone(payment.phone_number)
    timestamp = _timestamp()
    token = _access_token()
    
    # Determine transaction type based on payment category
    transaction_type = settings.MPESA_TRANSACTION_TYPE  # Default: "CustomerPayBillOnline"
    
    # For stamp duty, we don't collect via M-Pesa - handled by KRA
    if payment.category == PaymentRequest.Category.STAMP_DUTY:
        raise DarajaError(
            "Stamp duty must be paid directly to KRA via iTax, not via M-Pesa. "
            "Please use the KRA iTax platform to pay stamp duty."
        )
    
    payload = {
        "BusinessShortCode": settings.MPESA_BUSINESS_SHORTCODE,
        "Password": _password(timestamp),
        "Timestamp": timestamp,
        "TransactionType": transaction_type,
        "Amount": int(payment.amount),
        "PartyA": phone_number,
        "PartyB": settings.MPESA_BUSINESS_SHORTCODE,
        "PhoneNumber": phone_number,
        "CallBackURL": callback_url,
        "AccountReference": payment.internal_reference[:12],
        "TransactionDesc": (payment.title or payment.internal_reference)[:182],
    }
    
    logger.info(
        f"Initiating STK push for {payment.internal_reference}: "
        f"Amount: KES {payment.amount:,.2f}, Phone: {phone_number}"
    )
    
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
        logger.error(f"Daraja STK push failed for {payment.internal_reference}: {message}")
        raise DarajaError(message)
    
    logger.info(f"STK push initiated successfully for {payment.internal_reference}")
    return data


def extract_callback_metadata(callback):
    """Extract metadata from M-Pesa callback"""
    metadata_items = ((callback.get("CallbackMetadata") or {}).get("Item") or [])
    extracted = {}
    for item in metadata_items:
        name = item.get("Name")
        if name:
            extracted[name] = item.get("Value")
    return extracted


def process_stk_callback(callback_data, payment):
    """
    Process STK push callback and update payment status.
    Records escrow hold when payment is successful.
    """
    from payments.models import PaymentRequest
    
    result_code = callback_data.get("Body", {}).get("stkCallback", {}).get("ResultCode")
    result_desc = callback_data.get("Body", {}).get("stkCallback", {}).get("ResultDesc")
    merchant_request_id = callback_data.get("Body", {}).get("stkCallback", {}).get("MerchantRequestID")
    checkout_request_id = callback_data.get("Body", {}).get("stkCallback", {}).get("CheckoutRequestID")
    
    logger.info(
        f"Processing STK callback for {payment.internal_reference}: "
        f"ResultCode={result_code}, ResultDesc={result_desc}"
    )
    
    # Update payment with provider references
    payment.provider_reference = checkout_request_id or merchant_request_id
    payment.save(update_fields=['provider_reference', 'updated_at'])
    
    if result_code == "0":  # Success
        # Extract payment details from callback
        metadata = extract_callback_metadata(callback_data.get("Body", {}).get("stkCallback", {}))
        
        mpesa_receipt = metadata.get("mpesaReceiptNumber")
        amount = metadata.get("Amount")
        
        # Update metadata with M-Pesa details
        payment_metadata = dict(payment.metadata or {})
        payment_metadata['mpesa_receipt'] = mpesa_receipt
        payment_metadata['mpesa_checkout_request_id'] = checkout_request_id
        payment_metadata['mpesa_merchant_request_id'] = merchant_request_id
        payment_metadata['mpesa_paid_at'] = timezone.now().isoformat()
        payment.metadata = payment_metadata
        
        # Update payment status
        payment.status = PaymentRequest.Status.PAID
        payment.paid_at = timezone.now()
        payment.save(update_fields=['status', 'paid_at', 'metadata', 'updated_at'])
        
        logger.info(
            f"Payment {payment.internal_reference} successful: "
            f"Receipt: {mpesa_receipt}, Amount: KES {amount:,.2f}"
        )
        
        # Record escrow hold (funds now in platform escrow account)
        _record_escrow_hold(payment, amount, mpesa_receipt)
        
        return {
            'success': True,
            'mpesa_receipt': mpesa_receipt,
            'amount': amount
        }
    
    elif result_code == "1037":  # User cancelled
        payment.status = PaymentRequest.Status.CANCELLED
        payment.save(update_fields=['status', 'updated_at'])
        logger.info(f"Payment {payment.internal_reference} cancelled by user")
        return {'success': False, 'error': 'User cancelled the transaction'}
    
    else:  # Other failure
        payment.status = PaymentRequest.Status.FAILED
        payment_metadata = dict(payment.metadata or {})
        payment_metadata['mpesa_failure_reason'] = result_desc
        payment.metadata = payment_metadata
        payment.save(update_fields=['status', 'metadata', 'updated_at'])
        
        logger.error(
            f"Payment {payment.internal_reference} failed: "
            f"ResultCode={result_code}, ResultDesc={result_desc}"
        )
        return {'success': False, 'error': result_desc}


def _record_escrow_hold(payment, amount, mpesa_receipt):
    """
    Record that funds are now held in escrow after successful M-Pesa payment.
    This is a bookkeeping function to track escrow holdings.
    """
    from payments.models import PaymentDisbursement
    
    logger.info(
        f"Recording escrow hold for {payment.internal_reference}: "
        f"KES {amount:,.2f} via M-Pesa receipt {mpesa_receipt}"
    )
    
    # Determine which escrow record to update based on payment category
    if payment.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
        # 10% deposit
        disbursement = payment.disbursements.filter(code="deposit_held").first()
        if disbursement:
            disbursement.status = PaymentDisbursement.Status.HELD
            disbursement.metadata = {
                'mpesa_receipt': mpesa_receipt,
                'paid_at': timezone.now().isoformat()
            }
            disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
            
            # Update payment metadata
            payment_metadata = dict(payment.metadata or {})
            payment_metadata['deposit_paid'] = True
            payment_metadata['deposit_paid_at'] = timezone.now().isoformat()
            payment.metadata = payment_metadata
            payment.save(update_fields=['metadata', 'updated_at'])
    
    elif payment.category == PaymentRequest.Category.COMPLETION_BALANCE:
        # 90% balance
        disbursement = payment.disbursements.filter(code="balance_held").first()
        if disbursement:
            disbursement.status = PaymentDisbursement.Status.HELD
            disbursement.metadata = {
                'mpesa_receipt': mpesa_receipt,
                'paid_at': timezone.now().isoformat()
            }
            disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
            
            # Update payment metadata
            payment_metadata = dict(payment.metadata or {})
            payment_metadata['balance_paid'] = True
            payment_metadata['balance_paid_at'] = timezone.now().isoformat()
            payment.metadata = payment_metadata
            payment.save(update_fields=['metadata', 'updated_at'])
    
    elif payment.category == PaymentRequest.Category.COMMITMENT_FEE:
        # Commitment fee - not held in escrow (immediate expense)
        disbursement = payment.disbursements.filter(code="commitment_fee").first()
        if disbursement:
            disbursement.status = PaymentDisbursement.Status.RELEASED
            disbursement.released_at = timezone.now()
            disbursement.metadata = {
                'mpesa_receipt': mpesa_receipt,
                'paid_at': timezone.now().isoformat()
            }
            disbursement.save(update_fields=['status', 'released_at', 'metadata', 'updated_at'])
    
    # Send notification based on payment type
    from notifications.notification_service import NotificationService
    
    if payment.buyer:
        NotificationService.create_notification(
            user=payment.buyer,
            notification_type="payment_received",
            title=f"Payment Received - {payment.title}",
            message=f"Your payment of KES {amount:,.2f} has been received and is being held securely."
        )
    
    if payment.seller and payment.category in [
        PaymentRequest.Category.AGREEMENT_DEPOSIT,
        PaymentRequest.Category.COMPLETION_BALANCE
    ]:
        NotificationService.create_notification(
            user=payment.seller,
            notification_type="escrow_funds_received",
            title=f"Funds Received in Escrow - {payment.title}",
            message=(
                f"The buyer has paid KES {amount:,.2f} into escrow for {payment.title}. "
                f"Funds will be released after registration is complete."
            )
        )


def query_stk_status(checkout_request_id):
    """
    Query the status of an STK push transaction.
    Useful for polling when callback is delayed.
    """
    timestamp = _timestamp()
    token = _access_token()
    
    payload = {
        "BusinessShortCode": settings.MPESA_BUSINESS_SHORTCODE,
        "Password": _password(timestamp),
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id
    }
    
    response = _request_with_retry(
        "post",
        f"{_base_url()}/mpesa/stkpushquery/v1/query",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(5, 15),
    )
    
    data = _safe_json(response)
    
    if response.status_code >= 400 or data.get("errorCode"):
        logger.error(f"STK status query failed: {data}")
        return {'success': False, 'error': data.get('errorMessage', 'Unknown error')}
    
    return {
        'success': True,
        'result_code': data.get('ResultCode'),
        'result_desc': data.get('ResultDesc'),
        'amount': data.get('Amount'),
        'mpesa_receipt': data.get('MpesaReceiptNumber')
    }


def reverse_transaction(transaction_id, amount):
    """
    Reverse a completed M-Pesa transaction (refund).
    Only possible within a limited time window.
    """
    timestamp = _timestamp()
    token = _access_token()
    
    payload = {
        "Initiator": settings.MPESA_INITIATOR_NAME,
        "SecurityCredential": _get_security_credential(),
        "CommandID": "TransactionReversal",
        "TransactionID": transaction_id,
        "Amount": int(amount),
        "ReceiverParty": settings.MPESA_BUSINESS_SHORTCODE,
        "RecieverIdentifierType": "11",
        "ResultURL": settings.MPESA_REVERSAL_RESULT_URL,
        "QueueTimeOutURL": settings.MPESA_REVERSAL_TIMEOUT_URL,
        "Remarks": "Payment reversal requested by customer",
        "Occasion": "Transaction reversal"
    }
    
    response = _request_with_retry(
        "post",
        f"{_base_url()}/mpesa/reversal/v1/request",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(5, 30),
    )
    
    data = _safe_json(response)
    
    if response.status_code >= 400 or data.get("errorCode"):
        logger.error(f"Transaction reversal failed: {data}")
        return {'success': False, 'error': data.get('errorMessage', 'Reversal failed')}
    
    return {
        'success': True,
        'conversation_id': data.get('ConversationID'),
        'originator_conversation_id': data.get('OriginatorConversationID')
    }


def _get_security_credential():
    """
    Get security credential for reversal/refund operations.
    This requires the M-Pesa public certificate.
    """
    # This is a placeholder - implement based on M-Pesa documentation
    # You need to encrypt the initiator password using M-Pesa's public certificate
    
    # Load M-Pesa public certificate
    # cert_path = settings.MPESA_PUBLIC_CERT_PATH
    # with open(cert_path, 'rb') as cert_file:
    #     cert_data = cert_file.read()
    
    # public_key = load_pem_public_key(cert_data)
    # encrypted = public_key.encrypt(
    #     settings.MPESA_INITIATOR_PASSWORD.encode(),
    #     _Padding.PKCS1v15()
    # )
    
    # return base64.b64encode(encrypted).decode()