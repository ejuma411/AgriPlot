#!/usr/bin/env bash
set -euo pipefail

python manage.py shell <<'PY'
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

subject = "AgriPlot Connect: Platform Update"
body = (
    "Hello from AgriPlot Connect,\n\n"
    "We’ve added new verification tools, mock registry testing, and improved document checks "
    "to make listings more reliable. If you’re listing land, please ensure your parcel details "
    "and ownership documents are accurate.\n\n"
    "Thank you for using AgriPlot Connect.\n"
    f"Sent on {timezone.now().strftime('%Y-%m-%d %H:%M')}"
)

recipients = list(User.objects.exclude(email='').values_list('email', flat=True))

sent = 0
for email in recipients:
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
        sent += 1
    except Exception as e:
        print(f"Failed to send to {email}: {e}")

print(f"Sent {sent} emails out of {len(recipients)} recipients")
PY
