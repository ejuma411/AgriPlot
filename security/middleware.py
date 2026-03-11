from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from accounts.models import Profile


class EnforceTwoFactorEnrollmentMiddleware:
    """Redirect authenticated users to 2FA setup if required but not enabled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            require_2fa = getattr(settings, "REQUIRE_2FA", True)
            require_enrollment = getattr(settings, "REQUIRE_2FA_ENROLLMENT", True)
            if require_2fa and require_enrollment:
                # Allowlist paths that should be accessible without 2FA enabled
                allowed_paths = {
                    reverse("listings:two_factor_setup"),
                    reverse("listings:logout"),
                    reverse("listings:home"),
                }
                if request.path.startswith("/admin/"):
                    return self.get_response(request)
                if request.path in allowed_paths or request.path.startswith("/static/") or request.path.startswith("/media/"):
                    return self.get_response(request)

                profile = getattr(user, "profile", None)
                if profile is None:
                    try:
                        profile, _ = Profile.objects.get_or_create(user=user)
                    except Exception:
                        profile = None
                if profile and not profile.has_2fa_enabled:
                    return redirect("listings:two_factor_setup")

        return self.get_response(request)
