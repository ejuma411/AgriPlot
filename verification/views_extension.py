# listings/views_extension.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.urls import reverse
from django.contrib.gis.geos import Point
from crops.services import suggest_crops
from listings.models import (
    ExtensionOfficer,
    LandSurveyor,
    VerificationTask,
    Plot,
    ExtensionReport,
    SurveyorReport,
    VerificationStatus,
)
from django.contrib.contenttypes.models import ContentType
from verification.forms import ExtensionReportForm, SurveyorReportForm
from verification.verification_service import VerificationService
import logging

logger = logging.getLogger(__name__)


def _extension_crop_suggestions(form, plot):
    def _value(field_name, fallback=None):
        if form.is_bound:
            return form.data.get(field_name) or fallback
        if hasattr(form, "initial") and form.initial.get(field_name) not in (None, ""):
            return form.initial.get(field_name)
        return fallback

    soil_classification = _value("soil_classification", getattr(plot, "soil_type", ""))
    soil_texture = _value("soil_texture", getattr(plot, "soil_type", ""))
    topography = _value("topography", getattr(plot, "topography", ""))
    soil_ph = _value("soil_ph", getattr(plot, "ph_level", None))
    irrigation_viability = _value("irrigation_viability", "")

    return suggest_crops(
        soil_ph=soil_ph,
        soil_classification=soil_classification,
        soil_texture=soil_texture,
        topography=topography,
        irrigation_viability=irrigation_viability,
        limit=5,
    )


def _workspace_redirect(section="tasks"):
    return redirect(f"{reverse('listings:dashboard_router')}?section={section}")

@login_required
def extension_dashboard(request):
    return _workspace_redirect("tasks")


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
        return redirect('verification:extension_dashboard')
    
    plot = task.plot
    
    # Check if report already exists
    try:
        report = ExtensionReport.objects.get(task=task)
        messages.info(request, "A report already exists for this task.")
        return redirect('verification:view_extension_report', report_id=report.id)
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
                    return redirect('verification:extension_dashboard')
            else:
                report.officer = request.user.extension_officer
            report.plot = plot
            auto_suggestions = _extension_crop_suggestions(form, plot)
            if not report.recommended_crops and auto_suggestions:
                report.recommended_crops = ", ".join(
                    item["crop"].name for item in auto_suggestions[:3]
                )
            report.save()

            # Persist verified agricultural data back to plot for search/filtering
            plot_updates = {}
            if report.soil_texture:
                plot_updates["soil_type"] = report.soil_texture
            if report.soil_ph is not None:
                plot_updates["ph_level"] = float(report.soil_ph)
            elif report.soil_ph_verified is not None:
                plot_updates["ph_level"] = report.soil_ph_verified
            if report.recommended_crops:
                plot_updates["crop_suitability"] = report.recommended_crops
            elif report.existing_crops:
                plot_updates["crop_suitability"] = report.existing_crops
            if report.distance_to_tarmac_m is not None:
                plot_updates["road_distance_km"] = round(report.distance_to_tarmac_m / 1000, 2)
            if report.water_source_verified or report.water_sources_available:
                plot_updates["has_water"] = True
                plot_updates["water_source"] = "irrigation" if "mains" in (report.water_sources_available or "").lower() else plot.water_source
            if report.power_access and report.power_access not in {"none", "unknown"}:
                plot_updates["has_electricity"] = True
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
            return redirect('verification:extension_dashboard')
    else:
        form = ExtensionReportForm()

    system_crop_suggestions = _extension_crop_suggestions(form, plot)
    
    return render(request, 'verification/extension/conduct_review.html', {
        'task': task,
        'plot': plot,
        'form': form,
        'page_title': f'Extension Review: {plot.title}',
        'system_crop_suggestions': system_crop_suggestions,
    })


