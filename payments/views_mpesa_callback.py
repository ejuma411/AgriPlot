"""
M-Pesa Callback Handler
Receives webhook notifications from Daraja via ngrok
Integrates with AgriPlot's platform escrow model.
"""

import json
import logging
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction

from .wallet_service import WalletService
from .models import PaymentRequest, PaymentDisbursement, WalletDepositRequest

logger = logging.getLogger(__name__)


def _record_escrow_hold_from_mpesa(payment, amount, mpesa_receipt, checkout_request_id):
    """
    Record escrow hold when payment is received via M-Pesa.
    Updates payment metadata and disbursement records.
    """
    # Determine which escrow record to update based on payment category
    if payment.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
        # 10% deposit
        disbursement = payment.disbursements.filter(code="deposit_held").first()
        if disbursement:
            disbursement.status = PaymentDisbursement.Status.HELD
            disbursement.metadata = {
                'mpesa_receipt': mpesa_receipt,
                'checkout_request_id': checkout_request_id,
                'paid_at': timezone.now().isoformat()
            }
            disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
            
            # Update payment metadata
            payment_metadata = dict(payment.metadata or {})
            payment_metadata['deposit_paid'] = True
            payment_metadata['deposit_paid_at'] = timezone.now().isoformat()
            payment_metadata['deposit_mpesa_receipt'] = mpesa_receipt
            payment.metadata = payment_metadata
            payment.save(update_fields=['metadata', 'updated_at'])
            
            logger.info(f"Deposit escrow hold recorded for {payment.internal_reference}: KES {amount:,.2f}")
    
    elif payment.category == PaymentRequest.Category.COMPLETION_BALANCE:
        # 90% balance
        disbursement = payment.disbursements.filter(code="balance_held").first()
        if disbursement:
            disbursement.status = PaymentDisbursement.Status.HELD
            disbursement.metadata = {
                'mpesa_receipt': mpesa_receipt,
                'checkout_request_id': checkout_request_id,
                'paid_at': timezone.now().isoformat()
            }
            disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
            
            # Update payment metadata
            payment_metadata = dict(payment.metadata or {})
            payment_metadata['balance_paid'] = True
            payment_metadata['balance_paid_at'] = timezone.now().isoformat()
            payment_metadata['balance_mpesa_receipt'] = mpesa_receipt
            payment.metadata = payment_metadata
            payment.save(update_fields=['metadata', 'updated_at'])
            
            logger.info(f"Balance escrow hold recorded for {payment.internal_reference}: KES {amount:,.2f}")
    
    elif payment.category == PaymentRequest.Category.COMMITMENT_FEE:
        # Commitment fee - not held in escrow (immediate expense)
        disbursement = payment.disbursements.filter(code="commitment_fee").first()
        if disbursement:
            disbursement.status = PaymentDisbursement.Status.RELEASED
            disbursement.released_at = timezone.now()
            disbursement.metadata = {
                'mpesa_receipt': mpesa_receipt,
                'checkout_request_id': checkout_request_id,
                'paid_at': timezone.now().isoformat()
            }
            disbursement.save(update_fields=['status', 'released_at', 'metadata', 'updated_at'])
            logger.info(f"Commitment fee recorded for {payment.internal_reference}: KES {amount:,.2f}")


def _mark_payment_success(payment, amount, mpesa_receipt, checkout_request_id):
    """Mark payment as successful and record escrow hold"""
    # Update payment status
    payment.status = PaymentRequest.Status.PAID
    payment.paid_at = timezone.now()
    payment.provider_reference = mpesa_receipt or checkout_request_id
    payment.save(update_fields=['status', 'paid_at', 'provider_reference', 'updated_at'])
    
    # Record escrow hold
    _record_escrow_hold_from_mpesa(payment, amount, mpesa_receipt, checkout_request_id)
    
    # Add event to payment history
    payment.add_event(
        "mpesa_payment_received",
        f"Payment of KES {amount:,.2f} received via M-Pesa and held in escrow. Receipt: {mpesa_receipt}"
    )
    
    logger.info(f"Payment {payment.internal_reference} marked as paid and held in escrow")


