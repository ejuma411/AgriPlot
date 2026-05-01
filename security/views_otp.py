# listings/views_otp.py

import random
import os
from datetime import timedelta
from django.core import signing
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth import login
from django.core.files.storage import default_storage
from django.conf import settings
from django.core.files.base import File
from django.contrib.auth.models import User
from django.urls import reverse
from notifications.services.sms_service import TextSMSService
from notifications.notification_service import NotificationService
from accounts.models import Profile, LandownerProfile, Agent
from security.models import PhoneOTP, EmailOTP, PhoneEmailVerification
from security.forms import OTPVerificationForm
import logging

logger = logging.getLogger(__name__)


EMAIL_VERIFICATION_SALT = "security.email_verification"
OTP_CHANNEL_SESSION_KEY = "reg_otp_channels"

def generate_otp():
    """Generate 6-digit OTP"""
    return str(random.randint(100000, 999999))


def _email_verification_signer():
    return signing.TimestampSigner(salt=EMAIL_VERIFICATION_SALT)


def build_email_verification_token(user):
    email = (user.email or "").strip().lower()
    payload = f"{user.pk}:{email}"
    return _email_verification_signer().sign(payload)


def _email_verification_url(request, user):
    token = build_email_verification_token(user)
    path = reverse("security:verify_email", args=[token])
    return f"{settings.SITE_URL}{path}"


def send_email_verification_link(request, user):
    if not getattr(user, "email", ""):
        return False

    display_name = user.get_full_name().strip() or user.username or "there"
    result = NotificationService.send_email(
        recipient=user.email,
        subject="Verify your AgriPlot email address",
        template="email_verification_link",
        context={
            "user": user,
            "display_name": display_name,
            "verification_url": _email_verification_url(request, user),
            "support_url": settings.SITE_URL + "/contact-support/",
        },
        immediate=True,
    )
    return bool(result)


def _mark_email_verified(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])
    contact, _ = PhoneEmailVerification.objects.get_or_create(
        user=user,
        defaults={
            "phone_number": getattr(profile, "phone", "") or "",
            "email": user.email or "",
        },
    )
    contact.email = user.email or contact.email
    contact.email_verified = True
    contact.email_verified_at = timezone.now()
    contact.save(update_fields=["email", "email_verified", "email_verified_at", "updated_at"])


def _resolve_otp_provider():
    otp_provider = getattr(settings, "OTP_PROVIDER", "email")
    if otp_provider not in ("email", "sms", "both"):
        otp_provider = "email"
    return otp_provider


def _deliver_otp(request, *, phone, email, otp, reg_data):
    otp_provider = _resolve_otp_provider()
    sent_channels = []
    sms_error_message = None
    email_error_message = None

    if otp_provider in ("sms", "both"):
        try:
            sms = TextSMSService()
            result = sms.send_otp(phone, otp)
            if bool(result.get("success")):
                sent_channels.append("sms")
            else:
                sms_error_message = result.get("error", "Unknown SMS error")
                logger.error("Failed to send SMS OTP: %s", sms_error_message)
        except Exception as exc:
            sms_error_message = str(exc)
            logger.error("Exception sending SMS OTP: %s", exc, exc_info=True)

    should_send_email = otp_provider in ("email", "both") or (
        otp_provider == "sms" and email and "sms" not in sent_channels
    )
    if should_send_email and email:
        try:
            email_log = NotificationService.send_email(
                recipient=email,
                subject="AgriPlot verification code",
                template="otp_verification",
                context={
                    "user": None,
                    "display_name": f"{reg_data.get('first_name', '')} {reg_data.get('last_name', '')}".strip() or reg_data.get('username', 'there'),
                    "otp": otp,
                    "expiry_minutes": 10,
                    "support_url": settings.SITE_URL + "/contact-support/",
                },
                immediate=True,
            )
            if email_log:
                sent_channels.append("email")
            else:
                email_error_message = "Email delivery queue is unavailable."
                logger.error("Failed to queue email OTP for %s", email)
        except Exception as exc:
            email_error_message = str(exc)
            logger.error("Failed to send email OTP: %s", exc, exc_info=True)

    request.session[OTP_CHANNEL_SESSION_KEY] = sent_channels
    request.session.modified = True
    return {
        "provider": otp_provider,
        "sent_channels": sent_channels,
        "sms_error": sms_error_message,
        "email_error": email_error_message,
    }


def _otp_channel_for_template(request, otp_provider):
    sent_channels = request.session.get(OTP_CHANNEL_SESSION_KEY, [])
    if sent_channels == ["sms"]:
        return "sms"
    if sent_channels == ["email"]:
        return "email"
    if len(sent_channels) > 1:
        return "both"
    return otp_provider

