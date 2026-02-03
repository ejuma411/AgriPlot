from django.urls import path
from . import views

app_name= 'listings'

urlpatterns = [
    path('', views.home, name='home'),
    path('add_plot/', views.add_plot, name="add_plot"),
    path('plot/<int:id>/', views.plot_detail, name='plot_detail'),
    path('plot/<int:id>/edit/', views.edit_plot, name='edit_plot'), 
    path('plot/<int:plot_id>/upload/', views.upload_verification_doc, name='upload_verification'),
    path('verify/dashboard/', views.verification_dashboard, name='verification_dashboard'),
    path('verify/plot/<int:plot_id>/', views.review_plot, name='review_plot'),
    

    path('image/<int:id>/delete/', views.delete_image, name='delete_image'),


    # BROKER & SELLER REGISTRATION
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
]
