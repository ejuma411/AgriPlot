from django.urls import path

from .views import (
    PaymentDashboardView,
    PaymentDisputeCreateView,
    PaymentFlowOverviewView,
    PaymentMilestoneCreateView,
    PaymentRequestCreateView,
    PaymentRequestDetailView,
    PaymentTransitionView,
)


app_name = "payments"


urlpatterns = [
    path("", PaymentDashboardView.as_view(), name="dashboard"),
    path("flow/", PaymentFlowOverviewView.as_view(), name="flow_overview"),
    path("request/", PaymentRequestCreateView.as_view(), name="create_request"),
    path("<int:pk>/", PaymentRequestDetailView.as_view(), name="detail"),
    path("<int:pk>/transition/<str:action>/", PaymentTransitionView.as_view(), name="transition"),
    path("<int:pk>/milestones/add/", PaymentMilestoneCreateView.as_view(), name="add_milestone"),
    path("<int:pk>/dispute/", PaymentDisputeCreateView.as_view(), name="open_dispute"),
]
