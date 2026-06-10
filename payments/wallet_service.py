from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.db.models import Q, Sum

from accounts.validators import validate_kenyan_phone

from .daraja import daraja_ready, initiate_stk_push
from .models import (
    PaymentRequest,
    Wallet,
    WalletDepositRequest,
    WalletTransaction,
    WalletWithdrawalRequest,
)

import logging
logger = logging.getLogger(__name__)


class WalletService:
    """Service layer for wallet operations."""
    
    # ============================================================
    # CORE WALLET OPERATIONS (Your existing methods)
    # ============================================================
    
    @staticmethod
    def get_or_create_wallet(user):
        wallet, _created = Wallet.objects.get_or_create(user=user, defaults={"balance": Decimal("0.00")})
        if wallet.balance is None:
            wallet.balance = Decimal("0.00")
            wallet.save(update_fields=["balance", "updated_at"])
        return wallet

    @staticmethod
    def set_pin(user, pin):
        wallet = WalletService.get_or_create_wallet(user)
        wallet.pin_hash = make_password(pin)
        wallet.failed_pin_attempts = 0
        wallet.locked_until = None
        wallet.save(update_fields=["pin_hash", "failed_pin_attempts", "locked_until", "updated_at"])
        return wallet

    @staticmethod
    def verify_pin(user, pin):
        """
        Verify wallet PIN with lockout protection.
        Locks wallet after 5 failed attempts for 30 minutes.
        """
        wallet = WalletService.get_or_create_wallet(user)
        
        if not wallet.pin_hash:
            raise ValidationError("Wallet PIN not set.")
        
        # Check if wallet is locked
        if wallet.locked_until and timezone.now() < wallet.locked_until:
            remaining_minutes = (wallet.locked_until - timezone.now()).seconds // 60
            raise ValidationError(f"Wallet is locked for {remaining_minutes} minutes due to too many failed attempts.")
        
        is_valid = check_password(pin, wallet.pin_hash)
        
        if not is_valid:
            wallet.failed_pin_attempts += 1
            
            # Lock after 5 failed attempts
            if wallet.failed_pin_attempts >= 5:
                wallet.locked_until = timezone.now() + timezone.timedelta(minutes=30)
                wallet.save(update_fields=["failed_pin_attempts", "locked_until", "updated_at"])
                raise ValidationError("Too many failed PIN attempts. Wallet locked for 30 minutes.")
            else:
                remaining = 5 - wallet.failed_pin_attempts
                wallet.save(update_fields=["failed_pin_attempts", "updated_at"])
                raise ValidationError(f"Invalid PIN. {remaining} attempt(s) remaining.")
        else:
            # Reset failed attempts on successful verification
            if wallet.failed_pin_attempts > 0:
                wallet.failed_pin_attempts = 0
                wallet.locked_until = None
                wallet.save(update_fields=["failed_pin_attempts", "locked_until", "updated_at"])
        
        return True

    @staticmethod
    def has_pin(user):
        wallet = WalletService.get_or_create_wallet(user)
        return bool(wallet.pin_hash)

    @staticmethod
    def get_balance(user):
        """Get current wallet balance and pending credits."""
        wallet = WalletService.get_or_create_wallet(user)
        pending_credits = wallet.transactions.filter(
            type=WalletTransaction.TYPE_CREDIT,
            status=WalletTransaction.STATUS_PENDING,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        return {
            "balance": wallet.balance,
            "available_balance": wallet.available_balance,
            "pending_credits": pending_credits,
            "account_number": wallet.account_number,
        }

    @staticmethod
    def get_balance_dict(user):
        """Get current wallet balance as dict with additional info"""
        return WalletService.get_balance(user)

    @staticmethod
    def can_debit(user, amount):
        wallet = WalletService.get_or_create_wallet(user)
        return wallet.available_balance >= amount

    # ============================================================
    # DEPOSIT OPERATIONS (Your existing methods enhanced)
    # ============================================================
    
    @staticmethod
    def _wallet_callback_url(callback_url=None):
        if callback_url:
            return callback_url
        configured = getattr(settings, "WALLET_MPESA_CALLBACK_URL", "").strip()
        if configured:
            return configured
        site_url = getattr(settings, "SITE_URL", "").rstrip("/")
        if not site_url:
            raise ValidationError("Set SITE_URL or WALLET_MPESA_CALLBACK_URL before enabling live wallet deposits.")
        return f"{site_url}/payments/mpesa/wallet-callback/"

    @staticmethod
    def initiate_deposit(user, amount, phone_number, callback_url=None):
        """
        Initiate a wallet deposit via M-Pesa.
        Supports test mode (bypasses actual M-Pesa).
        """
        amount = Decimal(str(amount))
        if amount < Decimal("10"):
            raise ValidationError("Minimum deposit amount is KES 10.")

        checkout_phone = validate_kenyan_phone(phone_number)
        deposit = WalletDepositRequest.objects.create(
            user=user,
            amount=amount,
            phone_number=checkout_phone,
            status="pending",
        )

        # TEST MODE - bypass actual M-Pesa
        if getattr(settings, "WALLET_TEST_MODE", False):
            wallet = WalletService.get_or_create_wallet(user)
            transaction_record = wallet.credit(
                amount=amount,
                description=f"Test wallet deposit - KES {amount:,.2f}",
            )
            receipt = f"TEST-{deposit.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
            transaction_record.metadata = {
                **(transaction_record.metadata or {}),
                "mpesa_receipt": receipt,
                "wallet_test_mode": True,
            }
            transaction_record.mpesa_receipt = receipt
            transaction_record.provider_reference = receipt
            transaction_record.status = WalletTransaction.STATUS_SUCCESS
            transaction_record.completed_at = timezone.now()
            transaction_record.save(
                update_fields=[
                    "mpesa_receipt",
                    "provider_reference",
                    "metadata",
                    "status",
                    "completed_at",
                ]
            )
            
            deposit.status = "completed"
            deposit.completed_at = timezone.now()
            deposit.provider_reference = receipt
            deposit.provider_response = {
                **(deposit.provider_response or {}),
                "mpesa_receipt": receipt,
                "wallet_test_mode": True,
            }
            deposit.wallet_transaction = transaction_record
            deposit.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "provider_reference",
                    "provider_response",
                    "wallet_transaction",
                ]
            )
            return {
                "success": True,
                "deposit_id": deposit.id,
                "deposit_reference": deposit.reference,
                "message": f"KES {amount:,.2f} deposited successfully (test mode).",
                "test_mode": True,
                "new_balance": wallet.balance
            }

        # LIVE MODE - use Daraja
        if not daraja_ready():
            deposit.status = "failed"
            deposit.provider_response = {
                **(deposit.provider_response or {}),
                "error": "Daraja is not configured for live wallet deposits.",
            }
            deposit.save(update_fields=["status", "provider_response"])
            raise ValidationError("Safaricom Daraja is not configured for live wallet deposits yet.")

        # Create temporary payment request for STK push
        temp_payment = PaymentRequest.objects.create(
            buyer=user,
            amount=amount,
            phone_number=checkout_phone,
            title=f"Wallet Deposit - {user.username}",
            description=f"Deposit KES {amount:,.2f} into the AgriPlot Wallet",
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            category=PaymentRequest.Category.SERVICE_FEE,
            method=PaymentRequest.Method.MPESA_STK,
            status=PaymentRequest.Status.PENDING,
            internal_reference=f"WLD-{deposit.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            escrow_enabled=False,
        )

        deposit.provider_response = {
            **(deposit.provider_response or {}),
            "payment_id": temp_payment.id,
        }
        deposit.status = "processing"
        deposit.save(update_fields=["provider_response", "status"])

        try:
            response = initiate_stk_push(
                temp_payment,
                WalletService._wallet_callback_url(callback_url),
            )
        except Exception as exc:
            deposit.status = "failed"
            deposit.provider_response = {
                **(deposit.provider_response or {}),
                "error": str(exc),
            }
            deposit.save(update_fields=["status", "provider_response"])
            temp_payment.status = PaymentRequest.Status.FAILED
            temp_payment.save(update_fields=["status", "updated_at"])
            raise

        temp_payment.provider_reference = (
            response.get("CheckoutRequestID")
            or response.get("MerchantRequestID")
            or temp_payment.internal_reference
        )
        temp_payment.metadata = {
            **(temp_payment.metadata or {}),
            "daraja_checkout_request_id": response.get("CheckoutRequestID", ""),
            "daraja_merchant_request_id": response.get("MerchantRequestID", ""),
            "daraja_customer_message": response.get("CustomerMessage", ""),
            "daraja_response_description": response.get("ResponseDescription", ""),
            "wallet_deposit": True,
        }
        temp_payment.save(update_fields=["provider_reference", "metadata", "updated_at"])
        deposit.provider_reference = response.get("CheckoutRequestID", "")
        deposit.provider_response = {
            **(deposit.provider_response or {}),
            "checkout_request_id": response.get("CheckoutRequestID", ""),
            "merchant_request_id": response.get("MerchantRequestID", ""),
            "customer_message": response.get("CustomerMessage", ""),
            "response_description": response.get("ResponseDescription", ""),
        }
        deposit.save(update_fields=["provider_reference", "provider_response"])

        return {
            "success": True,
            "deposit_id": deposit.id,
            "deposit_reference": deposit.reference,
            "checkout_request_id": response.get("CheckoutRequestID"),
            "merchant_request_id": response.get("MerchantRequestID"),
            "message": response.get("CustomerMessage")
            or "STK push sent. Complete the wallet deposit on your phone.",
        }

    @staticmethod
    def complete_deposit(checkout_request_id, mpesa_receipt, amount):
        """
        Complete a deposit after M-Pesa confirmation.
        Called by webhook from Daraja.
        CRITICAL: Uses select_for_update() to prevent race conditions.
        """
        try:
            deposit = WalletDepositRequest.objects.get(provider_reference=checkout_request_id)
        except WalletDepositRequest.DoesNotExist:
            return {"success": False, "message": "Deposit request not found."}

        # Prevent double processing
        if deposit.status == "completed":
            wallet = WalletService.get_or_create_wallet(deposit.user)
            return {
                "success": True,
                "message": "Deposit already completed.",
                "new_balance": wallet.balance,
            }

        with transaction.atomic():
            # Lock the deposit row to prevent race conditions
            deposit = WalletDepositRequest.objects.select_for_update().get(pk=deposit.pk)
            
            # Double-check status after lock
            if deposit.status == "completed":
                wallet = WalletService.get_or_create_wallet(deposit.user)
                return {
                    "success": True,
                    "message": "Deposit already completed.",
                    "new_balance": wallet.balance,
                }

            payment_id = (deposit.provider_response or {}).get("payment_id")
            if payment_id:
                try:
                    temp_payment = PaymentRequest.objects.select_for_update().get(pk=payment_id)
                except PaymentRequest.DoesNotExist:
                    temp_payment = None
                if temp_payment and temp_payment.status == PaymentRequest.Status.PENDING:
                    temp_payment.apply_transition("mark_paid", actor=deposit.user)
                if temp_payment:
                    temp_payment.metadata = {
                        **(temp_payment.metadata or {}),
                        "wallet_deposit_receipt": mpesa_receipt,
                        "wallet_deposit_checkout_request_id": checkout_request_id,
                    }
                    temp_payment.save(update_fields=["metadata", "updated_at"])

            # Lock wallet row
            wallet = Wallet.objects.select_for_update().get(user=deposit.user)
            
            # Create and complete the wallet transaction
            transaction_record = wallet.credit(
                amount=amount,
                description=f"M-Pesa wallet deposit - receipt {mpesa_receipt}",
            )
            transaction_record.metadata = {
                **(transaction_record.metadata or {}),
                "checkout_request_id": checkout_request_id,
                "mpesa_receipt": mpesa_receipt,
            }
            transaction_record.mpesa_receipt = mpesa_receipt
            transaction_record.provider_reference = mpesa_receipt
            transaction_record.status = WalletTransaction.STATUS_SUCCESS
            transaction_record.completed_at = timezone.now()
            transaction_record.save(
                update_fields=[
                    "mpesa_receipt",
                    "provider_reference",
                    "metadata",
                    "status",
                    "completed_at",
                ]
            )

            deposit.status = "completed"
            deposit.completed_at = timezone.now()
            deposit.provider_response = {
                **(deposit.provider_response or {}),
                "mpesa_receipt": mpesa_receipt,
                "checkout_request_id": checkout_request_id,
            }
            deposit.wallet_transaction = transaction_record
            deposit.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "provider_response",
                    "wallet_transaction",
                ]
            )

        # Send notification (async in production)
        WalletService._send_deposit_notification(deposit.user, amount, transaction_record.reference)

        return {
            "success": True,
            "message": f"KES {amount:,.2f} deposited successfully.",
            "transaction_reference": transaction_record.reference,
            "new_balance": wallet.balance,
        }

    # ============================================================
    # PAYMENT OPERATIONS (Using wallet to pay for listings)
    # ============================================================
    
    @staticmethod
    def make_payment(user, amount, pin, payment_request=None, description=""):
        """
        Make a payment from wallet (for listings, commitments, etc.)
        Requires PIN verification.
        """
        if not WalletService.verify_pin(user, pin):
            raise ValidationError("Invalid wallet PIN.")

        amount = Decimal(str(amount))
        wallet = WalletService.get_or_create_wallet(user)
        
        # Check sufficient balance
        if not wallet.can_debit(amount):
            raise ValidationError(
                f"Insufficient wallet balance. Available: KES {wallet.available_balance:,.2f}."
            )

        with transaction.atomic():
            # Lock wallet row
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            
            # Double-check balance after lock
            if not wallet.can_debit(amount):
                raise ValidationError(
                    f"Insufficient wallet balance. Available: KES {wallet.available_balance:,.2f}."
                )

            # Create debit transaction
            transaction_record = wallet.debit(
                amount=amount,
                description=description or "Payment via AgriPlot Wallet",
            )
            transaction_record.status = WalletTransaction.STATUS_SUCCESS
            transaction_record.completed_at = timezone.now()
            
            if payment_request:
                transaction_record.payment_request = payment_request
                transaction_record.related_payment = payment_request
                transaction_record.metadata = {
                    **(transaction_record.metadata or {}),
                    "payment_request_id": payment_request.pk,
                }
                transaction_record.save(
                    update_fields=[
                        "payment_request",
                        "related_payment",
                        "metadata",
                        "status",
                        "completed_at",
                    ]
                )
                
                # Mark payment request as paid if pending
                if payment_request.status == PaymentRequest.Status.PENDING:
                    payment_request.apply_transition("mark_paid", actor=user)
            else:
                transaction_record.save(update_fields=["status", "completed_at"])

        return {
            "success": True,
            "transaction_reference": transaction_record.reference,
            "new_balance": wallet.balance,
            "message": f"Payment of KES {amount:,.2f} completed from your wallet.",
        }

    # ============================================================
    # WITHDRAWAL OPERATIONS (M-Pesa payouts)
    # ============================================================
    
    @staticmethod
    def initiate_withdrawal(user, amount, phone_number, pin):
        """
        Initiate a withdrawal from wallet to M-Pesa.
        Note: B2C payout via M-Pesa is required for production.
        For now, this records the withdrawal for manual processing.
        """
        if not WalletService.verify_pin(user, pin):
            raise ValidationError("Invalid wallet PIN.")

        amount = Decimal(str(amount))
        if amount < Decimal("50"):
            raise ValidationError("Minimum withdrawal amount is KES 50.")

        wallet = WalletService.get_or_create_wallet(user)
        
        # Check sufficient balance
        if not wallet.can_debit(amount):
            raise ValidationError(
                f"Insufficient balance. Available: KES {wallet.available_balance:,.2f}."
            )

        checkout_phone = validate_kenyan_phone(phone_number)
        
        with transaction.atomic():
            # Lock wallet row
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            
            # Double-check balance after lock
            if not wallet.can_debit(amount):
                raise ValidationError(
                    f"Insufficient balance. Available: KES {wallet.available_balance:,.2f}."
                )
            
            # Create debit transaction (frozen initially)
            transaction_record = wallet.debit(
                amount=amount,
                description=f"Wallet withdrawal to M-Pesa {checkout_phone}",
            )
            transaction_record.transaction_type = transaction_record.type
            transaction_record.channel = WalletTransaction.CHANNEL_MPESA
            transaction_record.status = WalletTransaction.STATUS_FROZEN
            transaction_record.metadata = {
                **(transaction_record.metadata or {}),
                "withdrawal_phone": checkout_phone,
            }
            transaction_record.save(update_fields=["transaction_type", "channel", "metadata", "status"])
            
            # Create withdrawal request
            withdrawal = WalletWithdrawalRequest.objects.create(
                user=user,
                amount=amount,
                phone_number=checkout_phone,
                status="pending",
                wallet_transaction=transaction_record,
            )
            
            # For test mode, complete immediately
            if getattr(settings, "WALLET_TEST_MODE", False):
                transaction_record.status = WalletTransaction.STATUS_SUCCESS
                transaction_record.completed_at = timezone.now()
                transaction_record.save(update_fields=["status", "completed_at"])
                
                withdrawal.status = "completed"
                withdrawal.completed_at = timezone.now()
                withdrawal.save(update_fields=["status", "completed_at"])
                
                return {
                    "success": True,
                    "withdrawal_id": withdrawal.id,
                    "withdrawal_reference": withdrawal.reference,
                    "message": f"KES {amount:,.2f} withdrawn successfully (test mode).",
                    "test_mode": True,
                    "new_balance": wallet.balance
                }
            
            # For production, transaction stays frozen until B2C completes
            # This will need integration with Daraja B2C API

        return {
            "success": True,
            "withdrawal_id": withdrawal.id,
            "withdrawal_reference": withdrawal.reference,
            "message": "Withdrawal initiated. Funds will be sent to your M-Pesa within 1-2 hours.",
            "new_balance": wallet.balance
        }

    # ============================================================
    # TRANSACTION HISTORY & REPORTS
    # ============================================================
    
    @staticmethod
    def get_transaction_history(user, limit=50, offset=0, transaction_type=None):
        """
        Get paginated transaction history with optional filtering.
        """
        wallet = WalletService.get_or_create_wallet(user)
        
        queryset = wallet.transactions.all()
        
        if transaction_type:
            queryset = queryset.filter(type=transaction_type)
        
        return list(queryset[offset:offset + limit])

    # ============================================================
    # NOTIFICATION HELPERS
    # ============================================================
    
    @staticmethod
    def _send_deposit_notification(user, amount, reference):
        """Send deposit success notification to user"""
        try:
            from notifications.notification_service import NotificationService
            
            NotificationService.send_email(
                recipient=user.email,
                subject=f"AgriPlot Wallet Deposit Confirmation - KES {amount:,.2f}",
                template="wallet/deposit_confirmation",
                context={
                    'user': user,
                    'amount': amount,
                    'reference': reference,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send deposit notification email: {e}")

    # ============================================================
    # ADMIN / MAKER-CHECKER OPERATIONS
    # ============================================================
    
    @staticmethod
    def get_pending_withdrawals():
        """Get all withdrawals pending approval (for admin dashboard)"""
        return WalletWithdrawalRequest.objects.filter(
            status='pending'
        ).select_related('user', 'wallet_transaction')

    @staticmethod
    def _get_withdrawal(identifier):
        lookup = Q(reference=identifier)
        try:
            lookup |= Q(id=int(identifier))
        except (TypeError, ValueError):
            pass
        return WalletWithdrawalRequest.objects.get(lookup)
    
    @staticmethod
    def approve_withdrawal(withdrawal_id, admin_user, notes=""):
        """
        Approve a withdrawal request (for large amounts).
        Only accessible by admin/staff users.
        """
        withdrawal = WalletService._get_withdrawal(withdrawal_id)
        
        if withdrawal.status != 'pending':
            raise ValidationError(f"Cannot approve withdrawal in {withdrawal.status} status")
        
        with transaction.atomic():
            withdrawal.status = 'approved'
            withdrawal.approved_by = admin_user
            withdrawal.approved_at = timezone.now()
            withdrawal.approval_notes = notes
            withdrawal.save(update_fields=['status', 'approved_by', 'approved_at', 'approval_notes', 'updated_at'])
            
            # For test mode, complete immediately
            if getattr(settings, "WALLET_TEST_MODE", False) and withdrawal.wallet_transaction:
                withdrawal.wallet_transaction.status = WalletTransaction.STATUS_SUCCESS
                withdrawal.wallet_transaction.completed_at = timezone.now()
                withdrawal.wallet_transaction.save(update_fields=['status', 'completed_at'])
                
                withdrawal.status = 'completed'
                withdrawal.completed_at = timezone.now()
                withdrawal.save(update_fields=['status', 'completed_at'])
        
        return {
            'success': True,
            'message': f'Withdrawal {withdrawal.reference} approved successfully'
        }
    
    @staticmethod
    def reject_withdrawal(withdrawal_id, admin_user, reason):
        """Reject a withdrawal request"""
        withdrawal = WalletService._get_withdrawal(withdrawal_id)
        
        if withdrawal.status != 'pending':
            raise ValidationError(f"Cannot reject withdrawal in {withdrawal.status} status")
        
        with transaction.atomic():
            # Refund the frozen transaction
            if withdrawal.wallet_transaction and withdrawal.wallet_transaction.status == WalletTransaction.STATUS_FROZEN:
                withdrawal.wallet_transaction.status = WalletTransaction.STATUS_FAILED
                withdrawal.wallet_transaction.description = (
                    f"{withdrawal.wallet_transaction.description} Rejected: {reason}"
                ).strip()
                withdrawal.wallet_transaction.metadata = {
                    **(withdrawal.wallet_transaction.metadata or {}),
                    "rejection_reason": reason,
                }
                withdrawal.wallet_transaction.save(
                    update_fields=['status', 'description', 'metadata']
                )
            
            withdrawal.status = 'rejected'
            withdrawal.approved_by = admin_user
            withdrawal.approved_at = timezone.now()
            withdrawal.rejection_reason = reason
            withdrawal.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at'])
        
        return {
            'success': True,
            'message': f'Withdrawal {withdrawal.reference} rejected: {reason}'
        }

    # ============================================================
    # ESCROW TO WALLET INTEGRATION
    # ============================================================
    
    @staticmethod
    def release_escrow_to_wallet(user, amount, payment_request, description=""):
        """
        Release escrow funds directly to user's wallet.
        Used for:
        - Seller receiving payment for land sale
        - Agent receiving commission
        - Landlord receiving lease payments
        """
        wallet = WalletService.get_or_create_wallet(user)
        
        with transaction.atomic():
            # Lock wallet row
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            
            # Create credit transaction
            transaction_record = wallet.credit(
                amount=amount,
                description=description or f"Funds released from {payment_request.internal_reference}",
            )
            transaction_record.related_payment = payment_request
            transaction_record.payment_request = payment_request
            transaction_record.status = WalletTransaction.STATUS_SUCCESS
            transaction_record.completed_at = timezone.now()
            transaction_record.save(
                update_fields=[
                    'payment_request',
                    'related_payment',
                    'status',
                    'completed_at',
                ]
            )
            
        return {
            'success': True,
            'transaction_reference': transaction_record.reference,
            'new_balance': wallet.balance,
            'message': f"KES {amount:,.2f} credited to your wallet"
        }
