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

    def add_event(self, event_type, message, actor=None):
        return PaymentEvent.objects.create(
            payment=self,
            event_type=event_type,
            actor=actor,
            message=message,
        )

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

    def sync_plot_market_state(self):
        if not self.plot:
            return
        if self.status == self.Status.RELEASED:
            if self.transaction_type == self.TransactionType.PURCHASE:
                self.plot.market_status = "sold"
                self.plot.lease_start_date = None
                self.plot.lease_end_date = None
                self.plot.availability_notes = (
                    f"Marked sold via payment {self.internal_reference}."
                )
                self.plot.save(
                    update_fields=[
                        "market_status",
                        "lease_start_date",
                        "lease_end_date",
                        "availability_notes",
                    ]
                )
            elif self.transaction_type == self.TransactionType.LEASE:
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
