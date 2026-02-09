from django.urls import path
from . import views
from .views import SellerWizard, FORMS
from django.views.generic import TemplateView
from django.contrib.auth.views import LogoutView

app_name= 'listings'

urlpatterns = [
    path('', views.home, name='home'),
    path('add_plot/', views.add_plot, name="add_plot"),
    path('plot/<int:id>/', views.plot_detail, name='plot_detail'),
    path('plot/<int:id>/edit/', views.edit_plot, name='edit_plot'), 
    path('plot/<int:plot_id>/upload/', views.upload_verification_doc, name='upload_verification'),
    path('verify/dashboard/', views.verification_dashboard, name='verification_dashboard'),
    path('verify/plot/<int:plot_id>/', views.review_plot, name='review_plot'),
    
    # LOGOUT
    path('logout/', LogoutView.as_view(next_page='listings:home'), name='logout'),

    path('image/<int:id>/delete/', views.delete_image, name='delete_image'),

    # BUYER REGISTERATION
    path('register/buyer/', views.register_buyer, name='register_buyer'),
    # BROKER & SELLER REGISTRATION
    path('register/seller/', SellerWizard.as_view(FORMS), name='register_seller'),
    path('register/seller/success/', TemplateView.as_view(template_name="listings/seller_success.html"), name='seller_success'),
    path("register-choice/", views.register_choice, name="register_choice"),
    path('register/seller/', views.register_seller, name='register_seller'),
    path('register/broker/', views.register_broker, name='register_broker'),  
    path('upgrade-role/', views.upgrade_role, name='upgrade_role'),
    path('upgrade/seller/', views.upgrade_seller, name='upgrade_seller'),
    path('upgrade/broker/', views.upgrade_broker, name='upgrade_broker'),

     # Dashboard URLs
    path('dashboard/', views.staff_dashboard, name='staff_dashboard'),
    path('dashboard/plots/', views.my_plots, name='my_plots'),
    path('dashboard/plot/<int:plot_id>/verification/', views.plot_verification_detail, name='plot_verification_detail'),
    path('dashboard/interests/', views.buyer_interests, name='buyer_interests'),
    path('dashboard/interest/<int:interest_id>/update/', views.update_interest_status, name='update_interest_status'),
    path('dashboard/profile/', views.profile_management, name='profile_management'),
    path('dashboard/analytics/', views.dashboard_analytics, name='dashboard_analytics'),
    path('dashboard/plot/<int:plot_id>/upload-verification-doc/', views.upload_verification_doc, name='upload_verification_doc'),
    path('dashboard/plot/<int:plot_id>/upload-checklist/', views.upload_checklist, name='upload_checklist'),

    # Plot detail and contact URLs
    path('plot/<int:id>/', views.plot_detail, name='plot_detail'),
    path('plot/<int:plot_id>/contact/', views.contact_broker, name='contact_broker'),
    
    # API endpoints
    path('api/request-contact/<int:plot_id>/', views.request_contact_details, name='request_contact'),
    path('api/log-phone-view/<int:plot_id>/', views.log_phone_view, name='log_phone_view'),
    path('api/plot-reactions/<int:plot_id>/toggle/', views.toggle_plot_reaction, name='toggle_reaction'),
    path('api/plot-reactions/<int:plot_id>/get/', views.get_plot_reactions, name='get_reactions'),
    path('ajax/search/', views.ajax_search, name='ajax_search'),
]
