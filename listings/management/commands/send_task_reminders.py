# listings/management/commands/send_task_reminders.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.timesince import timesince  # Import the timesince function
from datetime import timedelta
from listings.models import VerificationTask
from listings.notification_service import NotificationService
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Send reminders for overdue verification tasks'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=2,
            help='Number of days after which a task is considered overdue (default: 2)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without actually sending notifications'
        )
    
    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        
        self.stdout.write(f"Checking for tasks overdue by {days} days...")
        
        # Find tasks assigned > X days ago not completed
        cutoff_date = timezone.now() - timedelta(days=days)
        overdue_tasks = VerificationTask.objects.filter(
            status='in_progress',
            assigned_at__lt=cutoff_date
        ).select_related('assigned_to', 'plot')
        
        count = overdue_tasks.count()
        self.stdout.write(f"Found {count} overdue tasks")
        
        if dry_run:
            self.stdout.write("DRY RUN - No notifications sent")
            for task in overdue_tasks:
                time_ago = timesince(task.assigned_at)  # Use timesince function
                self.stdout.write(f"  - Task {task.id}: {task.get_verification_type_display()} for {task.plot.title} assigned to {task.assigned_to.username} ({time_ago} ago)")
            return
        
        # Send reminders
        sent_count = 0
        for task in overdue_tasks:
            try:
                time_ago = timesince(task.assigned_at)  # Use timesince function
                
                NotificationService.create_notification(
                    user=task.assigned_to,
                    notification_type='task_reminder',
                    title=f"⏰ Task Overdue: {task.get_verification_type_display()}",
                    message=f"Task for plot '{task.plot.title}' assigned {time_ago} ago. Please complete soon.",
                    plot=task.plot,
                    task=task
                )
                
                # Also send email for critical overdue (> 3 days)
                if days >= 3:
                    NotificationService.send_email(
                        recipient=task.assigned_to.email,
                        subject=f"URGENT: Task Overdue - {task.get_verification_type_display()}",
                        template='task_reminder',
                        context={
                            'user': task.assigned_to,
                            'task': task,
                            'plot': task.plot,
                            'days_overdue': days,
                            'time_ago': time_ago,
                            'task_url': f"/admin/tasks/{task.id}/"
                        }
                    )
                
                sent_count += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Reminder sent for task {task.id}"))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Failed to send reminder for task {task.id}: {str(e)}"))
                logger.error(f"Failed to send task reminder: {str(e)}", exc_info=True)
        
        self.stdout.write(self.style.SUCCESS(f"Successfully sent {sent_count} reminders"))