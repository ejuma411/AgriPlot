"""
Transaction Models for AgriPlot Connect
Strict implementation of Kenyan Land Laws:
- Land Act 2012
- Land Registration Act 2012
- Land Control Act Cap 302
- LSK Conditions of Sale
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
    3. CONTRACTS: Sale Agreement + 10% Escrow Deposit
    4. STATUTORY_CONSENTS: LCB Consent + Spousal Consent (if applicable)
    5. TAXATION: Stamp Duty (2% rural / 4% urban) + CGT (15%)
    6. REGISTRATION: Title Transfer & New Title Deed
    7. COMPLETED: Escrow Release + Final Payout
    """
    
    class Stage(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        DUE_DILIGENCE = 'due_diligence', 'Due Diligence (Official Search & Survey)'
        COMMITMENT = 'commitment', 'Letter of Offer (Intent to Purchase)'
        CONTRACTS = 'contracts', 'Sale Agreement & 10% Escrow Deposit'
        STATUTORY_CONSENTS = 'statutory_consents', 'LCB Consent & Spousal Consent'
        TAXATION = 'taxation', 'Stamp Duty & Capital Gains Tax'
        REGISTRATION = 'registration', 'Title Registration & Transfer'
        COMPLETED = 'completed', 'Completed & Disbursed'
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
        related_name='legal_transaction'
    )


    # Related Parties
    plot = models.ForeignKey('listings.Plot', on_delete=models.PROTECT, related_name='land_transactions')
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='land_purchases')
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='land_sales')
    
    # Financial Details
    agreed_price = models.DecimalField(max_digits=15, decimal_places=2)
    ten_percent_deposit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    ninety_percent_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    deposit_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Tax Calculations (Kenya specific)
    stamp_duty_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=2.00)  # 2% rural, 4% urban
    stamp_duty_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    capital_gains_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # 15% of profit
    
    # Timestamps for each stage (legal audit trail)
    due_diligence_completed_at = models.DateTimeField(null=True, blank=True)
    commitment_completed_at = models.DateTimeField(null=True, blank=True)
    contracts_completed_at = models.DateTimeField(null=True, blank=True)
    statutory_consents_completed_at = models.DateTimeField(null=True, blank=True)
    taxation_completed_at = models.DateTimeField(null=True, blank=True)
    registration_completed_at = models.DateTimeField(null=True, blank=True)
    
    # LCB Specifics
    lcb_meeting_date = models.DateField(null=True, blank=True)
    lcb_consent_reference = models.CharField(max_length=100, blank=True)
    lcb_application_fee = models.DecimalField(max_digits=10, decimal_places=2, default=1000)
    
    # Completion
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Transaction {self.id}: {self.plot.title} - {self.buyer.username}"
    
    def save(self, *args, **kwargs):
        """Auto-calculate financial values"""
        self.ten_percent_deposit = self.agreed_price * Decimal('0.10')
        self.ninety_percent_balance = self.agreed_price - self.ten_percent_deposit
        self.balance_due = self.agreed_price - self.deposit_paid
        super().save(*args, **kwargs)
    
    def get_required_documents_for_stage(self):
        """
        Return list of required document types for current stage.
        Based on Kenyan Land Law statutory requirements.
        """
        from .models import TransactionDocument
        
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
            self.Stage.STATUTORY_CONSENTS: [
                TransactionDocument.DocType.LCB_CONSENT,
                TransactionDocument.DocType.SPOUSAL_CONSENT,
            ],
            self.Stage.TAXATION: [
                TransactionDocument.DocType.ORIGINAL_TITLE_DEED,
                TransactionDocument.DocType.TRANSFER_FORM,
                TransactionDocument.DocType.ID_DOCUMENT,
                TransactionDocument.DocType.KRA_PIN,
                TransactionDocument.DocType.PASSPORT_PHOTO,
                TransactionDocument.DocType.RATES_CLEARANCE,
                TransactionDocument.DocType.RENT_CLEARANCE,
                TransactionDocument.DocType.STAMP_DUTY_ASSESSMENT,
            ],
            self.Stage.REGISTRATION: [
                TransactionDocument.DocType.NEW_TITLE_DEED,
            ],
        }
        return stage_document_map.get(self.stage, [])
    
    def get_required_deposit_percentage(self):
        """
        Return required deposit percentage for current stage.
        Legal requirements under LSK Conditions of Sale.
        """
        if self.stage == self.Stage.CONTRACTS:
            return Decimal('0.10')  # 10% deposit upon signing Sale Agreement
        elif self.stage == self.Stage.TAXATION:
            return Decimal('1.00')  # 100% total (10% deposit + 90% balance) before stamp duty & registration
        return Decimal('0.00')
    
    def can_advance_to_next_stage(self):
        """
        Validate all statutory requirements before advancing.
        Returns (can_advance: bool, message: str)
        """
        from .models import TransactionDocument
        from django.db.models import Q
        
        # Check required documents
        required_docs = self.get_required_documents_for_stage()
        for doc_type in required_docs:
            has_doc = TransactionDocument.objects.filter(
                transaction=self,
                document_type=doc_type,
                status='verified'
            ).exists()
            if not has_doc:
                doc_label = dict(TransactionDocument.DocType.choices).get(doc_type, doc_type)
                return False, f"Missing required legal document: {doc_label}"
        
        # Check deposit requirements
        required_percentage = self.get_required_deposit_percentage()
        if required_percentage > 0:
            required_amount = self.agreed_price * required_percentage
            if self.deposit_paid < required_amount:
                return False, f"Required escrow deposit: {required_percentage*100}% (KES {required_amount:,.2f})"
        
        # Stage-specific additional validations
        if self.stage == self.Stage.DUE_DILIGENCE:
            # Ensure official search is not older than 30 days
            official_search = TransactionDocument.objects.filter(
                transaction=self,
                document_type=TransactionDocument.DocType.OFFICIAL_SEARCH,
                status='verified'
            ).first()
            if official_search and official_search.search_date:
                if (timezone.now().date() - official_search.search_date).days > 30:
                    return False, "Official search certificate is older than 30 days. Please upload a recent search."
        
        elif self.stage == self.Stage.STATUTORY_CONSENTS:
            # Spousal consent is only required for matrimonial property
            if self.plot.is_matrimonial_property:
                has_spousal_consent = TransactionDocument.objects.filter(
                    transaction=self,
                    document_type=TransactionDocument.DocType.SPOUSAL_CONSENT,
                    status='verified'
                ).exists()
                if not has_spousal_consent:
                    return False, "Spousal consent required for matrimonial property under Section 93 of LRA 2012."
            
            # LCB consent is mandatory for agricultural land
            if self.plot.land_type == 'agricultural':
                has_lcb = TransactionDocument.objects.filter(
                    transaction=self,
                    document_type=TransactionDocument.DocType.LCB_CONSENT,
                    status='verified'
                ).exists()
                if not has_lcb:
                    return False, "Land Control Board consent required for agricultural land under Cap 302."
        
        elif self.stage == self.Stage.TAXATION:
            # Verify stamp duty percentage based on land zone
            if self.plot.market_zone == 'rural':
                expected_rate = Decimal('2.00')
            else:
                expected_rate = Decimal('4.00')
            
            if self.stamp_duty_percentage != expected_rate:
                return False, f"Stamp duty rate should be {expected_rate}% for {self.plot.market_zone} land."
        
        return True, "All legal requirements met"
    
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
        
        # Validate requirements
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
        }
        
        field_name = stage_time_fields.get(self.stage)
        if field_name:
            setattr(self, field_name, timezone.now())
        
        # Determine next stage (chronological order by law)
        stage_order = [
            self.Stage.DUE_DILIGENCE,
            self.Stage.COMMITMENT,
            self.Stage.CONTRACTS,
            self.Stage.STATUTORY_CONSENTS,
            self.Stage.TAXATION,
            self.Stage.REGISTRATION,
            self.Stage.COMPLETED,
        ]
        
        current_index = stage_order.index(self.stage) if self.stage in stage_order else -1
        next_index = current_index + 1
        
        if next_index < len(stage_order):
            self.stage = stage_order[next_index]
            
            # Create milestone record for legal audit trail
            TransactionMilestone.objects.create(
                transaction=self,
                milestone_type=self.stage,
                achieved_by=actor,
                notes=f"Advanced from {stage_order[current_index]} to {self.stage} per Land Act 2012"
            )
            
            self.save()
            
            # If completed, trigger final actions
            if self.stage == self.Stage.COMPLETED:
                self._finalize_transaction(actor)
            
            return True, f"Legal milestone achieved: {self.get_stage_display()}"
        else:
            return False, "Unknown stage progression"
    
    def _finalize_transaction(self, actor=None):
        """Final actions when transaction completes: plot sold, payout triggered"""
        from notifications.notification_service import NotificationService
        from payments.wallet_service import WalletService
        
        # 1. Update plot status to SOLD (removes from marketplace)
        self.plot.market_status = 'sold'
        self.plot.availability_notes = f"Sold via transaction {self.id} on {timezone.now().date()}. Per Land Registration Act 2012, title transferred to {self.buyer.get_full_name()}."
        self.plot.save(update_fields=['market_status', 'availability_notes'])
        
        # 2. Create completion milestone
        TransactionMilestone.objects.create(
            transaction=self,
            milestone_type=TransactionMilestone.MilestoneType.COMPLETED,
            achieved_by=actor,
            notes="Transaction completed. Title transferred. Escrow funds disbursed."
        )
        
        # 3. Release Escrow to Seller's Wallet (90% balance)
        payout_amount = self.agreed_price - self.stamp_duty_amount - self.capital_gains_tax
        
        try:
            result = WalletService.release_escrow_to_wallet(
                user=self.seller,
                amount=payout_amount,
                payment_request=self.payment_request,
                description=f"Final land sale proceeds - per Land Act 2012 for plot {self.plot.title}"
            )
            if result.get('success'):
                self.add_event(
                    'payout_initiated',
                    f"Final payout of KES {payout_amount:,.2f} released to {self.seller.username}'s Wallet",
                    actor=actor
                )
        except Exception as e:
            self.add_event('payout_failed', f"Payout to wallet failed: {str(e)}", actor=actor)
        
        self.completed_at = timezone.now()
        self.save(update_fields=['completed_at'])
        
        # 4. Send notifications
        NotificationService.notify_transaction_completed(self)
    
    def add_event(self, event_type, message, actor=None):
        """Add an event to the transaction audit log"""
        from .models import TransactionEvent
        return TransactionEvent.objects.create(
            transaction=self,
            event_type=event_type,
            actor=actor,
            message=message
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
        
        # Phase 5: Taxation (Stamp Duty Act, Income Tax Act)
        STAMP_DUTY_ASSESSMENT = 'STAMP_DUTY_ASSESSMENT', 'Stamp Duty Assessment Form'
        STAMP_DUTY_RECEIPT = 'STAMP_DUTY_RECEIPT', 'Stamp Duty Payment Receipt (eCitizen)'
        VALUATION_REPORT = 'VALUATION_REPORT', 'Government Valuation Report'
        CGT_RECEIPT = 'CGT_RECEIPT', 'Capital Gains Tax Payment Receipt (15%)'
        
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
        TAXATION = 'taxation', 'Stamp Duty & CGT Paid (Tax Laws)'
        REGISTRATION = 'registration', 'Title Transferred (LRA 2012)'
        COMPLETED = 'completed', 'Transaction Completed & Disbursed'
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