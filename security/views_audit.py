"""
Audit Log Views for Security & Compliance
Provides comprehensive audit trail viewing, filtering, and export capabilities
"""

from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Q, Count, Min, Max
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .models import AuditLog
import csv
from io import StringIO
import json


@staff_member_required
def audit_log_view(request):
    """
    View audit logs with filtering, pagination, and export options.
    Only accessible by staff/admin users.
    """
    # Base queryset
    logs = AuditLog.objects.select_related('user').all()
    
    # Store filter summary for display
    filter_summary = []
    
    # Apply filters
    # User filter
    user_filter = request.GET.get('user')
    if user_filter:
        logs = logs.filter(
            Q(user__username__icontains=user_filter) |
            Q(user__email__icontains=user_filter) |
            Q(user__first_name__icontains=user_filter) |
            Q(user__last_name__icontains=user_filter)
        )
        filter_summary.append(f"User: {user_filter}")
    
    # Action filter
    action_filter = request.GET.get('action')
    if action_filter:
        logs = logs.filter(action=action_filter)
        filter_summary.append(f"Action: {dict(AuditLog.ACTION_CHOICES).get(action_filter, action_filter)}")
    
    # Severity filter
    severity_filter = request.GET.get('severity')
    if severity_filter:
        logs = logs.filter(severity=severity_filter)
        filter_summary.append(f"Severity: {severity_filter.upper()}")
    
    # Object type filter
    object_type_filter = request.GET.get('object_type')
    if object_type_filter:
        logs = logs.filter(object_type__icontains=object_type_filter)
        filter_summary.append(f"Object: {object_type_filter}")
    
    # IP Address filter
    ip_filter = request.GET.get('ip_address')
    if ip_filter:
        logs = logs.filter(ip_address__icontains=ip_filter)
        filter_summary.append(f"IP: {ip_filter}")
    
    # Date range filters
    start_date = request.GET.get('start_date')
    if start_date:
        logs = logs.filter(created_at__date__gte=start_date)
        filter_summary.append(f"From: {start_date}")
    
    end_date = request.GET.get('end_date')
    if end_date:
        logs = logs.filter(created_at__date__lte=end_date)
        filter_summary.append(f"To: {end_date}")
    
    # Check if export requested
    if request.GET.get('export') == 'csv':
        return export_audit_csv(logs, filter_summary)
    
    if request.GET.get('export') == 'json':
        return export_audit_json(logs)
    
    # Get date range for stats
    first_log = logs.order_by('created_at').first()
    last_log = logs.order_by('created_at').last()
    
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
    
    # Get unique actions and object types for filter dropdowns
    unique_actions = AuditLog.objects.values_list('action', flat=True).distinct()
    action_choices = [(action, dict(AuditLog.ACTION_CHOICES).get(action, action)) for action in unique_actions]
    
    unique_object_types = AuditLog.objects.exclude(object_type='').values_list('object_type', flat=True).distinct()
    
    # Verify chain integrity
    is_chain_valid, chain_message = AuditLog.verify_chain()
    
    context = {
        'logs': logs_page,
        'total_count': logs.count(),
        'display_count': len(logs_page),
        'first_log': first_log,
        'last_log': last_log,
        'export_date': timezone.now(),
        'filter_summary': filter_summary,
        'action_choices': action_choices,
        'object_types': sorted(unique_object_types),
        'severity_choices': AuditLog.SEVERITY_CHOICES,
        'page': page,
        'page_size': page_size,
        'has_previous': logs_page.has_previous(),
        'has_next': logs_page.has_next(),
        'previous_page_number': logs_page.previous_page_number() if logs_page.has_previous() else None,
        'next_page_number': logs_page.next_page_number() if logs_page.has_next() else None,
        'num_pages': paginator.num_pages,
        'chain_valid': is_chain_valid,
        'chain_message': chain_message,
    }
    
    return render(request, 'verification/admin/audit_log.html', context)


def export_audit_csv(logs, filter_summary=None):
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
    
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    response['Content-Disposition'] = f'attachment; filename="audit_log_{timestamp}.csv"'
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
    
    response = HttpResponse(json.dumps(data, indent=2), content_type='application/json')
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    response['Content-Disposition'] = f'attachment; filename="audit_log_{timestamp}.json"'
    return response


@staff_member_required
def audit_log_verify(request):
    """Verify the integrity of the audit log chain"""
    is_valid, message = AuditLog.verify_chain()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'valid': is_valid,
            'message': message,
            'total_logs': AuditLog.objects.count(),
            'last_verified': timezone.now().isoformat(),
        })
    
    return render(request, 'verification/admin/audit_logs.html', {
        'is_valid': is_valid,
        'message': message,
        'total_logs': AuditLog.objects.count(),
        'export_date': timezone.now(),
    })


@staff_member_required
def audit_log_stats(request):
    """Get audit log statistics for dashboard"""
    total_logs = AuditLog.objects.count()
    
    # Count by action
    action_stats = AuditLog.objects.values('action').annotate(count=Count('id')).order_by('-count')
    
    # Count by severity
    severity_stats = AuditLog.objects.values('severity').annotate(count=Count('id'))
    
    # Count by day (last 30 days)
    from datetime import timedelta
    thirty_days_ago = timezone.now() - timedelta(days=30)
    daily_stats = AuditLog.objects.filter(
        created_at__gte=thirty_days_ago
    ).extra(
        {'day': "date_trunc('day', created_at)"}
    ).values('day').annotate(count=Count('id')).order_by('-day')
    
    return JsonResponse({
        'total_logs': total_logs,
        'action_stats': list(action_stats),
        'severity_stats': list(severity_stats),
        'daily_stats': list(daily_stats),
    })
