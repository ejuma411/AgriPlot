from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender="payments.PaymentRequest")
def auto_start_transaction(sender, instance, **kwargs):
    """
    Automatically creates or updates a Transaction record when a Purchase payment is confirmed.
    Integrates with payment stages (agreement deposit, completion balance, etc.)
    """
    from payments.models import PaymentRequest
    from .models import Transaction, TransactionMilestone, TransactionDocument
    
    # Only process purchase transactions
    if instance.transaction_type != PaymentRequest.TransactionType.PURCHASE:
        return
    
    # Check if payment is confirmed
    confirmed_statuses = {
        PaymentRequest.Status.PAID,
        PaymentRequest.Status.IN_ESCROW,
        PaymentRequest.Status.PARTIALLY_RELEASED,
        PaymentRequest.Status.RELEASED,
    }
    
    if instance.status not in confirmed_statuses:
        return
    
    # Ensure plot exists
    if not instance.plot:
        logger.warning(f"Payment {instance.internal_reference} has no plot linked. Cannot create legal transaction.")
        return
    
    # Determine seller
    seller_user = instance.seller
    if not seller_user and getattr(instance.plot, "landowner", None):
        seller_user = instance.plot.landowner.user
    if not seller_user and getattr(instance.plot, "agent", None):
        seller_user = instance.plot.agent.user
    
    if not seller_user:
        logger.warning(f"Payment {instance.internal_reference} has no seller identified.")
        return
    
    # Calculate agreed price (use plot sale price or payment amount)
    agreed_price = getattr(instance.plot, "sale_price", None) or instance.amount
    
    # Find existing legal transaction for this payment first
    transaction = Transaction.objects.filter(payment_request=instance).first()
    created = False
    
    if not transaction:
        # Check if there is an active transaction for this plot and buyer
        transaction = Transaction.objects.filter(
            plot=instance.plot,
            buyer=instance.buyer
        ).exclude(stage=Transaction.Stage.CANCELLED).first()
        
    if not transaction:
        # Create a new legal transaction
        transaction = Transaction.objects.create(
            plot=instance.plot,
            buyer=instance.buyer,
            seller=seller_user,
            agreed_price=agreed_price,
            deposit_paid=0,
            stage=Transaction.Stage.DUE_DILIGENCE,
            payment_request=instance,
            transaction_type=Transaction.TransactionType.PURCHASE,
        )
        created = True
    
    # If transaction already exists but not linked to payment, link it
    if not created and not transaction.payment_request:
        transaction.payment_request = instance
        transaction.save(update_fields=["payment_request", "updated_at"])
        logger.info(f"Linked existing legal transaction {transaction.id} to payment {instance.internal_reference}")
    
    # Track payment amount based on category
    previous_deposit = transaction.deposit_paid
    
    if instance.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
        # This is the 10% agreement deposit
        transaction.deposit_paid = instance.amount
        transaction.balance_due = transaction.agreed_price - transaction.deposit_paid
        
        # If this is the first payment and transaction was just created, advance to COMMITMENT or CONTRACTS
        if created:
            # After commitment fee, transaction should be at DUE_DILIGENCE or COMMITMENT
            # We don't auto-advance here - user must upload documents first
            milestone_notes = (
                f"Payment received: {instance.get_category_display()} of KES {instance.amount:,.2f}. "
                f"Reference: {instance.internal_reference}. "
                f"Legal transaction created. Please upload required documents to proceed."
            )
            TransactionMilestone.objects.create(
                transaction=transaction,
                milestone_type=TransactionMilestone.MilestoneType.DUE_DILIGENCE,
                notes=milestone_notes
            )
            logger.info(f"Created legal transaction {transaction.id} for payment {instance.internal_reference}")
        
        transaction.save(update_fields=["deposit_paid", "balance_due", "updated_at"])
        
        # Add milestone for deposit payment
        milestone_notes = (
            f"Agreement deposit of KES {instance.amount:,.2f} paid. "
            f"Reference: {instance.internal_reference}. "
            f"Total deposit now: KES {transaction.deposit_paid:,.2f}. "
            f"Remaining balance: KES {transaction.balance_due:,.2f}."
        )
        TransactionMilestone.objects.create(
            transaction=transaction,
            milestone_type=TransactionMilestone.MilestoneType.CONTRACTS,
            notes=milestone_notes
        )
        
        # Send notification to buyer and seller
        from notifications.notification_service import NotificationService
        NotificationService.notify_transaction_updated(transaction, "deposit_paid", instance.amount)
        
        logger.info(f"Agreement deposit recorded for transaction {transaction.id}: KES {instance.amount:,.2f}")
        
    elif instance.category == PaymentRequest.Category.COMPLETION_BALANCE:
        # This is the 90% completion balance
        transaction.deposit_paid += instance.amount
        if transaction.deposit_paid > transaction.agreed_price:
            transaction.deposit_paid = transaction.agreed_price
        transaction.balance_due = transaction.agreed_price - transaction.deposit_paid
        transaction.save(update_fields=["deposit_paid", "balance_due", "updated_at"])
        
        # Add milestone for balance payment
        milestone_notes = (
            f"Completion balance of KES {instance.amount:,.2f} paid. "
            f"Reference: {instance.internal_reference}. "
            f"Total paid: KES {transaction.deposit_paid:,.2f}. "
            f"Remaining balance: KES {transaction.balance_due:,.2f}."
        )
        TransactionMilestone.objects.create(
            transaction=transaction,
            milestone_type=TransactionMilestone.MilestoneType.TAXATION,
            notes=milestone_notes
        )
        
        # Send notification
        from notifications.notification_service import NotificationService
        NotificationService.notify_transaction_updated(transaction, "completion_paid", instance.amount)
        
        logger.info(f"Completion balance recorded for transaction {transaction.id}: KES {instance.amount:,.2f}")
        
    elif instance.category == PaymentRequest.Category.COMMITMENT_FEE:
        # Commitment fee - creates transaction but no deposit recorded
        milestone_notes = (
            f"Commitment fee of KES {instance.amount:,.2f} paid. "
            f"Reference: {instance.internal_reference}. "
            f"Transaction initiated. Please upload due diligence documents to proceed."
        )
        TransactionMilestone.objects.create(
            transaction=transaction,
            milestone_type=TransactionMilestone.MilestoneType.DUE_DILIGENCE,
            notes=milestone_notes
        )
        logger.info(f"Commitment fee recorded for transaction {transaction.id}: KES {instance.amount:,.2f}")
    
    # If deposit is fully paid (100%), automatically advance to TAXATION stage
    if transaction.deposit_paid >= transaction.agreed_price and transaction.stage == Transaction.Stage.CONTRACTS:
        try:
            transaction.advance_stage(actor=instance.buyer)
            logger.info(f"Transaction {transaction.id} auto-advanced to TAXATION after full payment")
        except Exception as e:
            logger.warning(f"Could not auto-advance transaction {transaction.id}: {e}")
    
    # Add event to payment
    instance.add_event(
        "legal_transaction_updated",
        f"Legal transaction {transaction.id} updated. Deposit paid: KES {transaction.deposit_paid:,.2f}, "
        f"Balance due: KES {transaction.balance_due:,.2f}",
        actor=instance.buyer
    )


