from accounts.validators import validate_kenyan_phone
from agriplot import settings
import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Transaction, TransactionDocument, TransactionMilestone
from .forms import TransactionDocumentForm, TransactionAdvanceForm, AdvocateAssignmentForm
from payments.models import PaymentRequest, PaymentClosingStep
from payments.permissions import user_is_finance_admin, user_is_escrow_admin
from payments.wallet_service import WalletService
from listings.models import Plot

logger = logging.getLogger(__name__)


class TransactionDashboardView(LoginRequiredMixin, ListView):
    """Dashboard view for legal transactions"""
    model = Transaction
    template_name = "transactions/dashboard.html"
    context_object_name = "transactions"
    paginate_by = 12

    def get_queryset(self):
        if (self.request.user.is_staff or self.request.user.is_superuser or 
            user_is_finance_admin(self.request.user) or user_is_escrow_admin(self.request.user)):
            return Transaction.objects.all().select_related("plot", "buyer", "seller")
        return Transaction.objects.filter(
            Q(buyer=self.request.user) | Q(seller=self.request.user)
        ).select_related("plot", "buyer", "seller")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transactions = self.get_queryset()
        
        context["stats"] = {
            "total": transactions.count(),
            "active": transactions.exclude(
                stage__in=[Transaction.Stage.COMPLETED, Transaction.Stage.CANCELLED]
            ).count(),
            "completed": transactions.filter(stage=Transaction.Stage.COMPLETED).count(),
            "pending_verification": TransactionDocument.objects.filter(
                transaction__in=transactions,
                status='pending'
            ).count(),
        }
        
        context["is_finance_admin"] = user_is_finance_admin(self.request.user)
        context["is_escrow_admin"] = user_is_escrow_admin(self.request.user)
        
        return context


@login_required
def pay_installment(request, pk):
    """Create a payment request for a transaction installment."""
    if request.method != "POST":
        return redirect("transactions:detail", pk=pk)
    
    transaction = get_object_or_404(Transaction, pk=pk, buyer=request.user)
    
    if transaction.balance_due <= 0:
        messages.error(request, "This transaction has no outstanding balance.")
        return redirect("transactions:detail", pk=pk)

    linked_payment = transaction.payment_request or PaymentRequest.objects.filter(legal_transaction=transaction).first()
    if linked_payment:
        paid_statuses = {
            PaymentRequest.Status.PAID,
            PaymentRequest.Status.IN_ESCROW,
            PaymentRequest.Status.PARTIALLY_RELEASED,
            PaymentRequest.Status.RELEASED,
        }
        if linked_payment.status in paid_statuses:
            messages.info(
                request,
                f"This transaction's payment ({linked_payment.internal_reference}) has already been completed."
            )
        else:
            messages.info(
                request,
                f"You have a pending payment workspace ({linked_payment.internal_reference}). "
                f"Please complete your payment there."
            )
        return redirect("payments:detail", pk=linked_payment.pk)
    
    amount_str = request.POST.get("amount")
    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError()
        if amount > transaction.balance_due:
            messages.error(request, f"Amount cannot exceed the balance due of KES {transaction.balance_due:,.2f}.")
            return redirect("transactions:detail", pk=pk)
    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, "Please enter a valid amount.")
        return redirect("transactions:detail", pk=pk)
    
    if transaction.stage not in [Transaction.Stage.CONTRACTS, Transaction.Stage.COMPLETION]:
        messages.error(request, "Payments are only allowed at the contract deposit or completion stages.")
        return redirect('transactions:detail', pk=pk)

    if transaction.stage == Transaction.Stage.CONTRACTS:
        if transaction.deposit_paid == 0 and amount == transaction.ten_percent_deposit:
            category = PaymentRequest.Category.AGREEMENT_DEPOSIT
            payment_description = f"10% agreement deposit for {transaction.plot.title}"
        else:
            messages.error(request, "Invalid deposit amount. Exact 10% deposit required.")
            return redirect('transactions:detail', pk=pk)
    elif transaction.stage == Transaction.Stage.COMPLETION:
        if transaction.balance_due > 0 and amount == transaction.balance_due:
            category = PaymentRequest.Category.COMPLETION_BALANCE
            payment_description = f"Completion balance payment for {transaction.plot.title}"
        else:
            messages.error(request, "Invalid completion balance amount.")
            return redirect('transactions:detail', pk=pk)
    else:
        messages.error(request, "Unsupported payment stage.")
        return redirect('transactions:detail', pk=pk)
    
    payment = PaymentRequest.objects.create(
        transaction_type=PaymentRequest.TransactionType.PURCHASE,
        category=category,
        plot=transaction.plot,
        buyer=request.user,
        seller=transaction.seller,
        amount=amount,
        status=PaymentRequest.Status.PENDING,
        title=payment_description,
        description=f"Payment for legal transaction {transaction.id} - {payment_description}",
        escrow_enabled=(category in [PaymentRequest.Category.AGREEMENT_DEPOSIT, PaymentRequest.Category.COMPLETION_BALANCE]),
        legal_transaction=transaction,
    )
    transaction.payment_request = payment
    transaction.save(update_fields=["payment_request", "updated_at"])
    
    messages.success(request, f"Payment request created for KES {amount:,.2f}. Please complete the payment.")
    return redirect("payments:detail", pk=payment.pk)


