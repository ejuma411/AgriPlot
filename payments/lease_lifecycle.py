import logging

from django.db import transaction
from django.utils import timezone

from notifications.notification_service import NotificationService

from .models import LeaseWaitlistEntry, PaymentRequest, PaymentClosingStep


logger = logging.getLogger(__name__)


ACTIVE_LEASE_STATUSES = {
    PaymentRequest.Status.PAID,
    PaymentRequest.Status.IN_ESCROW,
    PaymentRequest.Status.PARTIALLY_RELEASED,
    PaymentRequest.Status.RELEASED,
}

TENANT_RENEWAL_REMINDER_THRESHOLDS = [90, 60, 30, 7]


def _notify_user(user, plot, title, message, notification_type="plot_stage_update"):
    """Send notification to user"""
    if not user:
        return
    NotificationService.create_notification(
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        metadata={'plot_id': plot.id if plot else None}
    )


def _active_lease_payments(run_date):
    """Get active lease payments that haven't expired"""
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
    """Determine which reminder bucket the lease falls into"""
    for threshold in TENANT_RENEWAL_REMINDER_THRESHOLDS:
        if days_until_expiry <= threshold:
            return threshold
    return None


def _process_tenant_renewal_reminders(payment, today, stats):
    """Send renewal reminders to tenant as lease end approaches"""
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
    """Process notice window - contact next tenant in waitlist"""
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
    """Release expired lease and return plot to market"""
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


# ============================================================
# PURCHASE ESCROW LIFECYCLE (New)
# ============================================================

def _process_pending_registration_completion(payment, stats):
    """
    Check for purchase payments where registration should be complete
    but hasn't been marked yet. Trigger automatic disbursement.
    """
    if payment.transaction_type != PaymentRequest.TransactionType.PURCHASE:
        return
    
    # Check if registration step is completed
    registration_step = payment.closing_steps.filter(
        code="registration",
        status=PaymentClosingStep.Status.COMPLETED
    ).first()
    
    if not registration_step:
        return
    
    # Check if funds are ready for disbursement
    deposit_paid = payment.metadata.get('deposit_paid', False)
    balance_paid = payment.metadata.get('balance_paid', False)
    stamp_duty_verified = payment.stamp_duty_receipt_verified_at is not None
    
    if deposit_paid and balance_paid and stamp_duty_verified and not payment.disbursed_at:
        logger.info(f"Lifecycle: Registration complete for {payment.internal_reference}, triggering disbursement")
        
        try:
            payment.apply_transition("disburse_to_seller", actor=None)
            stats["disbursements_triggered"] += 1
        except Exception as e:
            logger.error(f"Lifecycle: Failed to disburse {payment.internal_reference}: {e}")


def _process_abandoned_purchase_transactions(payment, stats):
    """
    Process abandoned purchase transactions that have been pending for too long.
    Send reminders and eventually cancel if no activity.
    """
    if payment.transaction_type != PaymentRequest.TransactionType.PURCHASE:
        return
    
    if payment.status not in [PaymentRequest.Status.PAID, PaymentRequest.Status.IN_ESCROW]:
        return
    
    if payment.disbursed_at:
        return
    
    days_since_created = (timezone.now() - payment.created_at).days
    
    # 30 days without progress - send reminder
    if days_since_created == 30:
        metadata = dict(payment.metadata or {})
        if not metadata.get('abandoned_reminder_sent_30d'):
            _send_abandoned_transaction_reminder(payment, days_since_created)
            metadata['abandoned_reminder_sent_30d'] = timezone.now().isoformat()
            payment.metadata = metadata
            payment.save(update_fields=['metadata', 'updated_at'])
            stats["abandoned_reminders_sent"] += 1
    
    # 60 days without progress - send escalation
    elif days_since_created == 60:
        metadata = dict(payment.metadata or {})
        if not metadata.get('abandoned_reminder_sent_60d'):
            _send_abandoned_transaction_reminder(payment, days_since_created, escalate=True)
            metadata['abandoned_reminder_sent_60d'] = timezone.now().isoformat()
            payment.metadata = metadata
            payment.save(update_fields=['metadata', 'updated_at'])
            stats["abandoned_reminders_sent"] += 1
    
    # 90 days without progress - escalate to admin
    elif days_since_created == 90:
        metadata = dict(payment.metadata or {})
        if not metadata.get('abandoned_reminder_sent_90d'):
            _notify_finance_admins(payment, f"Transaction abandoned for 90 days: {payment.internal_reference}")
            metadata['abandoned_reminder_sent_90d'] = timezone.now().isoformat()
            payment.metadata = metadata
            payment.save(update_fields=['metadata', 'updated_at'])
            stats["admin_escalations"] += 1


def _send_abandoned_transaction_reminder(payment, days, escalate=False):
    """Send reminder about abandoned transaction"""
    subject = f"Action Required: Your purchase for {payment.title} needs attention"
    
    if escalate:
        message = (
            f"Your purchase transaction for {payment.title} has been pending for {days} days. "
            f"Please log in to AgriPlot and complete the next step. If no action is taken, "
            f"the transaction may be cancelled and funds returned to your wallet."
        )
    else:
        message = (
            f"We noticed your purchase for {payment.title} has been pending for {days} days. "
            f"The current step is '{payment.current_assigned_step.display_title if payment.current_assigned_step else 'Awaiting action'}'. "
            f"Please log in to continue with the transaction."
        )
    
    if payment.buyer:
        _notify_user(
            payment.buyer, 
            payment.plot, 
            subject, 
            message,
            notification_type="transaction_reminder"
        )


