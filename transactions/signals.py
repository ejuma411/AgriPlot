from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender="payments.PaymentRequest")
def auto_start_transaction(sender, instance, **kwargs):
    from payments.models import PaymentRequest
    from .models import Transaction, TransactionMilestone
    """
    Automatically creates a Transaction record when a Purchase payment is confirmed.
    """
    if instance.transaction_type == PaymentRequest.TransactionType.PURCHASE:
        # Only start transaction if payment is confirmed (Paid or In Escrow)
        confirmed_statuses = {
            PaymentRequest.Status.PAID,
            PaymentRequest.Status.IN_ESCROW,
        }
        
        if instance.status in confirmed_statuses:
            # Check if a transaction already exists for this plot and buyer
            transaction, created = Transaction.objects.get_or_create(
                plot=instance.plot,
                buyer=instance.buyer,
                defaults={
                    "seller": instance.seller or instance.plot.landowner.user,
                    "agreed_price": instance.plot.sale_price or instance.amount,
                    "deposit_paid": instance.amount if instance.category == PaymentRequest.Category.AGREEMENT_DEPOSIT else 0,
                    "stage": Transaction.Stage.DUE_DILIGENCE,
                }
            )
            
            if created:
                # Add initial milestone
                TransactionMilestone.objects.create(
                    transaction=transaction,
                    stage=Transaction.Stage.DUE_DILIGENCE,
                    notes="Transaction automatically initiated following confirmed purchase payment."
                )
                
                # Update deposit if this was an agreement deposit
                if instance.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
                    transaction.deposit_paid = instance.amount
                    transaction.balance_due = transaction.agreed_price - instance.amount
                    transaction.save(update_fields=["deposit_paid", "balance_due"])