def _send_escrow_notifications(payment, amount, mpesa_receipt):
    """Send notifications for escrow payments"""
    from notifications.notification_service import NotificationService
    
    # Notify buyer
    if payment.buyer:
        NotificationService.create_notification(
            user=payment.buyer,
            notification_type="payment_received",
            title=f"Payment Received - {payment.title}",
            message=(
                f"Your payment of KES {amount:,.2f} for {payment.title} has been received "
                f"and is being held securely in escrow. Receipt: {mpesa_receipt}"
            ),
            metadata={'payment_id': payment.id, 'amount': str(amount)}
        )
    
    # Notify seller for deposit/balance payments
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
                f"Funds will be released after registration is complete. Receipt: {mpesa_receipt}"
            ),
            metadata={'payment_id': payment.id, 'amount': str(amount)}
        )


@csrf_exempt
@require_http_methods(["POST"])
def mpesa_wallet_callback(request):
    """
    Handle M-Pesa STK Push callback from Daraja.
    This endpoint is called by Safaricom after user completes/fails payment.
    
    Funds go directly to platform escrow account for deposit/balance payments.
    """
    try:
        # Parse callback data
        callback_data = json.loads(request.body)
        logger.info(f"M-Pesa callback received: {json.dumps(callback_data, indent=2)}")
        
        # Extract body from callback
        body = callback_data.get('Body', {})
        stk_callback = body.get('stkCallback', {})
        
        # Get the checkout request ID (matches our initiate_deposit)
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        merchant_request_id = stk_callback.get('MerchantRequestID')
        
        # Get result code (0 = success)
        result_code = stk_callback.get('ResultCode')
        result_desc = stk_callback.get('ResultDesc', '')
        
        if result_code == 0:
            # Payment successful - extract transaction details
            callback_metadata = stk_callback.get('CallbackMetadata', {})
            items = callback_metadata.get('Item', [])
            
            # Extract amount and receipt from metadata
            amount = None
            mpesa_receipt = None
            phone_number = None
            
            for item in items:
                name = item.get('Name')
                value = item.get('Value')
                
                if name == 'Amount':
                    amount = Decimal(str(value))
                elif name == 'MpesaReceiptNumber':
                    mpesa_receipt = value
                elif name == 'PhoneNumber':
                    phone_number = value
            
            if not amount or not mpesa_receipt:
                logger.error(f"Missing amount or receipt in callback: {callback_metadata}")
                return JsonResponse(
                    {'ResultCode': 1, 'ResultDesc': 'Missing transaction details'},
                    status=200
                )
            
            with transaction.atomic():
                # First try to find payment request by checkout request ID
                payment = PaymentRequest.objects.select_for_update().filter(
                    provider_reference=checkout_request_id,
                    status=PaymentRequest.Status.PENDING
                ).first()
                
                # If not found, try by metadata
                if not payment:
                    payment = PaymentRequest.objects.select_for_update().filter(
                        metadata__daraja_checkout_request_id=checkout_request_id,
                        status=PaymentRequest.Status.PENDING
                    ).first()
                
                if payment:
                    # Check if this is a stamp duty payment (should not happen)
                    if payment.category == PaymentRequest.Category.STAMP_DUTY:
                        logger.error(f"Stamp duty payment attempted via M-Pesa for {payment.internal_reference} - This is not allowed")
                        payment.status = PaymentRequest.Status.FAILED
                        payment.metadata = {
                            **(payment.metadata or {}),
                            'mpesa_failure_reason': 'Stamp duty must be paid directly to KRA via iTax'
                        }
                        payment.save(update_fields=['status', 'metadata', 'updated_at'])
                        return JsonResponse(
                            {'ResultCode': 1, 'ResultDesc': 'Stamp duty must be paid to KRA directly'},
                            status=200
                        )
                    
                    # Mark payment as successful and record escrow hold
                    _mark_payment_success(payment, amount, mpesa_receipt, checkout_request_id)
                    
                    # Send notifications
                    _send_escrow_notifications(payment, amount, mpesa_receipt)
                    
                    # Update plot status if this is a purchase transaction
                    if payment.transaction_type == PaymentRequest.TransactionType.PURCHASE and payment.plot:
                        payment.plot.market_status = 'reserved'
                        payment.plot.availability_notes = f"Reserved under purchase transaction {payment.internal_reference}"
                        payment.plot.save(update_fields=['market_status', 'availability_notes', 'updated_at'])
                        logger.info(f"Plot {payment.plot.id} marked as reserved after M-Pesa deposit")
                    
                    logger.info(f"M-Pesa payment completed and held in escrow: {mpesa_receipt} - KES {amount:,.2f}")
                    
                    return JsonResponse(
                        {'ResultCode': 0, 'ResultDesc': 'Success'},
                        status=200
                    )
                
                # If no payment found, try wallet deposit
                deposit_result = WalletService.complete_deposit(
                    checkout_request_id=checkout_request_id,
                    mpesa_receipt=mpesa_receipt,
                    amount=amount
                )
                
                if deposit_result.get('success'):
                    logger.info(f"Wallet deposit completed: {mpesa_receipt} - KES {amount:,.2f}")
                    return JsonResponse(
                        {'ResultCode': 0, 'ResultDesc': 'Success'},
                        status=200
                    )
                else:
                    logger.error(f"Failed to complete deposit: {deposit_result.get('message')}")
                    return JsonResponse(
                        {'ResultCode': 1, 'ResultDesc': deposit_result.get('message', 'Processing failed')},
                        status=200
                    )
        
        else:
            # Payment failed
            logger.warning(f"M-Pesa payment failed: {result_code} - {result_desc}")
            
            with transaction.atomic():
                # Find and mark the payment as failed
                payment = PaymentRequest.objects.select_for_update().filter(
                    provider_reference=checkout_request_id,
                    status=PaymentRequest.Status.PENDING
                ).first()
                
                if not payment:
                    payment = PaymentRequest.objects.select_for_update().filter(
                        metadata__daraja_checkout_request_id=checkout_request_id,
                        status=PaymentRequest.Status.PENDING
                    ).first()
                
                if payment:
                    payment.status = PaymentRequest.Status.FAILED
                    payment.metadata = {
                        **(payment.metadata or {}),
                        'mpesa_failure_reason': result_desc,
                        'mpesa_failure_code': result_code,
                        'mpesa_failed_at': timezone.now().isoformat()
                    }
                    payment.save(update_fields=['status', 'metadata', 'updated_at'])
                    
                    payment.add_event(
                        "mpesa_payment_failed",
                        f"M-Pesa payment failed: {result_desc} (Code: {result_code})"
                    )
                    
                    logger.info(f"Payment {payment.internal_reference} marked as failed")
                
                # Find and mark deposit request as failed
                deposit = WalletDepositRequest.objects.select_for_update().filter(
                    provider_reference=checkout_request_id,
                    status__in=['pending', 'processing']
                ).first()
                
                if deposit:
                    deposit.status = 'failed'
                    deposit.provider_response = {
                        **(deposit.provider_response or {}),
                        'failure_reason': result_desc,
                        'failure_code': result_code
                    }
                    deposit.save(update_fields=['status', 'provider_response', 'updated_at'])
                    
                    # Also fail the temporary payment request
                    payment_id = (deposit.provider_response or {}).get('payment_id')
                    if payment_id:
                        try:
                            temp_payment = PaymentRequest.objects.select_for_update().get(pk=payment_id)
                            temp_payment.status = PaymentRequest.Status.FAILED
                            temp_payment.save(update_fields=['status', 'updated_at'])
                            logger.info(f"Temporary payment {temp_payment.internal_reference} marked as failed")
                        except PaymentRequest.DoesNotExist:
                            pass
            
            return JsonResponse(
                {'ResultCode': result_code, 'ResultDesc': result_desc},
                status=200
            )
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in callback: {e}")
        return JsonResponse(
            {'ResultCode': 1, 'ResultDesc': 'Invalid request format'},
            status=200
        )
    
    except Exception as e:
        logger.exception(f"Unexpected error processing M-Pesa callback: {e}")
        return JsonResponse(
            {'ResultCode': 1, 'ResultDesc': 'Internal server error'},
            status=200
        )


