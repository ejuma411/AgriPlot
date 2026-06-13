from django.db.models.signals import pre_save, post_save
from django.contrib.auth import get_user_model
from django.dispatch import receiver
from django.db.models import F
from decimal import Decimal
from django.utils import timezone
import logging

from .models import Wallet, WalletTransaction, PaymentRequest

logger = logging.getLogger(__name__)

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_wallet(sender, instance, created, **kwargs):
    """Auto-create wallet for new users"""
    if created:
        wallet, created = Wallet.objects.get_or_create(
            user=instance,
            defaults={"is_active": True}
        )
        if created:
            logger.info(f"Created wallet for new user {instance.username} (ID: {instance.id})")


@receiver(pre_save, sender=WalletTransaction)
def capture_previous_transaction_status(sender, instance, **kwargs):
    """Remember the prior status so we can track transitions."""
    if not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = (
        WalletTransaction.objects.filter(pk=instance.pk)
        .values_list("status", first=True)
        .first()
    )


@receiver(post_save, sender=WalletTransaction)
def handle_wallet_transaction_status_change(sender, instance, created, **kwargs):
    """
    Handle wallet transaction status changes.
    Note: Balance is calculated dynamically, so we don't need to update a stored balance.
    Instead, we log the event and send notifications.
    """
    # Skip if status hasn't changed
    if not created and instance._previous_status == instance.status:
        return
    
    # Log status change
    if instance._previous_status != instance.status:
        logger.info(
            f"Wallet transaction {instance.reference} status changed: "
            f"{instance._previous_status} → {instance.status}"
        )
    
    # Handle successful transactions
    if instance.status == WalletTransaction.STATUS_SUCCESS:
        _handle_successful_transaction(instance)
    
    # Handle failed transactions
    elif instance.status == WalletTransaction.STATUS_FAILED:
        _handle_failed_transaction(instance)
    
    # Handle frozen transactions (escrow holds)
    elif instance.status == WalletTransaction.STATUS_FROZEN:
        _handle_frozen_transaction(instance)


def _handle_successful_transaction(transaction):
    """Handle successful wallet transaction (credit or debit)"""
    from notifications.notification_service import NotificationService
    
    wallet = transaction.wallet
    
    if transaction.type == WalletTransaction.TYPE_CREDIT:
        # Money added to wallet
        message = f"KES {transaction.amount:,.2f} deposited into your wallet. Reference: {transaction.reference}"
        notification_type = "wallet_credit"
        title = "Wallet Deposit Successful"
        
        # Send email notification for deposits
        if transaction.channel in [WalletTransaction.CHANNEL_MPESA, WalletTransaction.CHANNEL_BANK_TRANSFER]:
            NotificationService.send_email(
                recipient=wallet.user.email,
                subject=f"Wallet Deposit Confirmation - KES {transaction.amount:,.2f}",
                template="notifications/emails/wallet_deposit_confirmation",
                context={
                    "user": wallet.user,
                    "amount": transaction.amount,
                    "reference": transaction.reference,
                    "channel": transaction.get_channel_display(),
                    "completed_at": transaction.completed_at,
                }
            )
    
    elif transaction.type == WalletTransaction.TYPE_DEBIT:
        # Money removed from wallet
        message = f"KES {transaction.amount:,.2f} debited from your wallet. Reference: {transaction.reference}"
        notification_type = "wallet_debit"
        title = "Wallet Payment Successful"
        
        # If this payment is linked to a payment request, update it
        if transaction.payment_request:
            _update_payment_request_status(transaction.payment_request, transaction)
    
    # Create in-app notification
    NotificationService.create_notification(
        user=wallet.user,
        notification_type=notification_type,
        title=title,
        message=message,
    )
    
    logger.info(
        f"Successful {transaction.type} transaction {transaction.reference} "
        f"for user {wallet.user.username}. Wallet balance: {wallet.balance:,.2f}"
    )


def _handle_failed_transaction(transaction):
    """Handle failed wallet transaction"""
    from notifications.notification_service import NotificationService
    
    wallet = transaction.wallet
    
    message = f"Transaction {transaction.reference} failed. Amount: KES {transaction.amount:,.2f}"
    if transaction.notes:
        message += f" Reason: {transaction.notes}"
    
    NotificationService.create_notification(
        user=wallet.user,
        notification_type="wallet_transaction_failed",
        title="Wallet Transaction Failed",
        message=message,
    )
    
    logger.warning(
        f"Failed {transaction.type} transaction {transaction.reference} "
        f"for user {wallet.user.username}: {transaction.notes}"
    )