# ============================================================
# ADVANCE STAGE - DEFINED AT TOP LEVEL
# ============================================================
@login_required
@require_http_methods(["POST"])
def advance_stage(request, pk):
    """Advance transaction to next legal stage."""
    logger.info(f"🚀 [advance_stage] Called: pk={pk}, user={request.user.username}")
    
    transaction = get_object_or_404(Transaction, pk=pk)
    logger.info(f"📋 [advance_stage] Transaction {pk}: stage={transaction.stage}, type={transaction.transaction_type}")
    
    if request.user not in [transaction.buyer, transaction.seller] and not request.user.is_staff:
        logger.warning(f"⛔ [advance_stage] Permission denied for user {request.user.username}")
        messages.error(request, "You don't have permission to advance this transaction")
        return redirect('transactions:detail', pk=pk)
    
    form = TransactionAdvanceForm(request.POST, transaction=transaction, user=request.user)
    
    if form.is_valid():
        try:
            with db_transaction.atomic():
                old_stage = transaction.stage
                step_code = None
                
                if transaction.transaction_type == Transaction.TransactionType.PURCHASE:
                    stage_to_step = {
                        Transaction.Stage.DUE_DILIGENCE: 'due_diligence',
                        Transaction.Stage.COMMITMENT: 'offer',
                        Transaction.Stage.CONTRACTS: 'agreement',
                        Transaction.Stage.STATUTORY_CONSENTS: 'lcb_consent',
                        Transaction.Stage.TAXATION: 'stamp_duty',
                        Transaction.Stage.COMPLETION: 'completion_docs',
                        Transaction.Stage.REGISTRATION: 'registration',
                        Transaction.Stage.DISBURSEMENT: 'disbursement',
                    }
                    step_code = stage_to_step.get(old_stage)
                
                step_to_complete = None
                can_advance_transaction = True
                
                # Check payment requirements before advancing
                if old_stage == Transaction.Stage.CONTRACTS and transaction.deposit_paid == 0:
                    logger.warning(f"⛔ Cannot advance CONTRACTS: deposit not paid")
                    messages.error(request, "❌ Cannot advance: 10% deposit payment is required before proceeding to statutory consents.")
                    return redirect('transactions:detail', pk=pk)
                
                if old_stage == Transaction.Stage.COMPLETION and transaction.balance_due > 0:
                    logger.warning(f"⛔ Cannot advance COMPLETION: balance due")
                    messages.error(request, "❌ Cannot advance: 90% completion balance is required before proceeding to registration.")
                    return redirect('transactions:detail', pk=pk)
                
                # Process LCB information
                if step_code == 'lcb_consent':
                    lcb_date = form.cleaned_data.get('lcb_meeting_date')
                    lcb_ref = form.cleaned_data.get('lcb_consent_reference')
                    if lcb_date:
                        transaction.lcb_meeting_date = lcb_date
                    if lcb_ref:
                        transaction.lcb_consent_reference = lcb_ref
                    transaction.save(update_fields=['lcb_meeting_date', 'lcb_consent_reference', 'updated_at'])
                
                # Process stamp duty (paid to KRA - platform never touches)
                if step_code == 'stamp_duty':
                    stamp_duty_rate = form.cleaned_data.get('stamp_duty_rate')
                    if stamp_duty_rate:
                        transaction.stamp_duty_percentage = Decimal(stamp_duty_rate)
                        transaction.stamp_duty_amount = transaction.agreed_price * (Decimal(stamp_duty_rate) / 100)
                        transaction.save(update_fields=['stamp_duty_percentage', 'stamp_duty_amount', 'updated_at'])
                    
                    receipt_number = form.cleaned_data.get('stamp_duty_receipt_number')
                    if receipt_number:
                        transaction.mark_stamp_duty_verified(receipt_number, request.user)
                        messages.info(request, f"Stamp duty payment to KRA verified. Receipt: {receipt_number}")
                    else:
                        messages.error(request, "Stamp duty receipt number is required to advance.")
                        return redirect('transactions:detail', pk=pk)
                
                # Process disbursement (escrow admin only)
                if step_code == 'disbursement':
                    if not user_is_escrow_admin(request.user):
                        messages.error(request, "Only escrow administrators can authorize fund disbursement.")
                        return redirect('transactions:detail', pk=pk)
                    
                    platform_fee_percentage = form.cleaned_data.get('platform_fee_percentage')
                    if platform_fee_percentage:
                        transaction.platform_fee_percentage = platform_fee_percentage
                        transaction.platform_fee_amount = transaction.agreed_price * (Decimal(platform_fee_percentage) / 100)
                        transaction.seller_net_amount = transaction.agreed_price - transaction.platform_fee_amount
                        transaction.save(update_fields=['platform_fee_percentage', 'platform_fee_amount', 'seller_net_amount', 'updated_at'])
                
                # Handle payment closing step confirmation
                if step_code and transaction.payment_request:
                    step = transaction.payment_request.closing_steps.filter(code=step_code).first()
                    if step and step.status != PaymentClosingStep.Status.COMPLETED:
                        confirmation_role = None
                        updated_fields = []

                        if request.user == transaction.buyer:
                            if not step.buyer_confirmed_at:
                                step.buyer_confirmed_at = timezone.now()
                                updated_fields.append("buyer_confirmed_at")
                            confirmation_role = "Buyer"
                        elif request.user == transaction.seller:
                            if not step.seller_confirmed_at:
                                step.seller_confirmed_at = timezone.now()
                                updated_fields.append("seller_confirmed_at")
                            confirmation_role = "Seller"

                        if updated_fields:
                            step.save(update_fields=updated_fields)
                        
                        if not step.can_mark_complete_with_current_evidence():
                            can_advance_transaction = False
                            if step_code == 'agreement':
                                if confirmation_role:
                                    messages.info(request, f"{confirmation_role} confirmation saved. Waiting for the other party to confirm the agreement.")
                                else:
                                    messages.info(request, "Please confirm the agreement to proceed.")
                        else:
                            step_to_complete = step
                
                # Advance transaction if allowed
                if can_advance_transaction:
                    success, message = transaction.advance_stage(actor=request.user)
                    
                    if success:
                        messages.success(request, f"🏛️ {message}")
                        
                        if transaction.stage == Transaction.Stage.CONTRACTS:
                            messages.info(request, f"💰 Contract stage reached. 10% deposit payment of KES {transaction.ten_percent_deposit:,.2f} is now required.")
                        elif transaction.stage == Transaction.Stage.TAXATION:
                            messages.info(request, "🏛️ Stamp Duty stage reached. Payment must be made directly to KRA via iTax.")
                        elif transaction.stage == Transaction.Stage.COMPLETION:
                            balance_amount = transaction.agreed_price - transaction.deposit_paid
                            messages.info(request, f"💰 Completion stage reached. Final payment of KES {balance_amount:,.2f} (90% balance) is now required.")
                        elif transaction.stage == Transaction.Stage.REGISTRATION:
                            messages.info(request, "📋 Registration stage reached. After the new title deed is issued, funds will be automatically disbursed.")
                        elif transaction.stage == Transaction.Stage.COMPLETED:
                            messages.success(request, "🎉 Transaction completed!")
                        
                        # Send notifications
                        from notifications.notification_service import NotificationService
                        NotificationService.create_notification(
                            user=transaction.buyer,
                            notification_type="stage_advanced",
                            title=f"Transaction Advanced - {transaction.plot.title}",
                            message=f"Transaction has advanced to {transaction.get_stage_display()}."
                        )
                        NotificationService.create_notification(
                            user=transaction.seller,
                            notification_type="stage_advanced",
                            title=f"Transaction Advanced - {transaction.plot.title}",
                            message=f"Transaction has advanced to {transaction.get_stage_display()}."
                        )
                        
                        if step_to_complete:
                            step_to_complete.set_status(PaymentClosingStep.Status.COMPLETED, actor=request.user)
                            messages.info(request, f"Payment workspace step '{step_to_complete.display_title}' automatically completed.")
                    else:
                        messages.error(request, f"❌ Cannot advance: {message}")
                    
        except ValidationError as e:
            messages.error(request, f"❌ Legal validation failed: {str(e)}")
            return redirect('transactions:detail', pk=pk)
        except Exception as e:
            logger.exception(f"Error advancing transaction: {e}")
            messages.error(request, f"❌ Failed to advance: {str(e)}")
            return redirect('transactions:detail', pk=pk)
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field}: {error}")
    
    return redirect('transactions:detail', pk=pk)


