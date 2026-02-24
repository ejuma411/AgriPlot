# listings/verification_service.py

from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.db.utils import NotSupportedError
from .models import *
from .notification_service import *
import logging

logger = logging.getLogger(__name__)

class VerificationService:
    """Service layer for verification business logic"""
    

    # In verification_service.py, add or update:

    from .services.ardhisasa_integration import ArdhisasaService

    @staticmethod
    def create_verification_tasks(plot, initiated_by=None):
        """Create all necessary verification tasks when a plot is submitted"""
        from .models import VerificationTask, VerificationLog, VerificationStatus
        from django.contrib.contenttypes.models import ContentType
        
        tasks_created = []
        
        # Task 1: Document Review (always required)
        doc_task, created = VerificationTask.objects.get_or_create(
            plot=plot,
            verification_type='document_review',
            defaults={'status': 'pending'}
        )
        if created:
            tasks_created.append('document_review')
        
        # Task 2: Extension Officer Review (for agricultural land)
        if plot.land_type == 'agricultural':
            ext_task, created = VerificationTask.objects.get_or_create(
                plot=plot,
                verification_type='extension_review',
                defaults={'status': 'pending'}
            )
            if created:
                tasks_created.append('extension_review')
                # Auto-assign to available extension officer
                VerificationService.assign_extension_task(ext_task.id, assigned_by=initiated_by)
        
        # Task 3: Surveyor Inspection (for large plots)
        if plot.area > 50:
            survey_task, created = VerificationTask.objects.get_or_create(
                plot=plot,
                verification_type='surveyor_inspection',
                defaults={'status': 'pending'}
            )
            if created:
                tasks_created.append('surveyor_inspection')
        
        # AUTOMATICALLY START ARDHISASA VERIFICATION
        content_type = ContentType.objects.get_for_model(Plot)
        verification = VerificationStatus.objects.filter(
            content_type=content_type,
            object_id=plot.id
        ).first()
        
        if verification:
            # Update stage to start API verification
            verification.update_stage('api_verification_started')
            logger.info(f"🚀 Automatically started Ardhisasa verification for plot {plot.id}")
        
        # Log the creation
        VerificationLog.objects.create(
            plot=plot,
            verification_type='system',
            comment=f"Created verification tasks: {', '.join(tasks_created)}. Ardhisasa verification started."
        )
        
        return tasks_created
    

    @staticmethod
    def assign_task(task_id, assigned_to_user, assigned_by=None):
        """
        Assign a verification task to a specific staff member
        """
        try:
            task = VerificationTask.objects.get(id=task_id)
            task.assigned_to = assigned_to_user
            task.status = 'in_progress'
            task.assigned_at = timezone.now()
            task.save()
            
            # Send notification if we have an assigner context.
            if assigned_by is not None:
                try:
                    from .notification_service import NotificationService
                    NotificationService.notify_task_assigned(task, assigned_by)
                except Exception as exc:
                    logger.warning(f"Task assignment notification skipped: {exc}")
            
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
    def assign_extension_task(task_id, assigned_by=None):
        """Auto-assign extension task to available officer"""
        from .models import ExtensionOfficer
        
        task = VerificationTask.objects.get(id=task_id)
        plot = task.plot

        if not plot.county:
            return None
        
        # Find available extension officers for this county.
        available_officers_qs = ExtensionOfficer.objects.filter(
            is_active=True,
            assigned_counties__contains=[plot.county],
            verified=True
        )
        try:
            available_officers = list(available_officers_qs)
        except NotSupportedError:
            # SQLite does not support JSON contains lookups in this form.
            available_officers = [
                officer for officer in ExtensionOfficer.objects.filter(
                    is_active=True,
                    verified=True
                )
                if plot.county in (officer.assigned_counties or [])
            ]
        
        # Find officer with lowest workload
        best_officer = None
        lowest_workload = float('inf')
        
        for officer in available_officers:
            workload = VerificationTask.objects.filter(
                assigned_to=officer.user,
                status='in_progress'
            ).count()
            
            if workload < officer.max_daily_tasks and workload < lowest_workload:
                lowest_workload = workload
                best_officer = officer.user
        
        if best_officer:
            effective_assigner = assigned_by or best_officer
            return VerificationService.assign_task(task_id, best_officer, effective_assigner)
        
        return None
    
    @staticmethod
    def check_plot_completion(plot):
        """
        Return True when a plot has no pending/in-progress verification tasks.
        """
        return not VerificationTask.objects.filter(
            plot=plot,
            status__in=['pending', 'in_progress']
        ).exists()

    @staticmethod
    def complete_task(task_id, completed_by, notes="", approved=None):
        task = VerificationTask.objects.get(id=task_id)
        task.status = 'completed'
        task.completed_at = timezone.now()
        task.notes = notes
        task.approved = approved
        task.save()
        
        # Check if all tasks are done
        all_completed = VerificationService.check_plot_completion(task.plot)
        
        if all_completed:
            # Update VerificationStatus
            content_type = ContentType.objects.get_for_model(Plot)
            verification = VerificationStatus.objects.get(
                content_type=content_type,
                object_id=task.plot.id
            )
            
            # Check if any tasks were rejected
            has_rejections = VerificationTask.objects.filter(
                plot=task.plot,
                approved=False
            ).exists()
            
            if has_rejections:
                verification.update_stage('rejected', {
                    'rejection_reason': 'One or more verification tasks were rejected',
                    'completed_by': completed_by.username
                })
            else:
                verification.update_stage('approved', {
                    'approved_by': completed_by.username,
                    'completed_at': timezone.now().isoformat()
                })
                
                # Plot is now verified! 🎉
                # You could add a 'is_verified' field to Plot model or just use verification status
        
        return task
    
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
            verification = VerificationStatus.objects.filter(
                content_type=content_type,
                object_id=plot.id
            ).first()
            
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
    
    @staticmethod
    def get_plot_verification_status(plot):
        """
        Get detailed verification status for a specific plot
        """
        content_type = ContentType.objects.get_for_model(Plot)
        verification = VerificationStatus.objects.filter(
            content_type=content_type,
            object_id=plot.id
        ).first()
        
        tasks = VerificationTask.objects.filter(plot=plot)
        
        return {
            'verification': verification,
            'total_tasks': tasks.count(),
            'pending_tasks': tasks.filter(status='pending').count(),
            'in_progress_tasks': tasks.filter(status='in_progress').count(),
            'completed_tasks': tasks.filter(status='completed').count(),
            'tasks_by_type': {
                'document_review': tasks.filter(verification_type='document_review').first(),
                'extension_review': tasks.filter(verification_type='extension_review').first(),
                'surveyor_inspection': tasks.filter(verification_type='surveyor_inspection').first(),
            }
        }

    @staticmethod
    def initiate_ardhisasa_verification(plot_id):
        """Start Ardhisasa verification for a plot."""
        from .services.ardhisasa_integration import ArdhisasaService

        plot = Plot.objects.get(id=plot_id)
        service = ArdhisasaService(use_mock=True)
        result = service.verify_plot_title(plot)

        if result.get('success'):
            content_type = ContentType.objects.get_for_model(Plot)
            verification = VerificationStatus.objects.filter(
                content_type=content_type,
                object_id=plot.id
            ).first()
            if verification:
                verification.update_stage('title_search_completed')

        return result