def send_otp_verification(request):
    """Step 1: Send OTP to phone/email based on settings"""
    phone = request.session.get('reg_phone')
    reg_data = request.session.get('reg_data')
    
    if not phone or not reg_data:
        if request.user.is_authenticated:
            messages.info(request, "Your account is already active. Continue from your dashboard.")
            return redirect('listings:dashboard_router')
        messages.error(request, "Session expired. Please register again.")
        return redirect('listings:register_choice')
    
    otp_provider = getattr(settings, "OTP_PROVIDER", "email")
    if otp_provider not in ("email", "sms", "both"):
        otp_provider = "email"

    email = reg_data.get('email')
    if otp_provider in ("email", "both") and not email:
        messages.error(request, "Missing email for verification.")
        return redirect('listings:register_choice')

    # Generate OTP
    otp = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=10)

    # Store OTP(s)
    if otp_provider in ("sms", "both"):
        PhoneOTP.objects.create(
            phone=phone,
            otp=otp,
            purpose='registration',
            expires_at=expires_at
        )
    if otp_provider in ("email", "both"):
        EmailOTP.objects.create(
            email=email,
            otp=otp,
            purpose='registration',
            expires_at=expires_at
        )

    delivery = _deliver_otp(
        request,
        phone=phone,
        email=email,
        otp=otp,
        reg_data=reg_data,
    )

    # FIX: Use the correct URL namespace for verify_otp
    # The verify_otp view is in the 'security' app
    from django.urls import reverse
    from django.urls import NoReverseMatch
    
    # Determine the correct redirect URL based on what's available
    verify_otp_url = None
    
    # Try different possible namespace combinations
    possible_names = [
        'security:verify_otp',
        'verify_otp',
        'listings:verify_otp',
        'accounts:verify_otp',
    ]
    
    for name in possible_names:
        try:
            verify_otp_url = reverse(name)
            break
        except NoReverseMatch:
            continue
    
    # If none found, check the URL patterns directly
    if not verify_otp_url:
        # Fallback: construct URL manually or show error
        logger.error("Could not find verify_otp URL pattern")
        messages.error(request, "System configuration error. Please contact support.")
        return redirect('listings:register_choice')
    
    if delivery["sent_channels"]:
        if delivery["sent_channels"] == ["sms"]:
            messages.success(request, "Verification code sent to your phone.")
        elif delivery["sent_channels"] == ["email"]:
            if otp_provider == "sms":
                messages.warning(request, "SMS delivery is unavailable right now, so we sent the verification code to your email instead.")
            else:
                messages.success(request, "Verification code sent to your email.")
        else:
            messages.success(request, f"Verification code sent via {', '.join(delivery['sent_channels'])}. Check your messages.")
        return redirect(verify_otp_url)

    errors = []
    if delivery["sms_error"]:
        errors.append(f"SMS: {delivery['sms_error']}")
    if delivery["email_error"]:
        errors.append(f"Email: {delivery['email_error']}")
    messages.error(request, f"Failed to send verification code. {'; '.join(errors)}")
    return redirect('listings:register_choice')

