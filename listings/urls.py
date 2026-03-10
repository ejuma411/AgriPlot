from django.urls import include, path
from django.views.generic import TemplateView
from django.contrib.auth.views import LogoutView
from django.views.generic.base import RedirectView
from . import views_otp
from .views import LandownerWizard
from . import views, views_admin, views_extension, views_test
from . import views_auth

app_name = "listings"

urlpatterns = [
    # Public pages
    path("", views.home, name="home"),
    path("plot/<int:id>/", views.plot_detail, name="plot_detail"),
    path("ajax/search/", views.ajax_search, name="ajax_search"),
    path("browse-plots/", TemplateView.as_view(template_name="listings/info/browse_plots.html"), name="browse_plots"),
    path("how-it-works/", TemplateView.as_view(template_name="listings/info/how_it_works.html"), name="how_it_works"),
    path("contact-us/", TemplateView.as_view(template_name="listings/info/contact_us.html"), name="contact_us"),
    path("about-us/", views.info_page, {"slug": "about", "template_name": "listings/info/about_us.html"}, name="about_us"),
    path("terms/", views.info_page, {"slug": "terms", "template_name": "listings/info/terms.html"}, name="terms"),
    path("privacy/", views.info_page, {"slug": "privacy", "template_name": "listings/info/privacy.html"}, name="privacy"),
    path("faq/", TemplateView.as_view(template_name="listings/info/faq.html"), name="faq"),

    # Plot management
    path("plot/<int:id>/edit/", views.edit_plot, name="edit_plot"),
    path("plot/<int:plot_id>/document/<str:doc_type>/", views.serve_plot_document, name="serve_plot_document"),
    path("plot/<int:plot_id>/upload-document/", views.upload_verification_doc, name="upload_verification_doc"),

    # Authentication
    path("logout/", LogoutView.as_view(next_page="listings:home"), name="logout"),
    path("two-factor/setup/", views_auth.two_factor_setup, name="two_factor_setup"),
    path("two-factor/verify/", views_auth.two_factor_verify, name="two_factor_verify"),
    path("sessions/signout-all/", views_auth.sign_out_all_sessions, name="sign_out_all_sessions"),

    # Registration
    path("register-choice/", views.register_choice, name="register_choice"),
    path("register/buyer/", views.register_buyer, name="register_buyer"),
    path("register/landowner/simple/", views.register_landowner_simple, name="register_landowner_simple"),
    path("register/landowner/upgrade/", views.register_landowner, name="register_landowner_upgrade"),
    path("register/landowner/", LandownerWizard.as_view(views.FORMS), name="register_landowner"),
    path(
        "register/landowner/success/",
        TemplateView.as_view(template_name="listings/landowner_success.html"),
        name="landowner_success",
    ),
    path("register/agent/", views.register_agent, name="register_agent"),
    path("request/extension-officer/", views.request_extension_officer, name="request_extension_officer"),
    path("request/land-surveyor/", views.request_land_surveyor, name="request_land_surveyor"),

    # Password Reset URLs
    path('password-reset/', 
         views_auth.CustomPasswordResetView.as_view(), 
         name='password_reset'),
    
    path('password-reset/confirm/', 
         views_auth.password_reset_confirm_request, 
         name='password_reset_confirm_request'),
    
    path('password-reset/done/', 
         views_auth.CustomPasswordResetDoneView.as_view(), 
         name='password_reset_done'),
    
    path('password-reset/<uidb64>/<token>/', 
         views_auth.CustomPasswordResetConfirmView.as_view(), 
         name='password_reset_confirm'),
    
    path('password-reset/complete/', 
         views_auth.CustomPasswordResetCompleteView.as_view(), 
         name='password_reset_complete'),
    
    # Dashboard
    path("add-plot/", RedirectView.as_view(pattern_name="listings:add_plot", permanent=True)),
    path("dashboard/add-plot/", views.add_plot, name="add_plot"),
    path("dashboard/", views.dashboard_router, name="dashboard_router"),
    path("staff-dashboard/", views.staff_dashboard, name="staff_dashboard"),
    path("dashboard/plots/", views.my_plots, name="my_plots"),
    path("dashboard/plot/<int:plot_id>/verification/", views.plot_verification_detail, name="plot_verification_detail"),
    path("dashboard/interests/", views.buyer_interests, name="buyer_interests"),
    path("dashboard/interest/<int:interest_id>/update/", views.update_interest_status, name="update_interest_status"),
    path("dashboard/profile/", views.profile_management, name="profile_management"),
    path("dashboard/profile/edit/", views.profile_edit, name="profile_edit"),
    path("dashboard/settings/", views.account_settings, name="account_settings"),
    path("dashboard/notifications/", views.notifications_inbox, name="notifications_inbox"),
    path("dashboard/analytics/", views.dashboard_analytics, name="dashboard_analytics"),
    path("dashboard/plot/<int:plot_id>/upload-document/", views.upload_verification_doc, name="dashboard_upload_doc"),
    path("verification-progress/", views.verification_progress, name="verification_progress"),

    # Messaging & contact
    path("plot/<int:plot_id>/contact/", views.contact_agent, name="contact_agent"),

    # API endpoints
    path("api/request-contact/<int:plot_id>/", views.request_contact_details, name="request_contact"),
    path("api/log-phone-view/<int:plot_id>/", views.log_phone_view, name="log_phone_view"),
    path("api/registry-lookup/", views.registry_lookup, name="registry_lookup"),
    path("get-subcounties/", views.get_subcounties, name="get_subcounties"),

    # Admin verification (canonical routes)
    path("verify/verification/", views_admin.verification_dashboard, name="verification_dashboard"),
    path("verify/verification/queue/", views_admin.verification_queue, name="verification_queue"),
    path("verify/verification/review/<int:plot_id>/", views_admin.review_plot, name="review_plot"),
    path("verify/verification/history/<int:plot_id>/", views_admin.plot_verification_history, name="verification_history"),
    path("verify/system-construction/", views_admin.system_construction_journal, name="system_construction_journal"),
    path("verify/registry/", views_admin.registry_parcels, name="registry_parcels"),
    path("verify/registry/mismatches/", views_admin.registry_mismatches, name="registry_mismatches"),

    # Legacy admin route compatibility
    path("verify/dashboard/", RedirectView.as_view(pattern_name="listings:verification_dashboard", permanent=True)),
    path("verify/plot/<int:plot_id>/", RedirectView.as_view(pattern_name="listings:review_plot", permanent=True)),

    # Task management
    path("verify/tasks/", views_admin.task_assignment, name="task_assignment"),
    path("verify/tasks/my/", views_admin.my_tasks, name="my_tasks"),
    path("verify/tasks/complete/<int:task_id>/", views_admin.complete_task_view, name="complete_task"),
    path("verify/tasks/ajax/assign/", views_admin.ajax_assign_task, name="ajax_assign_task"),

    # Notifications
    path("notifications/", views_admin.get_notifications, name="get_notifications"),
    path("notifications/mark/<int:notification_id>/", views_admin.mark_notification_read, name="mark_notification_read"),
    path("notifications/mark-all/", views_admin.mark_all_notifications_read, name="mark_all_notifications_read"),

    # Extension officer routes
    path(
        "extension/",
        include(
            [
                path("", views_extension.extension_dashboard, name="extension_dashboard"),
                path("confirm/<int:task_id>/", views_extension.confirm_task, name="confirm_extension_task"),
                path("review/<int:task_id>/", views_extension.conduct_extension_review, name="conduct_extension_review"),
                path("report/<int:report_id>/", views_extension.view_extension_report, name="view_extension_report"),
                path("find-plot/", views_extension.find_plot_by_parcel, {"role": "extension"}, name="extension_find_plot"),
            ]
        ),
    ),

    # Land surveyor routes
    path(
        "surveyors/",
        include(
            [
                path("", views_extension.surveyor_dashboard, name="surveyor_dashboard"),
                path("confirm/<int:task_id>/", views_extension.confirm_task, name="confirm_surveyor_task"),
                path("review/<int:task_id>/", views_extension.conduct_surveyor_inspection, name="conduct_surveyor_inspection"),
                path("report/<int:report_id>/", views_extension.view_surveyor_report, name="view_surveyor_report"),
                path("find-plot/", views_extension.find_plot_by_parcel, {"role": "surveyor"}, name="surveyor_find_plot"),
            ]
        ),
    ),

    # Analytics
    path("analytics/", views_admin.analytics_dashboard, name="analytics_dashboard"),
    path("analytics/export/", views_admin.export_report, name="export_report"),

    # Backward compatibility redirects
    path("register/Seller/", RedirectView.as_view(pattern_name="listings:register_landowner", permanent=True), name="register_Seller"),
    path("register/broker/", RedirectView.as_view(pattern_name="listings:register_agent", permanent=True), name="register_broker"),

    # Test endpoints (remove in production)
    path("test/ardhisasa/<int:plot_id>/", views_test.test_ardhisasa, name="test_ardhisasa"),
    path("plot/<int:plot_id>/trigger-ardhisasa/", views_admin.trigger_ardhisasa, name="trigger_ardhisasa"),

    # OTP Verification URLs
    path('send-otp/', views_otp.send_otp_verification, name='send_otp'),
    path('verify-otp/', views_otp.verify_otp, name='verify_otp'),
    path('resend-otp/', views_otp.resend_otp, name='resend_otp'),
    
    path('contact-support/', views.contact_support, name='contact_support'),
]
