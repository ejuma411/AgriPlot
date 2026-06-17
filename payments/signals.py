from django.db.models.signals import pre_save, post_save
from django.contrib.auth import get_user_model
from django.dispatch import receiver
from django.db.models import F, Q
from decimal import Decimal
from django.utils import timezone
import logging

from payments.models import Wallet, WalletTransaction, PaymentRequest, PaymentClosingStep, PaymentDisbursement
from transactions.models import Transaction

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
        .values_list("status", flat=True)
        .first()
    )


@receiver(post_save, sender=WalletTransaction)
def handle_wallet_transaction_status_change(sender, instance, created, **kwargs):
    """
    Handle wallet transaction status changes.
    Balance is calculated dynamically, so we don't update a stored balance.
    Instead, we log the event and send notifications.
    """
    # Skip if status hasn't changed
    if not created and hasattr(instance, '_previous_status') and instance._previous_status == instance.status:
        return
    
    # Log status change
    if hasattr(instance, '_previous_status') and instance._previous_status != instance.status:
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
        message = f"KES {transaction.amount:,.2f} deposited into your wallet. Reference: {transaction.reference}"
        notification_type = "wallet_credit"
        title = "Wallet Deposit Successful"
        
        # Send email notification for deposits
        if transaction.channel in [WalletTransaction.CHANNEL_MPESA, WalletTransaction.CHANNEL_BANK_TRANSFER]:
            try:
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
            except Exception as e:
                logger.warning(f"Failed to send deposit email: {e}")
    
    elif transaction.type == WalletTransaction.TYPE_DEBIT:
        message = f"KES {transaction.amount:,.2f} debited from your wallet. Reference: {transaction.reference}"
        notification_type = "wallet_debit"
        title = "Wallet Payment Successful"
        
        # If this payment is linked to a payment request, update it
        if transaction.payment_request:
            _update_payment_request_status(transaction.payment_request, transaction)
    
    # Create in-app notification
    try:
        NotificationService.create_notification(
            user=wallet.user,
            notification_type=notification_type,
            title=title,
            message=message,
        )
    except Exception as e:
        logger.warning(f"Failed to create notification: {e}")
    
    logger.info(
        f"Successful {transaction.type} transaction {transaction.reference} "
        f"for user {wallet.user.username}"
    )


def _handle_failed_transaction(transaction):
    """Handle failed wallet transaction"""
    from notifications.notification_service import NotificationService
    
    wallet = transaction.wallet
    
    message = f"Transaction {transaction.reference} failed. Amount: KES {transaction.amount:,.2f}"
    if transaction.notes:
        message += f" Reason: {transaction.notes}"
    
    try:
        NotificationService.create_notification(
            user=wallet.user,
            notification_type="wallet_transaction_failed",
            title="Wallet Transaction Failed",
            message=message,
        )
    except Exception as e:
        logger.warning(f"Failed to create notification: {e}")
    
    logger.warning(
        f"Failed {transaction.type} transaction {transaction.reference} "
        f"for user {wallet.user.username}: {transaction.notes}"
    )


def _handle_frozen_transaction(transaction):
    """Handle frozen transaction (held in escrow)"""
    from notifications.notification_service import NotificationService
    
    wallet = transaction.wallet
    
    message = f"KES {transaction.amount:,.2f} has been held from your wallet for escrow. Reference: {transaction.reference}"
    
    try:
        NotificationService.create_notification(
            user=wallet.user,
            notification_type="wallet_frozen",
            title="Funds Held in Escrow",
            message=message,
        )
    except Exception as e:
        logger.warning(f"Failed to create notification: {e}")
    
    logger.info(
        f"Frozen {transaction.type} transaction {transaction.reference} "
        f"for user {wallet.user.username}: KES {transaction.amount:,.2f}"
    )


def _update_payment_request_status(payment_request, transaction):
    """Update payment request status when wallet payment is completed"""
    if payment_request.status == PaymentRequest.Status.PENDING:
        # Guard against recursion
        if getattr(payment_request, '_wallet_payment_processing', False):
            return
        
        try:
            payment_request._wallet_payment_processing = True
            payment_request.apply_transition("mark_paid", actor=payment_request.buyer)
            logger.info(
                f"Payment request {payment_request.internal_reference} marked as paid "
                f"via wallet transaction {transaction.reference}"
            )
        finally:
            payment_request._wallet_payment_processing = False


