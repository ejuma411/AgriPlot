from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

class Transaction(models.Model):
    class Stage(models.TextChoices):
        DRAFT = "draft", "Draft / Negotiation"
        DUE_DILIGENCE = "due_diligence", "Due Diligence (Search & Site Visit)"
        SALE_AGREEMENT = "sale_agreement", "Sale Agreement Execution"
        LCB_CONSENT = "lcb_consent", "Land Control Board Consent"
        VALUATION = "valuation", "Government Valuation"
        STAMP_DUTY = "stamp_duty", "Stamp Duty Payment"
        TRANSFER_EXECUTION = "transfer_execution", "Transfer Execution (Form 30)"
        REGISTRATION = "registration", "Registry Registration"
        COMPLETED = "completed", "Completed / Handover"
        CANCELLED = "cancelled", "Cancelled"

    class PartyType(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        COMPANY = "company", "Company / Corporate"
        TRUST = "trust", "Trust"

    # Core Links
    plot = models.ForeignKey("listings.Plot", on_delete=models.CASCADE, related_name="land_transactions")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="land_sales")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="land_purchases")
    
    # Financials
    agreed_price = models.DecimalField(max_digits=12, decimal_places=2)
    deposit_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Status
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.DRAFT)
    is_completed = models.BooleanField(default=False)
    
    # Buyer KYC (Kenyan Context)
    buyer_type = models.CharField(max_length=20, choices=PartyType.choices, default=PartyType.INDIVIDUAL)
    buyer_id_number = models.CharField(max_length=50, blank=True, help_text="National ID or Reg Number")
    buyer_kra_pin = models.CharField(max_length=20, blank=True)
    buyer_address = models.TextField(blank=True)
    
    # Legal Representatives
    seller_advocate = models.CharField(max_length=200, blank=True)
    buyer_advocate = models.CharField(max_length=200, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"TRX-{self.id:05d}: {self.plot.title} ({self.get_stage_display()})"

    def save(self, *args, **kwargs):
        if self.stage == self.Stage.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()
            self.is_completed = True
        super().save(*args, **kwargs)


class TransactionMilestone(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="milestones")
    stage = models.CharField(max_length=30, choices=Transaction.Stage.choices)
    notes = models.TextField(blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction.id} - {self.get_stage_display()}"


class TransactionDocument(models.Model):
    class DocType(models.TextChoices):
        SALE_AGREEMENT = "sale_agreement", "Signed Sale Agreement"
        TRANSFER_FORM = "transfer_form", "Transfer Form (Form 30)"
        STAMP_DUTY_RECEIPT = "stamp_duty_receipt", "Stamp Duty Receipt"
        VALUATION_REPORT = "valuation_report", "Government Valuation Report"
        LCB_CONSENT = "lcb_consent", "LCB Consent Certificate"
        CR12 = "cr12", "CR12 (for Companies)"
        BUYER_ID = "buyer_id", "Buyer National ID"
        BUYER_PHOTO = "buyer_photo", "Buyer Passport Photo"
        REGISTRATION_PROOF = "registration_proof", "Registration Proof / New Title Copy"

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=30, choices=DocType.choices)
    file = models.FileField(upload_to="transaction_docs/")
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction.id} - {self.get_doc_type_display()}"
