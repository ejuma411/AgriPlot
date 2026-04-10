def contact_verification_banner(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {
            "show_email_verification_banner": False,
            "contact_email_verified": False,
            "contact_phone_verified": False,
        }

    profile = getattr(request.user, "profile", None)
    contact_verification = getattr(request.user, "contact_verification", None)

    phone_verified = bool(getattr(profile, "phone_verified", False))
    email_verified = bool(getattr(profile, "email_verified", False))

    if contact_verification:
        phone_verified = phone_verified or bool(contact_verification.phone_verified)
        email_verified = email_verified or bool(contact_verification.email_verified)

    return {
        "show_email_verification_banner": bool(phone_verified and not email_verified),
        "contact_email_verified": email_verified,
        "contact_phone_verified": phone_verified,
    }