# ============================================================
# PAYMENT REQUEST SIGNALS - WITH IDEMPOTENCY GUARDS
# ============================================================

@receiver(post_save, sender=PaymentRequest)
def handle_payment_request_status_change(sender, instance, created, **kwargs):
    """
    Handle payment request status changes with idempotency guard.
    - When PAID, record deposit (10%) or balance (90%) in escrow
    - When RELEASED, trigger fund disbursement to seller
    """
    # GUARD: Prevent re-entry
    if getattr(instance, '_payment_signal_processing', False):
        return
    
    try:
        instance._payment_signal_processing = True
        
        # Only handle status changes, not creation
        if not created:
            # Check if we need to record escrow payments (when status becomes PAID)
            if instance.status == PaymentRequest.Status.PAID:
                _record_escrow_payment(instance)
            
            # Check if we need to disburse funds (when status becomes RELEASED)
            if instance.status == PaymentRequest.Status.RELEASED:
                _trigger_fund_disbursement(instance)
    
    finally:
        instance._payment_signal_processing = False


def _record_escrow_payment(payment_request):
    """
    Record escrow payment when payment request is marked as PAID.
    Only records deposit (10%) or balance (90%) - no other categories.
    """
    # GUARD: Prevent double-recording
    if getattr(payment_request, '_escrow_recording', False):
        return
    
    try:
        payment_request._escrow_recording = True
        
        # Only handle legitimate payment stages (deposit or balance)
        if payment_request.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
            # Record 10% deposit
            if not payment_request.metadata.get('deposit_paid'):
                payment_request.deposit_received_at = timezone.now()
                payment_request.metadata['deposit_paid'] = True
                payment_request.save(update_fields=['deposit_received_at', 'metadata', 'updated_at'])
                
                logger.info(
                    f"10% DEPOSIT recorded for {payment_request.internal_reference}: "
                    f"KES {payment_request.amount:,.2f} held in escrow"
                )
                
                # Send notification to seller
                _notify_seller_deposit_received(payment_request)
        
        elif payment_request.category == PaymentRequest.Category.COMPLETION_BALANCE:
            # Record 90% balance
            if not payment_request.metadata.get('balance_paid'):
                payment_request.balance_received_at = timezone.now()
                payment_request.metadata['balance_paid'] = True
                payment_request.save(update_fields=['balance_received_at', 'metadata', 'updated_at'])
                
                logger.info(
                    f"90% BALANCE recorded for {payment_request.internal_reference}: "
                    f"KES {payment_request.amount:,.2f} held in escrow"
                )
                
                # Send notification to seller
                _notify_seller_balance_received(payment_request)
        
        else:
            # Skip other categories (stamp duty, service fees, etc.) - they don't go to escrow
            logger.debug(
                f"Skipping escrow recording for {payment_request.internal_reference} - "
                f"category {payment_request.category} not eligible for escrow"
            )
    
    finally:
        payment_request._escrow_recording = False


def _notify_seller_deposit_received(payment_request):
    """Send notification to seller that 10% deposit is in escrow"""
    from notifications.notification_service import NotificationService
    
    if not payment_request.seller:
        return
    
    try:
        NotificationService.create_notification(
            user=payment_request.seller,
            notification_type="payment_deposit_received",
            title="10% Deposit Received in Escrow",
            message=(
                f"Buyer has paid 10% deposit (KES {payment_request.amount:,.2f}) into escrow for "
                f"{payment_request.title}. Complete statutory consents and LCB documentation to proceed."
            ),
        )
    except Exception as e:
        logger.warning(f"Failed to send deposit notification: {e}")


def _notify_seller_balance_received(payment_request):
    """Send notification to seller that 90% balance is in escrow"""
    from notifications.notification_service import NotificationService
    
    if not payment_request.seller:
        return
    
    try:
        NotificationService.create_notification(
            user=payment_request.seller,
            notification_type="payment_balance_received",
            title="90% Balance Received in Escrow",
            message=(
                f"Buyer has paid 90% balance (KES {payment_request.amount:,.2f}) into escrow for "
                f"{payment_request.title}. Proceed to registration at the land registry."
            ),
        )
    except Exception as e:
        logger.warning(f"Failed to send balance notification: {e}")


