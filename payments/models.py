import uuid
from datetime import datetime, timedelta

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
        COMMITMENT_FEE = "commitment_fee", "Commitment / Verification Fee"
        VIEWING_FEE = "viewing_fee", "Viewing Fee"
        RESERVATION_DEPOSIT = "reservation_deposit", "Reservation Deposit"
        AGREEMENT_DEPOSIT = "agreement_deposit", "Agreement Deposit"
        VERIFICATION_PACKAGE = "verification_package", "Verification Package"
        ESCROW_DEPOSIT = "escrow_deposit", "Escrow Deposit"
        STAMP_DUTY = "stamp_duty", "Stamp Duty"
        COMPLETION_BALANCE = "completion_balance", "Completion Balance"
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
            "due_diligence",
            "Search & Survey Verified",
            "Official search and survey pack",
            "After the buyer pays the commitment fee, AgriPlot locks the plot and delivers the search and survey documents for review.",
        ),
        (
            "agreement",
            "Sale Agreement Signed",
            "Signed Sale Agreement",
            "Seller advocate drafts the agreement, both parties sign, and the 10% deposit is secured under the legal framework.",
        ),
        (
            "lcb_consent",
            "LCB Consent Obtained",
            "LCB / spousal consent pack",
            "Buyer and seller secure the Land Control Board consent and any required spousal consent before completion can proceed.",
        ),
        (
            "stamp_duty",
            "Stamp Duty Paid",
            "Valuation report and stamp duty receipt",
            "Government valuation is completed and the buyer clears stamp duty through KRA iTax/eCitizen.",
        ),
        (
            "completion_docs",
            "Completion Docs Exchanged",
            "Completion document bundle",
            "The buyer clears the remaining balance and the completion documents are exchanged under the lawyers' supervision.",
        ),
        (
            "registration",
            "Title Registered",
            "New search result / title evidence",
            "Land Registry records the buyer as proprietor, issues the registry proof, and the transaction is treated as complete.",
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

    @property
    def workflow_root_id(self):
        return (self.metadata or {}).get("workflow_root_id")

    @property
    def workflow_anchor_payment(self):
        root_id = self.workflow_root_id
        if not root_id or root_id == self.pk:
            return self
        try:
            return PaymentRequest.objects.get(pk=root_id)
        except PaymentRequest.DoesNotExist:
            return self

    @property
    def workflow_related_payments(self):
        anchor = self.workflow_anchor_payment
        candidates = PaymentRequest.objects.filter(
            buyer=anchor.buyer,
            plot=anchor.plot,
            transaction_type=anchor.transaction_type,
        ).order_by("created_at")
        related = []
        for candidate in candidates:
            candidate_root_id = (candidate.metadata or {}).get("workflow_root_id")
            if candidate.pk == anchor.pk or candidate_root_id == anchor.pk:
                related.append(candidate)
        return related

    @property
    def workflow_total_requested_amount(self):
        return sum((payment.amount for payment in self.workflow_related_payments), start=0)

    @property
    def workflow_total_paid_amount(self):
        paid_statuses = {
            self.Status.PAID,
            self.Status.IN_ESCROW,
            self.Status.PARTIALLY_RELEASED,
            self.Status.RELEASED,
        }
        return sum(
            (payment.amount for payment in self.workflow_related_payments if payment.status in paid_statuses),
            start=0,
        )

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
        anchor = self.workflow_anchor_payment
        if anchor.pk != self.pk:
            return anchor.ensure_closing_steps()
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
    def current_assigned_step(self):
        return self.next_closing_step

    @property
    def current_assigned_party(self):
        step = self.current_assigned_step
        return step.responsible_party_label if step else "Completed"

    @property
    def current_assignment_message(self):
        step = self.current_assigned_step
        if not step:
            return "All transaction steps are complete."
        return f"{step.display_title} is now assigned to {step.responsible_party_label}."

    @property
    def buyer_journey_steps(self):
        if self.transaction_type not in {self.TransactionType.PURCHASE, self.TransactionType.LEASE}:
            return []

        is_purchase = self.transaction_type == self.TransactionType.PURCHASE
        is_agricultural = bool(self.plot and self.plot.land_type == "agricultural")

        def grouped_status(codes):
            steps = list(self.closing_steps.filter(code__in=codes))
            if not steps:
                return "pending"
            statuses = {step.status for step in steps}
            if all(status == PaymentClosingStep.Status.COMPLETED for status in statuses):
                return "completed"
            if PaymentClosingStep.Status.BLOCKED in statuses:
                return "blocked"
            if PaymentClosingStep.Status.IN_PROGRESS in statuses or PaymentClosingStep.Status.COMPLETED in statuses:
                return "in_progress"
            return "pending"

        if is_purchase:
            consent_title = (
                "LCB Consent Obtained"
                if is_agricultural
                else "Transfer Consents Obtained"
            )
            consent_summary = (
                "LCB consent and any required spousal approvals are secured before the transfer can proceed."
                if is_agricultural
                else "Required transfer consents, rates/rent clearances, and other seller approvals are secured."
            )
            return [
                {
                    "status": grouped_status(["due_diligence"]),
                    "title": "Search & Survey Verified",
                    "summary": (
                        "The commitment fee locks the plot and AgriPlot delivers the official search plus survey and soil evidence for review."
                        if is_agricultural
                        else "The commitment fee locks the plot and AgriPlot delivers the official search plus verified site documents for review."
                    ),
                },
                {
                    "title": "Sale Agreement Signed",
                    "status": grouped_status(["agreement"]),
                    "summary": "The agreement is signed and the 10% deposit is secured under the legal framework.",
                },
                {
                    "title": consent_title,
                    "status": grouped_status(["lcb_consent"]),
                    "summary": consent_summary,
                },
                {
                    "title": "Government Valuation & Stamp Duty",
                    "status": grouped_status(["stamp_duty"]),
                    "summary": "Government valuation is completed and stamp duty is paid through the official channels.",
                },
                {
                    "title": "Completion Docs Exchanged",
                    "status": grouped_status(["completion_docs"]),
                    "summary": "The remaining balance is cleared and the completion documents are exchanged safely.",
                },
                {
                    "title": "Title Registered",
                    "status": grouped_status(["registration"]),
                    "summary": "A fresh registry result confirms the buyer as the new owner and the plot can finally flip to sold.",
                },
            ]

        return [
            {
                "status": grouped_status(["offer"]),
                "title": "Lease Offer Confirmed",
                "summary": "Confirm the lease intent, dates, and intended use before the agreement is drafted.",
            },
            {
                "title": "Lease Agreement",
                "status": grouped_status(["agreement"]),
                "summary": "Agree the lease terms and sign the lease agreement.",
            },
            {
                "title": "Payment & Security",
                "status": grouped_status(["payment_security"]),
                "summary": "Confirm the agreed lease deposit or rent commitment.",
            },
            {
                "title": "Handover & Activation",
                "status": grouped_status(["handover"]),
                "summary": "Record possession, handover details, and activate the lease on AgriPlot.",
            },
        ]

    @property
    def buyer_journey_title(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.plot and self.plot.land_type == "agricultural":
                return "Simple agricultural purchase journey"
            return "Simple purchase journey"
        if self.transaction_type == self.TransactionType.LEASE:
            if self.plot and self.plot.land_type == "agricultural":
                return "Simple agricultural lease journey"
            return "Simple lease journey"
        return "Buyer journey"

    @property
    def buyer_journey_intro(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            return "A plain-language view of the real path from checkout to title transfer. The detailed legal tracker stays below."
        if self.transaction_type == self.TransactionType.LEASE:
            return "A plain-language view of the lease journey from checkout to handover. The detailed legal tracker stays below."
        return "A simple view of the transaction journey."

    @property
    def buyer_journey_progress_value(self):
        steps = self.buyer_journey_steps
        if not steps:
            return 0
        completed = sum(1 for step in steps if step["status"] == "completed")
        return int((completed / len(steps)) * 100)

    @property
    def due_diligence_lock_expires_at(self):
        if self.transaction_type != self.TransactionType.PURCHASE:
            return None
        lock_value = (self.metadata or {}).get("due_diligence_lock_expires_at")
        if lock_value:
            parsed = datetime.fromisoformat(lock_value)
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed
        if self.paid_at:
            return self.paid_at + timedelta(days=7)
        return None

    @property
    def due_diligence_lock_message(self):
        lock_expires_at = self.due_diligence_lock_expires_at
        if not lock_expires_at:
            return ""
        return (
            "This plot is under the due-diligence lock and is being held for this buyer "
            f"until {timezone.localtime(lock_expires_at):%b %d, %Y %I:%M %p}."
        )

    @property
    def due_diligence_documents(self):
        plot = self.plot
        if not plot:
            return []
        documents = []
        if getattr(plot, "official_search", None):
            documents.append(
                {
                    "title": "Official Search",
                    "note": "Registry search showing the current ownership and registered interests.",
                    "url": plot.official_search.url,
                }
            )
        if getattr(plot, "survey_map", None):
            documents.append(
                {
                    "title": "Survey / Beacon Report",
                    "note": "Survey map or beacon evidence used during the verification stage.",
                    "url": plot.survey_map.url,
                }
            )
        if getattr(plot, "soil_report", None):
            documents.append(
                {
                    "title": "Soil / Land Use Report",
                    "note": "Extension or soil verification evidence for farming-fit review.",
                    "url": plot.soil_report.url,
                }
            )
        if getattr(plot, "title_deed", None):
            documents.append(
                {
                    "title": "Title Deed Copy",
                    "note": "Title document supplied during the verification process.",
                    "url": plot.title_deed.url,
                }
            )
        return documents

    @property
    def advocate_details(self):
        metadata = self.metadata or {}
        return {
            "buyer_name": metadata.get("buyer_advocate_name", ""),
            "buyer_phone": metadata.get("buyer_advocate_phone", ""),
            "seller_name": metadata.get("seller_advocate_name", ""),
            "seller_phone": metadata.get("seller_advocate_phone", ""),
        }

    @property
    def dashboard_process_steps(self):
        if self.transaction_type != self.TransactionType.PURCHASE:
            steps = [
                {
                    "sequence": "01",
                    "title": "Confirm Lease Need",
                    "caption": "Choose the plot and confirm the lease purpose.",
                    "icon": "01",
                    "status": "completed" if self.plot_id else "pending",
                },
                {
                    "sequence": "02",
                    "title": "Connect with AgriPlot",
                    "caption": "Buyer and seller open the guided lease workspace.",
                    "icon": "02",
                    "status": "completed" if self.seller_id else "pending",
                },
                {
                    "sequence": "03",
                    "title": "Visit the Land",
                    "caption": "Confirm access, use, and site condition before signing.",
                    "icon": "03",
                    "status": "completed" if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED, self.Status.RELEASED} else "pending",
                },
                {
                    "sequence": "04",
                    "title": "Pay the Commitment",
                    "caption": "Complete the M-Pesa commitment that opens the lease tracker.",
                    "icon": "04",
                    "status": "completed" if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED, self.Status.RELEASED} else "pending",
                },
                {
                    "sequence": "05",
                    "title": "Review the Lease Pack",
                    "caption": "Check the verified documents and lease details in AgriPlot.",
                    "icon": "05",
                    "status": self._dashboard_status_for_codes(["offer"]),
                },
                {
                    "sequence": "06",
                    "title": "Sign the Lease Agreement",
                    "caption": "Upload the executed lease agreement and supporting proof.",
                    "icon": "06",
                    "status": self._dashboard_status_for_codes(["agreement"]),
                },
                {
                    "sequence": "07",
                    "title": "Clear the Lease Security",
                    "caption": "Complete the rent security or deposit commitment.",
                    "icon": "07",
                    "status": self._dashboard_status_for_codes(["payment_security"]),
                },
                {
                    "sequence": "08",
                    "title": "Get Your Handover",
                    "caption": "Record possession, boundaries, and activation of the lease.",
                    "icon": "08",
                    "status": self._dashboard_status_for_codes(["handover"]),
                },
                {
                    "sequence": "09",
                    "title": "Use the Land",
                    "caption": "The lease is active and the property is ready for use.",
                    "icon": "09",
                    "status": "completed" if self.status == self.Status.RELEASED else "pending",
                },
            ]
            return self._normalize_dashboard_steps(steps)

        payment_started = self.status in {
            self.Status.PENDING,
            self.Status.PAID,
            self.Status.IN_ESCROW,
            self.Status.PARTIALLY_RELEASED,
            self.Status.RELEASED,
            self.Status.DISPUTED,
        }
        commitment_paid = self.status in {
            self.Status.PAID,
            self.Status.IN_ESCROW,
            self.Status.PARTIALLY_RELEASED,
            self.Status.RELEASED,
        }
        due_diligence_status = self._dashboard_status_for_codes(["due_diligence"])
        agreement_status = self._dashboard_status_for_codes(["agreement"])
        completion_run_status = self._dashboard_status_for_codes(
            ["lcb_consent", "stamp_duty", "completion_docs"]
        )
        registration_status = self._dashboard_status_for_codes(["registration"])

        steps = [
            {
                "sequence": "01",
                "title": "Identify Your Plot",
                "caption": "Choose the verified plot that matches your farming or investment goals.",
                "icon": "01",
                "status": "completed" if self.plot_id else "pending",
            },
            {
                "sequence": "02",
                "title": "Connect with AgriPlot",
                "caption": "Open the legal escrow workflow with the seller, agent, and support team before any commitment fee is paid.",
                "icon": "02",
                "status": "completed" if payment_started else "pending",
            },
            {
                "sequence": "03",
                "title": "Book Site Visit",
                "caption": "Visit the land and confirm the physical reality before committing fully.",
                "icon": "03",
                "status": "completed" if due_diligence_status in {"completed", "current"} else "pending",
            },
            {
                "sequence": "04",
                "title": "Deposit Booking Fee",
                "caption": "Pay the commitment fee so the plot is locked and the due-diligence pack is released.",
                "icon": "04",
                "status": "completed" if commitment_paid else ("current" if payment_started else "pending"),
            },
            {
                "sequence": "05",
                "title": "Do Your Due Diligence",
                "caption": "Review the official search, beacon report, and verification records in your dashboard.",
                "icon": "05",
                "status": due_diligence_status,
            },
            {
                "sequence": "06",
                "title": "Sign Agreement for Sale",
                "caption": "Seller advocate uploads the agreement and both sides secure the 10% deposit arrangement.",
                "icon": "06",
                "status": agreement_status,
            },
            {
                "sequence": "07",
                "title": "Clear the Remaining Balance",
                "caption": "Work through the approvals, stamp duty, and completion exchange so the final balance and handover happen in order.",
                "icon": "07",
                "status": completion_run_status,
            },
            {
                "sequence": "08",
                "title": "Get Your Title Deed",
                "caption": "Registration is completed and the fresh registry proof shows you as the new owner.",
                "icon": "08",
                "status": registration_status,
            },
            {
                "sequence": "09",
                "title": "Develop Your Property",
                "caption": "The title is in your name and the land is ready for development or productive use.",
                "icon": "09",
                "status": "completed" if self.purchase_registration_complete else "pending",
            },
        ]
        return self._normalize_dashboard_steps(steps)

    def _normalize_dashboard_steps(self, steps):
        normalized = []
        current_found = False
        for index, step in enumerate(steps):
            step_copy = dict(step)
            step_copy["state_label"] = {
                "completed": "Completed",
                "current": "Current",
                "blocked": "Blocked",
                "pending": "Pending",
            }.get(step_copy["status"], "Pending")
            if current_found:
                if step_copy["status"] != "completed":
                    step_copy["status"] = "pending"
                    step_copy["state_label"] = "Pending"
                normalized.append(step_copy)
                continue

            if step_copy["status"] == "completed":
                normalized.append(step_copy)
                continue

            if step_copy["status"] == "blocked":
                current_found = True
                normalized.append(step_copy)
                continue

            step_copy["status"] = "current"
            step_copy["state_label"] = "Current"
            current_found = True
            normalized.append(step_copy)

        if not current_found:
            return normalized

        first_current_index = next(
            (idx for idx, item in enumerate(normalized) if item["status"] in {"current", "blocked"}),
            None,
        )
        if first_current_index is None:
            return normalized

        for idx in range(first_current_index + 1, len(normalized)):
            if normalized[idx]["status"] != "completed":
                normalized[idx]["status"] = "pending"
                normalized[idx]["state_label"] = "Pending"
        return normalized

    def _dashboard_status_for_codes(self, codes):
        steps = list(self.closing_steps.filter(code__in=codes))
        if not steps:
            return "pending"
        statuses = {step.status for step in steps}
        if all(status == PaymentClosingStep.Status.COMPLETED for status in statuses):
            return "completed"
        if PaymentClosingStep.Status.IN_PROGRESS in statuses or PaymentClosingStep.Status.COMPLETED in statuses:
            return "current"
        return "pending"

    @property
    def _dashboard_site_visit_status(self):
        if self.transaction_type != self.TransactionType.PURCHASE:
            return "pending"
        if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED, self.Status.RELEASED}:
            if self.next_closing_step and self.next_closing_step.code == "due_diligence":
                return "current"
            return "completed"
        return "pending"

    @property
    def buyer_next_step_summary(self):
        if self.transaction_type not in {self.TransactionType.PURCHASE, self.TransactionType.LEASE}:
            return "Follow the payment milestones in this workspace."
        next_step = self.next_closing_step
        if next_step:
            return f"Next step: {next_step.display_title}"
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
            f"Open the guided workspace for '{next_step.display_title}'. "
            f"{next_step.buyer_instruction}"
        )

    @property
    def checkout_guidance_title(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.plot and self.plot.land_type == "agricultural":
                return "Agricultural land purchase journey"
            return "Land purchase journey"
        if self.transaction_type == self.TransactionType.LEASE:
            if self.plot and self.plot.land_type == "agricultural":
                return "Agricultural land lease journey"
            return "Land lease journey"
        return "Transaction journey"

    @property
    def checkout_guidance_steps(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.plot and self.plot.land_type == "agricultural":
                return [
                    "Pay the commitment fee so AgriPlot can lock the plot and release the verified search and survey pack.",
                    "Review the due diligence documents, then work with the seller's lawyer on the sale agreement and deposit.",
                    "Use the tracker for LCB consent, stamp duty, completion, and final registration.",
                ]
            return [
                "Pay the commitment fee so AgriPlot can lock the plot and release the verified search pack.",
                "Review the due diligence documents, then move to the sale agreement and deposit stage.",
                "Use the tracker for consents or clearances, stamp duty, completion, and final registration.",
            ]
        if self.transaction_type == self.TransactionType.LEASE:
            if self.plot and self.plot.land_type == "agricultural":
                return [
                    "Confirm the verified farming details and intended lease use.",
                    "Visit the land and verify access, boundaries, and handover expectations.",
                    "Use the lease tracker to sign the agreement, confirm payment, and complete handover.",
                ]
            return [
                "Confirm the verified site details and intended lease use.",
                "Visit the site and agree the handover expectations with the owner or agent.",
                "Use the lease tracker to sign the agreement, confirm payment, and complete handover.",
            ]
        return []

    def sync_plot_market_state(self):
        if self.workflow_anchor_payment.pk != self.pk:
            return
        if not self.plot:
            return
        if self.transaction_type == self.TransactionType.PURCHASE:
            lock_message = ""
            if self.due_diligence_lock_expires_at:
                lock_message = (
                    f" Due-diligence lock runs until "
                    f"{timezone.localtime(self.due_diligence_lock_expires_at):%b %d, %Y %I:%M %p}."
                )
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
                    f"Reserved under active purchase transaction {self.internal_reference}.{lock_message}"
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
    buyer_confirmed_at = models.DateTimeField(null=True, blank=True)
    seller_confirmed_at = models.DateTimeField(null=True, blank=True)
    consent_reference_number = models.CharField(max_length=120, blank=True)
    meeting_date = models.DateField(null=True, blank=True)
    official_market_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    assessed_stamp_duty = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    original_title_received = models.BooleanField(default=False)
    seller_id_copy_received = models.BooleanField(default=False)
    transfer_forms_signed = models.BooleanField(default=False)
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
    def display_title(self):
        plot = self.payment.plot
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE and self.code == "lcb_consent":
            if plot and plot.land_type == "agricultural":
                return "Land Control Board & Family Consents"
            return "Transfer Consents & Seller Clearances"
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE and self.code == "stamp_duty":
            if plot and plot.market_zone == "rural":
                return "Rural Valuation & Stamp Duty"
            if plot and plot.market_zone in {"urban", "peri_urban"}:
                return "Municipal Valuation & Stamp Duty"
        return self.title

    @property
    def display_document_name(self):
        plot = self.payment.plot
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE and self.code == "lcb_consent":
            if plot and plot.land_type == "agricultural":
                return "LCB consent letter and any spousal consent affidavit"
            return "Consent letters, rates/rent clearance, and any spousal consent"
        return self.document_name

    @property
    def display_guidance(self):
        plot = self.payment.plot
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE and self.code == "lcb_consent":
            if plot and plot.land_type == "agricultural":
                return (
                    "Agricultural land needs Land Control Board consent before the transfer can continue. "
                    "Capture any spousal consent alongside the board approval."
                )
            return (
                "This step covers the consents and seller clearances needed for non-agricultural transfers, "
                "including rates, rent, lessor consent where applicable, and any family approvals."
            )
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE and self.code == "stamp_duty":
            if plot and plot.market_zone == "rural":
                return (
                    "Capture the government valuation and the rural stamp duty evidence before the deal can move to completion."
                )
            return (
                "Capture the government valuation and the municipal or peri-urban stamp duty evidence before the deal can move to completion."
            )
        return self.guidance

    @property
    def responsible_party_label(self):
        purchase_map = {
            "due_diligence": "Buyer",
            "agreement": "Seller Advocate",
            "lcb_consent": "Admin / Lawyer",
            "stamp_duty": "Buyer / Admin",
            "completion_docs": "Buyer Advocate",
            "registration": "Registrar / Admin",
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
        plot = self.payment.plot
        is_agricultural = bool(plot and plot.land_type == "agricultural")
        purchase_map = {
            "due_diligence": {
                "headline": "Review the official search and survey pack.",
                "where": "After the commitment fee, open the search, survey, and verification reports in AgriPlot and confirm the land is clean enough to proceed.",
                "document": "Official search and survey pack",
                "platform_role": "AgriPlot locks the plot, releases the verified documents, and uses this step as the legal green light before the serious legal work starts.",
                "cta_label": "Review Due Diligence Pack",
                "support_label": "Do not move to the sale agreement until the verified search and survey evidence make sense for this deal.",
            },
            "agreement": {
                "headline": "Sign the sale agreement and secure the 10% deposit.",
                "where": "The seller's lawyer prepares the agreement, both parties sign, and the deposit is secured under the agreed legal arrangement.",
                "document": "Signed Sale Agreement",
                "platform_role": "AgriPlot tracks the legal lock on the deal so the buyer can see when the agreement and deposit stage is properly completed.",
                "cta_label": "Review Agreement & Deposit",
                "support_label": "The agreement step should capture both the executed agreement and the fact that the deposit arrangement is in place.",
            },
            "lcb_consent": {
                "headline": "Secure the statutory green light.",
                "where": "Coordinate the required transfer consents and clearances for this land type before the deal moves to completion.",
                "document": "Consent and clearance pack",
                "platform_role": "AgriPlot keeps the statutory consent milestone visible so the transfer does not move ahead prematurely.",
                "cta_label": "Track Statutory Consents",
                "support_label": "Do not release the full purchase amount before the required legal consents are in place.",
            },
            "stamp_duty": {
                "headline": "Complete valuation and clear stamp duty.",
                "where": "The government valuation is entered first, then the buyer clears stamp duty through the KRA / eCitizen process.",
                "document": "Valuation report and stamp duty receipt",
                "platform_role": "AgriPlot keeps the tax step locked until the valuation and receipt evidence are both available.",
                "cta_label": "Upload Valuation & Stamp Duty",
                "support_label": "Do not treat the tax step as done until the government value and stamp duty receipt are both captured.",
            },
            "completion_docs": {
                "headline": "Exchange the completion papers and clear the remaining balance.",
                "where": "The buyer's lawyer confirms the original title, signed transfer forms, and ID/KRA copies are all in order before the balance is treated as safely released.",
                "document": "Completion document pack",
                "platform_role": "AgriPlot uses the completion checklist to make sure the final money-for-papers exchange is evidence-backed.",
                "cta_label": "Confirm Completion Exchange",
                "support_label": "This stage should only finish when the balance and the completion documents line up correctly.",
            },
            "registration": {
                "headline": "Register the title transfer and flip the ownership.",
                "where": "The lawyer or registrar uploads fresh registry proof showing the buyer's name before AgriPlot marks the plot sold.",
                "document": "Fresh registry search / title proof",
                "platform_role": "AgriPlot only flips the plot to sold after this final registry evidence is completed.",
                "cta_label": "Track Title Registration",
                "support_label": "A successful payment does not equal ownership transfer. The fresh registry search is the final proof.",
            },
        }
        if is_agricultural and "due_diligence" in purchase_map:
            purchase_map["due_diligence"]["where"] = (
                "Review the official search, survey, soil, and zoning findings on AgriPlot before progressing the agricultural land deal."
            )
            purchase_map["lcb_consent"]["where"] = (
                "Coordinate the Land Control Board appearance and make sure any required spousal consent is signed too."
            )
            purchase_map["lcb_consent"]["document"] = "LCB / spousal consent pack"
            purchase_map["lcb_consent"]["support_label"] = (
                "Do not release the full purchase amount before the Land Control Board consent and related family consents are in place."
            )
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
            "due_diligence": "Review the verified search, survey, and registry pack on AgriPlot before moving into the sale agreement stage.",
            "agreement": "Review the sale agreement with your advocate and be ready to sign once the seller's advocate shares it.",
            "lcb_consent": "Coordinate with the seller for the Land Control Board meeting and carry your ID documents.",
            "stamp_duty": "Follow up on the government valuation, pay stamp duty through KRA/eCitizen, and upload the proof here.",
            "completion_docs": "Wait for the seller's advocate to hand over the completion documents, then confirm they are complete before the balance is released.",
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

    @property
    def stakeholder_update_label(self):
        purchase_map = {
            "due_diligence": "Buyer review confirmation",
            "agreement": "Seller-side legal upload",
            "lcb_consent": "Admin / lawyer evidence upload",
            "stamp_duty": "Buyer and admin tax evidence upload",
            "completion_docs": "Buyer-side completion checklist",
            "registration": "Registrar / admin proof upload",
        }
        lease_map = {
            "offer": "Buyer confirmation",
            "agreement": "Both parties / admin upload",
            "payment_security": "Buyer proof upload",
            "handover": "Seller handover confirmation",
        }
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return purchase_map.get(self.code, "Evidence-backed update")
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return lease_map.get(self.code, "Evidence-backed update")
        return "Evidence-backed update"

    @property
    def completion_requirements(self):
        requirement_map = {
            "agreement": ["Executed sale agreement uploaded"],
            "lcb_consent": ["Consent number entered", "Meeting date entered", "LCB / spousal consent upload"],
            "stamp_duty": ["Official market value entered", "Calculated stamp duty entered", "Stamp duty receipt uploaded"],
            "completion_docs": ["Original title received", "Seller ID / KRA copies received", "Transfer forms signed"],
            "registration": ["New search or registry proof uploaded"],
        }
        return requirement_map.get(self.code, [])

    def can_mark_complete_with_current_evidence(self):
        if self.code == "due_diligence":
            return True
        if self.code in {"agreement", "registration"}:
            return bool(self.document)
        if self.code == "lcb_consent":
            return bool(self.document and self.consent_reference_number and self.meeting_date)
        if self.code == "stamp_duty":
            return bool(
                self.document
                and self.official_market_value is not None
                and self.assessed_stamp_duty is not None
            )
        if self.code == "completion_docs":
            return bool(
                self.original_title_received
                and self.seller_id_copy_received
                and self.transfer_forms_signed
            )
        return True

    def evidence_blocking_reason(self):
        if self.can_mark_complete_with_current_evidence():
            return ""
        requirement_text = ", ".join(self.completion_requirements)
        return f"This step needs more evidence before it can be completed: {requirement_text}."

    def set_status(self, status, actor=None, notes="", bypass_evidence=False):
        if status == self.Status.COMPLETED and not bypass_evidence:
            blocking_reason = self.evidence_blocking_reason()
            if blocking_reason:
                raise ValidationError(blocking_reason)
        previous_status = self.status
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
        if previous_status != self.Status.COMPLETED and status == self.Status.COMPLETED:
            self._auto_assign_next_step(actor=actor)

    def _auto_assign_next_step(self, actor=None):
        next_step = (
            self.payment.closing_steps.filter(sequence__gt=self.sequence)
            .exclude(status=self.Status.COMPLETED)
            .order_by("sequence")
            .first()
        )
        if not next_step:
            return

        updated_fields = []
        if next_step.status == self.Status.PENDING:
            next_step.status = self.Status.IN_PROGRESS
            updated_fields.append("status")
        updated_fields.append("updated_at")
        next_step.save(update_fields=updated_fields)

        assignment_message = (
            f"Next transaction step assigned: {next_step.display_title} → "
            f"{next_step.responsible_party_label}."
        )
        self.payment.add_event("closing_step_assigned", assignment_message, actor=actor)

        from django.contrib.auth.models import User
        from notifications.notification_service import NotificationService

        recipients = []
        label = next_step.responsible_party_label.lower()
        if "buyer" in label and self.payment.buyer:
            recipients.append(self.payment.buyer)
        if any(token in label for token in ["seller", "agent"]) and self.payment.seller:
            recipients.append(self.payment.seller)
        if any(token in label for token in ["admin", "valuer", "government", "operations"]):
            recipients.extend(
                User.objects.filter(
                    models.Q(is_superuser=True) | models.Q(groups__name="Finance Admin")
                ).distinct()
            )

        for recipient in {user.pk: user for user in recipients if user}.values():
            NotificationService.create_notification(
                user=recipient,
                notification_type="plot_stage_update",
                title=f"Next step assigned: {next_step.display_title}",
                message=assignment_message,
                plot=self.payment.plot,
            )