def verify_otp(request):
    """Step 2: Verify OTP and complete registration"""
    if request.method == 'POST':
        otp_entered = request.POST.get('otp')
        phone = request.session.get('reg_phone')
        reg_data = request.session.get('reg_data')
        reg_files = request.session.get('reg_files', {})
        
        if not phone or not reg_data:
            if request.user.is_authenticated:
                messages.info(request, "Your account is already active. Continue from your dashboard.")
                return redirect('listings:dashboard_router')
            messages.error(request, "Session expired. Please register again.")
            return redirect('listings:register_choice')

        otp_provider = _resolve_otp_provider()
        delivered_channels = request.session.get(OTP_CHANNEL_SESSION_KEY, [])
        email = reg_data.get('email')

        # Check OTP
        try:
            verified = False
            if ("sms" in delivered_channels) or (not delivered_channels and otp_provider in ("sms", "both")):
                otp_record = PhoneOTP.objects.filter(
                    phone=phone,
                    otp=otp_entered,
                    purpose='registration',
                    is_verified=False,
                    expires_at__gt=timezone.now()
                ).latest('created_at')
                otp_record.is_verified = True
                otp_record.save()
                verified = True

            if (("email" in delivered_channels) or (not delivered_channels and otp_provider in ("email", "both"))) and not verified:
                email_record = EmailOTP.objects.filter(
                    email=email,
                    otp=otp_entered,
                    purpose='registration',
                    is_verified=False,
                    expires_at__gt=timezone.now()
                ).latest('created_at')
                email_record.is_verified = True
                email_record.save()
                verified = True

            if not verified:
                raise EmailOTP.DoesNotExist()
            
            # Create user
            user = User.objects.create_user(
                username=reg_data['username'],
                email=reg_data['email'],
                first_name=reg_data['first_name'],
                last_name=reg_data['last_name'],
                password=reg_data['password']
            )
            
            # Create or update profile (avoid unique constraint if profile was created elsewhere)
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role = reg_data['role']
            profile.phone = phone
            profile.phone_verified = "sms" in delivered_channels or (not delivered_channels and otp_provider in ("sms", "both"))
            profile.email_verified = False
            if reg_data.get('address'):
                profile.address = reg_data.get('address')
            profile.save()

            PhoneEmailVerification.objects.get_or_create(
                user=user,
                defaults={
                    'phone_number': phone,
                    'email': reg_data.get('email', ''),
                    'phone_verified': profile.phone_verified,
                    'email_verified': False,
                    'phone_verified_at': timezone.now() if profile.phone_verified else None,
                    'email_verified_at': None,
                }
            )
            
            def _attach_file(instance, field_name, path):
                if not path:
                    return
                try:
                    with default_storage.open(path, 'rb') as f:
                        getattr(instance, field_name).save(os.path.basename(path), File(f), save=False)
                finally:
                    default_storage.delete(path)

            # Create role-specific profile based on registration type
            if reg_data['role'] == 'landowner':
                landowner = LandownerProfile(
                    user=user,
                    verified=False
                )
                _attach_file(landowner, 'national_id', reg_files.get('national_id'))
                _attach_file(landowner, 'kra_pin', reg_files.get('kra_pin'))
                _attach_file(landowner, 'title_deed', reg_files.get('title_deed'))
                _attach_file(landowner, 'land_search', reg_files.get('land_search'))
                _attach_file(landowner, 'lcb_consent', reg_files.get('lcb_consent'))
                landowner.save()
                logger.info(f"Landowner profile created for {user.username}")

            elif reg_data['role'] == 'agent':
                agent = Agent(
                    user=user,
                    phone=phone,
                    id_number=reg_data.get('id_number', ''),
                    license_number=reg_data.get('license_number', ''),
                    verified=False
                )
                _attach_file(agent, 'license_doc', reg_files.get('license_doc'))
                _attach_file(agent, 'kra_pin', reg_files.get('kra_pin'))
                _attach_file(agent, 'practicing_certificate', reg_files.get('practicing_certificate'))
                _attach_file(agent, 'good_conduct', reg_files.get('good_conduct'))
                _attach_file(agent, 'professional_indemnity', reg_files.get('professional_indemnity'))
                agent.save()
                logger.info(f"Agent profile created for {user.username}")
            
            # Auto login
            login(request, user)

            email_link_sent = send_email_verification_link(request, user)

            # Clear session data
            target_role = request.session.get('reg_target_role')
            session_keys = ['reg_phone', 'reg_data', 'reg_files', 'reg_target_role']
            for key in session_keys:
                if key in request.session:
                    del request.session[key]
            if OTP_CHANNEL_SESSION_KEY in request.session:
                del request.session[OTP_CHANNEL_SESSION_KEY]
            # Clear wizard session data if any
            wizard_keys = [k for k in request.session.keys() if k.startswith('landownerwizard')]
            for key in wizard_keys:
                if key in request.session:
                    del request.session[key]

            if email_link_sent:
                messages.success(
                    request,
                    "Account created successfully. Your phone is verified, and we sent an email verification link to complete your account."
                )
            else:
                messages.warning(
                    request,
                    "Account created successfully and your phone is verified, but we could not send the email verification link yet. Use the resend email option from your dashboard."
                )

            # Redirect based on role
            if target_role == 'extension_officer':
                return redirect('verification:request_extension_officer')
            if target_role == 'land_surveyor':
                return redirect('verification:request_land_surveyor')
            if reg_data['role'] == 'agent':
                messages.info(request, "Your agent account is pending verification. You'll be able to list plots once verified.")
                return redirect('listings:dashboard_router')
            elif reg_data['role'] == 'landowner':
                messages.info(request, "Your landowner account is pending verification. You'll be able to list plots once verified.")
                return redirect('listings:dashboard_router')
            else:
                return redirect('listings:home')
                
        except (PhoneOTP.DoesNotExist, EmailOTP.DoesNotExist):
            messages.error(request, "Invalid or expired OTP. Please try again.")
            form = OTPVerificationForm()
            return render(
                request,
                'security/verify_otp.html',
                {
                    'phone': phone,
                    'channel': _otp_channel_for_template(request, otp_provider),
                    'form': form,
                }
            )
        except Exception as e:
            logger.error(f"Error completing registration: {str(e)}", exc_info=True)
            messages.error(request, "An error occurred. Please try again.")
            return redirect('listings:register_choice')
    
    # GET request - show OTP verification form
    phone = request.session.get('reg_phone')
    if not phone:
        if request.user.is_authenticated:
            messages.info(request, "Your phone verification step is already complete.")
            return redirect('listings:dashboard_router')
        return redirect('listings:register_choice')
    
    otp_provider = _resolve_otp_provider()
    form = OTPVerificationForm()
    return render(
        request,
        'security/verify_otp.html',
        {
            'phone': phone,
            'channel': _otp_channel_for_template(request, otp_provider),
            'form': form,
        }
    )


