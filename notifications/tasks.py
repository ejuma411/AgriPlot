"""
Deferred notification tasks.

The DB record (Notification row) is always written synchronously by
NotificationService.create_notification() before this task is queued.
This task only handles the outbound channels — email and SMS — which
are dispatched with a 30-second countdown so the UI action that
triggered the notification has already completed and the user sees a
clean, fast response.
"""

import logging
from html import escape

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone

from notifications.models import EmailLog

logger = logging.getLogger(__name__)

User = get_user_model()

DEFAULT_NOTIFICATION_DELAY_SECONDS = 60


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _notification_delay_seconds() -> int:
    return int(
        getattr(
            settings,
            "NOTIFICATION_DELAY_SECONDS",
            DEFAULT_NOTIFICATION_DELAY_SECONDS,
        )
    )


def _send_email_now(
    recipient: str,
    subject: str,
    message: str,
    template: str | None = None,
    context: dict | None = None,
    email_log_id: int | None = None,
) -> bool:
    """Send a single email and persist an EmailLog record. Returns True on success."""
    if not recipient:
        return False

    def _fallback_html(subject_text: str, body_text: str, context_data: dict | None = None) -> str:
        context_data = context_data or {}
        otp = context_data.get("otp")
        verification_url = context_data.get("verification_url") or context_data.get("reset_link")
        cta_label = context_data.get("cta_label") or "Open AgriPlot"
        extra_lines = []
        if verification_url:
            extra_lines.append(
                f'<p style="text-align:center; margin: 24px 0;">'
                f'<a href="{escape(str(verification_url))}" class="button">{escape(str(cta_label))}</a>'
                f'</p>'
            )
        if otp:
            extra_lines.append(
                '<div class="highlight-box">'
                f'{escape(str(otp))}'
                '</div>'
            )
        if context_data.get("support_url"):
            extra_lines.append(
                '<p style="text-align:center; margin-top: 16px;">'
                f'<a href="{escape(str(context_data["support_url"]))}">Contact Support</a>'
                '</p>'
            )
        rendered_body = escape(body_text or subject_text or "AgriPlot notification")
        return (
            "<html><body style=\"font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;\">"
            '<div style="background: linear-gradient(135deg, #069132 0%, #047a29 100%); color: #fff; padding: 28px 24px; text-align: center;">'
            "<h1 style=\"margin: 0; font-size: 24px;\">AgriPlot Connect</h1>"
            "</div>"
            '<div style="padding: 28px 24px;">'
            f"<p>{rendered_body}</p>"
            + "".join(extra_lines)
            + "</div></body></html>"
        )

    def _hydrate_context(ctx):
        if isinstance(ctx, dict):
            if "_model" in ctx and "id" in ctx:
                from django.apps import apps
                try:
                    model_class = apps.get_model(ctx["_model"])
                    return model_class.objects.get(pk=ctx["id"])
                except Exception:
                    return ctx
            return {k: _hydrate_context(v) for k, v in ctx.items()}
        elif isinstance(ctx, list):
            return [_hydrate_context(v) for v in ctx]
        return ctx

    html_message = None
    plain_message = message

    if template and template != "plain" and context:
        hydrated_context = _hydrate_context(context)
        try:
            html_message = render_to_string(f"{template}.html", hydrated_context)
            plain_message = strip_tags(html_message)
        except Exception as exc:
            logger.warning(
                "Email template %s not found or failed to render, using fallback HTML: %s",
                template,
                exc,
            )
            html_message = _fallback_html(subject, message, context)
            plain_message = message or subject or "AgriPlot notification"
    elif not message:
        plain_message = subject or "AgriPlot notification"

    log = None
    if email_log_id:
        log = EmailLog.objects.filter(pk=email_log_id).first()
    if log is None:
        log = EmailLog.objects.create(
            recipient=recipient,
            subject=subject,
            template=template or "plain",
            context=context or {},
            status="pending",
        )

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            html_message=html_message,
            fail_silently=False,
        )
        log.status = "sent"
        log.sent_at = timezone.now()
        log.save(update_fields=["status", "sent_at"])
        return True
    except Exception as exc:
        logger.error("Email to %s failed: %s", recipient, exc, exc_info=True)
        log.status = "failed"
        log.error_message = str(exc)
        log.save(update_fields=["status", "error_message"])
        return False


