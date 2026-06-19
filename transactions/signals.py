from payments.models import PaymentRequest
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
import logging

from transactions.models import Transaction, TransactionMilestone

logger = logging.getLogger(__name__)


@receiver(post_save, sender="payments.PaymentRequest")
def auto_start_transaction(sender, instance, **kwargs):
    """
    Automatically creates or updates a Transaction record when a Purchase payment is confirmed.
    Integrates with payment stages (agreement deposit, completion balance, etc.)
    """
    # GUARD: Prevent re-entry
    if getattr(instance, '_auto_transaction_processing', False):
        return
    
    try:
        instance._auto_transaction_processing = True
        _auto_start_transaction_logic(sender, instance, **kwargs)
    finally:
        instance._auto_transaction_processing = False


def _auto_start_transaction_logic(sender, instance, **kwargs):
    """Actual logic for auto_start_transaction with recursion prevention"""
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
            balance_paid=0,
            stage=Transaction.Stage.DUE_DILIGENCE,
            payment_request=instance,
            transaction_type=Transaction.TransactionType.PURCHASE,
        )
        created = True
        # Use update to avoid triggering signals again
        PaymentRequest.objects.filter(pk=instance.pk).update(legal_transaction=transaction)
        instance.legal_transaction = transaction
        
        # Add event for transaction creation
        transaction.add_event(
            'transaction_created',
            f"Legal transaction created from payment {instance.internal_reference}",
            actor=instance.buyer
        )
    
    # If transaction already exists but not linked to payment, link it
    if not created and not transaction.payment_request:
        transaction.payment_request = instance
        transaction.save(update_fields=["payment_request", "updated_at"])
        # Use update to avoid triggering signals again
        PaymentRequest.objects.filter(pk=instance.pk).update(legal_transaction=transaction)
        instance.legal_transaction = transaction
        logger.info(f"Linked existing legal transaction {transaction.id} to payment {instance.internal_reference}")
    
    # Track payment amount based on category
    if instance.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
        # This is the 10% agreement deposit held in escrow
        transaction.deposit_paid = instance.amount
        transaction.deposit_held_in_escrow_at = timezone.now()
        transaction.balance_due = transaction.agreed_price - (transaction.deposit_paid + transaction.balance_paid)
        
        # If this is the first payment and transaction was just created, advance to DUE_DILIGENCE or COMMITMENT
        if created:
            milestone_notes = (
                f"10% Agreement deposit of KES {instance.amount:,.2f} received and held in escrow. "
                f"Reference: {instance.internal_reference}. "
                f"Legal transaction created. Please upload required due diligence documents to proceed."
            )
            TransactionMilestone.objects.create(
                transaction=transaction,
                milestone_type=TransactionMilestone.MilestoneType.DUE_DILIGENCE,
                achieved_by=instance.buyer,
                notes=milestone_notes
            )
            logger.info(f"Created legal transaction {transaction.id} for payment {instance.internal_reference}")
        
        transaction.save(update_fields=["deposit_paid", "deposit_held_in_escrow_at", "balance_due", "updated_at"])
        
        # Add milestone for deposit payment
        milestone_notes = (
            f"10% Agreement deposit of KES {instance.amount:,.2f} paid and held in escrow. "
            f"Reference: {instance.internal_reference}. "
            f"Total deposit in escrow: KES {transaction.deposit_paid:,.2f}. "
            f"Remaining balance: KES {transaction.balance_due:,.2f}."
        )
        TransactionMilestone.objects.create(
            transaction=transaction,
            milestone_type=TransactionMilestone.MilestoneType.CONTRACTS,
            achieved_by=instance.buyer,
            notes=milestone_notes
        )
        
        # Update payment metadata to reflect deposit is in escrow
        payment_metadata = dict(instance.metadata or {})
        payment_metadata['deposit_paid'] = True
        payment_metadata['deposit_paid_at'] = timezone.now().isoformat()
        payment_metadata['transaction_id'] = transaction.id
        instance.metadata = payment_metadata
        # Use update to avoid triggering signals again
        PaymentRequest.objects.filter(pk=instance.pk).update(metadata=payment_metadata)
        
        # Send notification to buyer and seller
        from notifications.notification_service import NotificationService
        NotificationService.create_notification(
            user=transaction.buyer,
            notification_type="deposit_held",
            title=f"10% Deposit Held in Escrow - {transaction.plot.title}",
            message=f"Your deposit of KES {instance.amount:,.2f} is now securely held in escrow pending registration."
        )
        NotificationService.create_notification(
            user=transaction.seller,
            notification_type="deposit_received",
            title=f"Deposit Received in Escrow - {transaction.plot.title}",
            message=f"Buyer has paid KES {instance.amount:,.2f} into escrow. Funds will be released after registration."
        )
        
        logger.info(f"Agreement deposit recorded in escrow for transaction {transaction.id}: KES {instance.amount:,.2f}")
        
    elif instance.category == PaymentRequest.Category.COMPLETION_BALANCE:
        # This is the 90% completion balance held in escrow
        transaction.balance_paid = instance.amount
        transaction.balance_held_in_escrow_at = timezone.now()
        transaction.balance_due = transaction.agreed_price - (transaction.deposit_paid + transaction.balance_paid)
        transaction.save(update_fields=["balance_paid", "balance_held_in_escrow_at", "balance_due", "updated_at"])
        
        # Add milestone for balance payment
        milestone_notes = (
            f"90% Completion balance of KES {instance.amount:,.2f} paid and held in escrow. "
            f"Reference: {instance.internal_reference}. "
            f"Total held in escrow: KES {transaction.deposit_paid + transaction.balance_paid:,.2f}. "
            f"Remaining balance: KES {transaction.balance_due:,.2f}."
        )
        TransactionMilestone.objects.create(
            transaction=transaction,
            milestone_type=TransactionMilestone.MilestoneType.TAXATION,
            achieved_by=instance.buyer,
            notes=milestone_notes
        )
        
        # Update payment metadata to reflect balance is in escrow
        payment_metadata = dict(instance.metadata or {})
        payment_metadata['balance_paid'] = True
        payment_metadata['balance_paid_at'] = timezone.now().isoformat()
        payment_metadata['transaction_id'] = transaction.id
        instance.metadata = payment_metadata
        # Use update to avoid triggering signals again
        PaymentRequest.objects.filter(pk=instance.pk).update(metadata=payment_metadata)
        
        # Send notification
        from notifications.notification_service import NotificationService
        NotificationService.create_notification(
            user=transaction.buyer,
            notification_type="balance_held",
            title=f"90% Balance Held in Escrow - {transaction.plot.title}",
            message=f"Your balance payment of KES {instance.amount:,.2f} is now securely held in escrow. Proceed with registration."
        )
        NotificationService.create_notification(
            user=transaction.seller,
            notification_type="balance_received",
            title=f"Balance Received in Escrow - {transaction.plot.title}",
            message=f"Buyer has paid the 90% balance of KES {instance.amount:,.2f} into escrow. Complete registration to receive funds."
        )
        
        logger.info(f"Completion balance recorded in escrow for transaction {transaction.id}: KES {instance.amount:,.2f}")
    
    # Try to auto-advance the transaction stage if possible based on payment update
    try:
        can_advance, message = transaction.can_advance_to_next_stage()
        if can_advance:
            transaction.advance_stage(actor=instance.buyer)
            logger.info(f"Transaction {transaction.id} auto-advanced to {transaction.get_stage_display()} after payment update")
        else:
            logger.info(f"Transaction {transaction.id} cannot advance: {message}")
    except Exception as e:
        logger.warning(f"Could not auto-advance transaction {transaction.id}: {e}")    
    # Add event to payment - but don't save again
    # Use a direct DB update to avoid signal recursion
    from payments.models import PaymentEvent
    PaymentEvent.objects.create(
        payment=instance,
        event_type="legal_transaction_updated",
        message=(
            f"Legal transaction {transaction.id} updated. Deposit in escrow: KES {transaction.deposit_paid:,.2f}, "
            f"Balance in escrow: KES {transaction.balance_paid:,.2f}, "
            f"Balance due: KES {transaction.balance_due:,.2f}"
        ),
        actor=instance.buyer
    )


