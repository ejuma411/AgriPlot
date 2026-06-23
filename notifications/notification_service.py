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
                try:
                    _send_email_now(
                        recipient=user.email,
                        subject=email_subject or subject,
                        message=message,
                        template=template,
                        context=context,
                    )
                except Exception as exc:
                    logger.error(
                        "Immediate email fallback failed for user %s: %s",
                        getattr(user, "pk", None),
                        exc,
                        exc_info=True,
                    )

            phone = _resolve_phone(user)
            if phone:
                try:
                    _send_sms_now(phone, message, template=template, context=context)
                except Exception as exc:
                    logger.error(
                        "Immediate SMS fallback failed for user %s: %s",
                        getattr(user, "pk", None),
                        exc,
                        exc_info=True,
                    )
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
        template=None,
        context=None,
    ):
        """
        1. Write the in-app Notification row synchronously.
        2. Queue email + SMS via Celery with a 30-second countdown.
        """
        if user is None:
            return None

        inapp_title = title
        inapp_message = message
        
        if template and template != "plain" and context:
            from django.template.loader import render_to_string
            import os
            try:
                basename = os.path.basename(template)
                rendered_title = render_to_string(f"notifications/inapp/{basename}_title.txt", context)
                if rendered_title.strip():
                    inapp_title = rendered_title.strip()
            except Exception:
                pass
            
            try:
                basename = os.path.basename(template)
                rendered_message = render_to_string(f"notifications/inapp/{basename}.txt", context)
                if rendered_message.strip():
                    inapp_message = rendered_message.strip()
            except Exception:
                pass

        # Step 1 — synchronous DB write
        notification = NotificationService.create_notification(
            user=user,
            notification_type=notification_type,
            title=inapp_title,
            message=inapp_message,
            plot=plot,
            task=task,
        )

        # Step 2 — synchronous outbound channels
        try:
            def _dispatch_outbound():
                NotificationService._dispatch_user_channels_immediately(
                    user,
                    subject=title,
                    message=message,
                    email_subject=email_subject,
                    template=template,
                    context=context,
                )

            NotificationService._run_after_commit(
                _dispatch_outbound,
                label=f"notify_user:{notification_type}:{user.pk}",
            )
        except Exception as exc:
            # Never let notification dispatching break the calling action
            logger.error("Failed to dispatch notification for user %s: %s", user.pk, exc)

        return notification

    @staticmethod
    def send_email(recipient, subject, template, context, *, immediate=False, pdf_attachment=None):
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
            logger.error("EmailLog creation failed: %s", exc, exc_info=True)

        # ============================================================
        # UPDATED: Handle PDF Attachments
        # ============================================================
        def _send_with_attachment():
            from django.core.mail import EmailMultiAlternatives
            from django.template.loader import render_to_string
            from django.utils.html import strip_tags

            html_message = None
            plain_message = message_body

            if template and template != "plain" and context:
                try:
                    # Use the original context with real Python/Django objects so that
                    # template variables like {{ user.username }} resolve correctly.
                    # _json_safe is only for DB/JSON serialisation, not template rendering.
                    html_message = render_to_string(f"{template}.html", context)
                    plain_message = strip_tags(html_message)
                except Exception as exc:
                    logger.warning("Email template %s failed, using fallback: %s", template, exc)
                    html_message = f"<html><body><p>{message_body}</p></body></html>"


            # Create the multipart email
            email = EmailMultiAlternatives(
                subject=subject,
                body=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
            )
            if html_message:
                email.attach_alternative(html_message, "text/html")

            # Attach the PDF if provided
            if pdf_attachment:
                filename, pdf_bytes, mime_type = pdf_attachment
                email.attach(filename, pdf_bytes, mime_type)

            # Send the email
            email.send()
            return True
        # ============================================================

        if immediate:
            try:
                sent = _send_with_attachment()
                if log and sent:
                    log.status = "sent"
                    log.sent_at = timezone.now()
                    log.save(update_fields=["status", "sent_at"])
                return log if sent else None
            except Exception as exc:
                if log:
                    log.status = "failed"
                    log.error_message = f"Immediate send failed: {exc}"
                    log.save(update_fields=["status", "error_message"])
                logger.error("Failed to send email immediately to %s: %s", recipient, exc, exc_info=True)
                return None

        try:
            def _dispatch_email():
                sent = _send_with_attachment()
                if log and sent:
                    log.status = "sent"
                    log.sent_at = timezone.now()
                    log.save(update_fields=["status", "sent_at"])

            NotificationService._run_after_commit(
                _dispatch_email,
                label=f"send_email:{recipient}",
            )
        except Exception as exc:
            if log:
                log.status = "failed"
                log.error_message = f"Email setup failed: {exc}"
                log.save(update_fields=["status", "error_message"])
            logger.error("Failed to setup email to %s: %s", recipient, exc, exc_info=True)

        return log

    @staticmethod
    def send_sms(phone_number, message):
        """Queue an SMS with a 30-second countdown."""
        if not phone_number or not NotificationService.sms_notifications_enabled():
            return {"success": False, "skipped": True}
        try:
            def _dispatch_sms():
                from notifications.tasks import _send_sms_now
                _send_sms_now(phone_number, message)

            NotificationService._run_after_commit(
                _dispatch_sms,
                label=f"send_sms:{phone_number}",
            )
            return {"success": True, "queued": False}
        except Exception as exc:
            logger.error("Failed to dispatch SMS to %s: %s", phone_number, exc)
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Domain-specific notification methods (UPDATED with templates)
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
                template="notifications/emails/task_assigned",
                context={
                    "user": task.assigned_to,
                    "task": task,
                    "plot": task.plot,
                    "assigned_by": assigned_by,
                    "task_url": settings.SITE_URL + reverse("verification:my_tasks"),
                    "login_url": settings.SITE_URL + reverse("login"),
                    "site_name": "AgriPlot Connect",
                    "task_type": task_type,
                    "assigned_at": timezone.now(),
                    "confirm_by": getattr(task, "confirm_by", None),
                    "deadline_at": getattr(task, "deadline_at", None),
                },
            )

        # Notify assigner
        if assigned_by and assigned_by != task.assigned_to:
            assignee_name = task.assigned_to.username or "user"
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
        completed_by_name = completed_by.username or "user"
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
                template="notifications/emails/verification_step_completed",
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
                    template="notifications/emails/payment_step_assigned",
                    context={
                        "user": recipient,
                        "payment": payment,
                        "step": step,
                        "payment_url": settings.SITE_URL + reverse("payments:detail", args=[payment.pk]),
                    },
                )
                
    @staticmethod
    def notify_payment_step_updated(payment, step, previous_status, actor=None):
        actor_name = actor.username if actor else "AgriPlot"
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
                    template="notifications/emails/payment_step_updated",
                    context={
                        "user": recipient,
                        "payment": payment,
                        "step": step,
                        "previous_status": previous_status.replace('_', ' ').title(),
                        "actor_name": actor_name,
                        "updated_at": timezone.now(),
                        "payment_url": settings.SITE_URL + reverse("payments:detail", args=[payment.pk]),
                    },
                )

    @staticmethod
    def notify_transaction_updated(transaction, action, amount):
        """Notify buyer and seller when a payment is made on a transaction."""
        if action == "deposit_paid":
            title = f"Deposit Received: {transaction.plot.title}"
            message = (f"An agreement deposit of KES {amount:,.2f} has been received. "
                       f"Total deposit is now KES {transaction.deposit_paid:,.2f}. "
                       f"Remaining balance: KES {transaction.balance_due:,.2f}.")
        elif action == "completion_paid":
            title = f"Balance Received: {transaction.plot.title}"
            message = (f"A completion payment of KES {amount:,.2f} has been received. "
                       f"Total paid is now KES {transaction.deposit_paid:,.2f}. "
                       f"Remaining balance: KES {transaction.balance_due:,.2f}.")
        else:
            title = f"Transaction Updated: {transaction.plot.title}"
            message = f"Transaction updated with payment of KES {amount:,.2f}."

        for recipient in [transaction.buyer, transaction.seller]:
            if not recipient:
                continue
                
            NotificationService.notify_user(
                user=recipient,
                notification_type="transaction_update",
                title=title,
                message=message,
                plot=transaction.plot,
            )
            
            if recipient.email:
                try:
                    transaction_url = settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk])
                except Exception:
                    transaction_url = ""
                
                NotificationService.send_email(
                    recipient=recipient.email,
                    subject=title,
                    template="plain",
                    context={
                        "message": f"{message}\n\nView details here: {transaction_url}",
                        "user": recipient,
                    },
                )

    @staticmethod
    def notify_plot_submitted(plot):
        submitted_by = plot.agent.user if plot.agent else plot.landowner.user
        title = f"New Plot Submitted: {plot.title}"
        message = f"A new plot has been submitted for verification by {submitted_by.username}"

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
                template="notifications/emails/new_plot_submitted",
                context={
                    "user": admin,
                    "user_username": admin.username,
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
            template="notifications/emails/plot_submitted_confirmation",
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
        message = f"The verification team has requested changes for your plot."

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
            template="notifications/emails/plot_revision_request",
            context={
                "user": plot_owner,
                "plot": plot,
                "requested_by": requested_by,
                "notes": notes,
                "edit_url": settings.SITE_URL + reverse("listings:edit_plot", args=[plot.id]),
                "support_url": settings.SITE_URL + reverse("listings:contact_support"),
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
                template="notifications/emails/plot_verification_status",
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
            template="notifications/emails/plot_verification_complete",
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
                    template="notifications/emails/no_officer_available",
                    context={
                        "admin_name": admin.get_full_name() or admin.username,
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
                    template="notifications/emails/task_confirmation_expired",
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
            template="notifications/emails/role_request_submitted",
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
                message=f"{user.username} submitted a {role} request.",
            )
            if admin.email:
                NotificationService.send_email(
                    recipient=admin.email,
                    subject=f"New Role Request: {role}",
                    template="notifications/emails/role_request",
                    context={
                        "admin": admin,
                        "user": user,
                        "role": role,
                        "details": details,
                        "review_url": settings.SITE_URL + reverse("listings:profile_management"),
                    },
                )

    @staticmethod
    def notify_role_decision(user, role, approved, decided_by=None, reason="", details=None):
        details = details or {}
        if approved:
            notification_type = "role_approved"
            title = f"Role Approved: {role}"
            message = f"Congratulations! Your {role.lower()} role request has been approved."
            template = "notifications/emails/role_approved"
        else:
            notification_type = "role_rejected"
            title = f"Role Rejected: {role}"
            message = f"Your {role.lower()} role request has been reviewed and was not approved at this time."
            if reason:
                message = f"{message} Reason: {reason}"
            template = "notifications/emails/role_rejected"

        NotificationService.create_notification(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
        )
        if user.email:
            NotificationService.send_email(
                recipient=user.email,
                subject=title,
                template=template,
                context={
                    "user": user,
                    "role": role,
                    "approved": approved,
                    "decided_by": decided_by,
                    "reason": reason,
                    "details": details,
                    "login_url": settings.SITE_URL + reverse("login"),
                    "profile_url": settings.SITE_URL + reverse("listings:profile_management"),
                    "support_url": settings.SITE_URL + reverse("listings:contact_support"),
                },
            )

    @staticmethod
    def notify_account_verified(user, verified_by):
        title = "Account Verified! 🎉"
        message = (
            f"Your account has been verified by {verified_by.username}. "
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
            template="notifications/emails/verification_success",
            context={
                "user": user,
                "verified_by": verified_by,
                "login_url": settings.SITE_URL + reverse("login"),
                "profile_url": settings.SITE_URL + reverse("listings:profile_management"),
                "browse_url": settings.SITE_URL + reverse("listings:plot_list"),
            },
        )

    @staticmethod
    def send_otp_email(user, otp, purpose="login", expiry_minutes=10):
        """Send OTP verification email."""
        title = f"Your AgriPlot Verification Code"
        NotificationService.send_email(
            recipient=user.email,
            subject=title,
            template="notifications/emails/otp_verification",
            context={
                "user": user,
                "display_name": user.get_full_name() or user.username,
                "username": user.username,
                "otp": otp,
                "expiry_minutes": expiry_minutes,
                "support_url": settings.SITE_URL + reverse("listings:contact_support"),
            },
        )

    @staticmethod
    def send_email_verification(user, verification_url, expiry_hours=24):
        """Send email verification link."""
        title = "Verify Your Email Address"
        NotificationService.send_email(
            recipient=user.email,
            subject=title,
            template="notifications/emails/email_verification_link",
            context={
                "user": user,
                "username": user.username,
                "verification_url": verification_url,
                "expiry_hours": expiry_hours,
                "dashboard_url": settings.SITE_URL + reverse("listings:dashboard_router"),
                "browse_url": settings.SITE_URL + reverse("listings:plot_list"),
                "support_url": settings.SITE_URL + reverse("listings:contact_support"),
            },
        )

    @staticmethod
    def send_welcome_email(user):
        """Send welcome email after successful registration."""
        title = "Welcome to AgriPlot Connect!"
        NotificationService.send_email(
            recipient=user.email,
            subject=title,
            template="notifications/emails/registration_success",
            context={
                "user": user,
                "profile_url": settings.SITE_URL + reverse("listings:profile_management"),
                "browse_url": settings.SITE_URL + reverse("listings:plot_list"),
            },
        )

    @staticmethod
    def send_password_reset_email(user, reset_link):
        """Send password reset email."""
        title = "Password Reset Request"
        NotificationService.send_email(
            recipient=user.email,
            subject=title,
            template="notifications/emails/password_reset_email",
            context={
                "user": user,
                "reset_link": reset_link,
                "protocol": settings.SITE_URL.split("://")[0] if "://" in settings.SITE_URL else "https",
                "domain": settings.SITE_URL.split("://")[-1] if "://" in settings.SITE_URL else settings.SITE_URL,
            },
        )

    @staticmethod
    def notify_transaction_advanced(transaction):
        """Notify buyer and seller that the transaction advanced to the next stage"""
        title = f"Transaction Advanced: {transaction.get_stage_display()}"
        message = f"Transaction for {transaction.plot.title} has progressed to {transaction.get_stage_display()}."
        
        context = {
            "transaction": transaction,
            "stage_display": transaction.get_stage_display(),
            "plot_title": transaction.plot.title,
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }

        # Notify Buyer
        if transaction.buyer and transaction.buyer.email:
            NotificationService.notify_user(
                user=transaction.buyer,
                notification_type="transaction_advanced",
                title=title,
                message=message,
                plot=transaction.plot
            )
            NotificationService.send_email(
                recipient=transaction.buyer.email,
                subject=title,
                template="notifications/emails/transaction_advanced",
                context={**context, "user": transaction.buyer}
            )

        # Notify Seller
        if transaction.seller and transaction.seller.email:
            NotificationService.notify_user(
                user=transaction.seller,
                notification_type="transaction_advanced",
                title=title,
                message=message,
                plot=transaction.plot
            )
            NotificationService.send_email(
                recipient=transaction.seller.email,
                subject=title,
                template="notifications/emails/transaction_advanced",
                context={**context, "user": transaction.seller}
            )

        # Notify Admins
        for admin in User.objects.filter(is_staff=True):
            NotificationService.notify_user(
                user=admin,
                notification_type="transaction_advanced",
                title=title,
                message=message,
                plot=transaction.plot
            )
            if admin.email:
                NotificationService.send_email(
                    recipient=admin.email,
                    subject=title,
                    template="notifications/emails/transaction_advanced",
                    context={**context, "user": admin}
                )

    @staticmethod
    def notify_transaction_completed(transaction, user, pdf_attachment=None):
        """Notify buyer or seller that the transaction is fully complete"""
        title = f"Transaction Completed: {transaction.plot.title}"
        message = f"Congratulations! The transaction for {transaction.plot.title} is now successfully completed and title transferred. Thank you for partnering with AgriPlot."
        
        context = {
            "user": user,
            "transaction": transaction,
            "plot_title": transaction.plot.title,
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }

        if user and user.email:
            NotificationService.notify_user(
                user=user,
                notification_type="transaction_completed",
                title=title,
                message=message,
                plot=transaction.plot
            )
            NotificationService.send_email(
                recipient=user.email,
                subject=title,
                template="notifications/emails/transaction_completed",
                context=context,
                immediate=True if pdf_attachment else False,
                pdf_attachment=pdf_attachment
            )

    @staticmethod
    def notify_document_uploaded(document):
        """Notify the counterparty and admin when a document is uploaded"""
        transaction = document.transaction
        uploader = document.uploaded_by
        counterparty = transaction.buyer if uploader == transaction.seller else transaction.seller
        
        title = f"New Document Uploaded: {document.get_document_type_display()}"
        message = f"{uploader.get_full_name() or uploader.username} uploaded a new document for {transaction.plot.title}."
        
        context = {
            "document": document,
            "transaction": transaction,
            "uploader": uploader,
            "doc_type": document.get_document_type_display(),
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }

        # Notify counterparty
        if counterparty and counterparty.email:
            NotificationService.notify_user(
                user=counterparty,
                notification_type="document_uploaded",
                title=title,
                message=message,
                plot=transaction.plot
            )
            NotificationService.send_email(
                recipient=counterparty.email,
                subject=title,
                template="notifications/emails/document_uploaded",
                context={**context, "user": counterparty}
            )

        # Notify Admins
        for admin in User.objects.filter(is_staff=True):
            NotificationService.create_notification(
                user=admin,
                notification_type="document_uploaded",
                title=title,
                message=message,
                plot=transaction.plot
            )

    @staticmethod
    def notify_document_verified(document):
        """Notify uploader that their document was verified"""
        transaction = document.transaction
        uploader = document.uploaded_by
        
        title = f"Document Verified: {document.get_document_type_display()}"
        message = f"Your document for {transaction.plot.title} has been verified."
        
        context = {
            "user": uploader,
            "document": document,
            "transaction": transaction,
            "doc_type": document.get_document_type_display(),
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }

        if uploader and uploader.email:
            NotificationService.notify_user(
                user=uploader,
                notification_type="document_verified",
                title=title,
                message=message,
                plot=transaction.plot
            )
            NotificationService.send_email(
                recipient=uploader.email,
                subject=title,
                template="notifications/emails/document_verified",
                context=context
            )

    @staticmethod
    def notify_document_rejected(document):
        """Notify uploader that their document was rejected"""
        transaction = document.transaction
        uploader = document.uploaded_by
        
        title = f"Action Required: Document Rejected"
        message = f"Your document {document.get_document_type_display()} for {transaction.plot.title} was rejected."
        
        context = {
            "user": uploader,
            "document": document,
            "transaction": transaction,
            "doc_type": document.get_document_type_display(),
            "rejection_reason": document.rejection_reason,
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }

        if uploader and uploader.email:
            NotificationService.notify_user(
                user=uploader,
                notification_type="document_rejected",
                title=title,
                message=message,
                plot=transaction.plot
            )
            NotificationService.send_email(
                recipient=uploader.email,
                subject=title,
                template="notifications/emails/document_rejected",
                context=context
            )

    # ------------------------------------------------------------------
    # NEW: ESCROW & PAYMENT NOTIFICATIONS
    # ------------------------------------------------------------------

    @staticmethod
    def notify_deposit_held(transaction, user):
        """Notify buyer that 10% deposit is held in escrow"""
        title = f"10% Deposit Held in Escrow - {transaction.plot.title}"
        message = f"Your deposit of KES {transaction.deposit_paid:,.2f} is securely held in escrow."
        
        context = {
            "user": user,
            "transaction": transaction,
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }
        
        NotificationService.notify_user(
            user=user,
            notification_type="deposit_held",
            title=title,
            message=message,
            email_subject=title,
            template="notifications/emails/deposit_held",
            context=context,
            plot=transaction.plot,
        )

    @staticmethod
    def notify_deposit_received(transaction, user):
        """Notify seller that 10% deposit has been received"""
        title = f"Deposit Received for {transaction.plot.title}"
        message = f"A 10% deposit of KES {transaction.deposit_paid:,.2f} has been paid into escrow."
        
        context = {
            "user": user,
            "transaction": transaction,
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }
        
        NotificationService.notify_user(
            user=user,
            notification_type="deposit_received",
            title=title,
            message=message,
            email_subject=title,
            template="notifications/emails/deposit_received",
            context=context,
            plot=transaction.plot,
        )

    @staticmethod
    def notify_balance_held(transaction, user):
        """Notify buyer that 90% balance is held in escrow"""
        title = f"90% Balance Held in Escrow - {transaction.plot.title}"
        message = f"Your completion balance of KES {transaction.balance_paid:,.2f} is securely held in escrow."
        
        context = {
            "user": user,
            "transaction": transaction,
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }
        
        NotificationService.notify_user(
            user=user,
            notification_type="balance_held",
            title=title,
            message=message,
            email_subject=title,
            template="notifications/emails/balance_held",
            context=context,
            plot=transaction.plot,
        )

    @staticmethod
    def notify_balance_received(transaction, user):
        """Notify seller that 90% balance has been received"""
        title = f"Balance Received for {transaction.plot.title}"
        message = f"The 90% completion balance of KES {transaction.balance_paid:,.2f} has been paid into escrow."
        
        context = {
            "user": user,
            "transaction": transaction,
            "transaction_url": settings.SITE_URL + reverse("transactions:detail", args=[transaction.pk]),
        }
        
        NotificationService.notify_user(
            user=user,
            notification_type="balance_received",
            title=title,
            message=message,
            email_subject=title,
            template="notifications/emails/balance_received",
            context=context,
            plot=transaction.plot,
        )

    # ------------------------------------------------------------------
    # Read helpers
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