from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    label = "core"

    def ready(self) -> None:
        """Gate the Django admin behind a verified TOTP device.

        The API mandates TOTP for superadmins and revokes sessions server-side
        per request; a password-only /admin/ login on a plain session cookie
        would bypass both (2026-08-17 security audit, S3). Swapping the class
        here rather than in ``core/urls.py`` makes the gate hold from process
        start, not from the first URL resolution. An account with no confirmed
        device cannot enter the admin at all — the intended fail-closed
        posture.
        """
        from django.contrib import admin
        from django_otp.admin import OTPAdminSite

        admin.site.__class__ = OTPAdminSite
