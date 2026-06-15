import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from dateutil.relativedelta import relativedelta


class PaymentRequest(models.Model):
    # Fee defaults
    DEFAULT_OFFICIAL_SEARCH_FEE = Decimal("1000.00")
    DEFAULT_SURVEY_SEARCH_FEE = Decimal("500.00")
    DEFAULT_LCB_FEE = Decimal("3000.00")
    DEFAULT_TRANSFER_FEE = Decimal("1000.00")
    DEFAULT_TITLE_FEE = Decimal("2500.00")
    DEFAULT_SOIL_BASELINE_FEE = Decimal("2500.00")
    
    # Platform fee: 1-3% based on property value (tiered)
    DEFAULT_PLATFORM_FEE_PERCENTAGE = Decimal("0.02")  # 2% default
    PLATFORM_FEE_TIERS = [
        (Decimal("0"), Decimal("0.03")),      # 0 - 1M: 3%
        (Decimal("1000000"), Decimal("0.025")), # 1M - 5M: 2.5%
        (Decimal("5000000"), Decimal("0.02")),  # 5M - 10M: 2%
        (Decimal("10000000"), Decimal("0.015")), # 10M+: 1.5%
    ]
    
    DEFAULT_AGENT_COMMISSION_RATE = Decimal("0.03")
    DEFAULT_VERIFICATION_MARKUP_RATE = Decimal("0.20")
    DEFAULT_RESERVATION_DEPOSIT_RATE = Decimal("0.05")

    class TransactionType(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        LEASE = "lease", "Lease"
        BOTH = 'both', 'Purchase & Lease'

    class Category(models.TextChoices):
        COMMITMENT_FEE = "commitment_fee", "Commitment / Verification Fee"
        RESERVATION_DEPOSIT = "reservation_deposit", "Reservation Deposit"
        AGREEMENT_DEPOSIT = "agreement_deposit", "Agreement Deposit"
        VERIFICATION_PACKAGE = "verification_package", "Verification Package"
        ESCROW_DEPOSIT = "escrow_deposit", "Escrow Deposit"
        STAMP_DUTY = "stamp_duty", "Stamp Duty (Paid to KRA)"
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

    PLOT_REQUIRED_CATEGORIES = {
        Category.RESERVATION_DEPOSIT,
        Category.AGREEMENT_DEPOSIT,
        Category.ESCROW_DEPOSIT,
        Category.COMPLETION_BALANCE,
    }

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

    # Core fields
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
    legal_transaction = models.OneToOneField(
        'transactions.Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='related_payment',
        help_text="Associated legal transaction for conveyancing"
    )
    
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="KES")
    transaction_type = models.CharField(
        max_length=20, choices=TransactionType.choices, default=TransactionType.PURCHASE
    )
    category = models.CharField(
        max_length=40, choices=Category.choices, default=Category.COMMITMENT_FEE
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
    
    # Lease-specific fields
    lease_start_date = models.DateField(null=True, blank=True)
    lease_end_date = models.DateField(null=True, blank=True)
    intended_use = models.CharField(max_length=180, blank=True)
    lease_security_deposit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notice_period_days = models.PositiveIntegerField(default=90)
    good_husbandry_required = models.BooleanField(default=True)
    soil_exit_test_required = models.BooleanField(default=True)
    subject_to_sale = models.BooleanField(default=False)
    
    # Timestamps
    due_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True, help_text="When funds were released to seller")
    reports_sent_at = models.DateTimeField(null=True, blank=True, help_text="When transaction reports were emailed")
    
    # Escrow tracking
    deposit_received_at = models.DateTimeField(null=True, blank=True)
    balance_received_at = models.DateTimeField(null=True, blank=True)
    platform_fee_deducted_at = models.DateTimeField(null=True, blank=True)
    
    # Stamp duty tracking (platform never holds, just verifies)
    stamp_duty_receipt_uploaded_at = models.DateTimeField(null=True, blank=True)
    stamp_duty_receipt_verified_at = models.DateTimeField(null=True, blank=True)
    stamp_duty_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_stamp_duty_verifications",
        help_text="Finance/Legal admin who verified KRA receipt"
    )
    
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
            lease_terms_required = bool((self.metadata or {}).get("lease_terms_required"))
            if self.lease_start_date or self.lease_end_date:
                if not self.lease_start_date:
                    raise ValidationError(
                        {"lease_start_date": "Lease start date is required when setting lease terms."}
                    )
                if not self.lease_end_date:
                    raise ValidationError(
                        {"lease_end_date": "Lease end date is required when setting lease terms."}
                    )
                if self.lease_end_date <= self.lease_start_date:
                    raise ValidationError(
                        {"lease_end_date": "Lease end date must be after the lease start date."}
                    )
            elif lease_terms_required:
                raise ValidationError(
                    {
                        "lease_start_date": "Lease start date is required for this lease checkout.",
                        "lease_end_date": "Lease end date is required for this lease checkout.",
                    }
                )
            if self.notice_period_days < 30:
                raise ValidationError(
                    {"notice_period_days": "Vacation notice should be at least 30 days."}
                )
        
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.lease_start_date or self.lease_end_date:
                raise ValidationError("Purchase transactions should not include lease dates.")
        
        if self.category in self.PLOT_REQUIRED_CATEGORIES and not self.plot:
            raise ValidationError(
                {"plot": "A plot is required for this payment category."}
            )
        
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
                                f"{self._format_lease_date(self.plot.lease_start_date)} to "
                                f"{self._format_lease_date(self.plot.lease_end_date)}."
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
        if not self.seller:
            self.seller = self._resolve_counterparty_user()
        super().save(*args, **kwargs)

    def _resolve_counterparty_user(self):
        if self.seller:
            return self.seller
        if self.plot:
            if self.plot.landowner_id and self.plot.landowner.user_id:
                return self.plot.landowner.user
            if self.plot.agent_id and self.plot.agent.user_id:
                return self.plot.agent.user
        return None

    def _money(self, value):
        if value in (None, ""):
            return Decimal("0.00")
        if isinstance(value, Decimal):
            return value.quantize(Decimal("0.01"))
        return Decimal(str(value)).quantize(Decimal("0.01"))

    def _money_display(self, value):
        amount = self._money(value)
        return f"KSh {amount:,.2f}"

    def _format_lease_date(self, value, fallback="to be confirmed"):
        if not value:
            return fallback
        return value.strftime("%b %d, %Y")

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
    def workflow_total_paid_amount(self):
        paid_statuses = {
            self.Status.PAID,
            self.Status.IN_ESCROW,
            self.Status.PARTIALLY_RELEASED,
            self.Status.RELEASED,
        }
        return sum(
            (payment.amount for payment in self.workflow_related_payments if payment.status in paid_statuses),
            start=Decimal("0.00"),
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

    def calculate_platform_fee_percentage(self):
        """Calculate platform fee percentage based on property value (tiered)"""
        value = self.sale_price_value
        for threshold, rate in reversed(self.PLATFORM_FEE_TIERS):
            if value >= threshold:
                return rate
        return self.DEFAULT_PLATFORM_FEE_PERCENTAGE

    @property
    def platform_fee_percentage(self):
        return self._metadata_rate("platform_fee_percentage", self.calculate_platform_fee_percentage())

    @property
    def lease_contract_value(self):
        if self.transaction_type != self.TransactionType.LEASE:
            return Decimal("0.00")
        if self.lease_start_date and self.lease_end_date:
            delta = relativedelta(self.lease_end_date, self.lease_start_date)
            duration_months = max(1, delta.years * 12 + delta.months + (1 if delta.days > 0 else 0))
        else:
            duration_months = 12
        if self.plot and self.plot.lease_price_monthly:
            return self._money(self.plot.lease_price_monthly) * duration_months
        if self.plot and self.plot.lease_price_yearly:
            yearly = self._money(self.plot.lease_price_yearly)
            return (yearly / Decimal("12.00") * Decimal(str(duration_months))).quantize(Decimal("0.01"))
        return self._money(self.amount)

    @property
    def lease_base_amount(self):
        if self.plot and self.plot.lease_price_monthly:
            return self._money(self.plot.lease_price_monthly)
        if self.plot and self.plot.lease_price_yearly:
            return (self._money(self.plot.lease_price_yearly) / Decimal("12.00")).quantize(Decimal("0.01"))
        return None

    @property
    def agent_commission_rate(self):
        return self._metadata_rate("agent_commission_rate", self.DEFAULT_AGENT_COMMISSION_RATE)

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
        """Estimated stamp duty - actual paid to KRA directly"""
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
        lease_base = self.lease_base_amount
        return lease_base if lease_base is not None else self._money(self.amount)

    @property
    def completion_balance_amount(self):
        related = self._related_payment_for_category(self.Category.COMPLETION_BALANCE)
        if related:
            return self._money(related.amount)
        if self.transaction_type == self.TransactionType.PURCHASE:
            return max(self.sale_price_value - self.agreement_deposit_amount, Decimal("0.00"))
        lease_base = self.lease_base_amount
        return lease_base if lease_base is not None else self._money(self.amount)

    @property
    def platform_fee_amount(self):
        base = self.sale_price_value if self.transaction_type == self.TransactionType.PURCHASE else self.lease_contract_value
        return (base * self.platform_fee_percentage).quantize(Decimal("0.01"))

    @property
    def seller_net_amount(self):
        """Amount seller receives after platform fee deduction"""
        return max(self.amount - self.platform_fee_amount, Decimal("0.00"))

    @property
    def seller_total_payout_amount(self):
        """Total to pay seller after all deductions (platform fee already included)"""
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
    def verification_markup_amount(self):
        base = self.official_search_fee + self.survey_search_fee
        return (base * self.verification_markup_rate).quantize(Decimal("0.01"))

    @property
    def due_diligence_pack_amount(self):
        base = self.official_search_fee + self.survey_search_fee
        if self.plot and self.plot.land_type == "agricultural":
            base += self.soil_baseline_fee_amount
        return (base + self.verification_markup_amount).quantize(Decimal("0.01"))

    @property
    def commitment_fee_amount(self):
        if self.transaction_type in {self.TransactionType.PURCHASE, self.TransactionType.LEASE}:
            return self.due_diligence_pack_amount
        return self._money(self.amount)

    @property
    def verification_package_amount(self):
        return self.due_diligence_pack_amount

    @property
    def reservation_deposit_amount(self):
        if self.transaction_type == self.TransactionType.LEASE:
            lease_base = self.lease_base_amount
            return lease_base if lease_base is not None else self._money(self.amount)
        return (self.sale_price_value * self.DEFAULT_RESERVATION_DEPOSIT_RATE).quantize(Decimal("0.01"))

    @classmethod
    def calculate_stage_amount(cls, plot, transaction_type, category):
        if category in cls.PLOT_REQUIRED_CATEGORIES and not plot:
            return None
        if category == cls.Category.COMMITMENT_FEE:
            return cls._calculate_due_diligence_pack_amount(plot)
        if category == cls.Category.VERIFICATION_PACKAGE:
            return cls._calculate_due_diligence_pack_amount(plot)
        if category == cls.Category.RESERVATION_DEPOSIT:
            if transaction_type == cls.TransactionType.PURCHASE:
                sale_price = cls._sale_price_value(plot)
                if sale_price is None:
                    return None
                return (sale_price * cls.DEFAULT_RESERVATION_DEPOSIT_RATE).quantize(Decimal("0.01"))
            return cls._lease_base_amount(plot)
        if category == cls.Category.AGREEMENT_DEPOSIT:
            if transaction_type == cls.TransactionType.PURCHASE:
                sale_price = cls._sale_price_value(plot)
                if sale_price is None:
                    return None
                return (sale_price * Decimal("0.10")).quantize(Decimal("0.01"))
            return cls._lease_base_amount(plot)
        if category == cls.Category.ESCROW_DEPOSIT:
            if transaction_type == cls.TransactionType.PURCHASE:
                sale_price = cls._sale_price_value(plot)
                if sale_price is None:
                    return None
                return sale_price
            return cls._lease_base_amount(plot)
        if category == cls.Category.STAMP_DUTY:
            # Stamp duty is paid to KRA directly, not collected by platform
            return None
        if category == cls.Category.COMPLETION_BALANCE:
            if transaction_type == cls.TransactionType.PURCHASE:
                sale_price = cls._sale_price_value(plot)
                if sale_price is None:
                    return None
                agreement_deposit = (sale_price * Decimal("0.10")).quantize(Decimal("0.01"))
                return max(sale_price - agreement_deposit, Decimal("0.00"))
            return cls._lease_base_amount(plot)
        if category == cls.Category.SERVICE_FEE:
            return None
        return None

    @classmethod
    def _sale_price_value(cls, plot):
        if not plot:
            return None
        raw_price = getattr(plot, "sale_price", None) or getattr(plot, "price", None)
        if raw_price in {None, ""}:
            return None
        return cls._money_static(raw_price)

    @classmethod
    def _lease_base_amount(cls, plot):
        if not plot:
            return None
        if plot.lease_price_monthly:
            return cls.normalize_amount(plot.lease_price_monthly)
        if plot.lease_price_yearly:
            return cls.normalize_amount(Decimal(str(plot.lease_price_yearly)) / Decimal("12"))
        return None

    @classmethod
    def normalize_amount(cls, value):
        from decimal import Decimal, ROUND_HALF_UP
        if value is None:
            return Decimal('0.00')
        return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    def _money_static(cls, value):
        if value in (None, ""):
            return Decimal("0.00")
        if isinstance(value, Decimal):
            return value.quantize(Decimal("0.01"))
        return Decimal(str(value)).quantize(Decimal("0.01"))

    @classmethod
    def _calculate_due_diligence_pack_amount(cls, plot):
        if not plot:
            return None
        base = cls._money_static(cls.DEFAULT_OFFICIAL_SEARCH_FEE) + cls._money_static(cls.DEFAULT_SURVEY_SEARCH_FEE)
        if plot.land_type == "agricultural":
            base += cls._money_static(cls.DEFAULT_SOIL_BASELINE_FEE)
        markup = (base * cls.DEFAULT_VERIFICATION_MARKUP_RATE).quantize(Decimal("0.01"))
        return (base + markup).quantize(Decimal("0.01"))

    def ensure_transaction_artifacts(self):
        anchor = self.workflow_anchor_payment
        if anchor.pk != self.pk:
            return anchor.ensure_transaction_artifacts()
        anchor.ensure_closing_steps()
        anchor._ensure_default_certificates()
        anchor._ensure_default_disbursements()

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

    def _ensure_default_certificates(self):
        from .models import PaymentCertificate
        
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
        from .models import PaymentDisbursement
        
        if self.transaction_type == self.TransactionType.PURCHASE:
            templates = self._get_purchase_disbursement_templates()
        else:
            templates = self._get_lease_disbursement_templates()

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

    def _get_purchase_disbursement_templates(self):
        """Disbursement templates for purchase with platform escrow"""
        is_registration_complete = self.purchase_registration_complete
        is_agreement_complete = self.closing_steps.filter(code="agreement", status=PaymentClosingStep.Status.COMPLETED).exists()
        is_due_diligence_complete = self.closing_steps.filter(code="due_diligence", status=PaymentClosingStep.Status.COMPLETED).exists()
        is_stamp_duty_complete = self.closing_steps.filter(code="stamp_duty", status=PaymentClosingStep.Status.COMPLETED).exists()
        
        return [
            {
                "code": "deposit_held",
                "recipient_role": PaymentDisbursement.RecipientRole.PLATFORM,
                "recipient_user": None,
                "recipient_name": "AgriPlot Escrow",
                "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                "amount": self.agreement_deposit_amount,
                "release_trigger": "Held in escrow until new title deed is verified",
                "status": PaymentDisbursement.Status.HELD if not is_registration_complete else PaymentDisbursement.Status.RELEASED,
                "stage_code": "agreement",
                "notes": "10% deposit held in platform escrow account",
            },
            {
                "code": "balance_held",
                "recipient_role": PaymentDisbursement.RecipientRole.PLATFORM,
                "recipient_user": None,
                "recipient_name": "AgriPlot Escrow",
                "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                "amount": self.completion_balance_amount,
                "release_trigger": "Held in escrow until new title deed is verified",
                "status": PaymentDisbursement.Status.HELD if not is_registration_complete else PaymentDisbursement.Status.RELEASED,
                "stage_code": "completion_docs",
                "notes": "90% balance held in platform escrow account",
            },
            {
                "code": "platform_fee",
                "recipient_role": PaymentDisbursement.RecipientRole.PLATFORM,
                "recipient_user": None,
                "recipient_name": "AgriPlot",
                "paid_by_side": PaymentDisbursement.PaidBy.SELLER,
                "amount": self.platform_fee_amount,
                "release_trigger": "Deducted from escrow before seller disbursement",
                "status": PaymentDisbursement.Status.READY if is_registration_complete else PaymentDisbursement.Status.PLANNED,
                "stage_code": "disbursement",
                "notes": f"Platform fee ({self.platform_fee_percentage * 100}%) deducted from seller proceeds",
            },
            {
                "code": "seller_disbursement",
                "recipient_role": PaymentDisbursement.RecipientRole.SELLER,
                "recipient_user": self.seller,
                "recipient_name": self.counterparty_label,
                "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                "amount": self.seller_net_amount,
                "release_trigger": "Released to seller ONLY after new title deed is verified",
                "status": PaymentDisbursement.Status.READY if is_registration_complete else PaymentDisbursement.Status.HELD,
                "stage_code": "disbursement",
                "notes": f"Final seller payout after {self.platform_fee_percentage * 100}% platform fee deduction",
            },
            {
                "code": "official_search_fee",
                "recipient_role": PaymentDisbursement.RecipientRole.GOVERNMENT,
                "recipient_user": None,
                "recipient_name": "eCitizen / Lands Registry",
                "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                "amount": self.official_search_fee,
                "release_trigger": "Paid directly by buyer via eCitizen",
                "status": PaymentDisbursement.Status.RELEASED if is_due_diligence_complete else PaymentDisbursement.Status.PLANNED,
                "stage_code": "due_diligence",
                "notes": "Official search fee - paid directly to government (platform does not hold)",
            },
            {
                "code": "stamp_duty",
                "recipient_role": PaymentDisbursement.RecipientRole.GOVERNMENT,
                "recipient_user": None,
                "recipient_name": "KRA (iTax)",
                "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                "amount": Decimal("0.00"),
                "release_trigger": "Paid directly by buyer to KRA via iTax",
                "status": PaymentDisbursement.Status.RELEASED if is_stamp_duty_complete else PaymentDisbursement.Status.PLANNED,
                "stage_code": "stamp_duty",
                "notes": "Stamp duty - buyer pays KRA directly. Platform only verifies receipt.",
            },
        ]

    def _get_lease_disbursement_templates(self):
        """Disbursement templates for lease with platform escrow"""
        is_handover_complete = self.closing_steps.filter(code="handover", status=PaymentClosingStep.Status.COMPLETED).exists()
        
        return [
            {
                "code": "lease_deposit_held",
                "recipient_role": PaymentDisbursement.RecipientRole.PLATFORM,
                "recipient_user": None,
                "recipient_name": "AgriPlot Escrow",
                "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                "amount": self.lease_security_deposit or self.amount,
                "release_trigger": "Held in escrow until handover complete",
                "status": PaymentDisbursement.Status.HELD if not is_handover_complete else PaymentDisbursement.Status.RELEASED,
                "stage_code": "payment_security",
                "notes": "Lease security deposit held in platform escrow",
            },
            {
                "code": "platform_lease_fee",
                "recipient_role": PaymentDisbursement.RecipientRole.PLATFORM,
                "recipient_user": None,
                "recipient_name": "AgriPlot",
                "paid_by_side": PaymentDisbursement.PaidBy.SELLER,
                "amount": self.platform_fee_amount,
                "release_trigger": "Deducted from escrow before landlord disbursement",
                "status": PaymentDisbursement.Status.READY if is_handover_complete else PaymentDisbursement.Status.PLANNED,
                "stage_code": "handover",
                "notes": f"Platform fee ({self.platform_fee_percentage * 100}%) deducted from landlord proceeds",
            },
            {
                "code": "landlord_disbursement",
                "recipient_role": PaymentDisbursement.RecipientRole.SELLER,
                "recipient_user": self.seller,
                "recipient_name": self.counterparty_label,
                "paid_by_side": PaymentDisbursement.PaidBy.BUYER,
                "amount": self.seller_net_amount,
                "release_trigger": "Released to landlord ONLY after handover complete",
                "status": PaymentDisbursement.Status.READY if is_handover_complete else PaymentDisbursement.Status.HELD,
                "stage_code": "handover",
                "notes": f"Landlord payout after {self.platform_fee_percentage * 100}% platform fee deduction",
            },
        ]

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
        counterparty_user = self._resolve_counterparty_user()
        if counterparty_user:
            return counterparty_user.get_full_name() or counterparty_user.username
        if self.plot and self.plot.registry_owner_name:
            return self.plot.registry_owner_name
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

    # Closing Steps Templates - Updated for platform escrow model with clear milestones and document requirements
    PURCHASE_LEGAL_STEPS = [
        (
            "due_diligence",
            "Due Diligence & Searches",
            "Official search, survey, and diligence pack",
            "Review the official search, survey, and supporting diligence records before moving the sale forward.",
        ),
        (
            "offer",
            "Letter of Offer",
            "Letter of offer / reservation terms",
            "Issue and upload the formal letter of offer before the full sale agreement is drafted.",
        ),
        (
            "agreement",
            "Sale Agreement & 10% Deposit",
            "Executed sale agreement",
            "Upload the signed sale agreement. Buyer pays 10% deposit to platform escrow.",
        ),
        (
            "lcb_consent",
            "Land Control Board & Consents",
            "Consent letters and clearance pack",
            "Capture Land Control Board approval or the equivalent seller clearances and supporting consents required for transfer.",
        ),
        (
            "stamp_duty",
            "Stamp Duty (Pay KRA Directly)",
            "KRA stamp duty receipt",
            "Pay stamp duty directly to KRA via iTax and upload the receipt for verification.",
        ),
        (
            "completion_docs",
            "Completion Documents & 90% Balance",
            "Completion document checklist",
            "Buyer pays 90% balance to escrow. Seller provides original title, signed transfer forms, and clearances.",
        ),
        (
            "registration",
            "Title Registration",
            "Fresh registry proof / new title",
            "Upload the new title deed issued in buyer's name. This triggers automatic fund disbursement.",
        ),
        (
            "disbursement",
            "Fund Disbursement to Seller",
            "Disbursement confirmation",
            "Platform deducts fee and automatically disburses funds to seller after title verification.",
        ),
        (
            "reports",
            "Transaction Reports",
            "Final transaction reports",
            "Platform emails comprehensive transaction reports to both parties.",
        ),
        (
            "handover",
            "Possession & Handover",
            "Handover certificate",
            "Confirm physical possession and handover of the property.",
        ),
    ]

    LEASE_LEGAL_STEPS_AGRICULTURAL = [
        ("offer", "Letter of Offer", "Issue and accept lease offer."),
        ("lcb_consent", "Land Control Board & Family Consents", "Obtain Land Control Board consent and any required family/spousal consents."),
        ("agreement", "Lease Agreement & Deposit", "Prepare and execute lease agreement. Tenant pays deposit to escrow."),
        ("registration", "Registration", "Register lease where applicable."),
        ("disbursement", "Fund Disbursement", "Platform deducts fee and disburses to landlord."),
        ("handover", "Possession & Handover", "Grant possession and complete handover."),
    ]
    
    LEASE_LEGAL_STEPS_LEASEHOLD_NON_AG = [
        ("offer", "Letter of Offer", "Issue and accept lease offer."),
        ("consents_clearances", "Head Lessor & Spousal Consents", "Sublease consent from head lessor, county government, NLC or other superior interest holder where applicable. Obtain spousal consent if matrimonial property."),
        ("agreement", "Lease Agreement & Deposit", "Prepare and execute lease agreement. Tenant pays deposit to escrow."),
        ("registration", "Registration", "Register lease where applicable."),
        ("disbursement", "Fund Disbursement", "Platform deducts fee and disburses to landlord."),
        ("handover", "Possession & Handover", "Grant possession and complete handover."),
    ]
    
    LEASE_LEGAL_STEPS_FREEHOLD_NON_AG = [
        ("offer", "Letter of Offer", "Issue and accept lease offer."),
        ("consents_clearances", "Spousal & Estate Consents", "Record spousal consent under the Matrimonial Property Act where applicable, or estate approvals if the owner is deceased. Mark N/A if not required."),
        ("agreement", "Lease Agreement & Deposit", "Prepare and execute lease agreement. Tenant pays deposit to escrow."),
        ("registration", "Registration", "Register lease where applicable."),
        ("disbursement", "Fund Disbursement", "Platform deducts fee and disburses to landlord."),
        ("handover", "Possession & Handover", "Grant possession and complete handover."),
    ]

    @classmethod
    def closing_step_templates(cls, transaction_type, plot=None):
        if transaction_type == cls.TransactionType.PURCHASE:
            return cls.PURCHASE_LEGAL_STEPS
        if transaction_type == cls.TransactionType.LEASE:
            if plot and getattr(plot, "land_type", "") == "agricultural":
                return cls.LEASE_LEGAL_STEPS_AGRICULTURAL
            if plot and getattr(plot, "ownership_type", "") == "leasehold":
                return cls.LEASE_LEGAL_STEPS_LEASEHOLD_NON_AG
            return cls.LEASE_LEGAL_STEPS_FREEHOLD_NON_AG
        return []

    def add_event(self, event_type, message, actor=None):
        return PaymentEvent.objects.create(
            payment=self,
            event_type=event_type,
            actor=actor,
            message=message,
        )

    def _release_blocking_reason(self):
        """Check if funds can be released to seller"""
        if self.transaction_type == self.TransactionType.PURCHASE:
            # Must have new title deed verified
            new_title_verified = self.closing_steps.filter(
                code="registration",
                status=PaymentClosingStep.Status.COMPLETED
            ).exists()
            
            if not new_title_verified:
                return "Funds cannot be released yet. New title deed must be issued and verified first."
            
            # Must have stamp duty receipt verified (KRA payment)
            stamp_duty_verified = self.closing_steps.filter(
                code="stamp_duty",
                status=PaymentClosingStep.Status.COMPLETED
            ).exists()
            
            if not stamp_duty_verified:
                return "Stamp duty payment to KRA must be verified before fund release."
        
        if self.transaction_type == self.TransactionType.LEASE:
            handover_complete = self.closing_steps.filter(
                code="handover",
                status=PaymentClosingStep.Status.COMPLETED
            ).exists()
            
            if not handover_complete:
                return "Funds cannot be released yet. Lease handover must be completed first."
        
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
            "disburse_to_seller": (self.Status.RELEASED, "Funds disbursed to seller after registration."),
        }
        
        if action not in transition_map:
            raise ValidationError(f"Unsupported payment action: {action}")
        if action not in self.allowed_transitions:
            raise ValidationError(
                f"Action '{action}' is not allowed while payment is in '{self.status}'."
            )
        
        if action in ["release", "disburse_to_seller"]:
            blocking_reason = self._release_blocking_reason()
            if blocking_reason:
                raise ValidationError(blocking_reason)

        new_status, message = transition_map[action]
        self.status = new_status
        now = timezone.now()

        if action == "mark_paid" and not self.paid_at:
            self.paid_at = now
        
        if action in ["release", "disburse_to_seller"]:
            self.released_at = now
            self.disbursed_at = now
            
            # Mark platform fee as deducted
            self.platform_fee_deducted_at = now
            
            # Auto-trigger report generation after disbursement
            if not self.reports_sent_at:
                self._send_transaction_reports()

        self.save(update_fields=["status", "paid_at", "released_at", "disbursed_at", 
                                  "platform_fee_deducted_at", "reports_sent_at", "updated_at"])
        self.sync_plot_market_state()
        self.ensure_transaction_artifacts()

        self.add_event(action, message, actor=actor)

    def _send_transaction_reports(self):
        """Internal method to trigger report generation and email"""
        from notifications.notification_service import NotificationService
        
        self.reports_sent_at = timezone.now()
        self.save(update_fields=["reports_sent_at", "updated_at"])
        
        # Queue report generation and email
        NotificationService.send_transaction_completion_reports(self)

    @property
    def allowed_transitions(self):
        return self.TRANSITION_RULES.get(self.status, set())

    def ensure_closing_steps(self):
        from .models import PaymentClosingStep
        
        anchor = self.workflow_anchor_payment
        if anchor.pk != self.pk:
            return anchor.ensure_closing_steps()
        
        templates = self.closing_step_templates(self.transaction_type, self.plot)
        if not templates:
            return

        existing_steps = {
            step.code: step
            for step in self.closing_steps.all()
        }
        to_create = []
        
        for sequence, template in enumerate(templates, start=1):
            if len(template) == 4:
                code, title, document_name, guidance = template
            elif len(template) == 3:
                code, title, guidance = template
                document_name = title
            else:
                raise ValueError("Closing step templates must define either 3 or 4 values per step.")
            
            step = existing_steps.get(code)
            if step:
                changed = False
                for field_name, new_value in {
                    "sequence": sequence,
                    "title": title,
                    "document_name": document_name,
                    "guidance": guidance,
                }.items():
                    if getattr(step, field_name) != new_value:
                        setattr(step, field_name, new_value)
                        changed = True
                if changed:
                    step.save(update_fields=["sequence", "title", "document_name", "guidance", "updated_at"])
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
            return "All legal transfer steps are complete. Funds have been disbursed to the seller."
        if self.transaction_type == self.TransactionType.LEASE:
            return "All lease handover steps are complete."
        return "No closing tracker is required for this payment."

    @property
    def transfer_status_label(self):
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.purchase_registration_complete and self.disbursed_at:
                return "Completed - Funds Disbursed"
            if self.purchase_registration_complete:
                return "Registered - Awaiting Disbursement"
            if self.status == self.Status.RELEASED:
                return "Awaiting registry transfer"
            if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                return "Funds in Escrow"
            if self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                return "Transfer stopped"
            return "Awaiting buyer payment"
        
        if self.transaction_type == self.TransactionType.LEASE:
            if self.lease_currently_active:
                return "Lease active"
            if self.lease_ready_for_use:
                return "Approved - awaiting start date"
            if self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                return "Funds in Escrow"
            if self.status == self.Status.RELEASED:
                return "Lease approved"
            if self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                return "Lease stopped"
            return "Awaiting tenant payment"
        
        return self.get_status_display()

    @property
    def purchase_registration_complete(self):
        """Check if registration is complete (new title issued)"""
        if self.transaction_type != self.TransactionType.PURCHASE:
            return False
        return self.closing_steps.filter(
            code="registration",
            status=PaymentClosingStep.Status.COMPLETED,
        ).exists()

    @property
    def funds_ready_for_disbursement(self):
        """Check if all conditions for fund disbursement are met"""
        if self.transaction_type != self.TransactionType.PURCHASE:
            return False
        
        # Must have new title deed verified
        registration_complete = self.purchase_registration_complete
        
        # Must have stamp duty receipt verified
        stamp_duty_complete = self.closing_steps.filter(
            code="stamp_duty",
            status=PaymentClosingStep.Status.COMPLETED
        ).exists()
        
        # Must have both deposit and balance in escrow
        deposit_paid = self.metadata.get('deposit_paid', False)
        balance_paid = self.metadata.get('balance_paid', False)
        
        return registration_complete and stamp_duty_complete and deposit_paid and balance_paid

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
    def search_result_summary(self):
        plot = self.plot
        search_result = getattr(plot, "search_result", None) if plot else None
        documents = self.due_diligence_documents

        if search_result:
            platform = search_result.search_platform or "official registry search"
            owner = search_result.official_owner or getattr(plot, "owner_full_name", "") or "registered owner"
            parcel = search_result.parcel_number or getattr(plot, "parcel_number", "") or "this parcel"
            search_date = (
                f" dated {search_result.search_date:%b %d, %Y}"
                if search_result.search_date
                else ""
            )
            status_label = "verified" if search_result.verified else "uploaded for review"
            encumbrance_note = (
                f" Encumbrances noted: {search_result.encumbrances}."
                if search_result.encumbrances
                else " No encumbrances have been noted in the current search record."
            )
            lease_note = (
                f" Lease status: {search_result.lease_status}."
                if search_result.lease_status
                else ""
            )
            return (
                f"The {platform} result for {parcel}{search_date} identifies {owner} as the recorded owner and is "
                f"currently {status_label}.{encumbrance_note}{lease_note}"
            )

        if documents:
            document_titles = ", ".join(document["title"] for document in documents[:3])
            return (
                "AgriPlot has assembled the due-diligence pack for this plot, including "
                f"{document_titles}. Review the uploaded documents before moving to the agreement stage."
            )

        return (
            "The due-diligence certificate will summarise the official search, survey, and supporting verification "
            "documents once they are uploaded to this transaction."
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

    def sync_plot_market_state(self):
        """Update plot market status based on payment state"""
        if self.workflow_anchor_payment.pk != self.pk:
            return
        if not self.plot:
            return
        
        if self.transaction_type == self.TransactionType.PURCHASE:
            if self.purchase_registration_complete and self.disbursed_at:
                self.plot.market_status = "sold"
                self.plot.availability_notes = (
                    f"Sold via payment {self.internal_reference}. New title issued and funds disbursed."
                )
            elif self.status in {self.Status.PAID, self.Status.IN_ESCROW, self.Status.PARTIALLY_RELEASED}:
                self.plot.market_status = "reserved"
                self.plot.availability_notes = (
                    f"Reserved for purchase via payment {self.internal_reference}. Funds held in escrow."
                )
            elif self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                self.plot.market_status = "available"
                self.plot.availability_notes = f"Purchase transaction {self.internal_reference} closed without transfer."
            else:
                return
            
            self.plot.save(update_fields=["market_status", "availability_notes", "updated_at"])
            return
        
        if self.transaction_type == self.TransactionType.LEASE:
            if self.lease_currently_active:
                self.plot.market_status = "leased"
                self.plot.lease_start_date = self.lease_start_date
                self.plot.lease_end_date = self.lease_end_date
                self.plot.availability_notes = f"Lease active via payment {self.internal_reference}"
            elif self.lease_ready_for_use:
                self.plot.market_status = "reserved"
                self.plot.lease_start_date = self.lease_start_date
                self.plot.lease_end_date = self.lease_end_date
                self.plot.availability_notes = f"Lease approved via payment {self.internal_reference}"
            elif self.status in {self.Status.PAID, self.Status.IN_ESCROW}:
                self.plot.market_status = "reserved"
                self.plot.availability_notes = f"Lease in progress via payment {self.internal_reference}"
            elif self.status in {self.Status.REFUNDED, self.Status.CANCELLED, self.Status.FAILED}:
                self.plot.market_status = "available"
                self.plot.lease_start_date = None
                self.plot.lease_end_date = None
                self.plot.availability_notes = f"Lease transaction {self.internal_reference} closed without activation"
            else:
                return
            
            self.plot.save(update_fields=["market_status", "lease_start_date", "lease_end_date", "availability_notes", "updated_at"])


# ============================================================
# SUPPORTING MODELS
# ============================================================

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


class BankBeneficiary(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_beneficiaries",
    )
    legal_name = models.CharField(max_length=200)
    bank_name = models.CharField(max_length=100)
    bank_code = models.CharField(max_length=20, blank=True)
    account_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50)
    branch_name = models.CharField(max_length=100, blank=True)
    currency = models.CharField(max_length=10, default="KES")
    is_verified = models.BooleanField(default=False)
    verification_reference = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments_bank_beneficiary"
        ordering = ["legal_name", "bank_name", "account_name"]

    def __str__(self):
        return f"{self.legal_name} - {self.bank_name}"