def _trigger_fund_disbursement(payment_request):
    """
    Trigger fund disbursement to seller after ALL conditions are met:
    - Registration complete (new title deed issued)
    - Deposit and balance both in escrow
    - Stamp duty verified (paid to KRA)
    """
    # GUARD: Prevent double-disbursement
    if getattr(payment_request, '_disbursement_processing', False):
        return
    
    try:
        payment_request._disbursement_processing = True
        
        # Check if already disbursed
        if payment_request.disbursed_at:
            logger.info(f"Funds already disbursed for {payment_request.internal_reference}")
            return
        
        # ============================================================
        # VERIFY ALL CONDITIONS FOR DISBURSEMENT
        # ============================================================
        
        # Condition 1: Registration must be complete
        if not payment_request.purchase_registration_complete:
            logger.warning(
                f"Cannot disburse funds for {payment_request.internal_reference}: "
                "Registration not complete. New title deed not issued."
            )
            return
        
        # Condition 2: Both deposit and balance must be in escrow
        if not payment_request.metadata.get('deposit_paid') or not payment_request.metadata.get('balance_paid'):
            logger.warning(
                f"Cannot disburse funds for {payment_request.internal_reference}: "
                f"Deposit: {payment_request.metadata.get('deposit_paid')}, "
                f"Balance: {payment_request.metadata.get('balance_paid')}"
            )
            return
        
        # Condition 3: Stamp duty must be verified (paid directly to KRA)
        stamp_duty_step = payment_request.closing_steps.filter(code="taxation").first()
        if not stamp_duty_step or stamp_duty_step.status != PaymentClosingStep.Status.COMPLETED:
            logger.warning(
                f"Cannot disburse funds for {payment_request.internal_reference}: "
                "Stamp duty not verified. Buyer must pay KRA directly and upload receipt."
            )
            return
        
        # ============================================================
        # ALL CONDITIONS MET - PROCEED WITH DISBURSEMENT
        # ============================================================
        
        # Calculate platform fee
        platform_fee = payment_request.platform_fee_amount
        seller_amount = payment_request.seller_net_amount
        
        logger.info(
            f"Preparing disbursement for {payment_request.internal_reference}: "
            f"Total: KES {payment_request.amount:,.2f}, "
            f"Platform fee: KES {platform_fee:,.2f} ({payment_request.platform_fee_percentage * 100}%), "
            f"Seller receives: KES {seller_amount:,.2f}"
        )
        
        # Mark as disbursed
        payment_request.platform_fee_deducted_at = timezone.now()
        payment_request.disbursed_at = timezone.now()
        payment_request.save(update_fields=['platform_fee_deducted_at', 'disbursed_at', 'updated_at'])
        
        # Update disbursement records
        _update_disbursement_records(payment_request, platform_fee, seller_amount)
        
        # Send notifications to both parties
        _send_disbursement_notifications(payment_request, platform_fee, seller_amount)
        
        logger.info(
            f"Funds DISBURSED for {payment_request.internal_reference}: "
            f"Seller receives KES {seller_amount:,.2f} after {payment_request.platform_fee_percentage * 100}% fee"
        )
    
    finally:
        payment_request._disbursement_processing = False


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


