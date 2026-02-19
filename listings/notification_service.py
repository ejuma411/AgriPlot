# listings/notification_service.py

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from .models import Notification, EmailLog, User, Plot, VerificationTask
import logging

logger = logging.getLogger(__name__)

class NotificationService:
    """Service for handling notifications and emails"""
    
    @staticmethod
    def create_notification(user, notification_type, title, message, plot=None, task=None):
        """Create an in-app notification"""
        try:
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
            # Render email content
            html_message = render_to_string(f'emails/{template}.html', context)
            plain_message = strip_tags(html_message)
            
            # Create email log
            email_log = EmailLog.objects.create(
                recipient=recipient,
                subject=subject,
                template=template,
                context=context,
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
        
        # Notification for assignee
        title = f"New Task: {task.get_verification_type_display()}"
        message = f"You have been assigned to {task.get_verification_type_display()} for plot '{task.plot.title}'"
        
        NotificationService.create_notification(
            user=task.assigned_to,
            notification_type='task_assigned',
            title=title,
            message=message,
            plot=task.plot,
            task=task
        )
        
        # Send email to assignee
        context = {
            'user': task.assigned_to,
            'task': task,
            'plot': task.plot,
            'assigned_by': assigned_by,
            'login_url': settings.SITE_URL + reverse('listings:my_tasks')
        }
        
        NotificationService.send_email(
            recipient=task.assigned_to.email,
            subject=title,
            template='task_assigned',
            context=context
        )
        
        # Notification for assigner (optional)
        if assigned_by != task.assigned_to:
            NotificationService.create_notification(
                user=assigned_by,
                notification_type='task_assigned',
                title=f"Task Assigned: {task.get_verification_type_display()}",
                message=f"Task assigned to {task.assigned_to.get_full_name()|default:task.assigned_to.username} for plot '{task.plot.title}'",
                plot=task.plot,
                task=task
            )
    
    @staticmethod
    def notify_task_completed(task, completed_by):
        """Send notifications when a task is completed"""
        
        # Get the plot owner (landowner or agent)
        plot_owner = task.plot.agent.user if task.plot.agent else task.plot.landowner.user
        
        # Notification for task creator/admin
        title = f"Task Completed: {task.get_verification_type_display()}"
        message = f"Task completed by {completed_by.get_full_name()|default:completed_by.username} for plot '{task.plot.title}'"
        
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
        
        # Notify plot owner if task was approved/rejected
        if task.approved is not None:
            status = "approved" if task.approved else "rejected"
            owner_title = f"Plot {status.title()}: {task.plot.title}"
            owner_message = f"Your plot has been {status} by the verification team."
            
            NotificationService.create_notification(
                user=plot_owner,
                notification_type=f'plot_{status}',
                title=owner_title,
                message=owner_message,
                plot=task.plot
            )
            
            # Send email to plot owner
            context = {
                'user': plot_owner,
                'plot': task.plot,
                'task': task,
                'status': status,
                'completed_by': completed_by,
                'plot_url': settings.SITE_URL + reverse('listings:plot_detail', args=[task.plot.id])
            }
            
            NotificationService.send_email(
                recipient=plot_owner.email,
                subject=owner_title,
                template='plot_verification_status',
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
                'review_url': settings.SITE_URL + reverse('listings:review_plot', args=[plot.id])
            }
            
            NotificationService.send_email(
                recipient=admin.email,
                subject=title,
                template='new_plot_submitted',
                context=context
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