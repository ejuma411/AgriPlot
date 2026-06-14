"""
Jenga Webhook Handlers for C2B, B2C, and B2B callbacks
Integrates with AgriPlot's platform escrow model.
"""

import json
import logging
import base64
from decimal import Decimal

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction

from .jenga_service import JengaService
from .wallet_service import WalletService
from .models import (
    WalletTransaction, 
    WalletDepositRequest, 
    WalletWithdrawalRequest, 
    PaymentRequest,
    PaymentDisbursement,
    PaymentClosingStep
)

logger = logging.getLogger(__name__)

jenga_service = JengaService()


def verify_jenga_basic_auth(request):
    """
    Verify HTTP Basic Authentication for Jenga webhook.
    Uses credentials configured in Jenga IPN settings.
    """
    expected_username = getattr(settings, 'JENGA_WEBHOOK_USERNAME', '')
    expected_password = getattr(settings, 'JENGA_WEBHOOK_PASSWORD', '')
    
    if not expected_username and not expected_password:
        logger.warning("No Jenga webhook credentials configured - skipping auth check (sandbox only)")
        return True
    
    auth_header = request.headers.get('Authorization', '')
    
    if not auth_header:
        logger.warning("No Authorization header in Jenga webhook")
        return False
    
    if not auth_header.startswith('Basic '):
        logger.warning(f"Invalid auth header format: {auth_header[:20]}...")
        return False
    
    try:
        encoded = auth_header[6:]
        decoded = base64.b64decode(encoded).decode('utf-8')
        username, password = decoded.split(':', 1)
    except Exception as e:
        logger.error(f"Failed to decode Basic Auth: {e}")
        return False
    
    if username == expected_username and password == expected_password:
        logger.info("Jenga webhook authenticated successfully")
        return True
    
    logger.warning(f"Jenga webhook auth failed for user: {username}")
    return False


def _record_escrow_hold_from_jenga(payment, amount, transaction_id, source):
    """
    Record escrow hold when payment is received via Jenga.
    Updates payment metadata and disbursement records.
    """
    # Determine which escrow record to update based on payment category
    if payment.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
        # 10% deposit
        disbursement = payment.disbursements.filter(code="deposit_held").first()
        if disbursement:
            disbursement.status = PaymentDisbursement.Status.HELD
            disbursement.metadata = {
                'jenga_transaction_id': transaction_id,
                'source': source,
                'paid_at': timezone.now().isoformat()
            }
            disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
            
            # Update payment metadata
            payment_metadata = dict(payment.metadata or {})
            payment_metadata['deposit_paid'] = True
            payment_metadata['deposit_paid_at'] = timezone.now().isoformat()
            payment_metadata['deposit_source'] = source
            payment.metadata = payment_metadata
            payment.save(update_fields=['metadata', 'updated_at'])
            
            logger.info(f"Deposit escrow hold recorded for {payment.internal_reference}: KES {amount:,.2f}")
    
    elif payment.category == PaymentRequest.Category.COMPLETION_BALANCE:
        # 90% balance
        disbursement = payment.disbursements.filter(code="balance_held").first()
        if disbursement:
            disbursement.status = PaymentDisbursement.Status.HELD
            disbursement.metadata = {
                'jenga_transaction_id': transaction_id,
                'source': source,
                'paid_at': timezone.now().isoformat()
            }
            disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
            
            # Update payment metadata
            payment_metadata = dict(payment.metadata or {})
            payment_metadata['balance_paid'] = True
            payment_metadata['balance_paid_at'] = timezone.now().isoformat()
            payment_metadata['balance_source'] = source
            payment.metadata = payment_metadata
            payment.save(update_fields=['metadata', 'updated_at'])
            
            logger.info(f"Balance escrow hold recorded for {payment.internal_reference}: KES {amount:,.2f}")


