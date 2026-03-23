from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

from django import forms
from django.utils import timezone

from listings.models import Plot

from .models import PaymentDispute, PaymentMilestone, PaymentRequest
from .permissions import user_is_finance_admin


class DateTimePickerInput(forms.DateTimeInput):
    input_type = "datetime-local"


class PaymentRequestForm(forms.ModelForm):
    DEFAULT_DUE_WINDOWS = {
        PaymentRequest.Category.VIEWING_FEE: timedelta(hours=24),
        PaymentRequest.Category.RESERVATION_DEPOSIT: timedelta(hours=48),
        PaymentRequest.Category.VERIFICATION_PACKAGE: timedelta(hours=72),
        PaymentRequest.Category.ESCROW_DEPOSIT: timedelta(hours=72),
        PaymentRequest.Category.SERVICE_FEE: timedelta(hours=48),
    }
    FIXED_CATEGORY_AMOUNTS = {
        PaymentRequest.Category.VIEWING_FEE: Decimal("2500.00"),
        PaymentRequest.Category.VERIFICATION_PACKAGE: Decimal("5000.00"),
        PaymentRequest.Category.SERVICE_FEE: Decimal("3000.00"),
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
            "escrow_enabled",
            "due_at",
        ]
        widgets = {
            "plot": forms.Select(attrs={"class": "form-select"}),
            "transaction_type": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Reservation deposit for Plot A"}),
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
            "escrow_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "due_at": DateTimePickerInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, user=None, selected_plot=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.selected_plot = selected_plot
        self.allow_amount_override = user_is_finance_admin(user)
        self.allow_due_at_override = user_is_finance_admin(user)
        self.fields["plot"].queryset = Plot.objects.order_by("title")
        self.fields["plot"].required = False
        self.fields["due_at"].required = False
        self.fields["phone_number"].required = False
        self.fields["lease_start_date"].required = False
        self.fields["lease_end_date"].required = False
        if selected_plot is not None:
            self.fields["plot"].initial = selected_plot
            if selected_plot.listing_type == "sale":
                self.fields["transaction_type"].initial = PaymentRequest.TransactionType.PURCHASE
            elif selected_plot.listing_type == "lease":
                self.fields["transaction_type"].initial = PaymentRequest.TransactionType.LEASE
        if self.instance and self.instance.pk:
            metadata = self.instance.metadata or {}
            for field_name in self.METHOD_DETAIL_FIELDS:
                if field_name in metadata:
                    self.fields[field_name].initial = metadata.get(field_name)
        if user and user.is_authenticated:
            profile = getattr(user, "profile", None)
            if profile and profile.phone:
                self.fields["phone_number"].initial = profile.phone
        computed_amount = self.calculate_amount(
            selected_plot or self.initial.get("plot"),
            self.fields["transaction_type"].initial or self.initial.get("transaction_type"),
            self.initial.get("category") or self.fields["category"].initial or self.fields["category"].choices[0][0],
        )
        if computed_amount is not None:
            self.fields["amount"].initial = computed_amount
            self.fields["amount"].help_text = (
                f"This amount is system calculated for the selected checkout flow: KES {computed_amount}."
            )
        if not self.allow_amount_override:
            self.fields["amount"].widget.attrs["readonly"] = "readonly"
        if not self.allow_due_at_override:
            self.fields["due_at"].initial = self.calculate_due_at(
                self.fields["transaction_type"].initial or self.initial.get("transaction_type"),
                self.initial.get("category") or self.fields["category"].initial or self.fields["category"].choices[0][0],
                self.initial.get("lease_start_date"),
            )

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
        if category in cls.FIXED_CATEGORY_AMOUNTS:
            return cls.FIXED_CATEGORY_AMOUNTS[category]
        if not plot:
            return None
        if transaction_type == PaymentRequest.TransactionType.PURCHASE:
            if category == PaymentRequest.Category.RESERVATION_DEPOSIT:
                return cls.normalize_amount(Decimal(plot.price) * Decimal("0.05"))
            if category == PaymentRequest.Category.ESCROW_DEPOSIT:
                return cls.normalize_amount(Decimal(plot.price) * Decimal("0.10"))
        if transaction_type == PaymentRequest.TransactionType.LEASE:
            lease_base = cls.lease_base_amount(plot)
            if lease_base and category in {
                PaymentRequest.Category.RESERVATION_DEPOSIT,
                PaymentRequest.Category.ESCROW_DEPOSIT,
            }:
                return lease_base
        return None

    def clean(self):
        cleaned_data = super().clean()
        plot = cleaned_data.get("plot") or self.selected_plot
        transaction_type = cleaned_data.get("transaction_type")
        category = cleaned_data.get("category")
        method = cleaned_data.get("method")
        computed_amount = self.calculate_amount(plot, transaction_type, category)
        if computed_amount is not None:
            cleaned_data["amount"] = computed_amount
            self.instance.amount = computed_amount
        elif not self.allow_amount_override and plot:
            self.add_error(
                "amount",
                "This checkout flow needs a platform-defined amount and could not calculate one yet.",
            )

        method_requirements = {
            PaymentRequest.Method.MPESA_STK: ["phone_number"],
            PaymentRequest.Method.MPESA_PAYBILL: [
                "phone_number",
                "mpesa_reference",
                "mpesa_account_reference",
            ],
            PaymentRequest.Method.CARD: ["cardholder_name", "card_last4"],
            PaymentRequest.Method.BANK_TRANSFER: [
                "bank_name",
                "bank_account_name",
                "bank_account_number",
            ],
            PaymentRequest.Method.AIRTEL_MONEY: ["phone_number"],
            PaymentRequest.Method.WALLET: ["wallet_identifier"],
            PaymentRequest.Method.MANUAL_ESCROW: ["manual_escrow_notes"],
        }
        for field_name in method_requirements.get(method, []):
            if not cleaned_data.get(field_name):
                self.add_error(field_name, "This field is required for the selected payment method.")

        if method == PaymentRequest.Method.AIRTEL_MONEY:
            if cleaned_data.get("airtel_number"):
                cleaned_data["phone_number"] = cleaned_data["airtel_number"]
            elif cleaned_data.get("phone_number"):
                cleaned_data["airtel_number"] = cleaned_data["phone_number"]

        if not self.allow_due_at_override:
            computed_due_at = self.calculate_due_at(
                transaction_type,
                category,
                cleaned_data.get("lease_start_date"),
            )
            cleaned_data["due_at"] = computed_due_at
            self.instance.due_at = computed_due_at

        cleaned_data["payment_method_metadata"] = {
            field_name: cleaned_data.get(field_name, "")
            for field_name in self.METHOD_DETAIL_FIELDS
            if cleaned_data.get(field_name)
        }
        return cleaned_data

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