@csrf_exempt
@require_http_methods(["POST"])
def mpesa_b2c_callback(request):
    """
    Handle M-Pesa B2C (Business to Customer) callback for withdrawals and disbursements.
    Called when funds are sent from AgriPlot to user's M-Pesa.
    
    This handles:
    - Wallet withdrawals (user withdrawing to M-Pesa)
    - Escrow disbursements (seller receiving payment after registration)
    """
    try:
        callback_data = json.loads(request.body)
        logger.info(f"M-Pesa B2C callback received: {json.dumps(callback_data, indent=2)}")
        
        # Extract result from callback
        result = callback_data.get('Result', {})
        result_code = result.get('ResultCode')
        result_desc = result.get('ResultDesc', '')
        conversation_id = result.get('ConversationID')
        transaction_id = result.get('TransactionID')
        
        with transaction.atomic():
            if result_code == 0:
                # Withdrawal/Disbursement successful
                
                # First try to find withdrawal request
                from .models import WalletWithdrawalRequest
                
                withdrawal = WalletWithdrawalRequest.objects.select_for_update().filter(
                    provider_reference=conversation_id,
                    status__in=['processing', 'approved']
                ).first()
                
                if withdrawal:
                    withdrawal.status = 'completed'
                    withdrawal.completed_at = timezone.now()
                    withdrawal.provider_reference = transaction_id or conversation_id
                    withdrawal.provider_response = callback_data
                    
                    if withdrawal.wallet_transaction:
                        withdrawal.wallet_transaction.status = 'SUCCESS'
                        withdrawal.wallet_transaction.completed_at = timezone.now()
                        withdrawal.wallet_transaction.save(update_fields=['status', 'completed_at'])
                    
                    withdrawal.save(update_fields=['status', 'completed_at', 'provider_reference', 'provider_response', 'updated_at'])
                    
                    logger.info(f"B2C withdrawal completed: {withdrawal.reference} - Transaction: {transaction_id}")
                    
                    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Success'}, status=200)
                
                # Try to find disbursement (seller payout from escrow)
                disbursement = PaymentDisbursement.objects.select_for_update().filter(
                    code='seller_disbursement',
                    provider_reference__icontains=conversation_id
                ).first()
                
                if not disbursement:
                    # Try by metadata
                    for disb in PaymentDisbursement.objects.filter(code='seller_disbursement', status='READY'):
                        metadata = disb.metadata or {}
                        if metadata.get('b2c_conversation_id') == conversation_id:
                            disbursement = disb
                            break
                
                if disbursement:
                    payment = disbursement.payment
                    
                    disbursement.status = PaymentDisbursement.Status.RELEASED
                    disbursement.released_at = timezone.now()
                    disbursement.provider_reference = transaction_id or conversation_id
                    disbursement.metadata = {
                        **(disbursement.metadata or {}),
                        'b2c_conversation_id': conversation_id,
                        'b2c_transaction_id': transaction_id,
                        'b2c_confirmed_at': timezone.now().isoformat()
                    }
                    disbursement.save(update_fields=['status', 'released_at', 'provider_reference', 'metadata', 'updated_at'])
                    
                    # Mark payment as fully disbursed if not already
                    if not payment.disbursed_at:
                        payment.disbursed_at = timezone.now()
                        payment.save(update_fields=['disbursed_at', 'updated_at'])
                    
                    logger.info(f"Seller disbursement confirmed for {payment.internal_reference}: Transaction {transaction_id}")
                    
                    # Send notification to seller
                    from notifications.notification_service import NotificationService
                    if payment.seller:
                        NotificationService.create_notification(
                            user=payment.seller,
                            notification_type="funds_disbursed",
                            title="Funds Disbursed to Your M-Pesa",
                            message=(
                                f"KES {disbursement.amount:,.2f} from transaction {payment.title} has been sent to your M-Pesa. "
                                f"Transaction ID: {transaction_id}"
                            ),
                            metadata={'payment_id': payment.id, 'amount': str(disbursement.amount)}
                        )
                    
                    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Success'}, status=200)
                
                logger.warning(f"No withdrawal or disbursement found for conversation: {conversation_id}")
            
            else:
                # Withdrawal/Disbursement failed
                logger.error(f"B2C transaction failed: {result_code} - {result_desc}")
                
                # Find and mark withdrawal as failed
                from .models import WalletWithdrawalRequest
                
                withdrawal = WalletWithdrawalRequest.objects.select_for_update().filter(
                    provider_reference=conversation_id,
                    status__in=['processing', 'approved']
                ).first()
                
                if withdrawal:
                    withdrawal.status = 'failed'
                    withdrawal.rejection_reason = result_desc
                    withdrawal.provider_response = callback_data
                    withdrawal.save(update_fields=['status', 'rejection_reason', 'provider_response', 'updated_at'])
                    
                    # Refund the user if transaction was frozen
                    if withdrawal.wallet_transaction and withdrawal.wallet_transaction.status == 'FROZEN':
                        # Create a reversal transaction
                        from .models import WalletTransaction
                        refund_tx = WalletTransaction.objects.create(
                            wallet=withdrawal.wallet_transaction.wallet,
                            amount=withdrawal.amount,
                            type='CREDIT',
                            status='SUCCESS',
                            channel='REFUND',
                            reference=f"REF-{withdrawal.reference}",
                            description=f"Refund for failed withdrawal: {result_desc}",
                            metadata={'original_withdrawal': withdrawal.reference}
                        )
                        refund_tx.completed_at = timezone.now()
                        refund_tx.save(update_fields=['completed_at'])
                        
                        withdrawal.wallet_transaction.status = 'FAILED'
                        withdrawal.wallet_transaction.save(update_fields=['status'])
                    
                    logger.info(f"B2C withdrawal marked as failed: {withdrawal.reference}")
                    
                    # Notify user of failure
                    from notifications.notification_service import NotificationService
                    if withdrawal.user:
                        NotificationService.create_notification(
                            user=withdrawal.user,
                            notification_type="withdrawal_failed",
                            title="Withdrawal Failed",
                            message=(
                                f"Your withdrawal of KES {withdrawal.amount:,.2f} failed. "
                                f"Reason: {result_desc}. Funds have been returned to your wallet."
                            )
                        )
                
                # Find and mark disbursement as failed
                disbursement = PaymentDisbursement.objects.select_for_update().filter(
                    code='seller_disbursement',
                    status='READY'
                ).first()
                
                if disbursement:
                    disbursement.status = PaymentDisbursement.Status.HELD
                    disbursement.metadata = {
                        **(disbursement.metadata or {}),
                        'b2c_failure_reason': result_desc,
                        'b2c_failure_code': result_code,
                        'b2c_failed_at': timezone.now().isoformat()
                    }
                    disbursement.save(update_fields=['status', 'metadata', 'updated_at'])
                    
                    logger.error(f"Seller disbursement failed: {disbursement.payment.internal_reference} - {result_desc}")
                    
                    # Alert finance admins
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
                                    f"Disbursement for {disbursement.payment.internal_reference} failed. "
                                    f"Amount: KES {disbursement.amount:,.2f}. Reason: {result_desc}. "
                                    f"Please investigate and retry."
                                )
                            )
                    except Group.DoesNotExist:
                        logger.warning(f"Finance Admin group not found for disbursement failure alert")
        
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Success'}, status=200)
    
    except Exception as e:
        logger.exception(f"Error processing B2C callback: {e}")
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Internal error'}, status=200)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def test_callback(request):
    """
    Test endpoint to verify ngrok/callback URL is working.
    Use this to confirm your ngrok setup is correct.
    """
    logger.info(f"Test callback hit: {request.method} - {request.GET.dict()}")
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            logger.info(f"POST data: {data}")
        except:
            logger.info(f"Raw POST body: {request.body}")
    
    return JsonResponse({
        'status': 'ok',
        'message': 'Callback endpoint is working!',
        'method': request.method,
        'timestamp': str(timezone.now())
    })