# ============================================================
# ASSIGN ADVOCATES
# ============================================================
@login_required
@require_http_methods(["POST"])
def assign_advocates(request, pk):
    """
    Assign advocates to a transaction.
    Required under Kenyan law (Advocates Act Cap 16) before sale agreement can be uploaded.
    """
    transaction = get_object_or_404(Transaction, pk=pk)
    
    # Check permissions (only buyer or seller can assign advocates)
    if request.user not in [transaction.buyer, transaction.seller] and not request.user.is_staff:
        messages.error(request, "You don't have permission to assign advocates to this transaction")
        return redirect('transactions:detail', pk=pk)
    
    form = AdvocateAssignmentForm(request.POST, transaction=transaction)
    
    if form.is_valid():
        try:
            with db_transaction.atomic():
                # Get the advocate IDs from the form
                buyer_advocate_id = form.cleaned_data.get('buyer_advocate_id')
                seller_advocate_id = form.cleaned_data.get('seller_advocate_id')
                
                # Validate that buyer and seller are not the same person
                if buyer_advocate_id and seller_advocate_id and buyer_advocate_id == seller_advocate_id:
                    messages.error(request, "Buyer and seller advocates cannot be the same person. Each party must have independent legal representation under the Advocates Act.")
                    return redirect('transactions:detail', pk=pk)
                
                # Assign buyer advocate
                if buyer_advocate_id:
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    buyer_advocate = User.objects.get(pk=buyer_advocate_id)
                    transaction.buyer_advocate = buyer_advocate
                    logger.info(f"✅ Buyer advocate {buyer_advocate.username} assigned to transaction {pk}")
                
                # Assign seller advocate
                if seller_advocate_id:
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    seller_advocate = User.objects.get(pk=seller_advocate_id)
                    transaction.seller_advocate = seller_advocate
                    logger.info(f"✅ Seller advocate {seller_advocate.username} assigned to transaction {pk}")
                
                transaction.save(update_fields=['buyer_advocate', 'seller_advocate', 'updated_at'])
                
                # Log the assignment
                transaction.add_event(
                    'advocates_assigned',
                    f"Advocates assigned - Buyer: {transaction.buyer_advocate.username if transaction.buyer_advocate else 'None'}, Seller: {transaction.seller_advocate.username if transaction.seller_advocate else 'None'}",
                    actor=request.user
                )
                
                # Send notifications
                from notifications.notification_service import NotificationService
                if transaction.buyer_advocate:
                    NotificationService.create_notification(
                        user=transaction.buyer_advocate,
                        notification_type="advocate_assigned",
                        title=f"You've been assigned as Buyer Advocate - {transaction.plot.title}",
                        message=f"You have been assigned as the buyer's advocate for transaction {transaction.id}. Please review the case."
                    )
                if transaction.seller_advocate:
                    NotificationService.create_notification(
                        user=transaction.seller_advocate,
                        notification_type="advocate_assigned",
                        title=f"You've been assigned as Seller Advocate - {transaction.plot.title}",
                        message=f"You have been assigned as the seller's advocate for transaction {transaction.id}. Please review the case."
                    )
                
                messages.success(request, "✅ Advocates assigned successfully. You can now upload the sale agreement.")
                
        except Exception as e:
            logger.exception(f"Error assigning advocates: {e}")
            messages.error(request, f"❌ Failed to assign advocates: {str(e)}")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field}: {error}")
    
    return redirect('transactions:detail', pk=pk)


