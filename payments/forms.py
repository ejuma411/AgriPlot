from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

from django import forms
from django.utils import timezone

from listings.models import Plot

from .models import PaymentClosingStep, PaymentDispute, PaymentMilestone, PaymentRequest
from .permissions import user_is_finance_admin


class DateTimePickerInput(forms.DateTimeInput):
    input_type = "datetime-local"


class PaymentRequestForm(forms.ModelForm):
    DIRECT_TRANSACTION_CHOICES = [
        (PaymentRequest.TransactionType.PURCHASE, "Purchase"),
        (PaymentRequest.TransactionType.LEASE, "Lease"),
    ]
    DIRECT_CATEGORY_CHOICES = [
        (PaymentRequest.Category.COMMITMENT_FEE, "Commitment / Verification Fee"),
        (PaymentRequest.Category.RESERVATION_DEPOSIT, "Reservation Deposit"),
        (PaymentRequest.Category.AGREEMENT_DEPOSIT, "Agreement Deposit (10%)"),
        (PaymentRequest.Category.ESCROW_DEPOSIT, "Escrow Deposit"),
        (PaymentRequest.Category.STAMP_DUTY, "Stamp Duty"),
        (PaymentRequest.Category.COMPLETION_BALANCE, "Completion Balance"),
    ]
    DEFAULT_DUE_WINDOWS = {
        PaymentRequest.Category.COMMITMENT_FEE: timedelta(hours=24),
        PaymentRequest.Category.VIEWING_FEE: timedelta(hours=24),
        PaymentRequest.Category.RESERVATION_DEPOSIT: timedelta(hours=48),
        PaymentRequest.Category.AGREEMENT_DEPOSIT: timedelta(hours=72),
        PaymentRequest.Category.VERIFICATION_PACKAGE: timedelta(hours=72),
        PaymentRequest.Category.ESCROW_DEPOSIT: timedelta(hours=72),
        PaymentRequest.Category.STAMP_DUTY: timedelta(days=7),
        PaymentRequest.Category.COMPLETION_BALANCE: timedelta(days=14),
        PaymentRequest.Category.SERVICE_FEE: timedelta(hours=48),
    }
    FIXED_CATEGORY_AMOUNTS = {
        PaymentRequest.Category.COMMITMENT_FEE: Decimal("5000.00"),
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

    def __init__(self, *args, user=None, selected_plot=None, forced_category=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.selected_plot = selected_plot
        self.forced_category = forced_category
        self.allow_amount_override = False
        self.allow_due_at_override = user_is_finance_admin(user)
        self.simple_mpesa_checkout = True
        self.fields["plot"].queryset = Plot.objects.order_by("title")
        self.fields["plot"].required = False
        self.fields["due_at"].required = False
        self.fields["phone_number"].required = True
        self.fields["lease_start_date"].required = False
        self.fields["lease_end_date"].required = False
        self.fields["transaction_type"].choices = self.DIRECT_TRANSACTION_CHOICES
        self.fields["category"].choices = self.DIRECT_CATEGORY_CHOICES
        self.fields["category"].initial = PaymentRequest.Category.COMMITMENT_FEE
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
        self.fields["category"].help_text = (
            "Choose the stage you are paying for right now."
        )
        self.fields["amount"].help_text = (
            "AgriPlot calculates this automatically from the selected payment stage and the plot sale price."
        )
        self.fields["amount"].widget.attrs["readonly"] = True
        self.fields["amount"].widget.attrs["data-fixed-amount"] = "true"
        if self.forced_category:
            self.fields["category"].initial = self.forced_category
            self.fields["category"].widget = forms.HiddenInput()
            self.fields["category"].help_text = ""
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
        if self.instance and self.instance.pk:
            metadata = self.instance.metadata or {}
            for field_name in self.METHOD_DETAIL_FIELDS:
                if field_name in metadata:
                    self.fields[field_name].initial = metadata.get(field_name)
        if user and user.is_authenticated:
            profile = getattr(user, "profile", None)
            if profile and profile.phone:
                self.fields["phone_number"].initial = profile.phone
        default_amount = self.calculate_amount(
            selected_plot or self.initial.get("plot"),
            self.fields["transaction_type"].initial or self.initial.get("transaction_type"),
            self.forced_category
            or self.initial.get("category")
            or self.fields["category"].initial
            or self.fields["category"].choices[0][0],
        )
        if default_amount is not None:
            self.fields["amount"].initial = default_amount
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
        if category in cls.FIXED_CATEGORY_AMOUNTS:
            return cls.FIXED_CATEGORY_AMOUNTS[category]
        if not plot:
            return None
        if transaction_type == PaymentRequest.TransactionType.PURCHASE:
            if category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
                return cls.normalize_amount(Decimal(plot.price) * Decimal("0.10"))
            if category == PaymentRequest.Category.RESERVATION_DEPOSIT:
                return cls.normalize_amount(Decimal(plot.price) * Decimal("0.10"))
            if category == PaymentRequest.Category.ESCROW_DEPOSIT:
                return cls.normalize_amount(Decimal(plot.price) * Decimal("0.10"))
            if category == PaymentRequest.Category.STAMP_DUTY:
                rate = Decimal("0.02")
                if plot.market_zone in {"urban", "peri_urban"}:
                    rate = Decimal("0.04")
                return cls.normalize_amount(Decimal(plot.price) * rate)
            if category == PaymentRequest.Category.COMPLETION_BALANCE:
                return cls.normalize_amount(Decimal(plot.price) * Decimal("0.90"))
        if transaction_type == PaymentRequest.TransactionType.LEASE:
            lease_base = cls.lease_base_amount(plot)
            if lease_base and category in {
                PaymentRequest.Category.AGREEMENT_DEPOSIT,
                PaymentRequest.Category.RESERVATION_DEPOSIT,
                PaymentRequest.Category.ESCROW_DEPOSIT,
                PaymentRequest.Category.COMPLETION_BALANCE,
            }:
                return lease_base
        return None

    def clean(self):
        cleaned_data = super().clean()
        plot = cleaned_data.get("plot") or self.selected_plot
        transaction_type = cleaned_data.get("transaction_type")
        category = self.forced_category or cleaned_data.get("category")
        cleaned_data["category"] = category
        cleaned_data["method"] = PaymentRequest.Method.MPESA_STK
        self.instance.method = PaymentRequest.Method.MPESA_STK
        method = PaymentRequest.Method.MPESA_STK
        amount = cleaned_data.get("amount")
        calculated_amount = self.calculate_amount(plot, transaction_type, category)
        if transaction_type == PaymentRequest.TransactionType.PURCHASE:
            if calculated_amount in {None, ""}:
                self.add_error("amount", "AgriPlot could not calculate the amount for this sale stage.")
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

        computed_due_at = self.calculate_due_at(
            transaction_type,
            category,
            cleaned_data.get("lease_start_date"),
        )
        cleaned_data["due_at"] = computed_due_at
        self.instance.due_at = computed_due_at
        cleaned_data["title"] = self.build_title(plot, transaction_type, category)
        cleaned_data["description"] = (
            f"M-Pesa checkout for {dict(PaymentRequest.Category.choices).get(category, 'payment').lower()}."
        )
        cleaned_data["escrow_enabled"] = category in {
            PaymentRequest.Category.RESERVATION_DEPOSIT,
            PaymentRequest.Category.AGREEMENT_DEPOSIT,
            PaymentRequest.Category.ESCROW_DEPOSIT,
            PaymentRequest.Category.VERIFICATION_PACKAGE,
        }
        self.instance.title = cleaned_data["title"]
        self.instance.description = cleaned_data["description"]
        self.instance.escrow_enabled = cleaned_data["escrow_enabled"]

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
        step = self.instance if getattr(self.instance, "pk", None) else None
        allowed_field_map = {
            "offer": {"status", "notes", "document"},
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
            "payment_security": {"status", "notes", "document"},
            "handover": {"status", "notes", "document"},
        }
        if step:
            metadata = dict(step.payment.metadata or {})
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
            for name in list(self.fields.keys()):
                if name not in allowed_fields:
                    self.fields.pop(name)

    def clean(self):
        cleaned_data = super().clean()
        step = self.instance if getattr(self.instance, "pk", None) else None
        if not step:
            return cleaned_data

        status = cleaned_data.get("status")
        if not self.can_set_status:
            status = PaymentClosingStep.Status.COMPLETED
            cleaned_data["status"] = status

        if status != PaymentClosingStep.Status.COMPLETED:
            return cleaned_data

        if step.code in {"offer", "agreement", "registration"} and not (
            cleaned_data.get("document") or step.document
        ):
            self.add_error("document", "Upload the supporting document before marking this step complete.")

        if step.code == "agreement":
            for field_name, label in [
                ("submitter_name", "submitter name"),
                ("submitter_phone", "submitter phone"),
                ("submitter_role", "submitter role"),
                ("submitter_organisation", "submitter organisation"),
                ("buyer_advocate_name", "buyer's advocate name"),
                ("buyer_advocate_phone", "buyer's advocate phone"),
                ("seller_advocate_name", "seller's advocate name"),
                ("seller_advocate_phone", "seller's advocate phone"),
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Enter the {label} before completing this step.")

        if step.code == "lcb_consent":
            for field_name, label in [
                ("submitter_name", "lawyer / officer name"),
                ("submitter_phone", "lawyer / officer phone"),
                ("submitter_role", "lawyer / officer role"),
                ("submitter_organisation", "law firm / office"),
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Enter the {label} before completing this step.")
            if not (cleaned_data.get("document") or step.document):
                self.add_error("document", "Upload the LCB / spousal consent pack before completing this step.")
            if not cleaned_data.get("consent_reference_number"):
                self.add_error("consent_reference_number", "Enter the consent number before completing this step.")
            if not cleaned_data.get("meeting_date"):
                self.add_error("meeting_date", "Enter the LCB meeting date before completing this step.")

        if step.code == "stamp_duty":
            for field_name, label in [
                ("submitter_name", "valuer / tax handler name"),
                ("submitter_phone", "valuer / tax handler phone"),
                ("submitter_role", "valuer / tax handler role"),
                ("submitter_organisation", "valuer / office / firm"),
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Enter the {label} before completing this step.")
            if not (cleaned_data.get("document") or step.document):
                self.add_error("document", "Upload the stamp duty receipt before completing this step.")
            if cleaned_data.get("official_market_value") in {None, ""}:
                self.add_error("official_market_value", "Enter the official market value before completing this step.")
            if cleaned_data.get("assessed_stamp_duty") in {None, ""}:
                self.add_error("assessed_stamp_duty", "Enter the assessed stamp duty before completing this step.")

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

        if step.code == "registration":
            for field_name, label in [
                ("submitter_name", "registrar / lawyer name"),
                ("submitter_phone", "registrar / lawyer phone"),
                ("submitter_role", "registrar / lawyer role"),
                ("submitter_organisation", "registry office / law firm"),
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"Enter the {label} before completing this step.")

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
        payment.metadata = metadata
        if commit:
            payment.save(update_fields=["metadata", "updated_at"])
            instance.save()
        return instance