@csrf_exempt
@require_http_methods(["POST"])
def mpesa_reversal_callback(request):
    """
    Handle M-Pesa reversal callback for refunds.
    Called when a reversal/refund is processed.
    """
    try:
        callback_data = json.loads(request.body)
        logger.info(f"M-Pesa reversal callback received: {json.dumps(callback_data, indent=2)}")
        
        result = callback_data.get('Result', {})
        result_code = result.get('ResultCode')
        result_desc = result.get('ResultDesc', '')
        transaction_id = result.get('TransactionID')
        original_transaction_id = result.get('OriginalTransactionID')
        
        if result_code == 0:
            logger.info(f"Reversal successful: {original_transaction_id} -> {transaction_id}")
            
            # Find the original transaction and mark as refunded
            payment = PaymentRequest.objects.filter(
                provider_reference=original_transaction_id,
                status=PaymentRequest.Status.PAID
            ).first()
            
            if payment:
                payment.status = PaymentRequest.Status.REFUNDED
                payment.metadata = {
                    **(payment.metadata or {}),
                    'reversal_transaction_id': transaction_id,
                    'reversed_at': timezone.now().isoformat(),
                    'reversal_reason': result_desc
                }
                payment.save(update_fields=['status', 'metadata', 'updated_at'])
                
                payment.add_event(
                    "payment_reversed",
                    f"Payment reversed. Reversal ID: {transaction_id}. Reason: {result_desc}"
                )
                
                logger.info(f"Payment {payment.internal_reference} marked as refunded")
        
        else:
            logger.error(f"Reversal failed: {result_code} - {result_desc}")
        
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Success'}, status=200)
        
    except Exception as e:
        logger.exception(f"Error processing reversal callback: {e}")
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Internal error'}, status=200)