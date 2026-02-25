# listings/views_admin.py
import json
import logging
import traceback
from pathlib import Path
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User
from django.db.models import Q
from .models import *
from .verification_service import VerificationService
from .utils import log_audit

# Add this logger definition
logger = logging.getLogger(__name__)

# Add this to views_admin.py - somewhere after your other imports

@staff_member_required
def trigger_ardhisasa(request, plot_id):
    """Manually trigger Ardhisasa verification for a plot (runs directly, no Celery)"""
    from django.http import JsonResponse
    from django.contrib.contenttypes.models import ContentType
    from .models import Plot, VerificationStatus
    from .services.ardhisasa_integration import ArdhisasaService
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    
    try:
        plot = Plot.objects.get(id=plot_id)
    except Plot.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Plot not found'}, status=404)
    
    # Get verification status
    content_type = ContentType.objects.get_for_model(Plot)
    verification, created = VerificationStatus.objects.get_or_create(
        content_type=content_type,
        object_id=plot.id
    )
    
    # Update stage to start API verification
    verification.update_stage('api_verification_started')
    
    # Run directly (no Celery)
    service = ArdhisasaService(use_mock=True)
    result = service.verify_plot_title(plot)
    
    if result.get('success'):
        verification.update_stage('title_search_completed', {
            'search_reference': result.get('search_data', {}).get('search_reference'),
            'title_number': result.get('search_data', {}).get('title_number'),
            'parcel_number': result.get('search_data', {}).get('parcel_number'),
            'owner_name': result.get('search_data', {}).get('owner_name')
        })
        return JsonResponse({
            'success': True, 
            'message': 'Ardhisasa verification completed',
            'data': result.get('search_data')
        })
    else:
        return JsonResponse({
            'success': False, 
            'error': result.get('error', 'Unknown error occurred')
        })
        
                
# For extension officer views, create a custom decorator
from django.core.exceptions import PermissionDenied

def extension_officer_required(view_func):
    """Decorator to require extension officer status"""
    def _wrapped_view(request, *args, **kwargs):
        if not hasattr(request.user, 'extension_officer'):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@staff_member_required
def verification_dashboard(request):
    """Main verification dashboard showing stats and queues"""
    
    # Get content type for Plot
    plot_content_type = ContentType.objects.get_for_model(Plot)
    
    # Get counts for dashboard using the verification relation
    stats = {
        'pending_review': VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage='document_uploaded'
        ).count(),
        
        'in_progress': VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage__in=[
                'api_verification_started', 
                'title_search_completed',
                'admin_review'
            ]
        ).count(),
        
        'approved_today': VerificationStatus.objects.filter(
            content_type=plot_content_type,
            approved_at__date=timezone.now().date()
        ).count(),
        
        'total_verified': VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage='approved'
        ).count(),
    }
    
    # Get recent plots pending review
    # First get the verification statuses, then get the plots
    pending_verifications = VerificationStatus.objects.filter(
        content_type=plot_content_type,
        current_stage='document_uploaded'
    ).select_related('content_type').order_by('-created_at')[:10]
    
    # Extract the plot IDs and fetch the plots
    plot_ids = [v.object_id for v in pending_verifications]
    pending_plots = Plot.objects.filter(id__in=plot_ids).select_related(
        'landowner__user', 
        'agent__user'
    )
    
    context = {
        'stats': stats,
        'pending_plots': pending_plots,
        'page_title': 'Verification Dashboard'
    }
    
    return render(request, 'listings/admin/verification_dashboard.html', context)


@staff_member_required
def verification_queue(request):
    """Full queue of plots pending verification"""
    
    # Get filter from request
    filter_type = request.GET.get('filter', 'all')
    
    # Get content type for Plot
    plot_content_type = ContentType.objects.get_for_model(Plot)
    
    # Base queryset for verification statuses
    verifications = VerificationStatus.objects.filter(
        content_type=plot_content_type
    ).select_related('content_type')
    
    # Apply filters
    if filter_type == 'pending':
        verifications = verifications.filter(current_stage='document_uploaded')
    elif filter_type == 'in_progress':
        verifications = verifications.filter(current_stage__in=[
            'api_verification_started',
            'title_search_completed',
            'admin_review'
        ])
    elif filter_type == 'approved':
        verifications = verifications.filter(current_stage='approved')
    elif filter_type == 'rejected':
        verifications = verifications.filter(current_stage='rejected')
    
    # Order by most recent first
    verifications = verifications.order_by('-created_at')
    
    # Get the plot IDs and fetch plots
    plot_ids = [v.object_id for v in verifications]
    plots = Plot.objects.filter(id__in=plot_ids).select_related(
        'landowner__user',
        'agent__user'
    )
    
    # Create a dictionary for quick lookup of verification status
    verification_map = {v.object_id: v for v in verifications}
    
    # Attach verification status to each plot
    for plot in plots:
        plot.verification_status = verification_map.get(plot.id)
    
    context = {
        'plots': plots,
        'current_filter': filter_type,
        'page_title': 'Verification Queue'
    }
    
    return render(request, 'listings/admin/verification_queue.html', context)


