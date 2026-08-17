"""Request/response serializers for the authenticate app.

Serializers own input validation and output shaping only. Never pass raw request
dicts into services — always validated data.
"""

from __future__ import annotations

from core.nepal.text import normalize_unicode
from rest_framework import serializers

from authenticate.constants import AuthorityType
from authenticate.models import AuthEvent, AuthSession, User
from authenticate.selectors import has_confirmed_mfa
from authenticate.services import is_mfa_mandatory


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    device_id = serializers.CharField(max_length=255)
    device_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    otp_code = serializers.CharField(max_length=10, required=False, allow_blank=True, default="")


class MfaVerifySerializer(serializers.Serializer):
    code = serializers.CharField(max_length=10)


class MfaDisableSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    code = serializers.CharField(max_length=10)


class RefreshSerializer(serializers.Serializer):
    # Optional in the body: production reads the refresh token from an HttpOnly
    # cookie instead. The view resolves the effective token from body-or-cookie.
    refresh = serializers.CharField(required=False, allow_blank=True, default="")


class PasswordChangeSerializer(serializers.Serializer):
    # Strength is enforced in the service so the view can return the specific
    # AUTH_PASSWORD_WEAK code; the serializer only checks presence/shape here.
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)


class CurrentUserSerializer(serializers.ModelSerializer):
    """Read shape for the authenticated user (`/me`)."""

    must_change_password = serializers.SerializerMethodField()
    mfa_enabled = serializers.SerializerMethodField()
    mfa_enrollment_required = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "authority_type",
            "display_name",
            "full_name",
            "email",
            "phone",
            "is_active",
            "must_change_password",
            "mfa_enabled",
            "mfa_enrollment_required",
            "last_login",
            "created_at",
        ]
        read_only_fields = fields

    def get_must_change_password(self, obj: User) -> bool:
        state = getattr(obj, "security_state", None)
        return bool(state and state.must_change_password)

    def get_mfa_enabled(self, obj: User) -> bool:
        # The account list annotates has_mfa (selectors.get_manageable_users)
        # so a page costs one subquery, not two device queries per row; the
        # single-object /me path has no annotation and falls back.
        has_mfa = getattr(obj, "has_mfa", None)
        if has_mfa is not None:
            return bool(has_mfa)
        return has_confirmed_mfa(obj)

    def get_mfa_enrollment_required(self, obj: User) -> bool:
        return is_mfa_mandatory(obj) and not self.get_mfa_enabled(obj)


# --- Phase 3: account & session management ---------------------------------


def _norm(value: str | None) -> str | None:
    return normalize_unicode(value) if value else value


class AccountCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    authority_type = serializers.ChoiceField(choices=AuthorityType.choices)
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    password = serializers.CharField(
        write_only=True, required=False, allow_null=True, default=None, trim_whitespace=False
    )

    def validate_display_name(self, value: str) -> str:
        return _norm(value) or ""

    def validate_full_name(self, value: str) -> str:
        return _norm(value) or ""


class AccountUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255, required=False)
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)

    def validate_display_name(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_full_name(self, value: str) -> str:
        return _norm(value) or ""


class BlockAccountSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_reason(self, value: str) -> str:
        return _norm(value) or ""


class AdminResetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(
        write_only=True, required=False, allow_null=True, default=None, trim_whitespace=False
    )


class RevokeTargetSessionsSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class RevokeOwnSessionsSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    others_only = serializers.BooleanField(required=False, default=False)


class SessionSerializer(serializers.ModelSerializer):
    """Read shape for an AuthSession (self or admin session listing)."""

    class Meta:
        model = AuthSession
        fields = [
            "id",
            "device_id",
            "device_name",
            "ip_address",
            "user_agent",
            "is_active",
            "revoked_reason",
            "revoked_at",
            "last_used_at",
            "idle_expires_at",
            "expires_at",
            "created_at",
        ]
        read_only_fields = fields


class AuthEventSerializer(serializers.ModelSerializer):
    """Read shape for an authentication audit event (never exposes secrets)."""

    actor_username = serializers.CharField(source="actor.username", default=None, read_only=True)

    class Meta:
        model = AuthEvent
        fields = [
            "id",
            "event_type",
            "actor_username",
            "subject_username",
            "success",
            "reason",
            "ip_address",
            "device_id",
            "created_at",
        ]
        read_only_fields = fields