# ============================================================
# VERIFY DOCUMENT
# ============================================================
@login_required
@require_http_methods(["POST"])
def verify_document(request, doc_id):
    """Verify or reject a document (staff/finance admin only)"""
    logger.info(f"🔍 [verify_document] Called: doc_id={doc_id}, user={request.user.username}")
    
    if not (request.user.is_staff or user_is_finance_admin(request.user)):
        logger.warning(f"⛔ [verify_document] Permission denied for user {request.user.username}")
        return JsonResponse({'success': False, 'message': 'Permission denied'}, status=403)
    
    document = get_object_or_404(TransactionDocument, pk=doc_id)
    logger.info(f"📄 [verify_document] Document: type={document.document_type}, status={document.status}, transaction={document.transaction.id}")
    
    try:
        data = json.loads(request.body) if request.body else request.POST
        action = data.get('action') or request.POST.get('action')
        reason = data.get('reason') or request.POST.get('reason', '')
    except json.JSONDecodeError:
        action = request.POST.get('action')
        reason = request.POST.get('reason', '')
    
    if action == 'verify':
        document.status = 'verified'
        document.verification_notes = reason or f'Verified by {request.user.username}'
        message = 'Document verified successfully'
        logger.info(f"✅ [verify_document] Document {doc_id} verified")
    elif action == 'reject':
        document.status = 'rejected'
        document.verification_notes = reason or f'Rejected by {request.user.username}'
        message = 'Document rejected'
        logger.info(f"❌ [verify_document] Document {doc_id} rejected")
    else:
        return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
    
    document.verified_by = request.user
    document.verified_at = timezone.now()
    document.save()
    logger.info(f"💾 [verify_document] Document saved: status={document.status}")
    
    # Log the verification in transaction audit
    document.transaction.add_event(
        'document_verified',
        f"Document {document.get_document_type_display()} {action}ed by {request.user.username}",
        actor=request.user
    )
    
    # Send notification to the uploader
    from notifications.notification_service import NotificationService
    NotificationService.create_notification(
        user=document.uploaded_by,
        notification_type="document_verified",
        title=f"Document {action}ed - {document.transaction.plot.title}",
        message=f"Your document '{document.get_document_type_display()}' has been {action}ed. {reason}"
    )
    logger.info(f"📧 [verify_document] Notification sent to {document.uploaded_by.username}")
    
    # ============================================================
    # AUTO-ADVANCE: If document is verified, check if all required
    # documents for this stage are now verified and auto-advance
    # ============================================================
    if document.status == 'verified':
        transaction = document.transaction
        logger.info(f"🔍 [verify_document] Checking auto-advance for transaction {transaction.id}, current stage: {transaction.stage}")
        
        try:
            required_docs = transaction.get_required_documents_for_stage()
            logger.info(f"📋 [verify_document] Required docs for stage: {required_docs}")
            
            all_verified = True
            missing_docs = []
            
            for doc_type in required_docs:
                has_verified = TransactionDocument.objects.filter(
                    transaction=transaction,
                    document_type=doc_type,
                    status='verified'
                ).exists()
                if not has_verified:
                    all_verified = False
                    missing_docs.append(doc_type)
                    logger.info(f"📄 [verify_document] Missing verified doc: {doc_type}")
            
            logger.info(f"📊 [verify_document] All docs verified: {all_verified}, Missing: {missing_docs}")
            
            if all_verified:
                logger.info(f"🚀 [verify_document] All required docs verified, attempting auto-advance")
                
                # Check if the transaction can advance (legal checks)
                can_advance, advance_message = transaction.can_advance_to_next_stage()
                logger.info(f"🔒 [verify_document] Can advance: {can_advance}, Message: {advance_message}")
                
                if can_advance:
                    # Check if this stage requires payment before advancing
                    # We DON'T auto-advance past CONTRACTS or COMPLETION stages
                    # because those require payment confirmation
                    if transaction.stage in [Transaction.Stage.CONTRACTS, Transaction.Stage.COMPLETION]:
                        logger.info(f"💳 [verify_document] Stage {transaction.stage} requires payment, checking confirmation")
                        # For these stages, auto-advance only if payment is already confirmed
                        # via the payment closing step
                        payment_step_code = 'agreement' if transaction.stage == Transaction.Stage.CONTRACTS else 'completion_docs'
                        payment_step = transaction.payment_request.closing_steps.filter(code=payment_step_code).first() if transaction.payment_request else None
                        
                        if payment_step and payment_step.status == PaymentClosingStep.Status.COMPLETED:
                            # Payment was already confirmed, auto-advance
                            logger.info(f"💰 [verify_document] Payment confirmed, auto-advancing from {transaction.stage}")
                            success, msg = transaction.advance_stage(actor=request.user)
                            if success:
                                logger.info(f"✅ [verify_document] Auto-advance successful! New stage: {transaction.get_stage_display()}")
                            else:
                                logger.warning(f"⚠️ [verify_document] Auto-advance failed: {msg}")
                        else:
                            logger.info(f"⏳ [verify_document] Payment not confirmed yet, skipping auto-advance. Payment step status: {payment_step.status if payment_step else 'None'}")
                            
                            # ============================================================
                            # SPECIAL HANDLING: SALE AGREEMENT VERIFIED - PAYMENT REQUIRED
                            # ============================================================
                            if document.document_type == TransactionDocument.DocType.SALE_AGREEMENT:
                                logger.info(f"💰 [verify_document] SALE AGREEMENT verified - payment is now required")
                                
                                # Add a clear event to the transaction
                                transaction.add_event(
                                    'payment_required',
                                    f"💰 10% DEPOSIT PAYMENT REQUIRED: KES {transaction.ten_percent_deposit:,.2f}. "
                                    f"The sale agreement has been verified. Pay the deposit to proceed to statutory consents.",
                                    actor=request.user
                                )
                                
                                # Send a clear notification to the buyer
                                NotificationService.create_notification(
                                    user=transaction.buyer,
                                    notification_type="payment_required",
                                    title="💰 10% Deposit Payment Required",
                                    message=(
                                        f"✅ The sale agreement for {transaction.plot.title} has been verified.\n\n"
                                        f"💰 Please pay the 10% deposit of KES {transaction.ten_percent_deposit:,.2f} "
                                        f"to proceed with the transaction.\n\n"
                                        f"The funds will be held in escrow until registration is complete."
                                    )
                                )
                                
                                # Also notify the seller that payment is pending
                                if transaction.seller:
                                    NotificationService.create_notification(
                                        user=transaction.seller,
                                        notification_type="payment_pending",
                                        title="⏳ Awaiting Deposit Payment",
                                        message=(
                                            f"✅ The sale agreement for {transaction.plot.title} has been verified.\n\n"
                                            f"⏳ Awaiting the buyer's 10% deposit payment of KES {transaction.ten_percent_deposit:,.2f}. "
                                            f"You will be notified when payment is confirmed."
                                        )
                                    )
                                
                                logger.info(f"📧 [verify_document] Payment notification sent to buyer for transaction {transaction.id}")
                    else:
                        # For all other stages (due_diligence, statutory_consents, taxation, registration)
                        # Auto-advance immediately after documents are verified
                        logger.info(f"🚀 [verify_document] Auto-advancing from {transaction.stage} to next stage")
                        success, msg = transaction.advance_stage(actor=request.user)
                        if success:
                            logger.info(f"✅ [verify_document] Auto-advance successful! New stage: {transaction.get_stage_display()}")
                            
                            # If we advanced to CONTRACTS or COMPLETION, notify about payment
                            if transaction.stage == Transaction.Stage.CONTRACTS:
                                logger.info(f"💰 [verify_document] Reached CONTRACTS stage - deposit required")
                                NotificationService.create_notification(
                                    user=transaction.buyer,
                                    notification_type="payment_required",
                                    title="💰 Deposit Payment Required",
                                    message=f"10% deposit of KES {transaction.ten_percent_deposit:,.2f} is now required to proceed."
                                )
                            elif transaction.stage == Transaction.Stage.COMPLETION:
                                logger.info(f"💰 [verify_document] Reached COMPLETION stage - balance required")
                                NotificationService.create_notification(
                                    user=transaction.buyer,
                                    notification_type="payment_required",
                                    title="💰 Balance Payment Required",
                                    message=f"90% balance of KES {transaction.balance_due:,.2f} is now required to proceed."
                                )
                            elif transaction.stage == Transaction.Stage.TAXATION:
                                logger.info(f"🏛️ [verify_document] Reached TAXATION stage - stamp duty required")
                                NotificationService.create_notification(
                                    user=transaction.buyer,
                                    notification_type="stamp_duty_required",
                                    title="🏛️ Stamp Duty Payment Required",
                                    message="Stamp duty must be paid directly to KRA via iTax. Upload the receipt after payment."
                                )
                        else:
                            logger.warning(f"⚠️ [verify_document] Auto-advance failed: {msg}")
                else:
                    logger.info(f"⏳ [verify_document] Cannot advance: {advance_message}")
            else:
                logger.info(f"⏳ [verify_document] Not all docs verified yet. Required: {required_docs}, Missing: {missing_docs}")
                
        except Exception as e:
            logger.exception(f"💥 [verify_document] Auto-advance failed for transaction {document.transaction.id}: {e}")
            # Don't raise - we don't want to break the verification flow
    else:
        logger.info(f"⏭️ [verify_document] Document not verified (status={document.status}), skipping auto-advance")
    
    logger.info(f"🏁 [verify_document] Completed for doc_id={doc_id}")
    return JsonResponse({'success': True, 'message': message})