def _notify_finance_admins(payment, message):
    """Notify finance admins about issues requiring attention"""
    from django.contrib.auth.models import Group
    from .permissions import FINANCE_ADMIN_GROUP
    
    try:
        finance_admins = Group.objects.get(name=FINANCE_ADMIN_GROUP).users.all()
        for admin in finance_admins:
            _notify_user(
                admin,
                payment.plot,
                f"Admin Alert: {payment.internal_reference}",
                message,
                notification_type="admin_alert"
            )
    except Group.DoesNotExist:
        logger.warning(f"Finance Admin group not found for alert: {message}")


def _process_stamp_duty_reminders(payment, stats):
    """Send reminders for pending stamp duty payments to KRA"""
    if payment.transaction_type != PaymentRequest.TransactionType.PURCHASE:
        return
    
    # Check if stamp duty step is pending
    stamp_duty_step = payment.closing_steps.filter(code="stamp_duty").first()
    if not stamp_duty_step or stamp_duty_step.status == PaymentClosingStep.Status.COMPLETED:
        return
    
    # Check if stamp duty has been pending for a while
    days_since_created = (timezone.now() - payment.created_at).days
    
    if days_since_created >= 7 and not payment.metadata.get('stamp_duty_reminder_sent_7d'):
        _send_stamp_duty_reminder(payment, days_since_created)
        metadata = dict(payment.metadata or {})
        metadata['stamp_duty_reminder_sent_7d'] = timezone.now().isoformat()
        payment.metadata = metadata
        payment.save(update_fields=['metadata', 'updated_at'])
        stats["stamp_duty_reminders_sent"] += 1
    
    elif days_since_created >= 14 and not payment.metadata.get('stamp_duty_reminder_sent_14d'):
        _send_stamp_duty_reminder(payment, days_since_created, escalate=True)
        metadata = dict(payment.metadata or {})
        metadata['stamp_duty_reminder_sent_14d'] = timezone.now().isoformat()
        payment.metadata = metadata
        payment.save(update_fields=['metadata', 'updated_at'])
        stats["stamp_duty_reminders_sent"] += 1


def _send_stamp_duty_reminder(payment, days, escalate=False):
    """Send reminder about stamp duty payment to KRA"""
    estimated_duty = payment.purchase_stamp_duty_estimate
    rate = "2%" if payment.plot and payment.plot.market_zone == "rural" else "4%"
    
    subject = f"Action Required: Pay Stamp Duty for {payment.title}"
    
    if escalate:
        message = (
            f"Your stamp duty payment for {payment.title} has been pending for {days} days. "
            f"Please pay KES {estimated_duty:,.2f} ({rate}) directly to KRA via iTax (https://itax.kra.go.ke) "
            f"and upload the receipt to AgriPlot. If not paid within 30 days, the transaction may be cancelled."
        )
    else:
        message = (
            f"Please pay stamp duty for {payment.title} directly to KRA via iTax. "
            f"Estimated amount: KES {estimated_duty:,.2f} ({rate} of property value). "
            f"After payment, upload the receipt on AgriPlot for verification."
        )
    
    if payment.buyer:
        _notify_user(
            payment.buyer,
            payment.plot,
            subject,
            message,
            notification_type="stamp_duty_reminder"
        )


def process_purchase_escrow_lifecycle():
    """
    Process purchase escrow lifecycle events:
    - Check for registration completion and trigger disbursement
    - Send reminders for abandoned transactions
    - Send stamp duty reminders
    """
    stats = {
        "purchase_payments_checked": 0,
        "disbursements_triggered": 0,
        "abandoned_reminders_sent": 0,
        "admin_escalations": 0,
        "stamp_duty_reminders_sent": 0,
    }
    
    # Get active purchase payments
    purchase_payments = PaymentRequest.objects.filter(
        transaction_type=PaymentRequest.TransactionType.PURCHASE,
        status__in=[PaymentRequest.Status.PAID, PaymentRequest.Status.IN_ESCROW, PaymentRequest.Status.PARTIALLY_RELEASED],
        disbursed_at__isnull=True,
    ).select_related('plot', 'buyer', 'seller')
    
    for payment in purchase_payments:
        stats["purchase_payments_checked"] += 1
        _process_pending_registration_completion(payment, stats)
        _process_abandoned_purchase_transactions(payment, stats)
        _process_stamp_duty_reminders(payment, stats)
    
    return stats


def process_lease_lifecycle(run_at=None):
    """Process lease lifecycle events (original function)"""
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


def process_all_lifecycles():
    """
    Process all lifecycle events for both lease and purchase transactions.
    Called by the heartbeat middleware.
    """
    logger.info("Processing all payment lifecycles")
    
    lease_stats = process_lease_lifecycle()
    purchase_stats = process_purchase_escrow_lifecycle()
    
    logger.info(
        f"Lifecycle stats - Lease: {lease_stats}, "
        f"Purchase: {purchase_stats}"
    )
    
    return {
        "lease": lease_stats,
        "purchase": purchase_stats
    }