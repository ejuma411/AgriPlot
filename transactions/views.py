import json
import logging
from django.shortcuts import render, get_object_or_404, redirect

logger = logging.getLogger(__name__)
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db import transaction as db_transaction
from django.utils import timezone

from .models import Transaction, TransactionDocument
from .forms import TransactionDocumentForm, TransactionAdvanceForm
from payments.jenga_service import JengaService
from payments.wallet_service import WalletService
from listings.models import Plot
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from decimal import Decimal, InvalidOperation
from payments.models import PaymentRequest
from payments.permissions import user_is_finance_admin

class TransactionDashboardView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = "transactions/dashboard.html"
    context_object_name = "transactions"

    def get_queryset(self):
        # Staff, finance admins, and superusers can see all transactions for operational support.
        if self.request.user.is_staff or self.request.user.is_superuser or user_is_finance_admin(self.request.user):
            return Transaction.objects.all().select_related("plot", "buyer", "seller")
        # Everyone else sees transactions where they are participants.
        return Transaction.objects.filter(
            Q(buyer=self.request.user) | Q(seller=self.request.user)
        ).select_related("plot", "buyer", "seller")


@login_required
def pay_installment(request, pk):
    if request.method != "POST":
        return redirect("transactions:detail", pk=pk)
        
    transaction = get_object_or_404(Transaction, pk=pk, buyer=request.user)
    
    if transaction.balance_due <= 0:
        messages.error(request, "This transaction has no outstanding balance.")
        return redirect("transactions:detail", pk=pk)
        
    amount_str = request.POST.get("amount")
    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError()
        if amount > transaction.balance_due:
            messages.error(request, f"Amount cannot exceed the balance due of KES {transaction.balance_due}.")
            return redirect("transactions:detail", pk=pk)
    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, "Please enter a valid amount.")
        return redirect("transactions:detail", pk=pk)
        
    # Determine the category based on current deposit status
    if transaction.deposit_paid == 0:
        # First payment -> Agreement Deposit
        category = PaymentRequest.Category.AGREEMENT_DEPOSIT
    else:
        # Subsequent payments -> Completion Balance
        category = PaymentRequest.Category.COMPLETION_BALANCE

    # Create the payment request
    payment = PaymentRequest.objects.create(
        transaction_type=PaymentRequest.TransactionType.PURCHASE,
        category=category,
        plot=transaction.plot,
        buyer=request.user,
        seller=transaction.seller,
        amount=amount,
        status=PaymentRequest.Status.PENDING,
    )
    
    return redirect("payments:detail", pk=payment.pk)



@login_required
def transaction_detail(request, pk):
    """Display transaction details with all legal documents and milestones"""
    transaction = get_object_or_404(Transaction, pk=pk)
    
    # Check user permissions
    if request.user not in [transaction.buyer, transaction.seller] and not request.user.is_staff:
        messages.error(request, "You don't have permission to view this transaction")
        return redirect('listings:dashboard_router')
    
    # Get all documents
    documents = transaction.documents.all()
    
    # Group documents by type
    documents_by_type = {doc.document_type: doc for doc in documents}
    
    # Get required documents for current legal stage
    required_docs = transaction.get_required_documents_for_stage()
    
    # Check if can advance (legal validation)
    can_advance, advance_message = transaction.can_advance_to_next_stage()
    
    # Get milestones (audit trail)
    milestones = transaction.milestones.all()
    
    # Get events (activity log)
    events = transaction.events.all()[:20]
    
    # Upload form
    upload_form = TransactionDocumentForm(transaction=transaction, user=request.user)
    advance_form = TransactionAdvanceForm()
    
    # Calculate progress percentage for UI
    stage_order = [
        Transaction.Stage.DUE_DILIGENCE,
        Transaction.Stage.COMMITMENT,
        Transaction.Stage.CONTRACTS,
        Transaction.Stage.STATUTORY_CONSENTS,
        Transaction.Stage.TAXATION,
        Transaction.Stage.REGISTRATION,
        Transaction.Stage.COMPLETED,
    ]
    current_index = stage_order.index(transaction.stage) if transaction.stage in stage_order else 0
    progress_percentage = round((current_index / len(stage_order)) * 100, 1)
    
    # Determine user role for UI display
    if request.user == transaction.buyer:
        user_role = 'Buyer'
    elif request.user == transaction.seller:
        user_role = 'Seller'
    elif request.user.is_staff:
        user_role = 'Admin'
    else:
        user_role = 'Viewer'
        
    # Calculate suggested payment
    if transaction.deposit_paid == 0:
        suggested_payment = transaction.agreed_price * Decimal('0.10')
    else:
        suggested_payment = transaction.balance_due
    
    context = {
        'transaction': transaction,
        'documents_by_type': documents_by_type,
        'required_docs': required_docs,
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
    }
    
    return render(request, 'transactions/detail.html', context)


