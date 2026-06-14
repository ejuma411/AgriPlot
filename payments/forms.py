from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.validators import validate_kenyan_phone, validate_person_name

from listings.models import Plot

from .models import (
    PaymentRequest,
    PaymentMilestone,
    PaymentDispute,
    PaymentClosingStep,
)
from .permissions import user_is_finance_admin, user_is_escrow_admin


class DateTimePickerInput(forms.DateTimeInput):
    input_type = "datetime-local"


class PaymentRequestForm(forms.ModelForm):
    MPESA_MAX_AMOUNT = Decimal("50000.00")
    DIRECT_TRANSACTION_CHOICES = [
        (PaymentRequest.TransactionType.PURCHASE, "Purchase"),
        (PaymentRequest.TransactionType.LEASE, "Lease"),
    ]
    DIRECT_CATEGORY_CHOICES = [
        (PaymentRequest.Category.AGREEMENT_DEPOSIT, "10% Escrow Deposit"),
        (PaymentRequest.Category.ESCROW_DEPOSIT, "Full Escrow Deposit"),
        (PaymentRequest.Category.STAMP_DUTY, "Stamp Duty (Pay to KRA)"),
        (PaymentRequest.Category.COMPLETION_BALANCE, "90% Escrow Balance"),
    ]
    DEFAULT_DUE_WINDOWS = {
        PaymentRequest.Category.RESERVATION_DEPOSIT: timedelta(hours=48),
        PaymentRequest.Category.AGREEMENT_DEPOSIT: timedelta(hours=72),
        PaymentRequest.Category.VERIFICATION_PACKAGE: timedelta(hours=72),
        PaymentRequest.Category.ESCROW_DEPOSIT: timedelta(hours=72),
        PaymentRequest.Category.STAMP_DUTY: timedelta(days=30),  # 30 days for KRA payment
        PaymentRequest.Category.COMPLETION_BALANCE: timedelta(days=14),
        PaymentRequest.Category.SERVICE_FEE: timedelta(hours=48),
    }
    METHOD_DETAIL_FIELDS = [
        "mpesa_reference",
        "mpesa_account_reference",
        "cardholder_name",
        "card_last4",
        "bank_name",
        "bank_account_name",
        "bank_account_number",
        "airtel_number",
        "wallet_identifier",
        "manual_escrow_notes",
    ]
    METHOD_SLUG_MAP = {
        "mpesa": PaymentRequest.Method.MPESA_STK,
        "mpesa_stk": PaymentRequest.Method.MPESA_STK,
        "card": PaymentRequest.Method.CARD,
        "bank": PaymentRequest.Method.BANK_TRANSFER,
        "bank_transfer": PaymentRequest.Method.BANK_TRANSFER,
        "airtel": PaymentRequest.Method.AIRTEL_MONEY,
        "airtel_money": PaymentRequest.Method.AIRTEL_MONEY,
        "wallet": PaymentRequest.Method.WALLET,
        "manual_escrow": PaymentRequest.Method.MANUAL_ESCROW,
    }
    PLOT_REQUIRED_CATEGORIES = PaymentRequest.PLOT_REQUIRED_CATEGORIES

    # Payment method detail fields
    mpesa_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. AGP-RES-51"}
        ),
        help_text="Reference for manual Paybill / Till reconciliation.",
    )
    mpesa_account_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. AGP-RES-51"}
        ),
        help_text="Short account reference for Paybill or Till instructions.",
    )
    cardholder_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Name on card"}),
    )
    card_last4 = forms.CharField(
        required=False,
        max_length=4,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "1234"}),
        help_text="For checkout confirmation only, not full card storage.",
    )
    bank_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Equity Bank"}),
    )
    bank_account_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Account holder name"}),
    )
    bank_account_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Account number"}),
    )
    airtel_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "2547XXXXXXXX"}),
        help_text="Optional alternate Airtel Money number if it differs from the checkout number.",
    )
    wallet_identifier = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Wallet ID or customer code"}),
    )
    manual_escrow_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Banker, lawyer, or escrow partner instructions for manual settlement.",
            }
        ),
    )

    class Meta:
        model = PaymentRequest
        fields = [
            "plot",
            "transaction_type",
            "title",
            "description",
            "amount",
            "category",
            "method",
            "phone_number",
            "lease_start_date",
            "lease_end_date",
            "intended_use",
            "lease_security_deposit",
            "notice_period_days",
            "good_husbandry_required",
            "soil_exit_test_required",
            "subject_to_sale",
            "escrow_enabled",
            "due_at",
        ]
        widgets = {
            "plot": forms.Select(attrs={"class": "form-select"}),
            "transaction_type": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Agreement deposit for Plot A"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Describe what this payment unlocks and the next seller obligation.",
                }
            ),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "method": forms.Select(attrs={"class": "form-select"}),
            "phone_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "2547XXXXXXXX"}
            ),
            "lease_start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "lease_end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "intended_use": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. avocados, onions, grazing, greenhouse farming"}),
            "lease_security_deposit": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "notice_period_days": forms.NumberInput(attrs={"class": "form-control", "min": "30", "step": "1"}),
            "good_husbandry_required": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "soil_exit_test_required": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "subject_to_sale": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "escrow_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "due_at": DateTimePickerInput(attrs={"class": "form-control"}),
        }

    def __init__(
        self,
        *args,
        user=None,
        selected_plot=None,
        forced_category=None,
        active_deal=None,
        forced_amount=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.user = user
        self.selected_plot = selected_plot
        self.forced_category = forced_category
        self.active_deal = active_deal
        self.forced_amount = self.normalize_amount(forced_amount) if forced_amount not in {None, ""} else None
        self.allow_amount_override = False
        self.allow_due_at_override = user_is_finance_admin(user)
        self.allow_lease_term_entry = bool(
            user_is_finance_admin(user)
            or hasattr(user, "agent")
            or hasattr(user, "landownerprofile")
        )
        if not self.allow_lease_term_entry:
            for field_name in ("lease_start_date", "lease_end_date"):
                self.fields.pop(field_name, None)
        self.simple_mpesa_checkout = True
        self.fields["plot"].queryset = Plot.objects.order_by("title")
        self.fields["plot"].required = False
        self.fields["due_at"].required = False
        self.fields["phone_number"].required = False
        if "lease_start_date" in self.fields:
            self.fields["lease_start_date"].required = False
        if "lease_end_date" in self.fields:
            self.fields["lease_end_date"].required = False
        self.fields["intended_use"].required = False
        self.fields["lease_security_deposit"].required = False
        self.fields["notice_period_days"].required = False
        self.fields["good_husbandry_required"].required = False
        self.fields["soil_exit_test_required"].required = False
        self.fields["subject_to_sale"].required = False
        self.fields["transaction_type"].choices = self.DIRECT_TRANSACTION_CHOICES
        self.fields["category"].choices = self.DIRECT_CATEGORY_CHOICES
        self.fields["category"].initial = PaymentRequest.Category.AGREEMENT_DEPOSIT
        self.fields["method"].required = False
        self.fields["method"].initial = PaymentRequest.Method.MPESA_STK
        self.fields["method"].widget = forms.HiddenInput()
        self.fields["title"].required = False
        self.fields["title"].widget = forms.HiddenInput()
        self.fields["description"].required = False
        self.fields["description"].widget = forms.HiddenInput()
        self.fields["escrow_enabled"].required = False
        self.fields["escrow_enabled"].widget = forms.HiddenInput()
        self.fields["phone_number"].help_text = (
            "Use the M-Pesa number that should receive the STK prompt."
        )
        self.fields["transaction_type"].label = "Deal type"
        self.fields["category"].label = "Payment stage"
        self.fields["amount"].label = "Calculated amount (KES)"
        self.fields["phone_number"].label = "M-Pesa number"
        
        # Special help text for stamp duty
        if self.forced_category == PaymentRequest.Category.STAMP_DUTY:
            self.fields["category"].help_text = (
                "Stamp duty is paid directly to KRA via iTax. After payment, upload the receipt for verification."
            )
            self.fields["amount"].help_text = (
                "Estimated stamp duty (2% rural / 4% urban). Actual amount determined by KRA."
            )
        else:
            self.fields["category"].help_text = (
                "Choose the stage you are paying for right now."
            )
            self.fields["amount"].help_text = (
                "AgriPlot calculates this automatically from the selected payment stage and the plot sale price."
            )
        
        self.fields["amount"].widget.attrs["readonly"] = True
        self.fields["amount"].widget.attrs["data-fixed-amount"] = "true"
        self.fields["intended_use"].help_text = "State how the tenant plans to use the land so the lease can match the agricultural purpose."
        self.fields["lease_security_deposit"].help_text = "Security deposit held in the AgriPlot workflow before possession starts."
        self.fields["notice_period_days"].help_text = "Standard vacation notice period. Agricultural leases should normally give at least 90 days."
        self.fields["good_husbandry_required"].help_text = "Keep the land in good farming condition and avoid soil damage."
        self.fields["soil_exit_test_required"].help_text = "Require a soil or land-condition exit test before final release."
        self.fields["subject_to_sale"].help_text = "For plots listed for both sale and lease, the lease stays subject to a later sale."
        
        if self.forced_category:
            self.fields["category"].initial = self.forced_category
            self.fields["category"].widget = forms.HiddenInput()
            self.fields["category"].help_text = ""
        
        if self.active_deal and self.active_deal.transaction_type == PaymentRequest.TransactionType.LEASE:
            lease_initials = {
                "lease_start_date": self.active_deal.lease_start_date,
                "lease_end_date": self.active_deal.lease_end_date,
                "intended_use": self.active_deal.intended_use,
                "lease_security_deposit": self.active_deal.lease_security_deposit,
                "notice_period_days": self.active_deal.notice_period_days,
                "good_husbandry_required": self.active_deal.good_husbandry_required,
                "soil_exit_test_required": self.active_deal.soil_exit_test_required,
                "subject_to_sale": self.active_deal.subject_to_sale,
            }
            for field_name, value in lease_initials.items():
                if field_name in self.fields and value not in {None, ""}:
                    self.fields[field_name].initial = value
        
        if selected_plot is not None:
            self.fields["plot"].initial = selected_plot
            self.fields["plot"].help_text = (
                f"AgriPlot has already linked this checkout to {selected_plot.title}."
            )
            if selected_plot.listing_type == "sale":
                self.fields["transaction_type"].initial = PaymentRequest.TransactionType.PURCHASE
                self.fields["transaction_type"].choices = [
                    (PaymentRequest.TransactionType.PURCHASE, "Purchase")
                ]
            elif selected_plot.listing_type == "lease":
                self.fields["transaction_type"].initial = PaymentRequest.TransactionType.LEASE
                self.fields["transaction_type"].choices = [
                    (PaymentRequest.TransactionType.LEASE, "Lease")
                ]
            if selected_plot.listing_type == "both":
                self.fields["subject_to_sale"].initial = True
        
        if self.instance and self.instance.pk:
            metadata = self.instance.metadata or {}
            for field_name in self.METHOD_DETAIL_FIELDS:
                if field_name in metadata:
                    self.fields[field_name].initial = metadata.get(field_name)
        
        if user and user.is_authenticated:
            profile = getattr(user, "profile", None)
            if profile and profile.phone:
                self.fields["phone_number"].initial = profile.phone
        
        default_amount = self.forced_amount if self.forced_amount is not None else self.calculate_amount(
            selected_plot or self.initial.get("plot"),
            self.fields["transaction_type"].initial or self.initial.get("transaction_type"),
            self.forced_category
            or self.initial.get("category")
            or self.fields["category"].initial
            or self.fields["category"].choices[0][0],
        )
        if default_amount is not None:
            self.fields["amount"].initial = default_amount
            if self.forced_amount is not None:
                self.fields["amount"].widget.attrs["data-exact-amount"] = f"{self.forced_amount:.2f}"
                self.fields["amount"].help_text = (
                    "This is the exact agreed amount for the current deal stage and cannot be changed here."
                )
        
        if not self.allow_due_at_override:
            self.fields["due_at"].initial = self.calculate_due_at(
                self.fields["transaction_type"].initial or self.initial.get("transaction_type"),
                self.initial.get("category") or self.fields["category"].initial or self.fields["category"].choices[0][0],
                self.initial.get("lease_start_date"),
            )

    @staticmethod
    def build_title(plot, transaction_type, category):
        category_label = dict(PaymentRequest.Category.choices).get(category, "Payment")
        transaction_label = dict(PaymentRequest.TransactionType.choices).get(
            transaction_type, "Service"
        )
        plot_label = plot.title if plot else "AgriPlot"
        return f"{category_label} for {transaction_label}: {plot_label}"

    @classmethod
    def calculate_due_at(cls, transaction_type, category, lease_start_date=None):
        due_at = timezone.now() + cls.DEFAULT_DUE_WINDOWS.get(
            category, timedelta(hours=48)
        )
        if (
            transaction_type == PaymentRequest.TransactionType.LEASE
            and lease_start_date
        ):
            lease_cutoff = timezone.make_aware(
                datetime.combine(
                    lease_start_date,
                    datetime.min.time(),
                )
            ) - timedelta(hours=12)
            if lease_cutoff > timezone.now():
                due_at = min(due_at, lease_cutoff)
        return due_at.replace(second=0, microsecond=0)

    @classmethod
    def normalize_amount(cls, value):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def lease_base_amount(cls, plot):
        if not plot:
            return None
        if plot.lease_price_monthly:
            return cls.normalize_amount(plot.lease_price_monthly)
        if plot.lease_price_yearly:
            return cls.normalize_amount(Decimal(plot.lease_price_yearly) / Decimal("12"))
        return None

    @classmethod
    def calculate_amount(cls, plot, transaction_type, category):
        """
        Calculate payment amount based on backend business rules stored on the model.
        For stamp duty, returns None (paid directly to KRA, not collected by platform)
        """
        # Stamp duty is paid directly to KRA - platform never collects
        if category == PaymentRequest.Category.STAMP_DUTY:
            return None
        
        amount = PaymentRequest.calculate_stage_amount(plot, transaction_type, category)
        return cls.normalize_amount(amount) if amount not in {None, ""} else None

    @classmethod
    def mpesa_allowed_for_amount(cls, amount):
        normalized_amount = cls.normalize_amount(amount)
        if normalized_amount is None:
            return True
        return normalized_amount <= cls.MPESA_MAX_AMOUNT

    @classmethod
    def allowed_methods_for_amount(cls, amount):
        allowed = [
            PaymentRequest.Method.BANK_TRANSFER,
            PaymentRequest.Method.CARD,
            PaymentRequest.Method.WALLET,
            PaymentRequest.Method.AIRTEL_MONEY,
        ]
        if cls.mpesa_allowed_for_amount(amount):
            allowed.insert(0, PaymentRequest.Method.MPESA_STK)
        return allowed

    @classmethod
    def preferred_method_for_amount(cls, amount):
        allowed = set(cls.allowed_methods_for_amount(amount))
        preference_order = [
            PaymentRequest.Method.MPESA_STK,
            PaymentRequest.Method.BANK_TRANSFER,
            PaymentRequest.Method.CARD,
            PaymentRequest.Method.WALLET,
            PaymentRequest.Method.AIRTEL_MONEY,
        ]
        for method in preference_order:
            if method in allowed:
                return method
        return PaymentRequest.Method.WALLET
    
    def clean(self):
        cleaned_data = super().clean()
        plot = cleaned_data.get("plot") or self.selected_plot
        transaction_type = cleaned_data.get("transaction_type")
        category = self.forced_category or cleaned_data.get("category")
        cleaned_data["category"] = category
        selected_method = (
            self.data.get("payment_method")
            or self.data.get("method")
            or cleaned_data.get("method")
            or self.fields["method"].initial
            or PaymentRequest.Method.MPESA_STK
        )
        notice_days = cleaned_data.get("notice_period_days")
        plot = cleaned_data.get("plot")
        if notice_days is not None and plot:
            min_days = 90 if plot.land_type == "agricultural" else 30
            if notice_days < min_days:
                self.add_error(
                    "notice_period_days",
                    f"Notice period must be at least {min_days} days for {plot.get_land_type_display()} land."
                )
        
        method = self.METHOD_SLUG_MAP.get(selected_method, selected_method)
        valid_methods = {choice[0] for choice in PaymentRequest.Method.choices}
        if method not in valid_methods:
            method = PaymentRequest.Method.MPESA_STK
        cleaned_data["method"] = method
        self.instance.method = method
        
        # Special handling for stamp duty
        if category == PaymentRequest.Category.STAMP_DUTY:
            # Stamp duty is paid directly to KRA, not through platform
            # We don't collect amount, just track verification
            cleaned_data["amount"] = Decimal("0.00")
            self.instance.amount = Decimal("0.00")
            cleaned_data["escrow_enabled"] = False
            self.instance.escrow_enabled = False
        else:
            if category in self.PLOT_REQUIRED_CATEGORIES and not plot:
                self.add_error(
                    "plot",
                    "Select a plot before creating this payment.",
                )
            
            amount = cleaned_data.get("amount")
            calculated_amount = self.forced_amount if self.forced_amount is not None else self.calculate_amount(plot, transaction_type, category)
            
            if transaction_type in {
                PaymentRequest.TransactionType.PURCHASE,
                PaymentRequest.TransactionType.LEASE,
            }:
                if calculated_amount in {None, ""}:
                    self.add_error("amount", "AgriPlot could not calculate the amount for this checkout stage.")
                else:
                    cleaned_data["amount"] = calculated_amount
                    self.instance.amount = calculated_amount
            else:
                if amount in {None, ""}:
                    self.add_error("amount", "Enter the amount you want to test with.")
                else:
                    normalized_amount = self.normalize_amount(amount)
                    if normalized_amount <= Decimal("0.00"):
                        self.add_error("amount", "Amount must be greater than zero.")
                    cleaned_data["amount"] = normalized_amount
                    self.instance.amount = normalized_amount

            payment_amount = cleaned_data.get("amount")
            if method in {PaymentRequest.Method.MPESA_STK, PaymentRequest.Method.MPESA_PAYBILL}:
                if not self.mpesa_allowed_for_amount(payment_amount):
                    self.add_error(
                        "method",
                        "M-Pesa is only available for payments up to KES 50,000. Please use bank transfer, card, or wallet.",
                    )

        method_requirements = {
            PaymentRequest.Method.MPESA_STK: ["phone_number"],
            PaymentRequest.Method.MPESA_PAYBILL: [
                "phone_number",
                "mpesa_reference",
                "mpesa_account_reference",
            ],
            PaymentRequest.Method.AIRTEL_MONEY: ["phone_number"],
        }
        for field_name in method_requirements.get(method, []):
            if not cleaned_data.get(field_name):
                self.add_error(field_name, "This field is required for the selected payment method.")

        if method == PaymentRequest.Method.AIRTEL_MONEY:
            if cleaned_data.get("airtel_number"):
                cleaned_data["phone_number"] = cleaned_data["airtel_number"]
            elif cleaned_data.get("phone_number"):
                cleaned_data["airtel_number"] = cleaned_data["phone_number"]
        elif method == PaymentRequest.Method.WALLET:
            cleaned_data["phone_number"] = cleaned_data.get("phone_number") or ""

        if method in {
            PaymentRequest.Method.MPESA_STK,
            PaymentRequest.Method.MPESA_PAYBILL,
            PaymentRequest.Method.AIRTEL_MONEY,
        } and cleaned_data.get("phone_number"):
            cleaned_data["phone_number"] = validate_kenyan_phone(cleaned_data["phone_number"])
            self.instance.phone_number = cleaned_data["phone_number"]

        metadata = dict(self.instance.metadata or {})
        metadata["lease_terms_required"] = self.allow_lease_term_entry
        self.instance.metadata = metadata

        computed_due_at = self.calculate_due_at(
            transaction_type,
            category,
            cleaned_data.get("lease_start_date"),
        )
        cleaned_data["due_at"] = computed_due_at
        self.instance.due_at = computed_due_at
        cleaned_data["title"] = self.build_title(plot, transaction_type, category)
        cleaned_data["description"] = (
            f"Checkout for {dict(PaymentRequest.Category.choices).get(category, 'payment').lower()}."
        )
        
        # Only enable escrow for deposit and balance payments (not stamp duty)
        cleaned_data["escrow_enabled"] = category in {
            PaymentRequest.Category.RESERVATION_DEPOSIT,
            PaymentRequest.Category.AGREEMENT_DEPOSIT,
            PaymentRequest.Category.ESCROW_DEPOSIT,
            PaymentRequest.Category.VERIFICATION_PACKAGE,
            PaymentRequest.Category.COMPLETION_BALANCE,
        }
        
        if transaction_type == PaymentRequest.TransactionType.LEASE:
            if self.active_deal:
                active_values = {
                    "lease_start_date": self.active_deal.lease_start_date,
                    "lease_end_date": self.active_deal.lease_end_date,
                    "intended_use": self.active_deal.intended_use,
                    "lease_security_deposit": self.active_deal.lease_security_deposit,
                    "notice_period_days": self.active_deal.notice_period_days,
                    "good_husbandry_required": self.active_deal.good_husbandry_required,
                    "soil_exit_test_required": self.active_deal.soil_exit_test_required,
                    "subject_to_sale": self.active_deal.subject_to_sale,
                }
                for field_name, value in active_values.items():
                    if cleaned_data.get(field_name) in {None, ""} and value not in {None, ""}:
                        cleaned_data[field_name] = value
                        setattr(self.instance, field_name, value)
            
            if self.allow_lease_term_entry:
                if not cleaned_data.get("lease_start_date"):
                    self.add_error("lease_start_date", "Lease start date is required for this lease checkout.")
                else:
                    self.instance.lease_start_date = cleaned_data.get("lease_start_date")
                
                if not cleaned_data.get("lease_end_date"):
                    self.add_error("lease_end_date", "Lease end date is required for this lease checkout.")
                else:
                    self.instance.lease_end_date = cleaned_data.get("lease_end_date")
                
                if cleaned_data.get("lease_start_date") and cleaned_data.get("lease_end_date"):
                    if cleaned_data["lease_end_date"] <= cleaned_data["lease_start_date"]:
                        self.add_error(
                            "lease_end_date",
                            "Lease end date must be after the lease start date.",
                        )
                
                if not cleaned_data.get("intended_use"):
                    self.add_error("intended_use", "Tell AgriPlot how the tenant will use the land.")
                else:
                    self.instance.intended_use = cleaned_data.get("intended_use")
                
                if not cleaned_data.get("lease_security_deposit") and plot:
                    lease_base = self.lease_base_amount(plot)
                    if lease_base:
                        cleaned_data["lease_security_deposit"] = lease_base
                        self.instance.lease_security_deposit = lease_base
                else:
                    self.instance.lease_security_deposit = cleaned_data.get("lease_security_deposit")
                
                if plot and plot.listing_type == "both":
                    cleaned_data["subject_to_sale"] = True
                    self.instance.subject_to_sale = True
                
                if cleaned_data.get("notice_period_days"):
                    self.instance.notice_period_days = cleaned_data.get("notice_period_days")
                
                if cleaned_data.get("good_husbandry_required") is not None:
                    self.instance.good_husbandry_required = cleaned_data.get("good_husbandry_required")
                
                if cleaned_data.get("soil_exit_test_required") is not None:
                    self.instance.soil_exit_test_required = cleaned_data.get("soil_exit_test_required")
            else:
                cleaned_data["lease_start_date"] = None
                cleaned_data["lease_end_date"] = None
                self.instance.lease_start_date = None
                self.instance.lease_end_date = None
        
        self.instance.title = cleaned_data["title"]
        self.instance.description = cleaned_data["description"]
        self.instance.escrow_enabled = cleaned_data["escrow_enabled"]

        cleaned_data["payment_method_metadata"] = {
            field_name: cleaned_data.get(field_name, "")
            for field_name in self.METHOD_DETAIL_FIELDS
            if cleaned_data.get(field_name)
        }
        return cleaned_data

    def clean_phone_number(self):
        value = self.cleaned_data.get("phone_number")
        if not value:
            return value
        return validate_kenyan_phone(value)

    def save(self, commit=True):
        instance = super().save(commit=False)
        metadata = dict(instance.metadata or {})
        metadata.update(self.cleaned_data.get("payment_method_metadata", {}))
        instance.metadata = metadata
        if commit:
            instance.save()
        return instance


class PaymentMilestoneForm(forms.ModelForm):
    class Meta:
        model = PaymentMilestone
        fields = ["title", "amount", "due_at", "evidence_notes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Seller uploads title and official search"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "due_at": DateTimePickerInput(attrs={"class": "form-control"}),
            "evidence_notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "What evidence should AgriPlot collect before payout?",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount"].required = False
        self.fields["due_at"].required = False
        self.fields["evidence_notes"].required = False


class PaymentDisputeForm(forms.ModelForm):
    class Meta:
        model = PaymentDispute
        fields = ["reason", "details"]
        widgets = {
            "reason": forms.Select(attrs={"class": "form-select"}),
            "details": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Summarize what happened, what was promised, and what evidence exists.",
                }
            ),
        }


