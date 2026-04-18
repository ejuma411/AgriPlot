from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import AuditLog

@login_required
def test_audit_log(request):
    """Test view to verify audit logging is working"""
    
    # Create a test log entry
    log = AuditLog.objects.create(
        user=request.user,
        action='test_action',
        severity='info',
        object_type='Test',
        extra={'test': True, 'message': 'Audit logging is working!'}
    )
    
    return JsonResponse({
        'status': 'success',
        'message': 'Audit log created',
        'log_id': log.id,
        'hash_signature': log.hash_signature
    })
