from django import forms


class OTPVerificationForm(forms.Form):
    """Form for OTP verification."""

    otp = forms.CharField(
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg text-center",
                "placeholder": "000000",
                "autocomplete": "off",
            }
        ),
        help_text="Enter the 6-digit code sent to your phone",
    )

    def clean_otp(self):
        otp = self.cleaned_data.get("otp")
        if not otp.isdigit():
            raise forms.ValidationError("OTP must contain only numbers")
        return otp


class PhoneResendForm(forms.Form):
    """Simple form for resending OTP."""

    phone = forms.CharField(max_length=15, widget=forms.HiddenInput())

