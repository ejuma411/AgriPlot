# listings/views_auth.py

from django.contrib.auth.views import PasswordResetView, PasswordResetDoneView, PasswordResetConfirmView, PasswordResetCompleteView
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)

class CustomPasswordResetView(PasswordResetView):
    template_name = 'auth/password_reset.html'
    email_template_name = 'emails/password_reset_email.html'
    html_email_template_name = 'emails/password_reset_email.html'  # Add this line!
    subject_template_name = 'auth/password_reset_subject.txt'
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
    template_name = 'auth/password_reset_done.html'


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'auth/password_reset_confirm.html'
    success_url = reverse_lazy('listings:password_reset_complete')


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'auth/password_reset_complete.html'


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
    return render(request, 'auth/password_reset_confirm_request.html', {
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