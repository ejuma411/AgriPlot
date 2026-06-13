from django.urls import path
from . import views

app_name = 'transactions'

urlpatterns = [
    path('', views.TransactionDashboardView.as_view(), name='dashboard'),
    path('<int:pk>/', views.transaction_detail, name='detail'),
    path('<int:pk>/upload/', views.upload_document, name='upload_document'),
    path('<int:pk>/advance-stage/', views.advance_stage, name='advance_stage'),
    path('<int:pk>/pay-installment/', views.pay_installment, name='pay_installment'),
     path('document/<int:doc_id>/verify/', views.verify_document, name='verify_document'),
]