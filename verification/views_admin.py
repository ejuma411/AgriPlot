# listings/views_admin.py
import json
import logging
import traceback
from pathlib import Path
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.template.loader import get_template
from django.conf import settings
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User
from django.db.models import Q, Count, Sum
from django.utils.dateparse import parse_date
from django.urls import reverse
from listings.models import *  # noqa: F403
from security.models import AuditLog
from verification.verification_service import VerificationService
from listings.utils import log_audit
from registry_mock.models import RegistryMismatchAttempt
from accounts.access_control import resolve_access_profile

# Add this logger definition
logger = logging.getLogger(__name__)


def _workspace_redirect(section):
    return redirect(f"{reverse('listings:dashboard_router')}?section={section}")


def _marketplace_analytics_snapshot(days):
    since = timezone.now() - timezone.timedelta(days=days)
    active_users_daily = User.objects.filter(last_login__date=timezone.localdate()).count()
    active_users_weekly = User.objects.filter(last_login__gte=timezone.now() - timezone.timedelta(days=7)).count()
    top_regions = (
        Plot.objects.filter(is_hidden=False)
        .exclude(county__isnull=True)
        .values("county", "land_type")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    fraud_counts = list(
        FraudReport.objects.values("status").annotate(total=Count("id")).order_by("status")
    )
    fraud_recent = FraudReport.objects.filter(created_at__gte=since).count()
    revenue_simulation = Plot.objects.filter(is_hidden=False).aggregate(
        sale_total=Sum("sale_price"),
        lease_total=Sum("lease_price_yearly"),
    )
    return {
        "active_users_daily": active_users_daily,
        "active_users_weekly": active_users_weekly,
        "top_regions": list(top_regions),
        "fraud_counts": fraud_counts,
        "fraud_recent": fraud_recent,
        "revenue_simulation": revenue_simulation,
    }

# Add this to views_admin.py - somewhere after your other imports

@staff_member_required
def trigger_ardhisasa(request, plot_id):
    """Manually trigger Ardhisasa verification for a plot (runs directly, no Celery)"""
    from django.http import JsonResponse
    from django.contrib.contenttypes.models import ContentType
    from listings.models import Plot, VerificationStatus
    from verification.services.ardhisasa_integration import ArdhisasaService
    
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
        return JsonResponse({
            'success': True, 
            'message': 'Ardhisasa verification completed',
            'data': verification_data
        })
    else:
        verification.stage_details['ardhisasa_error'] = result.get('error')
        verification.stage_details['ardhisasa_failure'] = result.get('decision')
        VerificationStatus.objects.filter(pk=verification.pk).update(
            current_stage='rejected',
            rejected_at=timezone.now(),
            stage_details=verification.stage_details
        )
        return JsonResponse({
            'success': False, 
            'error': result.get('error', 'Unknown error occurred')
        })
        
                
# For extension officer views, create a custom decorator
from django.core.exceptions import PermissionDenied

def extension_officer_required(view_func):
    """Decorator to require extension officer status"""
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        if not hasattr(request.user, 'extension_officer'):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@staff_member_required
def verification_dashboard(request):
    return _workspace_redirect("verification")
    
    # Get content type for Plot
    plot_content_type = ContentType.objects.get_for_model(Plot)
    
    # Get counts for dashboard using the verification relation
    stats = {
        'pending_review': VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage='document_uploaded'
        ).count(),
        'pending_registry_search': VerificationTask.objects.filter(
            verification_type='registry_search',
            status='pending'
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

    flagged_parcels = RegistryMismatchAttempt.objects.values("parcel_number").annotate(
        attempts=Count("id")
    ).filter(attempts__gte=3).order_by("-attempts")[:10]
    flagged_total = RegistryMismatchAttempt.objects.values("parcel_number").annotate(
        attempts=Count("id")
    ).filter(attempts__gte=3).count()
    
    # Extract the plot IDs and fetch the plots
    plot_ids = [v.object_id for v in pending_verifications]
    pending_plots = Plot.objects.filter(id__in=plot_ids).select_related(
        'landowner__user', 
        'agent__user'
    )
    
    context = {
        'stats': stats,
        'pending_plots': pending_plots,
        'page_title': 'Verification Dashboard',
        'flagged_parcels': flagged_parcels,
        'flagged_total': flagged_total,
    }
    
    return render(request, 'verification/admin/verification_dashboard.html', context)


@staff_member_required
def registry_parcels(request):
    """List registry parcel numbers for testing land search."""
    q = (request.GET.get("q") or "").strip()
    parcels = Plot.objects.filter(is_registry_record=True)
    if q:
        parcels = parcels.filter(
            Q(parcel_number__icontains=q) |
            Q(registration_section__icontains=q) |
            Q(county__icontains=q) |
            Q(subcounty__icontains=q)
        )
    parcels = parcels.order_by("county", "parcel_number")
    return render(request, "verification/admin/registry_parcels.html", {
        "page_title": "Registry Parcels",
        "parcels": parcels,
        "query": q,
        "total": parcels.count(),
    })


@staff_member_required
def registry_mismatches(request):
    """View registry mismatch attempts for audit and fraud prevention."""
    q = (request.GET.get("q") or "").strip()
    attempts = RegistryMismatchAttempt.objects.all().order_by("-created_at")
    if q:
        attempts = attempts.filter(
            Q(parcel_number__icontains=q) |
            Q(provided_owner_name__icontains=q) |
            Q(provided_owner_id__icontains=q)
        )
    return render(request, "verification/admin/registry_mismatches.html", {
        "page_title": "Registry Mismatch Report",
        "attempts": attempts[:500],
        "query": q,
        "total": attempts.count(),
    })


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
    registry_task_map = {
        task.plot_id: task
        for task in VerificationTask.objects.filter(
            plot_id__in=plot_ids,
            verification_type='registry_search'
        )
    }
    
    # Attach verification status to each plot
    for plot in plots:
        plot.verification_status = verification_map.get(plot.id)
        plot.registry_task = registry_task_map.get(plot.id)
    
    context = {
        'plots': plots,
        'current_filter': filter_type,
        'page_title': 'Verification Queue'
    }
    
    return render(request, 'verification/admin/verification_queue.html', context)


@staff_member_required
def system_construction_journal(request):
    """Admin-only system construction journal page."""
    data_file = Path(settings.BASE_DIR) / "verification" / "data" / "system_construction_journal.json"
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
    return render(request, "verification/admin/system_construction_journal.html", context)


@staff_member_required
def system_construction_journal_pdf(request):
    """Export system construction journal as a PDF."""
    if not request.user.is_superuser:
        raise PermissionDenied

    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
    except Exception as exc:
        logger.error("WeasyPrint not available: %s", exc)
        return HttpResponse("PDF export is unavailable. Install WeasyPrint.", status=500)

    data_file = Path(settings.BASE_DIR) / "verification" / "data" / "system_construction_journal.json"
    entries = []
    if data_file.exists():
        try:
            entries = json.loads(data_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            messages.error(request, "Journal data file is not valid JSON.")
    else:
        messages.warning(request, "Journal data file is missing. Create it to display entries.")

    context = {
        "entries": entries,
        "export_date": timezone.now(),
        "total_count": len(entries),
    }

    template = get_template("verification/admin/system_construction_journal_pdf.html")
    html_string = template.render(context)
    font_config = FontConfiguration()

    pdf_file = HTML(string=html_string).write_pdf(
        stylesheets=[
            CSS(
                string="""
                @page {
                    size: A4 landscape;
                    margin: 1.2cm;
                }
                """
            )
        ],
        font_config=font_config,
    )

    response = HttpResponse(pdf_file, content_type="application/pdf")
    filename = f"system_construction_journal_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@staff_member_required
def review_plot(request, plot_id):
    """Review a single plot"""
    plot = (
        Plot.objects.select_related(
            'landowner__user',
            'agent__user'
        )
        .filter(id=plot_id)
        .first()
    )
    if not plot:
        messages.error(request, "Plot not found or already deleted.")
        return redirect('verification:verification_queue')
    
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
    
    admin_ready = False
    if verification and verification.current_stage == 'admin_review':
        admin_ready = bool(verification.stage_details.get('admin_review', {}).get('ready_for_publish'))

    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        
        if action in ('approve', 'publish'):
            if not admin_ready:
                messages.error(request, "This plot is not ready for final approval yet.")
                return redirect('verification:review_plot', plot_id=plot.id)
            missing_reports = VerificationService.has_required_reports(plot)
            required_types = set(VerificationService.required_task_types(plot))
            existing_types = set(
                VerificationTask.objects.filter(plot=plot).values_list('verification_type', flat=True)
            )
            missing_types = list(required_types - existing_types)

            if missing_types or missing_reports:
                messages.error(
                    request,
                    f"Cannot approve. Missing tasks: {missing_types} | Missing reports: {missing_reports}"
                )
                return redirect('verification:review_plot', plot_id=plot.id)
            # Update verification status
            verification.current_stage = 'approved'
            verification.approved_at = timezone.now()
            verification.stage_details['approval_notes'] = notes
            verification.stage_details['approved_by'] = request.user.username
            verification.save()

            plot.is_published = True
            plot.is_hidden = False
            plot.save(update_fields=['is_published', 'is_hidden'])
            
            # Create log entry
            VerificationLog.objects.create(
                plot=plot,
                verified_by=request.user,
                verification_type='approval',
                comment=f"Plot approved. Notes: {notes}"
            )

            try:
                from notifications.notification_service import NotificationService
                NotificationService.notify_plot_final_status(plot, 'approved', request.user, notes)
            except Exception as e:
                logger.error(f"Plot approval notification failed: {e}")
            
            messages.success(request, f"Plot '{plot.title}' has been published!")
            return redirect('verification:verification_queue')
            
        elif action == 'reject':
            verification.current_stage = 'document_uploaded'
            verification.stage_details['admin_rejection_reason'] = notes
            verification.stage_details['rejected_by'] = request.user.username
            verification.save()

            # Send back to extension officer for re-check
            ext_task, created = VerificationTask.objects.get_or_create(
                plot=plot,
                verification_type='extension_review',
                defaults={'status': 'pending'}
            )
            if created:
                VerificationService.assign_extension_task(ext_task.id, assigned_by=request.user)
            
            VerificationLog.objects.create(
                plot=plot,
                verified_by=request.user,
                verification_type='rejection',
                comment=f"Plot rejected. Reason: {notes}"
            )

            messages.warning(request, f"Plot '{plot.title}' sent back to Extension Officer for review.")
            return redirect('verification:verification_queue')
            
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
            return redirect('verification:verification_queue')
    
    context = {
        'plot': plot,
        'verification': verification,
        'verification_logs': verification_logs,
        'admin_ready': admin_ready,
        'page_title': f'Review: {plot.title}'
    }
    
    return render(request, 'verification/admin/review_plot.html', context)


def audit_logs(request):
    """Superadmin-only audit log view with filters and pagination."""
    if not request.user.is_superuser:
        raise PermissionDenied

    qs = AuditLog.objects.select_related("user").all()

    qs, filters, action_choices = _filter_audit_logs(request, qs)

    total_count = qs.count()
    last_24h = qs.filter(created_at__gte=timezone.now() - timezone.timedelta(days=1)).count()
    action_counts = (
        qs.values("action")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    top_users = (
        qs.values("user__username")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    try:
        per_page = int(request.GET.get("per_page", 50))
    except ValueError:
        per_page = 50
    if per_page not in (25, 50, 100):
        per_page = 50

    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))

    query_params = request.GET.copy()
    query_params.pop("page", None)
    base_querystring = query_params.urlencode()

    context = {
        "page_obj": page_obj,
        "logs": page_obj.object_list,
        "total_count": total_count,
        "last_24h": last_24h,
        "action_counts": action_counts,
        "top_users": top_users,
        "filters": {**filters, "per_page": per_page},
        "action_choices": action_choices,
        "base_querystring": base_querystring,
    }

    return render(request, "verification/admin/audit_logs.html", context)


def export_audit_logs(request):
    """Export audit logs (CSV or JSON). Superadmin only."""
    if not request.user.is_superuser:
        raise PermissionDenied

    qs = AuditLog.objects.select_related("user").all()
    qs, _filters, _action_choices = _filter_audit_logs(request, qs)

    export_format = (request.GET.get("format") or "csv").lower()
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")

    if export_format == "json":
        rows = []
        for log in qs.iterator():
            rows.append(
                {
                    "id": log.id,
                    "created_at": log.created_at.isoformat(),
                    "user_id": log.user_id,
                    "username": log.user.username if log.user else None,
                    "email": log.user.email if log.user else None,
                    "action": log.action,
                    "object_type": log.object_type,
                    "object_id": log.object_id,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "extra": log.extra,
                }
            )
        response = HttpResponse(
            json.dumps(rows, indent=2),
            content_type="application/json",
        )
        response["Content-Disposition"] = f'attachment; filename="audit_logs_{timestamp}.json"'
        return response

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="audit_logs_{timestamp}.csv"'
    response.write(
        "id,created_at,user_id,username,email,action,object_type,object_id,ip_address,user_agent,extra\n"
    )
    for log in qs.iterator():
        row = [
            log.id,
            log.created_at.isoformat(),
            log.user_id or "",
            (log.user.username if log.user else "") or "",
            (log.user.email if log.user else "") or "",
            log.action,
            log.object_type,
            log.object_id or "",
            log.ip_address or "",
            (log.user_agent or "").replace("\n", " ").replace("\r", " "),
            json.dumps(log.extra) if log.extra is not None else "",
        ]
        response.write(",".join([_csv_escape(value) for value in row]) + "\n")
    return response


def _filter_audit_logs(request, qs):
    action = request.GET.get("action") or ""
    user_query = request.GET.get("user") or ""
    ip_address = request.GET.get("ip") or ""
    object_type = request.GET.get("object_type") or ""
    object_id = request.GET.get("object_id") or ""
    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    search = request.GET.get("q") or ""

    if action:
        qs = qs.filter(action=action)
    if user_query:
        qs = qs.filter(
            Q(user__username__icontains=user_query)
            | Q(user__email__icontains=user_query)
            | Q(user__first_name__icontains=user_query)
            | Q(user__last_name__icontains=user_query)
        )
    if ip_address:
        qs = qs.filter(ip_address__icontains=ip_address)
    if object_type:
        qs = qs.filter(object_type__icontains=object_type)
    if object_id:
        try:
            qs = qs.filter(object_id=int(object_id))
        except ValueError:
            qs = qs.none()

    if date_from:
        parsed = parse_date(date_from)
        if parsed:
            qs = qs.filter(created_at__date__gte=parsed)
    if date_to:
        parsed = parse_date(date_to)
        if parsed:
            qs = qs.filter(created_at__date__lte=parsed)

    if search:
        qs = qs.filter(
            Q(action__icontains=search)
            | Q(object_type__icontains=search)
            | Q(user__username__icontains=search)
            | Q(user__email__icontains=search)
        )

    filters = {
        "action": action,
        "user": user_query,
        "ip": ip_address,
        "object_type": object_type,
        "object_id": object_id,
        "date_from": date_from,
        "date_to": date_to,
        "q": search,
    }

    return qs, filters, AuditLog.ACTION_CHOICES


def _csv_escape(value):
    text = str(value) if value is not None else ""
    if any(ch in text for ch in [",", "\"", "\n", "\r"]):
        return '"' + text.replace('"', '""') + '"'
    return text
    action = request.GET.get("action") or ""
    user_query = request.GET.get("user") or ""
    ip_address = request.GET.get("ip") or ""
    object_type = request.GET.get("object_type") or ""
    object_id = request.GET.get("object_id") or ""
    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    search = request.GET.get("q") or ""

    if action:
        qs = qs.filter(action=action)
    if user_query:
        qs = qs.filter(
            Q(user__username__icontains=user_query)
            | Q(user__email__icontains=user_query)
            | Q(user__first_name__icontains=user_query)
            | Q(user__last_name__icontains=user_query)
        )
    if ip_address:
        qs = qs.filter(ip_address__icontains=ip_address)
    if object_type:
        qs = qs.filter(object_type__icontains=object_type)
    if object_id:
        try:
            qs = qs.filter(object_id=int(object_id))
        except ValueError:
            qs = qs.none()

    if date_from:
        parsed = parse_date(date_from)
        if parsed:
            qs = qs.filter(created_at__date__gte=parsed)
    if date_to:
        parsed = parse_date(date_to)
        if parsed:
            qs = qs.filter(created_at__date__lte=parsed)

    if search:
        qs = qs.filter(
            Q(action__icontains=search)
            | Q(object_type__icontains=search)
            | Q(user__username__icontains=search)
            | Q(user__email__icontains=search)
        )

    total_count = qs.count()
    last_24h = qs.filter(created_at__gte=timezone.now() - timezone.timedelta(days=1)).count()
    action_counts = (
        qs.values("action")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    top_users = (
        qs.values("user__username")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    try:
        per_page = int(request.GET.get("per_page", 50))
    except ValueError:
        per_page = 50
    if per_page not in (25, 50, 100):
        per_page = 50

    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))

    query_params = request.GET.copy()
    query_params.pop("page", None)
    base_querystring = query_params.urlencode()

    context = {
        "page_obj": page_obj,
        "logs": page_obj.object_list,
        "total_count": total_count,
        "last_24h": last_24h,
        "action_counts": action_counts,
        "top_users": top_users,
        "filters": {
            "action": action,
            "user": user_query,
            "ip": ip_address,
            "object_type": object_type,
            "object_id": object_id,
            "date_from": date_from,
            "date_to": date_to,
            "q": search,
            "per_page": per_page,
        },
        "action_choices": AuditLog.ACTION_CHOICES,
        "base_querystring": base_querystring,
    }

    return render(request, "verification/admin/audit_logs.html", context)


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
    
    return render(request, 'verification/admin/verification_history.html', context)


# listings/views_admin.py - Add these new views

from django.contrib.auth.models import User
from verification.verification_service import VerificationService
from django.http import JsonResponse

@staff_member_required
def task_assignment(request):
    """View for managing task assignments"""
    if not request.user.is_superuser:
        messages.error(request, "You do not have permission to assign tasks.")
        return redirect('listings:dashboard_router')
    
    # Get all pending tasks
    pending_tasks = VerificationTask.objects.filter(
        status='pending'
    ).select_related('plot', 'plot__agent__user', 'plot__landowner__user').order_by('assigned_at')
    
    # Get in-progress tasks
    in_progress_tasks = VerificationTask.objects.filter(
        status='in_progress'
    ).select_related('plot', 'assigned_to').order_by('-assigned_at')
    
    # Get EXTENSION OFFICERS and SURVEYORS
    from .models import ExtensionOfficer, LandSurveyor
    extension_officers = ExtensionOfficer.objects.filter(
        is_active=True,
        verified=True
    ).select_related('user')
    surveyors = LandSurveyor.objects.filter(
        is_active=True,
        verified=True
    ).select_related('user')
    staff_users = User.objects.filter(is_staff=True)

    # Add unassigned reasons for pending tasks
    for task in pending_tasks:
        reason = "Awaiting manual assignment"
        if task.confirmation_status == 'expired':
            reason = "Assignment expired (not confirmed within 12 hours)"
        if not task.plot.county:
            reason = "Missing plot county"
        elif task.verification_type == 'extension_review':
            available = [o for o in extension_officers if task.plot.county in (o.assigned_counties or [])]
            if not available:
                reason = f"No verified extension officer for {task.plot.county}"
        elif task.verification_type == 'surveyor_inspection':
            available = [s for s in surveyors if task.plot.county in (s.assigned_counties or [])]
            if not available:
                reason = f"No verified land surveyor for {task.plot.county}"
        elif task.verification_type == 'document_review':
            reason = "Awaiting admin assignment"
        elif task.verification_type == 'registry_search':
            reason = "Automated registry search (system task)"
        task.unassigned_reason = reason
    
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
        'surveyors': surveyors,
        'staff_users': staff_users,
        'workload': workload,
        'task_stats': task_stats,
        'page_title': 'Task Assignment'
    }
    
    return render(request, 'verification/admin/task_assignment.html', context)

@staff_member_required
def ajax_assign_task(request):
    """AJAX endpoint for task assignment"""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            task_id = data.get('task_id')
            user_id = data.get('user_id')

            if not request.user.is_superuser:
                return JsonResponse({
                    'success': False,
                    'message': 'You do not have permission to assign tasks'
                }, status=403)
            
            # Now logger is defined
            logger.info(f"AJAX assign task - Task ID: {task_id}, User ID: {user_id}, Request by: {request.user.username}")
            
            if not task_id or not user_id:
                return JsonResponse({
                    'success': False,
                    'message': 'Task ID and User ID are required'
                }, status=400)
            
            try:
                assigned_to = User.objects.get(id=user_id)
            except User.DoesNotExist:
                logger.error(f"User {user_id} not found")
                return JsonResponse({
                    'success': False,
                    'message': 'Selected user not found'
                }, status=404)

            task = VerificationTask.objects.filter(id=task_id).first()
            if not task:
                logger.error(f"Task {task_id} not found")
                return JsonResponse({
                    'success': False,
                    'message': 'Task not found'
                }, status=404)

            if task.verification_type == 'extension_review':
                is_eligible = assigned_to.is_superuser or hasattr(assigned_to, 'extension_officer')
                if not is_eligible:
                    logger.error(f"User {user_id} not eligible for extension task {task_id}")
                    return JsonResponse({
                        'success': False,
                        'message': 'Selected user is not an Extension Officer'
                    }, status=400)
            elif task.verification_type == 'surveyor_inspection':
                is_eligible = assigned_to.is_superuser or hasattr(assigned_to, 'land_surveyor')
                if not is_eligible:
                    logger.error(f"User {user_id} not eligible for surveyor task {task_id}")
                    return JsonResponse({
                        'success': False,
                        'message': 'Selected user is not a Land Surveyor'
                    }, status=400)
            else:
                # Document review or other staff tasks
                if not assigned_to.is_staff and not assigned_to.is_superuser:
                    logger.error(f"User {user_id} not eligible for staff task {task_id}")
                    return JsonResponse({
                        'success': False,
                        'message': 'Selected user is not staff'
                    }, status=400)
            
            # Assign the task
            from verification.verification_service import VerificationService
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
    access_profile = resolve_access_profile(request.user)
    can_manage_task_queue = (
        request.user.is_superuser
        or access_profile.can("tasks.view_all")
        or access_profile.can("tasks.assign")
        or access_profile.can("verification.review")
    )

    my_tasks = VerificationTask.objects.filter(
        assigned_to=request.user,
        status__in=['pending', 'in_progress']
    ).select_related('plot').order_by('assigned_at')
    
    completed_tasks = VerificationTask.objects.filter(
        assigned_to=request.user,
        status='completed'
    ).select_related('plot').order_by('-completed_at')[:10]
    
    pending_admin_tasks = VerificationTask.objects.none()
    admin_review_plots = Plot.objects.none()
    if can_manage_task_queue:
        pending_admin_tasks = VerificationTask.objects.filter(
            verification_type='document_review',
            status='pending',
            assigned_to__isnull=True,
        ).select_related('plot').order_by('assigned_at')
        
        plot_content_type = ContentType.objects.get_for_model(Plot)
        admin_review_ids = VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage='admin_review'
        ).values_list('object_id', flat=True)
        admin_review_plots = Plot.objects.filter(id__in=admin_review_ids)
    
    context = {
        'my_tasks': my_tasks,
        'completed_tasks': completed_tasks,
        'pending_in_area': None,
        'page_title': 'My Tasks',
        'pending_admin_tasks': pending_admin_tasks,
        'admin_review_plots': admin_review_plots,
        'can_manage_task_queue': can_manage_task_queue,
    }
    
    return render(request, 'verification/admin/my_tasks.html', context)


@staff_member_required
def complete_task_view(request, task_id):
    """View for completing a task"""
    
    task = get_object_or_404(VerificationTask, id=task_id, assigned_to=request.user)
    if task.verification_type == "extension_review":
        return redirect("verification:conduct_extension_review", task_id=task.id)
    if task.verification_type == "surveyor_inspection":
        return redirect("verification:conduct_surveyor_inspection", task_id=task.id)

    plot_content_type = ContentType.objects.get_for_model(Plot)
    verification = VerificationStatus.objects.filter(
        content_type=plot_content_type,
        object_id=task.plot.id
    ).first()
    registry_data = {}
    if verification:
        registry_data = verification.stage_details.get('title_search_completed', {}) or {}
    expected_owner_name = (task.plot.owner_full_name or '').strip()
    if not expected_owner_name and task.plot.landowner:
        expected_owner_name = (task.plot.landowner.user.get_full_name() or task.plot.landowner.user.username).strip()
    expected_owner_id = (task.plot.owner_id_number or '').strip()
    
    if request.method == 'POST':
        notes = request.POST.get('notes', '')
        approved = request.POST.get('approved') == 'true'
        review_metadata = None

        if task.verification_type == 'document_review':
            from .models import DocumentVerification
            from verification.services.ocr_service import DocumentOCRService, OCRUnavailable
            ocr_results = {}
            form_data = {
                'owner_name_extracted': request.POST.get('owner_name_extracted', '').strip(),
                'id_number_extracted': request.POST.get('id_number_extracted', '').strip(),
                'kra_pin_extracted': request.POST.get('kra_pin_extracted', '').strip(),
                'title_number_extracted': request.POST.get('title_number_extracted', '').strip(),
                'parcel_number_extracted': request.POST.get('parcel_number_extracted', '').strip(),
                'search_ref_extracted': request.POST.get('search_ref_extracted', '').strip(),
                'search_date_extracted': request.POST.get('search_date_extracted', '').strip(),
            }
            confirm_doc_match = bool(request.POST.get('confirm_doc_match'))

            def _norm(value):
                return ''.join(c for c in (value or '').lower().strip() if c.isalnum())

            owner_name_matches = True
            if expected_owner_name:
                owner_name_matches = _norm(form_data['owner_name_extracted']) == _norm(expected_owner_name)
            id_matches = True
            if expected_owner_id:
                id_matches = _norm(form_data['id_number_extracted']) == _norm(expected_owner_id)

            missing_fields = [k for k, v in form_data.items() if not v and k != 'search_date_extracted']
            registry_owner_name = registry_data.get('owner_name') or registry_data.get('registered_owner_name')
            registry_title_number = registry_data.get('title_number')
            registry_parcel_number = registry_data.get('parcel_number')

            if approved:
                errors = []
                if missing_fields:
                    errors.append("All extracted document fields must be filled before approval.")
                if not confirm_doc_match:
                    errors.append("You must confirm extracted details match the uploaded documents.")
                if expected_owner_name and not owner_name_matches:
                    errors.append("Registered owner name does not match the listing's registered owner details.")
                if expected_owner_id and not id_matches:
                    errors.append("Registered owner ID number does not match the listing's registered owner details.")
                if registry_owner_name and _norm(form_data['owner_name_extracted']) != _norm(registry_owner_name):
                    errors.append("Registered owner name does not match registry search results.")
                if registry_title_number and _norm(form_data['title_number_extracted']) != _norm(registry_title_number):
                    errors.append("Title number does not match registry search results.")
                if registry_parcel_number and _norm(form_data['parcel_number_extracted']) != _norm(registry_parcel_number):
                    errors.append("Parcel number does not match registry search results.")

                # OCR strict check: compare extracted values with OCR results
                try:
                    ocr_results = {}
                    ocr_title = DocumentOCRService.extract_fields(
                        DocumentOCRService.extract_text(task.plot.title_deed)
                    )
                    ocr_search = DocumentOCRService.extract_fields(
                        DocumentOCRService.extract_text(task.plot.official_search)
                    )
                    ocr_id = DocumentOCRService.extract_fields(
                        DocumentOCRService.extract_text(task.plot.landowner_id_doc)
                    )
                    ocr_kra = DocumentOCRService.extract_fields(
                        DocumentOCRService.extract_text(task.plot.kra_pin)
                    )
                    ocr_results = {
                        'title_deed': ocr_title,
                        'official_search': ocr_search,
                        'national_id': ocr_id,
                        'kra_pin': ocr_kra
                    }

                    def _match_pair(label, a, b):
                        return _norm(a) == _norm(b) and _norm(a) != ""

                    # Document-to-document comparisons
                    if not _match_pair('owner_name', ocr_title.get('owner_name'), ocr_search.get('owner_name')):
                        errors.append("OCR check failed: Owner name mismatch between Title Deed and Official Search.")
                    if not _match_pair('title_number', ocr_title.get('title_number'), ocr_search.get('title_number')):
                        errors.append("OCR check failed: Title number mismatch between Title Deed and Official Search.")
                    if ocr_search.get('parcel_number') and not _match_pair('parcel_number', ocr_title.get('parcel_number'), ocr_search.get('parcel_number')):
                        errors.append("OCR check failed: Parcel number mismatch between Title Deed and Official Search.")

                    # Cross-document owner name with ID and KRA
                    if _norm(ocr_id.get('owner_name')) and not _match_pair('owner_name', ocr_title.get('owner_name'), ocr_id.get('owner_name')):
                        errors.append("OCR check failed: Owner name mismatch between Title Deed and National ID.")
                    if _norm(ocr_kra.get('owner_name')) and not _match_pair('owner_name', ocr_title.get('owner_name'), ocr_kra.get('owner_name')):
                        errors.append("OCR check failed: Owner name mismatch between Title Deed and KRA PIN.")

                    # Required fields present
                    if not _norm(ocr_id.get('id_number')):
                        errors.append("OCR check failed: National ID number not found in ID document.")
                    if not _norm(ocr_kra.get('kra_pin')):
                        errors.append("OCR check failed: KRA PIN not found in KRA certificate.")
                    if not _norm(ocr_search.get('search_ref')):
                        errors.append("OCR check failed: Search reference not found in Official Search.")
                except OCRUnavailable as exc:
                    errors.append(f"OCR unavailable: {exc}. Install Tesseract + pytesseract to enable strict checks.")
                    ocr_results = {'error': str(exc)}

                if errors:
                    try:
                        logger.error(
                            "Document review blocked by OCR checks. plot_id=%s task_id=%s errors=%s ocr=%s",
                            task.plot.id,
                            task.id,
                            errors,
                            ocr_results
                        )
                    except Exception:
                        pass
                    for err in errors:
                        messages.error(request, err)
                    context = {
                        'task': task,
                        'plot': task.plot,
                        'page_title': f'Complete Task: {task.get_verification_type_display()}',
                        'expected_owner_name': expected_owner_name,
                        'form_data': form_data,
                        'registry_data': registry_data
                    }
                    return render(request, 'verification/admin/complete_task.html', context)

            doc_checklist = {
                'title_deed': bool(request.POST.get('check_title')),
                'official_search': bool(request.POST.get('check_search')),
                'national_id': bool(request.POST.get('check_id')),
                'kra_pin': bool(request.POST.get('check_kra')),
            }
            review_checklist = {
                'name_match': bool(request.POST.get('check_name_match')),
                'seal_signature': bool(request.POST.get('check_seal_signature')),
                'rates_clearance': bool(request.POST.get('check_rates_clearance')),
                'rent_clearance': bool(request.POST.get('check_rent_clearance')),
                'consent_transfer': bool(request.POST.get('check_consent_transfer')),
                'lcb_consent': bool(request.POST.get('check_lcb_consent')),
                'mutation_form': bool(request.POST.get('check_mutation_form')),
                'plupa1': bool(request.POST.get('check_plupa1')),
                'spousal_consent': bool(request.POST.get('check_spousal_consent')),
                'search_recency': bool(request.POST.get('check_search_recency')),
            }
            checklist = {**doc_checklist, **review_checklist}
            search_date_extracted = parse_date(form_data.get('search_date_extracted') or "")
            if approved and review_checklist.get('search_recency'):
                if not search_date_extracted:
                    messages.error(request, "Search recency check requires a valid official search date.")
                else:
                    days_since = (timezone.now().date() - search_date_extracted).days
                    if days_since > 30:
                        messages.error(request, "Official search must be dated within the last 30 days.")
                        review_checklist['search_recency'] = False
            if approved and review_checklist.get('rates_clearance'):
                if not task.plot.rates_clearance:
                    messages.error(request, "Rates clearance certificate is required for approval.")
                    review_checklist['rates_clearance'] = False
            if approved and task.plot.ownership_type == 'leasehold':
                if review_checklist.get('rent_clearance') and not task.plot.rent_clearance:
                    messages.error(request, "Rent clearance certificate is required for leasehold plots.")
                    review_checklist['rent_clearance'] = False
                if review_checklist.get('consent_transfer') and not task.plot.consent_to_transfer:
                    messages.error(request, "Consent to transfer is required for leasehold plots.")
                    review_checklist['consent_transfer'] = False
            if approved and task.plot.land_type == 'agricultural':
                if review_checklist.get('lcb_consent') and not task.plot.lcb_consent_doc:
                    messages.error(request, "LCB consent is required for agricultural land.")
                    review_checklist['lcb_consent'] = False
            if approved and task.plot.is_subdivision:
                if review_checklist.get('mutation_form') and not task.plot.survey_map:
                    messages.error(request, "Mutation form/survey map is required for subdivision.")
                    review_checklist['mutation_form'] = False
                if review_checklist.get('plupa1') and not task.plot.plupa1_form:
                    messages.error(request, "PLUPA 1 / PPA 1 approval form is required for subdivision.")
                    review_checklist['plupa1'] = False
            if approved and task.plot.spousal_consent:
                if review_checklist.get('spousal_consent') and not task.plot.spousal_consent_doc:
                    messages.error(request, "Spousal consent document is required for approval.")
                    review_checklist['spousal_consent'] = False
            checklist = {**doc_checklist, **review_checklist}

            required_checks = {
                'title_deed': True,
                'official_search': True,
                'national_id': True,
                'kra_pin': True,
                'name_match': True,
                'seal_signature': True,
                'rates_clearance': True,
                'search_recency': True,
                'rent_clearance': task.plot.ownership_type == 'leasehold',
                'consent_transfer': task.plot.ownership_type == 'leasehold',
                'lcb_consent': task.plot.land_type == 'agricultural',
                'mutation_form': task.plot.is_subdivision,
                'plupa1': task.plot.is_subdivision,
                'spousal_consent': task.plot.spousal_consent,
            }
            if approved and not all(value for key, value in checklist.items() if required_checks.get(key, False)):
                messages.error(request, "All document checklist items must be confirmed before approval.")
                context = {
                    'task': task,
                    'plot': task.plot,
                    'page_title': f'Complete Task: {task.get_verification_type_display()}',
                    'expected_owner_name': expected_owner_name,
                    'form_data': form_data,
                    'registry_data': registry_data
                }
                return render(request, 'verification/admin/complete_task.html', context)
            extracted_summary = {
                **form_data,
                'expected_owner_name': expected_owner_name,
                'owner_name_matches': owner_name_matches,
                'id_matches_agent': id_matches,
                'ocr_results': ocr_results,
                'registry_data': registry_data
            }
            for doc_type, checked in doc_checklist.items():
                DocumentVerification.verify_document(
                    plot=task.plot,
                    doc_type=doc_type,
                    reviewer=request.user,
                    approved=approved and checked,
                    notes=json.dumps({
                        'review_notes': notes,
                        'extracted': extracted_summary
                    }),
                    task=task
                )

            review_metadata = {
                'checklist': checklist,
                'form_data': form_data,
                'registry_data': registry_data,
                'reviewed_by': request.user.username
            }
            task.review_metadata = review_metadata
            task.save(update_fields=['review_metadata'])
        
        if task.verification_type == 'document_review':
            status_label = 'approved' if approved else 'rejected'
            task = VerificationService.complete_document_review(
                task_id,
                request.user,
                status_label,
                notes,
                review_metadata=review_metadata if task.review_metadata else None
            )
        else:
            task = VerificationService.complete_task(task_id, request.user, notes, approved)
        
        if approved:
            messages.success(request, f"Task completed and approved!")
        else:
            messages.warning(request, f"Task completed with notes.")
        
        return redirect(f"{reverse('listings:dashboard_router')}?section=tasks")
    
    context = {
        'task': task,
        'plot': task.plot,
        'page_title': f'Complete Task: {task.get_verification_type_display()}',
        'expected_owner_name': expected_owner_name,
        'form_data': {},
        'registry_data': registry_data
    }
    
    return render(request, 'verification/admin/complete_task.html', context)

from notifications.notification_service import NotificationService

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

from verification.analytics_service import AnalyticsService

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
    sla_metrics = AnalyticsService.get_sla_metrics()
    
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
        'sla_metrics': sla_metrics,
        'days': days,
        'page_title': 'Analytics Dashboard',
        'marketplace_metrics': _marketplace_analytics_snapshot(days),
    }
    
    return render(request, 'verification/admin/analytics_dashboard.html', context)

