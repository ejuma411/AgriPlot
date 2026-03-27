from django.urls import path

from .views import (
    PaymentDashboardView,
    PaymentClosingStepUpdateView,
    PaymentClosingStepWorkspaceView,
    PaymentDisputeCreateView,
    PaymentFlowOverviewView,
    PaymentMilestoneCreateView,
    PaystackCallbackView,
    PaystackWebhookView,
    PaymentRequestCreateView,
    PaymentRequestDetailView,
    PaymentTransitionView,
)


app_name = "payments"


urlpatterns = [
    path("", PaymentDashboardView.as_view(), name="dashboard"),
    path("flow/", PaymentFlowOverviewView.as_view(), name="flow_overview"),
    path("request/", PaymentRequestCreateView.as_view(), name="create_request"),
    path("callback/paystack/", PaystackCallbackView.as_view(), name="paystack_callback"),
    path("webhook/paystack/", PaystackWebhookView.as_view(), name="paystack_webhook"),
    path("<int:pk>/", PaymentRequestDetailView.as_view(), name="detail"),
    path("<int:pk>/closing/<int:step_id>/workspace/", PaymentClosingStepWorkspaceView.as_view(), name="closing_step_workspace"),
    path("<int:pk>/transition/<str:action>/", PaymentTransitionView.as_view(), name="transition"),
    path("<int:pk>/closing/<int:step_id>/", PaymentClosingStepUpdateView.as_view(), name="update_closing_step"),
    path("<int:pk>/milestones/add/", PaymentMilestoneCreateView.as_view(), name="add_milestone"),
    path("<int:pk>/dispute/", PaymentDisputeCreateView.as_view(), name="open_dispute"),
]
