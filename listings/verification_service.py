# listings/verification_service.py

from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from .models import VerificationTask, VerificationLog, Plot
from .notification_service import NotificationService
import logging

logger = logging.getLogger(__name__)

class VerificationService:
    """Service layer for verification business logic"""
    
    @staticmethod
    def create_verification_tasks(plot):
        """
        Create all necessary verification tasks when a plot is submitted
        """
        content_type = ContentType.objects.get_for_model(Plot)
        
        tasks_created = []
        
        # Task 1: Document Review (always required)
        doc_task, created = VerificationTask.objects.get_or_create(
            plot=plot,
            verification_type='document_review',
            defaults={
                'status': 'pending',
                'assigned_at': timezone.now()
            }
        )
        if created:
            tasks_created.append('document_review')
            logger.info(f"Created document review task for plot {plot.id}")
        
        # Task 2: Extension Officer Review (for agricultural land)
        if plot.land_type == 'agricultural':
            ext_task, created = VerificationTask.objects.get_or_create(
                plot=plot,
                verification_type='extension_review',
                defaults={
                    'status': 'pending',
                    'assigned_at': timezone.now()
                }
            )
            if created:
                tasks_created.append('extension_review')
                logger.info(f"Created extension review task for plot {plot.id}")
        
        # Task 3: Surveyor Inspection (for large plots or complex cases)
        if plot.area > 50:  # Example: plots > 50 acres need surveyor
            survey_task, created = VerificationTask.objects.get_or_create(
                plot=plot,
                verification_type='surveyor_inspection',
                defaults={
                    'status': 'pending',
                    'assigned_at': timezone.now()
                }
            )
            if created:
                tasks_created.append('surveyor_inspection')
                logger.info(f"Created surveyor inspection task for plot {plot.id}")
        
        # Log the creation
        VerificationLog.objects.create(
            plot=plot,
            verification_type='system',
            comment=f"Created verification tasks: {', '.join(tasks_created)}"
        )
        
        return tasks_created
    
    @staticmethod
    def assign_task(task_id, assigned_to_user, assigned_by):
        """Assign a verification task to a specific staff member"""
        try:
            task = VerificationTask.objects.get(id=task_id)
            task.assigned_to = assigned_to_user
            task.status = 'in_progress'
            task.assigned_at = timezone.now()
            task.save()
            
            # Send notification
            NotificationService.notify_task_assigned(task, assigned_by)
            
            # Log the assignment
            VerificationLog.objects.create(
                plot=task.plot,
                verified_by=assigned_by,
                verification_type='assignment',
                comment=f"Task '{task.get_verification_type_display()}' assigned to {assigned_to_user.username}"
            )
            
            logger.info(f"Task {task_id} assigned to {assigned_to_user.username}")
            return task
            
        except VerificationTask.DoesNotExist:
            logger.error(f"Task {task_id} not found")
            return None
    
    @staticmethod
    def complete_task(task_id, completed_by, notes="", approved=None):
        """Mark a verification task as completed"""
        try:
            task = VerificationTask.objects.get(id=task_id)
            task.status = 'completed'
            task.completed_at = timezone.now()
            task.notes = notes
            task.approved = approved
            task.save()
            
            # Send notification
            NotificationService.notify_task_completed(task, completed_by)
            
            # Log the completion
            status = "approved" if approved else "rejected" if approved is False else "completed"
            VerificationLog.objects.create(
                plot=task.plot,
                verified_by=completed_by,
                verification_type=task.verification_type,
                comment=f"Task completed: {status}. Notes: {notes}"
            )
            
            logger.info(f"Task {task_id} completed by {completed_by.username}")
            
            # Check if all tasks are completed
            VerificationService.check_plot_verification_completion(task.plot)
            
            return task
            
        except VerificationTask.DoesNotExist:
            logger.error(f"Task {task_id} not found")
            return None
        
    @staticmethod
    def check_plot_verification_completion(plot):
        """
        Check if all required tasks are completed and update plot verification status
        """
        pending_tasks = VerificationTask.objects.filter(
            plot=plot,
            status__in=['pending', 'in_progress']
        ).count()
        
        if pending_tasks == 0:
            # All tasks completed - update verification status
            content_type = ContentType.objects.get_for_model(Plot)
            verification = plot.verification.first()
            
            if verification:
                verification.current_stage = 'approved'
                verification.approved_at = timezone.now()
                verification.save()
                
                VerificationLog.objects.create(
                    plot=plot,
                    verification_type='approval',
                    comment="All verification tasks completed. Plot approved."
                )
                
                logger.info(f"Plot {plot.id} fully verified and approved")
                return True
        
        return False
    
    @staticmethod
    def get_staff_workload():
        """
        Get workload statistics for all staff members
        """
        from django.contrib.auth.models import User
        from django.utils import timezone
        
        staff_users = User.objects.filter(is_staff=True)
        
        workload = []
        for user in staff_users:
            pending = VerificationTask.objects.filter(
                assigned_to=user,
                status='in_progress'
            ).count()
            
            completed_today = VerificationTask.objects.filter(
                assigned_to=user,
                status='completed',
                completed_at__date=timezone.now().date()
            ).count()
            
            total_assigned = VerificationTask.objects.filter(
                assigned_to=user
            ).count()
            
            workload.append({
                'user': user,
                'pending': pending,
                'completed_today': completed_today,
                'total_assigned': total_assigned
            })
        
        return workload
        @staticmethod
        def get_task_statistics():
            """
            Get overall task statistics for dashboard
            """
            from django.utils import timezone
            from datetime import timedelta
            
            stats = {
                'pending': VerificationTask.objects.filter(status='pending').count(),
                'in_progress': VerificationTask.objects.filter(status='in_progress').count(),
                'completed_today': VerificationTask.objects.filter(
                    status='completed',
                    completed_at__date=timezone.now().date()
                ).count(),
                'overdue': VerificationTask.objects.filter(
                    status='in_progress',
                    assigned_at__lt=timezone.now() - timedelta(days=2)
                ).count(),
            }
            
            # Tasks by type
            stats['by_type'] = {}
            for task_type, _ in VerificationTask.TASK_TYPE_CHOICES:
                stats['by_type'][task_type] = VerificationTask.objects.filter(
                    verification_type=task_type,
                    status='pending'
                ).count()
            
            return stats

