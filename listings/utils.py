"""
AgriPlot utilities: audit logging (Q8) and pricing suggestions (Q6).
"""
from django.db.models import Avg
from django.utils import timezone

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
    from .models import Plot, PriceComparable, PricingSuggestion
    from decimal import Decimal

    # Prefer comparables from DB; fallback to verified plots in same area/soil
    location_prefix = (plot.location or '').split(',')[0].strip() if plot.location else None
    comparables = PriceComparable.objects.filter(
        verified=True
    ).filter(
        location__icontains=location_prefix
    ) if location_prefix else PriceComparable.objects.filter(verified=True)

    if comparables.exists():
        avg_per_acre = comparables.aggregate(avg=Avg('price_per_acre'))['avg']
        if avg_per_acre and plot.area and plot.area > 0:
            suggested = Decimal(str(plot.area)) * avg_per_acre
            min_p = suggested * Decimal('0.85')
            max_p = suggested * Decimal('1.15')
            PricingSuggestion.objects.create(
                plot=plot,
                suggested_price=suggested,
                price_range_min=min_p,
                price_range_max=max_p,
                methodology='Sales comparison (PriceComparable)',
                comparable_plots_used=comparables.count(),
                explanation=f'Based on {comparables.count()} comparable sale(s) near {location_prefix or "this area"}.',
            )
            return {
                'suggested_price': suggested,
                'min_price': min_p,
                'max_price': max_p,
                'comparable_count': comparables.count(),
                'explanation': f'Based on {comparables.count()} comparable sale(s).',
            }

    # Fallback: same location/soil from verified plots (use sale_price or price)
    fallback = Plot.objects.filter(
        listing_type__in=['sale', 'both'],
        area__gt=0,
    ).exclude(pk=plot.pk)
    if location_prefix:
        fallback = fallback.filter(location__icontains=location_prefix)
    if plot.soil_type:
        fallback = fallback.filter(soil_type=plot.soil_type)
    fallback = fallback[:20]

    if fallback.exists():
        # Average price per acre from similar plots
        from django.db.models import F
        fallback = fallback.annotate(ppa=F('sale_price') / F('area')).filter(ppa__gt=0)
        avg_ppa = fallback.aggregate(avg=Avg('ppa'))['avg']
        if avg_ppa and plot.area and plot.area > 0:
            suggested = Decimal(str(plot.area)) * avg_ppa
            min_p = suggested * Decimal('0.85')
            max_p = suggested * Decimal('1.15')
            PricingSuggestion.objects.create(
                plot=plot,
                suggested_price=suggested,
                price_range_min=min_p,
                price_range_max=max_p,
                methodology='Similar listings (same area/soil)',
                comparable_plots_used=fallback.count(),
                explanation=f'Based on {fallback.count()} similar listing(s).',
            )
            return {
                'suggested_price': suggested,
                'min_price': min_p,
                'max_price': max_p,
                'comparable_count': fallback.count(),
                'explanation': f'Based on {fallback.count()} similar listing(s).',
            }

    return {
        'suggested_price': None,
        'min_price': None,
        'max_price': None,
        'comparable_count': 0,
        'explanation': 'No comparables found. Enter your desired price.',
    }