class BankTransferRequest(models.Model):
    class Provider(models.TextChoices):
        JENGA = "jenga", "Equity Jenga"
        MANUAL = "manual", "Manual"

    class Rail(models.TextChoices):
        PESALINK = "pesalink", "PesaLink"
        RTGS = "rtgs", "RTGS"
        EFT = "eft", "EFT"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUEUED = "queued", "Queued"
        SUBMITTED = "submitted", "Submitted"
        PROCESSING = "processing", "Processing"
        SETTLED = "settled", "Settled"
        FAILED = "failed", "Failed"
        REVERSED = "reversed", "Reversed"
        RECONCILED = "reconciled", "Reconciled"

    payment = models.ForeignKey(
        PaymentRequest,
        on_delete=models.CASCADE,
        related_name="bank_transfer_requests",
    )
    disbursement = models.OneToOneField(
        PaymentDisbursement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transfer_request",
    )
    beneficiary = models.ForeignKey(
        BankBeneficiary,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transfer_requests",
    )
    beneficiary_name = models.CharField(max_length=200)
    bank_name = models.CharField(max_length=100)
    bank_code = models.CharField(max_length=20, blank=True)
    account_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=10, default="KES")
    rail = models.CharField(max_length=20, choices=Rail.choices, default=Rail.PESALINK)
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.JENGA)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    reference = models.CharField(max_length=50, unique=True, editable=False, default="", blank=True)
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    callback_payload = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments_bank_transfer_request"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "rail"]),
            models.Index(fields=["reference"]),
            models.Index(fields=["provider_reference"]),
            models.Index(fields=["idempotency_key"]),
        ]

    def __str__(self):
        return f"{self.reference or self.payment.internal_reference} - {self.beneficiary_name}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"BTR-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)

    def mark_submitted(self, provider_reference="", response=None):
        self.status = self.Status.SUBMITTED
        self.provider_reference = provider_reference or self.provider_reference
        self.submitted_at = timezone.now()
        if response is not None:
            self.provider_response = response
        self.save(update_fields=["status", "provider_reference", "submitted_at", "provider_response", "updated_at"])

    def mark_settled(self, callback_payload=None, response=None):
        self.status = self.Status.SETTLED
        self.completed_at = timezone.now()
        if callback_payload is not None:
            self.callback_payload = callback_payload
        if response is not None:
            self.provider_response = response
        self.save(
            update_fields=[
                "status",
                "completed_at",
                "callback_payload",
                "provider_response",
                "updated_at",
            ]
        )

    def mark_failed(self, reason, callback_payload=None, response=None):
        self.status = self.Status.FAILED
        self.failure_reason = reason
        if callback_payload is not None:
            self.callback_payload = callback_payload
        if response is not None:
            self.provider_response = response
        self.save(
            update_fields=[
                "status",
                "failure_reason",
                "callback_payload",
                "provider_response",
                "updated_at",
            ]
        )


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
    def workflow_code(self):
        raw_code = (self.code or "").strip().lower()
        legacy_aliases = {
            "commitment": "offer",
            "letter_of_offer": "offer",
            "letter-of-offer": "offer",
            "letter offer": "offer",
        }
        if raw_code in legacy_aliases:
            return legacy_aliases[raw_code]

        text_blob = " ".join(
            value
            for value in [self.code, self.title, self.document_name, self.guidance]
            if value
        ).lower()
        if "offer" in text_blob:
            return "offer"
        if "due diligence" in text_blob or "official search" in text_blob or "survey" in text_blob:
            return "due_diligence"
        if "agreement" in text_blob or "contract" in text_blob:
            return "agreement"
        if "consent" in text_blob or "lcb" in text_blob:
            return "lcb_consent"
        if "completion" in text_blob or "balance" in text_blob:
            return "completion_docs"
        if "stamp duty" in text_blob or "valuation" in text_blob or "tax" in text_blob:
            return "stamp_duty"
        if "registration" in text_blob or "title" in text_blob or "registry" in text_blob:
            return "registration"
        return raw_code

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
        code = self.workflow_code
        purchase_map = {
            "due_diligence": "Buyer",
            "offer": "Buyer",
            "agreement": "Both Parties",
            "lcb_consent": "Seller",
            "completion_docs": "Both Advocates",
            "stamp_duty": "Buyer",
            "registration": "Buyer Advocate",
            "disbursement": "Platform (Automatic)",
            "handover": "Both Parties",
            "reports": "System",
        }
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return purchase_map.get(code, "Both Parties")
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            lease_map = {
                "offer": "Tenant",
                "lcb_consent": "Landlord",
                "agreement": "Both Parties",
                "payment_security": "Tenant",
                "lease_registration": "Landlord",
                "soil_health_baseline": "Both Parties",
                "handover": "Both Parties",
            }
            return lease_map.get(code, "Both Parties")
        return "Both Parties"

    @property
    def action_summary(self):
        code = self.workflow_code
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
            "offer": {
                "headline": "Upload the letter of offer and let the seller confirm it.",
                "where": "Draft and upload the letter of offer or reservation terms, then let the seller or their advocate countersign the same step in the system.",
                "document": "Letter of offer / reservation terms",
                "platform_role": "AgriPlot records the buyer's intent, then lets the seller side confirm the signed offer before the agreement stage opens.",
                "cta_label": "Upload Offer",
                "support_label": "This step should be completed by the buyer first and then confirmed by the seller or their advocate.",
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
                "headline": "Exchange the completion papers and prepare the 90% balance release.",
                "where": "The buyer's lawyer confirms the original title, signed transfer forms, ID/KRA copies, and clearances are all in order before the remaining balance is released.",
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
            return purchase_map.get(code, {})
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return lease_map.get(self.workflow_code, {})
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

    def _linked_legal_transaction(self):
        try:
            return self.payment.legal_transaction
        except Exception:
            return None

    def required_legal_document_types(self):
        """
        Return the legal-workspace document types that should satisfy this step.
        This is the canonical mapping used for payment step validation.
        """
        purchase_map = {
            "due_diligence": ["OFFICIAL_SEARCH", "SURVEY_MAP"],
            "offer": ["LETTER_OF_OFFER"],
            "agreement": ["SALE_AGREEMENT"],
            "lcb_consent": ["LCB_CONSENT", "SPOUSAL_CONSENT"],
            "stamp_duty": ["STAMP_DUTY_RECEIPT", "VALUATION_REPORT"],
            "registration": ["NEW_TITLE_DEED"],
        }
        lease_map = {
            "offer": ["LETTER_OF_OFFER"],
            "agreement": [],
            "lcb_consent": ["LCB_CONSENT", "SPOUSAL_CONSENT"],
            "lease_registration": ["NEW_TITLE_DEED"],
            "soil_health_baseline": [],
            "handover": [],
        }
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return purchase_map.get(self.workflow_code, [])
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return lease_map.get(self.workflow_code, [])
        return []

    def _legal_doc_state(self, doc_type):
        legal_tx = self._linked_legal_transaction()
        if not legal_tx:
            return None
        from transactions.models import TransactionDocument

        return legal_tx.documents.filter(document_type=doc_type).order_by("-uploaded_at").first()

    def _legal_docs_ready(self):
        doc_types = self.required_legal_document_types()
        if not doc_types:
            return True
        return all(
            self._legal_doc_state(doc_type) and self._legal_doc_state(doc_type).status == "verified"
            for doc_type in doc_types
        )

    def _legal_docs_blocking_reason(self):
        doc_types = self.required_legal_document_types()
        if not doc_types:
            return ""

        from transactions.models import TransactionDocument

        missing = []
        pending = []
        rejected = []
        for doc_type in doc_types:
            doc = self._legal_doc_state(doc_type)
            doc_label = dict(TransactionDocument.DocType.choices).get(doc_type, doc_type)
            if not doc:
                missing.append(doc_label)
            elif doc.status == "pending":
                pending.append(doc_label)
            elif doc.status == "rejected":
                rejected.append(doc_label)

        if missing:
            if len(missing) == 1:
                return f"Upload {missing[0]} in the Legal Workspace before advancing this step."
            return f"Upload these documents in the Legal Workspace before advancing this step: {', '.join(missing)}."
        if pending:
            if len(pending) == 1:
                return f"{pending[0]} has been uploaded but is still awaiting verification."
            return f"These documents are uploaded but still awaiting verification: {', '.join(pending)}."
        if rejected:
            if len(rejected) == 1:
                return f"{rejected[0]} was rejected. Please upload a new copy in the Legal Workspace."
            return f"These documents were rejected. Please upload new copies in the Legal Workspace: {', '.join(rejected)}."
        return ""

    @property
    def buyer_instruction(self):
        code = self.workflow_code
        purchase_map = {
            "due_diligence": "Review the verified search, survey, and registry pack on AgriPlot before moving into the sale agreement stage.",
            "offer": "Upload the letter of offer, then let the seller or their advocate confirm the signed copy in the system.",
            "agreement": "Review the sale agreement with your advocate and confirm once the seller-side upload is ready.",
            "lcb_consent": "Coordinate with the seller for the Land Control Board meeting and carry your ID documents.",
            "completion_docs": "Wait for the completion pack to be exchanged, then confirm it is complete before the balance and tax stages move on.",
            "stamp_duty": "Follow up on the government valuation, pay stamp duty through KRA/eCitizen, and upload the proof here.",
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
            return purchase_map.get(code, "Open this step and follow the guidance provided.")
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return lease_map.get(self.workflow_code, "Open this step and follow the guidance provided.")
        return "Open this step and follow the guidance provided."

    @property
    def stakeholder_update_label(self):
        code = self.workflow_code
        purchase_map = {
            "due_diligence": "Buyer review confirmation",
            "offer": "Buyer offer upload / seller confirmation",
            "agreement": "Both parties confirmation",
            "lcb_consent": "Seller evidence upload",
            "completion_docs": "Both advocates exchange",
            "stamp_duty": "Buyer tax evidence upload",
            "registration": "Buyer advocate proof upload",
        }
        lease_map = {
            "offer": "Tenant confirmation",
            "lcb_consent": "Landlord consent upload",
            "agreement": "Both parties confirmation",
            "payment_security": "Tenant payment confirmation",
            "lease_registration": "Landlord registry proof",
            "soil_health_baseline": "Both parties baseline upload",
            "handover": "Both parties handover",
        }
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return purchase_map.get(code, "Evidence-backed update")
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return lease_map.get(self.workflow_code, "Evidence-backed update")
        return "Evidence-backed update"

    @property
    def completion_requirements(self):
        code = self.workflow_code
        requirement_map = {
            "offer": ["Letter of offer uploaded"],
            "agreement": ["Executed sale agreement uploaded", "Buyer confirmed", "Seller confirmed"],
            "lcb_consent": ["Consent number entered", "Meeting date entered", "LCB / spousal consent upload"],
            "completion_docs": ["Original title received", "Seller ID / KRA copies received", "Transfer forms signed"],
            "stamp_duty": ["Official market value entered", "Calculated stamp duty entered", "Stamp duty receipt uploaded"],
            "registration": ["New search or registry proof uploaded"],
            "payment_security": [
                "Security deposit amount confirmed",
                "Escrow payment recorded through AgriPlot",
            ],
            "lease_registration": ["Lease registry proof uploaded"],
            "soil_health_baseline": ["Baseline soil or condition report uploaded"],
            "handover": ["Handover certificate uploaded"],
        }
        return requirement_map.get(code, [])

    def can_mark_complete_with_current_evidence(self):
        code = self.workflow_code
        active_payment_statuses = {
            PaymentRequest.Status.PAID,
            PaymentRequest.Status.IN_ESCROW,
            PaymentRequest.Status.PARTIALLY_RELEASED,
            PaymentRequest.Status.RELEASED,
        }
        if code == "due_diligence":
            return bool(self.document or self._legal_docs_ready())
        if code == "agreement":
            if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                return bool((self.document or self._legal_docs_ready()) and self.buyer_confirmed_at and self.seller_confirmed_at)
            return bool(self.buyer_confirmed_at and self.seller_confirmed_at)
        if code == "registration":
            return bool(self.document or self._legal_docs_ready())
        if code == "lcb_consent":
            return bool((self.document or self._legal_docs_ready()) and self.consent_reference_number and self.meeting_date)
        if code == "stamp_duty":
            return bool(
                (self.document or self._legal_docs_ready())
                and self.official_market_value is not None
                and self.assessed_stamp_duty is not None
            )
        if code == "completion_docs":
            return bool(
                self.original_title_received
                and self.seller_id_copy_received
                and self.transfer_forms_signed
            )
        if code == "payment_security":
            return any(
                related_payment.category == PaymentRequest.Category.ESCROW_DEPOSIT
                and related_payment.status in active_payment_statuses
                for related_payment in self.payment.workflow_related_payments
            )
        if code in {"lease_registration", "soil_health_baseline", "handover"}:
            return bool(self.document or self._legal_docs_ready())
        if code == "offer":
            return bool(self.notes or self.document or self._legal_docs_ready())
        return True

    def evidence_blocking_reason(self):
        if self.can_mark_complete_with_current_evidence():
            return ""
        if self.code == "agreement":
            if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                missing = []
                if not (self.document or self._legal_docs_ready()):
                    missing.append(self._legal_docs_blocking_reason() or "executed sale agreement")
                if not self.buyer_confirmed_at:
                    missing.append("buyer confirmation")
                if not self.seller_confirmed_at:
                    missing.append("seller confirmation")
                if missing == ["buyer confirmation"]:
                    return (
                        "Buyer confirmation is still needed. The buyer should tick the confirmation box "
                        "and submit this step."
                    )
                if missing == ["seller confirmation"]:
                    return (
                        "Seller confirmation is still needed. The seller should tick the confirmation box "
                        "and submit this step."
                    )
                if len(missing) == 1 and "upload" in missing[0].lower():
                    return missing[0]
                return f"This step still needs: {', '.join(missing)}."
            return (
                "Both the tenant and the landlord must digitally confirm the lease agreement before this step can be completed."
            )
        legal_reason = self._legal_docs_blocking_reason()
        if legal_reason:
            return legal_reason
        requirement_text = ", ".join(self.completion_requirements)
        if requirement_text:
            return f"This step still needs: {requirement_text}."
        return "This step still needs more evidence before it can be completed."

    def set_status(self, status, actor=None, notes="", bypass_evidence=False):
        from notifications.notification_service import NotificationService

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
        if previous_status != status:
            NotificationService.notify_payment_step_updated(
                self.payment,
                self,
                previous_status,
                actor=actor,
            )
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

        from notifications.notification_service import NotificationService
        NotificationService.notify_payment_step_assigned(self.payment, next_step)


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


# ============================================================
# WALLET SYSTEM - DOUBLE-ENTRY LEDGER
# ============================================================

class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT,
        related_name='wallet'
    )
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    account_number = models.CharField(
        max_length=30, 
        unique=True, 
        editable=False,
        help_text="Format: AGP-WLT-XXXXXXXX (Auto-generated)"
    )
    is_active = models.BooleanField(default=True)
    
    pin_hash = models.CharField(max_length=128, null=True, blank=True)
    failed_pin_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payments_wallet'
    
    def __str__(self):
        return f"{self.account_number} - {self.user.username}"
    
    def save(self, *args, **kwargs):
        if self.balance is None:
            self.balance = Decimal("0.00")
        if not self.account_number:
            unique_id = str(uuid.uuid4().int)[:10]
            self.account_number = f"AGP-WLT-{unique_id}"
        super().save(*args, **kwargs)

    @property
    def ledger_balance(self):
        from django.db.models import Sum
        credits = self.transactions.filter(
            type=WalletTransaction.TYPE_CREDIT,
            status=WalletTransaction.STATUS_SUCCESS
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        debits = self.transactions.filter(
            type=WalletTransaction.TYPE_DEBIT,
            status=WalletTransaction.STATUS_SUCCESS
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return credits - debits
    
    @property
    def available_balance(self):
        from django.db.models import Sum
        frozen_amount = self.transactions.filter(
            type=WalletTransaction.TYPE_DEBIT,
            status=WalletTransaction.STATUS_FROZEN
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return self.balance - frozen_amount
    
    def verify_pin(self, pin):
        from django.contrib.auth.hashers import check_password

        if not self.pin_hash:
            raise ValueError("Wallet PIN not set.")
        
        if self.locked_until and timezone.now() < self.locked_until:
            raise ValueError(f"Wallet is locked until {self.locked_until}.")
        
        import hashlib
        pin_hash_input = hashlib.sha256(f"{pin}{self.user.id}".encode()).hexdigest()
        
        if pin_hash_input == self.pin_hash or check_password(pin, self.pin_hash):
            if self.failed_pin_attempts > 0:
                self.failed_pin_attempts = 0
                self.save(update_fields=['failed_pin_attempts'])
            return True
        else:
            self.failed_pin_attempts += 1
            if self.failed_pin_attempts >= 5:
                self.locked_until = timezone.now() + timedelta(minutes=30)
                self.save(update_fields=['failed_pin_attempts', 'locked_until'])
            else:
                self.save(update_fields=['failed_pin_attempts'])
            raise ValueError(f"Invalid PIN. {5 - self.failed_pin_attempts} attempts remaining.")
    
    def set_pin(self, pin):
        from django.contrib.auth.hashers import make_password

        if len(pin) != 4 or not pin.isdigit():
            raise ValueError("PIN must be 4 digits")
        self.pin_hash = make_password(pin)
        self.failed_pin_attempts = 0
        self.locked_until = None
        self.save(update_fields=['pin_hash', 'failed_pin_attempts', 'locked_until'])
    
    def can_debit(self, amount):
        return self.available_balance >= amount
    
    def debit(self, amount, description="", reference="", metadata=None):
        from django.db import transaction as db_transaction
        
        if not self.can_debit(amount):
            raise ValueError(f"Insufficient balance. Available: {self.available_balance}, Requested: {amount}")
        
        with db_transaction.atomic():
            Wallet.objects.select_for_update().get(pk=self.pk)
            wallet_tx = WalletTransaction.objects.create(
                wallet=self,
                amount=amount,
                type=WalletTransaction.TYPE_DEBIT,
                status=WalletTransaction.STATUS_PENDING,
                reference=reference or f"TX-{uuid.uuid4().hex[:12].upper()}",
                description=description,
                metadata=metadata or {}
            )
        return wallet_tx
    
    def credit(self, amount, description="", reference="", metadata=None):
        from django.db import transaction as db_transaction
        
        with db_transaction.atomic():
            Wallet.objects.select_for_update().get(pk=self.pk)
            wallet_tx = WalletTransaction.objects.create(
                wallet=self,
                amount=amount,
                type=WalletTransaction.TYPE_CREDIT,
                status=WalletTransaction.STATUS_PENDING,
                reference=reference or f"TX-{uuid.uuid4().hex[:12].upper()}",
                description=description,
                metadata=metadata or {}
            )
        return wallet_tx


class WalletTransaction(models.Model):
    TYPE_CREDIT = 'CREDIT'
    TYPE_DEBIT = 'DEBIT'
    TRANSACTION_TYPES = [
        (TYPE_CREDIT, 'Credit (Deposit/Incoming)'),
        (TYPE_DEBIT, 'Debit (Withdrawal/Outgoing)'),
    ]
    
    STATUS_PENDING = 'PENDING'
    STATUS_PROCESSING = 'PROCESSING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILED = 'FAILED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_FROZEN = 'FROZEN'
    
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_SUCCESS, 'Success (Immutable)'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_FROZEN, 'Frozen (Held)'),
    ]
    
    CHANNEL_MPESA = 'MPESA'
    CHANNEL_BANK_TRANSFER = 'BANK_TRANSFER'
    CHANNEL_CARD = 'CARD'
    CHANNEL_WALLET = 'WALLET'
    CHANNEL_ESCROW = 'ESCROW'
    CHANNEL_REFUND = 'REFUND'
    CHANNEL_FEE = 'FEE'
    
    CHANNEL_CHOICES = [
        (CHANNEL_MPESA, 'M-Pesa'),
        (CHANNEL_BANK_TRANSFER, 'Bank Transfer'),
        (CHANNEL_CARD, 'Card Payment'),
        (CHANNEL_WALLET, 'Internal Wallet Transfer'),
        (CHANNEL_ESCROW, 'Escrow Release'),
        (CHANNEL_REFUND, 'Refund'),
        (CHANNEL_FEE, 'Platform Fee'),
    ]
    
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
        default=TYPE_CREDIT,
        db_column="transaction_type",
    )
    type = models.CharField(max_length=6, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, blank=True)

    reference = models.CharField(max_length=50, unique=True, db_index=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)

    description = models.TextField(blank=True)
    mpesa_receipt = models.CharField(max_length=50, blank=True)

    related_payment = models.ForeignKey(
        PaymentRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wallet_transactions_legacy',
        db_column='related_payment_id',
    )
    payment_request = models.ForeignKey(PaymentRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name='wallet_transactions')
    
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'payments_wallet_transaction'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', '-created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['idempotency_key']),
            models.Index(fields=['status', 'channel']),
        ]
    
    def __str__(self):
        return f"{self.reference} - {self.type}: KES {self.amount} ({self.status})"
    
    def save(self, *args, **kwargs):
        if self.type and self.transaction_type != self.type:
            self.transaction_type = self.type
        elif self.transaction_type and not self.type:
            self.type = self.transaction_type
        if self.payment_request_id and not self.related_payment_id:
            self.related_payment_id = self.payment_request_id
        elif self.related_payment_id and not self.payment_request_id:
            self.payment_request_id = self.related_payment_id
        if self.pk:
            original = WalletTransaction.objects.get(pk=self.pk)
            if original.status == self.STATUS_SUCCESS and self.status != self.STATUS_SUCCESS:
                raise ValueError("Cannot modify a successful transaction.")
        super().save(*args, **kwargs)
    
    def mark_success(self):
        if self.status != self.STATUS_PENDING:
            raise ValueError(f"Cannot mark transaction {self.status} as success")
        
        from django.db import transaction as db_transaction
        
        with db_transaction.atomic():
            Wallet.objects.select_for_update().get(pk=self.wallet_id)
            self.status = self.STATUS_SUCCESS
            self.completed_at = timezone.now()
            self.save(update_fields=['status', 'completed_at'])
        return True


class WalletDepositRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('expired', 'Expired'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='deposit_requests')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    phone_number = models.CharField(max_length=20, blank=True)
    payment_method = models.CharField(max_length=20, choices=PaymentRequest.Method.choices, default=PaymentRequest.Method.MPESA_STK)
    
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    reference = models.CharField(max_length=50, unique=True, editable=False, default='', blank=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    
    checkout_url = models.URLField(blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    
    
    payment_request = models.ForeignKey(
        'PaymentRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wallet_deposits'
    )
    wallet_transaction = models.OneToOneField(
        WalletTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deposit_request',
        db_column='transaction_id',
    )
    
    expires_at = models.DateTimeField(default=None, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'payments_wallet_deposit_request'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.reference} - KES {self.amount} ({self.status})"
    
    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"DEP-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)
    
    def is_expired(self):
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at


class WalletWithdrawalRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved (Ready for payout)'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled by User'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='withdrawal_requests')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PaymentRequest.Method.choices, default=PaymentRequest.Method.MPESA_STK)
    phone_number = models.CharField(max_length=20, blank=True)
    
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_name = models.CharField(max_length=200, blank=True)
    bank_account_number = models.CharField(max_length=50, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)
    bank_code = models.CharField(max_length=20, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reference = models.CharField(max_length=50, unique=True, editable=False, default='', blank=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='withdrawals_requested', null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='withdrawals_approved', null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(blank=True)
    
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='withdrawals_processed', null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    wallet_transaction = models.OneToOneField(
        WalletTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='withdrawal_request',
        db_column='transaction_id',
    )
    provider_response = models.JSONField(default=dict, blank=True)
    
    rejection_reason = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'payments_wallet_withdrawal_request'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.reference} - KES {self.amount} ({self.status})"
    
    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"WIT-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)
    
    def requires_maker_checker(self):
        return self.amount > Decimal('100000.00')
    
    def approve(self, approver, notes=""):
        if self.status != 'pending':
            raise ValueError(f"Cannot approve withdrawal in {self.status} status")
        self.status = 'approved'
        self.approved_by = approver
        self.approved_at = timezone.now()
        self.approval_notes = notes
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'approval_notes', 'updated_at'])
    
    def reject(self, approver, reason):
        if self.status != 'pending':
            raise ValueError(f"Cannot reject withdrawal in {self.status} status")
        self.status = 'rejected'
        self.approved_by = approver
        self.approved_at = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at'])


class WalletDisbursement(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    payment_request = models.ForeignKey(PaymentRequest, on_delete=models.CASCADE, related_name='wallet_disbursements')
    recipient_wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='incoming_disbursements')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reference = models.CharField(max_length=50, unique=True, editable=False, default='', blank=True)
    description = models.TextField(blank=True)
    
    wallet_transaction = models.OneToOneField(
        WalletTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disbursement',
        db_column='transaction_id',
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'payments_wallet_disbursement'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Disbursement {self.reference} - KES {self.amount}"
    
    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"DISB-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)
