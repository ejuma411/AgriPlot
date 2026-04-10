import logging

from django.db import transaction
from django.utils import timezone

from notifications.notification_service import NotificationService

from .models import LeaseWaitlistEntry, PaymentRequest


logger = logging.getLogger(__name__)


ACTIVE_LEASE_STATUSES = {
    PaymentRequest.Status.PAID,
    PaymentRequest.Status.IN_ESCROW,
    PaymentRequest.Status.PARTIALLY_RELEASED,
    PaymentRequest.Status.RELEASED,
}

TENANT_RENEWAL_REMINDER_THRESHOLDS = [90, 60, 30, 7]


def _notify_user(user, plot, title, message):
    NotificationService.notify_user(
        user=user,
        notification_type="plot_stage_update",
        title=title,
        message=message,
        plot=plot,
    )


def _active_lease_payments(run_date):
    candidates = (
        PaymentRequest.objects.select_related("plot", "buyer", "seller")
        .prefetch_related("closing_steps")
        .filter(
            transaction_type=PaymentRequest.TransactionType.LEASE,
            plot__isnull=False,
            lease_end_date__isnull=False,
            status__in=ACTIVE_LEASE_STATUSES,
        )
        .exclude(status__in=[PaymentRequest.Status.REFUNDED, PaymentRequest.Status.CANCELLED, PaymentRequest.Status.FAILED])
        .order_by("plot_id", "-lease_end_date", "-created_at")
    )
    latest_by_plot = {}
    for payment in candidates:
        if payment.plot_id not in latest_by_plot:
            latest_by_plot[payment.plot_id] = payment
    return latest_by_plot.values()


def _tenant_reminder_bucket(days_until_expiry):
    for threshold in TENANT_RENEWAL_REMINDER_THRESHOLDS:
        if days_until_expiry <= threshold:
            return threshold
    return None


def _process_tenant_renewal_reminders(payment, today, stats):
    if not payment.buyer or not payment.lease_end_date:
        return

    days_until_expiry = (payment.lease_end_date - today).days
    if days_until_expiry < 0:
        return

    reminder_bucket = _tenant_reminder_bucket(days_until_expiry)
    if reminder_bucket is None:
        return

    metadata = dict(payment.metadata or {})
    sent_buckets = list(metadata.get("tenant_renewal_reminder_buckets") or [])
    if reminder_bucket in sent_buckets:
        return

    if reminder_bucket == 90:
        title = "Lease renewal window is now open"
        renewal_phrase = (
            "You are now within the final 90 days of your agreed lease period. "
            "If you want to keep using this land, start renewal discussions immediately."
        )
    elif reminder_bucket == 60:
        title = "60-day lease renewal reminder"
        renewal_phrase = (
            "You are now within the final 60 days of your agreed lease period. "
            "Renew the lease terms now if you want to continue occupying the land."
        )
    elif reminder_bucket == 30:
        title = "30-day lease renewal warning"
        renewal_phrase = (
            "You are now within the final 30 days of your agreed lease period. "
            "If no renewal is agreed, AgriPlot will treat the tenancy as ending on the expiry date."
        )
    else:
        title = "Final lease expiry warning"
        renewal_phrase = (
            "Your lease is now in its final week. "
            "If you do not renew the terms before expiry, AgriPlot will terminate the tenancy automatically when the period ends."
        )

    message = (
        f"{renewal_phrase} The current term for '{payment.plot.title}' ends on "
        f"{payment.lease_end_date:%b %d, %Y}. "
        "Use the AgriPlot lease workflow to renew the terms before the expiry date. "
        "If the terms are not renewed in time, AgriPlot will terminate the tenancy upon expiry and release the land back into circulation for the next approved user."
    )
    _notify_user(payment.buyer, payment.plot, title, message)
    if payment.seller:
        _notify_user(
            payment.seller,
            payment.plot,
            f"Tenant renewal reminder sent ({reminder_bucket}-day)",
            (
                f"AgriPlot sent the current tenant a {reminder_bucket}-day renewal reminder for "
                f"'{payment.plot.title}'. The present term still ends on {payment.lease_end_date:%b %d, %Y} unless both sides renew it."
            ),
        )

    sent_buckets.append(reminder_bucket)
    metadata["tenant_renewal_reminder_buckets"] = sorted(set(sent_buckets), reverse=True)
    metadata["tenant_renewal_last_sent_at"] = timezone.now().isoformat()
    payment.metadata = metadata
    payment.save(update_fields=["metadata", "updated_at"])
    stats["tenant_renewal_reminders"] += 1


