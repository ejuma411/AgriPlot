import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class PaymentRequest(models.Model):
    DEFAULT_OFFICIAL_SEARCH_FEE = Decimal("1000.00")
    DEFAULT_SURVEY_SEARCH_FEE = Decimal("500.00")
    DEFAULT_LCB_FEE = Decimal("3000.00")
    DEFAULT_TRANSFER_FEE = Decimal("1000.00")
    DEFAULT_TITLE_FEE = Decimal("2500.00")
    DEFAULT_SOIL_BASELINE_FEE = Decimal("2500.00")
    DEFAULT_PLATFORM_ESCROW_RATE = Decimal("0.0075")
    DEFAULT_AGENT_COMMISSION_RATE = Decimal("0.03")
    DEFAULT_VERIFICATION_MARKUP_RATE = Decimal("0.20")

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
    intended_use = models.CharField(max_length=180, blank=True)
    lease_security_deposit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notice_period_days = models.PositiveIntegerField(default=90)
    good_husbandry_required = models.BooleanField(default=True)
    soil_exit_test_required = models.BooleanField(default=True)
    subject_to_sale = models.BooleanField(default=False)
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
            "lcb_consent",
            "LCB / Spousal Consent",
            "LCB consent and family approvals",
            "Agricultural leases over one month should not go live until the Land Control Board consent and any family approvals are in place.",
        ),
        (
            "agreement",
            "Lease Agreement Signed",
            "Signed Lease Agreement",
            "Both parties sign the lease agreement with their agreed dates, good husbandry obligations, exit rules, and any subject-to-sale clauses.",
        ),
        (
            "payment_security",
            "Deposit / Escrow Confirmed",
            "Security deposit or rent proof",
            "The agreed security deposit or first rent commitment is recorded and held under the AgriPlot workflow before occupation.",
        ),
        (
            "lease_registration",
            "Lease Registry Filing",
            "Registry filing evidence",
            "Leases beyond two years should be lodged or protected through the Lands Registry workflow so the tenant is not defeated by third parties.",
        ),
        (
            "soil_health_baseline",
            "Soil Health Baseline Agreed",
            "Baseline soil or land condition report",
            "The parties confirm the starting soil condition and any conservation duties before possession starts.",
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
            if self.notice_period_days < 30:
                raise ValidationError(
                    {"notice_period_days": "Vacation notice should be at least 30 days."}
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
                if self.plot.land_type == "agricultural" and self.notice_period_days < 90:
                    raise ValidationError(
                        {"notice_period_days": "Agricultural lease notice should be at least 90 days."}
                    )
                if self.plot.listing_type == "both":
                    self.subject_to_sale = True

    def save(self, *args, **kwargs):
        if not self.internal_reference:
            self.internal_reference = self.generate_reference()
        super().save(*args, **kwargs)

    def _money(self, value):
        if value in (None, ""):
            return Decimal("0.00")
        if isinstance(value, Decimal):
            return value.quantize(Decimal("0.01"))
        return Decimal(str(value)).quantize(Decimal("0.01"))

    def _money_display(self, value):
        amount = self._money(value)
        return f"KSh {amount:,.2f}"

    def _metadata_decimal(self, key, default):
        metadata = self.metadata or {}
        return self._money(metadata.get(key, default))

    def _metadata_rate(self, key, default):
        metadata = self.metadata or {}
        value = metadata.get(key, default)
        return Decimal(str(value))

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

    @property
    def sale_price_value(self):
        if not self.plot:
            return self._money(self.amount)
        return self._money(
            self.plot.sale_price
            or self.plot.price
            or self.amount
        )

    @property
    def lease_contract_value(self):
        if self.transaction_type != self.TransactionType.LEASE:
            return Decimal("0.00")
        if self.lease_start_date and self.lease_end_date:
            duration_days = max((self.lease_end_date - self.lease_start_date).days, 0)
            duration_months = max(1, (duration_days // 30) or 1)
        else:
            duration_months = 12
        if self.plot and self.plot.lease_price_monthly:
            return self._money(self.plot.lease_price_monthly) * duration_months
        if self.plot and self.plot.lease_price_yearly:
            yearly = self._money(self.plot.lease_price_yearly)
            return (yearly / Decimal("12.00") * Decimal(str(duration_months))).quantize(Decimal("0.01"))
        return self._money(self.amount)

    @property
    def agent_commission_rate(self):
        return self._metadata_rate("agent_commission_rate", self.DEFAULT_AGENT_COMMISSION_RATE)

    @property
    def platform_escrow_rate(self):
        return self._metadata_rate("platform_escrow_rate", self.DEFAULT_PLATFORM_ESCROW_RATE)

    @property
    def verification_markup_rate(self):
        return self._metadata_rate("verification_markup_rate", self.DEFAULT_VERIFICATION_MARKUP_RATE)

    @property
    def official_search_fee(self):
        return self._metadata_decimal("official_search_fee", self.DEFAULT_OFFICIAL_SEARCH_FEE)

    @property
    def survey_search_fee(self):
        return self._metadata_decimal("survey_search_fee", self.DEFAULT_SURVEY_SEARCH_FEE)

    @property
    def lcb_fee_amount(self):
        return self._metadata_decimal("lcb_fee_amount", self.DEFAULT_LCB_FEE)

    @property
    def transfer_fee_amount(self):
        return self._metadata_decimal("transfer_fee_amount", self.DEFAULT_TRANSFER_FEE)

    @property
    def title_fee_amount(self):
        return self._metadata_decimal("title_fee_amount", self.DEFAULT_TITLE_FEE)

    @property
    def soil_baseline_fee_amount(self):
        return self._metadata_decimal("soil_baseline_fee_amount", self.DEFAULT_SOIL_BASELINE_FEE)

    @property
    def purchase_stamp_duty_estimate(self):
        if self.transaction_type != self.TransactionType.PURCHASE:
            return Decimal("0.00")
        stamp_step = self.closing_steps.filter(code="stamp_duty").first()
        if stamp_step and stamp_step.assessed_stamp_duty is not None:
            return self._money(stamp_step.assessed_stamp_duty)
        rate = Decimal("0.02") if self.plot and self.plot.market_zone == "rural" else Decimal("0.04")
        return (self.sale_price_value * rate).quantize(Decimal("0.01"))

    def _related_payment_for_category(self, category):
        for payment in self.workflow_related_payments:
            if payment.category == category:
                return payment
        return None

    @property
    def agreement_deposit_amount(self):
        related = self._related_payment_for_category(self.Category.AGREEMENT_DEPOSIT)
        if related:
            return self._money(related.amount)
        if self.transaction_type == self.TransactionType.PURCHASE:
            return (self.sale_price_value * Decimal("0.10")).quantize(Decimal("0.01"))
        return self._money(self.amount)

    @property
    def completion_balance_amount(self):
        related = self._related_payment_for_category(self.Category.COMPLETION_BALANCE)
        if related:
            return self._money(related.amount)
        if self.transaction_type == self.TransactionType.PURCHASE:
            return max(self.sale_price_value - self.agreement_deposit_amount, Decimal("0.00"))
        return self._money(self.amount)

    @property
    def seller_total_payout_amount(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            gross = self.sale_price_value
        elif self.transaction_type == self.TransactionType.LEASE:
            gross = self.lease_contract_value
        else:
            gross = self._money(self.amount)
        if self.plot and self.plot.agent_id:
            gross -= self.agent_commission_amount
        return max(gross - self.platform_fee_amount, Decimal("0.00"))

    @property
    def agent_commission_amount(self):
        if not self.plot or not self.plot.agent_id:
            return Decimal("0.00")
        base = self.sale_price_value if self.transaction_type == self.TransactionType.PURCHASE else self.lease_contract_value
        return (base * self.agent_commission_rate).quantize(Decimal("0.01"))

    @property
    def platform_fee_amount(self):
        base = self.sale_price_value if self.transaction_type == self.TransactionType.PURCHASE else self.lease_contract_value
        return (base * self.platform_escrow_rate).quantize(Decimal("0.01"))

    @property
    def verification_markup_amount(self):
        base = self.official_search_fee + self.survey_search_fee
        return (base * self.verification_markup_rate).quantize(Decimal("0.01"))

    @property
    def search_result_summary(self):
        search_result = getattr(self.plot, "search_result", None) if self.plot else None
        if not search_result:
            return "Registry search result is still pending upload."
        if search_result.encumbrances:
            return f"Registered interests noted: {search_result.encumbrances}"
        if search_result.verified:
            return "Registry search is verified and no encumbrances were recorded."
        return "Search result is on file but still awaiting final verification."

    @property
    def transaction_stage_matrix(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            stamp_duty = self._money_display(self.purchase_stamp_duty_estimate)
            return [
                {
                    "stage": "1. Due Diligence",
                    "money_required": (
                        f"{self._money_display(self.official_search_fee)} official search + "
                        f"{self._money_display(self.survey_search_fee)} survey search"
                    ),
                    "form_document": "Official search request, survey search request, seller KYC pack",
                    "required_information": "Title number, parcel number, buyer name, seller ID/KRA PIN, and plot location details.",
                    "who_provides": "Buyer initiates and pays; seller uploads title and identity support.",
                    "who_files": "AgriPlot coordinates the registry/survey request and stores the result in the transaction room.",
                    "system_output": "Encumbrance-free certificate draft, verified due-diligence pack, and payment acknowledgment.",
                },
                {
                    "stage": "2. Commitment",
                    "money_required": f"{self._money_display(self.agreement_deposit_amount)} agreement deposit into escrow",
                    "form_document": "Letter of offer / reservation terms and escrow acknowledgment",
                    "required_information": "Offer price, deposit amount, buyer and seller details, payment reference, and reservation expiry.",
                    "who_provides": "Buyer signs and funds the escrow; seller or agent accepts the commercial terms.",
                    "who_files": "AgriPlot records the commitment and issues proof-of-funds to the seller side.",
                    "system_output": "Buyer payment acknowledgment and seller proof-of-funds notice.",
                },
                {
                    "stage": "3. Agreement",
                    "money_required": "Advocate fees and any agreed document-preparation costs",
                    "form_document": "Sale Agreement and advocate details",
                    "required_information": "Purchase price, completion period, parties, advocates, title details, deposit handling, and default remedies.",
                    "who_provides": "Seller advocate drafts; buyer and seller review and sign.",
                    "who_files": "Signed agreement is uploaded in AgriPlot by the responsible advocate or admin.",
                    "system_output": "Signed-agreement certificate and the first escrow release trigger.",
                },
                {
                    "stage": "4. Consents",
                    "money_required": f"{self._money_display(self.lcb_fee_amount)} estimated LCB / consent filing fees",
                    "form_document": "LCB consent, spousal consent, and other transfer clearances",
                    "required_information": "Consent reference, meeting date, land-control details, spouse/family approvals where applicable.",
                    "who_provides": "Seller leads statutory consent preparation with advocate support.",
                    "who_files": "AgriPlot or the advocate uploads the approval pack into the closing tracker.",
                    "system_output": "Consent clearance certificate showing the transfer is legally ready to continue.",
                },
                {
                    "stage": "5. Taxation",
                    "money_required": f"{stamp_duty} stamp duty + registry transfer fees",
                    "form_document": "Government valuation, stamp duty receipt, KRA/eCitizen confirmations",
                    "required_information": "Official market value, assessed stamp duty, payment receipt, transfer reference, and KRA identifiers.",
                    "who_provides": "Buyer pays duty; seller handles seller-side tax obligations and supporting documents.",
                    "who_files": "Buyer advocate or AgriPlot admin uploads the valuation and receipts.",
                    "system_output": "Tax clearance acknowledgment and a ready-to-register completion pack.",
                },
                {
                    "stage": "6. Transfer & Registration",
                    "money_required": (
                        f"{self._money_display(self.transfer_fee_amount + self.title_fee_amount)} registry filing fees + "
                        f"{self._money_display(self.completion_balance_amount)} balance release"
                    ),
                    "form_document": "Transfer instrument, original title, signed completion bundle, fresh registry proof",
                    "required_information": "Signed transfer forms, original title, seller ID/PIN, buyer ID/PIN, completion balance reference, and final registry evidence.",
                    "who_provides": "Seller signs transfer forms; buyer advocate lodges the registration set.",
                    "who_files": "Advocate or AgriPlot admin uploads registry proof after transfer.",
                    "system_output": "Completion notice, final payout release, and digital certified title-copy record for the buyer.",
                },
            ]

        if self.transaction_type == self.TransactionType.LEASE:
            return [
                {
                    "stage": "1. Lease Application & Intent",
                    "money_required": f"{self._money_display(self.amount)} commitment or first lease payment",
                    "form_document": "Lease offer / application and intended-use disclosure",
                    "required_information": "Requested term, intended use, start date, end date, and renewal expectations.",
                    "who_provides": "Tenant applies; landlord or agent reviews.",
                    "who_files": "AgriPlot opens the lease tracker and records the intent.",
                    "system_output": "Lease application acknowledgment and occupancy tracker entry.",
                },
                {
                    "stage": "2. LCB & Family Consents",
                    "money_required": f"{self._money_display(self.lcb_fee_amount)} consent filing estimate for agricultural land",
                    "form_document": "LCB consent pack and any spousal/family approvals",
                    "required_information": "Consent reference, board date, spouses or family sign-off, and plot details.",
                    "who_provides": "Landlord side prepares statutory approvals.",
                    "who_files": "Seller, advocate, or admin uploads the consent evidence into AgriPlot.",
                    "system_output": "Consent-readiness certificate before occupation.",
                },
                {
                    "stage": "3. Deposit & Escrow",
                    "money_required": f"{self._money_display(self.lease_security_deposit or self.amount)} security deposit or rent commitment",
                    "form_document": "Escrow receipt and payment acknowledgment",
                    "required_information": "Tenant identity, lease reference, amount paid, payment method, and due date.",
                    "who_provides": "Tenant pays through AgriPlot.",
                    "who_files": "System-generated from payment confirmation.",
                    "system_output": "Tenant payment acknowledgment and landlord proof-of-funds notice.",
                },
                {
                    "stage": "4. Digital Lease Agreement",
                    "money_required": "Advocate or drafting costs if applicable",
                    "form_document": "Digitally confirmed lease agreement",
                    "required_information": "Term, notice period, good husbandry clause, subject-to-sale clause, and exit obligations.",
                    "who_provides": "Tenant and landlord both confirm digitally.",
                    "who_files": "AgriPlot stores the generated agreement and confirmation timestamps.",
                    "system_output": "Lease agreement certificate and compliance baseline.",
                },
                {
                    "stage": "5. Registry & Soil Baseline",
                    "money_required": (
                        f"{self._money_display(self.soil_baseline_fee_amount)} soil baseline / officer fee"
                    ),
                    "form_document": "Registry protection proof and soil baseline report",
                    "required_information": "Lease term, registry filing evidence, soil status, and entry condition notes.",
                    "who_provides": "AgriPlot-appointed officer or approved professional uploads the baseline and registry evidence.",
                    "who_files": "Professional report is uploaded before handover.",
                    "system_output": "Soil baseline certificate and long-lease protection evidence where required.",
                },
                {
                    "stage": "6. Handover & Occupation",
                    "money_required": "No extra money unless handover services were ordered",
                    "form_document": "Possession note / handover acknowledgment",
                    "required_information": "Access date, site condition, boundaries, keys or access points, and outstanding obligations.",
                    "who_provides": "Landlord or agent meets the tenant for handover.",
                    "who_files": "AgriPlot stores the signed handover note and activates the lease status.",
                    "system_output": "Active occupancy notice, public lease status card, and next-lease waitlist visibility.",
                },
                {
                    "stage": "7. Renewal or Exit",
                    "money_required": "Renewal fee only if a new term is agreed",
                    "form_document": "Renewal confirmation or exit soil report",
                    "required_information": "Renewal election, final notice date, soil exit result, and handback status.",
                    "who_provides": "Current tenant responds to reminders; landlord confirms renewal or exit.",
                    "who_files": "AgriPlot records reminders, exit proof, or renewal confirmation.",
                    "system_output": "Renewal notice trail, tenancy termination record, and automatic release for the next tenant if not renewed.",
                },
            ]
        return []

    @property
    def officer_payment_rules(self):
        common_release = "Funds are held by AgriPlot and only released after the report or statutory evidence is uploaded and accepted."
        if self.transaction_type == self.TransactionType.PURCHASE:
            return [
                {
                    "officer": "Registry / Lands Officer",
                    "paid_by": "Buyer",
                    "fee": self._money_display(self.official_search_fee),
                    "purpose": "Official search and registry proof.",
                    "release_rule": common_release,
                },
                {
                    "officer": "Survey Office / Licensed Surveyor",
                    "paid_by": "Buyer",
                    "fee": self._money_display(self.survey_search_fee),
                    "purpose": "Survey search, beacon alignment, or map verification.",
                    "release_rule": common_release,
                },
                {
                    "officer": "Land Control Board / Consent Processing",
                    "paid_by": "Seller",
                    "fee": self._money_display(self.lcb_fee_amount),
                    "purpose": "Consent-processing and statutory readiness costs.",
                    "release_rule": "Released after consent evidence and board reference are uploaded.",
                },
                {
                    "officer": "Government Valuer / Tax Workflow",
                    "paid_by": "Buyer",
                    "fee": self._money_display(self.purchase_stamp_duty_estimate),
                    "purpose": "Valuation-linked tax clearance and stamp-duty processing.",
                    "release_rule": "Released once the government valuation and tax receipt are captured.",
                },
            ]
        if self.transaction_type == self.TransactionType.LEASE:
            return [
                {
                    "officer": "Land Control Board / Consent Processing",
                    "paid_by": "Landlord",
                    "fee": self._money_display(self.lcb_fee_amount),
                    "purpose": "Agricultural-lease consent processing.",
                    "release_rule": "Released after the consent pack is uploaded.",
                },
                {
                    "officer": "Extension Officer / Soil Professional",
                    "paid_by": "Tenant or buyer of baseline service",
                    "fee": self._money_display(self.soil_baseline_fee_amount),
                    "purpose": "Soil baseline and exit-condition support.",
                    "release_rule": common_release,
                },
                {
                    "officer": "Registry / Lawyer",
                    "paid_by": "Parties as agreed",
                    "fee": "Varies by lease term",
                    "purpose": "Registry protection for leases exceeding two years.",
                    "release_rule": "Released after filing proof is uploaded and the step is approved.",
                },
            ]
        return []

    @property
    def platform_revenue_streams(self):
        return [
            {
                "label": "Escrow facilitation fee",
                "amount": self._money_display(self.platform_fee_amount),
                "detail": "AgriPlot earns this when the transaction completes and money is released through the platform workflow.",
            },
            {
                "label": "Verification markup",
                "amount": self._money_display(self.verification_markup_amount),
                "detail": "Markup on search and survey coordination that pays for the digital report packaging and platform handling.",
            },
            {
                "label": "Agent subscriptions / featured listings",
                "amount": "External to this deal",
                "detail": "Recurring revenue for broker tools and listing visibility, not deducted from this transaction automatically.",
            },
        ]

    def _certificate_statuses(self):
        active_payment_statuses = {
            self.Status.PAID,
            self.Status.IN_ESCROW,
            self.Status.PARTIALLY_RELEASED,
            self.Status.RELEASED,
        }
        due_diligence_ready = bool(self.due_diligence_documents or getattr(self.plot, "search_result", None))
        payment_confirmed = self.status in active_payment_statuses
        registration_step = self.closing_steps.filter(code="registration").first()
        handover_complete = self.closing_steps.filter(
            code="handover",
            status=PaymentClosingStep.Status.COMPLETED,
        ).exists()
        agreement_complete = self.closing_steps.filter(
            code="agreement",
            status=PaymentClosingStep.Status.COMPLETED,
        ).exists()
        completion_complete = self.purchase_registration_complete
        if self.transaction_type == self.TransactionType.PURCHASE:
            return {
                "buyer_clearance": PaymentCertificate.Status.ISSUED if due_diligence_ready else PaymentCertificate.Status.PENDING,
                "buyer_payment_ack": PaymentCertificate.Status.ISSUED if payment_confirmed else PaymentCertificate.Status.PENDING,
                "seller_proof_of_funds": PaymentCertificate.Status.ISSUED if payment_confirmed else PaymentCertificate.Status.PENDING,
                "consent_clearance": PaymentCertificate.Status.ISSUED
                if self.closing_steps.filter(code="lcb_consent", status=PaymentClosingStep.Status.COMPLETED).exists()
                else PaymentCertificate.Status.PENDING,
                "completion_notice": PaymentCertificate.Status.ISSUED if completion_complete else PaymentCertificate.Status.PENDING,
                "digital_title_copy": PaymentCertificate.Status.ISSUED
                if registration_step and registration_step.document and completion_complete
                else PaymentCertificate.Status.PENDING,
            }
        return {
            "tenant_payment_ack": PaymentCertificate.Status.ISSUED if payment_confirmed else PaymentCertificate.Status.PENDING,
            "landlord_proof_of_funds": PaymentCertificate.Status.ISSUED if payment_confirmed else PaymentCertificate.Status.PENDING,
            "lease_compliance": PaymentCertificate.Status.ISSUED if agreement_complete and handover_complete else PaymentCertificate.Status.PENDING,
            "soil_baseline": PaymentCertificate.Status.ISSUED
            if self.closing_steps.filter(code="soil_health_baseline", status=PaymentClosingStep.Status.COMPLETED).exists()
            else PaymentCertificate.Status.PENDING,
            "renewal_exit_notice": PaymentCertificate.Status.READY if self.lease_end_date else PaymentCertificate.Status.PENDING,
        }

    def ensure_transaction_artifacts(self):
        anchor = self.workflow_anchor_payment
        if anchor.pk != self.pk:
            return anchor.ensure_transaction_artifacts()
        anchor.ensure_closing_steps()
        anchor._ensure_default_certificates()
        anchor._ensure_default_disbursements()

    def _ensure_default_certificates(self):
        statuses = self._certificate_statuses()
        search_result = getattr(self.plot, "search_result", None) if self.plot else None
        registration_step = self.closing_steps.filter(code="registration").first()
        if self.transaction_type == self.TransactionType.PURCHASE:
            templates = [
                {
                    "code": "buyer_clearance",
                    "title": "Encumbrance-Free / Search Clearance Certificate",
                    "audience": PaymentCertificate.Audience.BUYER,
                    "summary": self.search_result_summary,
                },
                {
                    "code": "buyer_payment_ack",
                    "title": "Buyer Payment Acknowledgment",
                    "audience": PaymentCertificate.Audience.BUYER,
                    "summary": f"AgriPlot has received and recorded {self._money_display(self.workflow_total_paid_amount)} for this deal.",
                },
                {
                    "code": "seller_proof_of_funds",
                    "title": "Seller Proof of Funds Notice",
                    "audience": PaymentCertificate.Audience.SELLER,
                    "summary": f"AgriPlot is holding buyer funds under reference {self.internal_reference} pending the agreed release rules.",
                },
                {
                    "code": "consent_clearance",
                    "title": "Consent & Clearance Milestone",
                    "audience": PaymentCertificate.Audience.BOTH,
                    "summary": "Statutory consents and seller clearances are recorded in the transaction workspace before completion can proceed.",
                },
                {
                    "code": "completion_notice",
                    "title": "Completion Notice",
                    "audience": PaymentCertificate.Audience.BOTH,
                    "summary": "Registration evidence is complete and AgriPlot can now close the transaction and release the final funds.",
                },
                {
                    "code": "digital_title_copy",
                    "title": "Digital Certified Title-Copy Record",
                    "audience": PaymentCertificate.Audience.BUYER,
                    "summary": (
                        f"Registry proof uploaded: {registration_step.document.name.split('/')[-1]}"
                        if registration_step and registration_step.document
                        else "Fresh registry proof will appear here after title registration completes."
                    ),
                },
            ]
        else:
            templates = [
                {
                    "code": "tenant_payment_ack",
                    "title": "Tenant Payment Acknowledgment",
                    "audience": PaymentCertificate.Audience.BUYER,
                    "summary": f"AgriPlot has recorded the tenant payment and security arrangement for {self._money_display(self.amount)}.",
                },
                {
                    "code": "landlord_proof_of_funds",
                    "title": "Landlord Proof of Funds Notice",
                    "audience": PaymentCertificate.Audience.SELLER,
                    "summary": "AgriPlot is holding the tenant's funds until the lease agreement, consent, and handover conditions are satisfied.",
                },
                {
                    "code": "lease_compliance",
                    "title": "Lease Compliance Certificate",
                    "audience": PaymentCertificate.Audience.BOTH,
                    "summary": "AgriPlot records the lease term, consent pack, agreement confirmations, and handover conditions in one audit trail.",
                },
                {
                    "code": "soil_baseline",
                    "title": "Soil Baseline Certificate",
                    "audience": PaymentCertificate.Audience.BOTH,
                    "summary": "The entry-condition soil or land baseline is stored here to support good husbandry and exit testing.",
                },
                {
                    "code": "renewal_exit_notice",
                    "title": "Renewal / Exit Notice Record",
                    "audience": PaymentCertificate.Audience.BOTH,
                    "summary": "AgriPlot tracks the notice window, renewal reminders, and exit-trigger timing for this lease.",
                },
            ]

        for template in templates:
            certificate, _ = PaymentCertificate.objects.get_or_create(
                payment=self,
                code=template["code"],
                defaults={
                    "title": template["title"],
                    "audience": template["audience"],
                    "summary": template["summary"],
                    "status": statuses.get(template["code"], PaymentCertificate.Status.PENDING),
                    "issued_at": timezone.now()
                    if statuses.get(template["code"]) == PaymentCertificate.Status.ISSUED
                    else None,
                    "metadata": {
                        "search_verified": bool(search_result and search_result.verified),
                    },
                },
            )
            update_fields = []
            if certificate.title != template["title"]:
                certificate.title = template["title"]
                update_fields.append("title")
            if certificate.audience != template["audience"]:
                certificate.audience = template["audience"]
                update_fields.append("audience")
            if certificate.summary != template["summary"]:
                certificate.summary = template["summary"]
                update_fields.append("summary")
            status = statuses.get(template["code"], PaymentCertificate.Status.PENDING)
            if certificate.status != status:
                certificate.status = status
                update_fields.append("status")
            issued_at = certificate.issued_at
            if status == PaymentCertificate.Status.ISSUED and not certificate.issued_at:
                issued_at = timezone.now()
            if status != PaymentCertificate.Status.ISSUED:
                issued_at = None
            if certificate.issued_at != issued_at:
                certificate.issued_at = issued_at
                update_fields.append("issued_at")
            if update_fields:
                update_fields.append("updated_at")
                certificate.save(update_fields=update_fields)

    def _ensure_default_disbursements(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            templates = [
                {
                    "code": "registry_search_fee",
                    "recipient_role": PaymentDisbursement.RecipientRole.OFFICER,
                    "recipient_user": None,
                    "recipient_name": "Registry / Lands Office",
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.official_search_fee,
                    "release_trigger": "Release after the official search evidence is uploaded and accepted.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="due_diligence", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "due_diligence",
                    "notes": "Buyer-funded official search fee managed through AgriPlot.",
                },
                {
                    "code": "survey_search_fee",
                    "recipient_role": PaymentDisbursement.RecipientRole.OFFICER,
                    "recipient_user": None,
                    "recipient_name": "Survey Office / Licensed Surveyor",
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.survey_search_fee,
                    "release_trigger": "Release after survey or beacon evidence is uploaded.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="due_diligence", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "due_diligence",
                    "notes": "Buyer-funded survey or map verification fee.",
                },
                {
                    "code": "platform_verification_markup",
                    "recipient_role": PaymentDisbursement.RecipientRole.PLATFORM,
                    "recipient_user": None,
                    "recipient_name": "AgriPlot",
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.verification_markup_amount,
                    "release_trigger": "Earned when AgriPlot coordinates and delivers the verified due-diligence pack.",
                    "status": PaymentDisbursement.Status.READY
                    if self.closing_steps.filter(code="due_diligence", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.PLANNED,
                    "stage_code": "due_diligence",
                    "notes": "Platform markup on verification coordination.",
                },
                {
                    "code": "seller_deposit_release",
                    "recipient_role": PaymentDisbursement.RecipientRole.SELLER,
                    "recipient_user": self.seller,
                    "recipient_name": self.counterparty_label,
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.agreement_deposit_amount,
                    "release_trigger": "Release after the sale agreement is signed and the agreement milestone is completed.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="agreement", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "agreement",
                    "notes": "The 10% deposit remains in escrow until the agreement milestone is satisfied.",
                },
                {
                    "code": "stamp_duty_payment",
                    "recipient_role": PaymentDisbursement.RecipientRole.GOVERNMENT,
                    "recipient_user": None,
                    "recipient_name": "KRA / eCitizen",
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.purchase_stamp_duty_estimate,
                    "release_trigger": "Release once the valuation and stamp-duty payment receipt are uploaded.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="stamp_duty", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "stamp_duty",
                    "notes": "Government tax clearance component.",
                },
                {
                    "code": "registry_transfer_fees",
                    "recipient_role": PaymentDisbursement.RecipientRole.GOVERNMENT,
                    "recipient_user": None,
                    "recipient_name": "Lands Registry",
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.transfer_fee_amount + self.title_fee_amount,
                    "release_trigger": "Release at the filing stage when registration documents are lodged.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.purchase_registration_complete
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "registration",
                    "notes": "Transfer filing and new-title fees.",
                },
                {
                    "code": "platform_escrow_fee",
                    "recipient_role": PaymentDisbursement.RecipientRole.PLATFORM,
                    "recipient_user": None,
                    "recipient_name": "AgriPlot",
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.platform_fee_amount,
                    "release_trigger": "Earned when the deal reaches final completion through AgriPlot escrow.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.purchase_registration_complete
                    else PaymentDisbursement.Status.READY,
                    "stage_code": "registration",
                    "notes": "Platform escrow facilitation fee.",
                },
                {
                    "code": "agent_commission",
                    "recipient_role": PaymentDisbursement.RecipientRole.AGENT,
                    "recipient_user": self.plot.agent.user if self.plot and self.plot.agent_id else None,
                    "recipient_name": (
                        self.plot.agent.user.get_full_name() or self.plot.agent.user.username
                        if self.plot and self.plot.agent_id
                        else "No agent on this deal"
                    ),
                    "paid_by_side": PaymentDisbursement.PaidBy.SELLER,
                    "amount": self.agent_commission_amount,
                    "release_trigger": "Deduct from the seller's final payout when registration is complete.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.purchase_registration_complete and self.agent_commission_amount > 0
                    else PaymentDisbursement.Status.PLANNED,
                    "stage_code": "registration",
                    "notes": "Agent commission deducted from seller proceeds.",
                },
                {
                    "code": "seller_final_payout",
                    "recipient_role": PaymentDisbursement.RecipientRole.SELLER,
                    "recipient_user": self.seller,
                    "recipient_name": self.counterparty_label,
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.seller_total_payout_amount,
                    "release_trigger": "Release only after title registration is evidenced and the deal is marked complete.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.purchase_registration_complete
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "registration",
                    "notes": "Final seller payout after deductions.",
                },
            ]
        else:
            templates = [
                {
                    "code": "tenant_security_receipt",
                    "recipient_role": PaymentDisbursement.RecipientRole.SELLER,
                    "recipient_user": self.seller,
                    "recipient_name": self.counterparty_label,
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self._money(self.lease_security_deposit or self.amount),
                    "release_trigger": "Held until the lease agreement, consent, and handover steps are complete.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="handover", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "payment_security",
                    "notes": "Lease security or first rent payout to landlord.",
                },
                {
                    "code": "lcb_processing_fee",
                    "recipient_role": PaymentDisbursement.RecipientRole.OFFICER,
                    "recipient_user": None,
                    "recipient_name": "Land Control Board / Consent Office",
                    "paid_by_side": PaymentDisbursement.PaidBy.SELLER,
                    "amount": self.lcb_fee_amount,
                    "release_trigger": "Release after the consent pack is uploaded and approved.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="lcb_consent", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "lcb_consent",
                    "notes": "Statutory consent-processing cost for agricultural lease deals.",
                },
                {
                    "code": "soil_baseline_fee",
                    "recipient_role": PaymentDisbursement.RecipientRole.OFFICER,
                    "recipient_user": None,
                    "recipient_name": "Extension Officer / Soil Professional",
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.soil_baseline_fee_amount,
                    "release_trigger": "Release after the soil baseline or entry-condition report is uploaded.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="soil_health_baseline", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "soil_health_baseline",
                    "notes": "Professional baseline report paid through the platform.",
                },
                {
                    "code": "platform_lease_fee",
                    "recipient_role": PaymentDisbursement.RecipientRole.PLATFORM,
                    "recipient_user": None,
                    "recipient_name": "AgriPlot",
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.platform_fee_amount,
                    "release_trigger": "Earned after the lease handover is complete and the lease goes live.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="handover", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.READY,
                    "stage_code": "handover",
                    "notes": "Platform lease administration fee.",
                },
                {
                    "code": "agent_commission",
                    "recipient_role": PaymentDisbursement.RecipientRole.AGENT,
                    "recipient_user": self.plot.agent.user if self.plot and self.plot.agent_id else None,
                    "recipient_name": (
                        self.plot.agent.user.get_full_name() or self.plot.agent.user.username
                        if self.plot and self.plot.agent_id
                        else "No agent on this deal"
                    ),
                    "paid_by_side": PaymentDisbursement.PaidBy.SELLER,
                    "amount": self.agent_commission_amount,
                    "release_trigger": "Deduct from the landlord's released lease proceeds once the lease activates.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="handover", status=PaymentClosingStep.Status.COMPLETED).exists()
                    and self.agent_commission_amount > 0
                    else PaymentDisbursement.Status.PLANNED,
                    "stage_code": "handover",
                    "notes": "Agent commission on lease proceeds.",
                },
                {
                    "code": "landlord_net_payout",
                    "recipient_role": PaymentDisbursement.RecipientRole.SELLER,
                    "recipient_user": self.seller,
                    "recipient_name": self.counterparty_label,
                    "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                    "amount": self.seller_total_payout_amount,
                    "release_trigger": "Release after agreement, consent, and handover are all complete.",
                    "status": PaymentDisbursement.Status.RELEASED
                    if self.closing_steps.filter(code="handover", status=PaymentClosingStep.Status.COMPLETED).exists()
                    else PaymentDisbursement.Status.HELD,
                    "stage_code": "handover",
                    "notes": "Net landlord payout after AgriPlot and agent deductions.",
                },
            ]

        for template in templates:
            disbursement, _ = PaymentDisbursement.objects.get_or_create(
                payment=self,
                code=template["code"],
                defaults=template,
            )
            update_fields = []
            for field in [
                "recipient_role",
                "recipient_user",
                "recipient_name",
                "paid_by_side",
                "amount",
                "release_trigger",
                "status",
                "stage_code",
                "notes",
            ]:
                if getattr(disbursement, field) != template[field]:
                    setattr(disbursement, field, template[field])
                    update_fields.append(field)
            issued_at = disbursement.released_at
            if template["status"] == PaymentDisbursement.Status.RELEASED and not disbursement.released_at:
                issued_at = timezone.now()
            if template["status"] != PaymentDisbursement.Status.RELEASED:
                issued_at = None
            if disbursement.released_at != issued_at:
                disbursement.released_at = issued_at
                update_fields.append("released_at")
            if update_fields:
                update_fields.append("updated_at")
                disbursement.save(update_fields=update_fields)

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
        self.ensure_transaction_artifacts()
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
            if self.lease_currently_active:
                return "Lease active"
            if self.lease_ready_for_use:
                return "Approved - awaiting start date"
            if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                return "Lease being secured"
            if self.status == self.Status.RELEASED:
                return "Lease approved"
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
            if self.lease_currently_active:
                if self.plot and self.plot.listing_type == "both":
                    return "The lease is active on AgriPlot and the land remains available for sale subject to the active tenancy terms."
                return "The lease is active on AgriPlot for the approved period."
            if self.lease_ready_for_use:
                return (
                    f"All lease approvals are complete and the tenant may occupy the land from "
                    f"{self.lease_start_date:%b %d, %Y} until {self.lease_end_date:%b %d, %Y}."
                )
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
    def lease_all_steps_completed(self):
        if self.transaction_type != self.TransactionType.LEASE or not self.closing_steps.exists():
            return False
        return not self.closing_steps.exclude(status=PaymentClosingStep.Status.COMPLETED).exists()

    @property
    def lease_use_window_open(self):
        if self.transaction_type != self.TransactionType.LEASE or not self.lease_start_date or not self.lease_end_date:
            return False
        today = timezone.localdate()
        return self.lease_start_date <= today <= self.lease_end_date

    @property
    def lease_ready_for_use(self):
        active_statuses = {
            self.Status.PAID,
            self.Status.IN_ESCROW,
            self.Status.PARTIALLY_RELEASED,
            self.Status.RELEASED,
        }
        if self.transaction_type != self.TransactionType.LEASE:
            return False
        return self.status in active_statuses and self.lease_all_steps_completed

    @property
    def lease_currently_active(self):
        return self.lease_ready_for_use and self.lease_use_window_open

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
                "title": "LCB & Family Consents",
                "status": grouped_status(["lcb_consent"]),
                "summary": "Capture Land Control Board approval and any spousal or family consents before the lease goes live.",
            },
            {
                "title": "Lease Agreement",
                "status": grouped_status(["agreement"]),
                "summary": "Agree the lease terms, notice rules, good husbandry clause, and subject-to-sale rules where applicable.",
            },
            {
                "title": "Payment & Security",
                "status": grouped_status(["payment_security"]),
                "summary": "Confirm the agreed security deposit or rent commitment through the AgriPlot escrow workflow.",
            },
            {
                "title": "Registry & Soil Baseline",
                "status": grouped_status(["lease_registration", "soil_health_baseline"]),
                "summary": "Protect long leases at the registry where needed and set the soil or land condition baseline before possession.",
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
            return "A plain-language view of the lease journey from application to consent, escrow security, handover, and renewal or exit. The detailed legal tracker stays below."
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
                    "title": "Secure LCB Approval",
                    "caption": "Record Land Control Board and family approvals before the lease goes live.",
                    "icon": "06",
                    "status": self._dashboard_status_for_codes(["lcb_consent"]),
                },
                {
                    "sequence": "07",
                    "title": "Sign the Lease Agreement",
                    "caption": "Upload the executed lease agreement and supporting proof.",
                    "icon": "07",
                    "status": self._dashboard_status_for_codes(["agreement"]),
                },
                {
                    "sequence": "08",
                    "title": "Clear the Lease Security",
                    "caption": "Complete the rent security or deposit commitment.",
                    "icon": "08",
                    "status": self._dashboard_status_for_codes(["payment_security"]),
                },
                {
                    "sequence": "09",
                    "title": "Protect the Lease Record",
                    "caption": "Register long leases and lock the baseline soil condition where needed.",
                    "icon": "09",
                    "status": self._dashboard_status_for_codes(["lease_registration", "soil_health_baseline"]),
                },
                {
                    "sequence": "10",
                    "title": "Get Your Handover",
                    "caption": "Record possession, boundaries, and activation of the lease.",
                    "icon": "10",
                    "status": self._dashboard_status_for_codes(["handover"]),
                },
                {
                    "sequence": "11",
                    "title": "Use the Land",
                    "caption": "The lease is active and the property is ready for use.",
                    "icon": "11",
                    "status": "completed" if self.lease_currently_active else "pending",
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

        if self.transaction_type == self.TransactionType.LEASE:
            lease_payment_active_statuses = {
                self.Status.PAID,
                self.Status.IN_ESCROW,
                self.Status.PARTIALLY_RELEASED,
                self.Status.RELEASED,
            }

            if self.lease_currently_active:
                self.plot.market_status = "leased"
                self.plot.lease_start_date = self.lease_start_date
                self.plot.lease_end_date = self.lease_end_date
                if self.plot.listing_type == "both":
                    self.plot.availability_notes = (
                        f"Lease activated via payment {self.internal_reference}. "
                        "This land remains on the market for sale subject to the active tenancy and notice terms."
                    )
                else:
                    self.plot.availability_notes = (
                        f"Lease activated via payment {self.internal_reference} after handover completion."
                    )
            elif self.lease_ready_for_use:
                self.plot.market_status = "reserved"
                self.plot.lease_start_date = self.lease_start_date
                self.plot.lease_end_date = self.lease_end_date
                self.plot.availability_notes = (
                    f"Lease approved via payment {self.internal_reference}. "
                    f"Tenant occupation may begin on {self.lease_start_date:%b %d, %Y} and ends on {self.lease_end_date:%b %d, %Y}."
                )
            elif self.status in lease_payment_active_statuses:
                self.plot.market_status = "reserved"
                self.plot.lease_start_date = self.lease_start_date
                self.plot.lease_end_date = self.lease_end_date
                self.plot.availability_notes = (
                    f"Lease in progress via payment {self.internal_reference}. Awaiting final handover completion."
                )
            elif self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                self.plot.market_status = "available"
                self.plot.lease_start_date = None
                self.plot.lease_end_date = None
                self.plot.availability_notes = (
                    f"Lease transaction {self.internal_reference} closed without activation."
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
            if self.buyer_id:
                LeaseWaitlistEntry.objects.filter(
                    plot=self.plot,
                    user_id=self.buyer_id,
                ).exclude(status=LeaseWaitlistEntry.Status.CONVERTED).update(
                    status=LeaseWaitlistEntry.Status.CONVERTED,
                    last_notified_at=timezone.now(),
                    updated_at=timezone.now(),
                )
            LeaseWaitlistEntry.objects.filter(
                plot=self.plot,
                status__in=[
                    LeaseWaitlistEntry.Status.WAITING,
                    LeaseWaitlistEntry.Status.CONTACTED,
                    LeaseWaitlistEntry.Status.CONFIRMED,
                ],
            ).exclude(user_id=self.buyer_id).update(
                desired_start_date=self.lease_end_date,
                updated_at=timezone.now(),
            )

    @property
    def lease_duration_days(self):
        if self.transaction_type != self.TransactionType.LEASE or not self.lease_start_date or not self.lease_end_date:
            return 0
        return (self.lease_end_date - self.lease_start_date).days

    @property
    def requires_registry_protection(self):
        return self.transaction_type == self.TransactionType.LEASE and self.lease_duration_days > 730

    @property
    def vacation_notice_date(self):
        if self.transaction_type != self.TransactionType.LEASE or not self.lease_end_date:
            return None
        return self.lease_end_date - timedelta(days=self.notice_period_days)

    @property
    def public_lease_summary(self):
        if self.transaction_type != self.TransactionType.LEASE or not self.lease_start_date or not self.lease_end_date:
            return ""
        summary = (
            f"Occupied from {self.lease_start_date:%b %d, %Y} to {self.lease_end_date:%b %d, %Y}. "
            f"Vacation notice window starts on {self.vacation_notice_date:%b %d, %Y}."
        )
        if self.subject_to_sale:
            summary += " This lease is subject to sale, so a buyer may inherit the tenancy or trigger the contractual notice process."
        return summary

    @property
    def generated_lease_agreement_terms(self):
        if self.transaction_type != self.TransactionType.LEASE or not self.plot:
            return []

        terms = [
            f"Parties: tenant {self.buyer.get_full_name() or self.buyer.username if self.buyer else 'to be confirmed'} and landlord {self.counterparty_label}.",
            f"Premises: {self.plot.title} in {self.plot.location}.",
            f"Term: {self.lease_start_date:%b %d, %Y} to {self.lease_end_date:%b %d, %Y}.",
            f"Intended use: {self.intended_use or 'Agricultural use as agreed by the parties'}.",
            f"Security deposit: KES {self.lease_security_deposit or 0:,.2f}.",
            f"Vacation notice: {self.notice_period_days} days before the lease end date.",
        ]
        if self.good_husbandry_required:
            terms.append(
                "Good husbandry: the tenant must conserve the soil, avoid waste, and return the land in the same or better productive condition."
            )
        if self.soil_exit_test_required:
            terms.append(
                "Soil exit test: the tenant must cooperate with the exit soil and land-condition inspection before final handover."
            )
        if self.subject_to_sale:
            terms.append(
                "Subject to sale: the land remains on the market for sale, and any buyer must either honour this lease or follow the agreed notice and attornment process."
            )
        if self.requires_registry_protection:
            terms.append(
                "Registry protection: this lease should be protected through the Lands Registry because the agreed term exceeds two years."
            )
        return terms

    @property
    def generated_lease_agreement_text(self):
        if self.transaction_type != self.TransactionType.LEASE:
            return ""
        return "\n".join(f"{index}. {term}" for index, term in enumerate(self.generated_lease_agreement_terms, start=1))


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


class PaymentCertificate(models.Model):
    class Audience(models.TextChoices):
        BUYER = "buyer", "Buyer"
        SELLER = "seller", "Seller / Landlord"
        BOTH = "both", "Buyer & Seller"
        INTERNAL = "internal", "Internal"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        ISSUED = "issued", "Issued"

    payment = models.ForeignKey(
        PaymentRequest, on_delete=models.CASCADE, related_name="certificates"
    )
    code = models.CharField(max_length=60)
    title = models.CharField(max_length=180)
    audience = models.CharField(max_length=20, choices=Audience.choices, default=Audience.BOTH)
    summary = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    issued_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        unique_together = [("payment", "code")]

    def __str__(self):
        return f"{self.payment.internal_reference} - {self.title}"


class PaymentDisbursement(models.Model):
    class RecipientRole(models.TextChoices):
        SELLER = "seller", "Seller / Landlord"
        AGENT = "agent", "Agent"
        PLATFORM = "platform", "AgriPlot"
        OFFICER = "officer", "Officer / Professional"
        GOVERNMENT = "government", "Government / Registry / Tax"

    class PaidBy(models.TextChoices):
        BUYER = "buyer", "Buyer / Tenant"
        SELLER = "seller", "Seller / Landlord"
        PLATFORM = "platform", "Platform"
        SHARED = "shared", "Shared / As agreed"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        HELD = "held", "Held in Escrow"
        READY = "ready", "Ready for Release"
        RELEASED = "released", "Released"

    payment = models.ForeignKey(
        PaymentRequest, on_delete=models.CASCADE, related_name="disbursements"
    )
    code = models.CharField(max_length=60)
    recipient_role = models.CharField(max_length=20, choices=RecipientRole.choices)
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_disbursements",
    )
    recipient_name = models.CharField(max_length=180)
    paid_by_side = models.CharField(max_length=20, choices=PaidBy.choices, default=PaidBy.BUYER)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    release_trigger = models.TextField(blank=True)
    stage_code = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        unique_together = [("payment", "code")]

    def __str__(self):
        return f"{self.payment.internal_reference} - {self.recipient_name}"


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
            "lcb_consent": "Seller / Admin",
            "agreement": "Buyer + Seller",
            "payment_security": "Buyer / Tenant",
            "lease_registration": "Admin / Lawyer",
            "soil_health_baseline": "Buyer + Seller",
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
            "lcb_consent": {
                "headline": "Secure Land Control Board and family approvals.",
                "where": "Agricultural lease deals should capture the Land Control Board consent and any necessary spousal approvals before occupation begins.",
                "document": "LCB consent and family approval pack",
                "platform_role": "AgriPlot keeps the statutory consent milestone visible so the tenancy is not activated prematurely.",
                "cta_label": "Track LCB & Consent Pack",
                "support_label": "Do not hand over possession on agricultural land until the required approvals are uploaded.",
            },
            "agreement": {
                "headline": "Review and sign the lease agreement.",
                "where": "Go through the lease terms carefully with the other side before signing, including good husbandry duties, exit terms, and any subject-to-sale clause.",
                "document": "Signed Lease Agreement",
                "platform_role": "AgriPlot tracks the signed agreement as the lease moves toward handover.",
                "cta_label": "Review Lease Agreement",
                "support_label": "Check renewal terms, payment schedule, access rights, and exit conditions.",
            },
            "payment_security": {
                "headline": "Pay the security deposit into AgriPlot escrow.",
                "where": "Review the required deposit amount, confirm the refund and deduction rules, then pay through AgriPlot before occupation or handover.",
                "document": "Escrow payment confirmation",
                "platform_role": "AgriPlot records the deposit, holds it in escrow, and only unlocks handover once the payment is visible in the lease tracker.",
                "cta_label": "Pay Security Deposit",
                "support_label": "You only need to complete the payment side here. Admin and legal consents are handled in their own stages.",
            },
            "lease_registration": {
                "headline": "Protect the long lease at the registry.",
                "where": "If the lease is longer than two years, record the filing or protection evidence from the Lands Registry workflow.",
                "document": "Lease registry proof",
                "platform_role": "AgriPlot highlights when the lease is long enough to need formal registry protection.",
                "cta_label": "Track Lease Registry Step",
                "support_label": "Long agricultural leases should not rely on informal paperwork alone.",
            },
            "soil_health_baseline": {
                "headline": "Set the soil and land condition baseline.",
                "where": "Capture the starting soil condition, conservation expectations, and any restoration obligations before handover.",
                "document": "Soil baseline or entry inspection report",
                "platform_role": "AgriPlot uses the baseline to support the good husbandry clause and any exit soil test.",
                "cta_label": "Record Soil Baseline",
                "support_label": "This protects both the landlord and the tenant if the land condition is disputed later.",
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
            "lcb_consent": "Follow up on the Land Control Board process and make sure the approval pack is uploaded before handover.",
            "agreement": "Review the lease agreement carefully and sign once the terms are agreed.",
            "payment_security": (
                "Review the deposit amount, pay it through AgriPlot escrow, and wait for payment confirmation. "
                "You do not need to upload LCB, registry, or other official documents at this stage."
            ),
            "lease_registration": "If the lease is long-term, confirm the registry filing or protective entry with your advocate.",
            "soil_health_baseline": "Capture the soil and land baseline before possession so the exit condition can be measured fairly.",
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
            "lcb_consent": "Seller or admin consent upload",
            "agreement": "Both parties / admin upload",
            "payment_security": "Tenant escrow payment confirmation",
            "lease_registration": "Admin registry evidence upload",
            "soil_health_baseline": "Joint baseline upload",
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
            "payment_security": [
                "Security deposit amount confirmed",
                "Escrow payment recorded through AgriPlot",
            ],
            "lease_registration": ["Lease registry proof uploaded"],
            "soil_health_baseline": ["Baseline soil or condition report uploaded"],
        }
        return requirement_map.get(self.code, [])

    def can_mark_complete_with_current_evidence(self):
        active_payment_statuses = {
            PaymentRequest.Status.PAID,
            PaymentRequest.Status.IN_ESCROW,
            PaymentRequest.Status.PARTIALLY_RELEASED,
            PaymentRequest.Status.RELEASED,
        }
        if self.code == "due_diligence":
            return True
        if self.code == "agreement":
            if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
                return bool(self.buyer_confirmed_at and self.seller_confirmed_at)
            return bool(self.document)
        if self.code == "registration":
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
        if self.code == "payment_security":
            return any(
                related_payment.category == PaymentRequest.Category.ESCROW_DEPOSIT
                and related_payment.status in active_payment_statuses
                for related_payment in self.payment.workflow_related_payments
            )
        if self.code in {"lease_registration", "soil_health_baseline", "handover"}:
            return bool(self.document)
        if self.code == "offer":
            return bool(self.notes or self.document)
        return True

    def evidence_blocking_reason(self):
        if self.can_mark_complete_with_current_evidence():
            return ""
        if self.code == "agreement" and self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return "Both the tenant and the landlord must digitally confirm the generated lease agreement before this step can be completed."
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
        self.payment.ensure_transaction_artifacts()
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
        if any(token in label for token in ["seller", "agent", "landowner"]) and self.payment.seller:
            recipients.append(self.payment.seller)
        if any(token in label for token in ["admin", "valuer", "government", "operations", "lawyer", "registrar"]):
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


class LeaseWaitlistEntry(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting"
        CONTACTED = "contacted", "Contacted"
        CONFIRMED = "confirmed", "Confirmed"
        CONVERTED = "converted", "Converted"
        WITHDRAWN = "withdrawn", "Withdrawn"

    plot = models.ForeignKey(
        "listings.Plot",
        on_delete=models.CASCADE,
        related_name="lease_waitlist_entries",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lease_waitlist_entries",
    )
    desired_start_date = models.DateField(null=True, blank=True)
    desired_duration_months = models.PositiveIntegerField(default=12)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.WAITING)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        unique_together = [("plot", "user")]

    def __str__(self):
        return f"{self.plot_id} waitlist - {self.user_id}"

    @property
    def is_active(self):
        return self.status in {
            self.Status.WAITING,
            self.Status.CONTACTED,
            self.Status.CONFIRMED,
        }

    @classmethod
    def next_candidate_for_plot(cls, plot):
        return (
            cls.objects.filter(
                plot=plot,
                status__in=[cls.Status.CONFIRMED, cls.Status.CONTACTED, cls.Status.WAITING],
            )
            .order_by(
                models.Case(
                    models.When(status=cls.Status.CONFIRMED, then=models.Value(0)),
                    models.When(status=cls.Status.CONTACTED, then=models.Value(1)),
                    default=models.Value(2),
                    output_field=models.IntegerField(),
                ),
                "created_at",
            )
            .first()
        )

    @property
    def queue_position(self):
        queue = list(
            LeaseWaitlistEntry.objects.filter(
                plot=self.plot,
                status__in=[self.Status.WAITING, self.Status.CONTACTED, self.Status.CONFIRMED],
            ).order_by("created_at")
        )
        for index, entry in enumerate(queue, start=1):
            if entry.pk == self.pk:
                return index
        return None

    def mark_contacted(self, save=True):
        self.status = self.Status.CONTACTED
        self.last_notified_at = timezone.now()
        if save:
            self.save(update_fields=["status", "last_notified_at", "updated_at"])

    def mark_confirmed(self, save=True):
        self.status = self.Status.CONFIRMED
        self.last_notified_at = timezone.now()
        if save:
            self.save(update_fields=["status", "last_notified_at", "updated_at"])

    def mark_converted(self, save=True):
        self.status = self.Status.CONVERTED
        self.last_notified_at = timezone.now()
        if save:
            self.save(update_fields=["status", "last_notified_at", "updated_at"])

    def mark_withdrawn(self, save=True):
        self.status = self.Status.WITHDRAWN
        if save:
            self.save(update_fields=["status", "updated_at"])
