from django.core.management.base import BaseCommand
from django.utils import timezone
from listings.models import VerificationTask, VerificationLog
from listings.notification_service import NotificationService


class Command(BaseCommand):
    help = "Unassign tasks not confirmed within 12 hours and notify admins"

    def handle(self, *args, **options):
        now = timezone.now()
        qs = VerificationTask.objects.filter(
            confirmation_status='pending',
            confirm_by__lt=now,
            assigned_to__isnull=False,
            status='in_progress'
        ).select_related('plot', 'assigned_to')

        total = qs.count()
        self.stdout.write(f"Found {total} unconfirmed tasks past confirm_by")

        for task in qs:
            assigned_user = task.assigned_to
            VerificationLog.objects.create(
                plot=task.plot,
                verified_by=assigned_user,
                verification_type='assignment_expired',
                comment=(
                    f"{task.get_verification_type_display()} confirmation expired. "
                    "Task unassigned for admin review."
                )
            )

            # Unassign and reset confirmation window
            task.assigned_to = None
            task.status = 'pending'
            task.confirmation_status = 'expired'
            task.confirmed_at = None
            task.confirm_by = None
            task.deadline_at = None
            task.save(update_fields=[
                'assigned_to',
                'status',
                'confirmation_status',
                'confirmed_at',
                'confirm_by',
                'deadline_at'
            ])

            try:
                NotificationService.notify_admin_task_unconfirmed(task)
            except Exception:
                # Notification failures should not stop escalation
                pass

        self.stdout.write(self.style.SUCCESS("Escalation run complete"))
