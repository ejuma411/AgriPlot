import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class PaymentRequest(models.Model):
    class TransactionType(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        LEASE = "lease", "Lease"
        SERVICE = "service", "Service"

    class Category(models.TextChoices):
        VIEWING_FEE = "viewing_fee", "Viewing Fee"
        RESERVATION_DEPOSIT = "reservation_deposit", "Reservation Deposit"
        VERIFICATION_PACKAGE = "verification_package", "Verification Package"
        ESCROW_DEPOSIT = "escrow_deposit", "Escrow Deposit"
        SERVICE_FEE = "service_fee", "Service Fee"

    class Method(models.TextChoices):
        MPESA_STK = "mpesa_stk", "M-Pesa STK Push"
        MPESA_PAYBILL = "mpesa_paybill", "M-Pesa Paybill / Till"
        CARD = "card", "Card"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        AIRTEL_MONEY = "airtel_money", "Airtel Money"
        WALLET = "wallet", "AgriPlot Wallet"
        MANUAL_ESCROW = "manual_escrow", "Manual Escrow"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending Payment"
        PAID = "paid", "Paid"
        IN_ESCROW = "in_escrow", "In Escrow"
        PARTIALLY_RELEASED = "partially_released", "Partially Released"
        RELEASED = "released", "Released"
        REFUNDED = "refunded", "Refunded"
        DISPUTED = "disputed", "Disputed"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    TRANSITION_RULES = {
        Status.DRAFT: {"submit", "cancel", "fail"},
        Status.PENDING: {"mark_paid", "cancel", "fail", "dispute"},
        Status.PAID: {"move_escrow", "refund", "dispute", "cancel"},
        Status.IN_ESCROW: {"partial_release", "release", "refund", "dispute"},
        Status.PARTIALLY_RELEASED: {"release", "refund", "dispute"},
        Status.DISPUTED: {"refund", "release", "cancel"},
        Status.RELEASED: set(),
        Status.REFUNDED: set(),
        Status.CANCELLED: set(),
        Status.FAILED: set(),
    }

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_requests_as_buyer",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_requests_as_seller",
    )
    plot = models.ForeignKey(
        "listings.Plot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_requests",
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="KES")
    transaction_type = models.CharField(
        max_length=20, choices=TransactionType.choices, default=TransactionType.SERVICE
    )
    category = models.CharField(
        max_length=40, choices=Category.choices, default=Category.VIEWING_FEE
    )
    method = models.CharField(
        max_length=40, choices=Method.choices, default=Method.MPESA_STK
    )
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.DRAFT
    )
    phone_number = models.CharField(max_length=20, blank=True)
    escrow_enabled = models.BooleanField(default=True)
    provider_reference = models.CharField(max_length=120, blank=True)
    internal_reference = models.CharField(max_length=24, unique=True, editable=False)
    lease_start_date = models.DateField(null=True, blank=True)
    lease_end_date = models.DateField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    PURCHASE_CLOSING_STEPS = [
        (
            "offer",
            "Offer to Purchase",
            "Offer / Letter of Intent",
            "Buyer advocate issues the offer to purchase with the proposed price and completion window.",
        ),
        (
            "agreement",
            "Sale Agreement Signed",
            "Signed Sale Agreement",
            "Seller advocate drafts the agreement and both parties sign after review.",
        ),
        (
            "lcb_consent",
            "LCB Consent Obtained",
            "Land Control Board Consent Letter",
            "Buyer and seller appear before the Land Control Board and obtain consent to transfer.",
        ),
        (
            "valuation",
            "Government Valuation Done",
            "Government Valuation Report",
            "A government valuer assesses the property for stamp duty purposes.",
        ),
        (
            "stamp_duty",
            "Stamp Duty Paid",
            "Stamp Duty Receipt",
            "Buyer pays stamp duty via KRA iTax/eCitizen after valuation.",
        ),
        (
            "completion_docs",
            "Completion Documents Received",
            "Completion document bundle",
            "Seller advocate releases title, transfer forms, clearances, IDs, and any spousal consent.",
        ),
        (
            "registration",
            "Transfer Registered",
            "New search result / title evidence",
            "Land Registry records the buyer as proprietor and a fresh registry proof is issued.",
        ),
    ]

    LEASE_CLOSING_STEPS = [
        (
            "offer",
            "Lease Offer Confirmed",
            "Signed lease offer / intent",
            "The lease intent and key commercial terms are confirmed between both sides.",
        ),
        (
            "agreement",
            "Lease Agreement Signed",
            "Signed Lease Agreement",
            "Both parties sign the lease agreement with their agreed dates and obligations.",
        ),
        (
            "payment_security",
            "Deposit / Rent Security Confirmed",
            "Payment confirmation",
            "The agreed lease deposit or first rent commitment is recorded by AgriPlot.",
        ),
        (
            "handover",
            "Possession / Handover Completed",
            "Handover note or possession acknowledgment",
            "The lessee receives possession and the lease is treated as active on the platform.",
        ),
    ]

    def __str__(self):
        return f"{self.internal_reference} - {self.title}"

    def clean(self):
        mobile_methods = {
            self.Method.MPESA_STK,
            self.Method.MPESA_PAYBILL,
            self.Method.AIRTEL_MONEY,
        }
        if self.method in mobile_methods and not self.phone_number:
            raise ValidationError(
                {"phone_number": "A phone number is required for mobile money payments."}
            )
        if self.transaction_type == self.TransactionType.LEASE:
            if not self.lease_start_date or not self.lease_end_date:
                raise ValidationError(
                    {
                        "lease_start_date": "Lease start date is required for lease checkout.",
                        "lease_end_date": "Lease end date is required for lease checkout.",
                    }
                )
            if self.lease_end_date <= self.lease_start_date:
                raise ValidationError(
                    {"lease_end_date": "Lease end date must be after the lease start date."}
                )
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.lease_start_date or self.lease_end_date:
                raise ValidationError("Purchase transactions should not include lease dates.")
        if self.plot:
            if self.transaction_type == self.TransactionType.PURCHASE and self.plot.market_status == "sold":
                raise ValidationError("This plot has already been sold.")
            if self.transaction_type == self.TransactionType.LEASE:
                if self.plot.market_status == "sold":
                    raise ValidationError("This plot has already been sold and cannot be leased.")
                if self.plot.listing_type not in {"lease", "both"}:
                    raise ValidationError("This plot is not listed for lease.")
                if self.plot.has_active_lease and self.lease_start_date and self.lease_end_date:
                    overlaps = not (
                        self.lease_end_date < self.plot.lease_start_date
                        or self.lease_start_date > self.plot.lease_end_date
                    )
                    if overlaps:
                        raise ValidationError(
                            (
                                "This land is already leased from "
                                f"{self.plot.lease_start_date:%b %d, %Y} to "
                                f"{self.plot.lease_end_date:%b %d, %Y}."
                            )
                        )

    def save(self, *args, **kwargs):
        if not self.internal_reference:
            self.internal_reference = self.generate_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_reference():
        return f"AGP-{uuid.uuid4().hex[:8].upper()}"

    @property
    def status_badge(self):
        mapping = {
            self.Status.DRAFT: "secondary",
            self.Status.PENDING: "warning",
            self.Status.PAID: "success",
            self.Status.IN_ESCROW: "primary",
            self.Status.PARTIALLY_RELEASED: "info",
            self.Status.RELEASED: "success",
            self.Status.REFUNDED: "dark",
            self.Status.DISPUTED: "danger",
            self.Status.CANCELLED: "secondary",
            self.Status.FAILED: "danger",
        }
        return mapping.get(self.status, "secondary")

    @property
    def counterparty_label(self):
        if self.seller:
            return self.seller.get_full_name() or self.seller.username
        if self.plot and self.plot.landowner:
            return self.plot.landowner.user.get_full_name() or self.plot.landowner.user.username
        if self.plot and self.plot.agent:
            return self.plot.agent.user.get_full_name() or self.plot.agent.user.username
        return "Unassigned seller"

    @property
    def progress_value(self):
        progress = {
            self.Status.DRAFT: 10,
            self.Status.PENDING: 25,
            self.Status.PAID: 45,
            self.Status.IN_ESCROW: 65,
            self.Status.PARTIALLY_RELEASED: 82,
            self.Status.RELEASED: 100,
            self.Status.REFUNDED: 100,
            self.Status.DISPUTED: 55,
            self.Status.CANCELLED: 100,
            self.Status.FAILED: 100,
        }
        return progress.get(self.status, 0)

    @classmethod
    def closing_step_templates(cls, transaction_type):
        if transaction_type == cls.TransactionType.PURCHASE:
            return cls.PURCHASE_CLOSING_STEPS
        if transaction_type == cls.TransactionType.LEASE:
            return cls.LEASE_CLOSING_STEPS
        return []

    def add_event(self, event_type, message, actor=None):
        return PaymentEvent.objects.create(
            payment=self,
            event_type=event_type,
            actor=actor,
            message=message,
        )

    def _release_blocking_reason(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            required_codes = {
                "agreement",
                "lcb_consent",
                "valuation",
                "stamp_duty",
                "completion_docs",
            }
            completed_codes = set(
                self.closing_steps.filter(status=PaymentClosingStep.Status.COMPLETED).values_list("code", flat=True)
            )
            missing = required_codes - completed_codes
            if missing:
                titles = list(
                    self.closing_steps.filter(code__in=missing).order_by("sequence").values_list("title", flat=True)
                )
                blocking_steps = ", ".join(titles) if titles else ", ".join(sorted(missing))
                return (
                    "Purchase funds cannot be released yet. Complete these legal steps first: "
                    f"{blocking_steps}."
                )
        return ""

    def apply_transition(self, action, actor=None):
        transition_map = {
            "submit": (self.Status.PENDING, "Payment request sent to the selected payment method."),
            "mark_paid": (self.Status.PAID, "Payment confirmed and buyer commitment recorded."),
            "move_escrow": (self.Status.IN_ESCROW, "Funds moved into escrow while seller milestones are fulfilled."),
            "partial_release": (
                self.Status.PARTIALLY_RELEASED,
                "A partial payout was released while retaining balance for remaining milestones.",
            ),
            "release": (self.Status.RELEASED, "Funds released to the seller after milestone approval."),
            "refund": (self.Status.REFUNDED, "Buyer refund approved and recorded."),
            "dispute": (self.Status.DISPUTED, "Payment moved into dispute review."),
            "cancel": (self.Status.CANCELLED, "Payment request cancelled."),
            "fail": (self.Status.FAILED, "Payment failed before settlement."),
        }
        if action not in transition_map:
            raise ValidationError(f"Unsupported payment action: {action}")
        if action not in self.allowed_transitions:
            raise ValidationError(
                f"Action '{action}' is not allowed while payment is in '{self.status}'."
            )
        if action == "release":
            blocking_reason = self._release_blocking_reason()
            if blocking_reason:
                raise ValidationError(blocking_reason)

        new_status, message = transition_map[action]
        self.status = new_status
        now = timezone.now()

        if action == "mark_paid" and not self.paid_at:
            self.paid_at = now
        if action in {"release", "partial_release"}:
            self.released_at = now

        self.save(update_fields=["status", "paid_at", "released_at", "updated_at"])
        self.sync_plot_market_state()
        self.add_event(action, message, actor=actor)

    @property
    def allowed_transitions(self):
        return self.TRANSITION_RULES.get(self.status, set())

    def ensure_closing_steps(self):
        templates = self.closing_step_templates(self.transaction_type)
        if not templates:
            return

        existing_codes = set(self.closing_steps.values_list("code", flat=True))
        to_create = []
        for sequence, (code, title, document_name, guidance) in enumerate(templates, start=1):
            if code in existing_codes:
                continue
            to_create.append(
                PaymentClosingStep(
                    payment=self,
                    code=code,
                    title=title,
                    sequence=sequence,
                    document_name=document_name,
                    guidance=guidance,
                )
            )
        if to_create:
            PaymentClosingStep.objects.bulk_create(to_create)

    @property
    def closing_progress_value(self):
        total = self.closing_steps.count()
        if not total:
            return 0
        completed = self.closing_steps.filter(status=PaymentClosingStep.Status.COMPLETED).count()
        return int((completed / total) * 100)

    @property
    def closing_stage_summary(self):
        if self.transaction_type in {self.TransactionType.PURCHASE, self.TransactionType.LEASE} and not self.closing_steps.exists():
            return "Closing tracker is being prepared."
        next_step = self.closing_steps.exclude(status=PaymentClosingStep.Status.COMPLETED).order_by("sequence").first()
        if next_step:
            return f"Next legal step: {next_step.title}"
        if self.transaction_type == self.TransactionType.PURCHASE:
            return "All legal transfer steps are complete. The sale can now be treated as fully registered."
        if self.transaction_type == self.TransactionType.LEASE:
            return "All lease handover steps are complete."
        return "No closing tracker is required for this payment."

    @property
    def transfer_status_label(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.purchase_registration_complete:
                return "Legally transferred"
            if self.status == self.Status.RELEASED:
                return "Awaiting registry transfer"
            if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                return "Reserved pending closing"
            if self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                return "Transfer stopped"
            return "Awaiting buyer payment"
        if self.transaction_type == self.TransactionType.LEASE:
            if self.status == self.Status.RELEASED:
                return "Lease active"
            if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                return "Lease being secured"
            if self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                return "Lease stopped"
            return "Awaiting tenant payment"
        return self.get_status_display()

    @property
    def transfer_status_detail(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.purchase_registration_complete:
                return "The registry transfer step is complete and the plot can now be treated as sold."
            if self.status == self.Status.RELEASED:
                return "Funds are released, but the plot stays reserved until the final registration step is completed."
            if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                return "Buyer funds have been committed, so the plot is reserved while legal closing continues."
            if self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                return "This purchase did not complete, so the plot can return to the market."
            return "No reservation is in place until the buyer successfully pays."
        if self.transaction_type == self.TransactionType.LEASE:
            if self.status == self.Status.RELEASED:
                return "The lease is active on AgriPlot for the approved period."
            if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                return "Lease payment is underway and the plot is being held for this lease flow."
            if self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                return "This lease flow did not complete, so the hold can be removed."
            return "No lease hold is active until the payment succeeds."
        return ""

    @property
    def purchase_registration_complete(self):
        if self.transaction_type != self.TransactionType.PURCHASE:
            return False
        return self.closing_steps.filter(
            code="registration",
            status=PaymentClosingStep.Status.COMPLETED,
        ).exists()

    @property
    def next_closing_step(self):
        return self.closing_steps.exclude(
            status=PaymentClosingStep.Status.COMPLETED
        ).order_by("sequence").first()

    @property
    def buyer_next_step_summary(self):
        if self.transaction_type not in {self.TransactionType.PURCHASE, self.TransactionType.LEASE}:
            return "Follow the payment milestones in this workspace."
        next_step = self.next_closing_step
        if next_step:
            return f"Next step: {next_step.title}"
        if self.transaction_type == self.TransactionType.PURCHASE:
            return "All legal transfer steps are complete."
        return "All lease handover steps are complete."

    @property
    def buyer_next_step_instruction(self):
        if self.transaction_type not in {self.TransactionType.PURCHASE, self.TransactionType.LEASE}:
            return "Use the payment timeline below for the next action."
        next_step = self.next_closing_step
        if not next_step:
            if self.transaction_type == self.TransactionType.PURCHASE:
                return "Keep the stamped transfer documents and final search result for your records."
            return "Keep the signed lease documents and handover record for your records."
        return (
            f"Go to the transaction tracker below and work on '{next_step.title}'. "
            f"{next_step.buyer_instruction}"
        )

    def sync_plot_market_state(self):
        if not self.plot:
            return
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.status == self.Status.RELEASED:
                self.plot.market_status = "sold" if self.purchase_registration_complete else "reserved"
                self.plot.lease_start_date = None
                self.plot.lease_end_date = None
                self.plot.availability_notes = (
                    f"Marked sold via payment {self.internal_reference} after registry transfer."
                    if self.purchase_registration_complete
                    else (
                        f"Reserved for legal completion via payment {self.internal_reference}. "
                        "Awaiting the statutory closing checklist before final transfer."
                    )
                )
            elif self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                self.plot.market_status = "reserved"
                self.plot.lease_start_date = None
                self.plot.lease_end_date = None
                self.plot.availability_notes = (
                    f"Reserved under active purchase transaction {self.internal_reference}."
                )
            elif self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                self.plot.market_status = "available"
                self.plot.lease_start_date = None
                self.plot.lease_end_date = None
                self.plot.availability_notes = (
                    f"Purchase transaction {self.internal_reference} closed without transfer."
                )
            else:
                return
            self.plot.save(
                update_fields=[
                    "market_status",
                    "lease_start_date",
                    "lease_end_date",
                    "availability_notes",
                ]
            )
            return

        if self.status == self.Status.RELEASED and self.transaction_type == self.TransactionType.LEASE:
            self.plot.market_status = "leased"
            self.plot.lease_start_date = self.lease_start_date
            self.plot.lease_end_date = self.lease_end_date
            self.plot.availability_notes = (
                f"Lease recorded via payment {self.internal_reference}."
            )
            self.plot.save(
                update_fields=[
                    "market_status",
                    "lease_start_date",
                    "lease_end_date",
                    "availability_notes",
                ]
            )


class PaymentMilestone(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        RELEASED = "released", "Released"
        REFUNDED = "refunded", "Refunded"
        BLOCKED = "blocked", "Blocked"

    payment = models.ForeignKey(
        PaymentRequest, on_delete=models.CASCADE, related_name="milestones"
    )
    title = models.CharField(max_length=180)
    sequence = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    evidence_notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence", "created_at"]
        unique_together = [("payment", "sequence")]

    def __str__(self):
        return f"{self.payment.internal_reference} - {self.title}"


class PaymentDispute(models.Model):
    class Reason(models.TextChoices):
        SELLER_NO_SHOW = "seller_no_show", "Seller No-show"
        MISSING_DOCUMENTS = "missing_documents", "Missing Documents"
        PAYMENT_NOT_RECOGNIZED = "payment_not_recognized", "Payment Not Recognized"
        FRAUD_SIGNAL = "fraud_signal", "Fraud Signal"
        REFUND_REQUEST = "refund_request", "Refund Request"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        UNDER_REVIEW = "under_review", "Under Review"
        RESOLVED = "resolved", "Resolved"
        REJECTED = "rejected", "Rejected"

    payment = models.OneToOneField(
        PaymentRequest, on_delete=models.CASCADE, related_name="dispute"
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_disputes_opened",
    )
    reason = models.CharField(max_length=40, choices=Reason.choices)
    details = models.TextField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_disputes_resolved",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Dispute for {self.payment.internal_reference}"


class PaymentEvent(models.Model):
    payment = models.ForeignKey(
        PaymentRequest, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=40)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_events",
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.payment.internal_reference} - {self.event_type}"


class PaymentClosingStep(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        BLOCKED = "blocked", "Blocked"

    payment = models.ForeignKey(
        PaymentRequest, on_delete=models.CASCADE, related_name="closing_steps"
    )
    code = models.CharField(max_length=40)
    title = models.CharField(max_length=180)
    sequence = models.PositiveIntegerField(default=1)
    document_name = models.CharField(max_length=180, blank=True)
    guidance = models.TextField(blank=True)
    document = models.FileField(upload_to="payments/closing_docs/", blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_closing_steps_completed",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sequence", "created_at"]
        unique_together = [("payment", "code")]

    def __str__(self):
        return f"{self.payment.internal_reference} - {self.title}"

    @property
    def responsible_party_label(self):
        purchase_map = {
            "offer": "Buyer / Buyer Advocate",
            "agreement": "Seller Advocate",
            "lcb_consent": "Buyer + Seller",
            "valuation": "Government Valuer / Buyer",
            "stamp_duty": "Buyer",
            "completion_docs": "Seller / Seller Advocate",
            "registration": "Buyer Advocate",
        }
        lease_map = {
            "offer": "Buyer / Tenant",
            "agreement": "Buyer + Seller",
            "payment_security": "Buyer / Tenant",
            "handover": "Seller / Landowner",
        }
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return purchase_map.get(self.code, "Operations")
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return lease_map.get(self.code, "Operations")
        return "Operations"

    @property
    def action_summary(self):
        purchase_map = {
            "offer": {
                "headline": "Prepare the formal offer to purchase.",
                "where": "Work with your advocate and send the offer to the seller's advocate.",
                "document": "Offer to Purchase / Letter of Intent",
                "platform_role": "AgriPlot keeps this step visible in your tracker and lets you upload proof once it is issued.",
                "cta_label": "Open Offer Step",
                "support_label": "Need help? Share the expected terms with your advocate before they draft the offer.",
            },
            "agreement": {
                "headline": "Review and sign the sale agreement.",
                "where": "Meet or coordinate with your advocate once the seller's advocate shares the agreement.",
                "document": "Signed Sale Agreement",
                "platform_role": "AgriPlot records progress and supporting documents for the deal.",
                "cta_label": "Review Agreement Step",
                "support_label": "Confirm the deposit terms, completion period, and land reference before signing.",
            },
            "lcb_consent": {
                "headline": "Prepare for the Land Control Board meeting.",
                "where": "Coordinate with the seller and appear at the local Land Control Board with the required IDs.",
                "document": "LCB Consent Letter",
                "platform_role": "AgriPlot tracks the consent milestone so the deal does not advance too early.",
                "cta_label": "Track LCB Consent",
                "support_label": "Do not release the full purchase amount before this consent is granted.",
            },
            "valuation": {
                "headline": "Follow up on government valuation.",
                "where": "Confirm the valuer's site visit and keep the valuation reference handy.",
                "document": "Government Valuation Report",
                "platform_role": "AgriPlot keeps this dependency visible before stamp duty and completion.",
                "cta_label": "Track Valuation",
                "support_label": "The stamp duty amount will depend on the government valuation, not just your agreed price.",
            },
            "stamp_duty": {
                "headline": "Pay stamp duty and keep the receipt.",
                "where": "Use the KRA iTax / eCitizen flow once valuation is complete.",
                "document": "Stamp Duty Receipt",
                "platform_role": "AgriPlot stores the receipt in the transaction trail.",
                "cta_label": "Upload Stamp Duty Proof",
                "support_label": "Complete this only after valuation is done so the correct duty is paid.",
            },
            "completion_docs": {
                "headline": "Confirm the seller's completion documents.",
                "where": "Your advocate should review the title, transfer forms, clearances, IDs, and any required consents.",
                "document": "Completion Document Pack",
                "platform_role": "AgriPlot keeps both sides aligned on what has been handed over.",
                "cta_label": "Check Completion Documents",
                "support_label": "Do not release the final balance until the completion documents are fully confirmed.",
            },
            "registration": {
                "headline": "Lodge the transfer for registration.",
                "where": "Your advocate should submit the transfer through Ardhisasa or the registry and share proof here.",
                "document": "New Search Result / Registry Proof",
                "platform_role": "AgriPlot only marks the plot sold after this final registration evidence is completed.",
                "cta_label": "Track Registration",
                "support_label": "This is the step that turns a reserved deal into a legally completed transfer on the platform.",
            },
        }
        lease_map = {
            "offer": {
                "headline": "Confirm the lease terms you want.",
                "where": "Formally communicate the lease period, use, and expectations to the landowner or agent.",
                "document": "Lease Offer / Intent",
                "platform_role": "AgriPlot keeps the lease intent visible before the agreement is signed.",
                "cta_label": "Open Lease Offer Step",
                "support_label": "Be clear about the lease dates and intended use before moving to agreement drafting.",
            },
            "agreement": {
                "headline": "Review and sign the lease agreement.",
                "where": "Go through the lease terms carefully with the other side before signing.",
                "document": "Signed Lease Agreement",
                "platform_role": "AgriPlot tracks the signed agreement as the lease moves toward handover.",
                "cta_label": "Review Lease Agreement",
                "support_label": "Check renewal terms, payment schedule, access rights, and exit conditions.",
            },
            "payment_security": {
                "headline": "Complete the lease payment commitment.",
                "where": "Finish the agreed deposit or rent security payment and keep proof of payment.",
                "document": "Lease Deposit / Rent Proof",
                "platform_role": "AgriPlot ties the payment proof to the lease tracker.",
                "cta_label": "Add Lease Payment Proof",
                "support_label": "Keep your payment proof ready before moving to land handover.",
            },
            "handover": {
                "headline": "Prepare for possession handover.",
                "where": "Meet the landowner or agent, confirm boundaries, and document possession details.",
                "document": "Handover Note / Signed Possession Record",
                "platform_role": "AgriPlot records the handover milestone before the lease is treated as active.",
                "cta_label": "Track Handover",
                "support_label": "Confirm the access date, site condition, and any standing obligations before occupying the land.",
            },
        }
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return purchase_map.get(self.code, {})
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return lease_map.get(self.code, {})
        return {}

    @property
    def action_headline(self):
        return self.action_summary.get("headline", self.title)

    @property
    def action_where(self):
        return self.action_summary.get("where", self.buyer_instruction)

    @property
    def action_document_label(self):
        return self.action_summary.get("document") or self.document_name or "Supporting document"

    @property
    def action_platform_role(self):
        return self.action_summary.get("platform_role", "AgriPlot keeps this step visible inside the transaction tracker.")

    @property
    def action_cta_label(self):
        return self.action_summary.get("cta_label", "Open step")

    @property
    def action_support_label(self):
        return self.action_summary.get("support_label", "Keep your documents and notes organised as this step progresses.")

    @property
    def buyer_instruction(self):
        purchase_map = {
            "offer": "Ask your advocate to prepare and send the Offer to Purchase to the seller's advocate.",
            "agreement": "Review the sale agreement with your advocate and be ready to sign once the seller's advocate shares it.",
            "lcb_consent": "Coordinate with the seller for the Land Control Board meeting and carry your ID documents.",
            "valuation": "Follow up on the government valuation visit so stamp duty can be assessed correctly.",
            "stamp_duty": "Pay the stamp duty through KRA/eCitizen and upload the receipt here.",
            "completion_docs": "Wait for the seller's advocate to hand over the completion documents, then confirm they are complete.",
            "registration": "Ask your advocate to lodge the transfer at the registry or Ardhisasa and upload the final proof.",
        }
        lease_map = {
            "offer": "Confirm the lease terms you want and formally signal that you want to proceed.",
            "agreement": "Review the lease agreement carefully and sign once the terms are agreed.",
            "payment_security": "Complete the agreed lease deposit or rent commitment and keep proof of payment.",
            "handover": "Arrange the handover meeting and confirm possession details before occupying the land.",
        }
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return purchase_map.get(self.code, "Open this step and follow the guidance provided.")
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return lease_map.get(self.code, "Open this step and follow the guidance provided.")
        return "Open this step and follow the guidance provided."

    def set_status(self, status, actor=None, notes=""):
        self.status = status
        if notes:
            self.notes = notes
        if status == self.Status.COMPLETED:
            self.completed_at = timezone.now()
            if actor:
                self.completed_by = actor
        else:
            self.completed_at = None
            self.completed_by = None
        self.save(update_fields=["status", "notes", "completed_at", "completed_by", "updated_at"])
        self.payment.sync_plot_market_state()
