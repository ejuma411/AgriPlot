# listings/views_otp.py

import random
import os
from datetime import timedelta
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth import authenticate, login
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.conf import settings
from django.core.files.base import File
from django.contrib.auth.models import User
from notifications.services.sms_service import TextSMSService
from accounts.models import Profile, LandownerProfile, Agent
from security.models import PhoneOTP, EmailOTP, PhoneEmailVerification
from security.forms import OTPVerificationForm
import logging

logger = logging.getLogger(__name__)

def generate_otp():
    """Generate 6-digit OTP"""
    return str(random.randint(100000, 999999))

def send_otp_verification(request):
    """Step 1: Send OTP to phone/email based on settings"""
    phone = request.session.get('reg_phone')
    reg_data = request.session.get('reg_data')
    
    if not phone or not reg_data:
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

    sms_ok = True
    if otp_provider in ("sms", "both"):
        sms = TextSMSService()
        result = sms.send_otp(phone, otp)
        sms_ok = bool(result.get('success'))
        if not sms_ok:
            logger.error(f"Failed to send SMS OTP: {result.get('error')}")

    email_ok = True
    if otp_provider in ("email", "both"):
        try:
            from notifications.notification_service import NotificationService
            subject = "AgriPlot verification code"
            NotificationService.send_email(
                recipient=email,
                subject=subject,
                template="otp_verification",
                context={
                    "user": None,
                    "display_name": f"{reg_data.get('first_name', '')} {reg_data.get('last_name', '')}".strip() or reg_data.get('username', 'there'),
                    "otp": otp,
                    "expiry_minutes": 10,
                    "support_url": settings.SITE_URL + "/contact-support/"
                }
            )
        except Exception as e:
            email_ok = False
            logger.error(f"Failed to send email OTP: {str(e)}", exc_info=True)

    if otp_provider == "sms" and sms_ok:
        messages.success(request, "Verification code sent to your phone!")
        return redirect('listings:verify_otp')
    if otp_provider == "email" and email_ok:
        messages.success(request, "Verification code sent to your email!")
        return redirect('listings:verify_otp')
    if otp_provider == "both" and (sms_ok or email_ok):
        messages.success(request, "Verification code sent. Check SMS and/or email.")
        return redirect('listings:verify_otp')

    messages.error(request, "Failed to send verification code. Please try again.")
    return redirect('listings:register_choice')


def verify_otp(request):
    """Step 2: Verify OTP and complete registration"""
    if request.method == 'POST':
        otp_entered = request.POST.get('otp')
        phone = request.session.get('reg_phone')
        reg_data = request.session.get('reg_data')
        reg_files = request.session.get('reg_files', {})
        
        if not phone or not reg_data:
            messages.error(request, "Session expired. Please register again.")
            return redirect('listings:register_choice')

        otp_provider = getattr(settings, "OTP_PROVIDER", "email")
        if otp_provider not in ("email", "sms", "both"):
            otp_provider = "email"
        email = reg_data.get('email')

        # Check OTP
        try:
            verified = False
            if otp_provider in ("sms", "both"):
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

            if otp_provider in ("email", "both") and not verified:
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
            profile.phone_verified = (otp_provider in ("sms", "both"))
            profile.email_verified = (otp_provider in ("email", "both"))
            if reg_data.get('address'):
                profile.address = reg_data.get('address')
            profile.save()

            PhoneEmailVerification.objects.get_or_create(
                user=user,
                defaults={
                    'phone_number': phone,
                    'email': reg_data.get('email', ''),
                    'phone_verified': (otp_provider in ("sms", "both")),
                    'email_verified': (otp_provider in ("email", "both")),
                    'phone_verified_at': timezone.now() if otp_provider in ("sms", "both") else None,
                    'email_verified_at': timezone.now() if otp_provider in ("email", "both") else None,
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

            # Clear session data
            target_role = request.session.get('reg_target_role')
            session_keys = ['reg_phone', 'reg_data', 'reg_files', 'reg_target_role']
            for key in session_keys:
                if key in request.session:
                    del request.session[key]
            # Clear wizard session data if any
            wizard_keys = [k for k in request.session.keys() if k.startswith('landownerwizard')]
            for key in wizard_keys:
                if key in request.session:
                    del request.session[key]

            messages.success(request, f"Account created successfully! Your phone is verified.")

            # Send registration email with role upgrade notice
            try:
                from notifications.notification_service import NotificationService
                if user.email:
                    NotificationService.send_email(
                        recipient=user.email,
                        subject="Welcome to AgriPlot",
                        template="registration_received",
                        context={
                            'user': user,
                            'login_url': settings.SITE_URL + '/login/',
                            'profile_url': settings.SITE_URL + '/dashboard/profile/',
                        }
                    )
            except Exception as e:
                logger.error(f"Failed to send registration email: {str(e)}", exc_info=True)
            
            # Redirect based on role
            if target_role == 'extension_officer':
                return redirect('listings:request_extension_officer')
            if target_role == 'land_surveyor':
                return redirect('listings:request_land_surveyor')
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
            return render(request, 'security/verify_otp.html', {'phone': phone, 'channel': otp_provider, 'form': form})
        except Exception as e:
            logger.error(f"Error completing registration: {str(e)}", exc_info=True)
            messages.error(request, "An error occurred. Please try again.")
            return redirect('listings:register_choice')
    
    # GET request - show OTP verification form
    phone = request.session.get('reg_phone')
    if not phone:
        return redirect('listings:register_choice')
    
    otp_provider = getattr(settings, "OTP_PROVIDER", "email")
    form = OTPVerificationForm()
    return render(request, 'security/verify_otp.html', {'phone': phone, 'channel': otp_provider, 'form': form})


def resend_otp(request):
    """Resend OTP to phone"""
    if request.method == 'POST':
        phone = request.session.get('reg_phone')
        reg_data = request.session.get('reg_data') or {}
        email = reg_data.get('email')
        
        if not phone:
            messages.error(request, "Session expired. Please register again.")
            return redirect('listings:register_choice')
        
        otp_provider = getattr(settings, "OTP_PROVIDER", "email")
        if otp_provider not in ("email", "sms", "both"):
            otp_provider = "email"

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

        sms_ok = True
        if otp_provider in ("sms", "both"):
            sms = TextSMSService()
            result = sms.send_otp(phone, otp)
            sms_ok = bool(result.get('success'))

        email_ok = True
        if otp_provider in ("email", "both") and email:
            try:
                from notifications.notification_service import NotificationService
                subject = "AgriPlot verification code"
                NotificationService.send_email(
                    recipient=email,
                    subject=subject,
                    template="otp_verification",
                    context={
                        "user": None,
                        "display_name": reg_data.get('username', 'there'),
                        "otp": otp,
                        "expiry_minutes": 10,
                        "support_url": settings.SITE_URL + "/contact-support/"
                    }
                )
            except Exception as e:
                email_ok = False
                logger.error(f"Failed to resend email OTP: {str(e)}", exc_info=True)

        if otp_provider == "sms" and sms_ok:
            messages.success(request, "New verification code sent!")
        elif otp_provider == "email" and email_ok:
            messages.success(request, "New verification code sent!")
        elif otp_provider == "both" and (sms_ok or email_ok):
            messages.success(request, "New verification code sent!")
        else:
            messages.error(request, "Failed to send code. Please try again.")
        
        return redirect('listings:verify_otp')
    
    return redirect('listings:register_choice')
