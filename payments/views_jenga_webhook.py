"""
Jenga Webhook Handlers for C2B, B2C, and B2B callbacks
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
from .models import WalletTransaction, WalletDepositRequest, WalletWithdrawalRequest, PaymentRequest

logger = logging.getLogger(__name__)

jenga_service = JengaService()


def verify_jenga_basic_auth(request):
    """
    Verify HTTP Basic Authentication for Jenga webhook.
    Uses credentials configured in Jenga IPN settings.
    
    Credentials should match what you entered in Jenga's IPN form:
    Username: CB2
    Password: 6HrnAQmk/%?HMP6
    """
    # Get credentials from Django settings
    expected_username = getattr(settings, 'JENGA_WEBHOOK_USERNAME', '')
    expected_password = getattr(settings, 'JENGA_WEBHOOK_PASSWORD', '')
    
    # If no credentials configured, skip verification (sandbox only)
    if not expected_username and not expected_password:
        logger.warning("No Jenga webhook credentials configured - skipping auth check (sandbox only)")
        return True
    
    # Get Authorization header
    auth_header = request.headers.get('Authorization', '')
    
    if not auth_header:
        logger.warning("No Authorization header in Jenga webhook")
        return False
    
    # Check for Basic auth
    if not auth_header.startswith('Basic '):
        logger.warning(f"Invalid auth header format: {auth_header[:20]}...")
        return False
    
    # Decode Basic Auth credentials
    try:
        encoded = auth_header[6:]  # Remove 'Basic ' prefix
        decoded = base64.b64decode(encoded).decode('utf-8')
        username, password = decoded.split(':', 1)
    except Exception as e:
        logger.error(f"Failed to decode Basic Auth: {e}")
        return False
    
    # Verify credentials
    if username == expected_username and password == expected_password:
        logger.info("Jenga webhook authenticated successfully")
        return True
    
    logger.warning(f"Jenga webhook auth failed for user: {username}")
    return False


@csrf_exempt
@require_http_methods(["POST"])
def jenga_c2b_webhook(request):
    """
    Handle C2B (Customer to Business) webhook from Jenga.
    Called when a customer completes a deposit payment.
    
    This updates the user's wallet and marks the deposit as completed.
    """
    # Verify HTTP Basic Authentication
    if not verify_jenga_basic_auth(request):
        logger.error("Jenga C2B webhook authentication failed")
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
    
    try:
        payload = json.loads(request.body)
        logger.info(f"Received Jenga C2B webhook: {payload}")
        
        # Extract transaction details
        transaction_id = payload.get('transactionId')
        checkout_id = payload.get('checkoutId')
        status = payload.get('status')
        amount = Decimal(payload.get('amount', 0))
        reference = payload.get('reference')
        mpesa_receipt = payload.get('mpesaReceiptNumber', '')
        
        if status == 'SUCCESS':
            with transaction.atomic():
                # Find the deposit request by reference
                deposit_request = WalletDepositRequest.objects.select_for_update().filter(
                    reference=reference,
                    status__in=['pending', 'processing']
                ).first()
                
                if not deposit_request:
                    logger.warning(f"Deposit request not found for reference: {reference}")
                    return JsonResponse({'status': 'ok', 'message': 'Deposit request not found'})
                
                # Prevent double processing
                if deposit_request.status == 'completed':
                    return JsonResponse({'status': 'ok', 'message': 'Already processed'})
                
                # Complete the deposit via wallet service
                result = WalletService.complete_deposit(
                    checkout_request_id=checkout_id or transaction_id,
                    mpesa_receipt=mpesa_receipt or f"JENGA-{transaction_id}",
                    amount=amount
                )
                
                if result.get('success'):
                    logger.info(f"C2B deposit completed: {reference} - {amount}")
                    
                    # ============================================================
                    # UPDATE PLOT STATUS IF THIS DEPOSIT IS FOR A PAYMENT REQUEST
                    # ============================================================
                    if deposit_request and deposit_request.payment_request:
                        payment = deposit_request.payment_request
                        
                        if payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                            # Update plot status to "reserved"
                            if payment.plot:
                                payment.plot.market_status = 'reserved'
                                payment.plot.availability_notes = f"Reserved under purchase transaction {payment.internal_reference}"
                                payment.plot.save(update_fields=['market_status', 'availability_notes'])
                                logger.info(f"Plot {payment.plot.id} marked as reserved after deposit")
                                
                                # Add event to payment history
                                payment.add_event(
                                    "plot_reserved",
                                    f"Plot {payment.plot.title} marked as reserved after successful deposit of KES {amount:,.2f}"
                                )
                    
                    return JsonResponse({'status': 'success', 'message': 'Deposit processed'})
                else:
                    logger.error(f"Deposit completion failed: {result}")
                    return JsonResponse({'status': 'error', 'message': result.get('message')}, status=500)
        
        elif status == 'FAILED':
            # Mark deposit as failed
            deposit_request = WalletDepositRequest.objects.filter(
                reference=reference,
                status__in=['pending', 'processing']
            ).first()
            
            if deposit_request:
                deposit_request.status = 'failed'
                deposit_request.provider_response = payload
                deposit_request.save(update_fields=['status', 'provider_response', 'updated_at'])
            
            logger.warning(f"C2B payment failed: {reference} - {payload.get('message')}")
            return JsonResponse({'status': 'ok', 'message': 'Payment failed recorded'})
        
        return JsonResponse({'status': 'ok', 'message': 'Webhook received'})
        
    except Exception as e:
        logger.exception(f"C2B webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def jenga_b2c_webhook(request):
    """
    Handle B2C (Business to Customer) webhook from Jenga.
    Called when a payout to an individual is completed or fails.
    
    This updates the withdrawal request status.
    """
    # Verify HTTP Basic Authentication
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
            # Find the withdrawal request
            withdrawal = WalletWithdrawalRequest.objects.select_for_update().filter(
                reference=reference,
                status__in=['processing', 'approved']
            ).first()
            
            if not withdrawal:
                logger.warning(f"Withdrawal request not found for reference: {reference}")
                return JsonResponse({'status': 'ok', 'message': 'Withdrawal not found'})
            
            if status == 'SUCCESS':
                withdrawal.status = 'completed'
                withdrawal.completed_at = timezone.now()
                withdrawal.provider_reference = transaction_id
                withdrawal.provider_response = payload
                withdrawal.save(update_fields=['status', 'completed_at', 'provider_reference', 'provider_response', 'updated_at'])
                
                # Mark the wallet transaction as success if it exists
                if withdrawal.wallet_transaction:
                    withdrawal.wallet_transaction.mark_success()
                
                logger.info(f"B2C payout completed: {reference} - {amount}")
                
            elif status == 'FAILED':
                withdrawal.status = 'failed'
                withdrawal.rejection_reason = message
                withdrawal.provider_response = payload
                withdrawal.save(update_fields=['status', 'rejection_reason', 'provider_response', 'updated_at'])
                
                # Refund the user if the transaction was frozen
                if withdrawal.wallet_transaction:
                    withdrawal.wallet_transaction.status = 'FAILED'
                    withdrawal.wallet_transaction.notes = f"B2C failed: {message}"
                    withdrawal.wallet_transaction.save(update_fields=['status', 'notes', 'updated_at'])
                
                logger.error(f"B2C payout failed: {reference} - {message}")
            
            return JsonResponse({'status': 'ok', 'message': 'Webhook processed'})
            
    except Exception as e:
        logger.exception(f"B2C webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def jenga_b2b_webhook(request):
    """
    Handle B2B (Business to Business) webhook from Jenga.
    Called when a corporate transfer is completed.
    
    This updates the bank transfer instruction status.
    """
    # Verify HTTP Basic Authentication
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
            # Find the bank transfer instruction
            from .models import BankTransferInstruction
            instruction = BankTransferInstruction.objects.select_for_update().filter(
                reference=reference
            ).first()
            
            if not instruction:
                logger.warning(f"Bank transfer instruction not found for reference: {reference}")
                return JsonResponse({'status': 'ok', 'message': 'Instruction not found'})
            
            if status == 'SUCCESS':
                instruction.status = 'confirmed'
                instruction.confirmed_at = timezone.now()
                instruction.bank_reference = transaction_id
                instruction.bank_response = payload
                instruction.save(update_fields=['status', 'confirmed_at', 'bank_reference', 'bank_response', 'updated_at'])
                
                logger.info(f"B2B transfer completed: {reference} - {amount}")
                
            elif status == 'FAILED':
                instruction.status = 'failed'
                instruction.notes = f"Transfer failed: {message}"
                instruction.bank_response = payload
                instruction.save(update_fields=['status', 'notes', 'bank_response', 'updated_at'])
                
                logger.error(f"B2B transfer failed: {reference} - {message}")
            
            return JsonResponse({'status': 'ok', 'message': 'Webhook processed'})
            
    except Exception as e:
        logger.exception(f"B2B webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)