from django.shortcuts import render
"""
Security Views for AgriPlot
Handles screenshot protection, audit logs, security monitoring, and compliance features
"""

import json
import csv
import logging
from io import StringIO
from datetime import datetime, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse, Http404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count, Sum, Avg
from django.contrib import messages
from django.template.loader import render_to_string
from django.conf import settings
from django.core.mail import send_mail

from notifications.services.sms_service import SMSService

from .models import (
    AuditLog, 
    ImpersonationDetection, 
    PhoneEmailVerification,
    PhoneOTP,
    EmailOTP,
    TwoFactorSettings,
    TwoFactorBackupCode
)
from accounts.models import Profile
from verification.services.ocr_service import DocumentOCRService

# Import WeasyPrint for PDF generation
try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


logger = logging.getLogger(__name__)


# ============================================================
# SCREENSHOT PROTECTION VIEWS
# ============================================================

@login_required
def log_screenshot_attempt(request):
    """Log screenshot attempts on sensitive pages for security auditing"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            page_url = data.get('page', request.META.get('HTTP_REFERER', ''))
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Log the screenshot attempt
            AuditLog.log_action(
                request=request,
                action='screenshot_attempt',
                severity=AuditLog.SEVERITY_WARNING,
                extra={
                    'page': page_url,
                    'user_agent': user_agent,
                    'method': 'keyboard_shortcut',
                },
                metadata={'screenshot_attempt': True}
            )
            
            # Update impersonation detection if multiple attempts
            today = timezone.now().date()
            recent_attempts = AuditLog.objects.filter(
                user=request.user,
                action='screenshot_attempt',
                created_at__date=today
            ).count()
            
            if recent_attempts > 5:
                # Create alert for multiple screenshot attempts
                ImpersonationDetection.objects.create(
                    user=request.user,
                    alert_type=ImpersonationDetection.ALERT_SUSPICIOUS_LOGIN,
                    severity=ImpersonationDetection.SEVERITY_MEDIUM,
                    description=f"User made {recent_attempts} screenshot attempts on sensitive pages today",
                    evidence={'attempts': recent_attempts, 'pages': [page_url]}
                )
            
            return JsonResponse({'status': 'logged', 'attempts': recent_attempts})
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


# ============================================================
# AUDIT LOG VIEWS
# ============================================================

@staff_member_required
def audit_log_view(request):
    """View audit logs with filtering and pagination"""
    logs = AuditLog.objects.select_related('user').all()
    
    # Apply filters
    filter_summary = []
    
    user_filter = request.GET.get('user')
    if user_filter:
        logs = logs.filter(
            Q(user__username__icontains=user_filter) |
            Q(user__email__icontains=user_filter) |
            Q(user__first_name__icontains=user_filter) |
            Q(user__last_name__icontains=user_filter)
        )
        filter_summary.append(f"User: {user_filter}")
    
    action_filter = request.GET.get('action')
    if action_filter:
        logs = logs.filter(action=action_filter)
        filter_summary.append(f"Action: {dict(AuditLog.ACTION_CHOICES).get(action_filter, action_filter)}")
    
    severity_filter = request.GET.get('severity')
    if severity_filter:
        logs = logs.filter(severity=severity_filter)
        filter_summary.append(f"Severity: {severity_filter.upper()}")
    
    object_type_filter = request.GET.get('object_type')
    if object_type_filter:
        logs = logs.filter(object_type__icontains=object_type_filter)
        filter_summary.append(f"Object: {object_type_filter}")
    
    ip_filter = request.GET.get('ip_address')
    if ip_filter:
        logs = logs.filter(ip_address__icontains=ip_filter)
        filter_summary.append(f"IP: {ip_filter}")
    
    start_date = request.GET.get('start_date')
    if start_date:
        logs = logs.filter(created_at__date__gte=start_date)
        filter_summary.append(f"From: {start_date}")
    
    end_date = request.GET.get('end_date')
    if end_date:
        logs = logs.filter(created_at__date__lte=end_date)
        filter_summary.append(f"To: {end_date}")
    
    # Calculate statistics
    unique_users = logs.values('user').distinct().count()
    unique_ips = logs.exclude(ip_address__isnull=True).values('ip_address').distinct().count()
    unique_actions = logs.values('action').distinct().count()
    
    # Export to CSV if requested
    if request.GET.get('export') == 'csv':
        return export_audit_csv(logs)
    
    if request.GET.get('export') == 'json':
        return export_audit_json(logs)
    
    # Get unique actions and object types for filters
    action_choices = []
    for action in AuditLog.ACTION_CHOICES:
        if logs.filter(action=action[0]).exists():
            action_choices.append(action)
    
    object_types = logs.exclude(object_type='').values_list('object_type', flat=True).distinct()
    
    # Pagination
    page_size = request.GET.get('page_size', 100)
    try:
        page_size = int(page_size)
        if page_size > 500:
            page_size = 500
    except ValueError:
        page_size = 100
    
    paginator = Paginator(logs, page_size)
    page = request.GET.get('page', 1)
    
    try:
        logs_page = paginator.page(page)
    except PageNotAnInteger:
        logs_page = paginator.page(1)
    except EmptyPage:
        logs_page = paginator.page(paginator.num_pages)
    
    context = {
        'logs': logs_page,
        'total_count': logs.count(),
        'unique_users': unique_users,
        'unique_ips': unique_ips,
        'unique_actions': unique_actions,
        'action_choices': action_choices,
        'object_types': sorted(object_types),
        'filter_summary': filter_summary,
        'page': page,
        'page_size': page_size,
        'has_previous': logs_page.has_previous(),
        'has_next': logs_page.has_next(),
        'previous_page_number': logs_page.previous_page_number() if logs_page.has_previous() else None,
        'next_page_number': logs_page.next_page_number() if logs_page.has_next() else None,
        'num_pages': paginator.num_pages,
    }
    
    return render(request, 'security/audit_log.html', context)


def export_audit_csv(logs):
    """Export audit logs to CSV format"""
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Timestamp', 'User ID', 'Username', 'Email', 'Action', 'Severity',
        'Object Type', 'Object ID', 'Object Name', 'IP Address', 
        'User Agent', 'Request Path', 'Request Method', 'Old Data', 
        'New Data', 'Changes', 'Extra Data', 'Hash Signature', 'Previous Hash'
    ])
    
    # Write data
    for log in logs:
        writer.writerow([
            log.created_at.isoformat(),
            log.user_id if log.user_id else 'System',
            log.user.username if log.user else 'System',
            log.user.email if log.user else '',
            log.action,
            log.severity,
            log.object_type or '',
            log.object_id or '',
            log.object_repr or '',
            log.ip_address or '',
            log.user_agent or '',
            log.request_path or '',
            log.request_method or '',
            json.dumps(log.old_data) if log.old_data else '',
            json.dumps(log.new_data) if log.new_data else '',
            json.dumps(log.changes) if log.changes else '',
            json.dumps(log.extra) if log.extra else '',
            log.hash_signature,
            log.previous_hash or '',
        ])
    
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="audit_logs_{timestamp}.csv"'
    return response


def export_audit_json(logs):
    """Export audit logs to JSON format"""
    data = []
    for log in logs:
        data.append({
            'timestamp': log.created_at.isoformat(),
            'user': {
                'id': log.user_id,
                'username': log.user.username if log.user else None,
                'email': log.user.email if log.user else None,
            },
            'action': log.action,
            'severity': log.severity,
            'object': {
                'type': log.object_type,
                'id': log.object_id,
                'name': log.object_repr,
            },
            'ip_address': log.ip_address,
            'user_agent': log.user_agent,
            'request_path': log.request_path,
            'request_method': log.request_method,
            'old_data': log.old_data,
            'new_data': log.new_data,
            'changes': log.changes,
            'extra': log.extra,
            'hash_signature': log.hash_signature,
            'previous_hash': log.previous_hash,
        })
    
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    response = HttpResponse(json.dumps(data, indent=2), content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="audit_logs_{timestamp}.json"'
    return response


@staff_member_required
def audit_log_verify(request):
    """Verify the integrity of the audit log chain"""
    is_valid, message = AuditLog.verify_chain()
    
    context = {
        'is_valid': is_valid,
        'message': message,
        'total_logs': AuditLog.objects.count(),
        'export_date': timezone.now(),
    }
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'valid': is_valid,
            'message': message,
            'total_logs': context['total_logs'],
        })
    
    return render(request, 'security/audit_log_verify.html', context)


@staff_member_required
def export_audit_pdf(request):
    """Export audit logs as PDF using WeasyPrint"""
    if not WEASYPRINT_AVAILABLE:
        messages.error(request, "PDF export is not available. Please install WeasyPrint.")
        return redirect('security:audit_log')
    
    # Get filtered queryset
    logs = AuditLog.objects.select_related('user').all()
    
    # Apply filters (same as main view)
    user_filter = request.GET.get('user')
    if user_filter:
        logs = logs.filter(user__username__icontains=user_filter)
    
    action_filter = request.GET.get('action')
    if action_filter:
        logs = logs.filter(action=action_filter)
    
    object_type_filter = request.GET.get('object_type')
    if object_type_filter:
        logs = logs.filter(object_type__icontains=object_type_filter)
    
    start_date = request.GET.get('start_date')
    if start_date:
        logs = logs.filter(created_at__date__gte=start_date)
    
    end_date = request.GET.get('end_date')
    if end_date:
        logs = logs.filter(created_at__date__lte=end_date)
    
    # Limit to 1000 records for PDF performance
    logs = logs[:1000]
    
    # Calculate statistics
    unique_users = logs.values('user').distinct().count()
    unique_ips = logs.exclude(ip_address__isnull=True).values('ip_address').distinct().count()
    unique_actions = logs.values('action').distinct().count()
    
    context = {
        'logs': logs,
        'total_count': logs.count(),
        'unique_users': unique_users,
        'unique_ips': unique_ips,
        'unique_actions': unique_actions,
        'export_date': timezone.now(),
        'request': request,
    }
    
    # Render HTML template
    html_string = render_to_string('security/audit_log_pdf.html', context)
    
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
    return response


# ============================================================
# SECURITY DASHBOARD VIEWS
# ============================================================

@staff_member_required
def security_dashboard(request):
    """Security dashboard showing alerts, statistics, and system health"""
    return redirect("/dashboard/?section=audit")


# ============================================================
# IMPERSONATION DETECTION VIEWS
# ============================================================

@staff_member_required
def impersonation_alerts(request):
    """View impersonation detection alerts"""
    alerts = ImpersonationDetection.objects.select_related('user', 'resolved_by').all()
    
    # Apply filters
    severity_filter = request.GET.get('severity')
    if severity_filter:
        alerts = alerts.filter(severity=severity_filter)
    
    status_filter = request.GET.get('status')
    if status_filter:
        alerts = alerts.filter(status=status_filter)
    
    user_filter = request.GET.get('user')
    if user_filter:
        alerts = alerts.filter(user__username__icontains=user_filter)
    
    # Pagination
    paginator = Paginator(alerts, 50)
    page = request.GET.get('page', 1)
    
    try:
        alerts_page = paginator.page(page)
    except PageNotAnInteger:
        alerts_page = paginator.page(1)
    except EmptyPage:
        alerts_page = paginator.page(paginator.num_pages)
    
    context = {
        'alerts': alerts_page,
        'total_count': alerts.count(),
        'severity_choices': ImpersonationDetection.SEVERITY_CHOICES,
        'status_choices': ImpersonationDetection.STATUS_CHOICES,
        'page': page,
        'num_pages': paginator.num_pages,
    }
    
    return render(request, 'security/impersonation_alerts.html', context)


@staff_member_required
@require_http_methods(["POST"])
def resolve_alert(request, alert_id):
    """Mark an impersonation alert as resolved"""
    alert = get_object_or_404(ImpersonationDetection, id=alert_id)
    alert.status = ImpersonationDetection.STATUS_RESOLVED
    alert.resolved_by = request.user
    alert.resolved_at = timezone.now()
    alert.save()
    
    messages.success(request, f"Alert #{alert.id} marked as resolved.")
    return redirect('security:impersonation_alerts')


# ============================================================
# 2FA MANAGEMENT VIEWS
# ============================================================

@login_required
def two_factor_setup(request):
    """Setup two-factor authentication for the user"""
    profile = get_object_or_404(Profile, user=request.user)
    settings, created = TwoFactorSettings.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Handle 2FA setup logic
        # This would integrate with your 2FA library
        pass
    
    context = {
        'profile': profile,
        'settings': settings,
        'has_2fa': settings.is_enabled,
    }
    
    return render(request, 'security/two_factor_setup.html', context)


@login_required
def two_factor_verify(request):
    """Verify two-factor authentication code"""
    if request.method == 'POST':
        # Handle 2FA verification
        pass
    
    return render(request, 'security/two_factor_verify.html')


# ============================================================
# VERIFICATION CODE VIEWS
# ============================================================

@login_required
def send_verification_code(request):
    """Send verification code to user's phone or email"""
    if request.method == 'POST':
        method = request.POST.get('method', 'sms')
        phone = request.POST.get('phone')
        email = request.POST.get('email')
        
        # Generate random OTP
        import random
        otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        
        if method == 'sms' and phone:
            # Send SMS via OpenSMS
            PhoneOTP.objects.create(
                user=request.user,
                phone=phone,
                otp=otp,
                purpose='verification',
                expires_at=timezone.now() + timedelta(minutes=10)
            )
            sms_service = SMSService()
            sms_result = sms_service.send_otp(phone, otp)
            if sms_result.get("success"):
                messages.success(request, f"Verification code sent to {phone}")
            else:
                messages.error(request, f"Failed to send SMS: {sms_result.get('error')}")
            
        elif method == 'email' and email:
            EmailOTP.objects.create(
                user=request.user,
                email=email,
                otp=otp,
                purpose='verification',
                expires_at=timezone.now() + timedelta(minutes=10)
            )
            
            subject = "AgriPlot Verification Code"
            message = f"Your AgriPlot verification code is: {otp}. Valid for 10 minutes."
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [email]
            
            try:
                send_mail(subject, message, from_email, recipient_list)
                messages.success(request, f"Verification code sent to {email}")
            except Exception as e:
                logger.error(f"Failed to send email to {email}: {e}")
                messages.error(request, "Failed to send verification email.")
        
        return redirect(request.META.get('HTTP_REFERER', '/'))
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def verify_code(request):
    """Verify the OTP code"""
    if request.method == 'POST':
        code = request.POST.get('code')
        method = request.POST.get('method', 'sms')
        
        if method == 'sms':
            otp = PhoneOTP.objects.filter(
                user=request.user,
                otp=code,
                is_verified=False,
                expires_at__gt=timezone.now()
            ).first()
        else:
            otp = EmailOTP.objects.filter(
                user=request.user,
                otp=code,
                is_verified=False,
                expires_at__gt=timezone.now()
            ).first()
        
        if otp:
            otp.is_verified = True
            otp.save()
            
            # Update verification status
            verification, _ = PhoneEmailVerification.objects.get_or_create(user=request.user)
            if method == 'sms':
                verification.phone_verified = True
                verification.phone_verified_at = timezone.now()
            else:
                verification.email_verified = True
                verification.email_verified_at = timezone.now()
            verification.save()
            
            messages.success(request, "Verification successful!")
            return JsonResponse({'success': True, 'message': 'Verification successful'})
        else:
            return JsonResponse({'success': False, 'message': 'Invalid or expired code'}, status=400)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


