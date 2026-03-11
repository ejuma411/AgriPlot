from django.urls import path
from django.views.generic import TemplateView

from .views_dashboard import (
    buyer_interests,
    dashboard_analytics,
    dashboard_router,
    my_plots,
    plot_verification_detail,
    staff_dashboard,
    update_interest_status,
)
from .views_profile import account_settings, profile_edit, profile_management
from .views_registration import (
    register_agent,
    register_buyer,
    register_choice,
    register_landowner,
    register_landowner_simple,
)
from .views_wizard import FORMS, LandownerWizard


urlpatterns = [
    # Registration
    path("register-choice/", register_choice, name="register_choice"),
    path("register/buyer/", register_buyer, name="register_buyer"),
    path("register/landowner/simple/", register_landowner_simple, name="register_landowner_simple"),
    path("register/landowner/upgrade/", register_landowner, name="register_landowner_upgrade"),
    path("register/landowner/", LandownerWizard.as_view(FORMS), name="register_landowner"),
    path(
        "register/landowner/success/",
        TemplateView.as_view(template_name="accounts/landowner_success.html"),
        name="landowner_success",
    ),
    path("register/agent/", register_agent, name="register_agent"),

    # Dashboard
    path("dashboard/", dashboard_router, name="dashboard_router"),
    path("staff-dashboard/", staff_dashboard, name="staff_dashboard"),
    path("dashboard/plots/", my_plots, name="my_plots"),
    path(
        "dashboard/plot/<int:plot_id>/verification/",
        plot_verification_detail,
        name="plot_verification_detail",
    ),
    path("dashboard/interests/", buyer_interests, name="buyer_interests"),
    path(
        "dashboard/interest/<int:interest_id>/update/",
        update_interest_status,
        name="update_interest_status",
    ),
    path("dashboard/profile/", profile_management, name="profile_management"),
    path("dashboard/profile/edit/", profile_edit, name="profile_edit"),
    path("dashboard/settings/", account_settings, name="account_settings"),
    path("dashboard/analytics/", dashboard_analytics, name="dashboard_analytics"),
]

