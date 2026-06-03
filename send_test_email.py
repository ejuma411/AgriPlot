import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agriplot.settings')
django.setup()

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

subject = "AgriPlot Template Test"
recipient_list = ["ejuma411@gmail.com"]

# We'll test with registration_received.html
context = {
    'user': 'testuser',
    'username': 'testuser',
    'profile_url': f"{settings.SITE_URL}/profile"
}
html_content = render_to_string('notifications/emails/registration_received.html', context)
text_content = strip_tags(html_content)

email = EmailMultiAlternatives(subject, text_content, None, recipient_list)
email.attach_alternative(html_content, "text/html")
try:
    email.send()
    print(f"Email sent successfully using profile URL: {context['profile_url']}")
except Exception as e:
    print(f"Failed to send email: {e}")
