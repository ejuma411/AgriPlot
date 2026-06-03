from django import forms
from django.contrib.auth.models import User
from django.urls import reverse

from verification.models import ExtensionOfficer, LandSurveyor

from .models import Agent, Profile
from .validators import (
    validate_kenyan_phone,
    validate_license_number,
    validate_national_id_number,
    validate_person_name,
    validate_realistic_email,
)


class _EmailCheckMixin:
    def _attach_email_check(self, field_name="email"):
        field = self.fields.get(field_name)
        if not field:
            return
        field.widget.attrs["data-email-check-url"] = reverse("listings:validate_email_input")
        field.widget.attrs["autocomplete"] = "email"


class AccountDetailsForm(_EmailCheckMixin, forms.Form):
    first_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    intent = forms.ChoiceField(
        choices=Profile._meta.get_field("intent").choices,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Choose the option that best describes how you use AgriPlot.",
    )
    address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self._attach_email_check()
        if user and not self.is_bound:
            profile, _ = Profile.objects.get_or_create(user=user)
            self.initial.update(
                {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "phone": profile.phone or "",
                    "intent": profile.intent,
                    "address": profile.address or "",
                }
            )

    def clean_first_name(self):
        return validate_person_name(self.cleaned_data.get("first_name"), "First name")

    def clean_last_name(self):
        return validate_person_name(self.cleaned_data.get("last_name"), "Last name")

    def clean_email(self):
        email = validate_realistic_email(self.cleaned_data.get("email"))
        existing = User.objects.filter(email__iexact=email)
        if self.user:
            existing = existing.exclude(pk=self.user.pk)
        if existing.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get("phone")
        if not phone:
            return ""
        return validate_kenyan_phone(phone)

    def clean_address(self):
        return (self.cleaned_data.get("address") or "").strip()


class AgentDetailsForm(forms.ModelForm):
    class Meta:
        model = Agent
        fields = [
            "phone",
            "license_number",
            "id_number",
            "contact_preference",
            "available_from",
            "available_to",
        ]
        widgets = {
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "license_number": forms.TextInput(attrs={"class": "form-control"}),
            "id_number": forms.TextInput(attrs={"class": "form-control"}),
            "contact_preference": forms.Select(attrs={"class": "form-select"}),
            "available_from": forms.TimeInput(attrs={"class": "form-control"}, format="%H:%M"),
            "available_to": forms.TimeInput(attrs={"class": "form-control"}, format="%H:%M"),
        }

    def clean_phone(self):
        return validate_kenyan_phone(self.cleaned_data.get("phone"))

    def clean_license_number(self):
        return validate_license_number(self.cleaned_data.get("license_number"))

    def clean_id_number(self):
        return validate_national_id_number(self.cleaned_data.get("id_number"))


class ExtensionOfficerEditForm(forms.ModelForm):
    class Meta:
        model = ExtensionOfficer
        fields = ["phone", "office_address"]
        widgets = {
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "office_address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def clean_phone(self):
        return validate_kenyan_phone(self.cleaned_data.get("phone"))

    def clean_office_address(self):
        return (self.cleaned_data.get("office_address") or "").strip()


class LandSurveyorEditForm(forms.ModelForm):
    class Meta:
        model = LandSurveyor
        fields = ["phone", "office_address"]
        widgets = {
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "office_address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def clean_phone(self):
        return validate_kenyan_phone(self.cleaned_data.get("phone"))

    def clean_office_address(self):
        return (self.cleaned_data.get("office_address") or "").strip()
