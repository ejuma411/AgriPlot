"""
M-Pesa Callback Handler
Receives webhook notifications from Daraja via ngrok
"""

import json
import logging
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .wallet_service import WalletService

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def mpesa_wallet_callback(request):
    """
    Handle M-Pesa STK Push callback from Daraja.
    This endpoint is called by Safaricom after user completes/fails payment.
    
    ngrok URL: https://your-ngrok.ngrok.io/payments/mpesa/wallet-callback/
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
            for item in items:
                name = item.get('Name')
                value = item.get('Value')
                
                if name == 'Amount':
                    amount = Decimal(str(value))
                elif name == 'MpesaReceiptNumber':
                    mpesa_receipt = value
            
            if not amount or not mpesa_receipt:
                logger.error(f"Missing amount or receipt in callback: {callback_metadata}")
                return JsonResponse(
                    {'ResultCode': 1, 'ResultDesc': 'Missing transaction details'},
                    status=200
                )
            
            # Complete the deposit
            result = WalletService.complete_deposit(
                checkout_request_id=checkout_request_id,
                mpesa_receipt=mpesa_receipt,
                amount=amount
            )
            
            if result.get('success'):
                logger.info(f"Wallet deposit completed: {mpesa_receipt} - {amount}")
                return JsonResponse(
                    {'ResultCode': 0, 'ResultDesc': 'Success'},
                    status=200
                )
            else:
                logger.error(f"Failed to complete deposit: {result.get('message')}")
                return JsonResponse(
                    {'ResultCode': 1, 'ResultDesc': result.get('message', 'Processing failed')},
                    status=200
                )
        
        else:
            # Payment failed
            logger.warning(f"M-Pesa payment failed: {result_code} - {result_desc}")
            
            # Find and mark the deposit as failed
            try:
                from .models import WalletDepositRequest
                deposit = WalletDepositRequest.objects.get(
                    provider_reference=checkout_request_id,
                    status='processing'
                )
                deposit.status = 'failed'
                deposit.provider_response = {
                    **(deposit.provider_response or {}),
                    'failure_reason': result_desc,
                    'failure_code': result_code
                }
                deposit.save(update_fields=['status', 'provider_response'])
                
                # Also fail the temporary payment request
                payment_id = (deposit.provider_response or {}).get('payment_id')
                if payment_id:
                    from .models import PaymentRequest
                    try:
                        temp_payment = PaymentRequest.objects.get(pk=payment_id)
                        temp_payment.status = PaymentRequest.Status.FAILED
                        temp_payment.save(update_fields=['status', 'updated_at'])
                    except PaymentRequest.DoesNotExist:
                        pass
                        
            except WalletDepositRequest.DoesNotExist:
                logger.error(f"Deposit request not found for checkout: {checkout_request_id}")
            
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
    Handle M-Pesa B2C (Business to Customer) callback for withdrawals.
    Called when funds are sent from AgriPlot to user's M-Pesa.
    """
    try:
        callback_data = json.loads(request.body)
        logger.info(f"M-Pesa B2C callback received: {json.dumps(callback_data, indent=2)}")
        
        # Extract result from callback
        result = callback_data.get('Result', {})
        result_code = result.get('ResultCode')
        result_desc = result.get('ResultDesc', '')
        conversation_id = result.get('ConversationID')
        
        if result_code == 0:
            # Withdrawal successful
            # Find the withdrawal request by conversation ID or transaction ID
            from .models import WalletWithdrawalRequest
            
            withdrawal = WalletWithdrawalRequest.objects.filter(
                provider_reference=conversation_id,
                status='processing'
            ).first()
            
            if withdrawal:
                # Mark withdrawal as completed
                withdrawal.status = 'completed'
                withdrawal.completed_at = timezone.now()
                withdrawal.provider_response = callback_data
                
                # Mark the transaction as success
                if withdrawal.wallet_transaction:
                    withdrawal.wallet_transaction.status = 'SUCCESS'
                    withdrawal.wallet_transaction.completed_at = timezone.now()
                    withdrawal.wallet_transaction.save(update_fields=['status', 'completed_at'])
                
                withdrawal.save(update_fields=['status', 'completed_at', 'provider_response'])
                
                logger.info(f"B2C withdrawal completed: {withdrawal.reference}")
            else:
                logger.warning(f"Withdrawal request not found for conversation: {conversation_id}")
        
        else:
            # Withdrawal failed
            logger.error(f"B2C withdrawal failed: {result_code} - {result_desc}")
            
            # Find and mark withdrawal as failed
            from .models import WalletWithdrawalRequest
            
            withdrawal = WalletWithdrawalRequest.objects.filter(
                provider_reference=conversation_id,
                status='processing'
            ).first()
            
            if withdrawal:
                withdrawal.status = 'failed'
                withdrawal.rejection_reason = result_desc
                withdrawal.provider_response = callback_data
                withdrawal.save(update_fields=['status', 'rejection_reason', 'provider_response'])
                
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
