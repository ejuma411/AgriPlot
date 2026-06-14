from django.urls import path
from . import views

app_name = 'transactions'

urlpatterns = [
    # Dashboard and Detail
    path('', views.TransactionDashboardView.as_view(), name='dashboard'),
    path('<int:pk>/', views.transaction_detail, name='detail'),
    
    # Document Management
    path('<int:pk>/upload/', views.upload_document, name='upload_document'),
    path('document/<int:doc_id>/verify/', views.verify_document, name='verify_document'),
    path('document/<int:doc_id>/', views.verify_document, name='document_verify'),
    
    # Stage Management
    path('<int:pk>/advance-stage/', views.advance_stage, name='advance_stage'),
    path('<int:pk>/pay-installment/', views.pay_installment, name='pay_installment'),
    
    # Stamp Duty (KRA iTax Verification)
    path('<int:pk>/stamp-duty-verify/', views.stamp_duty_verification, name='stamp_duty_verification'),
    
    # Fund Disbursement (Escrow Admin Only)
    path('<int:pk>/disburse/', views.disburse_funds, name='disburse_funds'),
    
    # Transaction Reports
    path('<int:pk>/resend-reports/', views.resend_transaction_reports, name='resend_reports'),
    path('<int:pk>/make-stage-payment/', views.make_stage_payment, name='make_stage_payment'),
]