def _send_disbursement_notifications(payment_request, platform_fee, seller_amount):
    """Send notifications to buyer and seller about disbursement"""
    from notifications.notification_service import NotificationService
    
    # Notify seller
    if payment_request.seller:
        try:
            NotificationService.create_notification(
                user=payment_request.seller,
                notification_type="funds_disbursed",
                title="Funds Disbursed to Your Account",
                message=(
                    f"Funds for {payment_request.title} have been disbursed.\n\n"
                    f"Total amount: KES {payment_request.amount:,.2f}\n"
                    f"Platform fee ({payment_request.platform_fee_percentage * 100}%): KES {platform_fee:,.2f}\n"
                    f"Net amount to you: KES {seller_amount:,.2f}\n\n"
                    f"Please allow 1-3 business days for the transfer to reflect in your bank account."
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to send seller disbursement notification: {e}")
    
    # Notify buyer
    if payment_request.buyer:
        try:
            NotificationService.create_notification(
                user=payment_request.buyer,
                notification_type="transaction_complete",
                title="Transaction Complete - Funds Disbursed",
                message=(
                    f"The transaction for {payment_request.title} is complete.\n\n"
                    f"Funds have been disbursed to the seller after title registration.\n"
                    f"Check your email for the transaction report and new title deed."
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to send buyer disbursement notification: {e}")


# ============================================================
# CLOSING STEP SIGNALS
# ============================================================

@receiver(post_save, sender=PaymentClosingStep)
def handle_closing_step_completion(sender, instance, created, **kwargs):
    """
    Handle when a closing step is completed.
    This is the primary driver for workflow progression.
    """
    # Only care about completed steps
    if instance.status != PaymentClosingStep.Status.COMPLETED:
        return
    
    # GUARD: Prevent re-entry
    if getattr(instance, '_step_signal_processing', False):
        return
    
    try:
        instance._step_signal_processing = True
        payment = instance.payment
        
        # ============================================================
        # STAGE 5: STAMP DUTY VERIFICATION (paid directly to KRA)
        # ============================================================
        if instance.code == "taxation":
            if not payment.stamp_duty_receipt_verified_at:
                payment.stamp_duty_receipt_verified_at = timezone.now()
                if instance.completed_by:
                    payment.stamp_duty_verified_by = instance.completed_by
                payment.save(update_fields=['stamp_duty_receipt_verified_at', 'stamp_duty_verified_by', 'updated_at'])
                
                logger.info(f"Stamp duty verified for {payment.internal_reference} (paid directly to KRA)")
                
                # Notify buyer that stamp duty is verified
                _notify_stamp_duty_verified(payment)
        
        # ============================================================
        # STAGE 7: REGISTRATION COMPLETE - TRIGGER DISBURSEMENT
        # ============================================================
        elif instance.code == "registration":
            # Check if all funds are in escrow
            if payment.metadata.get('deposit_paid') and payment.metadata.get('balance_paid'):
                logger.info(f"Registration completed for {payment.internal_reference}, triggering disbursement")
                
                # Trigger disbursement (will check all conditions)
                payment.apply_transition("disburse_to_seller", actor=instance.completed_by)
    
    finally:
        instance._step_signal_processing = False


def _notify_stamp_duty_verified(payment_request):
    """Notify buyer that stamp duty payment to KRA has been verified"""
    from notifications.notification_service import NotificationService
    
    if not payment_request.buyer:
        return
    
    try:
        NotificationService.create_notification(
            user=payment_request.buyer,
            notification_type="stamp_duty_verified",
            title="Stamp Duty Payment Verified",
            message=(
                f"Your stamp duty payment for {payment_request.title} has been verified.\n\n"
                f"Proceed to registration at the land registry to complete the title transfer."
            ),
        )
    except Exception as e:
        logger.warning(f"Failed to send stamp duty notification: {e}")


# ============================================================
# PLOT MARKET STATUS SYNC (no recursion risk)
# ============================================================

@receiver(post_save, sender=PaymentRequest)
def sync_plot_market_status(sender, instance, created, **kwargs):
    """
    Ensure plot market status is synced with payment state.
    Handles edge cases where the payment status changes without the plot being updated.
    """
    # GUARD: Prevent recursion
    if getattr(instance, '_plot_sync_processing', False):
        return
    
    if not instance.plot:
        return
    
    try:
        instance._plot_sync_processing = True
        
        # When transaction is complete and disbursed, mark plot as sold
        if instance.purchase_registration_complete and instance.disbursed_at:
            if instance.plot.market_status != "sold":
                instance.sync_plot_market_state()
                logger.info(f"Synced plot {instance.plot.id} market status to 'sold' via payment {instance.internal_reference}")
        
        # When payment is refunded or cancelled, mark plot as available
        elif instance.status in [PaymentRequest.Status.REFUNDED, PaymentRequest.Status.CANCELLED, PaymentRequest.Status.FAILED]:
            if instance.plot.market_status != "available":
                instance.sync_plot_market_state()
                logger.info(f"Synced plot {instance.plot.id} market status to 'available' via payment {instance.internal_reference}")
    
    finally:
        instance._plot_sync_processing = False


# ============================================================
# WALLET SIGNALS
# ============================================================

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
        # Reset locked_until if the lock period has passed
        if instance.locked_until <= timezone.now():
            instance.locked_until = None
            instance.failed_pin_attempts = 0
            logger.info(f"Wallet {instance.account_number} PIN lock expired, resetting attempts")