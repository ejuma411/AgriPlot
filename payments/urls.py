from django.urls import path
from . import views
from .views import (
    PaymentDashboardView,
    PaymentClosingStepUpdateView,
    PaymentClosingStepWorkspaceView,
    PaymentClosingStepStkPushView,
    DarajaCallbackView,
    PaymentDisputeCreateView,
    PaymentFlowOverviewView,
    PaymentMilestoneCreateView,
    PaystackCallbackView,
    PaystackWebhookView,
    PaymentRequestCreateView,
    PaymentRequestDetailView,
    PaymentStatusPollView,
    PaymentTransitionView,
)


app_name = "payments"


urlpatterns = [
    path("", PaymentDashboardView.as_view(), name="dashboard"),
    path("flow/", PaymentFlowOverviewView.as_view(), name="flow_overview"),
    path("request/", PaymentRequestCreateView.as_view(), name="create_request"),
    path("callback/daraja/", DarajaCallbackView.as_view(), name="daraja_callback"),
    path("callback/paystack/", PaystackCallbackView.as_view(), name="paystack_callback"),
    path("webhook/paystack/", PaystackWebhookView.as_view(), name="paystack_webhook"),
    path("<int:pk>/", PaymentRequestDetailView.as_view(), name="detail"),
    path("<int:pk>/closing/<int:step_id>/workspace/", PaymentClosingStepWorkspaceView.as_view(), name="closing_step_workspace"),
    path("<int:pk>/closing/<int:step_id>/stk-push/", PaymentClosingStepStkPushView.as_view(), name="closing_step_stk_push"),
    path("<int:pk>/payments/<int:payment_id>/status/", PaymentStatusPollView.as_view(), name="payment_status_poll"),
    path("<int:pk>/transition/<str:action>/", PaymentTransitionView.as_view(), name="transition"),
    path("<int:pk>/closing/<int:step_id>/", PaymentClosingStepUpdateView.as_view(), name="update_closing_step"),
    path("<int:pk>/milestones/add/", PaymentMilestoneCreateView.as_view(), name="add_milestone"),
    path("<int:pk>/dispute/", PaymentDisputeCreateView.as_view(), name="open_dispute"),
    
    # Wallet URLs
    path('wallet/', views.wallet_dashboard, name='wallet_dashboard'),
    path('wallet/set-pin/', views.wallet_set_pin, name='wallet_set_pin'),
    path('wallet/deposit/', views.wallet_deposit, name='wallet_deposit'),
    path('wallet/withdraw/', views.wallet_withdraw, name='wallet_withdraw'),
    path('wallet/pay/', views.wallet_pay, name='wallet_pay'),
    path('wallet/transactions/', views.wallet_transactions, name='wallet_transactions'),
    path('wallet/balance/', views.wallet_balance_api, name='wallet_balance_api'),
    path('mpesa/wallet-callback/', views.mpesa_wallet_callback, name='mpesa_wallet_callback'),
    
    # TEST URL
    path('test-stk/', views.test_stk_push, name='test_stk_push'),
]
