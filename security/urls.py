from django.urls import path
from . import views

app_name = 'security'

urlpatterns = [
    # Screenshot protection
    path('log-screenshot/', views.log_screenshot_attempt, name='log_screenshot'),
    
    # Audit logs
    path('audit-log/', views.audit_log_view, name='audit_log'),
    path('audit-log/verify/', views.audit_log_verify, name='audit_log_verify'),
    path('audit-log/export/pdf/', views.export_audit_pdf, name='export_audit_pdf'),
    
    # Security dashboard
    path('dashboard/', views.security_dashboard, name='dashboard'),
    
    # Impersonation alerts
    path('alerts/', views.impersonation_alerts, name='alerts'),
    path('alerts/resolve/<int:alert_id>/', views.resolve_alert, name='resolve_alert'),
    
    # Two-factor authentication
    path('two-factor/setup/', views.two_factor_setup, name='two_factor_setup'),
    path('two-factor/verify/', views.two_factor_verify, name='two_factor_verify'),
    
    # Verification codes
    path('send-code/', views.send_verification_code, name='send_code'),
    path('verify-code/', views.verify_code, name='verify_code'),
    
    # Security health and reports
    path('health-check/', views.security_health_check, name='health_check'),
    path('report/', views.security_report, name='report'),
    
    # Test endpoint (for debugging)
    path('test-audit/', views.test_audit_log, name='test_audit'),
]
