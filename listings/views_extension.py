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
    
    # Get or create extension officer profile
    try:
        officer = request.user.extension_officer
    except ExtensionOfficer.DoesNotExist:
        messages.error(request, "You don't have an extension officer profile.")
        return redirect('listings:home')
    
    # Get assigned tasks
    assigned_tasks = VerificationTask.objects.filter(
        assigned_to=request.user,
        status='in_progress',
        verification_type='extension_review'
    ).select_related('plot')
    
    # Get completed tasks
    completed_tasks = VerificationTask.objects.filter(
        assigned_to=request.user,
        status='completed',
        verification_type='extension_review'
    ).select_related('plot').order_by('-completed_at')[:10]
    
    # Get pending tasks in officer's counties
    pending_in_area = VerificationTask.objects.filter(
        status='pending',
        verification_type='extension_review',
        plot__county__in=officer.assigned_counties
    ).select_related('plot').count()
    
    context = {
        'officer': officer,
        'assigned_tasks': assigned_tasks,
        'completed_tasks': completed_tasks,
        'pending_in_area': pending_in_area,
        'workload': officer.current_workload,
        'page_title': 'Extension Officer Dashboard'
    }
    
    return render(request, 'listings/admin/my_tasks.html', context)


@login_required
def conduct_extension_review(request, task_id):
    """Conduct extension review for a plot"""
    
    task = get_object_or_404(VerificationTask, 
                            id=task_id, 
                            assigned_to=request.user,
                            verification_type='extension_review')
    
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
            report.officer = request.user.extension_officer
            report.plot = plot
            report.save()
            
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
    if report.officer.user != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to view this report.")
        return redirect('listings:home')
    
    return render(request, 'listings/extension/view_report.html', {
        'report': report,
        'plot': report.plot,
        'page_title': f'Extension Report: {report.plot.title}'
    })


@login_required
def surveyor_dashboard(request):
    """Dashboard for land surveyors"""
    try:
        surveyor = request.user.land_surveyor
    except LandSurveyor.DoesNotExist:
        messages.error(request, "You don't have a land surveyor profile.")
        return redirect('listings:home')

    assigned_tasks = VerificationTask.objects.filter(
        assigned_to=request.user,
        status='in_progress',
        verification_type='surveyor_inspection'
    ).select_related('plot')

    completed_tasks = VerificationTask.objects.filter(
        assigned_to=request.user,
        status='completed',
        verification_type='surveyor_inspection'
    ).select_related('plot').order_by('-completed_at')[:10]

    pending_in_area = VerificationTask.objects.filter(
        status='pending',
        verification_type='surveyor_inspection',
        plot__county__in=surveyor.assigned_counties
    ).select_related('plot').count()

    context = {
        'surveyor': surveyor,
        'assigned_tasks': assigned_tasks,
        'completed_tasks': completed_tasks,
        'pending_in_area': pending_in_area,
        'workload': surveyor.current_workload,
        'page_title': 'Land Surveyor Dashboard'
    }
    return render(request, 'listings/admin/my_tasks.html', context)


@login_required
def conduct_surveyor_inspection(request, task_id):
    """Conduct land surveyor inspection for a plot"""
    task = get_object_or_404(
        VerificationTask,
        id=task_id,
        assigned_to=request.user,
        verification_type='surveyor_inspection'
    )
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
            report.surveyor = request.user.land_surveyor
            report.plot = plot
            report.save()

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

    if report.surveyor.user != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to view this report.")
        return redirect('listings:home')

    return render(request, 'listings/extension/view_report.html', {
        'report': report,
        'plot': report.plot,
        'page_title': f'Surveyor Report: {report.plot.title}'
    })