def resend_otp(request):
    """Resend OTP to phone"""
    if request.method == 'POST':
        phone = request.session.get('reg_phone')
        reg_data = request.session.get('reg_data') or {}
        email = reg_data.get('email')
        
        if not phone:
            messages.error(request, "Session expired. Please register again.")
            return redirect('listings:register_choice')
        
        otp_provider = _resolve_otp_provider()

        # Generate new OTP
        otp = generate_otp()
        expires_at = timezone.now() + timedelta(minutes=10)
        
        if otp_provider in ("sms", "both"):
            PhoneOTP.objects.create(
                phone=phone,
                otp=otp,
                purpose='registration',
                expires_at=expires_at
            )
        if otp_provider in ("email", "both") and email:
            EmailOTP.objects.create(
                email=email,
                otp=otp,
                purpose='registration',
                expires_at=expires_at
            )

        delivery = _deliver_otp(
            request,
            phone=phone,
            email=email,
            otp=otp,
            reg_data=reg_data,
        )

        if delivery["sent_channels"]:
            if delivery["sent_channels"] == ["email"] and otp_provider == "sms":
                messages.warning(request, "SMS delivery is unavailable right now, so we sent the new code to your email instead.")
            else:
                messages.success(request, "New verification code sent.")
        else:
            errors = []
            if delivery["sms_error"]:
                errors.append(f"SMS: {delivery['sms_error']}")
            if delivery["email_error"]:
                errors.append(f"Email: {delivery['email_error']}")
            messages.error(request, f"Failed to send code. {'; '.join(errors)}")
        
        return redirect('security:verify_otp')
    
    return redirect('listings:register_choice')


def verify_email(request, token):
    try:
        unsigned = _email_verification_signer().unsign(token, max_age=60 * 60 * 24 * 3)
        user_id, email = unsigned.split(":", 1)
        user = User.objects.get(pk=int(user_id), email__iexact=email)
    except (signing.BadSignature, signing.SignatureExpired, User.DoesNotExist, ValueError):
        messages.error(request, "This email verification link is invalid or has expired.")
        if request.user.is_authenticated:
            return redirect("listings:profile_management")
        return redirect("login")

    _mark_email_verified(user)
    try:
        NotificationService.send_email(
            recipient=user.email,
            subject="Your AgriPlot email is verified",
            template="account_verified",
            context={
                "user": user,
                "login_url": settings.SITE_URL + reverse("listings:dashboard_router"),
            },
        )
    except Exception:
        logger.exception("Failed to send post-verification email for user %s", user.pk)

    if request.user.is_authenticated and request.user.pk == user.pk:
        messages.success(request, "Your email address has been verified successfully.")
        return redirect("listings:profile_management")

    messages.success(request, "Email verified successfully. Please sign in.")
    return redirect("login")


def resend_email_verification(request):
    if not request.user.is_authenticated:
        messages.error(request, "Sign in to resend your verification email.")
        return redirect("login")

    if request.method != "POST":
        return redirect("listings:profile_management")

    profile = getattr(request.user, "profile", None)
    contact_verification = getattr(request.user, "contact_verification", None)
    email_verified = bool(getattr(profile, "email_verified", False))
    if contact_verification:
        email_verified = email_verified or contact_verification.email_verified

    if email_verified:
        messages.info(request, "Your email is already verified.")
        return redirect("listings:profile_management")

    if not request.user.email:
        messages.error(request, "Add an email address to your account before requesting verification.")
        return redirect("listings:profile_edit")

    if send_email_verification_link(request, request.user):
        messages.success(request, "A new email verification link has been sent to your inbox.")
    else:
        messages.error(request, "We could not send the email verification link right now. Please try again.")
    return redirect("listings:profile_management")
