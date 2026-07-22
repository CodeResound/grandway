"""URL routes for the authenticate app (mounted at /api/v1/auth/)."""

from django.urls import path

from authenticate.views import (
    AccountBlockView,
    AccountDetailView,
    AccountEventsView,
    AccountListCreateView,
    AccountResetMfaView,
    AccountResetPasswordView,
    AccountRestoreView,
    AccountSessionListView,
    AccountSessionRevokeView,
    CurrentUserView,
    LoginView,
    LogoutView,
    MfaDisableView,
    MfaEnrollView,
    MfaVerifyView,
    OwnSessionListView,
    OwnSessionRevokeView,
    PasswordChangeView,
    RefreshView,
)

app_name = "auth"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshView.as_view(), name="refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", CurrentUserView.as_view(), name="me"),
    path("password/change/", PasswordChangeView.as_view(), name="password-change"),
    path("mfa/enroll/", MfaEnrollView.as_view(), name="mfa-enroll"),
    path("mfa/verify/", MfaVerifyView.as_view(), name="mfa-verify"),
    path("mfa/disable/", MfaDisableView.as_view(), name="mfa-disable"),
    # Own session management
    path("sessions/", OwnSessionListView.as_view(), name="session-list"),
    path("sessions/revoke/", OwnSessionRevokeView.as_view(), name="session-revoke"),
    # Account management (admin/superadmin)
    path("users/", AccountListCreateView.as_view(), name="user-list"),
    path("users/<uuid:user_id>/", AccountDetailView.as_view(), name="user-detail"),
    path("users/<uuid:user_id>/block/", AccountBlockView.as_view(), name="user-block"),
    path("users/<uuid:user_id>/restore/", AccountRestoreView.as_view(), name="user-restore"),
    path("users/<uuid:user_id>/reset-password/", AccountResetPasswordView.as_view(), name="user-reset-password"),
    path("users/<uuid:user_id>/reset-mfa/", AccountResetMfaView.as_view(), name="user-reset-mfa"),
    path("users/<uuid:user_id>/sessions/", AccountSessionListView.as_view(), name="user-session-list"),
    path("users/<uuid:user_id>/sessions/revoke/", AccountSessionRevokeView.as_view(), name="user-session-revoke"),
    path("users/<uuid:user_id>/events/", AccountEventsView.as_view(), name="user-events"),
]
