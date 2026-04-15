from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # Encumbrance Reports
    path('encumbrance-search/<int:plot_id>/', views.encumbrance_search_report, name='encumbrance_search'),
    
    # Transaction Reports
    path('transaction-milestone/<int:payment_id>/', views.transaction_milestone_report, name='transaction_milestone'),
    
    # Financial Reports
    path('escrow-statement/', views.escrow_statement_report, name='escrow_statement'),
    path('escrow-statement/<int:payment_id>/', views.escrow_statement_report, name='escrow_statement_detail'),
    
    # Lease Reports
    path('lease-management/<int:payment_id>/', views.lease_management_report, name='lease_management'),
    
    # Seller Reports
    path('payout-commission/', views.payout_commission_report, name='payout_commission'),
    path('occupancy-waitlist/<int:plot_id>/', views.occupancy_waitlist_report, name='occupancy_waitlist'),
    path('property-performance/<int:plot_id>/', views.property_performance_report, name='property_performance'),
    
    # Admin Reports
    path('admin/revenue-audit/', views.revenue_escrow_audit_report, name='revenue_audit'),
    path('admin/transaction-velocity/', views.transaction_velocity_report, name='transaction_velocity'),
    path('admin/officer-performance/', views.officer_performance_report, name='officer_performance'),
    path('admin/regional-trends/', views.regional_market_trends_report, name='regional_trends'),
    path('admin/executive-report/', views.executive_system_report, name='executive_system_report'),
    
    # Legal Reports
    path('legal/stamp-duty/<int:payment_id>/', views.stamp_duty_tax_report, name='stamp_duty'),
    path('legal/land-use-zoning/<int:plot_id>/', views.land_use_zoning_report, name='land_use_zoning'),
]