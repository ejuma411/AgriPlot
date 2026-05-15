"""
NotificationService — AgriPlot

Design contract
---------------
1. create_notification()  → always synchronous DB write, returns the Notification row.
2. notify_user()          → DB write first, then queues email + SMS via Celery (30 s delay).
3. send_email()           → queues email only via Celery (30 s delay).
4. send_sms()             → queues SMS only via Celery (30 s delay).

This means every HTTP response returns to the browser before any outbound
channel fires, giving a fast, clean UI/UX experience.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from notifications.models import EmailLog, Notification
from notifications.services.sms_service import SMSService
from verification.models import VerificationTask  # noqa: F401 — kept for callers

logger = logging.getLogger(__name__)
User = get_user_model()


class NotificationService:
    """Central notification service for AgriPlot."""

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def sms_notifications_enabled() -> bool:
        return bool(getattr(settings, "ENABLE_SMS_NOTIFICATIONS", False))

    @staticmethod
    def resolve_user_phone(user) -> str:
        if user is None:
            return ""
        profile = getattr(user, "profile", None)
        if profile and getattr(profile, "phone", ""):
            return profile.phone
        contact = getattr(user, "contact_verification", None)
        if contact and getattr(contact, "phone_number", ""):
            return contact.phone_number
        agent = getattr(user, "agent", None)
        if agent and getattr(agent, "phone", ""):
            return agent.phone
        return ""

    @staticmethod
    def _json_safe(value):
        """Recursively convert objects to JSON-serialisable values."""
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [NotificationService._json_safe(v) for v in value]
        if isinstance(value, dict):
            return {str(k): NotificationService._json_safe(v) for k, v in value.items()}
        if isinstance(value, models.Model):
            return {"_model": value._meta.label, "id": value.pk, "str": str(value)}
        return str(value)

    # ------------------------------------------------------------------
    # Core: synchronous DB write
    # ------------------------------------------------------------------

    @staticmethod
    def create_notification(user, notification_type, title, message, plot=None, task=None):
        """
        Write an in-app Notification row to the database.
        This is always synchronous — the row exists before the HTTP response
        returns so the UI can display it immediately.
        """
        if user is None:
            logger.warning("Skipping notification '%s' — user is None", notification_type)
            return None
        try:
            notification = Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                plot=plot,
                task=task,
            )
            logger.info("Notification saved for user %s: %s", user.id, notification_type)
            return notification
        except Exception as exc:
            logger.error("create_notification failed: %s", exc, exc_info=True)
            return None

    @staticmethod
    def notification_delay_seconds() -> int:
        return int(getattr(settings, "NOTIFICATION_DELAY_SECONDS", 60))

    @staticmethod
    def _run_after_commit(callback, *, label: str):
        def _safe_callback():
            try:
                callback()
            except Exception as exc:
                logger.error("Deferred notification callback failed for %s: %s", label, exc)

        transaction.on_commit(_safe_callback)

    @staticmethod
    def _dispatch_user_channels_immediately(
        user,
        *,
        subject,
        message,
        email_subject=None,
        template=None,
        context=None,
    ):
        """Fallback path when Celery/Redis queueing is unavailable."""
        try:
            from notifications.tasks import _resolve_phone, _send_email_now, _send_sms_now

            if getattr(user, "email", ""):
                _send_email_now(
                    recipient=user.email,
                    subject=email_subject or subject,
                    message=message,
                    template=template,
                    context=context,
                )

            phone = _resolve_phone(user)
            if phone:
                _send_sms_now(phone, message)
        except Exception as exc:
            logger.error("Immediate notification fallback failed for user %s: %s", getattr(user, "pk", None), exc)

    # ------------------------------------------------------------------
    # Core: deferred outbound dispatch
    # ------------------------------------------------------------------

    @staticmethod
    def notify_user(
        user,
        notification_type,
        title,
        message,
        *,
        plot=None,
        task=None,
        email_subject=None,
    ):
        """
        1. Write the in-app Notification row synchronously.
        2. Queue email + SMS via Celery with a 30-second countdown.
        """
        if user is None:
            return None

        # Step 1 — synchronous DB write
        notification = NotificationService.create_notification(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            plot=plot,
            task=task,
        )

        # Step 2 — deferred outbound channels
        try:
            from notifications.tasks import queue_notification

            def _queue_outbound():
                try:
                    queue_notification(
                        user_id=user.pk,
                        subject=title,
                        message=message,
                        email_subject=email_subject,
                        delay=NotificationService.notification_delay_seconds(),
                    )
                except Exception as exc:
                    logger.error("Queue notification failed for user %s: %s. Falling back to immediate send.", user.pk, exc)
                    NotificationService._dispatch_user_channels_immediately(
                        user,
                        subject=title,
                        message=message,
                        email_subject=email_subject,
                    )

            NotificationService._run_after_commit(
                _queue_outbound,
                label=f"notify_user:{notification_type}:{user.pk}",
            )
        except Exception as exc:
            # Never let task queuing break the calling action
            logger.error("Failed to queue notification for user %s: %s", user.pk, exc)

        return notification

    @staticmethod
    def send_email(recipient, subject, template, context, *, immediate=False):
        """
        Queue a templated email with a 30-second countdown.
        Also creates a pending EmailLog row synchronously so the record
        exists before the task fires.
        """
        if not recipient:
            logger.warning("send_email skipped — no recipient for subject: %s", subject)
            return None

        safe_context = NotificationService._json_safe(context)
        template_name = template or "plain"
        message_body = context.get("message", subject) if isinstance(context, dict) else subject

        # Synchronous log row so we have a record even if the task never runs
        log = None
        queue_state = {"queued": False}
        try:
            log = EmailLog.objects.create(
                recipient=recipient,
                subject=subject,
                template=template_name,
                context=safe_context,
                status="pending",
            )
        except Exception as exc:
            logger.error("EmailLog creation failed: %s", exc)

        if immediate:
            try:
                from notifications.tasks import _send_email_now

                sent = _send_email_now(
                    recipient=recipient,
                    subject=subject,
                    message=message_body,
                    template=template_name,
                    context=safe_context,
                    email_log_id=log.pk if log else None,
                )
                return log if sent else None
            except Exception as exc:
                if log:
                    log.status = "failed"
                    log.error_message = f"Immediate send failed: {exc}"
                    log.save(update_fields=["status", "error_message"])
                logger.error("Failed to send email immediately to %s: %s", recipient, exc)
                return None

        try:
            from notifications.tasks import queue_email

            def _queue_email():
                try:
                    queue_email(
                        recipient_email=recipient,
                        subject=subject,
                        message=message_body,
                        template=template_name,
                        context=safe_context,
                        delay=NotificationService.notification_delay_seconds(),
                        email_log_id=log.pk if log else None,
                    )
                    queue_state["queued"] = True
                except Exception as exc:
                    logger.error("Email queue failed for %s: %s. Falling back to immediate send.", recipient, exc)
                    from notifications.tasks import _send_email_now

                    sent = _send_email_now(
                        recipient=recipient,
                        subject=subject,
                        message=message_body,
                        template=template_name,
                        context=safe_context,
                        email_log_id=log.pk if log else None,
                    )
                    queue_state["queued"] = sent

            NotificationService._run_after_commit(
                _queue_email,
                label=f"send_email:{recipient}",
            )
        except Exception as exc:
            if log:
                log.status = "failed"
                log.error_message = f"Queue setup failed: {exc}"
                log.save(update_fields=["status", "error_message"])
            logger.error("Failed to queue email to %s: %s", recipient, exc)

        if queue_state["queued"]:
            return log
        return None

    @staticmethod
    def send_sms(phone_number, message):
        """Queue an SMS with a 30-second countdown."""
        if not phone_number or not NotificationService.sms_notifications_enabled():
            return {"success": False, "skipped": True}
        try:
            from notifications.tasks import queue_sms

            sms_state = {"queued": False}

            def _queue_sms():
                try:
                    queue_sms(
                        phone=phone_number,
                        message=message,
                        delay=NotificationService.notification_delay_seconds(),
                    )
                    sms_state["queued"] = True
                except Exception as exc:
                    logger.error("SMS queue failed for %s: %s. Falling back to immediate send.", phone_number, exc)
                    from notifications.tasks import _send_sms_now

                    sms_state["queued"] = _send_sms_now(phone_number, message)

            NotificationService._run_after_commit(
                _queue_sms,
                label=f"send_sms:{phone_number}",
            )
            return {"success": True, "queued": True}
        except Exception as exc:
            logger.error("Failed to queue SMS to %s: %s", phone_number, exc)
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Domain-specific notification methods
    # ------------------------------------------------------------------

    @staticmethod
    def notify_task_assigned(task, assigned_by):
        if not task or not task.assigned_to:
            logger.error("notify_task_assigned: task or assignee missing")
            return

        task_type = task.get_verification_type_display()
        title = f"New Task: {task_type}"
        message = f"You have been assigned to {task_type} for plot '{task.plot.title}'"

        # In-app + deferred outbound for assignee
        NotificationService.notify_user(
            user=task.assigned_to,
            notification_type="task_assigned",
            title=title,
            message=message,
            plot=task.plot,
            task=task,
        )

        # Deferred email with full template context
        if task.assigned_to.email:
            NotificationService.send_email(
                recipient=task.assigned_to.email,
                subject=title,
                template="task_assigned",
                context={
                    "user": task.assigned_to,
                    "task": task,
                    "plot": task.plot,
                    "assigned_by": assigned_by,
                    "login_url": settings.SITE_URL + reverse("verification:my_tasks"),
                    "site_name": "AgriPlot Connect",
                    "task_type": task_type,
                    "assigned_at": timezone.now().strftime("%Y-%m-%d %H:%M"),
                    "confirm_by": task.confirm_by,
                    "deadline_at": task.deadline_at,
                },
            )

        # Notify assigner
        if assigned_by and assigned_by != task.assigned_to:
            assignee_name = task.assigned_to.get_full_name() or task.assigned_to.username
            NotificationService.notify_user(
                user=assigned_by,
                notification_type="task_assigned",
                title=f"Task Assigned: {task_type}",
                message=f"Task assigned to {assignee_name} for plot '{task.plot.title}'",
                plot=task.plot,
                task=task,
            )

        logger.info("Task assignment notifications queued for task %s", task.id)

    @staticmethod
    def notify_task_completed(task, completed_by):
        plot_owner = task.plot.agent.user if task.plot.agent else task.plot.landowner.user
        task_type = task.get_verification_type_display()
        title = f"Task Completed: {task_type}"
        completed_by_name = completed_by.get_full_name() or completed_by.username
        message = f"Task completed by {completed_by_name} for plot '{task.plot.title}'"

        for admin in User.objects.filter(is_staff=True):
            NotificationService.create_notification(
                user=admin,
                notification_type="task_completed",
                title=title,
                message=message,
                plot=task.plot,
                task=task,
            )

        if task.approved is not None:
            step_status = "approved" if task.approved else "rejected"
            step_title = f"{task_type} {step_status.title()}"
            step_message = (
                f"Your plot '{task.plot.title}' completed {task_type.lower()} and was {step_status}."
            )
            NotificationService.notify_user(
                user=plot_owner,
                notification_type="verification_step_update",
                title=step_title,
                message=step_message,
                plot=task.plot,
                task=task,
            )
            NotificationService.send_email(
                recipient=plot_owner.email,
                subject=step_title,
                template="verification_step_update",
                context={
                    "user": plot_owner,
                    "plot": task.plot,
                    "task": task,
                    "status": step_status,
                    "completed_by": completed_by,
                    "plot_url": settings.SITE_URL + reverse("listings:plot_detail", args=[task.plot.id]),
                },
            )

    @staticmethod
    def _payment_step_recipients(payment, step):
        recipients = []
        if payment.buyer:
            recipients.append(payment.buyer)
        if payment.seller:
            recipients.append(payment.seller)

        label = (step.responsible_party_label or "").lower()
        if any(token in label for token in ["admin", "lawyer", "valuer", "government", "operations", "registrar"]):
            recipients.extend(
                User.objects.filter(
                    models.Q(is_superuser=True) | models.Q(groups__name="Finance Admin") | models.Q(is_staff=True)
                ).distinct()
            )

        return {user.pk: user for user in recipients if user}.values()

    @staticmethod
    def notify_payment_step_assigned(payment, step):
        title = f"Next transaction step: {step.display_title}"
        message = (
            f"The next transaction step for '{payment.title}' is now active: "
            f"{step.display_title}. Responsible party: {step.responsible_party_label}."
        )

        for recipient in NotificationService._payment_step_recipients(payment, step):
            NotificationService.notify_user(
                user=recipient,
                notification_type="plot_stage_update",
                title=title,
                message=message,
                plot=payment.plot,
            )
            if recipient.email:
                NotificationService.send_email(
                    recipient=recipient.email,
                    subject=title,
                    template="plain",
                    context={"message": message},
                )

    @staticmethod
    def notify_payment_step_updated(payment, step, previous_status, actor=None):
        actor_name = actor.get_full_name() or actor.username if actor else "AgriPlot"
        title = f"Transaction step updated: {step.display_title}"
        message = (
            f"{step.display_title} for '{payment.title}' moved from "
            f"{previous_status.replace('_', ' ').title()} to {step.get_status_display()} by {actor_name}."
        )

        for recipient in NotificationService._payment_step_recipients(payment, step):
            NotificationService.notify_user(
                user=recipient,
                notification_type="verification_step_update",
                title=title,
                message=message,
                plot=payment.plot,
            )
            if recipient.email:
                NotificationService.send_email(
                    recipient=recipient.email,
                    subject=title,
                    template="plain",
                    context={"message": message},
                )

    @staticmethod
    def notify_plot_submitted(plot):
        submitted_by = plot.agent.user if plot.agent else plot.landowner.user
        title = f"New Plot Submitted: {plot.title}"
        message = f"A new plot has been submitted for verification by {submitted_by.get_full_name() or submitted_by.username}"

        for admin in User.objects.filter(is_staff=True):
            NotificationService.create_notification(
                user=admin,
                notification_type="verification_started",
                title=title,
                message=message,
                plot=plot,
            )
            NotificationService.send_email(
                recipient=admin.email,
                subject=title,
                template="new_plot_submitted",
                context={
                    "user": admin,
                    "plot": plot,
                    "submitted_by": submitted_by,
                    "review_url": settings.SITE_URL + reverse("verification:review_plot", args=[plot.id]),
                },
            )

        NotificationService.notify_user(
            user=submitted_by,
            notification_type="plot_submitted",
            title=f"Plot Submitted: {plot.title}",
            message="Your plot has been submitted and is under verification.",
            plot=plot,
        )
        NotificationService.send_email(
            recipient=submitted_by.email,
            subject=f"Plot Submitted: {plot.title}",
            template="plot_status_update",
            context={
                "user": submitted_by,
                "plot": plot,
                "stage": "document_uploaded",
                "status_title": "Submission Received",
                "plot_url": settings.SITE_URL + reverse("listings:plot_detail", args=[plot.id]),
            },
        )

    @staticmethod
    def notify_changes_requested(plot, requested_by, notes):
        plot_owner = plot.agent.user if plot.agent else plot.landowner.user
        title = f"Changes Requested: {plot.title}"
        message = f"The verification team has requested changes for your plot. Notes: {notes}"

        NotificationService.notify_user(
            user=plot_owner,
            notification_type="changes_requested",
            title=title,
            message=message,
            plot=plot,
        )
        NotificationService.send_email(
            recipient=plot_owner.email,
            subject=title,
            template="changes_requested",
            context={
                "user": plot_owner,
                "plot": plot,
                "requested_by": requested_by,
                "notes": notes,
                "edit_url": settings.SITE_URL + reverse("listings:edit_plot", args=[plot.id]),
            },
        )

    @staticmethod
    def notify_plot_stage(plot, stage, details=None):
        try:
            plot_owner = plot.agent.user if plot.agent else plot.landowner.user
            stage_titles = {
                "api_verification_started": "API Verification Started",
                "title_search_completed": "Title Search Completed",
                "admin_review": "Admin Review",
                "physical_location_verified": "Physical Location Verified",
            }
            status_title = stage_titles.get(stage, stage.replace("_", " ").title())
            title = f"Verification Update: {plot.title}"
            message = f"Your plot verification moved to: {status_title}."

            NotificationService.notify_user(
                user=plot_owner,
                notification_type="plot_stage_update",
                title=title,
                message=message,
                plot=plot,
            )
            NotificationService.send_email(
                recipient=plot_owner.email,
                subject=title,
                template="plot_status_update",
                context={
                    "user": plot_owner,
                    "plot": plot,
                    "stage": stage,
                    "status_title": status_title,
                    "details": details or {},
                    "plot_url": settings.SITE_URL + reverse("listings:plot_detail", args=[plot.id]),
                },
            )
        except Exception as exc:
            logger.error("notify_plot_stage failed: %s", exc)

    @staticmethod
    def notify_plot_final_status(plot, status, completed_by, notes=""):
        plot_owner = plot.agent.user if plot.agent else plot.landowner.user
        title = f"Plot {status.title()}: {plot.title}"
        NotificationService.notify_user(
            user=plot_owner,
            notification_type=f"plot_{status}",
            title=title,
            message=f"Your plot has been {status}.",
            plot=plot,
        )
        context = {
            "user": plot_owner,
            "plot": plot,
            "task": None,
            "status": status,
            "completed_by": completed_by,
            "plot_url": settings.SITE_URL + reverse("listings:plot_detail", args=[plot.id]),
        }
        if notes:
            context["notes"] = notes
        NotificationService.send_email(
            recipient=plot_owner.email,
            subject=title,
            template="plot_verification_status",
            context=context,
        )

    @staticmethod
    def notify_admin_no_officer(plot, role_label, county):
        for admin in User.objects.filter(is_superuser=True):
            NotificationService.create_notification(
                user=admin,
                notification_type="no_officer_available",
                title=f"No {role_label} Available",
                message=(
                    f"No verified {role_label.lower()} available for {county}. "
                    f"Plot '{plot.title}' needs manual assignment."
                ),
                plot=plot,
            )
            if admin.email:
                NotificationService.send_email(
                    recipient=admin.email,
                    subject=f"No {role_label} Available for {county}",
                    template="no_officer_available",
                    context={
                        "admin": admin,
                        "plot": plot,
                        "role_label": role_label,
                        "county": county,
                        "review_url": settings.SITE_URL + reverse("verification:task_assignment"),
                    },
                )

    @staticmethod
    def notify_admin_task_unconfirmed(task):
        for admin in User.objects.filter(is_superuser=True):
            NotificationService.create_notification(
                user=admin,
                notification_type="task_unconfirmed",
                title="Task Confirmation Expired",
                message=(
                    f"{task.get_verification_type_display()} for plot '{task.plot.title}' "
                    "was not confirmed within 12 hours and has been unassigned."
                ),
                plot=task.plot,
                task=task,
            )
            if admin.email:
                NotificationService.send_email(
                    recipient=admin.email,
                    subject="Task Confirmation Expired",
                    template="task_unconfirmed_escalation",
                    context={
                        "admin": admin,
                        "task": task,
                        "plot": task.plot,
                        "review_url": settings.SITE_URL + reverse("verification:task_assignment"),
                    },
                )

    @staticmethod
    def notify_role_request(user, role, details=None):
        details = details or {}
        user_title = f"Role Request Received: {role}"
        NotificationService.create_notification(
            user=user,
            notification_type="role_request",
            title=user_title,
            message=f"Your {role} request has been submitted and is under review.",
        )
        NotificationService.send_email(
            recipient=user.email,
            subject=user_title,
            template="role_request_received",
            context={
                "user": user,
                "role": role,
                "details": details,
                "profile_url": settings.SITE_URL + reverse("listings:profile_management"),
            },
        )
        for admin in User.objects.filter(is_staff=True):
            NotificationService.create_notification(
                user=admin,
                notification_type="role_request",
                title=f"New Role Request: {role}",
                message=f"{user.get_full_name() or user.username} submitted a {role} request.",
            )
            if admin.email:
                NotificationService.send_email(
                    recipient=admin.email,
                    subject=f"New Role Request: {role}",
                    template="role_request_admin",
                    context={
                        "admin": admin,
                        "user": user,
                        "role": role,
                        "details": details,
                        "review_url": settings.SITE_URL + reverse("listings:profile_management"),
                    },
                )

    @staticmethod
    def notify_account_verified(user, verified_by):
        title = "Account Verified! 🎉"
        message = (
            f"Your account has been verified by {verified_by.get_full_name() or verified_by.username}. "
            "You can now list plots."
        )
        NotificationService.notify_user(
            user=user,
            notification_type="account_verified",
            title=title,
            message=message,
        )
        NotificationService.send_email(
            recipient=user.email,
            subject=title,
            template="account_verified",
            context={
                "user": user,
                "verified_by": verified_by,
                "login_url": settings.SITE_URL + reverse("listings:staff_dashboard"),
            },
        )

    # ------------------------------------------------------------------
    # Read helpers (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def get_user_notifications(user, limit=50, unread_only=False):
        queryset = Notification.objects.filter(user=user)
        if unread_only:
            queryset = queryset.filter(is_read=False)
        return queryset[:limit]

    @staticmethod
    def mark_all_as_read(user):
        return Notification.objects.filter(user=user, is_read=False).update(
            is_read=True,
            read_at=timezone.now(),
        )