# ============================================================
# DISBURSE FUNDS
# ============================================================
@login_required
@require_http_methods(["POST"])
def disburse_funds(request, pk):
    """Manually disburse escrow funds to seller after registration."""
    transaction = get_object_or_404(Transaction, pk=pk)
    
    if not user_is_escrow_admin(request.user):
        messages.error(request, "Only escrow administrators can authorize fund disbursement.")
        return redirect('transactions:detail', pk=pk)
    
    if transaction.stage != Transaction.Stage.REGISTRATION:
        messages.error(request, f"Cannot disburse funds. Transaction is at {transaction.get_stage_display()}. Registration must be complete first.")
        return redirect('transactions:detail', pk=pk)
    
    new_title = TransactionDocument.objects.filter(
        transaction=transaction,
        document_type=TransactionDocument.DocType.NEW_TITLE_DEED,
        status='verified'
    ).exists()
    
    if not new_title:
        messages.error(request, "Cannot disburse funds. New title deed must be uploaded and verified first.")
        return redirect('transactions:detail', pk=pk)
    
    if not transaction.stamp_duty_receipt_verified_at:
        messages.error(request, "Cannot disburse funds. Stamp duty payment to KRA must be verified first.")
        return redirect('transactions:detail', pk=pk)
    
    try:
        with db_transaction.atomic():
            success, message = transaction.advance_stage(actor=request.user)
            
            if success:
                messages.success(request, f"💰 {message}")
                
                if transaction.payment_request and not transaction.payment_request.disbursed_at:
                    transaction.payment_request.apply_transition("disburse_to_seller", actor=request.user)
                    messages.info(request, f"Funds disbursed to seller. Platform fee: KES {transaction.platform_fee_amount:,.2f}, Seller net: KES {transaction.seller_net_amount:,.2f}")
            else:
                messages.error(request, f"❌ Disbursement failed: {message}")
    except Exception as e:
        logger.exception(f"Disbursement error: {e}")
        messages.error(request, f"❌ Disbursement failed: {str(e)}")
    
    return redirect('transactions:detail', pk=pk)


# ============================================================
# RESEND TRANSACTION REPORTS
# ============================================================
@login_required
@require_http_methods(["POST"])
def resend_transaction_reports(request, pk):
    """Resend transaction completion reports to both parties"""
    transaction = get_object_or_404(Transaction, pk=pk)
    
    if not (request.user.is_staff or user_is_finance_admin(request.user)):
        messages.error(request, "Permission denied.")
        return redirect('transactions:detail', pk=pk)
    
    if transaction.stage != Transaction.Stage.COMPLETED:
        messages.error(request, "Reports are only available for completed transactions.")
        return redirect('transactions:detail', pk=pk)
    
    try:
        transaction._send_transaction_reports()
        messages.success(request, f"Transaction reports resent to {transaction.buyer.email} and {transaction.seller.email}")
    except Exception as e:
        logger.exception(f"Failed to resend reports: {e}")
        messages.error(request, f"Failed to send reports: {str(e)}")
    
    return redirect('transactions:detail', pk=pk)


