"""
Transaction Models for AgriPlot Connect
Strict implementation of Kenyan Land Laws:
- Land Act 2012
- Land Registration Act 2012
- Land Control Act Cap 302
- LSK Conditions of Sale

Integrates with Platform Escrow Model:
- 10% deposit held in escrow at agreement stage
- 90% balance held in escrow before registration
- Stamp duty paid directly to KRA (platform never collects)
- Funds disbursed to seller ONLY after registration completes
- Platform fee deducted from seller proceeds before disbursement
"""

from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal


class Transaction(models.Model):
    """
    Core transaction model for land transfers.
    Implements strict chronological pipeline as per Kenyan law.
    
    Statutory Pipeline (REAL-LIFE SEQUENCE):
    1. DUE_DILIGENCE: Official Land Search + Physical Beacon Verification
    2. COMMITMENT: Letter of Offer (non-binding)
    3. CONTRACTS: Sale Agreement + 10% Escrow Deposit (Platform Holds)
    4. STATUTORY_CONSENTS: LCB Consent + Spousal Consent (if applicable)
    5. TAXATION: Stamp Duty (2% rural / 4% urban - Paid Directly to KRA)
    6. REGISTRATION: Title Transfer & New Title Deed
    7. DISBURSEMENT: Platform Fee Deducted + Final Seller Payout
    8. COMPLETED: Transaction Complete & Reports Sent
    """
    
    class Stage(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        DUE_DILIGENCE = 'due_diligence', 'Due Diligence'
        COMMITMENT = 'commitment', 'Offer Agreement (Negotiation & Drafting)'
        CONTRACTS = 'contracts', 'Agreement Deposit (10% Escrow Payment)'
        STATUTORY_CONSENTS = 'statutory_consents', 'Statutory Consents'
        TAXATION = 'taxation', 'Stamp Duty Payment (Direct to KRA)'
        COMPLETION = 'completion', 'Completion Balance (Final Payment)'
        REGISTRATION = 'registration', 'Final Registration & Title Issuance'
        DISBURSEMENT = 'disbursement', 'Disbursement & Completion'
        COMPLETED = 'completed', 'Workflow Complete'
        CANCELLED = 'cancelled', 'Cancelled'
    
    class TransactionType(models.TextChoices):
        PURCHASE = 'purchase', 'Purchase'
        LEASE = 'lease', 'Lease'
        BOTH = 'both', 'Purchase & Lease'

    # Basic Information
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices, default=TransactionType.PURCHASE)
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.DRAFT)
    payment_request = models.OneToOneField(
        'payments.PaymentRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text="Associated payment request for this transaction"
    )

    # Related Parties
    plot = models.ForeignKey('listings.Plot', on_delete=models.PROTECT, related_name='land_transactions')
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='land_purchases')
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='land_sales')
    
    # Assigned Professionals
    buyer_advocate = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='buyer_representations',
        help_text="Licensed advocate representing the buyer (required by Law Society of Kenya)"
    )
    seller_advocate = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='seller_representations',
        help_text="Licensed advocate representing the seller (required by Law Society of Kenya)"
    )
    
    # Financial Details
    agreed_price = models.DecimalField(max_digits=15, decimal_places=2)
    ten_percent_deposit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    ninety_percent_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    deposit_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="10% deposit held in platform escrow")
    balance_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="90% balance held in platform escrow")
    balance_due = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Platform Fee (deducted before seller disbursement)
    platform_fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=2.00, help_text="Platform fee percentage (1.5-3%)")
    platform_fee_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Platform fee deducted from seller proceeds")
    seller_net_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Seller receives after platform fee deduction")
    
    # Tax Calculations (Kenya specific)
    stamp_duty_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=2.00, help_text="2% rural, 4% urban")
    stamp_duty_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Paid directly to KRA, not collected by platform")
    capital_gains_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="15% of profit - Seller files with KRA")
    
    # Escrow Tracking
    deposit_held_in_escrow_at = models.DateTimeField(null=True, blank=True, help_text="When 10% deposit was received in escrow")
    balance_held_in_escrow_at = models.DateTimeField(null=True, blank=True, help_text="When 90% balance was received in escrow")
    disbursed_at = models.DateTimeField(null=True, blank=True, help_text="When funds were released to seller after registration")
    platform_fee_deducted_at = models.DateTimeField(null=True, blank=True, help_text="When platform fee was deducted")
    
    # Stamp Duty Tracking (paid directly to KRA, platform only verifies)
    stamp_duty_receipt_uploaded_at = models.DateTimeField(null=True, blank=True)
    stamp_duty_receipt_verified_at = models.DateTimeField(null=True, blank=True)
    stamp_duty_receipt_number = models.CharField(max_length=100, blank=True, help_text="KRA iTax receipt number")
    stamp_duty_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='transaction_stamp_duty_verifications'
    )
    
    # Timestamps for each stage (legal audit trail)
    due_diligence_completed_at = models.DateTimeField(null=True, blank=True)
    commitment_completed_at = models.DateTimeField(null=True, blank=True)
    contracts_completed_at = models.DateTimeField(null=True, blank=True)
    statutory_consents_completed_at = models.DateTimeField(null=True, blank=True)
    taxation_completed_at = models.DateTimeField(null=True, blank=True)
    registration_completed_at = models.DateTimeField(null=True, blank=True)
    disbursement_completed_at = models.DateTimeField(null=True, blank=True)
    
    # LCB Specifics
    lcb_meeting_date = models.DateField(null=True, blank=True)
    lcb_consent_reference = models.CharField(max_length=100, blank=True)
    lcb_application_fee = models.DecimalField(max_digits=10, decimal_places=2, default=1000)
    
    # Completion & Reporting
    completed_at = models.DateTimeField(null=True, blank=True)
    reports_sent_at = models.DateTimeField(null=True, blank=True, help_text="When transaction reports were emailed to both parties")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions_created',
        help_text="User who initiated this transaction"
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Transaction {self.id}: {self.plot.title} - {self.buyer.username}"
    
    def save(self, *args, **kwargs):
        """Auto-calculate financial values and platform fee"""
        self.ten_percent_deposit = self.agreed_price * Decimal('0.10')
        self.ninety_percent_balance = self.agreed_price - self.ten_percent_deposit
        self.balance_due = self.agreed_price - (self.deposit_paid + self.balance_paid)
        
        # Calculate platform fee (tiered based on property value)
        self.platform_fee_amount = self._calculate_platform_fee()
        self.seller_net_amount = self.agreed_price - self.platform_fee_amount
        
        super().save(*args, **kwargs)
    
    def _calculate_platform_fee(self):
        """
        Calculate platform fee based on tiered structure:
        - Below 1M KES: 3%
        - 1M - 5M: 2.5%
        - 5M - 10M: 2%
        - Above 10M: 1.5%
        """
        value = self.agreed_price
        if value < 1000000:
            percentage = Decimal('0.03')
        elif value < 5000000:
            percentage = Decimal('0.025')
        elif value < 10000000:
            percentage = Decimal('0.02')
        else:
            percentage = Decimal('0.015')
        
        self.platform_fee_percentage = percentage * 100
        return (value * percentage).quantize(Decimal('0.01'))
    
    def _get_statutory_consent_docs(self):
        """Return required statutory consent documents based on plot properties."""
        from .models import TransactionDocument
        docs = []
        if self.plot and self.plot.land_type == 'agricultural':
            docs.append(TransactionDocument.DocType.LCB_CONSENT)
        if self.plot and getattr(self.plot, 'is_matrimonial_property', False):
            docs.append(TransactionDocument.DocType.SPOUSAL_CONSENT)
        return docs
    
    def get_required_documents_for_stage(self, stage=None):
        """
        Return list of required document types for the specified stage.
        If no stage is provided, uses the current stage.
        """
        from .models import TransactionDocument
        
        target_stage = stage or self.stage
        
        stage_document_map = {
            self.Stage.DUE_DILIGENCE: [
                TransactionDocument.DocType.OFFICIAL_SEARCH,
                TransactionDocument.DocType.SURVEY_MAP,
            ],
            self.Stage.COMMITMENT: [
                TransactionDocument.DocType.LETTER_OF_OFFER,
            ],
            self.Stage.CONTRACTS: [
                TransactionDocument.DocType.SALE_AGREEMENT,
            ],
            self.Stage.STATUTORY_CONSENTS: self._get_statutory_consent_docs(),
            self.Stage.TAXATION: [
                TransactionDocument.DocType.STAMP_DUTY_RECEIPT,
                TransactionDocument.DocType.VALUATION_REPORT,
            ],
            self.Stage.COMPLETION: [],
            self.Stage.REGISTRATION: [
                TransactionDocument.DocType.ORIGINAL_TITLE_DEED,
                TransactionDocument.DocType.TRANSFER_FORM,
                TransactionDocument.DocType.ID_DOCUMENT,
                TransactionDocument.DocType.KRA_PIN,
                TransactionDocument.DocType.PASSPORT_PHOTO,
                TransactionDocument.DocType.RATES_CLEARANCE,
                TransactionDocument.DocType.RENT_CLEARANCE,
                TransactionDocument.DocType.NEW_TITLE_DEED,
            ],
            self.Stage.DISBURSEMENT: [
                TransactionDocument.DocType.NEW_TITLE_DEED,
            ],
        }
        return stage_document_map.get(target_stage, [])
    
    def get_required_deposit_percentage(self):
        """
        Return required deposit percentage for current stage.
        Under platform escrow model:
        - At CONTRACTS stage: 10% deposit must be in escrow
        - At COMPLETION stage: 100% (10% + 90%) must be in escrow
        """
        if self.stage == self.Stage.CONTRACTS:
            return Decimal('0.10')
        elif self.stage == self.Stage.COMPLETION:
            return Decimal('1.00')
        return Decimal('0.00')
    
    def get_required_deposit_amount(self):
        """Return the actual amount required for current stage"""
        percentage = self.get_required_deposit_percentage()
        return self.agreed_price * percentage
    
    def can_advance_to_next_stage(self):
        """
        Validate all statutory requirements before advancing.
        Returns (can_advance: bool, message: str)
        """
        from .models import TransactionDocument
        
        # Check required documents for current stage
        required_docs = self.get_required_documents_for_stage()
        for doc_type in required_docs:
            doc_qs = TransactionDocument.objects.filter(
                transaction=self,
                document_type=doc_type,
            )
            verified_doc = doc_qs.filter(status=TransactionDocument.Status.VERIFIED).first()
            if verified_doc:
                continue

            pending_doc = doc_qs.filter(status=TransactionDocument.Status.PENDING).first()
            rejected_doc = doc_qs.filter(status=TransactionDocument.Status.REJECTED).first()
            doc_label = dict(TransactionDocument.DocType.choices).get(doc_type, doc_type)
            if pending_doc:
                return False, (
                    f"{doc_label} has been uploaded but is still awaiting verification. "
                    "Please ask an admin to verify it before advancing."
                )
            if rejected_doc:
                return False, (
                    f"{doc_label} was rejected. Please upload a new copy before advancing."
                )
            return False, f"Missing required legal document: {doc_label}"
        
        # ============================================================
        # FIXED DEPOSIT/ESCROW REQUIREMENTS CHECK
        # ============================================================
        if self.stage == self.Stage.CONTRACTS:
            # Only 10% deposit is required at this stage
            if self.deposit_paid < self.ten_percent_deposit:
                return False, f"10% deposit required: KES {self.ten_percent_deposit:,.2f} (Currently held: KES {self.deposit_paid:,.2f})"
                
        elif self.stage == self.Stage.COMPLETION:
            # Both 10% deposit AND 90% balance must be in escrow at Completion
            if self.deposit_paid < self.ten_percent_deposit:
                return False, f"10% deposit not fully held in escrow. Required: KES {self.ten_percent_deposit:,.2f}"
            if self.balance_paid < self.ninety_percent_balance:
                return False, f"90% completion balance not fully held in escrow. Required: KES {self.ninety_percent_balance:,.2f}"
        # ============================================================
        
        # Stage-specific additional validations
        if self.stage == self.Stage.DUE_DILIGENCE:
            official_search = TransactionDocument.objects.filter(
                transaction=self,
                document_type=TransactionDocument.DocType.OFFICIAL_SEARCH,
                status='verified'
            ).first()
            if official_search and official_search.search_date:
                if (timezone.now().date() - official_search.search_date).days > 30:
                    return False, "Official search certificate is older than 30 days. Please upload a recent search."
        
        elif self.stage == self.Stage.STATUTORY_CONSENTS:
            if self.plot.is_matrimonial_property:
                has_spousal_consent = TransactionDocument.objects.filter(
                    transaction=self,
                    document_type=TransactionDocument.DocType.SPOUSAL_CONSENT,
                    status='verified'
                ).exists()
                if not has_spousal_consent:
                    return False, "Spousal consent required for matrimonial property under Section 93 of LRA 2012."
            
            if self.plot.land_type == 'agricultural':
                has_lcb = TransactionDocument.objects.filter(
                    transaction=self,
                    document_type=TransactionDocument.DocType.LCB_CONSENT,
                    status='verified'
                ).exists()
                if not has_lcb:
                    return False, "Land Control Board consent required for agricultural land under Cap 302."
        
        elif self.stage == self.Stage.TAXATION:
            expected_rate = Decimal('2.00') if self.plot.market_zone == 'rural' else Decimal('4.00')
            
            if self.stamp_duty_percentage != expected_rate:
                return False, f"Stamp duty rate should be {expected_rate}% for {self.plot.market_zone} land."
            
            if not self.stamp_duty_receipt_verified_at:
                return False, "Stamp duty receipt not verified. Please pay stamp duty directly to KRA via iTax and upload the receipt."
        
        elif self.stage == self.Stage.REGISTRATION:
            has_new_title = TransactionDocument.objects.filter(
                transaction=self,
                document_type=TransactionDocument.DocType.NEW_TITLE_DEED,
                status='verified'
            ).exists()
            if not has_new_title:
                return False, "New title deed not verified. Registration must complete before disbursement."
        
        elif self.stage == self.Stage.DISBURSEMENT:
            has_new_title = TransactionDocument.objects.filter(
                transaction=self,
                document_type=TransactionDocument.DocType.NEW_TITLE_DEED,
                status='verified'
            ).exists()
            if not has_new_title:
                return False, "New title deed not verified. Registration must complete before disbursement."
        
        return True, "All legal requirements met"
    
    def get_stage_index(self):
        """Return the numeric index of the current stage (1-8)"""
        stage_order = [
            self.Stage.DUE_DILIGENCE,
            self.Stage.COMMITMENT,
            self.Stage.CONTRACTS,
            self.Stage.STATUTORY_CONSENTS,
            self.Stage.TAXATION,
            self.Stage.COMPLETION,
            self.Stage.REGISTRATION,
            self.Stage.DISBURSEMENT,
            self.Stage.COMPLETED,
        ]
        if self.stage in stage_order:
            return stage_order.index(self.stage) + 1
        return 0
    
    def advance_stage(self, actor=None):
        """
        Advance to next stage after validating all statutory requirements.
        This enforces the chronological legal pipeline.
        """
        from .models import TransactionMilestone
        
        if self.stage == self.Stage.COMPLETED:
            raise ValueError("Transaction already completed")
        
        if self.stage == self.Stage.CANCELLED:
            raise ValueError("Transaction has been cancelled")
        
        can_advance, message = self.can_advance_to_next_stage()
        if not can_advance:
            raise ValueError(message)
        
        # Record completion time for current stage
        stage_time_fields = {
            self.Stage.DUE_DILIGENCE: 'due_diligence_completed_at',
            self.Stage.COMMITMENT: 'commitment_completed_at',
            self.Stage.CONTRACTS: 'contracts_completed_at',
            self.Stage.STATUTORY_CONSENTS: 'statutory_consents_completed_at',
            self.Stage.TAXATION: 'taxation_completed_at',
            self.Stage.REGISTRATION: 'registration_completed_at',
            self.Stage.DISBURSEMENT: 'disbursement_completed_at',
        }
        
        field_name = stage_time_fields.get(self.stage)
        if field_name:
            setattr(self, field_name, timezone.now())
        
        stage_order = [
            self.Stage.DUE_DILIGENCE,
            self.Stage.COMMITMENT,
            self.Stage.CONTRACTS,
            self.Stage.STATUTORY_CONSENTS,
            self.Stage.TAXATION,
            self.Stage.COMPLETION,
            self.Stage.REGISTRATION,
            self.Stage.DISBURSEMENT,
            self.Stage.COMPLETED,
        ]
        
        current_index = stage_order.index(self.stage) if self.stage in stage_order else -1
        next_index = current_index + 1
        
        if next_index < len(stage_order):
            self.stage = stage_order[next_index]
            
            TransactionMilestone.objects.create(
                transaction=self,
                milestone_type=self.stage,
                achieved_by=actor,
                notes=f"Advanced from {stage_order[current_index]} to {self.stage} per Land Act 2012"
            )
            
            self.save()
            
            if self.stage == self.Stage.DISBURSEMENT:
                self._trigger_disbursement(actor)
            
            if self.stage == self.Stage.COMPLETED:
                self._finalize_transaction(actor)
            
            # Auto-chain: if the new stage also has all requirements met,
            # continue advancing (e.g., STATUTORY_CONSENTS with no docs needed).
            # Guard against infinite loops by only chaining for non-terminal stages.
            if self.stage not in (self.Stage.COMPLETED, self.Stage.CANCELLED):
                try:
                    chain_ok, chain_msg = self.can_advance_to_next_stage()
                    if chain_ok:
                        return self.advance_stage(actor=actor)
                except Exception:
                    pass  # Don't block the current advance if chaining fails
            
            return True, f"Legal milestone achieved: {self.get_stage_display()}"
        else:
            return False, "Unknown stage progression"
    
    def _trigger_disbursement(self, actor=None):
        """Trigger fund disbursement to seller after registration."""
        from notifications.notification_service import NotificationService
        
        self.disbursed_at = timezone.now()
        self.platform_fee_deducted_at = timezone.now()
        self.save(update_fields=['disbursed_at', 'platform_fee_deducted_at'])
        
        self.add_event(
            'disbursement_initiated',
            f"Disbursement initiated. Platform fee: KES {self.platform_fee_amount:,.2f}, Seller net: KES {self.seller_net_amount:,.2f}",
            actor=actor
        )
        
        if self.payment_request and not self.payment_request.disbursed_at:
            try:
                self.payment_request.apply_transition("disburse_to_seller", actor=actor)
                
                self.add_event(
                    'payment_disbursed',
                    f"Funds disbursed to seller via payment request {self.payment_request.internal_reference}",
                    actor=actor
                )
            except Exception as e:
                self.add_event('disbursement_failed', f"Disbursement failed: {str(e)}", actor=actor)
                raise
    
    def _finalize_transaction(self, actor=None):
        """Final actions when transaction completes: plot sold, reports sent"""
        from notifications.notification_service import NotificationService
        
        self.plot.market_status = 'sold'
        self.plot.availability_notes = (
            f"Sold via transaction {self.id} on {timezone.now().date()}. "
            f"Per Land Registration Act 2012, title transferred to {self.buyer.get_full_name()}."
        )
        self.plot.save(update_fields=['market_status', 'availability_notes'])
        
        TransactionMilestone.objects.create(
            transaction=self,
            milestone_type=TransactionMilestone.MilestoneType.COMPLETED,
            achieved_by=actor,
            notes="Transaction completed. Title transferred. Funds disbursed. Reports sent."
        )
        
        self.completed_at = timezone.now()
        self.save(update_fields=['completed_at'])
        
        self._send_transaction_reports()
    
    def _send_transaction_reports(self):
        """Send comprehensive transaction reports to both parties via email"""
        from notifications.notification_service import NotificationService
        from django.template.loader import render_to_string
        
        self.reports_sent_at = timezone.now()
        self.save(update_fields=['reports_sent_at'])
        
        report_data = {
            'transaction_id': self.id,
            'plot_title': self.plot.title,
            'agreed_price': self.agreed_price,
            'deposit_paid': self.deposit_paid,
            'balance_paid': self.balance_paid,
            'platform_fee': self.platform_fee_amount,
            'seller_net': self.seller_net_amount,
            'stamp_duty': self.stamp_duty_amount,
            'stamp_duty_receipt': self.stamp_duty_receipt_number,
            'completion_date': self.completed_at,
            'buyer_name': self.buyer.get_full_name(),
            'seller_name': self.seller.get_full_name(),
            'lcb_consent': self.lcb_consent_reference,
            'lcb_meeting_date': self.lcb_meeting_date,
            'milestones': list(self.milestones.values('milestone_type', 'achieved_at')),
        }
        
        buyer_subject = f"Transaction Complete - {self.plot.title} - Your Land Purchase Report"
        buyer_html = render_to_string('transactions/emails/buyer_completion_report.html', report_data)
        buyer_text = f"""
Transaction Complete: {self.plot.title}

Property Details:
- Plot: {self.plot.title}
- Location: {self.plot.location}
- Title Number: {self.plot.title_number}

Financial Summary:
- Purchase Price: KES {self.agreed_price:,.2f}
- 10% Deposit Paid: KES {self.deposit_paid:,.2f}
- 90% Balance Paid: KES {self.balance_paid:,.2f}
- Stamp Duty Paid to KRA: KES {self.stamp_duty_amount:,.2f} (Receipt: {self.stamp_duty_receipt_number})

Legal Documents:
- New Title Deed issued in your name
- LCB Consent: {self.lcb_consent_reference}
- Completion Date: {self.completed_at.date()}

Keep this report and your title deed for your records.
        """
        
        seller_subject = f"Transaction Complete - {self.plot.title} - Funds Disbursed"
        seller_html = render_to_string('transactions/emails/seller_completion_report.html', report_data)
        seller_text = f"""
Transaction Complete: {self.plot.title}

Financial Summary:
- Sale Price: KES {self.agreed_price:,.2f}
- Platform Fee ({self.platform_fee_percentage}%): KES {self.platform_fee_amount:,.2f}
- Net Amount Received: KES {self.seller_net_amount:,.2f}

Important Tax Information:
- Stamp duty was paid by buyer directly to KRA
- You are responsible for filing Capital Gains Tax (15% of profit) within 30 days
- Consult your tax advisor for CGT filing requirements

Completion Date: {self.completed_at.date()}
        """
        
        try:
            NotificationService.send_email(
                recipient=self.buyer.email,
                subject=buyer_subject,
                html_content=buyer_html,
                text_content=buyer_text
            )
            
            NotificationService.send_email(
                recipient=self.seller.email,
                subject=seller_subject,
                html_content=seller_html,
                text_content=seller_text
            )
            
            self.add_event('reports_sent', f"Transaction reports sent to {self.buyer.email} and {self.seller.email}")
            
        except Exception as e:
            self.add_event('reports_failed', f"Failed to send reports: {str(e)}")
    
    def add_event(self, event_type, message, actor=None, ip_address=None):
        """Add an event to the transaction audit log"""
        from .models import TransactionEvent
        return TransactionEvent.objects.create(
            transaction=self,
            event_type=event_type,
            actor=actor,
            message=message,
            ip_address=ip_address
        )
    
    def mark_stamp_duty_verified(self, receipt_number, verified_by):
        """Mark stamp duty as verified (payment made directly to KRA)"""
        self.stamp_duty_receipt_number = receipt_number
        self.stamp_duty_receipt_verified_at = timezone.now()
        self.stamp_duty_verified_by = verified_by
        self.save(update_fields=['stamp_duty_receipt_number', 'stamp_duty_receipt_verified_at', 'stamp_duty_verified_by'])
        
        self.add_event(
            'stamp_duty_verified',
            f"Stamp duty verified: Receipt {receipt_number} paid directly to KRA via iTax",
            actor=verified_by
        )


