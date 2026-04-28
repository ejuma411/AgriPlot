import logging
from operator import itemgetter

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render

from notifications.models import Notification
from notifications.notification_service import NotificationService
from listings.forms import SupportTicketForm
from listings.models import UserInterest

logger = logging.getLogger(__name__)


def _message_queryset_for_user(user):
    if hasattr(user, "agent"):
        return UserInterest.objects.filter(plot__agent=user.agent)
    if hasattr(user, "landownerprofile"):
        return UserInterest.objects.filter(plot__landowner=user.landownerprofile)
    return UserInterest.objects.none()


def _build_inbox_entries(user, active_filter):
    notification_qs = Notification.objects.filter(user=user)
    message_qs = _message_queryset_for_user(user).select_related("plot", "user", "user__profile")

    if active_filter == "unread":
        notification_qs = notification_qs.filter(is_read=False)
        message_qs = message_qs.filter(status="pending")
    elif active_filter == "messages":
        notification_qs = Notification.objects.none()
    elif active_filter == "updates":
        message_qs = UserInterest.objects.none()

    notifications = [
        {
            "kind": "notification",
            "id": f"notification-{item.id}",
            "raw_id": item.id,
            "title": item.title,
            "message": item.message,
            "meta": item.get_notification_type_display(),
            "timestamp": item.created_at,
            "is_unread": not item.is_read,
            "badge": "New" if not item.is_read else "Read",
            "icon": "fas fa-bell",
            "icon_family": "generic",
            "action_label": "Mark read" if not item.is_read else "",
            "can_mark_read": not item.is_read,
            "plot_id": item.plot_id,
            "task_id": item.task_id,
        }
        for item in notification_qs.order_by("-created_at")[:200]
    ]

    for entry in notifications:
        title_text = entry["meta"].lower()
        if "task" in title_text:
            entry["icon"] = "fas fa-tasks"
            entry["icon_family"] = "task"
        elif "plot" in title_text or "verification" in title_text:
            entry["icon"] = "fas fa-file-shield"
            entry["icon_family"] = "plot"
        elif "role" in title_text or "account" in title_text:
            entry["icon"] = "fas fa-user-shield"
            entry["icon_family"] = "account"

    messages_feed = [
        {
            "kind": "message",
            "id": f"message-{item.id}",
            "raw_id": item.id,
            "title": item.plot.title,
            "message": item.message or "Saved interest recorded on this plot.",
            "meta": item.get_status_display(),
            "timestamp": item.created_at,
            "is_unread": item.status == "pending",
            "badge": "Pending" if item.status == "pending" else "Handled",
            "icon": "fas fa-envelope-open-text",
            "icon_family": "message",
            "action_label": "Open plot",
            "can_mark_read": False,
            "plot_id": item.plot_id,
            "task_id": None,
            "buyer_name": item.user.get_full_name() or item.user.username,
            "buyer_email": item.user.email or "",
            "status": item.status,
        }
        for item in message_qs.order_by("-created_at")[:200]
    ]

    if active_filter == "messages":
        entries = messages_feed
    elif active_filter == "updates":
        entries = notifications
    else:
        entries = sorted(notifications + messages_feed, key=itemgetter("timestamp"), reverse=True)

    return entries[:200], notifications, messages_feed


@login_required
def notifications_inbox(request):
    """Unified inbox for system notifications and role-specific messages."""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark_all":
            NotificationService.mark_all_as_read(request.user)
            messages.success(request, "All notifications marked as read.")
            return redirect("listings:notifications_inbox")
        if action == "mark_one":
            notification_id = request.POST.get("notification_id")
            notification = Notification.objects.filter(
                user=request.user,
                pk=notification_id,
            ).first()
            if notification and not notification.is_read:
                notification.mark_as_read()
                messages.success(request, "Notification marked as read.")
            return redirect("listings:notifications_inbox")

    active_filter = request.GET.get("filter", "all")
    if active_filter not in {"all", "unread", "messages", "updates"}:
        active_filter = "all"

    inbox_entries, notification_entries, message_entries = _build_inbox_entries(request.user, active_filter)
    unread_notification_count = Notification.objects.filter(user=request.user, is_read=False).count()
    unread_message_count = _message_queryset_for_user(request.user).filter(status="pending").count()
    unread_count = unread_notification_count + unread_message_count
    total_count = Notification.objects.filter(user=request.user).count() + _message_queryset_for_user(request.user).count()
    read_count = max(total_count - unread_count, 0)

    return render(
        request,
        "notifications/inbox.html",
        {
            "inbox_entries": inbox_entries,
            "unread_count": unread_count,
            "read_count": read_count,
            "total_count": total_count,
            "message_count": len(message_entries) if active_filter in {"messages", "all", "unread"} else _message_queryset_for_user(request.user).count(),
            "notification_count": len(notification_entries) if active_filter in {"updates", "all", "unread"} else Notification.objects.filter(user=request.user).count(),
            "active_filter": active_filter,
            "page_title": "Inbox",
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
