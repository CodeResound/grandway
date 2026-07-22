"""Thin views for the authenticate app.

Views receive the request, validate input, call a service, translate domain
exceptions into the standard error envelope, and shape the response. No business
logic lives here.
"""

from __future__ import annotations

from typing import Any

from core.pagination import StandardPagination
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
    InvalidAuthorityError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    MfaAlreadyEnrolledError,
    MfaInvalidError,
    MfaMandatoryError,
    MfaNotEnrolledError,
    MfaRequiredError,
    NotManageableError,
    PasswordIncorrectError,
    RefreshTokenReuseError,
    SessionNotFoundError,
    UsernameTakenError,
)
from authenticate.selectors import (
    get_active_sessions_for_user,
    get_events_for_user,
    get_manageable_users,
)
from authenticate.serializers import (
    AccountCreateSerializer,
    AccountUpdateSerializer,
    AdminResetPasswordSerializer,
    AuthEventSerializer,
    BlockAccountSerializer,
    CurrentUserSerializer,
    LoginSerializer,
    MfaDisableSerializer,
    MfaVerifySerializer,
    PasswordChangeSerializer,
    RefreshSerializer,
    RevokeOwnSessionsSerializer,
    RevokeTargetSessionsSerializer,
    SessionSerializer,
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


# ---------------------------------------------------------------------------
# Phase 3 — account & session management (inline authority-hierarchy checks)
# ---------------------------------------------------------------------------


def _resolve_target(request: Request, user_id: str) -> tuple[object | None, Response | None]:
    """Return (target, None) or (None, 404 response) if not in the actor's authority."""
    try:
        return services.get_managed_target(request.user, user_id), None
    except NotManageableError:
        return None, error_response(
            ErrorCode.USER_NOT_FOUND,
            "User not found.",
            http_status=status.HTTP_404_NOT_FOUND,
        )


class AccountListCreateView(APIView):
    """GET/POST /api/v1/auth/users/ — list or create accounts within your tier."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        queryset = get_manageable_users(request.user)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = CurrentUserSerializer(page if page is not None else queryset, many=True)
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return success_response(data=serializer.data, message="Accounts retrieved.")

    def post(self, request: Request) -> Response:
        serializer = AccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            user, temp_password = services.create_managed_account(
                actor=request.user,
                username=data["username"],
                authority_type=data["authority_type"],
                password=data.get("password"),
                display_name=data.get("display_name", ""),
                full_name_np=data.get("full_name_np", ""),
                full_name_en=data.get("full_name_en", ""),
                email=data.get("email", ""),
                phone=data.get("phone", ""),
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except InvalidAuthorityError:
            return error_response(
                ErrorCode.INVALID_AUTHORITY,
                "You may not create an account of that authority level.",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        except UsernameTakenError:
            return error_response(
                ErrorCode.USERNAME_TAKEN,
                "That username is already in use.",
                http_status=status.HTTP_409_CONFLICT,
            )
        payload = {"user": CurrentUserSerializer(user).data}
        if temp_password is not None:
            payload["temporary_password"] = temp_password
        return success_response(data=payload, message="Account created.", http_status=status.HTTP_201_CREATED)


class AccountDetailView(APIView):
    """GET/PATCH /api/v1/auth/users/<id>/ — read or edit a managed account."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        return success_response(data=CurrentUserSerializer(target).data, message="Account retrieved.")

    def patch(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        serializer = AccountUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = services.update_managed_account(
            actor=request.user,
            target=target,
            fields=serializer.validated_data,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
        return success_response(data=CurrentUserSerializer(updated).data, message="Account updated.")


class AccountBlockView(APIView):
    """POST /api/v1/auth/users/<id>/block/ — block a managed account."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        serializer = BlockAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.block_account(
            actor=request.user,
            target=target,
            reason=serializer.validated_data.get("reason", ""),
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
        return success_response(message="Account blocked.")


class AccountRestoreView(APIView):
    """POST /api/v1/auth/users/<id>/restore/ — restore a blocked account."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        services.restore_account(
            actor=request.user,
            target=target,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
        return success_response(message="Account restored.")


class AccountResetPasswordView(APIView):
    """POST /api/v1/auth/users/<id>/reset-password/ — administrative password reset."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        serializer = AdminResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            temp_password = services.admin_reset_password(
                actor=request.user,
                target=target,
                new_password=serializer.validated_data.get("password"),
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except DjangoValidationError as exc:
            return error_response(
                ErrorCode.PASSWORD_WEAK,
                "Password does not meet strength requirements.",
                details={"password": list(exc.messages)},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        payload = {"temporary_password": temp_password} if temp_password is not None else {}
        return success_response(data=payload, message="Password reset. The user must change it at next login.")


class AccountResetMfaView(APIView):
    """POST /api/v1/auth/users/<id>/reset-mfa/ — administrative MFA removal."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        services.admin_reset_mfa(
            actor=request.user,
            target=target,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
        return success_response(message="MFA reset. The user may enroll again.")


class AccountSessionListView(APIView):
    """GET /api/v1/auth/users/<id>/sessions/ — list a managed account's active sessions."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        sessions = get_active_sessions_for_user(target)
        return success_response(data=SessionSerializer(sessions, many=True).data, message="Sessions retrieved.")


class AccountSessionRevokeView(APIView):
    """POST /api/v1/auth/users/<id>/sessions/revoke/ — revoke one or all sessions."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        serializer = RevokeTargetSessionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_id = serializer.validated_data.get("session_id")
        try:
            count = services.revoke_target_sessions(
                actor=request.user,
                target=target,
                session_id=str(session_id) if session_id else None,
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except SessionNotFoundError:
            return error_response(
                ErrorCode.SESSION_NOT_FOUND,
                "Session not found for this user.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return success_response(data={"revoked": count}, message="Sessions revoked.")


class AccountEventsView(APIView):
    """GET /api/v1/auth/users/<id>/events/ — review a managed account's auth activity."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, user_id: str) -> Response:
        target, err = _resolve_target(request, user_id)
        if err:
            return err
        events = get_events_for_user(target)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(events, request)
        serializer = AuthEventSerializer(page if page is not None else events, many=True)
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return success_response(data=serializer.data, message="Events retrieved.")


class OwnSessionListView(APIView):
    """GET /api/v1/auth/sessions/ — list your own active sessions."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        sessions = get_active_sessions_for_user(request.user)
        return success_response(data=SessionSerializer(sessions, many=True).data, message="Sessions retrieved.")


class OwnSessionRevokeView(APIView):
    """POST /api/v1/auth/sessions/revoke/ — revoke one/others/all of your own sessions."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = RevokeOwnSessionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_id = serializer.validated_data.get("session_id")
        current = getattr(request.user, "auth_session", None)
        try:
            count = services.revoke_own_sessions(
                user=request.user,
                session_id=str(session_id) if session_id else None,
                current_session_id=str(current.id) if current else None,
                others_only=serializer.validated_data.get("others_only", False),
            )
        except SessionNotFoundError:
            return error_response(
                ErrorCode.SESSION_NOT_FOUND,
                "Session not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        response = success_response(data={"revoked": count}, message="Sessions revoked.")
        _clear_refresh_cookie(response)
        return response