@login_required
def view_extension_report(request, report_id):
    """View an extension report"""
    
    report = get_object_or_404(ExtensionReport, id=report_id)
    
    # Check permission
    if report.officer.user != request.user and not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "You don't have permission to view this report.")
        return redirect('listings:home')
    
    return render(request, 'verification/extension/view_report.html', {
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
        return _workspace_redirect("tasks")
    if task.confirm_by and timezone.now() > task.confirm_by:
        messages.error(request, "Confirmation window expired. Please contact admin.")
        return _workspace_redirect("tasks")
    task.confirmation_status = 'confirmed'
    task.confirmed_at = timezone.now()
    task.save(update_fields=['confirmation_status', 'confirmed_at'])
    messages.success(request, "Task confirmed. Please complete it before the deadline.")
    return _workspace_redirect("tasks")


@login_required
def surveyor_dashboard(request):
    return _workspace_redirect("tasks")


@login_required
def find_plot_by_parcel(request, role):
    """
    Find plot by parcel number and open the appropriate report form.
    role: 'surveyor' or 'extension'
    """
    if request.method != 'POST':
        return _workspace_redirect("tasks")

    parcel_number = (request.POST.get('parcel_number') or '').strip()
    if not parcel_number:
        messages.error(request, "Parcel number is required.")
        return _workspace_redirect("tasks")

    plot = Plot.objects.filter(parcel_number__iexact=parcel_number).first()
    if not plot:
        messages.error(request, "No plot found for that parcel number.")
        return _workspace_redirect("tasks")

    # Ensure verification status exists
    try:
        content_type = ContentType.objects.get_for_model(Plot)
        VerificationStatus.objects.get_or_create(
            content_type=content_type,
            object_id=plot.id,
            defaults={'current_stage': 'document_uploaded', 'document_uploaded_at': timezone.now()}
        )
    except Exception:
        pass

    if role == 'surveyor':
        task_type = 'surveyor_inspection'
        redirect_name = 'verification:conduct_surveyor_inspection'
    else:
        task_type = 'extension_review'
        redirect_name = 'verification:conduct_extension_review'

    task, created = VerificationTask.objects.get_or_create(
        plot=plot,
        verification_type=task_type,
        defaults={
            'status': 'in_progress',
            'assigned_to': request.user,
            'assigned_at': timezone.now(),
        }
    )

    if not created:
        if task.assigned_to and task.assigned_to != request.user and not request.user.is_superuser:
            messages.error(request, "This task is already assigned to another officer.")
            return _workspace_redirect("tasks")
        if task.status in ('pending', 'in_progress'):
            task.assigned_to = request.user
            task.status = 'in_progress'
            task.assigned_at = timezone.now()
            task.save(update_fields=['assigned_to', 'status', 'assigned_at'])

    return redirect(redirect_name, task_id=task.id)


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
        return redirect('verification:surveyor_dashboard')
    plot = task.plot

    try:
        report = SurveyorReport.objects.get(task=task)
        messages.info(request, "A report already exists for this task.")
        return redirect('verification:view_surveyor_report', report_id=report.id)
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
                    return redirect('verification:surveyor_dashboard')
            else:
                try:
                    report.surveyor = request.user.land_surveyor
                except LandSurveyor.DoesNotExist:
                    messages.error(request, "You do not have a land surveyor profile.")
                    return redirect('verification:surveyor_dashboard')
            report.plot = plot
            if not report.lsb_license_number and hasattr(report.surveyor, 'license_number'):
                report.lsb_license_number = report.surveyor.license_number
            report.save()

            # Save plot images uploaded by surveyor
            try:
                from listings.models import PlotImage
                images = form.cleaned_data.get('plot_images') or []
                if not isinstance(images, (list, tuple)):
                    images = [images]
                for img in images:
                    PlotImage.objects.create(
                        plot=plot,
                        image=img,
                        uploaded_by=request.user
                    )
            except Exception as e:
                logger.error(f"Failed to save plot images: {e}")

            # Update plot GPS coordinates from surveyor report
            gps_updates = []
            if report.gps_latitude is not None:
                plot.latitude = report.gps_latitude
                gps_updates.append('latitude')
            if report.gps_longitude is not None:
                plot.longitude = report.gps_longitude
                gps_updates.append('longitude')
            if gps_updates:
                if plot.latitude is not None and plot.longitude is not None:
                    try:
                        plot.geom = Point(float(plot.longitude), float(plot.latitude), srid=4326)
                        gps_updates.append('geom')
                    except Exception:
                        pass
                plot.save(update_fields=gps_updates)

            if report.ground_acreage and plot.area:
                try:
                    listed_area = float(plot.area)
                    if plot.area_unit == "acres":
                        listed_area = listed_area / 2.47105
                    measured_area = float(report.ground_acreage)
                    if measured_area > 0:
                        report.variance_flagged = abs(listed_area - measured_area) / measured_area > 0.05
                        report.save(update_fields=["variance_flagged"])
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

            # If surveyor flags price unrealistic, update plot pricing (sale listings)
            if report.price_realistic is False and plot.listing_type in ['sale', 'both']:
                updated_fields = []
                plot.price_review_required = True
                updated_fields.append('price_review_required')
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
            return redirect('verification:surveyor_dashboard')
    else:
        form = SurveyorReportForm()

    return render(request, 'verification/extension/conduct_review.html', {
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

    return render(request, 'verification/extension/view_report.html', {
        'report': report,
        'plot': report.plot,
        'page_title': f'Surveyor Report: {report.plot.title}'
    })