@staff_member_required
def export_report(request):
    """Export verification report as CSV or PDF."""
    import csv
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from weasyprint import HTML
    
    report_type = request.GET.get('type', 'verification')
    days = int(request.GET.get('days', 30))
    export_format = (request.GET.get("format") or "csv").lower()

    if export_format == "pdf":
        context = {
            "report_type": report_type,
            "days": days,
            "generated_at": timezone.now(),
            "overview": AnalyticsService.get_verification_overview(days),
            "timeline": AnalyticsService.get_verification_timeline(days),
            "officer_performance": AnalyticsService.get_officer_performance(days),
            "county_stats": AnalyticsService.get_county_statistics(),
            "marketplace_metrics": _marketplace_analytics_snapshot(days),
        }
        html = render_to_string("verification/admin/analytics_report_pdf.html", context)
        pdf = HTML(string=html).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="agriplot_{report_type}_report.pdf"'
        return response
    
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

    elif report_type == 'marketplace':
        writer.writerow(['Metric', 'Value'])
        snapshot = _marketplace_analytics_snapshot(days)
        writer.writerow(['Active users today', snapshot['active_users_daily']])
        writer.writerow(['Active users this week', snapshot['active_users_weekly']])
        writer.writerow(['Fraud reports in period', snapshot['fraud_recent']])
        writer.writerow(['Revenue simulation sale total', snapshot['revenue_simulation'].get('sale_total') or 0])
        writer.writerow(['Revenue simulation annual lease total', snapshot['revenue_simulation'].get('lease_total') or 0])
    
    return response