# ============================================================
# STAMP DUTY VERIFICATION
# ============================================================
@login_required
def stamp_duty_verification(request, pk):
    """View for verifying stamp duty payment to KRA."""
    transaction = get_object_or_404(Transaction, pk=pk)
    
    if not (request.user.is_staff or user_is_finance_admin(request.user)):
        messages.error(request, "Permission denied.")
        return redirect('transactions:detail', pk=pk)
    
    if request.method == 'POST':
        receipt_number = request.POST.get('receipt_number', '')
        stamp_duty_amount = request.POST.get('stamp_duty_amount', '')
        
        if not receipt_number:
            messages.error(request, "Please enter the KRA stamp duty receipt number.")
            return redirect('transactions:detail', pk=pk)
        
        try:
            import re
            pattern = r'^KRA-\d{8}-\d{6}$'
            if not re.match(pattern, receipt_number):
                messages.error(request, "Invalid KRA receipt number format. Expected: KRA-YYYYMMDD-XXXXXX")
                return redirect('transactions:detail', pk=pk)
            
            transaction.mark_stamp_duty_verified(receipt_number, request.user)
            
            if transaction.payment_request:
                payment_metadata = dict(transaction.payment_request.metadata or {})
                payment_metadata['stamp_duty_receipt_number'] = receipt_number
                payment_metadata['stamp_duty_receipt_verified_at'] = timezone.now().isoformat()
                transaction.payment_request.metadata = payment_metadata
                transaction.payment_request.save(update_fields=['metadata', 'updated_at'])
            
            messages.success(request, f"Stamp duty verified successfully. Receipt: {receipt_number}")
            
        except Exception as e:
            logger.exception(f"Stamp duty verification error: {e}")
            messages.error(request, f"Verification failed: {str(e)}")
        
        return redirect('transactions:detail', pk=pk)
    
    return render(request, 'transactions/stamp_duty_verification.html', {
        'transaction': transaction,
        'is_finance_admin': user_is_finance_admin(request.user),
    })


# ============================================================
# TRANSACTION DETAIL VIEW
# ============================================================
from payments.presenters import PaymentPresenter

@login_required
def transaction_detail(request, pk):
    """Display transaction details with all legal documents and milestones"""
    transaction = get_object_or_404(Transaction, pk=pk)
    
    if request.user not in [transaction.buyer, transaction.seller] and not request.user.is_staff:
        messages.error(request, "You don't have permission to view this transaction")
        return redirect('listings:dashboard_router')
    
    documents = transaction.documents.all()
    documents_by_type = {doc.document_type: doc for doc in documents}
    
    stage_order = [
        Transaction.Stage.DUE_DILIGENCE,
        Transaction.Stage.COMMITMENT,
        Transaction.Stage.CONTRACTS,
        Transaction.Stage.STATUTORY_CONSENTS,
        Transaction.Stage.TAXATION,
        Transaction.Stage.COMPLETION,
        Transaction.Stage.REGISTRATION,
        Transaction.Stage.DISBURSEMENT,
        Transaction.Stage.COMPLETED,
    ]
    current_index = stage_order.index(transaction.stage) if transaction.stage in stage_order else 0

    required_docs = transaction.get_required_documents_for_stage()
    doc_type_labels = dict(TransactionDocument.DocType.choices)
    workflow_stages = []
    
    for stage_code in stage_order:
        stage_label = dict(Transaction.Stage.choices).get(stage_code, stage_code)
        stage_doc_types = transaction.get_required_documents_for_stage(stage_code)
        stage_required_doc_details = []
        
        for doc_type in stage_doc_types:
            doc = documents_by_type.get(doc_type)
            doc_label = doc_type_labels.get(doc_type, doc_type)
            stage_required_doc_details.append({
                "doc_type": doc_type,
                "label": doc_label,
                "doc": doc,
                "has_document": bool(doc),
                "is_verified": bool(doc and doc.status == TransactionDocument.Status.VERIFIED),
                "is_pending": bool(doc and doc.status == TransactionDocument.Status.PENDING),
                "is_rejected": bool(doc and doc.status == TransactionDocument.Status.REJECTED),
                "status": doc.status if doc else "",
                "status_label": (
                    "Verified" if doc and doc.status == TransactionDocument.Status.VERIFIED
                    else "Awaiting verification" if doc and doc.status == TransactionDocument.Status.PENDING
                    else "Rejected" if doc and doc.status == TransactionDocument.Status.REJECTED
                    else "Not uploaded"
                ),
            })
        
        workflow_stages.append({
            "code": stage_code,
            "label": stage_label,
            "required_docs": [doc_type_labels.get(doc_type, doc_type) for doc_type in stage_doc_types],
            "required_doc_details": stage_required_doc_details,
            "is_current": transaction.stage == stage_code,
            "is_completed": stage_order.index(stage_code) < current_index,
        })
    
    can_advance, advance_message = transaction.can_advance_to_next_stage()
    milestones = transaction.milestones.all()
    events = transaction.events.all()[:20]
    
    upload_form = TransactionDocumentForm(transaction=transaction, user=request.user)
    advance_form = TransactionAdvanceForm(transaction=transaction, user=request.user)
    
    progress_percentage = round((current_index / len(stage_order)) * 100, 1)
    
    if request.user == transaction.buyer:
        user_role = 'Buyer'
    elif request.user == transaction.seller:
        user_role = 'Seller'
    elif request.user.is_staff or user_is_finance_admin(request.user):
        user_role = 'Admin'
    elif user_is_escrow_admin(request.user):
        user_role = 'Escrow Admin'
    else:
        user_role = 'Viewer'
    
    suggested_payment = transaction.ten_percent_deposit if transaction.deposit_paid == 0 else transaction.balance_due
    can_disburse = user_is_escrow_admin(request.user) and transaction.stage == Transaction.Stage.REGISTRATION
    
    payment_status = None
    if transaction.payment_request:
        payment_status = {
            'deposit_paid': transaction.payment_request.metadata.get('deposit_paid', False),
            'balance_paid': transaction.payment_request.metadata.get('balance_paid', False),
            'disbursed': transaction.payment_request.disbursed_at is not None,
        }
    
    # ============================================================
    # ADVOCATE ASSIGNMENT - Get available advocates
    # ============================================================
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    available_advocates = User.objects.filter(
        Q(groups__name='Legal Admin') | 
        Q(is_staff=True) |
        Q(profile__role='advocate')
    ).distinct()
    
    # Also include currently assigned advocates even if they don't match the filter
    if transaction.buyer_advocate and transaction.buyer_advocate not in available_advocates:
        available_advocates = available_advocates | User.objects.filter(pk=transaction.buyer_advocate.pk)
    if transaction.seller_advocate and transaction.seller_advocate not in available_advocates:
        available_advocates = available_advocates | User.objects.filter(pk=transaction.seller_advocate.pk)
    
    advocate_form = AdvocateAssignmentForm(transaction=transaction)
    
    # ============================================================
    # PAYMENT UI LOGIC - Only show at CONTRACTS (deposit) and COMPLETION (balance)
    # ============================================================
    show_payment_ui = False
    payment_stage_type = None
    payment_amount = None
    payment_label = None
    
    if transaction.payment_request:
        if transaction.stage == Transaction.Stage.CONTRACTS:
            if not payment_status or not payment_status.get('deposit_paid'):
                show_payment_ui = True
                payment_stage_type = 'deposit'
                payment_amount = transaction.ten_percent_deposit
                payment_label = "Agreement Deposit (10%)"
                
        elif transaction.stage == Transaction.Stage.COMPLETION:
            if not payment_status or not payment_status.get('balance_paid'):
                show_payment_ui = True
                payment_stage_type = 'completion_balance'
                payment_amount = transaction.balance_due                
                payment_label = "Completion Balance (90%)"
    
    stamp_duty_status = None
    if transaction.stage == Transaction.Stage.TAXATION:
        stamp_duty_status = {
            'required': True,
            'paid_to_kra': bool(transaction.stamp_duty_receipt_verified_at),
            'receipt_number': transaction.stamp_duty_receipt_number,
            'verified_at': transaction.stamp_duty_receipt_verified_at,
            'instructions': "Pay stamp duty directly to KRA via iTax portal, then upload receipt",
            'kra_link': "https://itax.kra.go.ke",
        }
    
    wallet_balance = None
    has_wallet_pin = False
    if show_payment_ui and request.user == transaction.buyer:
        wallet_balance = WalletService.get_balance(request.user)
        has_wallet_pin = WalletService.has_pin(request.user)
    
    context = {
        'transaction': transaction,
        'documents_by_type': documents_by_type,
        'required_docs': required_docs,
        'workflow_stages': workflow_stages,
        'can_advance': can_advance,
        'advance_message': advance_message,
        'milestones': milestones,
        'events': events,
        'upload_form': upload_form,
        'advance_form': advance_form,
        'progress_percentage': progress_percentage,
        'stage_sequence': stage_order,
        'current_stage_index': current_index,
        'user_role': user_role,
        'suggested_payment': suggested_payment,
        'can_disburse': can_disburse,
        'can_verify_documents': request.user.is_staff or user_is_finance_admin(request.user),
        'payment_status': payment_status,
        'is_escrow_admin': user_is_escrow_admin(request.user),
        'is_finance_admin': user_is_finance_admin(request.user),
        'show_payment_ui': show_payment_ui,
        'payment_stage_type': payment_stage_type,
        'payment_amount': payment_amount,
        'payment_label': payment_label,
        'stamp_duty_status': stamp_duty_status,
        'wallet_balance': wallet_balance,
        'has_wallet_pin': has_wallet_pin,
        'mpesa_allowed': payment_amount <= 50000 if payment_amount else True,
        # Advocate assignment context
        'advocate_form': advocate_form,
        'available_advocates': available_advocates,
        'show_advocate_assignment': (
            transaction.stage in [Transaction.Stage.COMMITMENT, Transaction.Stage.CONTRACTS] or
            not transaction.buyer_advocate or 
            not transaction.seller_advocate
        ),
    }
    
    return render(request, 'transactions/detail.html', context)