# ============================================================
# SECURITY HEALTH CHECK
# ============================================================

@staff_member_required
def security_health_check(request):
    """Check system security health status"""
    ocr_health = DocumentOCRService.health_status()
    if ocr_health.get('ready'):
        logger.info(
            "OCR ready: pytesseract=%s, tesseract=%s, pdftoppm=%s",
            ocr_health.get('pytesseract_available'),
            ocr_health.get('tesseract_version'),
            ocr_health.get('pdftoppm_available'),
        )
    else:
        logger.warning(
            "OCR degraded: %s",
            ocr_health.get('error') or 'unknown OCR readiness issue',
        )

    health_status = {
        'audit_log_integrity': AuditLog.verify_chain()[0],
        'total_audit_logs': AuditLog.objects.count(),
        'total_alerts': ImpersonationDetection.objects.count(),
        'unresolved_alerts': ImpersonationDetection.objects.exclude(status='resolved').count(),
        'recent_screenshot_attempts': AuditLog.objects.filter(
            action='screenshot_attempt',
            created_at__gte=timezone.now() - timedelta(days=7)
        ).count(),
        'recent_failed_logins': AuditLog.objects.filter(
            action='failed_login',
            created_at__gte=timezone.now() - timedelta(days=7)
        ).count(),
        'two_factor_adoption': TwoFactorSettings.objects.filter(is_enabled=True).count(),
        'ocr': ocr_health,
    }
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(health_status)
    
    return render(request, 'security/health_check.html', {'health': health_status})


