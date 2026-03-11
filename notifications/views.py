import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render

from notifications.models import Notification
from notifications.notification_service import NotificationService
from listings.forms import SupportTicketForm

logger = logging.getLogger(__name__)


@login_required
def notifications_inbox(request):
    """User notifications inbox."""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark_all":
            NotificationService.mark_all_as_read(request.user)
            messages.success(request, "All notifications marked as read.")
            return redirect("listings:notifications_inbox")

    notifications = (
        Notification.objects.filter(user=request.user).order_by("-created_at")[:200]
    )
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

    return render(
        request,
        "notifications/inbox.html",
        {
            "notifications": notifications,
            "unread_count": unread_count,
            "page_title": "Notifications",
        },
    )


def contact_support(request):
    """Simple contact support page."""
    support_email = "agriplotconnect@gmail.com"
    support_phone = "+254 718 810 503"

    if request.method == "POST":
        form = SupportTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            if request.user.is_authenticated:
                ticket.user = request.user
            ticket.save()

            try:
                admins = User.objects.filter(is_staff=True)
                for admin in admins:
                    NotificationService.send_email(
                        recipient=admin.email,
                        subject=f"New Support Ticket: {ticket.subject}",
                        template="support_ticket_admin",
                        context={
                            "admin": admin,
                            "ticket": ticket,
                            "site_url": settings.SITE_URL,
                        },
                    )
            except Exception as exc:
                logger.error("Support ticket admin email failed: %s", exc)

            try:
                NotificationService.send_email(
                    recipient=ticket.email,
                    subject="Support Ticket Received",
                    template="support_ticket_received",
                    context={"ticket": ticket},
                )
            except Exception as exc:
                logger.error("Support ticket user email failed: %s", exc)

            messages.success(
                request,
                "Support request submitted. We will get back to you shortly.",
            )
            return redirect("listings:contact_support")
    else:
        initial = {}
        if request.user.is_authenticated:
            initial = {
                "name": request.user.get_full_name() or request.user.username,
                "email": request.user.email,
            }
        form = SupportTicketForm(initial=initial)

    return render(
        request,
        "notifications/contact_support.html",
        {
            "support_email": support_email,
            "support_phone": support_phone,
            "form": form,
        },
    )
