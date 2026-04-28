from listings.models import UserInterest
from notifications.models import Notification


def nav_activity(request):
    if not request.user.is_authenticated:
        return {
            "nav_unread_notifications_count": 0,
            "nav_recent_notifications": [],
            "nav_unread_buyer_messages_count": 0,
            "nav_unread_inbox_count": 0,
            "nav_recent_inbox_items": [],
        }

    notifications = Notification.objects.filter(user=request.user).order_by("-created_at")
    unread_notifications_count = notifications.filter(is_read=False).count()

    unread_buyer_messages_count = 0
    if hasattr(request.user, "agent"):
        unread_buyer_messages_count = UserInterest.objects.filter(
            plot__agent=request.user.agent,
            status="pending",
        ).count()
    elif hasattr(request.user, "landownerprofile"):
        unread_buyer_messages_count = UserInterest.objects.filter(
            plot__landowner=request.user.landownerprofile,
            status="pending",
        ).count()

    recent_messages = []
    if hasattr(request.user, "agent"):
        recent_messages = list(
            UserInterest.objects.filter(plot__agent=request.user.agent)
            .select_related("plot", "user")
            .order_by("-created_at")[:5]
        )
    elif hasattr(request.user, "landownerprofile"):
        recent_messages = list(
            UserInterest.objects.filter(plot__landowner=request.user.landownerprofile)
            .select_related("plot", "user")
            .order_by("-created_at")[:5]
        )

    recent_inbox_items = [
        {
            "kind": "notification",
            "title": item.title,
            "message": item.message,
            "created_at": item.created_at,
            "is_read": item.is_read,
        }
        for item in notifications[:5]
    ] + [
        {
            "kind": "message",
            "title": message.plot.title,
            "message": message.message or "Saved interest recorded on this plot.",
            "created_at": message.created_at,
            "is_read": message.status != "pending",
        }
        for message in recent_messages
    ]
    recent_inbox_items.sort(key=lambda item: item["created_at"], reverse=True)

    return {
        "nav_unread_notifications_count": unread_notifications_count,
        "nav_recent_notifications": notifications[:5],
        "nav_unread_buyer_messages_count": unread_buyer_messages_count,
        "nav_unread_inbox_count": unread_notifications_count + unread_buyer_messages_count,
        "nav_recent_inbox_items": recent_inbox_items[:5],
    }
