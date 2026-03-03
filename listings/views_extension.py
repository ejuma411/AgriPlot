# listings/views_extension.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from .models import ExtensionOfficer, LandSurveyor, VerificationTask, Plot, ExtensionReport, SurveyorReport
from .forms import ExtensionReportForm, SurveyorReportForm
from .verification_service import VerificationService
import logging

logger = logging.getLogger(__name__)

@login_required
def extension_dashboard(request):
    """Dashboard for extension officers"""
    try:
        officer = request.user.extension_officer
        if not officer.verified or not officer.is_active:
            messages.error(request, "Your extension officer role is not active yet.")
            return redirect('listings:profile_management')
    except ExtensionOfficer.DoesNotExist:
        if request.user.is_superuser:
            officer = None
        else:
            messages.error(request, "You don't have an extension officer profile.")
            return redirect('listings:home')
    
    # Get assigned tasks
    assigned_tasks = VerificationTask.objects.filter(
        status='in_progress',
        verification_type='extension_review',
        assigned_to=request.user
    ).select_related('plot')
    
    # Get completed tasks
    completed_tasks = VerificationTask.objects.filter(
        status='completed',
        verification_type='extension_review',
        assigned_to=request.user
    ).select_related('plot').order_by('-completed_at')[:10]
    
    # Get pending tasks in officer's counties
    pending_in_area = 0
    if officer:
        assigned_counties = officer.assigned_counties or []
        if assigned_counties:
            pending_in_area = VerificationTask.objects.filter(
                status='pending',
                verification_type='extension_review',
                plot__county__in=assigned_counties
            ).count()
    
    context = {
        'officer': officer,
        'assigned_tasks': assigned_tasks,
        'my_tasks': assigned_tasks,
        'completed_tasks': completed_tasks,
        'pending_in_area': pending_in_area,
        'workload': officer.current_workload if officer else 0,
        'page_title': 'Extension Officer Dashboard'
    }
    
    return render(request, 'listings/admin/my_tasks.html', context)


@login_required
def conduct_extension_review(request, task_id):
    """Conduct extension review for a plot"""
    task = get_object_or_404(
        VerificationTask,
        id=task_id,
        verification_type='extension_review'
    )
    if not request.user.is_superuser and task.assigned_to != request.user:
        messages.error(request, "You don't have permission to access this task.")
        return redirect('listings:extension_dashboard')
    
    plot = task.plot
    
    # Check if report already exists
    try:
        report = ExtensionReport.objects.get(task=task)
        messages.info(request, "A report already exists for this task.")
        return redirect('listings:view_extension_report', report_id=report.id)
    except ExtensionReport.DoesNotExist:
        pass
    
    if request.method == 'POST':
        form = ExtensionReportForm(request.POST, request.FILES)
        if form.is_valid():
            report = form.save(commit=False)
            report.task = task
            if request.user.is_superuser:
                if hasattr(task.assigned_to, 'extension_officer'):
                    report.officer = task.assigned_to.extension_officer
                else:
                    messages.error(request, "Assigned user has no extension officer profile.")
                    return redirect('listings:extension_dashboard')
            else:
                report.officer = request.user.extension_officer
            report.plot = plot
            report.save()

            # Persist verified agricultural data back to plot for search/filtering
            plot_updates = {}
            if report.soil_texture:
                plot_updates["soil_type"] = report.soil_texture
            if report.soil_ph_verified is not None:
                plot_updates["ph_level"] = report.soil_ph_verified
            if report.recommended_crops:
                plot_updates["crop_suitability"] = report.recommended_crops
            elif report.existing_crops:
                plot_updates["crop_suitability"] = report.existing_crops
            if plot_updates:
                for k, v in plot_updates.items():
                    setattr(plot, k, v)
                plot.save(update_fields=list(plot_updates.keys()))
            
            # Complete the task with the officer's recommendation
            approved = report.recommendation in ['approve', 'approve_with_conditions']
            VerificationService.complete_task(
                task_id=task.id,
                completed_by=request.user,
                notes=report.comments,
                approved=approved
            )
            
            messages.success(request, "Extension review submitted!")
            return redirect('listings:extension_dashboard')
    else:
        form = ExtensionReportForm()
    
    return render(request, 'listings/extension/conduct_review.html', {
        'task': task,
        'plot': plot,
        'form': form,
        'page_title': f'Extension Review: {plot.title}'
    })


@login_required
def view_extension_report(request, report_id):
    """View an extension report"""
    
    report = get_object_or_404(ExtensionReport, id=report_id)
    
    # Check permission
    if report.officer.user != request.user and not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "You don't have permission to view this report.")
        return redirect('listings:home')
    
    return render(request, 'listings/extension/view_report.html', {
        'report': report,
        'plot': report.plot,
        'page_title': f'Extension Report: {report.plot.title}'
    })


@login_required
def confirm_task(request, task_id):
    """Confirm an assigned task within the required window."""
    task = get_object_or_404(VerificationTask, id=task_id, assigned_to=request.user)
    if task.confirmation_status == 'confirmed':
        messages.info(request, "Task already confirmed.")
        return redirect('listings:my_tasks')
    if task.confirm_by and timezone.now() > task.confirm_by:
        messages.error(request, "Confirmation window expired. Please contact admin.")
        return redirect('listings:my_tasks')
    task.confirmation_status = 'confirmed'
    task.confirmed_at = timezone.now()
    task.save(update_fields=['confirmation_status', 'confirmed_at'])
    messages.success(request, "Task confirmed. Please complete it before the deadline.")
    return redirect('listings:my_tasks')