# ============================================================
# UPLOAD DOCUMENT
# ============================================================
@login_required
@require_http_methods(["POST"])
def upload_document(request, pk):
    """Upload a legal document for the transaction"""
    transaction = get_object_or_404(Transaction, pk=pk)
    
    if request.user not in [transaction.buyer, transaction.seller] and not request.user.is_staff:
        messages.error(request, "You don't have permission to upload documents")
        return redirect('transactions:detail', pk=pk)
    
    try:
        posted_document_type = request.POST.get("document_type")
        existing_doc = None
        if posted_document_type:
            existing_doc = TransactionDocument.objects.filter(
                transaction=transaction,
                document_type=posted_document_type
            ).first()

        form = TransactionDocumentForm(
            request.POST,
            request.FILES,
            instance=existing_doc,
            transaction=transaction,
            user=request.user,
        )

        if not form.is_valid():
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
            return redirect('transactions:detail', pk=pk)

        doc = form.save()
        action_message = "updated" if existing_doc else "uploaded"

        messages.success(request, f"✅ Legal document '{doc.get_document_type_display()}' {action_message} successfully")
        transaction.add_event(
            f"document_{action_message}",
            f"{doc.get_document_type_display()} {action_message} by {request.user.username}",
            actor=request.user
        )
        
        from notifications.notification_service import NotificationService
        recipient = transaction.seller if request.user == transaction.buyer else transaction.buyer
        if recipient:
            NotificationService.create_notification(
                user=recipient,
                notification_type="document_uploaded",
                title=f"Document Uploaded - {transaction.plot.title}",
                message=f"{request.user.username} has uploaded a document to your transaction."
            )
    except Exception as e:
        logger.exception(f"Error saving document: {e}")
        messages.error(request, f"Error saving document: {str(e)}")
    
    return redirect('transactions:detail', pk=pk)