@receiver(post_save, sender="payments.PaymentRequest")
def auto_update_transaction_on_disbursement(sender, instance, **kwargs):
    """
    When a payment request is disbursed (funds released to seller),
    update the associated legal transaction.
    """
    # GUARD: Prevent re-entry
    if getattr(instance, '_disbursement_sync_processing', False):
        return
    
    try:
        instance._disbursement_sync_processing = True
        _auto_update_transaction_on_disbursement_logic(sender, instance, **kwargs)
    finally:
        instance._disbursement_sync_processing = False


def _auto_update_transaction_on_disbursement_logic(sender, instance, **kwargs):
    """Actual logic for auto_update_transaction_on_disbursement with recursion prevention"""
    from payments.models import PaymentRequest
    from .models import Transaction
    
    if instance.transaction_type != PaymentRequest.TransactionType.PURCHASE:
        return
    
    # Check if this is the disbursement event
    if instance.disbursed_at and instance.metadata.get('disbursement_triggered'):
        transaction = Transaction.objects.filter(payment_request=instance).first()
        
        if transaction and transaction.stage != Transaction.Stage.DISBURSEMENT:
            try:
                # Advance to disbursement stage if not already there
                if transaction.stage == Transaction.Stage.REGISTRATION:
                    transaction.advance_stage(actor=instance.buyer)
                elif transaction.stage != Transaction.Stage.DISBURSEMENT:
                    # Force update to disbursement stage
                    transaction.stage = Transaction.Stage.DISBURSEMENT
                    transaction.disbursed_at = instance.disbursed_at
                    transaction.platform_fee_deducted_at = instance.platform_fee_deducted_at
                    transaction.platform_fee_amount = instance.platform_fee_amount
                    transaction.seller_net_amount = instance.seller_net_amount
                    transaction.save(update_fields=[
                        'stage', 'disbursed_at', 'platform_fee_deducted_at',
                        'platform_fee_amount', 'seller_net_amount', 'updated_at'
                    ])
                    
                    TransactionMilestone.objects.create(
                        transaction=transaction,
                        milestone_type=TransactionMilestone.MilestoneType.DISBURSEMENT,
                        achieved_by=instance.buyer,
                        notes=(
                            f"Funds disbursed to seller. Platform fee: KES {instance.platform_fee_amount:,.2f}, "
                            f"Seller net: KES {instance.seller_net_amount:,.2f}"
                        )
                    )
                    
                    logger.info(f"Transaction {transaction.id} updated to DISBURSEMENT stage")
                    
            except Exception as e:
                logger.warning(f"Could not update transaction on disbursement: {e}")


