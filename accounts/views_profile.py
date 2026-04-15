from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import redirect, render

from listings.models import Plot, UserInterest

from .forms import (
    AccountDetailsForm,
    AgentDetailsForm,
    ExtensionOfficerEditForm,
    LandSurveyorEditForm,
)

from .models import Profile


def _build_profile_context(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    agent = getattr(user, "agent", None)
    landowner = getattr(user, "landownerprofile", None)
    extension_officer = getattr(user, "extension_officer", None)
    land_surveyor = getattr(user, "land_surveyor", None)

    is_landowner = landowner is not None
    is_agent = agent is not None
    is_extension = extension_officer is not None
    is_surveyor = land_surveyor is not None

    profile_type = "Buyer"
    if is_agent:
        profile_type = "Agent"
    elif is_landowner:
        profile_type = "Landowner"
    elif is_extension:
        profile_type = "Extension Officer"
    elif is_surveyor:
        profile_type = "Land Surveyor"

    two_factor_enabled = False
    if hasattr(user, "two_factor_settings"):
        two_factor_enabled = user.two_factor_settings.is_enabled
    elif profile:
        two_factor_enabled = profile.has_2fa_enabled

    def _doc(label, filefield):
        if not filefield:
            return None
        return {
            "label": label,
            "name": filefield.name.split("/")[-1] if filefield.name else label,
            "url": filefield.url,
        }

    role_requests = []
    if agent:
        docs = list(
            filter(
                None,
                [
                    _doc("License Document", agent.license_doc),
                    _doc("KRA PIN", agent.kra_pin),
                    _doc("Practicing Certificate", agent.practicing_certificate),
                    _doc("Good Conduct", agent.good_conduct),
                    _doc("Professional Indemnity", agent.professional_indemnity),
                ],
            )
        )
        role_requests.append(
            {"role": "Agent", "verified": agent.verified, "is_active": True, "docs": docs}
        )

    if landowner:
        docs = list(
            filter(
                None,
                [
                    _doc("National ID", landowner.national_id),
                    _doc("KRA PIN", landowner.kra_pin),
                    _doc("Title Deed", landowner.title_deed),
                    _doc("Land Search", landowner.land_search),
                    _doc("LCB Consent", landowner.lcb_consent),
                ],
            )
        )
        role_requests.append(
            {
                "role": "Landowner",
                "verified": landowner.verified,
                "is_active": True,
                "docs": docs,
            }
        )

    if extension_officer:
        role_requests.append(
            {
                "role": "Extension Officer",
                "verified": extension_officer.verified,
                "is_active": extension_officer.is_active,
                "docs": [],
            }
        )

    if land_surveyor:
        role_requests.append(
            {
                "role": "Land Surveyor",
                "verified": land_surveyor.verified,
                "is_active": land_surveyor.is_active,
                "docs": [],
            }
        )

    total_plots = 0
    verified_plots = 0
    pending_inquiries = 0
    if is_agent:
        total_plots = Plot.objects.filter(agent=agent).count()
        pending_inquiries = UserInterest.objects.filter(
            plot__agent=agent, status="pending"
        ).count()
    elif is_landowner:
        total_plots = Plot.objects.filter(landowner=landowner).count()
        pending_inquiries = UserInterest.objects.filter(
            plot__landowner=landowner, status="pending"
        ).count()

    return {
        "is_landowner": is_landowner,
        "is_agent": is_agent,
        "is_extension": is_extension,
        "is_surveyor": is_surveyor,
        "profile": profile,
        "agent": agent,
        "landowner": landowner,
        "extension_officer": extension_officer,
        "land_surveyor": land_surveyor,
        "profile_type": profile_type,
        "role_requests": role_requests,
        "two_factor_enabled": two_factor_enabled,
        "total_plots": total_plots,
        "verified_plots": verified_plots,
        "pending_inquiries": pending_inquiries,
    }


@login_required
def profile_management(request):
    context = _build_profile_context(request.user)
    return render(request, "accounts/dashboard/profile_management.html", context)


@login_required
def profile_edit(request):
    context = _build_profile_context(request.user)
    user = request.user
    profile = context["profile"]
    agent = context["agent"]
    extension_officer = context["extension_officer"]
    land_surveyor = context["land_surveyor"]

    account_form = AccountDetailsForm(user=user)
    agent_form = AgentDetailsForm(instance=agent) if agent else None
    extension_form = (
        ExtensionOfficerEditForm(instance=extension_officer) if extension_officer else None
    )
    surveyor_form = (
        LandSurveyorEditForm(instance=land_surveyor) if land_surveyor else None
    )

    if request.method == "POST":
        section = request.POST.get("section")
        if section == "account":
            account_form = AccountDetailsForm(request.POST, user=user)
            if account_form.is_valid():
                user.first_name = account_form.cleaned_data["first_name"]
                user.last_name = account_form.cleaned_data["last_name"]
                user.email = account_form.cleaned_data["email"]
                profile.phone = account_form.cleaned_data["phone"]
                profile.address = account_form.cleaned_data["address"]
                user.save()
                profile.save()
                messages.success(request, "Account details updated successfully.")
                return redirect("listings:profile_edit")
            messages.error(request, "Correct the account details below and try again.")
        elif section == "agent" and agent:
            agent_form = AgentDetailsForm(request.POST, instance=agent)
            if agent_form.is_valid():
                agent_form.save()
                messages.success(request, "Agent details updated successfully.")
                return redirect("listings:profile_edit")
            messages.error(request, "Correct the agent details below and try again.")
        elif section == "extension_officer" and extension_officer:
            extension_form = ExtensionOfficerEditForm(request.POST, instance=extension_officer)
            if extension_form.is_valid():
                extension_form.save()
                messages.success(request, "Extension officer details updated successfully.")
                return redirect("listings:profile_edit")
            messages.error(request, "Correct the extension officer details below and try again.")
        elif section == "land_surveyor" and land_surveyor:
            surveyor_form = LandSurveyorEditForm(request.POST, instance=land_surveyor)
            if surveyor_form.is_valid():
                surveyor_form.save()
                messages.success(request, "Surveyor details updated successfully.")
                return redirect("listings:profile_edit")
            messages.error(request, "Correct the surveyor details below and try again.")

    context.update(
        {
            "account_form": account_form,
            "agent_form": agent_form,
            "extension_form": extension_form,
            "surveyor_form": surveyor_form,
        }
    )
    return render(request, "accounts/dashboard/profile_edit.html", context)


@login_required
def account_settings(request):
    context = _build_profile_context(request.user)
    user = request.user

    if request.method == "POST":
        section = request.POST.get("section")
        if section == "change_password":
            current_password = request.POST.get("current_password", "")
            new_password = request.POST.get("new_password", "")
            confirm_password = request.POST.get("confirm_password", "")
            if not user.check_password(current_password):
                messages.error(request, "Current password is incorrect.")
            elif new_password != confirm_password:
                messages.error(request, "New passwords do not match.")
            elif len(new_password) < 8:
                messages.error(request, "New password must be at least 8 characters.")
            else:
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated successfully.")
        return redirect("listings:account_settings")

    return render(request, "accounts/dashboard/settings.html", context)