from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from listings.models import Plot
from payments.models import PaymentRequest
from django.contrib.auth import get_user_model

User = get_user_model()

@staff_member_required
def admin_dashboard(request):
    return _workspace_redirect("overview")

def export_audit_logs_pdf(request):
    """Export audit logs as PDF using WeasyPrint"""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    from io import BytesIO
    from django.utils import timezone
    from django.db.models import Count
    
    # Get filtered queryset (same as main view)
    qs = AuditLog.objects.select_related('user').all()
    
    # Apply filters
    filters = []
    user_filter = request.GET.get('user')
    if user_filter:
        qs = qs.filter(
            Q(user__username__icontains=user_filter) |
            Q(user__email__icontains=user_filter)
        )
        filters.append(f"User: {user_filter}")
    
    action_filter = request.GET.get('action')
    if action_filter:
        qs = qs.filter(action=action_filter)
        filters.append(f"Action: {dict(AuditLog.ACTION_CHOICES).get(action_filter, action_filter)}")
    
    object_type_filter = request.GET.get('object_type')
    if object_type_filter:
        qs = qs.filter(object_type__icontains=object_type_filter)
        filters.append(f"Object: {object_type_filter}")
    
    severity_filter = request.GET.get('severity')
    if severity_filter:
        qs = qs.filter(severity=severity_filter)
        filters.append(f"Severity: {severity_filter.upper()}")
    
    start_date = request.GET.get('start_date')
    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
        filters.append(f"From: {start_date}")
    
    end_date = request.GET.get('end_date')
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)
        filters.append(f"To: {end_date}")
    
    # Limit to 1000 records for PDF performance
    logs = qs[:1000]
    
    # Calculate stats
    unique_users = qs.values('user').distinct().count()
    unique_ips = qs.exclude(ip_address__isnull=True).values('ip_address').distinct().count()
    unique_actions = qs.values('action').distinct().count()
    
    context = {
        'logs': logs,
        'total_count': qs.count(),
        'unique_users': unique_users,
        'unique_ips': unique_ips,
        'unique_actions': unique_actions,
        'export_date': timezone.now(),
        'request': request,
        'filter_summary': filters if filters else None,
    }
    
    # Render HTML template
    html_string = render_to_string('verification/admin/audit_logs_pdf.html', context)
    
    # Generate PDF
    font_config = FontConfiguration()
    pdf_file = BytesIO()
    
    HTML(string=html_string).write_pdf(
        pdf_file,
        font_config=font_config,
        presentational_hints=True
    )
    
    pdf_file.seek(0)
    
    # Create response
    response = HttpResponse(pdf_file.read(), content_type='application/pdf')
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    response['Content-Disposition'] = f'attachment; filename="audit_logs_{timestamp}.pdf"'
    response['Content-Length'] = pdf_file.tell()
    
    return response