class PaymentClosingStepForm(forms.ModelForm):
    submitter_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Name of the lawyer / officer handling this stage"}
        ),
    )
    submitter_phone = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Professional phone number"}
        ),
    )
    submitter_role = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. Buyer Advocate, Seller Advocate, Registrar"}
        ),
    )
    submitter_organisation = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Law firm, registry office, or organisation"}
        ),
    )
    buyer_advocate_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Buyer's advocate or firm"}
        ),
    )
    buyer_advocate_phone = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Buyer's advocate phone"}
        ),
    )
    seller_advocate_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Seller's advocate or firm"}
        ),
    )
    seller_advocate_phone = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Seller's advocate phone"}
        ),
    )
    buyer_accepts_agreement = forms.BooleanField(
        required=False,
        label="Buyer / tenant digitally confirms this agreement",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    seller_accepts_agreement = forms.BooleanField(
        required=False,
        label="Seller / landowner digitally confirms this agreement",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    
    # Stamp duty specific - note that platform never holds stamp duty
    stamp_duty_paid_to_kra = forms.BooleanField(
        required=False,
        label="I confirm that stamp duty has been paid directly to KRA via iTax",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Platform does not collect stamp duty. You must pay KRA directly and upload the receipt."
    )
    
    not_applicable = forms.BooleanField(
        required=False,
        label="Not Applicable",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input"}
        ),
    )

    class Meta:
        model = PaymentClosingStep
        fields = [
            "status",
            "notes",
            "document",
            "consent_reference_number",
            "meeting_date",
            "official_market_value",
            "assessed_stamp_duty",
            "original_title_received",
            "seller_id_copy_received",
            "transfer_forms_signed",
        ]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Add a short update, document reference, or blocker note.",
                }
            ),
            "document": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "consent_reference_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "LCB or consent reference number"}),
            "meeting_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "official_market_value": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "Official market value"}),
            "assessed_stamp_duty": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "Calculated stamp duty"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["notes"].required = False
        self.can_set_status = user_is_finance_admin(self.user)
        self.can_disburse_funds = user_is_escrow_admin(self.user)
        self.agreement_role = None
        step = self.instance if getattr(self.instance, "pk", None) else None
        
        allowed_field_map = {
            "offer": {"status", "notes", "document", "submitter_name", "submitter_phone", "submitter_role", "submitter_organisation"},
            "due_diligence": {"status", "notes"},
            "agreement": {
                "status",
                "notes",
                "document",
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
                "buyer_advocate_name",
                "buyer_advocate_phone",
                "seller_advocate_name",
                "seller_advocate_phone",
                "buyer_accepts_agreement",
                "seller_accepts_agreement",
            },
            "lcb_consent": {
                "status",
                "notes",
                "document",
                "consent_reference_number",
                "meeting_date",
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
            },
            "consents_clearances": {
                "status",
                "notes",
                "document",
                "consent_reference_number",
                "not_applicable",
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
            },
            "stamp_duty": {
                "status",
                "notes",
                "document",
                "official_market_value",
                "assessed_stamp_duty",
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
                "stamp_duty_paid_to_kra",
            },
            "completion_docs": {
                "status",
                "notes",
                "original_title_received",
                "seller_id_copy_received",
                "transfer_forms_signed",
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
            },
            "registration": {
                "status",
                "notes",
                "document",
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
            },
            "disbursement": {
                "status",
                "notes",
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
            },
            "reports": {
                "status",
                "notes",
            },
            "payment_security": {"status", "notes", "document"},
            "handover": {"status", "notes", "document"},
        }
        
        if step:
            metadata = dict(step.payment.metadata or {})
            actor_is_buyer = self.user and self.user == step.payment.buyer
            actor_is_seller = self.user and self.user == step.payment.seller
            
            if actor_is_buyer:
                self.agreement_role = "buyer"
            elif actor_is_seller:
                self.agreement_role = "seller"
            elif self.can_set_status:
                self.agreement_role = "admin"
            else:
                self.agreement_role = "viewer"

            # Add special handling for disbursement step (only escrow admins)
            if step.code == "disbursement" and not self.can_disburse_funds:
                self.fields["status"].widget = forms.HiddenInput()
                self.fields["status"].initial = step.status
                self.fields["status"].disabled = True

            for field_name in {
                "buyer_advocate_name",
                "buyer_advocate_phone",
                "seller_advocate_name",
                "seller_advocate_phone",
            }:
                self.fields[field_name].initial = metadata.get(field_name, "")
            
            submitter_details = (metadata.get("step_submitters") or {}).get(step.code, {})
            for field_name in {
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
            }:
                self.fields[field_name].initial = submitter_details.get(field_name, "")
            
            allowed_fields = set(allowed_field_map.get(step.code, {"status", "notes", "document"}))
            
            if not self.can_set_status:
                self.fields["status"].widget = forms.HiddenInput()
                self.fields["status"].required = False
                allowed_fields.add("status")
            
            if step.code == "agreement":
                self.fields["buyer_accepts_agreement"].initial = bool(step.buyer_confirmed_at)
                self.fields["seller_accepts_agreement"].initial = bool(step.seller_confirmed_at)

                # Both buyer and seller can confirm the agreement
                if self.can_set_status:
                    allowed_fields.update({
                        "document",
                        "submitter_name",
                        "submitter_phone",
                        "submitter_role",
                        "submitter_organisation",
                        "buyer_advocate_name",
                        "buyer_advocate_phone",
                        "seller_advocate_name",
                        "seller_advocate_phone",
                        "buyer_accepts_agreement",
                        "seller_accepts_agreement",
                    })
                elif actor_is_buyer:
                    allowed_fields.update({"buyer_accepts_agreement"})
                elif actor_is_seller:
                    allowed_fields.update({"seller_accepts_agreement"})
            
            # Stamp duty step special handling
            if step.code == "stamp_duty":
                # Set initial value for KRA payment confirmation
                self.fields["stamp_duty_paid_to_kra"].initial = bool(step.document)
            
            for name in list(self.fields.keys()):
                if name not in allowed_fields:
                    self.fields.pop(name)
            
            consent_metadata = (
                metadata.get("consent_clearances") or {}
            )

            if step.code == "consents_clearances" and "not_applicable" in self.fields:
                self.fields["not_applicable"].initial = (
                    consent_metadata.get(step.code, {})
                    .get("not_applicable", False)
                )

    def clean(self):
        cleaned_data = super().clean()
        step = self.instance if getattr(self.instance, "pk", None) else None
        if not step:
            return cleaned_data

        for field_name in [
            "submitter_phone",
            "buyer_advocate_phone",
            "seller_advocate_phone",
        ]:
            if field_name in self.fields and cleaned_data.get(field_name):
                try:
                    cleaned_data[field_name] = validate_kenyan_phone(cleaned_data.get(field_name))
                except forms.ValidationError as exc:
                    self.add_error(field_name, exc)

        for field_name, label in [
            ("submitter_name", "Submitter name"),
            ("buyer_advocate_name", "Buyer's advocate name"),
            ("seller_advocate_name", "Seller's advocate name"),
        ]:
            if field_name in self.fields and cleaned_data.get(field_name):
                try:
                    cleaned_data[field_name] = validate_person_name(cleaned_data.get(field_name), label)
                except forms.ValidationError as exc:
                    self.add_error(field_name, exc)

        requested_completion = cleaned_data.get("status") == PaymentClosingStep.Status.COMPLETED
        
        # Disbursement step requires escrow admin
        if step.code == "disbursement" and requested_completion:
            if not user_is_escrow_admin(self.user):
                self.add_error(
                    "status",
                    "Only escrow administrators can mark fund disbursement as complete."
                )
        
        if not self.can_set_status:
            cleaned_data["status"] = (
                step.status if step.status != PaymentClosingStep.Status.PENDING else PaymentClosingStep.Status.IN_PROGRESS
            )
            requested_completion = False

        if not requested_completion:
            return cleaned_data

        # Document validation based on step type
        if step.code in {"offer", "registration"} and not (
            cleaned_data.get("document") or step.document
        ):
            self.add_error("document", "Upload the supporting document before marking this step complete.")

        # Agreement step validation - both parties must confirm
        if step.code == "agreement":
            if step.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                # Only require document for purchase (lease agreement is generated)
                if not (step.document or cleaned_data.get("document")):
                    self.add_error("document", "Upload the executed sale agreement before completing this step.")
                
                # Both buyer and seller must confirm
                if not (step.buyer_confirmed_at or cleaned_data.get("buyer_accepts_agreement")):
                    self.add_error("buyer_accepts_agreement", "The buyer must digitally confirm the sale agreement.")
                if not (step.seller_confirmed_at or cleaned_data.get("seller_accepts_agreement")):
                    self.add_error("seller_accepts_agreement", "The seller must digitally confirm the sale agreement.")
            else:
                # Lease agreement - both parties confirm
                if not (step.buyer_confirmed_at or cleaned_data.get("buyer_accepts_agreement")):
                    self.add_error("buyer_accepts_agreement", "The tenant must digitally confirm the lease agreement.")
                if not (step.seller_confirmed_at or cleaned_data.get("seller_accepts_agreement")):
                    self.add_error("seller_accepts_agreement", "The landowner must digitally confirm the lease agreement.")

        # LCB Consent validation
        if step.code == "lcb_consent":
            required_fields = [
                ("submitter_name", "lawyer / officer name"),
                ("submitter_phone", "lawyer / officer phone"),
                ("submitter_role", "lawyer / officer role"),
                ("submitter_organisation", "law firm / office"),
                ("meeting_date", "LCB meeting date"),
                ("consent_reference_number", "LCB consent reference number"),
            ]

            for field_name, label in required_fields:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Enter the {label} before completing this step.")

            if not (cleaned_data.get("document") or step.document):
                self.add_error("document", "Upload the LCB consent documents before completing this step.")

        # Stamp Duty validation (paid directly to KRA)
        if step.code == "stamp_duty":
            # Verify buyer confirmed payment to KRA
            if not cleaned_data.get("stamp_duty_paid_to_kra"):
                self.add_error(
                    "stamp_duty_paid_to_kra",
                    "You must confirm that stamp duty has been paid directly to KRA via iTax."
                )
            
            required_fields = [
                ("submitter_name", "valuer / tax handler name"),
                ("submitter_phone", "valuer / tax handler phone"),
                ("submitter_role", "valuer / tax handler role"),
                ("submitter_organisation", "valuer / office / firm"),
            ]

            for field_name, label in required_fields:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Enter the {label} before completing this step.")
            
            if not (cleaned_data.get("document") or step.document):
                self.add_error("document", "Upload the KRA stamp duty receipt before completing this step.")
            
            if cleaned_data.get("official_market_value") in {None, ""}:
                self.add_error("official_market_value", "Enter the official market value before completing this step.")
            else:
                official_value = cleaned_data.get("official_market_value")
                if official_value <= 0:
                    self.add_error("official_market_value", "Official market value must be greater than zero.")
            
            if cleaned_data.get("assessed_stamp_duty") in {None, ""}:
                self.add_error("assessed_stamp_duty", "Enter the assessed stamp duty from KRA before completing this step.")
            else:
                assessed_duty = cleaned_data.get("assessed_stamp_duty")
                if assessed_duty <= 0:
                    self.add_error("assessed_stamp_duty", "Assessed stamp duty must be greater than zero.")

        # Completion Docs validation
        if step.code == "completion_docs":
            for field_name, label in [
                ("submitter_name", "buyer advocate / handler name"),
                ("submitter_phone", "buyer advocate / handler phone"),
                ("submitter_role", "submitter role"),
                ("submitter_organisation", "law firm / organisation"),
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Enter the {label} before completing this step.")
            
            for field_name, label in [
                ("original_title_received", "original title"),
                ("seller_id_copy_received", "seller ID / KRA copies"),
                ("transfer_forms_signed", "signed transfer forms"),
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Confirm the {label} before completing this step.")

        # Registration validation
        if step.code == "registration":
            for field_name, label in [
                ("submitter_name", "registrar / lawyer name"),
                ("submitter_phone", "registrar / lawyer phone"),
                ("submitter_role", "registrar / lawyer role"),
                ("submitter_organisation", "registry office / law firm"),
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Enter the {label} before completing this step.")
            
            if not (cleaned_data.get("document") or step.document):
                self.add_error("document", "Upload the new title deed or registration proof before completing this step.")

        # Disbursement validation (automatic, but can be manually completed by escrow admin)
        if step.code == "disbursement" and requested_completion:
            # Check if all conditions for disbursement are met
            payment = step.payment
            if not payment.purchase_registration_complete:
                self.add_error(
                    "status",
                    "Cannot disburse funds: Registration not complete. The new title deed must be issued first."
                )
            
            stamp_duty_complete = payment.closing_steps.filter(
                code="stamp_duty",
                status=PaymentClosingStep.Status.COMPLETED
            ).exists()
            
            if not stamp_duty_complete:
                self.add_error(
                    "status",
                    "Cannot disburse funds: Stamp duty payment to KRA not verified."
                )
            
            if not payment.metadata.get('deposit_paid') or not payment.metadata.get('balance_paid'):
                self.add_error(
                    "status",
                    "Cannot disburse funds: Not all funds have been received in escrow."
                )

        # ============================================================
        # LEGAL DOCUMENT VALIDATION - INTEGRATION WITH TRANSACTION MODEL
        # ============================================================
        from transactions.models import Transaction, TransactionDocument
        
        payment = step.payment
        
        # Check if there's a linked legal transaction
        legal_tx = None
        try:
            legal_tx = payment.legal_transaction
        except (Transaction.DoesNotExist, AttributeError):
            pass
        
        # Only check for purchase transactions that have a legal transaction linked
        if legal_tx and payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            # Map payment closing step to required legal documents
            legal_requirements = {
                'due_diligence': ['OFFICIAL_SEARCH', 'SURVEY_MAP'],
                'offer': ['LETTER_OF_OFFER'],
                'agreement': ['SALE_AGREEMENT'],
                'lcb_consent': ['LCB_CONSENT', 'SPOUSAL_CONSENT'],
                'completion_docs': ['TRANSFER_FORM', 'ORIGINAL_TITLE_DEED'],
                'stamp_duty': ['STAMP_DUTY_RECEIPT', 'VALUATION_REPORT'],
                'registration': ['NEW_TITLE_DEED'],
            }
            
            required_docs = legal_requirements.get(step.code, [])
            
            if required_docs and requested_completion:
                missing_docs = []
                
                for doc_type in required_docs:
                    has_doc = TransactionDocument.objects.filter(
                        transaction=legal_tx,
                        document_type=doc_type,
                        status='verified'
                    ).exists()
                    if not has_doc:
                        missing_docs.append(dict(TransactionDocument.DocType.choices).get(doc_type, doc_type))
                
                if missing_docs:
                    raise ValidationError(
                        f"Cannot complete this payment step. Missing legal documents in the Legal Workspace: {', '.join(missing_docs)}. "
                        "Please upload and verify these documents before proceeding."
                    )
                
                # Also check if legal stage is sufficiently advanced
                legal_stage_required = {
                    'due_diligence': 'due_diligence',
                    'offer': 'commitment',
                    'agreement': 'contracts',
                    'lcb_consent': 'statutory_consents',
                    'completion_docs': 'statutory_consents',
                    'stamp_duty': 'taxation',
                    'registration': 'registration',
                }
                
                required_stage = legal_stage_required.get(step.code)
                if required_stage:
                    stage_order = ['due_diligence', 'commitment', 'contracts', 'statutory_consents', 'taxation', 'registration']
                    if legal_tx.stage in stage_order and required_stage in stage_order:
                        current_idx = stage_order.index(legal_tx.stage)
                        required_idx = stage_order.index(required_stage)
                        
                        if current_idx < required_idx:
                            raise ValidationError(
                                f"Cannot complete this payment step. The legal transaction must be at the '{required_stage.replace('_', ' ').title()}' stage. "
                                f"Current legal stage: '{legal_tx.get_stage_display()}'. "
                                "Please advance the legal workspace first."
                            )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        payment = instance.payment
        metadata = dict(payment.metadata or {})
        
        for field_name in [
            "buyer_advocate_name",
            "buyer_advocate_phone",
            "seller_advocate_name",
            "seller_advocate_phone",
        ]:
            if field_name in self.cleaned_data:
                metadata[field_name] = self.cleaned_data.get(field_name, "")
        
        step_submitters = dict(metadata.get("step_submitters") or {})
        step_submitters[instance.code] = {
            field_name: self.cleaned_data.get(field_name, "")
            for field_name in [
                "submitter_name",
                "submitter_phone",
                "submitter_role",
                "submitter_organisation",
            ]
            if field_name in self.cleaned_data and self.cleaned_data.get(field_name)
        }
        metadata["step_submitters"] = step_submitters
        
        if instance.code == "agreement":
            agreement_acceptance = dict(metadata.get("agreement_acceptance") or {})
            if self.cleaned_data.get("buyer_accepts_agreement") and self.user == payment.buyer and not instance.buyer_confirmed_at:
                instance.buyer_confirmed_at = timezone.now()
            if self.cleaned_data.get("seller_accepts_agreement") and self.user == payment.seller and not instance.seller_confirmed_at:
                instance.seller_confirmed_at = timezone.now()
            if instance.buyer_confirmed_at:
                agreement_acceptance["buyer_confirmed_at"] = instance.buyer_confirmed_at.isoformat()
            if instance.seller_confirmed_at:
                agreement_acceptance["seller_confirmed_at"] = instance.seller_confirmed_at.isoformat()
            
            agreement_participants = dict(metadata.get("agreement_participants") or {})
            agreement_participants[instance.code] = {
                "buyer_advocate_name": self.cleaned_data.get("buyer_advocate_name", metadata.get("buyer_advocate_name", "")),
                "buyer_advocate_phone": self.cleaned_data.get("buyer_advocate_phone", metadata.get("buyer_advocate_phone", "")),
                "seller_advocate_name": self.cleaned_data.get("seller_advocate_name", metadata.get("seller_advocate_name", "")),
                "seller_advocate_phone": self.cleaned_data.get("seller_advocate_phone", metadata.get("seller_advocate_phone", "")),
                "buyer_confirmed_at": agreement_acceptance.get("buyer_confirmed_at", ""),
                "seller_confirmed_at": agreement_acceptance.get("seller_confirmed_at", ""),
                "transaction_type": payment.transaction_type,
            }
            metadata["agreement_acceptance"] = agreement_acceptance
            metadata["agreement_participants"] = agreement_participants
        
        # Track stamp duty KRA payment confirmation
        if instance.code == "stamp_duty":
            if self.cleaned_data.get("stamp_duty_paid_to_kra"):
                metadata["stamp_duty_confirmed_at"] = timezone.now().isoformat()
                metadata["stamp_duty_confirmed_by"] = self.user.id if self.user else None
        
        consent_metadata = dict(
            metadata.get("consent_clearances") or {}
        )

        if "not_applicable" in self.cleaned_data:
            consent_metadata[instance.code] = {
                "not_applicable": self.cleaned_data.get(
                    "not_applicable",
                    False
                )
            }

        metadata["consent_clearances"] = consent_metadata
        
        payment.metadata = metadata
        if commit:
            payment.save(update_fields=["metadata", "updated_at"])
            instance.save()
        
        # If this is the registration step being completed, trigger disbursement check
        if instance.code == "registration" and instance.status == PaymentClosingStep.Status.COMPLETED:
            from django.db import transaction
            from .models import PaymentRequest
            
            transaction.on_commit(lambda: payment.apply_transition("disburse_to_seller", actor=self.user))
        
        return instance