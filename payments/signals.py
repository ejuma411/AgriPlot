from django.db.models.signals import pre_save, post_save
from django.contrib.auth import get_user_model
from django.dispatch import receiver
from django.db.models import F, Q
from decimal import Decimal
from django.utils import timezone
import logging

from .models import Wallet, WalletTransaction, PaymentRequest, PaymentClosingStep, PaymentDisbursement

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
        f"for user {wallet.user.username}. Wallet balance computed on demand"
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
    Handle payment request status changes.
    - When PAID, record deposit or balance payment to escrow
    - When RELEASED, trigger fund disbursement to seller
    - When registration completes, trigger automatic disbursement
    """
    # Check if we need to record escrow payments
    if instance.status == PaymentRequest.Status.PAID:
        _record_escrow_payment(instance)
    
    # Check if we need to disburse funds (after registration)
    if instance.status == PaymentRequest.Status.RELEASED:
        _trigger_fund_disbursement(instance)
    
    # Check if registration step just completed
    if not created:
        _check_registration_completion(instance)
    
    # Check if stamp duty receipt was verified
    if not created:
        _check_stamp_duty_verification(instance)


def _record_escrow_payment(payment_request):
    """
    Record escrow payment when payment request is marked as PAID.
    Differentiates between deposit (10%) and balance (90%).
    """
    # Determine if this is deposit or balance based on category
    if payment_request.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
        payment_request.deposit_received_at = timezone.now()
        payment_request.metadata['deposit_paid'] = True
        payment_request.save(update_fields=['deposit_received_at', 'metadata', 'updated_at'])
        
        logger.info(
            f"Deposit payment recorded for {payment_request.internal_reference}: "
            f"KES {payment_request.amount:,.2f} held in escrow"
        )
        
        # Send notification to seller that deposit is in escrow
        from notifications.notification_service import NotificationService
        if payment_request.seller:
            NotificationService.create_notification(
                user=payment_request.seller,
                notification_type="payment_deposit_received",
                title="Deposit Received in Escrow",
                message=f"Buyer has paid 10% deposit (KES {payment_request.amount:,.2f}) into escrow for {payment_request.title}",
            )
    
    elif payment_request.category == PaymentRequest.Category.COMPLETION_BALANCE:
        payment_request.balance_received_at = timezone.now()
        payment_request.metadata['balance_paid'] = True
        payment_request.save(update_fields=['balance_received_at', 'metadata', 'updated_at'])
        
        logger.info(
            f"Balance payment recorded for {payment_request.internal_reference}: "
            f"KES {payment_request.amount:,.2f} held in escrow"
        )
        
        # Send notification to seller that balance is in escrow
        from notifications.notification_service import NotificationService
        if payment_request.seller:
            NotificationService.create_notification(
                user=payment_request.seller,
                notification_type="payment_balance_received",
                title="Balance Received in Escrow",
                message=f"Buyer has paid 90% balance (KES {payment_request.amount:,.2f}) into escrow for {payment_request.title}",
            )


def _trigger_fund_disbursement(payment_request):
    """
    Trigger fund disbursement to seller after registration completion.
    Platform fee is deducted before disbursement.
    """
    # Check if already disbursed
    if payment_request.disbursed_at:
        logger.info(f"Funds already disbursed for {payment_request.internal_reference}")
        return
    
    # Verify registration is complete
    if not payment_request.purchase_registration_complete:
        logger.warning(
            f"Cannot disburse funds for {payment_request.internal_reference}: "
            "Registration not complete"
        )
        return
    
    # Verify stamp duty is verified
    stamp_duty_step = payment_request.closing_steps.filter(code="stamp_duty").first()
    if not stamp_duty_step or stamp_duty_step.status != PaymentClosingStep.Status.COMPLETED:
        logger.warning(
            f"Cannot disburse funds for {payment_request.internal_reference}: "
            "Stamp duty not verified"
        )
        return
    
    # Verify both deposit and balance are in escrow
    if not payment_request.metadata.get('deposit_paid') or not payment_request.metadata.get('balance_paid'):
        logger.warning(
            f"Cannot disburse funds for {payment_request.internal_reference}: "
            "Not all funds received in escrow"
        )
        return
    
    # Calculate platform fee
    platform_fee = payment_request.platform_fee_amount
    seller_amount = payment_request.seller_net_amount
    
    logger.info(
        f"Preparing disbursement for {payment_request.internal_reference}: "
        f"Total: KES {payment_request.amount:,.2f}, "
        f"Platform fee: KES {platform_fee:,.2f}, "
        f"Seller receives: KES {seller_amount:,.2f}"
    )
    
    # Mark platform fee as deducted
    payment_request.platform_fee_deducted_at = timezone.now()
    payment_request.disbursed_at = timezone.now()
    payment_request.save(update_fields=['platform_fee_deducted_at', 'disbursed_at', 'updated_at'])
    
    # Update disbursement records
    _update_disbursement_records(payment_request, platform_fee, seller_amount)
    
    # Send notifications
    _send_disbursement_notifications(payment_request, platform_fee, seller_amount)
    
    logger.info(
        f"Funds disbursed for {payment_request.internal_reference}: "
        f"Seller receives KES {seller_amount:,.2f} after {payment_request.platform_fee_percentage * 100}% fee"
    )


def _update_disbursement_records(payment_request, platform_fee, seller_amount):
    """Update PaymentDisbursement records to RELEASED status"""
    # Update platform fee disbursement
    platform_disbursement = payment_request.disbursements.filter(code="platform_fee").first()
    if platform_disbursement and platform_disbursement.status != PaymentDisbursement.Status.RELEASED:
        platform_disbursement.status = PaymentDisbursement.Status.RELEASED
        platform_disbursement.released_at = timezone.now()
        platform_disbursement.save(update_fields=['status', 'released_at', 'updated_at'])
        logger.info(f"Platform fee disbursement recorded: KES {platform_fee:,.2f}")
    
    # Update seller disbursement
    seller_disbursement = payment_request.disbursements.filter(code="seller_disbursement").first()
    if seller_disbursement and seller_disbursement.status != PaymentDisbursement.Status.RELEASED:
        seller_disbursement.status = PaymentDisbursement.Status.RELEASED
        seller_disbursement.released_at = timezone.now()
        seller_disbursement.save(update_fields=['status', 'released_at', 'updated_at'])
        logger.info(f"Seller disbursement recorded: KES {seller_amount:,.2f}")
    
    # Update deposit and balance held records to released
    deposit_held = payment_request.disbursements.filter(code="deposit_held").first()
    if deposit_held and deposit_held.status != PaymentDisbursement.Status.RELEASED:
        deposit_held.status = PaymentDisbursement.Status.RELEASED
        deposit_held.released_at = timezone.now()
        deposit_held.save(update_fields=['status', 'released_at', 'updated_at'])
    
    balance_held = payment_request.disbursements.filter(code="balance_held").first()
    if balance_held and balance_held.status != PaymentDisbursement.Status.RELEASED:
        balance_held.status = PaymentDisbursement.Status.RELEASED
        balance_held.released_at = timezone.now()
        balance_held.save(update_fields=['status', 'released_at', 'updated_at'])


def _send_disbursement_notifications(payment_request, platform_fee, seller_amount):
    """Send notifications to buyer and seller about disbursement"""
    from notifications.notification_service import NotificationService
    
    # Notify seller
    if payment_request.seller:
        NotificationService.create_notification(
            user=payment_request.seller,
            notification_type="funds_disbursed",
            title="Funds Disbursed to Your Account",
            message=(
                f"Funds for {payment_request.title} have been disbursed. "
                f"Total: KES {payment_request.amount:,.2f}. "
                f"Platform fee ({payment_request.platform_fee_percentage * 100}%): KES {platform_fee:,.2f}. "
                f"Net amount: KES {seller_amount:,.2f}. "
                f"Please allow 1-3 business days for the transfer to reflect in your bank account."
            ),
        )
        
        # Send email
        NotificationService.send_email(
            recipient=payment_request.seller.email,
            subject=f"Funds Disbursed - {payment_request.title}",
            template="notifications/emails/funds_disbursed",
            context={
                "payment": payment_request,
                "platform_fee": platform_fee,
                "seller_amount": seller_amount,
                "fee_percentage": payment_request.platform_fee_percentage * 100,
            }
        )
    
    # Notify buyer
    if payment_request.buyer:
        NotificationService.create_notification(
            user=payment_request.buyer,
            notification_type="transaction_complete",
            title="Transaction Complete - Funds Disbursed",
            message=(
                f"The transaction for {payment_request.title} is complete. "
                f"Funds have been disbursed to the seller after title registration. "
                f"Check your email for the transaction report."
            ),
        )


def _check_registration_completion(payment_request):
    """
    Check if registration step was just completed.
    If so, automatically trigger fund disbursement.
    """
    # Only for purchase transactions
    if payment_request.transaction_type != PaymentRequest.TransactionType.PURCHASE:
        return
    
    # Check if registration step exists and was just completed
    registration_step = payment_request.closing_steps.filter(code="registration").first()
    if not registration_step:
        return
    
    # Get previous status (need to track this - could use a pre-save signal on PaymentClosingStep)
    # For now, check if step is completed and funds haven't been disbursed yet
    if (registration_step.status == PaymentClosingStep.Status.COMPLETED and 
        not payment_request.disbursed_at and
        payment_request.metadata.get('deposit_paid') and
        payment_request.metadata.get('balance_paid')):
        
        logger.info(f"Registration completed for {payment_request.internal_reference}, triggering disbursement")
        payment_request.apply_transition("disburse_to_seller", actor=registration_step.completed_by)


def _check_stamp_duty_verification(payment_request):
    """
    Check if stamp duty receipt was just verified.
    Log the verification event.
    """
    # Only for purchase transactions
    if payment_request.transaction_type != PaymentRequest.TransactionType.PURCHASE:
        return
    
    # Check if stamp duty step was just completed
    stamp_duty_step = payment_request.closing_steps.filter(code="stamp_duty").first()
    if not stamp_duty_step:
        return
    
    if stamp_duty_step.status == PaymentClosingStep.Status.COMPLETED:
        # Record that stamp duty was verified (payment was made directly to KRA)
        if not payment_request.stamp_duty_receipt_verified_at:
            payment_request.stamp_duty_receipt_verified_at = timezone.now()
            if stamp_duty_step.completed_by:
                payment_request.stamp_duty_verified_by = stamp_duty_step.completed_by
            payment_request.save(update_fields=['stamp_duty_receipt_verified_at', 'stamp_duty_verified_by', 'updated_at'])
            
            logger.info(
                f"Stamp duty receipt verified for {payment_request.internal_reference} "
                f"by {stamp_duty_step.completed_by.username if stamp_duty_step.completed_by else 'system'}"
            )
            
            # Send notification to buyer that stamp duty is verified
            from notifications.notification_service import NotificationService
            if payment_request.buyer:
                NotificationService.create_notification(
                    user=payment_request.buyer,
                    notification_type="stamp_duty_verified",
                    title="Stamp Duty Payment Verified",
                    message=f"Your stamp duty payment for {payment_request.title} has been verified. Proceed to registration.",
                )


@receiver(post_save, sender=PaymentClosingStep)
def handle_closing_step_completion(sender, instance, created, **kwargs):
    """
    Handle when a closing step is completed.
    This triggers:
    - Registration completion → fund disbursement
    - Stamp duty verification → notification
    """
    if instance.status != PaymentClosingStep.Status.COMPLETED:
        return
    
    payment = instance.payment
    
    # If registration step completed, trigger disbursement
    if instance.code == "registration" and payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
        if payment.metadata.get('deposit_paid') and payment.metadata.get('balance_paid'):
            logger.info(f"Registration step completed for {payment.internal_reference}, triggering disbursement")
            payment.apply_transition("disburse_to_seller", actor=instance.completed_by)
    
    # If stamp duty step completed, record verification
    elif instance.code == "stamp_duty":
        if not payment.stamp_duty_receipt_verified_at:
            payment.stamp_duty_receipt_verified_at = timezone.now()
            if instance.completed_by:
                payment.stamp_duty_verified_by = instance.completed_by
            payment.save(update_fields=['stamp_duty_receipt_verified_at', 'stamp_duty_verified_by', 'updated_at'])
            
            logger.info(f"Stamp duty verified for {payment.internal_reference}")
    
    # If agreement step completed, update deposit status
    elif instance.code == "agreement":
        if not payment.metadata.get('deposit_paid'):
            payment.metadata['deposit_paid'] = True
            payment.save(update_fields=['metadata', 'updated_at'])
            logger.info(f"Deposit marked as paid for {payment.internal_reference}")
    
    # If completion_docs step completed, update balance status
    elif instance.code == "completion_docs":
        if not payment.metadata.get('balance_paid'):
            payment.metadata['balance_paid'] = True
            payment.save(update_fields=['metadata', 'updated_at'])
            logger.info(f"Balance marked as paid for {payment.internal_reference}")
    
    # If reports step completed, mark reports as sent
    elif instance.code == "reports":
        if not payment.reports_sent_at:
            payment.reports_sent_at = timezone.now()
            payment.save(update_fields=['reports_sent_at', 'updated_at'])
            logger.info(f"Transaction reports sent for {payment.internal_reference}")


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


@receiver(post_save, sender=PaymentRequest)
def auto_generate_transaction_reports(sender, instance, created, **kwargs):
    """
    Automatically generate and send transaction reports when:
    - Funds are disbursed (reports_sent_at is set)
    - Or when explicitly triggered
    """
    if instance.disbursed_at and not instance.reports_sent_at:
        # This will trigger the report generation via the notification service
        from notifications.notification_service import NotificationService
        NotificationService.send_transaction_completion_reports(instance)
        
        logger.info(f"Auto-generated transaction reports for {instance.internal_reference}")


@receiver(post_save, sender=PaymentRequest)
def sync_plot_market_status(sender, instance, created, **kwargs):
    """
    Ensure plot market status is synced with payment state.
    This handles edge cases where the payment status changes without 
    the plot being updated.
    """
    if instance.plot and not created:
        # Check if market status needs updating
        if instance.purchase_registration_complete and instance.disbursed_at:
            if instance.plot.market_status != "sold":
                instance.sync_plot_market_state()
                logger.info(f"Synced plot {instance.plot.id} market status to 'sold' via payment {instance.internal_reference}")
        
        elif instance.status in [PaymentRequest.Status.REFUNDED, PaymentRequest.Status.CANCELLED, PaymentRequest.Status.FAILED]:
            if instance.plot.market_status != "available":
                instance.sync_plot_market_state()
                logger.info(f"Synced plot {instance.plot.id} market status to 'available' via payment {instance.internal_reference}")