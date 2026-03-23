from listings.models import UserInterest
from notifications.models import Notification


def nav_activity(request):
    if not request.user.is_authenticated:
        return {
            "nav_unread_notifications_count": 0,
            "nav_recent_notifications": [],
            "nav_unread_buyer_messages_count": 0,
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

    return {
        "nav_unread_notifications_count": unread_notifications_count,
        "nav_recent_notifications": notifications[:5],
        "nav_unread_buyer_messages_count": unread_buyer_messages_count,
    }
