"""
AgriPlot utilities: audit logging (Q8) and pricing suggestions (Q6).
"""

def get_client_ip(request):
    """Extract client IP from request."""
    if not request:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def get_user_agent(request):
    """Extract User-Agent string (truncated for DB)."""
    if not request:
        return ''
    return (request.META.get('HTTP_USER_AGENT') or '')[:500]


def log_audit(request, action, object_type=None, object_id=None, extra=None):
    """
    Log a sensitive action for compliance (Q8 - ZTA/CIA).
    Call from views: log_audit(request, 'create_plot', object_type='Plot', object_id=plot.id)
    """
    from .models import AuditLog
    user = request.user if request and getattr(request, 'user', None) and request.user.is_authenticated else None
    AuditLog.objects.create(
        user=user,
        action=action,
        object_type=object_type or '',
        object_id=object_id,
        extra=extra or {},
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )


def suggest_price(plot):
    """
    Suggest sale price based on comparables (Q6).
    Returns dict: suggested_price, min_price, max_price, comparable_count, explanation.
    """
    recommendation = plot.pricing_recommendation("sale")
    if not recommendation:
        return {
            'suggested_price': None,
            'min_price': None,
            'max_price': None,
            'comparable_count': 0,
            'explanation': 'No comparables or regional guide found yet.',
        }

    comparable_snapshot = recommendation.get("comparable_snapshot") or {}
    return {
        'suggested_price': recommendation['suggested_total'],
        'min_price': recommendation.get('price_range_min'),
        'max_price': recommendation.get('price_range_max'),
        'comparable_count': comparable_snapshot.get('sample_size', 0),
        'explanation': recommendation['explanation'],
    }