class TransactionDocument(models.Model):
    """
    Legal documents required for land transfer under Kenyan law.
    Each document maps to a specific statutory requirement.
    """
    
    class DocType(models.TextChoices):
        # Phase 1: Due Diligence (Land Act 2012, Section 7)
        OFFICIAL_SEARCH = 'OFFICIAL_SEARCH', 'Official Land Search Certificate (From ArdhiSasa Portal)'
        SURVEY_MAP = 'SURVEY_MAP', 'Survey Map / Beacon Report / RIM'
        
        # Phase 2: Commitment (Preliminary)
        LETTER_OF_OFFER = 'LETTER_OF_OFFER', 'Letter of Offer (Intent to Purchase)'
        
        # Phase 3: Contracts (LSK Conditions of Sale)
        SALE_AGREEMENT = 'SALE_AGREEMENT', 'Signed Sale Agreement (LSK Form)'
        
        # Phase 4: Statutory Consents (Land Control Act Cap 302)
        LCB_CONSENT = 'LCB_CONSENT', 'Land Control Board Consent (Cap 302)'
        SPOUSAL_CONSENT = 'SPOUSAL_CONSENT', 'Spousal Consent Affidavit (LRA 2012, Sec 93)'
        
        # Phase 5: Taxation (Stamp Duty Act - Paid Directly to KRA)
        STAMP_DUTY_RECEIPT = 'STAMP_DUTY_RECEIPT', 'Stamp Duty Payment Receipt (KRA iTax)'
        VALUATION_REPORT = 'VALUATION_REPORT', 'Government Valuation Report'
        
        # Phase 6: Registration (Land Registration Act 2012)
        TRANSFER_FORM = 'TRANSFER_FORM', 'Signed Transfer Form (RL 1)'
        ORIGINAL_TITLE_DEED = 'ORIGINAL_TITLE_DEED', 'Original Title Deed (Surrendered)'
        NEW_TITLE_DEED = 'NEW_TITLE_DEED', 'New Certificate of Title (Buyer\'s Name)'
        
        # Supporting Documents
        ID_DOCUMENT = 'ID_DOCUMENT', 'National ID (Buyer/Seller)'
        KRA_PIN = 'KRA_PIN', 'KRA PIN Certificate'
        RATES_CLEARANCE = 'RATES_CLEARANCE', 'Land Rates Clearance Certificate (County)'
        RENT_CLEARANCE = 'RENT_CLEARANCE', 'Land Rent Clearance Certificate (National)'
        PASSPORT_PHOTO = 'PASSPORT_PHOTO', 'Passport Photos (Buyer/Seller)'
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending Verification'
        VERIFIED = 'verified', 'Verified by Admin'
        REJECTED = 'rejected', 'Rejected'
    
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30, choices=DocType.choices)
    file = models.FileField(upload_to='transactions/documents/%Y/%m/%d/')
    filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(help_text="File size in bytes")
    mime_type = models.CharField(max_length=100)
    
    # Document-specific metadata
    document_date = models.DateField(null=True, blank=True, help_text="Date on the document")
    reference_number = models.CharField(max_length=100, blank=True, help_text="LCB ref, Stamp Duty ref, etc.")
    search_date = models.DateField(null=True, blank=True, help_text="For official search certificates")
    
    # Verification
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    # Metadata
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='uploaded_documents')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        unique_together = [['transaction', 'document_type']]
    
    def __str__(self):
        return f"{self.get_document_type_display()} - Transaction {self.transaction.id}"


