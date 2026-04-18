from django.urls import path, include
from django.views.generic.base import RedirectView

from . import views, views_admin, views_extension


app_name = "verification"


urlpatterns = [
    path(
        "request/extension-officer/",
        views.request_extension_officer,
        name="request_extension_officer",
    ),
    path(
        "request/land-surveyor/",
        views.request_land_surveyor,
        name="request_land_surveyor",
    ),

    # Admin verification (canonical routes)
    path("verify/verification/", views_admin.verification_dashboard, name="verification_dashboard"),
    path("verify/verification/queue/", views_admin.verification_queue, name="verification_queue"),
    path("verify/verification/review/<int:plot_id>/", views_admin.review_plot, name="review_plot"),
    path("verify/verification/history/<int:plot_id>/", views_admin.plot_verification_history, name="verification_history"),
    path("verify/system-construction/", views_admin.system_construction_journal, name="system_construction_journal"),
    path("verify/registry/", views_admin.registry_parcels, name="registry_parcels"),
    path("verify/registry/mismatches/", views_admin.registry_mismatches, name="registry_mismatches"),
    path('', views_admin.admin_dashboard, name='admin_dashboard'),

    # Legacy admin route compatibility
    path("verify/dashboard/", RedirectView.as_view(pattern_name="verification:verification_dashboard", permanent=True)),
    path("verify/plot/<int:plot_id>/", RedirectView.as_view(pattern_name="verification:review_plot", permanent=True)),

    # Task management
    path("verify/tasks/", views_admin.task_assignment, name="task_assignment"),
    path("verify/tasks/my/", views_admin.my_tasks, name="my_tasks"),
    path("verify/tasks/complete/<int:task_id>/", views_admin.complete_task_view, name="complete_task"),
    path("verify/tasks/ajax/assign/", views_admin.ajax_assign_task, name="ajax_assign_task"),

    # Notifications
    path("notifications/", views_admin.get_notifications, name="get_notifications"),
    path("notifications/mark/<int:notification_id>/", views_admin.mark_notification_read, name="mark_notification_read"),
    path("notifications/mark-all/", views_admin.mark_all_notifications_read, name="mark_all_notifications_read"),

    path('audit-logs/export/pdf/', views.audit_logs_export_pdf, name='audit_logs_export_pdf'),
    
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
    path("verify/audit-logs/", views_admin.audit_logs, name="audit_logs"),
    path("verify/audit-logs/export/", views_admin.export_audit_logs, name="audit_logs_export"),
    path("verify/system-construction/export/", views_admin.system_construction_journal_pdf, name="system_construction_journal_pdf"),

    # Test endpoints (remove in production)
    path("test/ardhisasa/<int:plot_id>/", views_admin.trigger_ardhisasa, name="test_ardhisasa"),
    path("plot/<int:plot_id>/trigger-ardhisasa/", views_admin.trigger_ardhisasa, name="trigger_ardhisasa"),
    path('audit-logs/export/pdf/', views_admin.export_audit_logs_pdf, name='export_audit_logs_pdf'),
]
