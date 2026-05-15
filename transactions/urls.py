from django.urls import path
from . import views

app_name = "transactions"

urlpatterns = [
    path("", views.TransactionDashboardView.as_view(), name="dashboard"),
    path("<int:pk>/", views.TransactionDetailView.as_view(), name="detail"),
]
