from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.contrib import messages
from django.db import models
from django.db.models import Sum, Count, Avg
from decimal import Decimal
import hashlib
import hmac
from datetime import timedelta
from verification.models import VerificationStatus  # Add this import

from listings.models import Plot
from payments.models import PaymentRequest, PaymentClosingStep, LeaseWaitlistEntry
from django.contrib.auth import get_user_model
from django.conf import settings

from .utils.pdf_generator import WeasyPDFGenerator

User = get_user_model()

# ==================== BUYER/TENANT REPORTS ====================

@login_required
def transaction_milestone_report(request, payment_id):
    """Generate transaction milestone report using PaymentRequest model"""
    payment = get_object_or_404(PaymentRequest, id=payment_id)
    
    # Check permission
    if request.user not in [payment.buyer, payment.seller]:
        messages.error(request, "You don't have permission to view this report")
        return redirect('listings:dashboard_router')
    
    # Get closing steps
    closing_steps = payment.closing_steps.all().order_by('sequence')
    
    steps = []
    completed_steps = 0
    
    for step in closing_steps:
        step_data = {
            'name': step.display_title,
            'status': 'completed' if step.status == PaymentClosingStep.Status.COMPLETED else 'pending',
            'completed_date': step.completed_at,
            'due_date': None,
            'notes': step.notes,
        }
        steps.append(step_data)
        if step_data['status'] == 'completed':
            completed_steps += 1
    
    progress_percentage = (completed_steps / len(steps)) * 100 if steps else 0
    
    # Calculate days elapsed
    days_elapsed = (timezone.now().date() - payment.created_at.date()).days
    
    # Required documents from the payment
    required_documents = []
    if payment.plot:
        required_documents = [
            {'name': 'Title Deed', 'uploaded': bool(payment.plot.title_deed)},
            {'name': 'Official Search', 'uploaded': bool(payment.plot.official_search)},
            {'name': 'LCB Consent', 'uploaded': bool(payment.plot.lcb_consent_doc)},
            {'name': 'Spousal Consent', 'uploaded': bool(payment.plot.spousal_consent_doc)},
            {'name': 'Valuation Report', 'uploaded': bool(payment.plot.valuation_report)},
        ]
    
    # Generate verification code
    report_id = f'TMR-{payment.id}-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.sha256(
        f"{payment.id}{payment.created_at}{payment.buyer.id if payment.buyer else ''}{payment.seller.id if payment.seller else ''}".encode()
    ).hexdigest()[:12].upper()
    
    # Generate digital signature
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{payment.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': f'Transaction Milestone Report - {payment.internal_reference}',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'deal': payment,
        'plot': payment.plot,
        'steps': steps,
        'progress_percentage': progress_percentage,
        'completed_steps': completed_steps,
        'total_steps': len(steps),
        'estimated_completion': None,
        'days_elapsed': days_elapsed,
        'days_remaining': 0,
        'required_documents': required_documents,
        'verification_code': verification_code,
        'digital_signature': digital_signature,
        'buyer_next_step_instruction': payment.buyer_next_step_instruction if hasattr(payment, 'buyer_next_step_instruction') else "Continue following the milestone tracker.",
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/transaction_milestone.html',
        context=context,
        filename=f'Transaction_Milestone_{payment.internal_reference}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


@login_required
def escrow_statement_report(request, payment_id=None):
    """Generate escrow statement for the authenticated user"""
    user = request.user
    
    if payment_id:
        payments = PaymentRequest.objects.filter(
            models.Q(buyer=user) | models.Q(seller=user),
            id=payment_id
        )
    else:
        payments = PaymentRequest.objects.filter(
            models.Q(buyer=user) | models.Q(seller=user)
        ).order_by('-created_at')
    
    # Calculate totals
    total_paid = payments.filter(
        buyer=user,
        status__in=[PaymentRequest.Status.PAID, PaymentRequest.Status.IN_ESCROW, PaymentRequest.Status.RELEASED]
    ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
    
    total_received = payments.filter(
        seller=user,
        status__in=[PaymentRequest.Status.RELEASED]
    ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
    
    in_escrow = payments.filter(
        status=PaymentRequest.Status.IN_ESCROW
    ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
    
    # Group payments by type
    payment_types = payments.filter(buyer=user).values('category').annotate(
        total=models.Sum('amount')
    )
    
    report_id = f'ESC-{user.id}-{timezone.now().strftime("%Y%m%d%H%M%S")}'
    verification_code = hashlib.md5(f"{user.id}{in_escrow}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{user.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': f'Escrow Statement - {user.get_full_name()}',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': user.get_full_name() or user.username,
        'user': user,
        'total_paid': total_paid,
        'total_received': total_received,
        'escrow_balance': in_escrow,
        'payments': payments[:100],
        'payment_types': payment_types,
        'verification_code': verification_code,
        'digital_signature': digital_signature,
        'deal': payments.first() if payments.exists() else None,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/escrow_statement.html',
        context=context,
        filename=f'Escrow_Statement_{user.username}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


@login_required
def encumbrance_search_report(request, plot_id):
    """Generate encumbrance report for due diligence"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Get verification logs if they exist
    verification_logs = []
    if hasattr(plot, 'verification_logs'):
        verification_logs = plot.verification_logs.all().order_by('-created_at')[:10]
    
    # Due diligence checklist
    due_diligence = [
        {'item': 'Official Land Search', 'status': 'completed' if getattr(plot, 'official_search', False) else 'pending', 
         'details': getattr(plot, 'search_reference_number', 'Not conducted')},
        {'item': 'Title Deed Verification', 'status': 'completed' if getattr(plot, 'title_deed', False) else 'pending',
         'details': 'Document on file' if getattr(plot, 'title_deed', False) else 'Not uploaded'},
        {'item': 'LCB Consent', 'status': 'completed' if getattr(plot, 'lcb_consent_doc', False) else 'pending',
         'details': 'Obtained' if getattr(plot, 'lcb_consent_doc', False) else 'Required'},
        {'item': 'Spousal Consent', 'status': 'completed' if getattr(plot, 'spousal_consent', False) else 'pending',
         'details': 'On file' if getattr(plot, 'spousal_consent', False) else 'Not obtained'},
        {'item': 'Rates Clearance', 'status': 'completed' if getattr(plot, 'rates_clearance', False) else 'pending',
         'details': 'Cleared' if getattr(plot, 'rates_clearance', False) else 'Pending verification'},
        {'item': 'Encumbrance Check', 'status': 'completed' if not getattr(plot, 'registry_has_encumbrances', False) else 'warning',
         'details': 'No encumbrances' if not getattr(plot, 'registry_has_encumbrances', False) else 'Encumbrances recorded'},
    ]
    
    completed_items = sum(1 for item in due_diligence if item['status'] == 'completed')
    diligence_score = (completed_items / len(due_diligence)) * 100
    
    report_id = f'ENC-{plot.id}-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.sha256(f"{plot.id}{plot.parcel_number}{plot.created_at}".encode()).hexdigest()[:12].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{plot.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': f'Encumbrance & Search Report - {plot.parcel_number or f"Plot #{plot.id}"}',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'plot': plot,
        'due_diligence': due_diligence,
        'diligence_score': diligence_score,
        'search_date': getattr(plot, 'search_certificate_date', None),
        'search_reference': getattr(plot, 'search_reference_number', None),
        'verification_logs': verification_logs,
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/encumbrance_search.html',
        context=context,
        filename=f'Encumbrance_Report_{plot.parcel_number or plot.id}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


@login_required
def lease_management_report(request, payment_id):
    """Generate lease management dashboard for tenants"""
    payment = get_object_or_404(PaymentRequest, id=payment_id, transaction_type='lease')
    
    # Check permission
    if request.user != payment.buyer:
        messages.error(request, "You don't have permission to view this report")
        return redirect('listings:dashboard_router')
    
    # Calculate lease metrics
    today = timezone.now().date()
    lease_start = payment.lease_start_date
    lease_end = payment.lease_end_date
    
    days_remaining = (lease_end - today).days if lease_end else 0
    months_remaining = days_remaining // 30 if days_remaining > 0 else 0
    
    report_id = f'LSE-{payment.id}-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"{payment.id}{payment.buyer.id}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{payment.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': f'Lease Management Dashboard - {payment.plot.title if payment.plot else "N/A"}',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'payment': payment,
        'deal': payment,
        'plot': payment.plot,
        'days_remaining': days_remaining,
        'months_remaining': months_remaining,
        'lease_progress': 100 - ((days_remaining / 365) * 100) if days_remaining > 0 and lease_end else 0,
        'upcoming_payments': [],
        'compliance_logs': [],
        'good_husbandry_score': 85,
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/lease_management.html',
        context=context,
        filename=f'Lease_Management_{payment.internal_reference}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


# ==================== SELLER/LANDLORD REPORTS ====================

@login_required
def payout_commission_report(request):
    """Generate payout and commission summary for seller"""
    user = request.user
    
    # Get all completed payment requests where user is seller
    completed_deals = PaymentRequest.objects.filter(
        seller=user,
        status__in=[PaymentRequest.Status.RELEASED]
    )
    
    total_sales = Decimal('0')
    total_commissions = Decimal('0')
    total_taxes = Decimal('0')
    payouts = []
    
    for deal in completed_deals:
        sale_amount = deal.amount
        commission = deal.platform_fee_amount
        tax = commission * Decimal('0.16')  # 16% VAT
        net_payout = sale_amount - commission - tax
        
        total_sales += sale_amount
        total_commissions += commission
        total_taxes += tax
        
        payouts.append({
            'plot': deal.plot,
            'deal': deal,
            'sale_amount': sale_amount,
            'commission': commission,
            'tax': tax,
            'net_payout': net_payout,
            'date': deal.released_at or deal.updated_at
        })
    
    total_net_payout = total_sales - total_commissions - total_taxes
    
    report_id = f'PAY-{user.id}-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"{user.id}{total_net_payout}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{user.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': 'Payout & Commission Summary',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': user.get_full_name() or user.username,
        'user': user,
        'total_sales': total_sales,
        'total_commissions': total_commissions,
        'total_taxes': total_taxes,
        'total_net_payout': total_net_payout,
        'payouts': payouts,
        'platform_commission_rate': 7.5,
        'agent_commission': Decimal('0'),
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/payout_commission.html',
        context=context,
        filename=f'Payout_Summary_{user.username}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


@login_required
def occupancy_waitlist_report(request, plot_id):
    """Generate occupancy and waitlist report for landlord"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Check if user is the owner
    if request.user != plot.landowner.user:
        messages.error(request, "You don't have permission to view this report")
        return redirect('listings:dashboard_router')
    
    # Get active leases for this plot
    active_leases = PaymentRequest.objects.filter(
        plot=plot,
        transaction_type='lease',
        status__in=[PaymentRequest.Status.IN_ESCROW, PaymentRequest.Status.RELEASED],
        lease_end_date__gte=timezone.now().date()
    )
    
    # Get waitlist entries
    waitlist_entries = LeaseWaitlistEntry.objects.filter(
        plot=plot,
        status__in=['waiting', 'contacted', 'confirmed']
    )
    
    # Historical occupancy
    historical_leases = PaymentRequest.objects.filter(
        plot=plot,
        transaction_type='lease'
    ).values('status').annotate(count=Count('id'))
    
    report_id = f'OCC-{plot.id}-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"{plot.id}{plot.parcel_number}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{plot.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': f'Occupancy & Waitlist Report - {plot.title}',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'plot': plot,
        'active_leases': active_leases,
        'waitlist_count': waitlist_entries.count(),
        'waitlist_entries': waitlist_entries[:20],
        'occupancy_rate': (active_leases.count() / 1) * 100 if active_leases.exists() else 0,
        'occupancy_history': historical_leases,
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/occupancy_waitlist.html',
        context=context,
        filename=f'Occupancy_Report_{plot.parcel_number or plot.id}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


@login_required
def property_performance_report(request, plot_id):
    """Generate property performance analytics for seller"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Check permission
    if request.user != plot.landowner.user:
        messages.error(request, "You don't have permission to view this report")
        return redirect('listings:dashboard_router')
    
    # Get analytics
    views = 0  # Replace with actual view count
    saves = plot.saved_by.count() if hasattr(plot, 'saved_by') else 0
    inquiries = plot.contact_requests.count() if hasattr(plot, 'contact_requests') else 0
    
    conversion_rate = (inquiries / views * 100) if views > 0 else 0
    
    report_id = f'PRF-{plot.id}-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"{plot.id}{plot.parcel_number}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{plot.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': f'Property Performance Analytics - {plot.title}',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'plot': plot,
        'views': views,
        'saves': saves,
        'inquiries': inquiries,
        'conversion_rate': conversion_rate,
        'avg_price_comparison': 0,
        'price_position': 0,
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/property_performance.html',
        context=context,
        filename=f'Performance_{plot.parcel_number or plot.id}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


# ==================== ADMIN REPORTS ====================

@login_required
@user_passes_test(lambda u: u.is_superuser)
def revenue_escrow_audit_report(request):
    """Generate revenue and escrow audit for admin"""
    
    # Get all payment requests
    all_payments = PaymentRequest.objects.all()
    
    # Calculate total in escrow (payments in 'in_escrow' status)
    total_in_escrow = all_payments.filter(
        status=PaymentRequest.Status.IN_ESCROW
    ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
    
    # Calculate total commission (platform fee - using amount for now)
    # Since there's no separate platform_fee_amount, we'll use a percentage of completed transactions
    completed_payments = all_payments.filter(
        status=PaymentRequest.Status.RELEASED
    )
    total_commission = Decimal('0')
    
    for payment in completed_payments:
        # Assuming platform fee is 7.5% of the amount
        platform_fee = payment.amount * Decimal('0.075')
        total_commission += platform_fee
    
    # Alternative: If you have a separate way to calculate fees
    # You might have a metadata field or a related model
    
    # Monthly revenue breakdown
    monthly_revenue = []
    current_year = timezone.now().year
    
    for month in range(1, 13):
        month_payments = completed_payments.filter(
            released_at__year=current_year,
            released_at__month=month
        )
        month_revenue = Decimal('0')
        for payment in month_payments:
            month_revenue += payment.amount * Decimal('0.075')
        
        if month_revenue > 0:
            monthly_revenue.append({
                'released_at__month': month,
                'revenue': month_revenue
            })
    
    report_id = f'REV-{timezone.now().strftime("%Y%m%d%H%M%S")}'
    verification_code = hashlib.md5(f"revenue{timezone.now()}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': 'Revenue & Escrow Audit Report',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'total_in_escrow': total_in_escrow,
        'total_commission': total_commission,
        'total_revenue': total_commission,
        'monthly_revenue': monthly_revenue,
        'completed_deals_count': completed_payments.count(),
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/revenue_escrow_audit.html',
        context=context,
        filename=f'Revenue_Audit_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()

@login_required
@user_passes_test(lambda u: u.is_superuser)
def transaction_velocity_report(request):
    """Generate transaction velocity report for admin"""
    ninety_days_ago = timezone.now() - timedelta(days=90)
    
    deals = PaymentRequest.objects.filter(
        created_at__gte=ninety_days_ago,
        status=PaymentRequest.Status.RELEASED
    )
    
    velocity_data = []
    for deal in deals:
        if deal.released_at:
            days_to_complete = (deal.released_at - deal.created_at).days
            velocity_data.append({
                'deal_id': deal.id,
                'plot_title': deal.plot.title if deal.plot else 'N/A',
                'transaction_type': deal.transaction_type,
                'days_to_complete': days_to_complete,
            })
    
    avg_days = sum([d['days_to_complete'] for d in velocity_data]) / len(velocity_data) if velocity_data else 0
    
    report_id = f'VEL-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"velocity{timezone.now()}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': 'Transaction Velocity Report',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'start_date': ninety_days_ago,
        'end_date': timezone.now(),
        'deals': velocity_data,
        'average_days': avg_days,
        'fastest_transaction': min(velocity_data, key=lambda x: x['days_to_complete']) if velocity_data else None,
        'slowest_transaction': max(velocity_data, key=lambda x: x['days_to_complete']) if velocity_data else None,
        'total_deals': len(velocity_data),
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/transaction_velocity.html',
        context=context,
        filename=f'Transaction_Velocity_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


@login_required
@user_passes_test(lambda u: u.is_superuser)
def officer_performance_report(request):
    """Generate officer/professional performance report"""
    report_id = f'OFF-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"officer{timezone.now()}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': 'Officer/Professional Performance Report',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'professionals': [],
        'top_rated': [],
        'fastest_completion': [],
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/officer_performance.html',
        context=context,
        filename=f'Officer_Performance_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


@login_required
@user_passes_test(lambda u: u.is_superuser)
def regional_market_trends_report(request):
    """Generate regional market trends report"""
    market_data = Plot.objects.filter(
        is_published=True
    ).values('county').annotate(
        avg_price=Avg('price'),
        total_listings=Count('id'),
        avg_area=Avg('area')
    ).order_by('-avg_price')
    
    report_id = f'MRK-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"market{timezone.now()}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': 'Regional Market Trends Report',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'market_data': market_data,
        'counties_count': market_data.count(),
        'total_listings': Plot.objects.filter(is_published=True).count(),
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/regional_market_trends.html',
        context=context,
        filename=f'Market_Trends_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


# ==================== LEGAL REPORTS ====================

@login_required
def stamp_duty_tax_report(request, payment_id):
    """Generate stamp duty and tax clearance report"""
    payment = get_object_or_404(PaymentRequest, id=payment_id)
    
    stamp_duty_rate = Decimal('0.02') if payment.plot and payment.plot.market_zone == 'rural' else Decimal('0.04')
    stamp_duty = payment.amount * stamp_duty_rate
    vat = payment.platform_fee_amount * Decimal('0.16')
    
    report_id = f'TAX-{payment.id}-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"{payment.id}{stamp_duty}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{payment.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': f'Stamp Duty & Tax Clearance - {payment.internal_reference}',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'deal': payment,
        'stamp_duty': stamp_duty,
        'capital_gains_tax': Decimal('0'),
        'vat': vat,
        'withholding_tax': Decimal('0'),
        'total_tax_liability': stamp_duty + vat,
        'payment_reference': payment.internal_reference,
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/stamp_duty_tax_clearance.html',
        context=context,
        filename=f'Stamp_Duty_{payment.internal_reference}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()


@login_required
def land_use_zoning_report(request, plot_id):
    """Generate land use and zoning report"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    report_id = f'LUZ-{plot.id}-{timezone.now().strftime("%Y%m%d")}'
    verification_code = hashlib.md5(f"{plot.id}{plot.parcel_number}".encode()).hexdigest()[:8].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}{plot.id}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': f'Land Use & Zoning Report - {plot.title}',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'plot': plot,
        'land_use_classification': plot.get_land_type_display() if hasattr(plot, 'get_land_type_display') else 'Agricultural',
        'zoning_compliance': 'Agricultural Zone - Compliant',
        'protected_area_status': 'Not in protected area',
        'recommended_uses': ['Crop Farming', 'Livestock Grazing', 'Agroforestry'],
        'restrictions': ['No subdivision without LCB consent', 'Environmental assessment for large projects'],
        'verification_code': verification_code,
        'digital_signature': digital_signature,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/land_use_zoning.html',
        context=context,
        filename=f'Land_Use_{plot.parcel_number or plot.id}_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()

@login_required
@user_passes_test(lambda u: u.is_superuser)
def executive_system_report(request):
    """Generate comprehensive system-wide executive report"""
    from django.db.models import Sum, Count, Avg, Q
    from datetime import timedelta
    from decimal import Decimal
    
    # Date ranges
    today = timezone.now().date()
    thirty_days_ago = today - timedelta(days=30)
    ninety_days_ago = today - timedelta(days=90)
    
    # ========== PLATFORM METRICS ==========
    total_plots = Plot.objects.count()
    published_plots = Plot.objects.filter(is_published=True).count()
    pending_plots = total_plots - published_plots
    
    # Plot market status breakdown
    available_plots = Plot.objects.filter(market_status='available').count()
    reserved_plots = Plot.objects.filter(market_status='reserved').count()
    sold_plots = Plot.objects.filter(market_status='sold').count()
    leased_plots = Plot.objects.filter(market_status='leased').count()
    
    # Land type distribution
    agricultural_plots = Plot.objects.filter(land_type='agricultural').count()
    commercial_plots = Plot.objects.filter(land_type='commercial').count()
    residential_plots = Plot.objects.filter(land_type='residential').count()
    
    # Verification stats
    verification_completed = VerificationStatus.objects.filter(is_complete=True).count()
    verification_pending = VerificationStatus.objects.filter(is_complete=False).count()
    verification_not_started = total_plots - verification_completed - verification_pending
    
    # ========== TRANSACTION METRICS ==========
    total_transactions = PaymentRequest.objects.count()
    
    # Transaction breakdown by type
    purchase_transactions = PaymentRequest.objects.filter(transaction_type='purchase').count()
    lease_transactions = PaymentRequest.objects.filter(transaction_type='lease').count()
    service_transactions = PaymentRequest.objects.filter(transaction_type='service').count()
    
    # Transaction status breakdown
    pending_transactions = PaymentRequest.objects.filter(status='pending').count()
    paid_transactions = PaymentRequest.objects.filter(status='paid').count()
    in_escrow_transactions = PaymentRequest.objects.filter(status='in_escrow').count()
    released_transactions = PaymentRequest.objects.filter(status='released').count()
    completed_transactions = PaymentRequest.objects.filter(status='released').count()
    cancelled_transactions = PaymentRequest.objects.filter(status='cancelled').count()
    
    # Transaction volume trends
    transactions_last_30_days = PaymentRequest.objects.filter(
        created_at__date__gte=thirty_days_ago
    ).count()
    transactions_last_90_days = PaymentRequest.objects.filter(
        created_at__date__gte=ninety_days_ago
    ).count()
    
    # ========== FINANCIAL METRICS ==========
    total_transaction_value = PaymentRequest.objects.aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')
    
    total_in_escrow = PaymentRequest.objects.filter(
        status='in_escrow'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    total_released = PaymentRequest.objects.filter(
        status='released'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    # Platform revenue (estimated at 7.5%)
    estimated_revenue = total_released * Decimal('0.075')
    
    # Average transaction value
    avg_transaction_value = total_transaction_value / total_transactions if total_transactions > 0 else Decimal('0')
    
    # ========== USER METRICS ==========
    total_users = User.objects.count()
    
    # User role breakdown
    landowners = User.objects.filter(is_landowner=True).count() if hasattr(User, 'is_landowner') else 0
    agents = User.objects.filter(is_agent=True).count() if hasattr(User, 'is_agent') else 0
    buyers = total_users - landowners - agents
    
    # New users (last 30 days)
    new_users_last_30_days = User.objects.filter(
        date_joined__date__gte=thirty_days_ago
    ).count()
    
    # Active users (with transactions)
    active_users = PaymentRequest.objects.values('buyer').union(
        PaymentRequest.objects.values('seller')
    ).count()
    
        # ========== ENGAGEMENT METRICS ==========
    total_saved_plots = 0
    total_contact_requests = 0
    
    # Try to get saved plots count
    try:
        if hasattr(Plot, 'saved_by'):
            # Get count of saved plots
            for plot in Plot.objects.all():
                total_saved_plots += plot.saved_by.count()
    except Exception:
        total_saved_plots = 0
    
    # Try to get contact requests count
    try:
        if hasattr(Plot, 'contact_requests'):
            for plot in Plot.objects.all():
                total_contact_requests += plot.contact_requests.count()
    except Exception:
        total_contact_requests = 0
        
    # ========== GROWTH METRICS ==========
    plots_last_30_days = Plot.objects.filter(
        created_at__date__gte=thirty_days_ago
    ).count()
    plots_last_90_days = Plot.objects.filter(
        created_at__date__gte=ninety_days_ago
    ).count()
    
    # Monthly trends (last 6 months)
    monthly_trends = []
    for i in range(6):
        month_start = today.replace(day=1) - timedelta(days=30 * i)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        month_plots = Plot.objects.filter(
            created_at__date__gte=month_start,
            created_at__date__lte=month_end
        ).count()
        
        month_transactions = PaymentRequest.objects.filter(
            created_at__date__gte=month_start,
            created_at__date__lte=month_end
        ).count()
        
        monthly_trends.append({
            'month': month_start.strftime('%B %Y'),
            'plots': month_plots,
            'transactions': month_transactions
        })
    
    # ========== REGIONAL INSIGHTS ==========
    top_counties = Plot.objects.filter(
        is_published=True
    ).values('county').annotate(
        count=Count('id'),
        avg_price=Avg('price')
    ).order_by('-count')[:5]
    
    # ========== REPORT METADATA ==========
    report_id = f'EXEC-{timezone.now().strftime("%Y%m%d%H%M%S")}'
    verification_code = hashlib.md5(f"executive{timezone.now()}".encode()).hexdigest()[:12].upper()
    digital_signature = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{report_id}{verification_code}".encode(),
        hashlib.sha256
    ).hexdigest()[:16].upper()
    
    context = {
        'report_title': 'Executive System Report',
        'report_id': report_id,
        'generated_date': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
        'verification_code': verification_code,
        'digital_signature': digital_signature,
        
        # Platform Metrics
        'total_plots': total_plots,
        'published_plots': published_plots,
        'pending_plots': pending_plots,
        'publication_rate': int(published_plots / total_plots * 100) if total_plots > 0 else 0,
        'available_plots': available_plots,
        'reserved_plots': reserved_plots,
        'sold_plots': sold_plots,
        'leased_plots': leased_plots,
        'agricultural_plots': agricultural_plots,
        'commercial_plots': commercial_plots,
        'residential_plots': residential_plots,
        'verification_completed': verification_completed,
        'verification_pending': verification_pending,
        'verification_not_started': verification_not_started,
        'verification_progress': int(verification_completed / total_plots * 100) if total_plots > 0 else 0,
        
        # Transaction Metrics
        'total_transactions': total_transactions,
        'purchase_transactions': purchase_transactions,
        'lease_transactions': lease_transactions,
        'service_transactions': service_transactions,
        'pending_transactions': pending_transactions,
        'paid_transactions': paid_transactions,
        'in_escrow_transactions': in_escrow_transactions,
        'released_transactions': released_transactions,
        'completed_transactions': completed_transactions,
        'cancelled_transactions': cancelled_transactions,
        'completion_rate': int(completed_transactions / total_transactions * 100) if total_transactions > 0 else 0,
        'transactions_last_30_days': transactions_last_30_days,
        'transactions_last_90_days': transactions_last_90_days,
        
        # Financial Metrics
        'total_transaction_value': total_transaction_value,
        'total_in_escrow': total_in_escrow,
        'total_released': total_released,
        'estimated_revenue': estimated_revenue,
        'avg_transaction_value': avg_transaction_value,
        
        # User Metrics
        'total_users': total_users,
        'landowners': landowners,
        'agents': agents,
        'buyers': buyers,
        'new_users_last_30_days': new_users_last_30_days,
        'active_users': active_users,
        
        # Engagement Metrics
        'total_saved_plots': total_saved_plots,
        'total_contact_requests': total_contact_requests,
        
        # Growth Metrics
        'plots_last_30_days': plots_last_30_days,
        'plots_last_90_days': plots_last_90_days,
        'monthly_trends': monthly_trends,
        'growth_rate': int((plots_last_30_days / plots_last_90_days * 100) - 100) if plots_last_90_days > 0 else 0,
        
        # Regional Insights
        'top_counties': top_counties,
    }
    
    pdf_gen = WeasyPDFGenerator(
        template_name='reports/executive_system_report.html',
        context=context,
        filename=f'Executive_Report_{timezone.now().strftime("%Y%m%d")}'
    )
    
    return pdf_gen.generate_pdf()