@receiver(post_save, sender="transactions.Transaction")
def sync_transaction_stage_to_payment(sender, instance, **kwargs):
    """
    When a legal transaction advances stage, sync relevant information back to payment.
    This ensures payment and legal workflows stay aligned.
    """
    # GUARD: Prevent re-entry
    if getattr(instance, '_sync_to_payment_processing', False):
        return
    
    try:
        instance._sync_to_payment_processing = True
        
        if not instance.payment_request:
            return
        
        payment = instance.payment_request
        payment_metadata = dict(payment.metadata or {})
        
        # Map transaction stage to payment metadata
        stage_mapping = {
            Transaction.Stage.DUE_DILIGENCE: 'legal_due_diligence_completed',
            Transaction.Stage.COMMITMENT: 'legal_commitment_completed',
            Transaction.Stage.CONTRACTS: 'legal_contracts_completed',
            Transaction.Stage.STATUTORY_CONSENTS: 'legal_consents_completed',
            Transaction.Stage.TAXATION: 'legal_taxation_completed',
            Transaction.Stage.REGISTRATION: 'legal_registration_completed',
            Transaction.Stage.DISBURSEMENT: 'legal_disbursement_completed',
            Transaction.Stage.COMPLETED: 'legal_completed',
        }
        
        if instance.stage in stage_mapping:
            payment_metadata[stage_mapping[instance.stage]] = timezone.now().isoformat()
        
        # Sync stamp duty verification (paid to KRA)
        if instance.stamp_duty_receipt_verified_at:
            payment_metadata['stamp_duty_receipt_verified_at'] = instance.stamp_duty_receipt_verified_at.isoformat()
            payment_metadata['stamp_duty_receipt_number'] = instance.stamp_duty_receipt_number
        
        # Sync disbursement information
        if instance.disbursed_at:
            payment_metadata['disbursed_at'] = instance.disbursed_at.isoformat()
            payment_metadata['platform_fee_amount'] = str(instance.platform_fee_amount)
            payment_metadata['seller_net_amount'] = str(instance.seller_net_amount)
        
        # Use update to avoid triggering signals again
        PaymentRequest.objects.filter(pk=payment.pk).update(metadata=payment_metadata)
        
        logger.info(f"Synced transaction {instance.id} stage {instance.stage} to payment {payment.internal_reference}")
    
    finally:
        instance._sync_to_payment_processing = False


