# listings/notification_service.py

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from django.contrib.auth.models import User
from notifications.services.sms_service import TextSMSService
from listings.models import Plot
from notifications.models import Notification, EmailLog
from verification.models import VerificationTask
import logging
from django.db import models

logger = logging.getLogger(__name__)

class NotificationService:
    """Service for handling notifications and emails"""

    @staticmethod
    def sms_notifications_enabled():
        return bool(getattr(settings, "ENABLE_SMS_NOTIFICATIONS", False))

    @staticmethod
    def resolve_user_phone(user):
        if user is None:
            return ""
        profile = getattr(user, "profile", None)
        if profile and getattr(profile, "phone", ""):
            return profile.phone
        contact_verification = getattr(user, "contact_verification", None)
        if contact_verification and getattr(contact_verification, "phone_number", ""):
            return contact_verification.phone_number
        agent = getattr(user, "agent", None)
        if agent and getattr(agent, "phone", ""):
            return agent.phone
        return ""

    @staticmethod
    def send_sms(phone_number, message):
        if not phone_number or not NotificationService.sms_notifications_enabled():
            return {"success": False, "skipped": True}
        try:
            sms = TextSMSService()
            return sms.send_sms(phone_number, message)
        except Exception as exc:
            logger.error("Failed to send SMS to %s: %s", phone_number, exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def notify_user(user, notification_type, title, message, *, plot=None, task=None, email_subject=None):
        if user is None:
            return None

        notification = NotificationService.create_notification(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            plot=plot,
            task=task,
        )

        if getattr(user, "email", ""):
            try:
                _subject = email_subject or f"AgriPlot: {title}"
                send_mail(
                    subject=_subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception:
                logger.exception("Failed to send notification email to %s", user.email)

        phone_number = NotificationService.resolve_user_phone(user)
        if phone_number:
            NotificationService.send_sms(phone_number, message)

        return notification

    @staticmethod
    def _json_safe(value):
        """Convert common objects to JSON-serializable values for EmailLog.context."""
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [NotificationService._json_safe(v) for v in value]
        if isinstance(value, dict):
            return {str(k): NotificationService._json_safe(v) for k, v in value.items()}
        if isinstance(value, models.Model):
            return {
                "_model": value._meta.label,
                "id": value.pk,
                "str": str(value),
            }
        return str(value)
    
    @staticmethod
    def create_notification(user, notification_type, title, message, plot=None, task=None):
        """Create an in-app notification"""
        try:
            if user is None:
                logger.warning(
                    f"Skipping notification '{notification_type}' because user is None"
                )
                return None
            notification = Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                plot=plot,
                task=task
            )
            logger.info(f"Notification created for user {user.id}: {notification_type}")
            return notification
        except Exception as e:
            logger.error(f"Error creating notification: {str(e)}", exc_info=True)
            return None
    
    @staticmethod
    def send_email(recipient, subject, template, context):
        """Send an email and log it"""
        try:
            if not recipient:
                logger.warning(f"Email not sent (missing recipient): {subject}")
                return None
            # Render email content
            html_message = render_to_string(f'notifications/emails/{template}.html', context)
            plain_message = strip_tags(html_message)
            safe_context = NotificationService._json_safe(context)
            
            # Create email log
            email_log = EmailLog.objects.create(
                recipient=recipient,
                subject=subject,
                template=template,
                context=safe_context,
                status='pending'
            )
            
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                html_message=html_message,
                fail_silently=False
            )
            
            # Update log
            email_log.status = 'sent'
            email_log.sent_at = timezone.now()
            email_log.save()
            
            logger.info(f"Email sent to {recipient}: {subject}")
            return email_log
            
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}", exc_info=True)
            
            # Update log with error
            if 'email_log' in locals():
                email_log.status = 'failed'
                email_log.error_message = str(e)
                email_log.save()
            
            return None
    
    @staticmethod
    def notify_task_assigned(task, assigned_by):
        """Send notifications when a task is assigned"""
        
        # Guard clause - check if task and assigned_to exist
        if not task or not task.assigned_to:
            logger.error(f"Cannot send task assignment notification: task or assignee missing")
            return
        
        # Notification for assignee
        task_type_display = task.get_verification_type_display()
        title = f"New Task: {task_type_display}"
        message = f"You have been assigned to {task_type_display} for plot '{task.plot.title}'"
        
        # Create in-app notification
        NotificationService.create_notification(
            user=task.assigned_to,
            notification_type='task_assigned',
            title=title,
            message=message,
            plot=task.plot,
            task=task
        )
        
        # Send email to assignee (if email exists)
        if task.assigned_to.email:
            try:
                context = {
                    'user': task.assigned_to,
                    'task': task,
                    'plot': task.plot,
                    'assigned_by': assigned_by,
                    'login_url': settings.SITE_URL + reverse('verification:my_tasks'),
                    'site_name': 'AgriPlot Connect',
                    'task_type': task_type_display,
                    'assigned_at': timezone.now().strftime("%Y-%m-%d %H:%M"),
                    'confirm_by': task.confirm_by,
                    'deadline_at': task.deadline_at
                }
                
                NotificationService.send_email(
                    recipient=task.assigned_to.email,
                    subject=title,
                    template='task_assigned',
                    context=context
                )
            except Exception as e:
                logger.error(f"Failed to send task assignment email: {str(e)}")

        # Send SMS if phone number available (optional)
        if hasattr(task.assigned_to, 'profile') and task.assigned_to.profile.phone:
            try:
                sms = TextSMSService()
                sms.send_task_assigned(
                    task.assigned_to.profile.phone,
                    task.assigned_to.get_full_name() or task.assigned_to.username,
                    task.plot.title
                )
            except Exception as e:
                logger.error(f"Failed to send task assignment SMS: {str(e)}")
        
        # Notification for assigner (optional)
        if assigned_by and assigned_by != task.assigned_to:
            assignee_name = task.assigned_to.get_full_name() or task.assigned_to.username
            NotificationService.create_notification(
                user=assigned_by,
                notification_type='task_assigned',
                title=f"Task Assigned: {task_type_display}",
                message=f"Task assigned to {assignee_name} for plot '{task.plot.title}'",
                plot=task.plot,
                task=task
            )
            
            # Also email the assigner if they want confirmation
            if assigned_by.email:
                try:
                    context = {
                        'user': assigned_by,
                        'task': task,
                        'plot': task.plot,
                        'assignee': task.assigned_to,
                        'task_type': task_type_display,
                        'assigned_at': timezone.now().strftime("%Y-%m-%d %H:%M"),
                        'login_url': settings.SITE_URL + reverse('verification:task_assignment')
                    }
                    
                    NotificationService.send_email(
                        recipient=assigned_by.email,
                        subject=f"Task Assigned: {task_type_display}",
                        template='task_assigned_confirmation',
                        context=context
                    )
                except Exception as e:
                    logger.error(f"Failed to send assignment confirmation email: {str(e)}")
        
        logger.info(f"Task assignment notifications sent for task {task.id} to {task.assigned_to.username}")
    @staticmethod
    def notify_task_completed(task, completed_by):
        """Send notifications when a task is completed"""
        
        # Get the plot owner (landowner or agent)
        plot_owner = task.plot.agent.user if task.plot.agent else task.plot.landowner.user
        
        # Notification for task creator/admin
        title = f"Task Completed: {task.get_verification_type_display()}"
        completed_by_name = completed_by.get_full_name() or completed_by.username
        message = f"Task completed by {completed_by_name} for plot '{task.plot.title}'"
        
        # Notify all admins
        admins = User.objects.filter(is_staff=True)
        for admin in admins:
            NotificationService.create_notification(
                user=admin,
                notification_type='task_completed',
                title=title,
                message=message,
                plot=task.plot,
                task=task
            )
        
        # Notify plot owner about the verification step outcome
        if task.approved is not None:
            step_status = "approved" if task.approved else "rejected"
            step_title = f"{task.get_verification_type_display()} {step_status.title()}"
            step_message = (
                f"Your plot '{task.plot.title}' has completed {task.get_verification_type_display().lower()} "
                f"and was {step_status}."
            )
            NotificationService.create_notification(
                user=plot_owner,
                notification_type='verification_step_update',
                title=step_title,
                message=step_message,
                plot=task.plot,
                task=task
            )

            context = {
                'user': plot_owner,
                'plot': task.plot,
                'task': task,
                'status': step_status,
                'completed_by': completed_by,
                'plot_url': settings.SITE_URL + reverse('listings:plot_detail', args=[task.plot.id])
            }

            NotificationService.send_email(
                recipient=plot_owner.email,
                subject=step_title,
                template='verification_step_update',
                context=context
            )
    
    @staticmethod
    def notify_plot_submitted(plot):
        """Notify admins when a new plot is submitted"""
        
        title = f"New Plot Submitted: {plot.title}"
        message = f"A new plot has been submitted for verification by {plot.agent.user.get_full_name() if plot.agent else plot.landowner.user.get_full_name()}"
        
        # Notify all admins
        admins = User.objects.filter(is_staff=True)
        for admin in admins:
            NotificationService.create_notification(
                user=admin,
                notification_type='verification_started',
                title=title,
                message=message,
                plot=plot
            )
            
            # Send email to admins
            context = {
                'user': admin,
                'plot': plot,
                'submitted_by': plot.agent.user if plot.agent else plot.landowner.user,
                'review_url': settings.SITE_URL + reverse('verification:review_plot', args=[plot.id])
            }
            
            NotificationService.send_email(
                recipient=admin.email,
                subject=title,
                template='new_plot_submitted',
                context=context
            )

        # Notify plot owner
        plot_owner = plot.agent.user if plot.agent else plot.landowner.user
        owner_title = f"Plot Submitted: {plot.title}"
        owner_message = "Your plot has been submitted and is under verification."
        NotificationService.create_notification(
            user=plot_owner,
            notification_type='plot_submitted',
            title=owner_title,
            message=owner_message,
            plot=plot
        )
        owner_context = {
            'user': plot_owner,
            'plot': plot,
            'stage': 'document_uploaded',
            'status_title': 'Submission Received',
            'plot_url': settings.SITE_URL + reverse('listings:plot_detail', args=[plot.id])
        }
        NotificationService.send_email(
            recipient=plot_owner.email,
            subject=owner_title,
            template='plot_status_update',
            context=owner_context
        )
    
    @staticmethod
    def notify_changes_requested(plot, requested_by, notes):
        """Notify plot owner when changes are requested"""
        
        plot_owner = plot.agent.user if plot.agent else plot.landowner.user
        
        title = f"Changes Requested: {plot.title}"
        message = f"The verification team has requested changes for your plot. Notes: {notes}"
        
        NotificationService.create_notification(
            user=plot_owner,
            notification_type='changes_requested',
            title=title,
            message=message,
            plot=plot
        )
        
        # Send email
        context = {
            'user': plot_owner,
            'plot': plot,
            'requested_by': requested_by,
            'notes': notes,
            'edit_url': settings.SITE_URL + reverse('listings:edit_plot', args=[plot.id])
        }
        
        NotificationService.send_email(
            recipient=plot_owner.email,
            subject=title,
            template='changes_requested',
            context=context
        )

    @staticmethod
    def notify_plot_stage(plot, stage, details=None):
        """Notify plot owner about a verification stage update."""
        try:
            plot_owner = plot.agent.user if plot.agent else plot.landowner.user
            stage_titles = {
                'api_verification_started': 'API Verification Started',
                'title_search_completed': 'Title Search Completed',
                'admin_review': 'Admin Review',
                'physical_location_verified': 'Physical Location Verified',
            }
            status_title = stage_titles.get(stage, stage.replace('_', ' ').title())
            title = f"Verification Update: {plot.title}"
            message = f"Your plot verification moved to: {status_title}."
            NotificationService.create_notification(
                user=plot_owner,
                notification_type='plot_stage_update',
                title=title,
                message=message,
                plot=plot
            )
            context = {
                'user': plot_owner,
                'plot': plot,
                'stage': stage,
                'status_title': status_title,
                'details': details or {},
                'plot_url': settings.SITE_URL + reverse('listings:plot_detail', args=[plot.id])
            }
            NotificationService.send_email(
                recipient=plot_owner.email,
                subject=title,
                template='plot_status_update',
                context=context
            )
        except Exception as e:
            logger.error(f"Plot stage notification failed: {e}")

    @staticmethod
    def notify_plot_final_status(plot, status, completed_by, notes=""):
        """Notify plot owner when the plot is finally approved or rejected."""
        plot_owner = plot.agent.user if plot.agent else plot.landowner.user
        title = f"Plot {status.title()}: {plot.title}"
        NotificationService.create_notification(
            user=plot_owner,
            notification_type=f'plot_{status}',
            title=title,
            message=f"Your plot has been {status}.",
            plot=plot
        )
        context = {
            'user': plot_owner,
            'plot': plot,
            'task': None,
            'status': status,
            'completed_by': completed_by,
            'plot_url': settings.SITE_URL + reverse('listings:plot_detail', args=[plot.id])
        }
        if notes:
            context['notes'] = notes
        NotificationService.send_email(
            recipient=plot_owner.email,
            subject=title,
            template='plot_verification_status',
            context=context
        )

    @staticmethod
    def notify_admin_no_officer(plot, role_label, county):
        admins = User.objects.filter(is_superuser=True)
        for admin in admins:
            NotificationService.create_notification(
                user=admin,
                notification_type='no_officer_available',
                title=f"No {role_label} Available",
                message=f"No verified {role_label.lower()} available for {county}. Plot '{plot.title}' needs manual assignment.",
                plot=plot
            )
            if admin.email:
                NotificationService.send_email(
                    recipient=admin.email,
                    subject=f"No {role_label} Available for {county}",
                    template='no_officer_available',
                    context={
                        'admin': admin,
                        'plot': plot,
                        'role_label': role_label,
                        'county': county,
                        'review_url': settings.SITE_URL + reverse('verification:task_assignment')
                    }
                )

    @staticmethod
    def notify_admin_task_unconfirmed(task):
        """Notify superusers when an assigned task was not confirmed in time."""
        admins = User.objects.filter(is_superuser=True)
        for admin in admins:
            NotificationService.create_notification(
                user=admin,
                notification_type='task_unconfirmed',
                title="Task Confirmation Expired",
                message=(
                    f"{task.get_verification_type_display()} for plot '{task.plot.title}' "
                    "was not confirmed within 12 hours and has been unassigned."
                ),
                plot=task.plot,
                task=task
            )
            if admin.email:
                NotificationService.send_email(
                    recipient=admin.email,
                    subject="Task Confirmation Expired",
                    template='task_unconfirmed_escalation',
                    context={
                        'admin': admin,
                        'task': task,
                        'plot': task.plot,
                        'review_url': settings.SITE_URL + reverse('verification:task_assignment')
                    }
                )

    @staticmethod
    def notify_role_request(user, role, details=None):
        """Notify user and admins when a role request is submitted."""
        details = details or {}
        user_title = f"Role Request Received: {role}"
        NotificationService.send_email(
            recipient=user.email,
            subject=user_title,
            template='role_request_received',
            context={
                'user': user,
                'role': role,
                'details': details,
                'profile_url': settings.SITE_URL + reverse('listings:profile_management'),
            }
        )
        NotificationService.create_notification(
            user=user,
            notification_type='role_request',
            title=user_title,
            message=f"Your {role} request has been submitted and is under review."
        )

        admins = User.objects.filter(is_staff=True)
        for admin in admins:
            NotificationService.create_notification(
                user=admin,
                notification_type='role_request',
                title=f"New Role Request: {role}",
                message=f"{user.get_full_name() or user.username} submitted a {role} request."
            )
            if admin.email:
                NotificationService.send_email(
                    recipient=admin.email,
                    subject=f"New Role Request: {role}",
                    template='role_request_admin',
                    context={
                        'admin': admin,
                        'user': user,
                        'role': role,
                        'details': details,
                        'review_url': settings.SITE_URL + reverse('listings:profile_management')
                    }
                )
    
    @staticmethod
    def get_user_notifications(user, limit=50, unread_only=False):
        """Get notifications for a user"""
        queryset = Notification.objects.filter(user=user)
        
        if unread_only:
            queryset = queryset.filter(is_read=False)
        
        return queryset[:limit]
    
    @staticmethod
    def mark_all_as_read(user):
        """Mark all notifications as read for a user"""
        return Notification.objects.filter(user=user, is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )

    @staticmethod
    def notify_account_verified(user, verified_by):
        """Send notification when account is verified"""
        title = "Account Verified! 🎉"
        message = f"Your account has been verified by {verified_by.get_full_name()}. You can now list plots."

        NotificationService.create_notification(
            user=user,
            notification_type='account_verified',
            title=title,
            message=message
        )

        context = {
            'user': user,
            'verified_by': verified_by,
            'login_url': settings.SITE_URL + reverse('listings:staff_dashboard')
        }

        NotificationService.send_email(
            recipient=user.email,
            subject=title,
            template='account_verified',
            context=context
        )
