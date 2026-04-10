from django.urls import path

from security import views_otp


urlpatterns = [
    path("send-otp/", views_otp.send_otp_verification, name="send_otp"),
    path("verify-otp/", views_otp.verify_otp, name="verify_otp"),
    path("resend-otp/", views_otp.resend_otp, name="resend_otp"),
    path("verify-email/<str:token>/", views_otp.verify_email, name="verify_email"),
    path("resend-email-verification/", views_otp.resend_email_verification, name="resend_email_verification"),
]
