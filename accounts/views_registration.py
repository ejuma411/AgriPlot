import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import DisallowedHost
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.shortcuts import redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme

from listings.forms import (
    AgentRegistrationForm,
    AgentUpgradeForm,
    BuyerRegistrationForm,
    LandownerUpgradeForm,
)
from .validators import email_validation_report

from .models import Agent, LandownerProfile, Profile

logger = logging.getLogger(__name__)


def _safe_next_url(request, fallback="listings:home"):
    """Allow only local redirects from ?next=..."""
    next_url = request.GET.get("next") or request.POST.get("next")
    try:
        current_host = request.get_host()
    except DisallowedHost:
        return resolve_url(fallback)
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={current_host},
        require_https=request.is_secure(),
    ):
        return next_url
    return resolve_url(fallback)


def _store_registration_files(files, field_names):
    """Persist uploaded files temporarily and return storage paths."""
    stored = {}
    for field in field_names:
        upload = files.get(field)
        if not upload:
            continue
        filename = f"registration_uploads/{uuid.uuid4().hex}_{upload.name}"
        stored[field] = default_storage.save(filename, upload)
    return stored


def register_choice(request):
    """Registration entrypoint: only buyer registration is allowed."""
    return redirect("listings:register_buyer")


def register_buyer(request):
    role = request.GET.get("role")
    requested_role = "buyer"
    if request.method == "GET" and role:
        role = role.strip().lower()
        if role == "landowner":
            return redirect("listings:register_landowner")
        if role == "agent":
            return redirect("listings:register_agent")
        if role in ("extension", "extension_officer"):
            requested_role = "extension_officer"
            if request.user.is_authenticated:
                return redirect("verification:request_extension_officer")
            request.session["reg_target_role"] = "extension_officer"
        if role in ("surveyor", "land_surveyor"):
            requested_role = "land_surveyor"
            if request.user.is_authenticated:
                return redirect("verification:request_land_surveyor")
            request.session["reg_target_role"] = "land_surveyor"

    if request.method == "POST":
        form = BuyerRegistrationForm(request.POST)
        if form.is_valid():
            request.session["reg_data"] = {
                "username": form.cleaned_data["username"],
                "email": form.cleaned_data["email"],
                "first_name": form.cleaned_data["first_name"],
                "last_name": form.cleaned_data["last_name"],
                "password": form.cleaned_data["password1"],
                "role": "buyer",
                "phone": form.cleaned_data["phone"],
            }
            request.session["reg_phone"] = form.cleaned_data["phone"]

            from security.views_otp import send_otp_verification

            return send_otp_verification(request)
    else:
        form = BuyerRegistrationForm()

    return render(
        request,
        "accounts/register_buyer.html",
        {
            "form": form,
            "requested_role": requested_role,
            "email_check_url": resolve_url("listings:validate_email_input"),
        },
    )


@login_required
def register_landowner(request):
    """Upgrade an existing user to landowner."""
    landowner_profile = LandownerProfile.objects.filter(user=request.user).first()
    if request.method == "POST":
        form = LandownerUpgradeForm(
            request.POST, request.FILES, instance=landowner_profile, user=request.user
        )
        if form.is_valid():
            try:
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.role = "landowner"
                profile.save()
                form.save(user=request.user)
                messages.success(
                    request,
                    "Landowner documents submitted. Please wait for verification.",
                )
                return redirect(_safe_next_url(request))
            except Exception as exc:
                messages.error(request, "Error submitting landowner details.")
                logger.error("Landowner upgrade error: %s", exc)
    else:
        form = LandownerUpgradeForm(instance=landowner_profile, user=request.user)

    return render(
        request,
        "accounts/register_landowner.html",
        {
            "form": form,
            "is_upgrade_flow": request.user.is_authenticated,
        },
    )


def register_agent(request):
    """Register as agent (new user) or upgrade (existing user)."""
    if not request.user.is_authenticated:
        if request.method == "POST":
            form = AgentRegistrationForm(request.POST, request.FILES)
            if form.is_valid():
                request.session["reg_data"] = {
                    "username": form.cleaned_data["username"],
                    "email": form.cleaned_data["email"],
                    "first_name": form.cleaned_data["first_name"],
                    "last_name": form.cleaned_data["last_name"],
                    "password": form.cleaned_data["password1"],
                    "role": "agent",
                    "phone": form.cleaned_data["phone"],
                    "id_number": form.cleaned_data["id_number"],
                    "license_number": form.cleaned_data["license_number"],
                    "company_name": form.cleaned_data.get("company_name", ""),
                    "earb_registration_number": form.cleaned_data["earb_registration_number"],
                }
                request.session["reg_phone"] = form.cleaned_data["phone"]
                request.session["reg_files"] = _store_registration_files(
                    request.FILES,
                    [
                        "license_doc",
                        "kra_pin",
                        "tax_compliance_certificate",
                        "practicing_certificate",
                        "good_conduct",
                        "professional_indemnity",
                    ],
                )
                from security.views_otp import send_otp_verification

                return send_otp_verification(request)
        else:
            form = AgentRegistrationForm()
        return render(
            request,
            "accounts/register_agent.html",
            {
                "form": form,
                "is_upgrade_flow": False,
                "email_check_url": resolve_url("listings:validate_email_input"),
            },
        )

    agent_profile = Agent.objects.filter(user=request.user).first()
    if request.method == "POST":
        form = AgentUpgradeForm(
            request.POST,
            request.FILES,
            instance=agent_profile,
            user=request.user,
        )
        if form.is_valid():
            try:
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.role = "agent"
                profile.save()
                form.save(user=request.user)
                messages.success(
                    request,
                    "Agent documents submitted. Please wait for verification.",
                )
                return redirect(_safe_next_url(request))
            except Exception as exc:
                messages.error(request, "Error submitting agent details.")
                logger.error("Agent upgrade error: %s", exc)
    else:
        form = AgentUpgradeForm(instance=agent_profile, user=request.user)

    return render(
        request,
        "accounts/register_agent.html",
        {
            "form": form,
            "is_upgrade_flow": True,
        },
    )


def register_landowner_simple(request):
    """Backward-compatibility alias for the landowner registration path."""
    return redirect("listings:register_landowner_upgrade")


def validate_email_input(request):
    email = request.GET.get("email", "")
    report = email_validation_report(email)
    exists = False
    if report["valid"]:
        from django.contrib.auth.models import User

        existing = User.objects.filter(email__iexact=report["normalized"])
        if request.user.is_authenticated:
            existing = existing.exclude(pk=request.user.pk)
        exists = existing.exists()

    valid = report["valid"] and not exists
    message = report["message"]
    if exists:
        message = "An account with this email already exists."
    elif valid:
        message = "Email looks valid and available."

    return JsonResponse(
        {
            "ok": True,
            "valid": valid,
            "exists": exists,
            "normalized": report["normalized"],
            "message": message,
            "domain_exists": report["domain_exists"],
        }
    )