@receiver(post_save, sender="transactions.TransactionDocument")
def sync_document_verification_to_payment(sender, instance, **kwargs):
    """
    When a legal document is verified, update the associated payment's closing step.
    This links legal document verification with payment step completion.
    """
    # GUARD: Prevent re-entry
    if getattr(instance, '_doc_sync_processing', False):
        return
    
    try:
        instance._doc_sync_processing = True
        
        if not instance.transaction or not instance.transaction.payment_request:
            return
        
        payment = instance.transaction.payment_request
        
        # Map document type to payment closing step
        doc_to_step = {
            'OFFICIAL_SEARCH': 'due_diligence',
            'SURVEY_MAP': 'due_diligence',
            'LETTER_OF_OFFER': 'offer',
            'SALE_AGREEMENT': 'agreement',
            'LCB_CONSENT': 'lcb_consent',
            'SPOUSAL_CONSENT': 'lcb_consent',
            'STAMP_DUTY_RECEIPT': 'stamp_duty',
            'VALUATION_REPORT': 'stamp_duty',
            'TRANSFER_FORM': 'completion_docs',
            'ORIGINAL_TITLE_DEED': 'completion_docs',
            'NEW_TITLE_DEED': 'registration',
        }
        
        step_code = doc_to_step.get(instance.document_type)
        if step_code and instance.status == 'verified':
            from payments.models import PaymentClosingStep
            closing_step = payment.closing_steps.filter(code=step_code).first()
            if closing_step and closing_step.status != PaymentClosingStep.Status.COMPLETED:
                # Check if all documents for this step are verified
                required_docs = instance.transaction.get_required_documents_for_stage()
                all_verified = True
                
                for doc_type in required_docs:
                    doc = instance.transaction.documents.filter(
                        document_type=doc_type,
                        status='verified'
                    ).first()
                    if not doc:
                        all_verified = False
                        break
                
                if all_verified:
                    try:
                        closing_step.set_status(
                            PaymentClosingStep.Status.COMPLETED,
                            actor=instance.verified_by,
                            notes=f"All legal documents verified for {closing_step.display_title}"
                        )
                        logger.info(f"Auto-completed payment step {step_code} for {payment.internal_reference}")
                    except Exception as e:
                        logger.warning(f"Could not auto-complete payment step: {e}")
                    
                    # ============================================================
                    # AUTO-ADVANCE: Try to advance the transaction stage
                    # This covers the case where payment was already confirmed
                    # and this document verification was the last missing piece.
                    # ============================================================
                    transaction = instance.transaction
                    try:
                        can_advance, advance_msg = transaction.can_advance_to_next_stage()
                        if can_advance:
                            transaction.advance_stage(actor=instance.verified_by)
                            logger.info(
                                f"🚀 Auto-advanced transaction {transaction.id} to "
                                f"{transaction.get_stage_display()} after document verification"
                            )
                        else:
                            logger.info(
                                f"⏳ Transaction {transaction.id} cannot advance yet: {advance_msg}"
                            )
                    except Exception as e:
                        logger.warning(f"Could not auto-advance transaction {transaction.id}: {e}")
    
    finally:
        instance._doc_sync_processing = False


