from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.validators import validate_kenyan_phone

from .daraja import DarajaError, daraja_ready, initiate_stk_push
from .models import (
    PaymentRequest,
    Wallet,
    WalletDepositRequest,
    WalletTransaction,
    WalletWithdrawalRequest,
)


class WalletService:
    """Service layer for wallet operations."""

    @staticmethod
    def get_or_create_wallet(user):
        wallet, _created = Wallet.objects.get_or_create(user=user)
        return wallet

    @staticmethod
    def set_pin(user, pin):
        wallet = WalletService.get_or_create_wallet(user)
        wallet.pin_hash = make_password(pin)
        wallet.save(update_fields=["pin_hash", "updated_at"])
        return wallet

    @staticmethod
    def verify_pin(user, pin):
        wallet = WalletService.get_or_create_wallet(user)
        if not wallet.pin_hash:
            raise ValidationError("Wallet PIN not set.")
        return check_password(pin, wallet.pin_hash)

    @staticmethod
    def has_pin(user):
        wallet = WalletService.get_or_create_wallet(user)
        return bool(wallet.pin_hash)

    @staticmethod
    def get_balance(user):
        wallet = WalletService.get_or_create_wallet(user)
        return wallet.balance

    @staticmethod
    def can_debit(user, amount):
        wallet = WalletService.get_or_create_wallet(user)
        return wallet.balance >= amount

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

        if getattr(settings, "WALLET_TEST_MODE", False):
            wallet = WalletService.get_or_create_wallet(user)
            transaction_record = wallet.credit(
                amount=amount,
                description=f"Test wallet deposit - KES {amount:,.2f}",
            )
            receipt = f"TEST-{deposit.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
            transaction_record.mpesa_receipt = receipt
            transaction_record.metadata = {
                **(transaction_record.metadata or {}),
                "wallet_test_mode": True,
            }
            transaction_record.save(update_fields=["mpesa_receipt", "metadata"])
            deposit.status = "completed"
            deposit.mpesa_receipt = receipt
            deposit.completed_at = timezone.now()
            deposit.transaction = transaction_record
            deposit.save(
                update_fields=[
                    "status",
                    "mpesa_receipt",
                    "completed_at",
                    "transaction",
                ]
            )
            return {
                "success": True,
                "deposit_id": deposit.id,
                "message": f"KES {amount:,.2f} deposited successfully (test mode).",
                "test_mode": True,
            }

        if not daraja_ready():
            deposit.status = "failed"
            deposit.metadata = {
                **(deposit.metadata or {}),
                "error": "Daraja is not configured for live wallet deposits.",
            }
            deposit.save(update_fields=["status", "metadata"])
            raise ValidationError("Safaricom Daraja is not configured for live wallet deposits yet.")

        temp_payment = PaymentRequest.objects.create(
            buyer=user,
            amount=amount,
            phone_number=checkout_phone,
            title=f"Wallet Deposit - {user.username}",
            description=f"Deposit KES {amount:,.2f} into the AgriPlot Wallet",
            transaction_type=PaymentRequest.TransactionType.SERVICE,
            category=PaymentRequest.Category.SERVICE_FEE,
            method=PaymentRequest.Method.MPESA_STK,
            status=PaymentRequest.Status.PENDING,
            internal_reference=f"WLD-{deposit.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            escrow_enabled=False,
        )

        deposit.metadata = {
            **(deposit.metadata or {}),
            "payment_id": temp_payment.id,
        }
        deposit.status = "processing"
        deposit.save(update_fields=["metadata", "status"])

        try:
            response = initiate_stk_push(
                temp_payment,
                WalletService._wallet_callback_url(callback_url),
            )
        except Exception as exc:
            deposit.status = "failed"
            deposit.metadata = {
                **(deposit.metadata or {}),
                "error": str(exc),
            }
            deposit.save(update_fields=["status", "metadata"])
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
        deposit.checkout_request_id = response.get("CheckoutRequestID", "")
        deposit.save(update_fields=["checkout_request_id"])

        return {
            "success": True,
            "deposit_id": deposit.id,
            "checkout_request_id": response.get("CheckoutRequestID"),
            "merchant_request_id": response.get("MerchantRequestID"),
            "message": response.get("CustomerMessage")
            or "STK push sent. Complete the wallet deposit on your phone.",
        }

    @staticmethod
    def complete_deposit(checkout_request_id, mpesa_receipt, amount):
        try:
            deposit = WalletDepositRequest.objects.get(checkout_request_id=checkout_request_id)
        except WalletDepositRequest.DoesNotExist:
            return {"success": False, "message": "Deposit request not found."}

        if deposit.status == "completed":
            wallet = WalletService.get_or_create_wallet(deposit.user)
            return {
                "success": True,
                "message": "Deposit already completed.",
                "new_balance": wallet.balance,
            }

        with transaction.atomic():
            payment_id = (deposit.metadata or {}).get("payment_id")
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

            wallet = WalletService.get_or_create_wallet(deposit.user)
            transaction_record = wallet.credit(
                amount=amount,
                description=f"M-Pesa wallet deposit - receipt {mpesa_receipt}",
            )
            transaction_record.mpesa_receipt = mpesa_receipt
            transaction_record.metadata = {
                **(transaction_record.metadata or {}),
                "checkout_request_id": checkout_request_id,
            }
            transaction_record.save(update_fields=["mpesa_receipt", "metadata"])

            deposit.status = "completed"
            deposit.mpesa_receipt = mpesa_receipt
            deposit.completed_at = timezone.now()
            deposit.transaction = transaction_record
            deposit.save(
                update_fields=[
                    "status",
                    "mpesa_receipt",
                    "completed_at",
                    "transaction",
                ]
            )

        return {
            "success": True,
            "message": f"KES {amount:,.2f} deposited successfully.",
            "new_balance": wallet.balance,
        }

    @staticmethod
    def make_payment(user, amount, pin, payment_request=None, description=""):
        if not WalletService.verify_pin(user, pin):
            raise ValidationError("Invalid wallet PIN.")

        wallet = WalletService.get_or_create_wallet(user)
        if not wallet.can_debit(amount):
            raise ValidationError(
                f"Insufficient wallet balance. Available: KES {wallet.balance:,.2f}."
            )

        transaction_record = wallet.debit(
            amount=amount,
            description=description or "Payment via AgriPlot Wallet",
        )

        if payment_request:
            transaction_record.related_payment = payment_request
            transaction_record.metadata = {
                **(transaction_record.metadata or {}),
                "payment_request_id": payment_request.pk,
            }
            transaction_record.save(update_fields=["related_payment", "metadata"])
            if payment_request.status == PaymentRequest.Status.PENDING:
                payment_request.apply_transition("mark_paid", actor=user)

        return {
            "success": True,
            "transaction": transaction_record,
            "new_balance": wallet.balance,
            "message": f"Payment of KES {amount:,.2f} completed from your wallet.",
        }

    @staticmethod
    def initiate_withdrawal(user, amount, phone_number, pin):
        if not WalletService.verify_pin(user, pin):
            raise ValidationError("Invalid wallet PIN.")

        amount = Decimal(str(amount))
        if amount < Decimal("50"):
            raise ValidationError("Minimum withdrawal amount is KES 50.")

        wallet = WalletService.get_or_create_wallet(user)
        if not wallet.can_debit(amount):
            raise ValidationError(
                f"Insufficient balance. Available: KES {wallet.balance:,.2f}."
            )

        checkout_phone = validate_kenyan_phone(phone_number)
        withdrawal = WalletWithdrawalRequest.objects.create(
            user=user,
            amount=amount,
            phone_number=checkout_phone,
            status="processing",
        )

        transaction_record = wallet.debit(
            amount=amount,
            description=f"Wallet withdrawal to M-Pesa {checkout_phone}",
        )
        withdrawal.transaction = transaction_record
        withdrawal.completed_at = timezone.now()
        withdrawal.status = "completed"
        withdrawal.save(update_fields=["transaction", "completed_at", "status"])

        return {
            "success": True,
            "withdrawal_id": withdrawal.id,
            "message": "Withdrawal initiated. Funds will be sent to your M-Pesa.",
        }

    @staticmethod
    def get_transaction_history(user, limit=50):
        wallet = WalletService.get_or_create_wallet(user)
        return wallet.transactions.all()[:limit]