# ============================================================
# SECURITY REPORTS
# ============================================================

@staff_member_required
def security_report(request):
    """Generate comprehensive security report"""
    
    # Date range
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)
    
    # Summary statistics
    total_actions = AuditLog.objects.filter(created_at__gte=start_date).count()
    
    # Actions by type
    action_breakdown = AuditLog.objects.filter(
        created_at__gte=start_date
    ).values('action').annotate(count=Count('id')).order_by('-count')[:10]
    
    # Daily activity
    daily_activity = AuditLog.objects.filter(
        created_at__gte=start_date
    ).extra(
        {'day': "date_trunc('day', created_at)"}
    ).values('day').annotate(count=Count('id')).order_by('day')
    
    # Severity breakdown
    severity_breakdown = AuditLog.objects.filter(
        created_at__gte=start_date
    ).values('severity').annotate(count=Count('id'))
    
    # Top users by activity
    top_users = AuditLog.objects.filter(
        created_at__gte=start_date,
        user__isnull=False
    ).values('user__username').annotate(count=Count('id')).order_by('-count')[:10]
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'total_actions': total_actions,
        'action_breakdown': action_breakdown,
        'daily_activity': daily_activity,
        'severity_breakdown': severity_breakdown,
        'top_users': top_users,
        'export_date': timezone.now(),
    }
    
    if request.GET.get('format') == 'pdf' and WEASYPRINT_AVAILABLE:
        # Generate PDF report
        html_string = render_to_string('security/security_report_pdf.html', context)
        font_config = FontConfiguration()
        pdf_file = BytesIO()
        
        HTML(string=html_string).write_pdf(pdf_file, font_config=font_config)
        pdf_file.seek(0)
        
        response = HttpResponse(pdf_file.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="security_report_{timezone.now().strftime("%Y%m%d")}.pdf"'
        return response
    
    return render(request, 'security/security_report.html', context)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def is_staff_or_admin(user):
    """Check if user is staff or admin"""
    return user.is_staff or user.is_superuser


# ============================================================
# TEST VIEW FOR AUDIT LOGGING
# ============================================================

@login_required
def test_audit_log(request):
    """Test view to verify audit logging is working"""
    from .models import AuditLog
    from django.http import JsonResponse
    
    # Create a test log entry
    log = AuditLog.objects.create(
        user=request.user,
        action='test_action',
        severity='info',
        object_type='Test',
        extra={'test': True, 'message': 'Audit logging is working!'},
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
        request_path=request.path,
        request_method=request.method,
    )
    
    return JsonResponse({
        'status': 'success',
        'message': 'Audit log created successfully',
        'log_id': log.id,
        'hash_signature': log.hash_signature[:16] + '...',
        'total_logs': AuditLog.objects.count()
    })