def _mark_payment_success(payment, amount, transaction_id, source):
    """Mark payment as successful and record escrow hold"""
    from django.utils import timezone
    
    # Update payment status
    payment.status = PaymentRequest.Status.PAID
    payment.paid_at = timezone.now()
    payment.provider_reference = transaction_id
    payment.save(update_fields=['status', 'paid_at', 'provider_reference', 'updated_at'])
    
    # Record escrow hold
    _record_escrow_hold_from_jenga(payment, amount, transaction_id, source)
    
    # Add event to payment history
    payment.add_event(
        "jenga_payment_received",
        f"Payment of KES {amount:,.2f} received via {source} and held in escrow. Transaction ID: {transaction_id}"
    )
    
    logger.info(f"Payment {payment.internal_reference} marked as paid and held in escrow")


@csrf_exempt
@require_http_methods(["POST"])
def jenga_c2b_webhook(request):
    """
    Handle C2B (Customer to Business) webhook from Jenga.
    Called when a customer completes a deposit payment.
    
    Funds go directly to platform escrow account.
    """
    if not verify_jenga_basic_auth(request):
        logger.error("Jenga C2B webhook authentication failed")
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
    
    try:
        payload = json.loads(request.body)
        logger.info(f"Received Jenga C2B webhook: {payload}")
        
        transaction_id = payload.get('transactionId')
        checkout_id = payload.get('checkoutId')
        status = payload.get('status')
        amount = Decimal(payload.get('amount', 0))
        reference = payload.get('reference')
        mpesa_receipt = payload.get('mpesaReceiptNumber', '')
        customer_phone = payload.get('customerPhoneNumber', '')
        
        if status == 'SUCCESS':
            with transaction.atomic():
                # First try to find by reference (payment request internal reference)
                payment = PaymentRequest.objects.select_for_update().filter(
                    internal_reference=reference,
                    status=PaymentRequest.Status.PENDING
                ).first()
                
                # If not found, try deposit request
                deposit_request = None
                if not payment:
                    deposit_request = WalletDepositRequest.objects.select_for_update().filter(
                        reference=reference,
                        status__in=['pending', 'processing']
                    ).first()
                
                if not payment and not deposit_request:
                    logger.warning(f"No payment or deposit request found for reference: {reference}")
                    return JsonResponse({'status': 'ok', 'message': 'Request not found'})
                
                # Handle Payment Request (direct payment for escrow)
                if payment:
                    # Prevent double processing
                    if payment.status != PaymentRequest.Status.PENDING:
                        return JsonResponse({'status': 'ok', 'message': 'Already processed'})
                    
                    # Mark payment as successful and record escrow hold
                    _mark_payment_success(payment, amount, transaction_id or checkout_id, 'Jenga C2B')
                    
                    # Update payment with M-Pesa receipt
                    metadata = dict(payment.metadata or {})
                    metadata['mpesa_receipt'] = mpesa_receipt
                    metadata['customer_phone'] = customer_phone
                    payment.metadata = metadata
                    payment.save(update_fields=['metadata', 'updated_at'])
                    
                    # Update plot status if this is a purchase transaction
                    if payment.transaction_type == PaymentRequest.TransactionType.PURCHASE and payment.plot:
                        payment.plot.market_status = 'reserved'
                        payment.plot.availability_notes = f"Reserved under purchase transaction {payment.internal_reference}"
                        payment.plot.save(update_fields=['market_status', 'availability_notes', 'updated_at'])
                        logger.info(f"Plot {payment.plot.id} marked as reserved after C2B deposit")
                    
                    logger.info(f"C2B payment completed and held in escrow: {reference} - KES {amount:,.2f}")
                    
                    # Send notifications
                    from notifications.notification_service import NotificationService
                    if payment.buyer:
                        NotificationService.create_notification(
                            user=payment.buyer,
                            notification_type="payment_received",
                            title=f"Payment Received - {payment.title}",
                            message=f"Your payment of KES {amount:,.2f} has been received and is being held securely in escrow."
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
                
                # Handle Wallet Deposit Request
                elif deposit_request:
                    if deposit_request.status == 'completed':
                        return JsonResponse({'status': 'ok', 'message': 'Already processed'})
                    
                    # Complete the deposit via wallet service
                    result = WalletService.complete_deposit(
                        checkout_request_id=checkout_id or transaction_id,
                        mpesa_receipt=mpesa_receipt or f"JENGA-{transaction_id}",
                        amount=amount
                    )
                    
                    if result.get('success'):
                        logger.info(f"Wallet deposit completed via C2B: {reference} - KES {amount:,.2f}")
                    else:
                        logger.error(f"Wallet deposit completion failed: {result}")
                        return JsonResponse({'status': 'error', 'message': result.get('message')}, status=500)
                
                return JsonResponse({'status': 'success', 'message': 'Payment processed and held in escrow'})
        
        elif status == 'FAILED':
            # Mark payment as failed if found
            payment = PaymentRequest.objects.filter(
                internal_reference=reference,
                status=PaymentRequest.Status.PENDING
            ).first()
            
            if payment:
                payment.status = PaymentRequest.Status.FAILED
                payment.metadata = {
                    **(payment.metadata or {}),
                    'jenga_failure_reason': payload.get('message', 'Unknown error'),
                    'jenga_failure_payload': payload
                }
                payment.save(update_fields=['status', 'metadata', 'updated_at'])
                logger.warning(f"C2B payment failed: {reference} - {payload.get('message')}")
            
            # Mark deposit request as failed
            deposit_request = WalletDepositRequest.objects.filter(
                reference=reference,
                status__in=['pending', 'processing']
            ).first()
            
            if deposit_request:
                deposit_request.status = 'failed'
                deposit_request.provider_response = payload
                deposit_request.save(update_fields=['status', 'provider_response', 'updated_at'])
            
            return JsonResponse({'status': 'ok', 'message': 'Payment failure recorded'})
        
        return JsonResponse({'status': 'ok', 'message': 'Webhook received'})
        
    except Exception as e:
        logger.exception(f"C2B webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def jenga_b2c_webhook(request):
    """
    Handle B2C (Business to Customer) webhook from Jenga.
    Called when a payout to an individual (seller) is completed or fails.
    
    This updates the disbursement status for escrow releases.
    """
    if not verify_jenga_basic_auth(request):
        logger.error("Jenga B2C webhook authentication failed")
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
    
    try:
        payload = json.loads(request.body)
        logger.info(f"Received Jenga B2C webhook: {payload}")
        
        transaction_id = payload.get('transactionId')
        reference = payload.get('reference')
        status = payload.get('status')
        amount = Decimal(payload.get('amount', 0))
        message = payload.get('message', '')
        
        with transaction.atomic():
            # First try to find by withdrawal request reference
            withdrawal = WalletWithdrawalRequest.objects.select_for_update().filter(
                reference=reference,
                status__in=['processing', 'approved']
            ).first()
            
            if withdrawal:
                if status == 'SUCCESS':
                    withdrawal.status = 'completed'
                    withdrawal.completed_at = timezone.now()
                    withdrawal.provider_reference = transaction_id
                    withdrawal.provider_response = payload
                    withdrawal.save(update_fields=['status', 'completed_at', 'provider_reference', 'provider_response', 'updated_at'])
                    
                    if withdrawal.wallet_transaction:
                        withdrawal.wallet_transaction.mark_success()
                    
                    logger.info(f"B2C payout completed (withdrawal): {reference} - KES {amount:,.2f}")
                    
                elif status == 'FAILED':
                    withdrawal.status = 'failed'
                    withdrawal.rejection_reason = message
                    withdrawal.provider_response = payload
                    withdrawal.save(update_fields=['status', 'rejection_reason', 'provider_response', 'updated_at'])
                    
                    if withdrawal.wallet_transaction:
                        withdrawal.wallet_transaction.status = 'FAILED'
                        withdrawal.wallet_transaction.notes = f"B2C failed: {message}"
                        withdrawal.wallet_transaction.save(update_fields=['status', 'notes', 'updated_at'])
                    
                    logger.error(f"B2C payout failed (withdrawal): {reference} - {message}")
                
                return JsonResponse({'status': 'ok', 'message': 'Withdrawal webhook processed'})
            
            # Try to find by disbursement reference (seller payout from escrow)
            disbursement = PaymentDisbursement.objects.select_for_update().filter(
                code='seller_disbursement',
                payment__internal_reference=reference
            ).first()
            
            if disbursement:
                payment = disbursement.payment
                
                if status == 'SUCCESS':
                    disbursement.status = PaymentDisbursement.Status.RELEASED
                    disbursement.released_at = timezone.now()
                    disbursement.provider_reference = transaction_id
                    disbursement.metadata = {
                        **(disbursement.metadata or {}),
                        'b2c_transaction_id': transaction_id,
                        'b2c_confirmed_at': timezone.now().isoformat()
                    }
                    disbursement.save(update_fields=['status', 'released_at', 'provider_reference', 'metadata', 'updated_at'])
                    
                    # Mark payment as fully disbursed if not already
                    if not payment.disbursed_at:
                        payment.disbursed_at = timezone.now()
                        payment.save(update_fields=['disbursed_at', 'updated_at'])
                    
                    logger.info(f"Seller disbursement confirmed for {payment.internal_reference}: KES {amount:,.2f}")
                    
                    # Send notification to seller
                    from notifications.notification_service import NotificationService
                    if payment.seller:
                        NotificationService.create_notification(
                            user=payment.seller,
                            notification_type="funds_disbursed",
                            title="Funds Disbursed to Your Account",
                            message=(
                                f"KES {amount:,.2f} from transaction {payment.title} has been sent to your account. "
                                f"Reference: {transaction_id}"
                            )
                        )
                    
                elif status == 'FAILED':
                    disbursement.status = PaymentDisbursement.Status.HELD
                    disbursement.metadata = {
                        **(disbursement.metadata or {}),
                        'b2c_failure_reason': message,
                        'b2c_failed_at': timezone.now().isoformat()
                    }
                    disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
                    
                    logger.error(f"Seller disbursement failed for {payment.internal_reference}: {message}")
                    
                    # Send alert to finance admins
                    from notifications.notification_service import NotificationService
                    from django.contrib.auth.models import Group
                    from .permissions import FINANCE_ADMIN_GROUP
                    
                    try:
                        finance_admins = Group.objects.get(name=FINANCE_ADMIN_GROUP).users.all()
                        for admin in finance_admins:
                            NotificationService.create_notification(
                                user=admin,
                                notification_type="disbursement_failed",
                                title="Disbursement Failed - Action Required",
                                message=(
                                    f"Disbursement for {payment.internal_reference} failed. "
                                    f"Amount: KES {amount:,.2f}. Reason: {message}. "
                                    f"Please investigate and retry."
                                )
                            )
                    except Group.DoesNotExist:
                        logger.warning(f"Finance Admin group not found for disbursement failure alert")
                
                return JsonResponse({'status': 'ok', 'message': 'Disbursement webhook processed'})
            
            logger.warning(f"No withdrawal or disbursement found for reference: {reference}")
            return JsonResponse({'status': 'ok', 'message': 'Reference not found'})
            
    except Exception as e:
        logger.exception(f"B2C webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def jenga_b2b_webhook(request):
    """
    Handle B2B (Business to Business) webhook from Jenga.
    Called when a corporate transfer is completed.
    
    This tracks platform fee transfers and professional service payments.
    """
    if not verify_jenga_basic_auth(request):
        logger.error("Jenga B2B webhook authentication failed")
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
    
    try:
        payload = json.loads(request.body)
        logger.info(f"Received Jenga B2B webhook: {payload}")
        
        transaction_id = payload.get('transactionId')
        reference = payload.get('reference')
        status = payload.get('status')
        amount = Decimal(payload.get('amount', 0))
        message = payload.get('message', '')
        
        with transaction.atomic():
            # Look for platform fee disbursement
            fee_disbursement = PaymentDisbursement.objects.select_for_update().filter(
                code='platform_fee',
                payment__internal_reference=reference
            ).first()
            
            if fee_disbursement:
                if status == 'SUCCESS':
                    fee_disbursement.status = PaymentDisbursement.Status.RELEASED
                    fee_disbursement.released_at = timezone.now()
                    fee_disbursement.provider_reference = transaction_id
                    fee_disbursement.metadata = {
                        **(fee_disbursement.metadata or {}),
                        'b2b_transaction_id': transaction_id,
                        'b2b_confirmed_at': timezone.now().isoformat()
                    }
                    fee_disbursement.save(update_fields=['status', 'released_at', 'provider_reference', 'metadata', 'updated_at'])
                    
                    logger.info(f"Platform fee transfer confirmed for {reference}: KES {amount:,.2f}")
                    
                elif status == 'FAILED':
                    fee_disbursement.status = PaymentDisbursement.Status.PLANNED
                    fee_disbursement.metadata = {
                        **(fee_disbursement.metadata or {}),
                        'b2b_failure_reason': message,
                        'b2b_failed_at': timezone.now().isoformat()
                    }
                    fee_disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
                    
                    logger.error(f"Platform fee transfer failed for {reference}: {message}")
                
                return JsonResponse({'status': 'ok', 'message': 'Fee transfer webhook processed'})
            
            # Look for bank transfer instruction (legacy)
            try:
                from .models import BankTransferInstruction
                instruction = BankTransferInstruction.objects.select_for_update().filter(
                    reference=reference
                ).first()
                
                if instruction:
                    if status == 'SUCCESS':
                        instruction.status = 'confirmed'
                        instruction.confirmed_at = timezone.now()
                        instruction.bank_reference = transaction_id
                        instruction.bank_response = payload
                        instruction.save(update_fields=['status', 'confirmed_at', 'bank_reference', 'bank_response', 'updated_at'])
                        
                        logger.info(f"B2B transfer completed: {reference} - KES {amount:,.2f}")
                        
                    elif status == 'FAILED':
                        instruction.status = 'failed'
                        instruction.notes = f"Transfer failed: {message}"
                        instruction.bank_response = payload
                        instruction.save(update_fields=['status', 'notes', 'bank_response', 'updated_at'])
                        
                        logger.error(f"B2B transfer failed: {reference} - {message}")
                    
                    return JsonResponse({'status': 'ok', 'message': 'Transfer webhook processed'})
            
            except ImportError:
                pass
            
            logger.warning(f"No fee disbursement or instruction found for reference: {reference}")
            return JsonResponse({'status': 'ok', 'message': 'Reference not found'})
            
    except Exception as e:
        logger.exception(f"B2B webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def jenga_escrow_webhook(request):
    """
    Special webhook for escrow-specific events.
    Handles escrow holds and releases via Jenga.
    """
    if not verify_jenga_basic_auth(request):
        logger.error("Jenga escrow webhook authentication failed")
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
    
    try:
        payload = json.loads(request.body)
        logger.info(f"Received Jenga escrow webhook: {payload}")
        
        event_type = payload.get('eventType')
        reference = payload.get('reference')
        status = payload.get('status')
        amount = Decimal(payload.get('amount', 0))
        
        if event_type == 'ESCROW_HELD':
            # Funds have been placed in escrow
            with transaction.atomic():
                payment = PaymentRequest.objects.select_for_update().filter(
                    internal_reference=reference
                ).first()
                
                if payment:
                    payment_metadata = dict(payment.metadata or {})
                    payment_metadata['escrow_held_at'] = timezone.now().isoformat()
                    payment_metadata['escrow_held_amount'] = str(amount)
                    payment_metadata['escrow_held_by'] = 'Jenga'
                    payment.metadata = payment_metadata
                    payment.save(update_fields=['metadata', 'updated_at'])
                    
                    logger.info(f"Escrow hold confirmed for {reference}: KES {amount:,.2f}")
                    
                    return JsonResponse({'status': 'ok', 'message': 'Escrow hold recorded'})
        
        elif event_type == 'ESCROW_RELEASED':
            # Funds have been released from escrow to seller
            with transaction.atomic():
                payment = PaymentRequest.objects.select_for_update().filter(
                    internal_reference=reference
                ).first()
                
                if payment:
                    payment_metadata = dict(payment.metadata or {})
                    payment_metadata['escrow_released_at'] = timezone.now().isoformat()
                    payment_metadata['escrow_released_amount'] = str(amount)
                    payment.metadata = payment_metadata
                    
                    if not payment.disbursed_at:
                        payment.disbursed_at = timezone.now()
                    
                    payment.save(update_fields=['metadata', 'disbursed_at', 'updated_at'])
                    
                    logger.info(f"Escrow released for {reference}: KES {amount:,.2f}")
                    
                    return JsonResponse({'status': 'ok', 'message': 'Escrow release recorded'})
        
        return JsonResponse({'status': 'ok', 'message': 'Webhook received'})
        
    except Exception as e:
        logger.exception(f"Escrow webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)