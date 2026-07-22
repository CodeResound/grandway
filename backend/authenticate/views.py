"""Thin views for the authenticate app.

Views receive the request, validate input, call a service, translate domain
exceptions into the standard error envelope, and shape the response. No business
logic lives here.
"""

from __future__ import annotations

from typing import Any

from core.responses import error_response, success_response
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from authenticate import services
from authenticate.constants import ErrorCode
from authenticate.exceptions import (
    DeviceLimitError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    MfaAlreadyEnrolledError,
    MfaInvalidError,
    MfaMandatoryError,
    MfaNotEnrolledError,
    MfaRequiredError,
    PasswordIncorrectError,
    RefreshTokenReuseError,
)
from authenticate.serializers import (
    CurrentUserSerializer,
    LoginSerializer,
    MfaDisableSerializer,
    MfaVerifySerializer,
    PasswordChangeSerializer,
    RefreshSerializer,
)
from authenticate.throttling import LoginIPThrottle, LoginUsernameThrottle, RefreshThrottle


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _user_agent(request: Request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:2000]


def _emit_refresh(response: Response, raw_token: str) -> None:
    """Return the refresh token via HttpOnly cookie (prod) or response body (dev)."""
    if settings.AUTH_REFRESH_COOKIE_ENABLED:
        response.set_cookie(
            settings.AUTH_REFRESH_COOKIE_NAME,
            raw_token,
            secure=settings.AUTH_REFRESH_COOKIE_SECURE,
            httponly=settings.AUTH_REFRESH_COOKIE_HTTPONLY,
            samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
            path=settings.AUTH_REFRESH_COOKIE_PATH,
        )
    else:
        response.data["data"]["refresh"] = raw_token


def _clear_refresh_cookie(response: Response) -> None:
    if settings.AUTH_REFRESH_COOKIE_ENABLED:
        response.delete_cookie(
            settings.AUTH_REFRESH_COOKIE_NAME,
            path=settings.AUTH_REFRESH_COOKIE_PATH,
        )


def _resolve_refresh_token(request: Request, validated: dict[str, Any]) -> str:
    """Prefer the HttpOnly cookie (prod); fall back to the request body (dev)."""
    if settings.AUTH_REFRESH_COOKIE_ENABLED:
        return request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME, "")
    return validated.get("refresh", "")


