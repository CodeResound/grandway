from django.contrib import admin
from django.urls import include, path

from core.views import health, ready

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("ready/", ready, name="ready"),
    path("api/v1/", include("core.api_urls", namespace="v1")),
]