def _process_notice_window(payment, today, stats):
    if not payment.vacation_notice_date or payment.vacation_notice_date > today:
        return

    metadata = dict(payment.metadata or {})
    if metadata.get("waitlist_notice_sent_at"):
        return

    candidate = LeaseWaitlistEntry.next_candidate_for_plot(payment.plot)
    if not candidate or candidate.status != LeaseWaitlistEntry.Status.WAITING:
        return

    candidate.mark_contacted()
    metadata["waitlist_notice_sent_at"] = timezone.now().isoformat()
    metadata["waitlist_notice_entry_id"] = candidate.pk
    payment.metadata = metadata
    payment.save(update_fields=["metadata", "updated_at"])

    notice_message = (
        f"The current lease for '{payment.plot.title}' is expected to end on "
        f"{payment.lease_end_date:%b %d, %Y}. You are first in the AgriPlot queue. "
        "Confirm your interest now so you can move first when the land becomes free."
    )
    _notify_user(candidate.user, payment.plot, "Confirm your next lease interest", notice_message)
    if payment.buyer:
        _notify_user(
            payment.buyer,
            payment.plot,
            "Vacation notice window is now open",
            (
                f"The vacation notice window for '{payment.plot.title}' opened on "
                f"{payment.vacation_notice_date:%b %d, %Y}. AgriPlot has now contacted the next queued tenant."
            ),
        )
    if payment.seller:
        _notify_user(
            payment.seller,
            payment.plot,
            "Next tenant queue contacted",
            (
                f"AgriPlot has contacted the next queued tenant for '{payment.plot.title}' "
                f"ahead of the lease ending on {payment.lease_end_date:%b %d, %Y}."
            ),
        )
    stats["notice_contacts"] += 1


def _release_expired_lease(payment, today, stats):
    if payment.lease_end_date >= today:
        return

    metadata = dict(payment.metadata or {})
    if metadata.get("lease_release_processed_at"):
        return

    with transaction.atomic():
        plot = payment.plot
        plot.market_status = "available"
        plot.lease_start_date = None
        plot.lease_end_date = None
        plot.availability_notes = (
            f"The previous lease linked to {payment.internal_reference} has ended. "
            "The land is now free for the next lease or sale workflow."
        )
        plot.save(update_fields=["market_status", "lease_start_date", "lease_end_date", "availability_notes", "updated_at"])

        active_entries = list(
            LeaseWaitlistEntry.objects.filter(
                plot=plot,
                status__in=[
                    LeaseWaitlistEntry.Status.WAITING,
                    LeaseWaitlistEntry.Status.CONTACTED,
                    LeaseWaitlistEntry.Status.CONFIRMED,
                ],
            ).select_related("user")
        )
        for entry in active_entries:
            entry.last_notified_at = timezone.now()
            entry.save(update_fields=["last_notified_at", "updated_at"])

        metadata["lease_release_processed_at"] = timezone.now().isoformat()
        payment.metadata = metadata
        payment.save(update_fields=["metadata", "updated_at"])
        payment.add_event(
            "lease_expired",
            "Lease term ended automatically and the plot was returned to the market.",
            actor=None,
        )

    title = f"Lease ended for {payment.plot.title}"
    landlord_message = (
        f"The lease on '{payment.plot.title}' ended on {payment.lease_end_date:%b %d, %Y}. "
        "AgriPlot has returned the land to available status and notified queued tenants."
    )
    tenant_message = (
        f"Your AgriPlot lease on '{payment.plot.title}' ended on {payment.lease_end_date:%b %d, %Y}. "
        "The land is now free for handover to the next approved user."
    )
    waitlist_message = (
        f"The land '{payment.plot.title}' is now free after the previous lease expired on "
        f"{payment.lease_end_date:%b %d, %Y}. You can now continue with the AgriPlot lease workflow."
    )
    if payment.seller:
        _notify_user(payment.seller, payment.plot, title, landlord_message)
    if payment.buyer:
        _notify_user(payment.buyer, payment.plot, title, tenant_message)
    for entry in active_entries:
        _notify_user(entry.user, payment.plot, "Land is now free to lease", waitlist_message)
    stats["leases_released"] += 1


def process_lease_lifecycle(run_at=None):
    now = run_at or timezone.now()
    today = timezone.localdate(now)
    stats = {
        "lease_count": 0,
        "notice_contacts": 0,
        "tenant_renewal_reminders": 0,
        "leases_released": 0,
    }

    for payment in _active_lease_payments(today):
        stats["lease_count"] += 1
        _process_tenant_renewal_reminders(payment, today, stats)
        _process_notice_window(payment, today, stats)
        _release_expired_lease(payment, today, stats)

    return stats