def _send_sms_now(phone: str, message: str) -> bool:
    """Send a single SMS. Returns True on success."""
    if not phone or not getattr(settings, "ENABLE_SMS_NOTIFICATIONS", False):
        return False
    try:
        # Import from notifications.services where the SMS service class is defined
        from notifications.services.sms_service import SMSService

        # Instantiate the class
        sms_service = SMSService()

        # Call the method we fixed earlier
        result = sms_service.send_sms(phone, message)
        return bool(result.get("success"))
    except Exception as exc:
        logger.error("SMS to %s failed: %s", phone, exc, exc_info=True)
        return False

# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="notifications.tasks.dispatch_sms_only",
)
def dispatch_sms_only(self, *, phone: str, message: str):
    """Deferred SMS dispatch."""
    try:
        _send_sms_now(phone, message)
    except Exception as exc:
        logger.error("dispatch_sms_only to %s failed: %s", phone, exc)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="notifications.tasks.dispatch_notification_channels",
)
def dispatch_notification_channels(
    self,
    *,
    user_id: int,
    subject: str,
    message: str,
    email_subject: str | None = None,
    template: str | None = None,
    context: dict | None = None,
):
    """
    Deferred outbound dispatch — email + SMS only.

    The in-app Notification DB row is already saved before this task runs.
    This task is always queued with a countdown of NOTIFICATION_DELAY_SECONDS
    so the triggering HTTP response has returned to the browser first.
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.warning("dispatch_notification_channels: user %s not found, skipping", user_id)
        return

    # --- Email ---
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
            logger.error("dispatch_notification_channels email failed for user %s: %s", user_id, exc, exc_info=True)

    # --- SMS ---
    phone = _resolve_phone(user)
    if phone:
        try:
            _send_sms_now(phone, message)
        except Exception as exc:
            logger.error("dispatch_notification_channels SMS failed for user %s: %s", user_id, exc, exc_info=True)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="notifications.tasks.dispatch_email_only",
)
def dispatch_email_only(
    self,
    *,
    recipient_email: str,
    subject: str,
    message: str,
    template: str | None = None,
    context: dict | None = None,
    email_log_id: int | None = None,
):
    """
    Deferred email dispatch to an arbitrary address (e.g. admin alerts,
    support ticket confirmations) where we only have an email, not a user_id.
    """
    try:
        _send_email_now(
            recipient=recipient_email,
            subject=subject,
            message=message,
            template=template,
            context=context,
            email_log_id=email_log_id,
        )
    except Exception as exc:
        logger.error("dispatch_email_only to %s failed: %s", recipient_email, exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Public helper used by NotificationService
# ---------------------------------------------------------------------------

def _resolve_phone(user) -> str:
    """Extract the best available phone number from a user object."""
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


def queue_notification(
    *,
    user_id: int,
    subject: str,
    message: str,
    email_subject: str | None = None,
    template: str | None = None,
    context: dict | None = None,
    delay: int | None = None,
):
    """
    Queue the outbound channels for a notification.

    Always call this AFTER the DB record has been saved.
    The task runs after `delay` seconds (default 30).
    """
    try:
        dispatch_notification_channels.apply_async(
            kwargs=dict(
                user_id=user_id,
                subject=subject,
                message=message,
                email_subject=email_subject,
                template=template,
                context=context,
            ),
            countdown=_notification_delay_seconds() if delay is None else delay,
        )
        return True
    except Exception as exc:
        logger.warning("Notification queue unavailable for user %s: %s", user_id, exc)
        return False


def queue_email(
    *,
    recipient_email: str,
    subject: str,
    message: str,
    template: str | None = None,
    context: dict | None = None,
    delay: int | None = None,
    email_log_id: int | None = None,
):
    """
    Queue a plain email to an address (no user object required).
    Used for admin alerts, support tickets, etc.
    """
    try:
        dispatch_email_only.apply_async(
            kwargs=dict(
                recipient_email=recipient_email,
                subject=subject,
                message=message,
                template=template,
                context=context,
                email_log_id=email_log_id,
            ),
            countdown=_notification_delay_seconds() if delay is None else delay,
        )
        return True
    except Exception as exc:
        logger.warning("Email queue unavailable for %s: %s", recipient_email, exc)
        return False


def queue_sms(*, phone: str, message: str, delay: int | None = None):
    try:
        dispatch_sms_only.apply_async(
            kwargs={"phone": phone, "message": message},
            countdown=_notification_delay_seconds() if delay is None else delay,
        )
        return True
    except Exception as exc:
        logger.warning("SMS queue unavailable for %s: %s", phone, exc)
        return False
