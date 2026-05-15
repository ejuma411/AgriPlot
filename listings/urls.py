from django.urls import include, path
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView
from django.contrib.auth.views import LogoutView
from . import views
from listings.views import get_wards_api


app_name = "listings"

urlpatterns = [
    # Public pages
    path("plots-for-<str:listing_type>/in-<str:county>/", views.seo_filtered_home, name="seo_filtered"),
    path("plots-in-<str:county>/", views.seo_filtered_home, name="seo_filtered_county"),
    path("", views.home, name="home"),
    path("plots/<slug:county>/<slug:title>/<int:id>/", views.plot_detail_slug, name="plot_detail_slug"),
    path("plot/<int:id>/", views.plot_detail, name="plot_detail"),
    path("plot/<int:plot_id>/owner-approval/", views.approve_agent_listing, name="approve_agent_listing"),
    path("plot/<int:plot_id>/lease-waitlist/", views.join_lease_waitlist, name="join_lease_waitlist"),
    path("plot/<int:plot_id>/lease-waitlist/confirm/", views.confirm_lease_waitlist, name="confirm_lease_waitlist"),
    path("plot/<int:plot_id>/save/", views.toggle_saved_plot, name="toggle_saved_plot"),
    path("plot/<int:plot_id>/report-fraud/", views.submit_fraud_report, name="submit_fraud_report"),
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
    path("", include("authentication.urls")),
    path("", include("accounts.urls")),
    path("", include("notifications.urls")),

    # Password reset and 2FA URLs live under authentication app (included above)
    
    # Dashboard
    path("add-plot/", RedirectView.as_view(pattern_name="listings:add_plot", permanent=True)),
    path("dashboard/add-plot/", views.add_plot, name="add_plot"),
    path("dashboard/plot/<int:plot_id>/upload-document/", views.upload_verification_doc, name="dashboard_upload_doc"),
    path("verification-progress/", views.verification_progress, name="verification_progress"),
    path('land/<int:pk>/full-details/', views.land_full_details, name='land_full_details'),
    # Messaging & contact
    path("plot/<int:plot_id>/contact/", views.contact_agent, name="contact_agent"),

    # API endpoints
    path("api/request-contact/<int:plot_id>/", views.request_contact_details, name="request_contact"),
    path("api/log-phone-view/<int:plot_id>/", views.log_phone_view, name="log_phone_view"),
    path("api/registry-lookup/", views.registry_lookup, name="registry_lookup"),
    path("api/pricing-preview/", views.pricing_preview, name="pricing_preview"),
    path("api/recommendations/", views.recommendations_api, name="recommendations_api"),
    path("analytics/track/", views.track_ux_event, name="track_ux_event"),
    path("get-subcounties/", views.get_subcounties, name="get_subcounties"),
    path('api/wards/', get_wards_api, name='get_wards'),


    # Settings
    path('two-factor/setup/', views.two_factor_setup, name='two_factor_setup'),
    path('two-factor/verify/', views.two_factor_verify, name='two_factor_verify'),
    path('sessions/sign-out-all/', views.sign_out_all_sessions, name='sign_out_all_sessions'),

    # Backward compatibility redirects
    path("register/Seller/", RedirectView.as_view(pattern_name="listings:register_landowner", permanent=True), name="register_Seller"),
    path("register/broker/", RedirectView.as_view(pattern_name="listings:register_agent", permanent=True), name="register_broker"),

    # OTP URLs live under security app
    path("", include("security.urls")),
    
]
