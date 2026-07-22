"""URL routes for the authenticate app (mounted at /api/v1/auth/)."""

from django.urls import path

from authenticate.views import (
    CurrentUserView,
    LoginView,
    LogoutView,
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
]