@login_required
@require_http_methods(["POST"])
def upload_document(request, pk):
    """Upload a legal document for the transaction"""
    transaction = get_object_or_404(Transaction, pk=pk)
    
    # Debug: Print to see what's coming in
    logger.info(f"Upload request for transaction {pk} by user {request.user.username}")
    logger.info(f"POST data: {request.POST}")
    logger.info(f"FILES: {request.FILES}")
    
    # Check permissions (only buyer, seller, or staff can upload)
    if request.user not in [transaction.buyer, transaction.seller] and not request.user.is_staff:
        messages.error(request, "You don't have permission to upload documents")
        return redirect('transactions:detail', pk=pk)
    
    # Create form with transaction and user
    form = TransactionDocumentForm(
        request.POST, 
        request.FILES, 
        transaction=transaction,  # CRITICAL: Pass the transaction
        user=request.user          # CRITICAL: Pass the user
    )
    
    if form.is_valid():
        try:
            document = form.save()
            logger.info(f"Document saved: {document.id} - {document.document_type}")
            
            # Log the upload in audit trail
            transaction.add_event(
                'document_uploaded',
                f"{document.get_document_type_display()} uploaded by {request.user.username} (Ref: {document.reference_number or 'N/A'})",
                actor=request.user
            )
            
            # Send notification
            from notifications.notification_service import NotificationService
            NotificationService.notify_document_uploaded(document)
            
            messages.success(request, f"✅ Legal document '{document.get_document_type_display()}' uploaded successfully")
            
            # Check if all required documents are now present
            can_advance, message = transaction.can_advance_to_next_stage()
            if can_advance:
                messages.info(request, f"✅ All legal requirements for {transaction.get_stage_display()} are met! You can now advance to the next stage.")
                
        except Exception as e:
            logger.exception(f"Error saving document: {e}")
            messages.error(request, f"Error saving document: {str(e)}")
    else:
        # Log form errors
        logger.warning(f"Form errors: {form.errors}")
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field}: {error}")
    
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
        
    return redirect('transactions:detail', pk=pk)

@login_required
@require_http_methods(["POST"])
def advance_stage(request, pk):
    """
    Advance transaction to next legal stage.
    This enforces the chronological pipeline under Kenyan law.
    """
    transaction = get_object_or_404(Transaction, pk=pk)
    
    # Check permissions (only buyer or seller can advance)
    if request.user not in [transaction.buyer, transaction.seller] and not request.user.is_staff:
        messages.error(request, "You don't have permission to advance this transaction")
        return redirect('transactions:detail', pk=pk)
    
    form = TransactionAdvanceForm(request.POST)
    
    if form.is_valid():
        try:
            with db_transaction.atomic():
                # Step 1: Map the current stage to its payment step code
                old_stage = transaction.stage
                step_code = None
                
                if transaction.transaction_type == Transaction.TransactionType.PURCHASE:
                    stage_to_step = {
                        Transaction.Stage.DUE_DILIGENCE: 'due_diligence',
                        Transaction.Stage.COMMITMENT: 'offer',
                        Transaction.Stage.CONTRACTS: 'agreement',
                        Transaction.Stage.STATUTORY_CONSENTS: 'lcb_consent',
                        Transaction.Stage.TAXATION: 'stamp_duty',
                        Transaction.Stage.REGISTRATION: 'registration',
                    }
                    step_code = stage_to_step.get(old_stage)
                
                # Step 2: Handle dual confirmations on the PaymentClosingStep
                from payments.models import PaymentClosingStep
                from django.utils import timezone
                
                step_to_complete = None
                can_advance_transaction = True
                
                if step_code and transaction.payment_request:
                    step = transaction.payment_request.closing_steps.filter(code=step_code).first()
                    if step and step.status != PaymentClosingStep.Status.COMPLETED:
                        # Record the current user's confirmation
                        if request.user == transaction.buyer:
                            step.buyer_confirmed_at = timezone.now()
                        elif request.user == transaction.seller:
                            step.seller_confirmed_at = timezone.now()
                        step.save(update_fields=['buyer_confirmed_at', 'seller_confirmed_at'])
                        
                        # Check if the step has enough evidence/confirmations to complete
                        if not step.can_mark_complete_with_current_evidence():
                            can_advance_transaction = False
                            messages.info(request, "Your confirmation has been saved. Waiting for the other party to confirm before advancing.")
                        else:
                            step_to_complete = step
                
                # Step 3: Advance transaction if allowed
                if can_advance_transaction:
                    success, message = transaction.advance_stage(actor=request.user)
                    
                    if success:
                        messages.success(request, f"🏛️ {message}")
                        
                        # Send notifications
                        from notifications.notification_service import NotificationService
                        NotificationService.notify_transaction_advanced(transaction)
                        
                        # Complete the step we just evaluated
                        if step_to_complete:
                            step_to_complete.set_status(PaymentClosingStep.Status.COMPLETED, actor=request.user)
                            messages.info(request, f"Payment workspace step '{step_to_complete.display_title}' automatically completed.")
                        
                        # If this was the final stage, show special message
                        if transaction.stage == Transaction.Stage.COMPLETED:
                            messages.success(request, "🎉 Transaction completed! The title has been transferred and escrow funds disbursed to the seller.")
                    else:
                        messages.error(request, f"❌ Cannot advance: {message}")
        except ValidationError as e:
            messages.error(request, f"❌ Legal validation failed: {str(e)}")
        except Exception as e:
            messages.error(request, f"❌ Failed to advance: {str(e)}")
    else:
        messages.error(request, "Please confirm that all legal requirements are met")
    
    return redirect('transactions:detail', pk=pk)


@login_required
@require_http_methods(["POST"])
def verify_document(request, doc_id):
    """Verify or reject a document (staff only)"""
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'}, status=403)
    
    document = get_object_or_404(TransactionDocument, pk=doc_id)
    
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
    elif action == 'reject':
        document.status = 'rejected'
        document.verification_notes = reason or f'Rejected by {request.user.username}'
        message = 'Document rejected'
    else:
        return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
    
    document.verified_by = request.user
    document.verified_at = timezone.now()
    document.save()
    
    # Log the verification in transaction audit
    document.transaction.add_event(
        'document_verified',
        f"Document {document.get_document_type_display()} {action}ed by {request.user.username}",
        actor=request.user
    )
    
    return JsonResponse({'success': True, 'message': message})