@staff_member_required
def system_construction_journal(request):
    """Admin-only system construction journal page."""
    data_file = Path(settings.BASE_DIR) / "listings" / "data" / "system_construction_journal.json"
    entries = []
    if data_file.exists():
        try:
            entries = json.loads(data_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            messages.error(request, "Journal data file is not valid JSON.")
    else:
        messages.warning(request, "Journal data file is missing. Create it to display entries.")

    context = {
        "page_title": "System Construction Journal",
        "entries": entries,
        "data_file": str(data_file),
    }
    return render(request, "listings/admin/system_construction_journal.html", context)


@staff_member_required
def review_plot(request, plot_id):
    """Review a single plot"""
    
    plot = get_object_or_404(
        Plot.objects.select_related(
            'landowner__user',
            'agent__user'
        ),
        id=plot_id
    )
    
    # Get or create verification status
    plot_content_type = ContentType.objects.get_for_model(Plot)
    verification, created = VerificationStatus.objects.get_or_create(
        content_type=plot_content_type,
        object_id=plot.id,
        defaults={
            'current_stage': 'document_uploaded',
            'document_uploaded_at': timezone.now(),
            'stage_details': {
                'created_by': 'system',
                'created_at': timezone.now().isoformat(),
                'plot_title': plot.title
            }
        }
    )
    
    # Get verification history
    verification_logs = VerificationLog.objects.filter(
        plot=plot
    ).select_related('verified_by').order_by('-created_at')[:20]
    
    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        
        if action == 'approve':
            # Update verification status
            verification.current_stage = 'approved'
            verification.approved_at = timezone.now()
            verification.stage_details['approval_notes'] = notes
            verification.stage_details['approved_by'] = request.user.username
            verification.save()
            
            # Create log entry
            VerificationLog.objects.create(
                plot=plot,
                verified_by=request.user,
                verification_type='approval',
                comment=f"Plot approved. Notes: {notes}"
            )
            
            messages.success(request, f"Plot '{plot.title}' has been approved!")
            return redirect('listings:verification_queue')
            
        elif action == 'reject':
            verification.current_stage = 'rejected'
            verification.rejected_at = timezone.now()
            verification.stage_details['rejection_reason'] = notes
            verification.stage_details['rejected_by'] = request.user.username
            verification.save()
            
            VerificationLog.objects.create(
                plot=plot,
                verified_by=request.user,
                verification_type='rejection',
                comment=f"Plot rejected. Reason: {notes}"
            )
            
            messages.warning(request, f"Plot '{plot.title}' has been rejected.")
            return redirect('listings:verification_queue')
            
        elif action == 'request_changes':
            verification.current_stage = 'document_uploaded'  # Back to pending
            verification.stage_details['change_requests'] = notes
            verification.stage_details['requested_by'] = request.user.username
            verification.save()
            
            VerificationLog.objects.create(
                plot=plot,
                verified_by=request.user,
                verification_type='change_request',
                comment=f"Changes requested: {notes}"
            )
            
            messages.info(request, f"Changes requested for '{plot.title}'")
            return redirect('listings:verification_queue')
    
    context = {
        'plot': plot,
        'verification': verification,
        'verification_logs': verification_logs,
        'page_title': f'Review: {plot.title}'
    }
    
    return render(request, 'listings/admin/review_plot.html', context)


@staff_member_required
def plot_verification_history(request, plot_id):
    """View full verification history for a plot"""
    
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Get logs with proper null handling
    logs = VerificationLog.objects.filter(
        plot=plot
    ).select_related('verified_by').order_by('-created_at')
    
    # Get verification status
    content_type = ContentType.objects.get_for_model(Plot)
    verification = VerificationStatus.objects.filter(
        content_type=content_type,
        object_id=plot.id
    ).first()
    
    # Get task statistics
    total_tasks = VerificationTask.objects.filter(plot=plot).count()
    completed_tasks = VerificationTask.objects.filter(plot=plot, status='completed').count()
    pending_tasks = VerificationTask.objects.filter(plot=plot, status__in=['pending', 'in_progress']).count()
    
    context = {
        'plot': plot,
        'verification': verification,
        'logs': logs,
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'pending_tasks': pending_tasks,
        'page_title': f'Verification History: {plot.title}'
    }
    
    return render(request, 'listings/admin/verification_history.html', context)


# listings/views_admin.py - Add these new views

from django.contrib.auth.models import User
from .verification_service import VerificationService
from django.http import JsonResponse

@staff_member_required
def task_assignment(request):
    """View for managing task assignments"""
    
    # Get all pending tasks
    pending_tasks = VerificationTask.objects.filter(
        status='pending'
    ).select_related('plot', 'plot__agent__user', 'plot__landowner__user').order_by('assigned_at')
    
    # Get in-progress tasks
    in_progress_tasks = VerificationTask.objects.filter(
        status='in_progress'
    ).select_related('plot', 'assigned_to').order_by('-assigned_at')
    
    # Get EXTENSION OFFICERS instead of all staff
    from .models import ExtensionOfficer
    extension_officers = ExtensionOfficer.objects.filter(
        is_active=True,
        verified=True
    ).select_related('user')
    
    # Get workload statistics
    workload = []
    for officer in extension_officers:
        pending = VerificationTask.objects.filter(
            assigned_to=officer.user,
            status='in_progress'
        ).count()
        
        completed_today = VerificationTask.objects.filter(
            assigned_to=officer.user,
            status='completed',
            completed_at__date=timezone.now().date()
        ).count()
        
        total_assigned = VerificationTask.objects.filter(
            assigned_to=officer.user
        ).count()
        
        workload.append({
            'user': officer.user,
            'officer': officer,
            'pending': pending,
            'completed_today': completed_today,
            'total_assigned': total_assigned,
            'station': officer.station,
            'assigned_counties': officer.assigned_counties
        })
    
    task_stats = VerificationService.get_task_statistics()
    
    context = {
        'pending_tasks': pending_tasks,
        'in_progress_tasks': in_progress_tasks,
        'extension_officers': extension_officers,  # Pass only extension officers
        'workload': workload,
        'task_stats': task_stats,
        'page_title': 'Task Assignment'
    }
    
    return render(request, 'listings/admin/task_assignment.html', context)

@staff_member_required
def ajax_assign_task(request):
    """AJAX endpoint for task assignment"""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            task_id = data.get('task_id')
            user_id = data.get('user_id')
            
            # Now logger is defined
            logger.info(f"AJAX assign task - Task ID: {task_id}, User ID: {user_id}, Request by: {request.user.username}")
            
            if not task_id or not user_id:
                return JsonResponse({
                    'success': False,
                    'message': 'Task ID and User ID are required'
                }, status=400)
            
            try:
                assigned_to = User.objects.get(id=user_id, is_staff=True)
            except User.DoesNotExist:
                logger.error(f"User {user_id} not found or not staff")
                return JsonResponse({
                    'success': False,
                    'message': 'Selected staff member not found'
                }, status=404)
            
            # Assign the task
            from .verification_service import VerificationService
            task = VerificationService.assign_task(task_id, assigned_to, request.user)
            
            if task:
                logger.info(f"Task {task_id} assigned successfully to {assigned_to.username}")
                assignee_name = assigned_to.get_full_name() or assigned_to.username
                return JsonResponse({
                    'success': True,
                    'message': f"Task assigned to {assignee_name}"
                })
            else:
                logger.error(f"Task {task_id} not found or could not be assigned")
                return JsonResponse({
                    'success': False,
                    'message': 'Task not found or could not be assigned'
                }, status=404)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return JsonResponse({
                'success': False,
                'message': 'Invalid request format'
            }, status=400)
        except Exception as e:
            logger.error(f"Error in ajax_assign_task: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
    
    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

@staff_member_required
def my_tasks(request):
    """View for staff to see their assigned tasks"""
    
    my_tasks = VerificationTask.objects.filter(
        assigned_to=request.user,
        status='in_progress'
    ).select_related('plot').order_by('assigned_at')
    
    completed_tasks = VerificationTask.objects.filter(
        assigned_to=request.user,
        status='completed'
    ).select_related('plot').order_by('-completed_at')[:10]
    
    context = {
        'my_tasks': my_tasks,
        'completed_tasks': completed_tasks,
        'page_title': 'My Tasks'
    }
    
    return render(request, 'listings/admin/my_tasks.html', context)


@staff_member_required
def complete_task_view(request, task_id):
    """View for completing a task"""
    
    task = get_object_or_404(VerificationTask, id=task_id, assigned_to=request.user)
    
    if request.method == 'POST':
        notes = request.POST.get('notes', '')
        approved = request.POST.get('approved') == 'true'
        
        task = VerificationService.complete_task(task_id, request.user, notes, approved)
        
        if approved:
            messages.success(request, f"Task completed and approved!")
        else:
            messages.warning(request, f"Task completed with notes.")
        
        return redirect('listings:my_tasks')
    
    context = {
        'task': task,
        'plot': task.plot,
        'page_title': f'Complete Task: {task.get_verification_type_display()}'
    }
    
    return render(request, 'listings/admin/complete_task.html', context)

from .notification_service import NotificationService

@staff_member_required
def get_notifications(request):
    """AJAX endpoint to get user notifications"""
    notifications = NotificationService.get_user_notifications(request.user, limit=10)
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    
    data = {
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'type': n.notification_type,
                'time': n.created_at.isoformat(),
                'is_read': n.is_read,
                'plot_id': n.plot.id if n.plot else None,
            }
            for n in notifications
        ],
        'unread_count': unread_count
    }
    return JsonResponse(data)

