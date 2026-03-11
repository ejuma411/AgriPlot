import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from notifications.notification_service import NotificationService
from .forms import ExtensionOfficerProfileForm, LandSurveyorProfileForm
from .models import ExtensionOfficer, LandSurveyor

logger = logging.getLogger(__name__)


@login_required
def request_extension_officer(request):
    """Allow a user to request extension officer role (pending approval)."""
    try:
        existing = request.user.extension_officer
        messages.info(request, "You already have an extension officer profile.")
        return redirect("verification:extension_dashboard")
    except ExtensionOfficer.DoesNotExist:
        existing = None

    if request.method == "POST":
        form = ExtensionOfficerProfileForm(request.POST, instance=existing)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.verified = False
            profile.is_active = False
            profile.save()
            messages.success(
                request, "Request submitted. An admin will review your details."
            )
            try:
                NotificationService.notify_role_request(
                    request.user,
                    "Extension Officer",
                    details={
                        "station": profile.station,
                        "counties": profile.assigned_counties,
                    },
                )
            except Exception as exc:
                logger.error("Role request notification failed: %s", exc)
            return redirect("listings:profile_management")
    else:
        form = ExtensionOfficerProfileForm(instance=existing)

    context = {
        "form": form,
        "role_label": "Extension Officer",
        "requirements": [
            "Official employee ID",
            "Designation and department",
            "Station/assigned office",
            "Qualifications and specializations",
            "Phone and office address",
            "Assigned counties and max daily tasks",
        ],
    }
    return render(request, "verification/request_role.html", context)


@login_required
def request_land_surveyor(request):
    """Allow a user to request land surveyor role (pending approval)."""
    try:
        existing = request.user.land_surveyor
        messages.info(request, "You already have a land surveyor profile.")
        return redirect("verification:surveyor_dashboard")
    except LandSurveyor.DoesNotExist:
        existing = None

    if request.method == "POST":
        form = LandSurveyorProfileForm(request.POST, instance=existing)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.verified = False
            profile.is_active = False
            profile.save()
            messages.success(
                request, "Request submitted. An admin will review your details."
            )
            try:
                NotificationService.notify_role_request(
                    request.user,
                    "Land Surveyor",
                    details={
                        "station": profile.station,
                        "counties": profile.assigned_counties,
                    },
                )
            except Exception as exc:
                logger.error("Role request notification failed: %s", exc)
            return redirect("listings:profile_management")
    else:
        form = LandSurveyorProfileForm(instance=existing)

    context = {
        "form": form,
        "role_label": "Land Surveyor",
        "requirements": [
            "Professional license number",
            "Designation and station",
            "Qualifications and experience",
            "Phone and office address",
            "Assigned counties and max daily tasks",
        ],
    }
    return render(request, "verification/request_role.html", context)

# PDF EXPORT VIEWS 
