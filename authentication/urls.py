from django.urls import path

from authentication import views_auth


urlpatterns = [
    path("two-factor/setup/", views_auth.two_factor_setup, name="two_factor_setup"),
    path("two-factor/verify/", views_auth.two_factor_verify, name="two_factor_verify"),
    path("sessions/signout-all/", views_auth.sign_out_all_sessions, name="sign_out_all_sessions"),
    path(
        "password-reset/",
        views_auth.CustomPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/confirm/",
        views_auth.password_reset_confirm_request,
        name="password_reset_confirm_request",
    ),
    path(
        "password-reset/done/",
        views_auth.CustomPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        views_auth.CustomPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        views_auth.CustomPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]

