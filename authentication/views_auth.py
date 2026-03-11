# listings/views_auth.py

from django.contrib.auth.views import (
    LoginView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth import login
from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.conf import settings
import pyotp
import logging
import base64
import io
import secrets
import hashlib
import qrcode
from accounts.models import Profile
from security.models import TwoFactorSettings, TwoFactorBackupCode, EmailOTP, PhoneOTP
from authentication.forms import TwoFactorSetupForm, TwoFactorVerifyForm
from notifications.notification_service import NotificationService
from notifications.services.sms_service import TextSMSService

logger = logging.getLogger(__name__)

class TwoFactorLoginView(LoginView):
    template_name = 'authentication/login.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request
        context['show_wizard_resume'] = any(
            key.startswith("landownerwizard") or key.startswith("wizard_")
            for key in request.session.keys()
        )
        return context

    def form_valid(self, form):
        user = form.get_user()
        # Only require 2FA challenge if user has enabled it.
        profile = getattr(user, "profile", None)
        if profile and profile.has_2fa_enabled:
            self.request.session['pre_2fa_user_id'] = user.id
            self.request.session['pre_2fa_next'] = self.get_success_url()
            return redirect('listings:two_factor_verify')
        return super().form_valid(form)


def _get_or_create_2fa_settings(user):
    settings_obj, _ = TwoFactorSettings.objects.get_or_create(user=user)
    if not settings_obj.totp_secret:
        settings_obj.totp_secret = pyotp.random_base32()
        settings_obj.save()
    return settings_obj


def _hash_backup_code(code):
    salt = settings.SECRET_KEY or "agriplot"
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def _generate_backup_codes(user, count=10):
    TwoFactorBackupCode.objects.filter(user=user, used_at__isnull=True).delete()
    codes = []
    for _ in range(count):
        code = secrets.token_hex(4).upper()
        TwoFactorBackupCode.objects.create(
            user=user,
            code_hash=_hash_backup_code(code)
        )
        codes.append(code)
    return codes


def _issue_login_otp(user, method):
    import random
    otp_code = str(random.randint(100000, 999999))
    expires_at = timezone.now() + timezone.timedelta(minutes=10)

    if method == "email":
        email = user.email
        if not email:
            return False, "Email address not available."
        EmailOTP.objects.create(
            user=user,
            email=email,
            otp=otp_code,
            purpose='login',
            expires_at=expires_at
        )
        NotificationService.send_email(
            recipient=email,
            subject="Your AgriPlot login verification code",
            template="otp_verification",
            context={
                "user": user,
                "display_name": user.get_full_name() or user.username,
                "otp": otp_code,
                "expiry_minutes": 10,
                "support_url": settings.SITE_URL + "/contact-support/"
            }
        )
        return True, "Verification code sent to email."

    if method == "sms":
        phone = getattr(user.profile, "phone", "")
        if not phone:
            return False, "Phone number not available."
        PhoneOTP.objects.create(
            user=user,
            phone=phone,
            otp=otp_code,
            purpose='login',
            expires_at=expires_at
        )
        sms = TextSMSService()
        sms.send_otp(phone, otp_code)
        return True, "Verification code sent via SMS."

    return False, "Unsupported method."


def two_factor_setup(request):
    if not request.user.is_authenticated:
        return redirect('login')

    settings_obj = _get_or_create_2fa_settings(request.user)
    profile, _ = Profile.objects.get_or_create(user=request.user)

    totp = pyotp.TOTP(settings_obj.totp_secret)
    issuer = "AgriPlot Connect"
    identifier = request.user.email or request.user.username
    provisioning_uri = totp.provisioning_uri(name=identifier, issuer_name=issuer)
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_code_data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("utf-8")

    backup_codes = request.session.pop("backup_codes", None)

    if request.method == "POST":
        if request.POST.get("regen_backup_codes"):
            backup_codes = _generate_backup_codes(request.user)
            request.session["backup_codes"] = backup_codes
            messages.success(request, "New backup codes generated.")
            return redirect('listings:two_factor_setup')

        if request.POST.get("disable_2fa"):
            settings_obj.is_enabled = False
            settings_obj.save()
            profile.has_2fa_enabled = False
            profile.save()
            messages.success(request, "Two-factor authentication disabled.")
            return redirect('listings:account_settings')

        form = TwoFactorSetupForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            if totp.verify(code, valid_window=1):
                settings_obj.is_enabled = True
                settings_obj.save()
                profile.has_2fa_enabled = True
                profile.save()
                backup_codes = _generate_backup_codes(request.user)
                request.session["backup_codes"] = backup_codes
                messages.success(request, "Two-factor authentication enabled.")
                return redirect('listings:two_factor_setup')
            messages.error(request, "Invalid code. Please try again.")
    else:
        form = TwoFactorSetupForm()

    return render(request, "authentication/two_factor_setup.html", {
        "form": form,
        "provisioning_uri": provisioning_uri,
        "secret": settings_obj.totp_secret,
        "is_enabled": settings_obj.is_enabled,
        "qr_code_data_uri": qr_code_data_uri,
        "backup_codes": backup_codes,
    })


def two_factor_verify(request):
    user_id = request.session.get('pre_2fa_user_id')
    if not user_id:
        messages.info(request, "Please login to continue.")
        return redirect('login')

    user = User.objects.filter(id=user_id).first()
    if not user:
        messages.error(request, "Session expired. Please login again.")
        return redirect('login')

    settings_obj = _get_or_create_2fa_settings(user)
    profile = getattr(user, "profile", None)
    available_methods = ['totp', 'email', 'sms', 'backup']
    if not settings_obj.totp_secret:
        available_methods.remove('totp')
    if not user.email and 'email' in available_methods:
        available_methods.remove('email')
    if not (profile and profile.phone) and 'sms' in available_methods:
        available_methods.remove('sms')
    if not TwoFactorBackupCode.objects.filter(user=user, used_at__isnull=True).exists():
        if 'backup' in available_methods:
            available_methods.remove('backup')

    if request.method == "POST":
        if request.POST.get("send_code"):
            method = request.POST.get("method")
            ok, msg = _issue_login_otp(user, method)
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
            form = TwoFactorVerifyForm(initial={'method': method})
        else:
            form = TwoFactorVerifyForm(request.POST)
            if form.is_valid():
                method = form.cleaned_data['method']
                code = form.cleaned_data['code']
                if method not in available_methods:
                    messages.error(request, "Selected method is not available for your account.")
                    return redirect('listings:two_factor_verify')

                if method == 'totp':
                    totp = pyotp.TOTP(settings_obj.totp_secret)
                    if totp.verify(code, valid_window=1):
                        login(request, user)
                        request.session.pop('pre_2fa_user_id', None)
                        next_url = request.session.pop('pre_2fa_next', None) or settings.LOGIN_REDIRECT_URL
                        return redirect(next_url)
                    messages.error(request, "Invalid authenticator code.")

                if method == 'email':
                    otp_record = EmailOTP.objects.filter(
                        user=user,
                        email=user.email,
                        otp=code,
                        purpose='login',
                        is_verified=False,
                        expires_at__gt=timezone.now()
                    ).order_by('-created_at').first()
                    if otp_record:
                        otp_record.is_verified = True
                        otp_record.save()
                        login(request, user)
                        request.session.pop('pre_2fa_user_id', None)
                        next_url = request.session.pop('pre_2fa_next', None) or settings.LOGIN_REDIRECT_URL
                        return redirect(next_url)
                    messages.error(request, "Invalid or expired email code.")

                if method == 'sms':
                    phone = profile.phone if profile else ""
                    otp_record = PhoneOTP.objects.filter(
                        user=user,
                        phone=phone,
                        otp=code,
                        purpose='login',
                        is_verified=False,
                        expires_at__gt=timezone.now()
                    ).order_by('-created_at').first()
                    if otp_record:
                        otp_record.is_verified = True
                        otp_record.save()
                        login(request, user)
                        request.session.pop('pre_2fa_user_id', None)
                        next_url = request.session.pop('pre_2fa_next', None) or settings.LOGIN_REDIRECT_URL
                        return redirect(next_url)
                    messages.error(request, "Invalid or expired SMS code.")

                if method == 'backup':
                    code_hash = _hash_backup_code(code.strip().upper())
                    backup = TwoFactorBackupCode.objects.filter(
                        user=user,
                        code_hash=code_hash,
                        used_at__isnull=True
                    ).first()
                    if backup:
                        backup.used_at = timezone.now()
                        backup.save()
                        login(request, user)
                        request.session.pop('pre_2fa_user_id', None)
                        next_url = request.session.pop('pre_2fa_next', None) or settings.LOGIN_REDIRECT_URL
                        return redirect(next_url)
                    messages.error(request, "Invalid or already used backup code.")
    else:
        form = TwoFactorVerifyForm()

    return render(request, "authentication/two_factor_verify.html", {
        "form": form,
        "available_methods": available_methods,
        "email": user.email,
        "phone": getattr(profile, "phone", ""),
    })


def sign_out_all_sessions(request):
    if not request.user.is_authenticated:
        return redirect('login')
    from django.contrib.sessions.models import Session
    from django.utils import timezone as tz
    user_id = str(request.user.id)
    for session in Session.objects.filter(expire_date__gte=tz.now()):
        data = session.get_decoded()
        if data.get('_auth_user_id') == user_id:
            session.delete()
    messages.success(request, "All sessions signed out.")
    return redirect('listings:account_settings')

class CustomPasswordResetView(PasswordResetView):
    template_name = 'authentication/password_reset.html'
    email_template_name = 'emails/password_reset_email.html'
    html_email_template_name = 'emails/password_reset_email.html'  # Add this line!
    subject_template_name = 'authentication/password_reset_subject.txt'
    success_url = reverse_lazy('listings:password_reset_done')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reset_step'] = 'request'
        return context
    
    def form_valid(self, form):
        email = form.cleaned_data['email']
        self.request.session['reset_email'] = email
        
        user_exists = User.objects.filter(email=email).exists()
        
        if not user_exists:
            logger.info(f"Password reset attempted for non-existent email: {email}")
            messages.info(self.request, "If this email exists in our system, you'll receive reset instructions.")
            return redirect(self.success_url)
        
        return redirect('listings:password_reset_confirm_request')


class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'authentication/password_reset_done.html'


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'authentication/password_reset_confirm.html'
    success_url = reverse_lazy('listings:password_reset_complete')


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'authentication/password_reset_complete.html'


def password_reset_confirm_request(request):
    email = request.session.get('reset_email')
    
    if not email:
        messages.error(request, "Session expired. Please start over.")
        return redirect('listings:password_reset')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'confirm':
            try:
                # Create form
                form = PasswordResetForm({'email': email})
                if form.is_valid():
                    # Get users with this email
                    users = User.objects.filter(email=email)
                    
                    for user in users:
                        # Generate token
                        from django.contrib.auth.tokens import default_token_generator
                        from django.utils.encoding import force_bytes
                        from django.utils.http import urlsafe_base64_encode
                        
                        uid = urlsafe_base64_encode(force_bytes(user.pk))
                        token = default_token_generator.make_token(user)
                        
                        # Build reset link
                        reset_link = f"{request.scheme}://{request.get_host()}/password-reset/{uid}/{token}/"
                        
                        # Create email context
                        context = {
                            'user': user,
                            'reset_link': reset_link,
                            'protocol': request.scheme,
                            'domain': request.get_host(),
                            'uid': uid,
                            'token': token,
                        }
                        
                        # Render HTML email
                        html_content = render_to_string('emails/password_reset_email.html', context)
                        text_content = strip_tags(html_content)  # Create plain text version
                        
                        # Send email
                        email_msg = EmailMultiAlternatives(
                            subject="Password Reset Request - AgriPlot Connect",
                            body=text_content,
                            from_email=None,  # Use DEFAULT_FROM_EMAIL
                            to=[user.email]
                        )
                        email_msg.attach_alternative(html_content, "text/html")
                        email_msg.send()
                    
                    del request.session['reset_email']
                    logger.info(f"Password reset email sent to: {email}")
                    messages.success(request, "Password reset instructions have been sent to your email.")
                    return redirect('listings:password_reset_done')
                    
            except Exception as e:
                logger.error(f"Error sending password reset email: {str(e)}")
                messages.error(request, "An error occurred. Please try again.")
                return redirect('listings:password_reset')
                
        elif action == 'cancel':
            if 'reset_email' in request.session:
                del request.session['reset_email']
            messages.info(request, "Password reset cancelled.")
            return redirect('listings:login')
    
    masked_email = mask_email(email)
    return render(request, 'authentication/password_reset_confirm_request.html', {
        'email': email,
        'masked_email': masked_email
    })


def mask_email(email):
    if not email:
        return email
    parts = email.split('@')
    if len(parts) != 2:
        return email
    username, domain = parts
    if len(username) <= 2:
        masked_username = username[0] + '*' * (len(username) - 1)
    else:
        masked_username = username[0] + '*' * (len(username) - 2) + username[-1]
    return f"{masked_username}@{domain}"
