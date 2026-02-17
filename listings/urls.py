from django.urls import path
from . import views
from .views import LandownerWizard
from django.views.generic import TemplateView
from django.contrib.auth.views import LogoutView
from django.views.generic.base import RedirectView # For backward compatibility redirects

app_name = 'listings'

urlpatterns = [
    # ============ Home & Public Pages ============
    path('', views.home, name='home'),
    path('plot/<int:id>/', views.plot_detail, name='plot_detail'),
    path('ajax/search/', views.ajax_search, name='ajax_search'),
    
    # ============ Plot Management ============
    path('add-plot/', views.add_plot, name='add_plot'),  # Changed from add_plot/ to add-plot/ for consistency
    path('plot/<int:id>/edit/', views.edit_plot, name='edit_plot'),
    
    # ============ Document Management ============
    path('plot/<int:plot_id>/upload-document/', views.upload_verification_doc, name='upload_verification_doc'),
    # REMOVED: upload_checklist - this view no longer exists
    
    # ============ Authentication ============
    path('logout/', LogoutView.as_view(next_page='listings:home'), name='logout'),
    
    # ============ Registration ============
    path('register-choice/', views.register_choice, name='register_choice'),
    path('register/buyer/', views.register_buyer, name='register_buyer'),
    
    # Landowner Registration - Two options (choose ONE)
    # OPTION 1: Simple registration (no wizard)
    path('register/landowner/simple/', views.register_landowner, name='register_landowner_simple'),
    # OPTION 2: Wizard registration (multi-step)
    path('register/landowner/', LandownerWizard.as_view(views.FORMS), name='register_landowner'),
    path('register/landowner/success/', TemplateView.as_view(template_name="listings/landowner_success.html"), name='landowner_success'),
    
    # Agent Registration
    path('register/agent/', views.register_agent, name='register_agent'),
   
    # ============ Dashboard ============
    path('dashboard/', views.staff_dashboard, name='staff_dashboard'),
    path('dashboard/plots/', views.my_plots, name='my_plots'),
    path('dashboard/plot/<int:plot_id>/verification/', views.plot_verification_detail, name='plot_verification_detail'),
    path('dashboard/interests/', views.buyer_interests, name='buyer_interests'),
    path('dashboard/interest/<int:interest_id>/update/', views.update_interest_status, name='update_interest_status'),
    path('dashboard/profile/', views.profile_management, name='profile_management'),
    path('dashboard/analytics/', views.dashboard_analytics, name='dashboard_analytics'),
    path('dashboard/plot/<int:plot_id>/upload-document/', views.upload_verification_doc, name='dashboard_upload_doc'),
    
    # ============ Admin Verification ============
    path('verify/dashboard/', views.verification_dashboard, name='verification_dashboard'),
    path('verify/plot/<int:plot_id>/', views.review_plot, name='review_plot'),
    
    # ============ Messaging & Contact ============
    path('plot/<int:plot_id>/contact/', views.contact_agent, name='contact_agent'),
    
    # ============ API Endpoints ============
    path('api/request-contact/<int:plot_id>/', views.request_contact_details, name='request_contact'),
    path('api/log-phone-view/<int:plot_id>/', views.log_phone_view, name='log_phone_view'),
    path('api/plot-reactions/<int:plot_id>/toggle/', views.toggle_plot_reaction, name='toggle_reaction'),
    path('api/plot-reactions/<int:plot_id>/get/', views.get_plot_reactions, name='get_reactions'),

        # ============ BACKWARD COMPATIBILITY REDIRECTS ============
    path('register/seller/', RedirectView.as_view(pattern_name='listings:register_landowner', permanent=True), name='register_seller'),
    path('register/broker/', RedirectView.as_view(pattern_name='listings:register_agent', permanent=True), name='register_broker'),
    path('register/landowner/simple/', RedirectView.as_view(pattern_name='listings:register_landowner', permanent=True)),

]