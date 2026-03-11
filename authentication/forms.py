from django import forms


class TwoFactorSetupForm(forms.Form):
    """Verify TOTP setup during enrollment."""

    code = forms.CharField(
        max_length=6,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "123456"}),
    )


class TwoFactorVerifyForm(forms.Form):
    """Verify 2FA during login."""

    METHOD_CHOICES = [
        ("totp", "Authenticator App (TOTP)"),
        ("email", "Email OTP"),
        ("sms", "SMS OTP"),
        ("backup", "Backup Code"),
    ]
    method = forms.ChoiceField(choices=METHOD_CHOICES, required=True)
    code = forms.CharField(
        max_length=6,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "123456"}),
    )

