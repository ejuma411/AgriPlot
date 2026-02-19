# listings/views_admin.py

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from django.contrib.contenttypes.models import ContentType
from .models import *

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
    
    # Get all pending tasks - use assigned_at instead of created_at
    pending_tasks = VerificationTask.objects.filter(
        status='pending'
    ).select_related('plot', 'plot__agent__user', 'plot__landowner__user').order_by('assigned_at')
    
    # Get in-progress tasks
    in_progress_tasks = VerificationTask.objects.filter(
        status='in_progress'
    ).select_related('plot', 'assigned_to').order_by('-assigned_at')
    
    # Get staff users for assignment dropdown
    staff_users = User.objects.filter(is_staff=True, is_active=True)
    
    # Get workload statistics
    workload = VerificationService.get_staff_workload()
    task_stats = VerificationService.get_task_statistics()
    
    context = {
        'pending_tasks': pending_tasks,
        'in_progress_tasks': in_progress_tasks,
        'staff_users': staff_users,
        'workload': workload,
        'task_stats': task_stats,
        'page_title': 'Task Assignment'
    }
    
    return render(request, 'listings/admin/task_assignment.html', context)

@staff_member_required
def ajax_assign_task(request):
    """AJAX endpoint for task assignment"""
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        task_id = data.get('task_id')
        user_id = data.get('user_id')
        
        try:
            assigned_to = User.objects.get(id=user_id)
            task = VerificationService.assign_task(task_id, assigned_to, request.user)
            
            if task:
                return JsonResponse({
                    'success': True,
                    'message': f'Task assigned to {assigned_to.username}'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Task not found'
                }, status=404)
                
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'User not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)


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