# ============================================================
# MAKE STAGE PAYMENT
# ============================================================
@login_required
@require_http_methods(["POST"])
def make_stage_payment(request, pk):
    """Handle payment for a specific legal stage (deposit or completion)."""
    transaction = get_object_or_404(Transaction, pk=pk)
    
    if request.user != transaction.buyer:
        messages.error(request, "Only the buyer can make payments.")
        return redirect('transactions:detail', pk=pk)

    linked_payment = transaction.payment_request or PaymentRequest.objects.filter(legal_transaction=transaction).first()
    if linked_payment:
        paid_statuses = {
            PaymentRequest.Status.PAID,
            PaymentRequest.Status.IN_ESCROW,
            PaymentRequest.Status.PARTIALLY_RELEASED,
            PaymentRequest.Status.RELEASED,
        }
        if linked_payment.status in paid_statuses:
            messages.info(
                request,
                f"This transaction's payment ({linked_payment.internal_reference}) has already been completed."
            )
        else:
            messages.info(
                request,
                f"You have a pending payment workspace ({linked_payment.internal_reference}). "
                f"Please complete your payment there."
            )
        return redirect("payments:detail", pk=linked_payment.pk)
    
    # Only allow payments at CONTRACTS (deposit) or COMPLETION (balance) stages
    if transaction.stage not in [Transaction.Stage.CONTRACTS, Transaction.Stage.COMPLETION]:
        messages.error(request, "Payments are only allowed at the contract deposit or completion stages.")
        return redirect('transactions:detail', pk=pk)
    
    stage_type = request.POST.get("stage_type")
    method = request.POST.get("method")
    phone_number = request.POST.get("phone_number")
    wallet_pin = request.POST.get("wallet_pin")
    
    if stage_type == 'deposit':
        amount = transaction.ten_percent_deposit
        category = PaymentRequest.Category.AGREEMENT_DEPOSIT
        description = f"10% agreement deposit for {transaction.plot.title}"
        
        if transaction.deposit_paid >= transaction.ten_percent_deposit:
            messages.error(request, "Deposit already paid.")
            return redirect('transactions:detail', pk=pk)
    else:  # completion
        amount = transaction.balance_due
        category = PaymentRequest.Category.COMPLETION_BALANCE
        description = f"90% completion balance for {transaction.plot.title}"
        
        if transaction.balance_due <= 0:
            messages.error(request, "Balance already paid.")
            return redirect('transactions:detail', pk=pk)
    
    if not method:
        messages.error(request, "Please select a payment method.")
        return redirect('transactions:detail', pk=pk)
    
    payment = PaymentRequest.objects.create(
        transaction_type=PaymentRequest.TransactionType.PURCHASE,
        category=category,
        plot=transaction.plot,
        buyer=request.user,
        seller=transaction.seller,
        amount=amount,
        status=PaymentRequest.Status.PENDING,
        title=description,
        description=f"Payment for legal transaction {transaction.id} - {description}",
        escrow_enabled=True,
        method=method,
        phone_number=phone_number if phone_number else None,
        legal_transaction=transaction,
        metadata={'transaction_id': transaction.id, 'stage_type': stage_type},
    )
    transaction.payment_request = payment
    transaction.save(update_fields=['payment_request', 'updated_at'])
    
    try:
        with db_transaction.atomic():
            if method == PaymentRequest.Method.WALLET:
                if not wallet_pin:
                    raise ValidationError("Wallet PIN required.")
                
                result = WalletService.make_payment(
                    user=request.user,
                    amount=amount,
                    pin=wallet_pin,
                    payment_request=payment,
                    description=description
                )
                
                payment.apply_transition("mark_paid", actor=request.user)
                
                if stage_type == 'deposit':
                    transaction.deposit_paid = amount
                else:
                    transaction.balance_paid = amount
                    transaction.deposit_paid = min(transaction.deposit_paid, transaction.ten_percent_deposit)
                
                metadata = dict(payment.metadata or {})
                metadata[f"{stage_type}_paid"] = True
                metadata[f"{stage_type}_paid_at"] = timezone.now().isoformat()
                payment.metadata = metadata
                payment.save(update_fields=['metadata', 'updated_at'])
                
                transaction.save(update_fields=['deposit_paid', 'balance_paid', 'updated_at'])
                
                messages.success(request, f"💰 Payment of KES {amount:,.2f} successful via wallet.")
                
                if transaction.deposit_paid >= transaction.ten_percent_deposit and transaction.balance_due <= 0:
                    messages.info(request, "✅ All payments complete! Transaction will proceed to registration.")
                
                return redirect('transactions:detail', pk=pk)
                
            elif method == PaymentRequest.Method.MPESA_STK:
                if not phone_number:
                    raise ValidationError("Phone number required for M-Pesa.")
                
                from payments.daraja import initiate_stk_push
                
                phone_number = validate_kenyan_phone(phone_number)
                payment.phone_number = phone_number
                payment.save()
                
                callback_url = settings.MPESA_CALLBACK_URL or (
                    f"{settings.SITE_URL.rstrip('/')}{reverse('payments:daraja_callback')}"
                )
                
                stk_data = initiate_stk_push(payment, callback_url)
                
                payment.provider_reference = stk_data.get("CheckoutRequestID")
                payment.save(update_fields=["provider_reference"])
                
                messages.success(request, stk_data.get("CustomerMessage", "STK push sent. Check your phone to complete payment."))
                return redirect('payments:detail', pk=payment.pk)
                
            elif method == PaymentRequest.Method.BANK_TRANSFER:
                messages.info(request, f"Bank transfer initiated. Please transfer KES {amount:,.2f} to:\nBank: Cooperative Bank of Kenya\nAccount: AgriPlot Escrow Services\nAccount: 0114123456789\nReference: {payment.internal_reference}")
                return redirect('payments:detail', pk=payment.pk)
                
            elif method == PaymentRequest.Method.CARD:
                return redirect('payments:card_payment', pk=payment.pk)
                
            elif method == PaymentRequest.Method.AIRTEL_MONEY:
                messages.info(request, "Airtel Money payment initiated. Check your phone.")
                return redirect('payments:detail', pk=payment.pk)
                
    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        logger.exception(f"Stage payment failed: {e}")
        messages.error(request, f"Payment failed: {str(e)}")
    
    return redirect('transactions:detail', pk=pk)