class LoginView(APIView):
    """POST /api/v1/auth/login/ — public. Verify credentials, open a device session."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginIPThrottle, LoginUsernameThrottle]

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = services.login(
                request=request,
                username=data["username"],
                password=data["password"],
                device_id=data["device_id"],
                device_name=data.get("device_name", ""),
                otp_code=data.get("otp_code", ""),
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except InvalidCredentialsError:
            return error_response(
                ErrorCode.CREDENTIALS_INVALID,
                "Invalid username or password.",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )
        except MfaRequiredError:
            return error_response(
                ErrorCode.MFA_REQUIRED,
                "An authenticator code is required to complete login.",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )
        except MfaInvalidError:
            return error_response(
                ErrorCode.MFA_INVALID,
                "The authenticator code is invalid or expired.",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )
        except DeviceLimitError:
            return error_response(
                ErrorCode.DEVICE_LIMIT_REACHED,
                "You are signed in on the maximum number of devices. Log out of another device first.",
                http_status=status.HTTP_409_CONFLICT,
            )

        response = success_response(
            data={
                "access": result["access"],
                "must_change_password": result["must_change_password"],
                "mfa_enrollment_required": result["mfa_enrollment_required"],
                "user": CurrentUserSerializer(result["user"]).data,
            },
            message="Login successful.",
        )
        _emit_refresh(response, result["refresh"])
        return response


class RefreshView(APIView):
    """POST /api/v1/auth/refresh/ — public. Rotate a refresh session."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [RefreshThrottle]

    def post(self, request: Request) -> Response:
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_token = _resolve_refresh_token(request, serializer.validated_data)

        if not raw_token:
            return error_response(
                ErrorCode.REFRESH_INVALID,
                "No refresh credential supplied.",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            result = services.refresh_session(
                raw_token=raw_token,
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except RefreshTokenReuseError:
            response = error_response(
                ErrorCode.REFRESH_REUSED,
                "Refresh token reuse detected; all sessions for this device family were revoked.",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_refresh_cookie(response)
            return response
        except InvalidRefreshTokenError:
            response = error_response(
                ErrorCode.REFRESH_INVALID,
                "Refresh credential is invalid or expired.",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_refresh_cookie(response)
            return response

        response = success_response(
            data={
                "access": result["access"],
                "must_change_password": result["must_change_password"],
            },
            message="Token refreshed.",
        )
        _emit_refresh(response, result["refresh"])
        return response


class LogoutView(APIView):
    """POST /api/v1/auth/logout/ — authenticated. Revoke the current session."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        session = getattr(request.user, "auth_session", None)
        if session is not None:
            services.logout(
                session,
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        response = success_response(message="Logged out.")
        _clear_refresh_cookie(response)
        return response


class CurrentUserView(APIView):
    """GET /api/v1/auth/me/ — authenticated. The current user."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return success_response(
            data=CurrentUserSerializer(request.user).data,
            message="Current user.",
        )


class PasswordChangeView(APIView):
    """POST /api/v1/auth/password/change/ — authenticated self-service.

    Allowed while `must_change_password` is set (this is how a user clears it).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            services.change_own_password(
                user=request.user,
                current_password=data["current_password"],
                new_password=data["new_password"],
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except PasswordIncorrectError:
            return error_response(
                ErrorCode.PASSWORD_INCORRECT,
                "Current password is incorrect.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except DjangoValidationError as exc:
            return error_response(
                ErrorCode.PASSWORD_WEAK,
                "New password does not meet strength requirements.",
                details={"new_password": list(exc.messages)},
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        response = success_response(
            message="Password changed. Please log in again.",
        )
        _clear_refresh_cookie(response)
        return response


class MfaEnrollView(APIView):
    """POST /api/v1/auth/mfa/enroll/ — authenticated. Begin TOTP enrollment.

    Returns the secret + otpauth URL once; the client shows a QR / manual key,
    then confirms with a code via `mfa/verify/`.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        try:
            result = services.begin_mfa_enrollment(request.user)
        except MfaAlreadyEnrolledError:
            return error_response(
                ErrorCode.MFA_ALREADY_ENROLLED,
                "MFA is already enabled for this account.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return success_response(
            data={"secret": result["secret"], "otpauth_url": result["otpauth_url"]},
            message="Scan the code in an authenticator app, then confirm.",
        )


class MfaVerifyView(APIView):
    """POST /api/v1/auth/mfa/verify/ — authenticated. Confirm/activate MFA."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = MfaVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.confirm_mfa_enrollment(
                request.user,
                serializer.validated_data["code"],
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except MfaAlreadyEnrolledError:
            return error_response(
                ErrorCode.MFA_ALREADY_ENROLLED,
                "MFA is already enabled for this account.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except MfaNotEnrolledError:
            return error_response(
                ErrorCode.MFA_NOT_ENROLLED,
                "Start enrollment before confirming a code.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except MfaInvalidError:
            return error_response(
                ErrorCode.MFA_INVALID,
                "The authenticator code is invalid or expired.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(message="MFA enabled.")


class MfaDisableView(APIView):
    """POST /api/v1/auth/mfa/disable/ — authenticated self-service.

    Superadmin MFA is mandatory and cannot be self-disabled. Revokes all sessions.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = MfaDisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            services.disable_mfa(
                request.user,
                data["current_password"],
                data["code"],
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except MfaMandatoryError:
            return error_response(
                ErrorCode.MFA_MANDATORY,
                "MFA is mandatory for this account and cannot be disabled.",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        except MfaNotEnrolledError:
            return error_response(
                ErrorCode.MFA_NOT_ENROLLED,
                "MFA is not enabled for this account.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except PasswordIncorrectError:
            return error_response(
                ErrorCode.PASSWORD_INCORRECT,
                "Current password is incorrect.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except MfaInvalidError:
            return error_response(
                ErrorCode.MFA_INVALID,
                "The authenticator code is invalid or expired.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        response = success_response(message="MFA disabled. Please log in again.")
        _clear_refresh_cookie(response)
        return response
