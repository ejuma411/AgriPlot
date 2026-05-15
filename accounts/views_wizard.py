import uuid

from django.contrib import messages
from django.core.files.storage import FileSystemStorage, default_storage
from django.shortcuts import redirect

from listings.forms import (
    LandownerStep1Form,
    LandownerStep2Form,
    LandownerStep3Form,
    LandownerStep4Form,
)

wizard_file_storage = FileSystemStorage(location="/tmp/agriplot_uploads")

try:
    from formtools.wizard.views import SessionWizardView
except ImportError:  # pragma: no cover
    class SessionWizardView:  # type: ignore[override]
        @classmethod
        def as_view(cls, *args, **kwargs):
            def _missing_wizard(*_args, **_kwargs):
                raise ImportError("django-formtools is required for the landowner wizard.")

            return _missing_wizard


FORMS = [
    ("personal", LandownerStep1Form),
    ("verification", LandownerStep2Form),
    ("documents", LandownerStep3Form),
    ("confirmation", LandownerStep4Form),
]

TEMPLATES = {
    "personal": "accounts/landowner_wizard_step.html",
    "verification": "accounts/landowner_wizard_step.html",
    "documents": "accounts/landowner_wizard_step.html",
    "confirmation": "accounts/landowner_wizard_step.html",
}


class LandownerWizard(SessionWizardView):
    form_list = FORMS
    file_storage = wizard_file_storage

    def get_template_names(self):
        return [TEMPLATES[self.steps.current]]

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        total = self.steps.count
        current_index = self.steps.step1
        context["progress_percent"] = int((current_index / total) * 100)
        context["step_labels"] = [
            {"key": "personal", "label": "Account"},
            {"key": "verification", "label": "Contact"},
            {"key": "documents", "label": "Documents"},
            {"key": "confirmation", "label": "Confirm"},
        ]
        return context

    def post(self, *args, **kwargs):
        request = self.request
        if request.POST.get("save_resume"):
            messages.success(
                request, "Progress saved. You can resume this registration later."
            )
            return redirect("listings:home")
        if request.POST.get("reset_wizard"):
            self.storage.reset()
            messages.info(request, "Registration progress cleared.")
            return redirect("listings:register_landowner")
        return super().post(*args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            messages.info(
                request, "You already have an account. Use the landowner upgrade form."
            )
            return redirect("listings:register_landowner_upgrade")
        return super().dispatch(request, *args, **kwargs)

    def done(self, form_list, **kwargs):
        """Process wizard forms and send OTP for registration."""
        try:
            step1 = self.get_cleaned_data_for_step("personal") or {}
            step2 = self.get_cleaned_data_for_step("verification") or {}
            step3 = self.get_cleaned_data_for_step("documents") or {}

            phone = step2.get("phone") or step1.get("phone")
            if not phone:
                messages.error(self.request, "Phone number is required.")
                return redirect("listings:register_landowner")

            self.request.session["reg_data"] = {
                "username": step1.get("username"),
                "email": step1.get("email"),
                "first_name": step1.get("first_name"),
                "last_name": step1.get("last_name"),
                "password": step1.get("password1"),
                "role": "landowner",
                "phone": phone,
                "address": f"{step2.get('region', '')}, {step2.get('city', '')}".strip(
                    ", "
                ),
            }
            self.request.session["reg_phone"] = phone

            stored_files = {}
            for field_name in [
                "national_id",
                "kra_pin",
                "title_deed",
                "land_search",
                "lcb_consent",
            ]:
                file_obj = step3.get(field_name)
                if not file_obj:
                    continue
                try:
                    file_obj.seek(0)
                except Exception:
                    pass
                file_path = default_storage.save(
                    f"tmp/landowner_{uuid.uuid4().hex}_{file_obj.name}", file_obj
                )
                stored_files[field_name] = file_path

            self.request.session["reg_files"] = stored_files

            from security.views_otp import send_otp_verification

            return send_otp_verification(self.request)
        except Exception as exc:
            messages.error(self.request, f"Error creating account: {exc}")
            return redirect("listings:register_choice")
