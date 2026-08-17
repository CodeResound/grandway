from django.contrib import admin
from django.urls import include, path

from core.views import health, ready

# /admin/ is OTP-gated: core.apps.CoreConfig.ready() swaps admin.site to
# django_otp's OTPAdminSite (2026-08-17 security audit, S3).
urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("ready/", ready, name="ready"),
    path("api/v1/", include("core.api_urls", namespace="v1")),
]