@staff_member_required
def mark_notification_read(request, notification_id):
    """Mark a notification as read"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()
    return JsonResponse({'success': True})

@staff_member_required
def mark_all_notifications_read(request):
    """Mark all notifications as read"""
    count = NotificationService.mark_all_as_read(request.user)
    return JsonResponse({'success': True, 'count': count})

from .analytics_service import AnalyticsService

@staff_member_required
def analytics_dashboard(request):
    """Main analytics dashboard"""
    
    # Get date range from request
    days = int(request.GET.get('days', 30))
    
    # Get analytics data
    overview = AnalyticsService.get_verification_overview(days)
    officer_performance = AnalyticsService.get_officer_performance(days)
    timeline = AnalyticsService.get_verification_timeline(days)
    task_breakdown = AnalyticsService.get_task_breakdown()
    county_stats = AnalyticsService.get_county_statistics()
    system_health = AnalyticsService.get_system_health()
    
    # Convert timeline to JSON for Chart.js
    import json
    timeline_json = json.dumps(timeline)
    
    context = {
        'overview': overview,
        'officer_performance': officer_performance,
        'timeline': timeline,
        'timeline_json': timeline_json,
        'task_breakdown': task_breakdown,
        'county_stats': county_stats,
        'system_health': system_health,
        'days': days,
        'page_title': 'Analytics Dashboard'
    }
    
    return render(request, 'listings/admin/analytics_dashboard.html', context)

@staff_member_required
def export_report(request):
    """Export verification report as CSV"""
    import csv
    from django.http import HttpResponse
    
    report_type = request.GET.get('type', 'verification')
    days = int(request.GET.get('days', 30))
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="agriplot_{report_type}_report.csv"'
    
    writer = csv.writer(response)
    
    if report_type == 'verification':
        writer.writerow(['Date', 'Plots Submitted', 'Plots Verified', 'Verification Rate'])
        timeline = AnalyticsService.get_verification_timeline(days)
        for day in timeline:
            rate = round((day['verified'] / day['submitted'] * 100), 2) if day['submitted'] > 0 else 0
            writer.writerow([day['date'], day['submitted'], day['verified'], f"{rate}%"])
    
    elif report_type == 'officers':
        writer.writerow(['Officer', 'Station', 'Tasks Completed', 'Avg Rating', 'Avg Response (hrs)', 'Utilization %'])
        performance = AnalyticsService.get_officer_performance(days)
        for p in performance:
            writer.writerow([
                p['officer'].user.get_full_name() or p['officer'].user.username,
                p['officer'].station,
                p['tasks_completed'],
                p['avg_rating'],
                p['avg_response_hours'],
                p['utilization']
            ])
    
    elif report_type == 'counties':
        writer.writerow(['County', 'Total Plots', 'Verified', 'Verification Rate', 'Assigned Officers'])
        for stat in AnalyticsService.get_county_statistics():
            writer.writerow([
                stat['county'],
                stat['total_plots'],
                stat['verified_plots'],
                f"{stat['verification_rate']}%",
                stat['assigned_officers']
            ])
    
    return response
