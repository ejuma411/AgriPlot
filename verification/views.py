import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from notifications.notification_service import NotificationService
from .forms import ExtensionOfficerProfileForm, LandSurveyorProfileForm
from .models import ExtensionOfficer, LandSurveyor
from .standards import get_role_requirements

logger = logging.getLogger(__name__)


@login_required
def request_extension_officer(request):
    """Allow a user to request extension officer role (pending approval)."""
    try:
        existing = request.user.extension_officer
        messages.info(request, "You already have an extension officer profile.")
        return redirect("verification:extension_dashboard")
    except ExtensionOfficer.DoesNotExist:
        existing = None

    if request.method == "POST":
        form = ExtensionOfficerProfileForm(
            request.POST,
            instance=existing,
            user=request.user,
        )
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.verified = False
            profile.is_active = False
            profile.save()
            messages.success(
                request, "Request submitted. An admin will review your details."
            )
            try:
                NotificationService.notify_role_request(
                    request.user,
                    "Extension Officer",
                    details={
                        "station": profile.station,
                        "counties": profile.assigned_counties,
                    },
                )
            except Exception as exc:
                logger.error("Role request notification failed: %s", exc)
            return redirect("listings:profile_management")
    else:
        form = ExtensionOfficerProfileForm(instance=existing, user=request.user)

    context = {
        "form": form,
        "role_label": "Extension Officer",
        "requirements": get_role_requirements("extension_officer"),
    }
    return render(request, "verification/request_role.html", context)


@login_required
def request_land_surveyor(request):
    """Allow a user to request land surveyor role (pending approval)."""
    try:
        existing = request.user.land_surveyor
        messages.info(request, "You already have a land surveyor profile.")
        return redirect("verification:surveyor_dashboard")
    except LandSurveyor.DoesNotExist:
        existing = None

    if request.method == "POST":
        form = LandSurveyorProfileForm(
            request.POST,
            instance=existing,
            user=request.user,
        )
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.verified = False
            profile.is_active = False
            profile.save()
            messages.success(
                request, "Request submitted. An admin will review your details."
            )
            try:
                NotificationService.notify_role_request(
                    request.user,
                    "Land Surveyor",
                    details={
                        "station": profile.station,
                        "counties": profile.assigned_counties,
                    },
                )
            except Exception as exc:
                logger.error("Role request notification failed: %s", exc)
            return redirect("listings:profile_management")
    else:
        form = LandSurveyorProfileForm(instance=existing, user=request.user)

    context = {
        "form": form,
        "role_label": "Land Surveyor",
        "requirements": get_role_requirements("land_surveyor"),
    }
    return render(request, "verification/request_role.html", context)

# PDF EXPORT VIEWS
from django.http import HttpResponse
from django.template.loader import get_template
from django.utils import timezone
import logging
from security.models import AuditLog

logger = logging.getLogger(__name__)

def audit_logs_export_pdf(request):
    """Export filtered audit logs as a beautifully styled PDF"""
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
        # Get filtered queryset (reuse your existing filter logic)
        logs = AuditLog.objects.all().select_related('user').order_by('-created_at')
        
        # Apply filters (same as your main view)
        action = request.GET.get('action')
        user = request.GET.get('user')
        ip = request.GET.get('ip')
        object_type = request.GET.get('object_type')
        object_id = request.GET.get('object_id')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        q = request.GET.get('q')
        
        # Apply your existing filter logic here
        if action:
            logs = logs.filter(action=action)
        if user:
            logs = logs.filter(
                Q(user__username__icontains=user) | 
                Q(user__email__icontains=user)
            )
        if ip:
            logs = logs.filter(ip_address__icontains=ip)
        if object_type:
            logs = logs.filter(object_type__icontains=object_type)
        if object_id:
            logs = logs.filter(object_id=object_id)
        if date_from:
            logs = logs.filter(created_at__date__gte=date_from)
        if date_to:
            logs = logs.filter(created_at__date__lte=date_to)
        if q:
            logs = logs.filter(
                Q(action__icontains=q) |
                Q(object_type__icontains=q) |
                Q(extra__icontains=q)
            )
        
        # Get filter summary for the PDF header
        filter_summary = []
        if action:
            filter_summary.append(f"Action: {dict(AuditLog.ACTION_CHOICES).get(action, action)}")
        if user:
            filter_summary.append(f"User: {user}")
        if date_from or date_to:
            date_range = f"{date_from or 'Start'} to {date_to or 'Now'}"
            filter_summary.append(f"Date: {date_range}")
        
        total_count = logs.count()
        logs_list = list(logs[:1000])  # Limit to 1000 records for PDF performance
        first_log = logs_list[0] if logs_list else None
        last_log = logs_list[-1] if logs_list else None

        # Prepare context for PDF template
        context = {
            'logs': logs_list,
            'total_count': total_count,
            'display_count': len(logs_list),
            'first_log': first_log,
            'last_log': last_log,
            'export_date': timezone.now(),
            'filter_summary': filter_summary,
            'request': request,
        }
        
        # Render HTML template
        template = get_template('verification/admin/audit_logs_pdf.html')
        html_string = template.render(context)
        
        # Configure fonts
        font_config = FontConfiguration()
        
        # Generate PDF with custom styling
        pdf_file = HTML(string=html_string).write_pdf(
            stylesheets=[
                CSS(string='''
                    @page {
                        size: A4 landscape;
                        margin: 1.5cm;
                        @top-center {
                            content: "AgriPlot Audit Logs - " counter(page);
                            font-family: Arial, sans-serif;
                            font-size: 9pt;
                            color: #666;
                        }
                        @bottom-center {
                            content: "Generated on " counter(page) " of " counter(pages);
                            font-family: Arial, sans-serif;
                            font-size: 8pt;
                            color: #999;
                        }
                    }
                '''),
            ],
            font_config=font_config
        )
        
        # Create response
        response = HttpResponse(pdf_file, content_type='application/pdf')
        filename = f"audit_logs_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        logger.error(f"PDF export failed: {str(e)}")
        return HttpResponse(f"Error generating PDF: {str(e)}", status=500)