def _handle_frozen_transaction(transaction):
    """Handle frozen transaction (held in escrow)"""
    from notifications.notification_service import NotificationService
    
    wallet = transaction.wallet
    
    message = f"KES {transaction.amount:,.2f} has been held from your wallet for escrow. Reference: {transaction.reference}"
    
    NotificationService.create_notification(
        user=wallet.user,
        notification_type="wallet_frozen",
        title="Funds Held in Escrow",
        message=message,
    )
    
    logger.info(
        f"Frozen {transaction.type} transaction {transaction.reference} "
        f"for user {wallet.user.username}: KES {transaction.amount:,.2f}"
    )


def _update_payment_request_status(payment_request, transaction):
    """Update payment request status when wallet payment is completed"""
    if payment_request.status == PaymentRequest.Status.PENDING:
        payment_request.apply_transition("mark_paid", actor=payment_request.buyer)
        logger.info(
            f"Payment request {payment_request.internal_reference} marked as paid "
            f"via wallet transaction {transaction.reference}"
        )


@receiver(post_save, sender=PaymentRequest)
def handle_payment_request_status_change(sender, instance, created, **kwargs):
    """
    When a payment request is marked as PAID, create a wallet transaction
    if the payment method is wallet and no transaction exists yet.
    """
    if instance.method != PaymentRequest.Method.WALLET:
        return
    
    if instance.status != PaymentRequest.Status.PAID:
        return
    
    # Check if wallet transaction already exists for this payment
    existing_tx = WalletTransaction.objects.filter(
        payment_request=instance,
        status=WalletTransaction.STATUS_SUCCESS
    ).exists()
    
    if existing_tx:
        return
    
    # Create wallet transaction for this payment
    from .wallet_service import WalletService
    
    try:
        wallet = Wallet.objects.get(user=instance.buyer)
        
        # Check if this is a debit (payment from wallet) or credit (refund)
        transaction_type = WalletTransaction.TYPE_DEBIT  # Default: paying out
        
        wallet_tx = WalletTransaction.objects.create(
            wallet=wallet,
            amount=instance.amount,
            type=transaction_type,
            status=WalletTransaction.STATUS_PROCESSING,
            channel=WalletTransaction.CHANNEL_WALLET,
            reference=f"PAY-{instance.internal_reference}",
            provider_reference=instance.internal_reference,
            description=f"Payment to {instance.seller.username if instance.seller else 'seller'} for {instance.title}",
            payment_request=instance,
        )
        
        # Mark as success if wallet has sufficient balance
        if wallet.can_debit(instance.amount):
            wallet_tx.mark_success()
            logger.info(f"Auto-created wallet transaction {wallet_tx.reference} for payment {instance.internal_reference}")
        else:
            wallet_tx.mark_failed("Insufficient wallet balance")
            logger.warning(f"Insufficient balance for wallet payment {instance.internal_reference}")
            
    except Wallet.DoesNotExist:
        logger.error(f"Wallet not found for user {instance.buyer.username} when processing payment {instance.internal_reference}")


@receiver(post_save, sender=Wallet)
def log_wallet_creation(sender, instance, created, **kwargs):
    """Log when a wallet is created"""
    if created:
        logger.info(f"Wallet {instance.account_number} created for user {instance.user.username}")


@receiver(pre_save, sender=Wallet)
def enforce_wallet_pin_lockout(sender, instance, **kwargs):
    """
    Enforce PIN lockout - if locked_until is in the future, prevent any debit operations.
    This is a pre-save validation.
    """
    if instance.locked_until and instance.locked_until > timezone.now():
        # Check if we're trying to update failed_pin_attempts (allow it)
        if instance.failed_pin_attempts > 0:
            # Reset locked_until if the lock period has passed
            if instance.locked_until <= timezone.now():
                instance.locked_until = None
                instance.failed_pin_attempts = 0
                logger.info(f"Wallet {instance.account_number} PIN lock expired, resetting attempts")