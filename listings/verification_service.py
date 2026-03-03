# listings/verification_service.py

from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.db.utils import NotSupportedError
from .models import *
from .notification_service import *
from .services.sms_service import TextSMSService
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
        # Extension/Surveyor tasks will be created after API verification completes.
        
        # Log the creation
        VerificationLog.objects.create(
            plot=plot,
            verification_type='system',
            comment=f"Created verification tasks: {', '.join(tasks_created)}. Ardhisasa verification started."
        )
        
        return tasks_created
    

    @staticmethod
    def assign_task(task_id, assigned_to_user, assigned_by):
        task = VerificationTask.objects.get(id=task_id)
        task.assigned_to = assigned_to_user
        task.status = 'in_progress'
        task.assigned_at = timezone.now()
        task.confirm_by = timezone.now() + timezone.timedelta(hours=12)
        task.deadline_at = timezone.now() + timezone.timedelta(days=3)
        task.save()

        VerificationLog.objects.create(
            plot=task.plot,
            verified_by=assigned_by,
            verification_type='assignment',
            comment=f"{task.get_verification_type_display()} assigned to {assigned_to_user.get_full_name() or assigned_to_user.username}"
        )

        try:
            NotificationService.notify_task_assigned(task, assigned_by)
        except Exception as e:
            logger.error(f"Task assignment notification failed: {e}")
        
        # Send SMS notification
        try:
            if assigned_to_user.profile and assigned_to_user.profile.phone:
                sms = TextSMSService()
                sms.send_task_assigned(
                    phone_number=assigned_to_user.profile.phone,
                    officer_name=assigned_to_user.get_full_name() or assigned_to_user.username,
                    plot_title=task.plot.title
                )
        except Exception as e:
            logger.error(f"SMS failed: {e}")
        
        return task
        
    @staticmethod
    def assign_extension_task(task_id, assigned_by=None):
        """Auto-assign extension task to available officer"""
        from .models import ExtensionOfficer
        
        task = VerificationTask.objects.get(id=task_id)
        plot = task.plot

        if not plot.county:
            logger.warning(f"Extension task {task_id} not assigned: plot {plot.id} missing county")
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
            logger.info(f"Assigning extension task {task_id} for plot {plot.id} to {best_officer.username}")
            return VerificationService.assign_task(task_id, best_officer, effective_assigner)
        
        logger.warning(f"No available extension officers for plot {plot.id} (county={plot.county})")
        try:
            NotificationService.notify_admin_no_officer(plot, 'Extension Officer', plot.county)
        except Exception:
            pass
        return None

    @staticmethod
    def assign_surveyor_task(task_id, assigned_by=None):
        """Auto-assign surveyor task to available land surveyor"""
        from .models import LandSurveyor

        task = VerificationTask.objects.get(id=task_id)
        plot = task.plot

        if not plot.county:
            logger.warning(f"Surveyor task {task_id} not assigned: plot {plot.id} missing county")
            return None

        available_surveyors_qs = LandSurveyor.objects.filter(
            is_active=True,
            assigned_counties__contains=[plot.county],
            verified=True
        )
        try:
            available_surveyors = list(available_surveyors_qs)
        except NotSupportedError:
            available_surveyors = [
                surveyor for surveyor in LandSurveyor.objects.filter(
                    is_active=True,
                    verified=True
                )
                if plot.county in (surveyor.assigned_counties or [])
            ]

        best_surveyor = None
        lowest_workload = float('inf')

        for surveyor in available_surveyors:
            workload = VerificationTask.objects.filter(
                assigned_to=surveyor.user,
                status='in_progress'
            ).count()

            if workload < surveyor.max_daily_tasks and workload < lowest_workload:
                lowest_workload = workload
                best_surveyor = surveyor.user

        if best_surveyor:
            effective_assigner = assigned_by or best_surveyor
            logger.info(f"Assigning surveyor task {task_id} for plot {plot.id} to {best_surveyor.username}")
            return VerificationService.assign_task(task_id, best_surveyor, effective_assigner)

        logger.warning(f"No available surveyors for plot {plot.id} (county={plot.county})")
        try:
            NotificationService.notify_admin_no_officer(plot, 'Land Surveyor', plot.county)
        except Exception:
            pass
        return None

    @staticmethod
    def after_api_verification(plot, assigned_by=None):
        """
        After API verification succeeds, move to document review.
        Surveyor task is created only after document review is approved.
        """
        logger.info(f"Post-API assignment start for plot {plot.id} (land_type={plot.land_type})")
        doc_task, _ = VerificationTask.objects.get_or_create(
            plot=plot,
            verification_type='document_review',
            defaults={'status': 'pending'}
        )
        VerificationLog.objects.create(
            plot=plot,
            verified_by=assigned_by,
            verification_type='task_pending',
            comment="Document review pending after API verification."
        )
        return doc_task
    
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
    def required_task_types(plot):
        """Return required verification task types for a plot."""
        required = ['document_review', 'surveyor_inspection']
        if plot.land_type == 'agricultural':
            required.append('extension_review')
        return required

    @staticmethod
    def has_required_reports(plot):
        """Ensure required verification reports exist for the plot."""
        missing = []
        if plot.land_type == 'agricultural':
            if not ExtensionReport.objects.filter(plot=plot).exists():
                missing.append('extension_report')
        if not SurveyorReport.objects.filter(plot=plot).exists():
            missing.append('surveyor_report')
        return missing

    @staticmethod
    def complete_task(task_id, completed_by, notes="", approved=None):
        task = VerificationTask.objects.get(id=task_id)
        task.status = 'completed'
        task.completed_at = timezone.now()
        task.notes = notes
        task.approved = approved
        task.save()

        VerificationLog.objects.create(
            plot=task.plot,
            verified_by=completed_by,
            verification_type='task_completed',
            comment=f"{task.get_verification_type_display()} completed. Approved={approved}. Notes: {notes}"
        )

        try:
            NotificationService.notify_task_completed(task, completed_by)
        except Exception as e:
            logger.error(f"Task completion notification failed: {e}")

        # Handoff logic based on task type and outcome
        if task.verification_type == 'surveyor_inspection':
            if approved:
                if task.plot.land_type == 'agricultural':
                    ext_task, created = VerificationTask.objects.get_or_create(
                        plot=task.plot,
                        verification_type='extension_review',
                        defaults={'status': 'pending'}
                    )
                    if created:
                        logger.info(f"Created extension_review task for plot {task.plot.id} after surveyor approval")
                    # Always attempt assignment if task is pending/unassigned
                    if ext_task.status == 'pending' or ext_task.assigned_to is None:
                        assigned = VerificationService.assign_extension_task(
                            ext_task.id,
                            assigned_by=completed_by
                        )
                        if not assigned:
                            VerificationLog.objects.create(
                                plot=task.plot,
                                verified_by=completed_by,
                                verification_type='assignment_pending',
                                comment=(
                                    "Extension review task pending assignment. "
                                    "No available officer or missing county."
                                )
                            )
                # Non-agricultural goes to admin review later
            else:
                content_type = ContentType.objects.get_for_model(Plot)
                verification = VerificationStatus.objects.filter(
                    content_type=content_type,
                    object_id=task.plot.id
                ).first()
                if verification:
                    verification.update_stage('rejected', {
                        'rejection_reason': notes or 'Surveyor rejected the plot',
                        'completed_by': completed_by.username
                    })
        elif task.verification_type == 'document_review':
            if approved:
                survey_task, created = VerificationTask.objects.get_or_create(
                    plot=task.plot,
                    verification_type='surveyor_inspection',
                    defaults={'status': 'pending'}
                )
                if created:
                    logger.info(f"Created surveyor_inspection task for plot {task.plot.id} after document review approval")
                if survey_task.status == 'pending' or survey_task.assigned_to is None:
                    VerificationService.assign_surveyor_task(survey_task.id, assigned_by=completed_by)
            else:
                content_type = ContentType.objects.get_for_model(Plot)
                verification = VerificationStatus.objects.filter(
                    content_type=content_type,
                    object_id=task.plot.id
                ).first()
                if verification:
                    verification.update_stage('rejected', {
                        'rejection_reason': notes or 'Document review rejected the plot',
                        'completed_by': completed_by.username
                    })
        elif task.verification_type == 'extension_review':
            if not approved:
                # Send back to surveyor for re-check
                survey_task, created = VerificationTask.objects.get_or_create(
                    plot=task.plot,
                    verification_type='surveyor_inspection',
                    defaults={'status': 'pending'}
                )
                if created:
                    VerificationService.assign_surveyor_task(survey_task.id, assigned_by=completed_by)
        
        # Check if all tasks are done
        all_completed = VerificationService.check_plot_completion(task.plot)
        
        if all_completed:
            # Update VerificationStatus
            content_type = ContentType.objects.get_for_model(Plot)
            verification = VerificationStatus.objects.get(
                content_type=content_type,
                object_id=task.plot.id
            )

            # Ensure required tasks exist and required reports are submitted
            required_types = set(VerificationService.required_task_types(task.plot))
            existing_types = set(
                VerificationTask.objects.filter(plot=task.plot).values_list('verification_type', flat=True)
            )
            missing_types = list(required_types - existing_types)
            missing_reports = VerificationService.has_required_reports(task.plot)
            
            # Check if any tasks were rejected
            has_rejections = VerificationTask.objects.filter(
                plot=task.plot,
                approved=False
            ).exclude(verification_type='extension_review').exists()
            
            if has_rejections:
                verification.update_stage('rejected', {
                    'rejection_reason': 'One or more verification tasks were rejected',
                    'completed_by': completed_by.username
                })
            elif missing_types or missing_reports:
                verification.update_stage('admin_review', {
                    'reason': 'Required verification reports or tasks missing',
                    'missing_task_types': missing_types,
                    'missing_reports': missing_reports,
                    'completed_by': completed_by.username
                })
                VerificationLog.objects.create(
                    plot=task.plot,
                    verification_type='admin_review',
                    comment=f"Approval blocked. Missing tasks: {missing_types}, reports: {missing_reports}"
                )
            else:
                # All verification tasks complete; send to admin for final approval
                verification.update_stage('admin_review', {
                    'completed_by': completed_by.username,
                    'completed_at': timezone.now().isoformat()
                })
                VerificationLog.objects.create(
                    plot=task.plot,
                    verification_type='admin_review',
                    comment="All verification tasks completed. Awaiting admin approval."
                )
                
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
            # All tasks completed - move to admin review (final approval step)
            content_type = ContentType.objects.get_for_model(Plot)
            verification = VerificationStatus.objects.filter(
                content_type=content_type,
                object_id=plot.id
            ).first()
            
            if verification:
                verification.current_stage = 'admin_review'
                verification.admin_review_at = timezone.now()
                verification.save()
                
                VerificationLog.objects.create(
                    plot=plot,
                    verification_type='approval',
                    comment="All verification tasks completed. Awaiting admin approval."
                )
                
                logger.info(f"Plot {plot.id} verification complete; awaiting admin approval")
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
                verification_data = result.get('verification_data', {})
                search_result = verification_data.get('search_result', {})
                verification.update_stage('title_search_completed', {
                    'search_reference': search_result.get('search_reference'),
                    'title_number': verification_data.get('title_number') or search_result.get('title_number'),
                    'parcel_number': search_result.get('parcel_number'),
                    'owner_name': search_result.get('owner_name'),
                    'search_result': search_result,
                    'ownership_result': verification_data.get('ownership_result'),
                    'encumbrance_result': verification_data.get('encumbrance_result'),
                    'decision': verification_data.get('decision')
                })

            # After API verification, assign the next role in the chain
            VerificationService.after_api_verification(plot, assigned_by=None)
        else:
            content_type = ContentType.objects.get_for_model(Plot)
            verification = VerificationStatus.objects.filter(
                content_type=content_type,
                object_id=plot.id
            ).first()
            if verification:
                verification.stage_details['ardhisasa_error'] = result.get('error')
                verification.stage_details['ardhisasa_failure'] = result.get('decision')
                VerificationStatus.objects.filter(pk=verification.pk).update(
                    current_stage='rejected',
                    rejected_at=timezone.now(),
                    stage_details=verification.stage_details
                )

        return result
