"""Request/response serializers for the authenticate app.

Serializers own input validation and output shaping only. Never pass raw request
dicts into services — always validated data.
"""

from __future__ import annotations

from rest_framework import serializers

from authenticate.models import User
from authenticate.selectors import has_confirmed_mfa
from authenticate.services import mfa_enrollment_required


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
            "full_name_np",
            "full_name_en",
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
        return has_confirmed_mfa(obj)

    def get_mfa_enrollment_required(self, obj: User) -> bool:
        return mfa_enrollment_required(obj)