@login_required
def surveyor_dashboard(request):
    """Dashboard for land surveyors"""
    try:
        surveyor = request.user.land_surveyor
        if not surveyor.verified or not surveyor.is_active:
            messages.error(request, "Your land surveyor role is not active yet.")
            return redirect('listings:profile_management')
    except LandSurveyor.DoesNotExist:
        if request.user.is_superuser:
            surveyor = None
        else:
            messages.error(request, "You don't have a land surveyor profile.")
            return redirect('listings:home')

    assigned_tasks = VerificationTask.objects.filter(
        status='in_progress',
        verification_type='surveyor_inspection',
        assigned_to=request.user
    ).select_related('plot')

    completed_tasks = VerificationTask.objects.filter(
        status='completed',
        verification_type='surveyor_inspection',
        assigned_to=request.user
    ).select_related('plot').order_by('-completed_at')[:10]

    pending_in_area = 0
    if surveyor:
        assigned_counties = surveyor.assigned_counties or []
        if assigned_counties:
            pending_in_area = VerificationTask.objects.filter(
                status='pending',
                verification_type='surveyor_inspection',
                plot__county__in=assigned_counties
            ).count()

    context = {
        'surveyor': surveyor,
        'assigned_tasks': assigned_tasks,
        'my_tasks': assigned_tasks,
        'completed_tasks': completed_tasks,
        'pending_in_area': pending_in_area,
        'workload': surveyor.current_workload if surveyor else 0,
        'page_title': 'Land Surveyor Dashboard'
    }
    return render(request, 'listings/admin/my_tasks.html', context)


@login_required
def conduct_surveyor_inspection(request, task_id):
    """Conduct land surveyor inspection for a plot"""
    task = get_object_or_404(
        VerificationTask,
        id=task_id,
        verification_type='surveyor_inspection'
    )
    if not request.user.is_superuser and task.assigned_to != request.user:
        messages.error(request, "You don't have permission to access this task.")
        return redirect('listings:surveyor_dashboard')
    plot = task.plot

    try:
        report = SurveyorReport.objects.get(task=task)
        messages.info(request, "A report already exists for this task.")
        return redirect('listings:view_surveyor_report', report_id=report.id)
    except SurveyorReport.DoesNotExist:
        pass

    if request.method == 'POST':
        form = SurveyorReportForm(request.POST, request.FILES)
        if form.is_valid():
            report = form.save(commit=False)
            report.task = task
            if request.user.is_superuser:
                if hasattr(task.assigned_to, 'land_surveyor'):
                    report.surveyor = task.assigned_to.land_surveyor
                else:
                    messages.error(request, "Assigned user has no land surveyor profile.")
                    return redirect('listings:surveyor_dashboard')
            else:
                try:
                    report.surveyor = request.user.land_surveyor
                except LandSurveyor.DoesNotExist:
                    messages.error(request, "You do not have a land surveyor profile.")
                    return redirect('listings:surveyor_dashboard')
            report.plot = plot
            report.save()

            # Update plot GPS coordinates from surveyor report
            gps_updates = []
            if report.gps_latitude is not None:
                plot.latitude = report.gps_latitude
                gps_updates.append('latitude')
            if report.gps_longitude is not None:
                plot.longitude = report.gps_longitude
                gps_updates.append('longitude')
            if gps_updates:
                plot.save(update_fields=gps_updates)

            # If surveyor flags price unrealistic, update plot pricing (sale listings)
            if report.price_realistic is False and plot.listing_type in ['sale', 'both']:
                updated_fields = []
                if report.suggested_sale_price:
                    plot.sale_price = report.suggested_sale_price
                    updated_fields.append('sale_price')
                if report.suggested_price_per_acre:
                    plot.price_per_acre = report.suggested_price_per_acre
                    updated_fields.append('price_per_acre')
                elif report.suggested_sale_price and plot.area:
                    plot.price_per_acre = report.suggested_sale_price / plot.area
                    updated_fields.append('price_per_acre')
                if updated_fields:
                    note = "Surveyor price review: adjusted to surveyor suggested price."
                    plot.price_notes = (plot.price_notes + "\n" + note).strip() if plot.price_notes else note
                    updated_fields.append('price_notes')
                    plot.save(update_fields=updated_fields)

            approved = report.recommendation in ['approve', 'approve_with_conditions']
            VerificationService.complete_task(
                task_id=task.id,
                completed_by=request.user,
                notes=report.notes,
                approved=approved
            )

            messages.success(request, "Surveyor inspection submitted!")
            return redirect('listings:surveyor_dashboard')
    else:
        form = SurveyorReportForm()

    return render(request, 'listings/extension/conduct_review.html', {
        'task': task,
        'plot': plot,
        'form': form,
        'page_title': f'Surveyor Inspection: {plot.title}'
    })


@login_required
def view_surveyor_report(request, report_id):
    """View a land surveyor report"""
    report = get_object_or_404(SurveyorReport, id=report_id)

    if report.surveyor.user != request.user and not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "You don't have permission to view this report.")
        return redirect('listings:home')

    return render(request, 'listings/extension/view_report.html', {
        'report': report,
        'plot': report.plot,
        'page_title': f'Surveyor Report: {report.plot.title}'
    })
