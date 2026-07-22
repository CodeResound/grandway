"""Django admin registration for the authenticate app.

Sensitive material (password hash, refresh-token hash) is never editable and the
password hash is never displayed. Admin never bypasses application validation.
"""

from __future__ import annotations

from django.contrib import admin

from authenticate.models import AuthEvent, AuthSession, User, UserSecurityState


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "authority_type", "display_name", "is_active", "is_staff", "created_at")
    list_filter = ("authority_type", "is_active", "is_staff")
    search_fields = ("username", "display_name", "full_name_np", "full_name_en", "full_name_romanized", "email")
    readonly_fields = ("id", "password", "last_login", "created_at", "updated_at", "full_name_romanized")
    ordering = ("username",)


@admin.register(UserSecurityState)
class UserSecurityStateAdmin(admin.ModelAdmin):
    list_display = ("user", "must_change_password", "password_changed_at", "provisioned_via", "blocked_at")
    list_filter = ("must_change_password", "provisioned_via")
    search_fields = ("user__username",)
    readonly_fields = ("id", "created_at", "updated_at", "password_changed_at")


@admin.register(AuthSession)
class AuthSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device_id", "is_active", "last_used_at", "expires_at", "revoked_reason")
    list_filter = ("is_active", "revoked_reason")
    search_fields = ("user__username", "device_id", "device_name")
    readonly_fields = (
        "id",
        "user",
        "device_id",
        "device_name",
        "refresh_token_hash",
        "family_id",
        "previous_session",
        "ip_address",
        "user_agent",
        "last_used_at",
        "idle_expires_at",
        "expires_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: object) -> bool:
        return False


@admin.register(AuthEvent)
class AuthEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "subject_username", "success", "reason", "ip_address", "created_at")
    list_filter = ("event_type", "success")
    search_fields = ("subject_username", "reason", "device_id")
    readonly_fields = (
        "id",
        "event_type",
        "actor",
        "subject",
        "subject_username",
        "success",
        "reason",
        "ip_address",
        "user_agent",
        "device_id",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
