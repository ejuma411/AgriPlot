from django.urls import path

from . import views


urlpatterns = [
    path("dashboard/notifications/", views.notifications_inbox, name="notifications_inbox"),
    path("contact-support/", views.contact_support, name="contact_support"),
]