class TransactionMilestone(models.Model):
    """Legal audit trail of stage advancements (required for dispute resolution)"""
    
    class MilestoneType(models.TextChoices):
        DUE_DILIGENCE = 'due_diligence', 'Due Diligence Completed (Land Act 2012)'
        COMMITMENT = 'commitment', 'Letter of Offer Issued'
        CONTRACTS = 'contracts', 'Sale Agreement Signed & 10% Escrow (LSK Conditions)'
        STATUTORY_CONSENTS = 'statutory_consents', 'LCB & Spousal Consents Obtained'
        TAXATION = 'taxation', 'Stamp Duty Paid to KRA (Tax Laws)'
        COMPLETION = 'completion', 'Completion Balance Paid'
        REGISTRATION = 'registration', 'Title Transferred (LRA 2012)'
        DISBURSEMENT = 'disbursement', 'Funds Disbursed to Seller (Platform Fee Deducted)'
        COMPLETED = 'completed', 'Transaction Completed & Reports Sent'
        CANCELLED = 'cancelled', 'Transaction Cancelled'
    
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='milestones')
    milestone_type = models.CharField(max_length=30, choices=MilestoneType.choices)
    achieved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    achieved_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['achieved_at']
    
    def __str__(self):
        return f"TX {self.transaction.id} - {self.get_milestone_type_display()} - {self.achieved_at.date()}"


class TransactionEvent(models.Model):
    """Immutable audit log for all transaction events"""
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=50)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    message = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.created_at}: {self.event_type} - {self.transaction.id}"