@receiver(post_save, sender="transactions.Transaction")
def auto_trigger_payment_disbursement(sender, instance, **kwargs):
    """
    When a legal transaction reaches the REGISTRATION stage (new title issued),
    automatically trigger the payment disbursement.
    """
    # GUARD: Prevent re-entry
    if getattr(instance, '_disbursement_trigger_processing', False):
        return
    
    try:
        instance._disbursement_trigger_processing = True
        
        # Check if we just advanced to REGISTRATION stage
        if not hasattr(instance, '_previous_stage'):
            try:
                original = Transaction.objects.get(pk=instance.pk)
                previous_stage = original.stage
            except Transaction.DoesNotExist:
                previous_stage = None
        else:
            previous_stage = getattr(instance, '_previous_stage', None)
        
        # If we just advanced to REGISTRATION stage, trigger disbursement
        if (instance.stage == Transaction.Stage.REGISTRATION and 
            previous_stage != Transaction.Stage.REGISTRATION and
            instance.payment_request):
            
            payment = instance.payment_request
            
            # Check if both deposit and balance are in escrow
            deposit_paid = payment.metadata.get('deposit_paid', False)
            balance_paid = payment.metadata.get('balance_paid', False)
            
            if deposit_paid and balance_paid and not payment.disbursed_at:
                logger.info(f"Registration complete for transaction {instance.id}, triggering disbursement for {payment.internal_reference}")
                
                try:
                    # Mark stamp duty as verified if receipt exists
                    if instance.stamp_duty_receipt_number and not payment.stamp_duty_receipt_verified_at:
                        PaymentRequest.objects.filter(pk=payment.pk).update(
                            stamp_duty_receipt_verified_at=timezone.now(),
                            stamp_duty_receipt_number=instance.stamp_duty_receipt_number
                        )
                    
                    # Trigger disbursement using a separate method to avoid signal recursion
                    _trigger_payment_disbursement_safely(payment, instance.buyer)
                    
                except Exception as e:
                    logger.error(f"Failed to auto-disburse for {payment.internal_reference}: {e}")
    
    finally:
        instance._disbursement_trigger_processing = False


def _trigger_payment_disbursement_safely(payment, actor):
    """
    Safely trigger payment disbursement without causing signal recursion.
    """
    # Mark disbursement as in progress to prevent recursion
    payment_metadata = dict(payment.metadata or {})
    payment_metadata['disbursement_triggered'] = True
    PaymentRequest.objects.filter(pk=payment.pk).update(
        disbursed_at=timezone.now(),
        platform_fee_deducted_at=timezone.now(),
        metadata=payment_metadata
    )
    
    # Use a direct update to set status to RELEASED
    PaymentRequest.objects.filter(pk=payment.pk).update(
        status=PaymentRequest.Status.RELEASED,
        released_at=timezone.now()
    )
    
    logger.info(f"Funds disbursed for {payment.internal_reference}")
    
    
# ============================================================
# RESERVE PLOT WHEN LEGAL TRANSACTION IS CREATED
# ============================================================
@receiver(post_save, sender="transactions.Transaction")
def reserve_plot_on_transaction_creation(sender, instance, created, **kwargs):
    """
    When a legal transaction is created (NOT updated), mark the plot as 'reserved' 
    so it disappears from the general marketplace and can't be bought by others.
    """
    if created:
        plot = instance.plot
        if plot.market_status != 'reserved':
            plot.market_status = 'reserved'
            plot.availability_notes = (
                f"Reserved under legal transaction #{instance.id} by {instance.buyer.username} "
                f"on {timezone.now().strftime('%Y-%m-%d %H:%M')}."
            )
            plot.save(update_fields=['market_status', 'availability_notes'])
            logger.info(f"✅ [reserve_plot] Plot {plot.id} marked as 'reserved' for transaction {instance.id}.")