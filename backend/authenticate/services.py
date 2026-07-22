"""Business logic for the authenticate app.

All credential checks, session lifecycle, device limits, and audit writes live
here. Views pass validated data in and receive plain objects/dicts back.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from core.nepal.text import normalize_unicode, romanize_devanagari
from django.conf import settings
from django.contrib.auth import authenticate as django_authenticate
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from authenticate.constants import (
    CLAIM_AUTHORITY_TYPE,
    CLAIM_MUST_CHANGE_PASSWORD,
    CLAIM_SESSION_ID,
    REFRESH_TOKEN_BYTES,
    AuthEventType,
    AuthorityType,
    ProvisionedVia,
    SessionRevocationReason,
)
from authenticate.exceptions import (
    DeviceLimitError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    PasswordIncorrectError,
    RefreshTokenReuseError,
)
from authenticate.managers import UserManager
from authenticate.models import AuthEvent, AuthSession, User, UserSecurityState
from authenticate.selectors import (
    get_active_session_by_refresh_hash,
    get_session_by_refresh_hash,
)
from authenticate.validators import validate_password_strength

# ---------------------------------------------------------------------------
# Refresh-token helpers
# ---------------------------------------------------------------------------


def generate_refresh_token() -> str:
    """Return a fresh opaque URL-safe refresh token (never stored raw)."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw refresh token — the only form persisted."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def record_auth_event(
    *,
    event_type: str,
    subject_username: str,
    success: bool,
    actor: User | None = None,
    subject: User | None = None,
    reason: str = "",
    ip_address: str | None = None,
    user_agent: str = "",
    device_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> AuthEvent:
    """Append one immutable audit row. Never pass secrets in any field."""
    return AuthEvent.objects.create(
        event_type=event_type,
        actor=actor,
        subject=subject,
        subject_username=subject_username[:150],
        success=success,
        reason=reason[:100],
        ip_address=ip_address,
        user_agent=user_agent,
        device_id=device_id[:255],
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Account creation
# ---------------------------------------------------------------------------


def _apply_name_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Normalize name fields and auto-populate the romanized search field (§39.2/39.3)."""
    for key in ("display_name", "full_name_np", "full_name_en"):
        if fields.get(key):
            fields[key] = normalize_unicode(fields[key])
    if fields.get("full_name_np") and not fields.get("full_name_romanized"):
        fields["full_name_romanized"] = romanize_devanagari(fields["full_name_np"])
    return fields


@transaction.atomic
def create_account(
    *,
    username: str,
    password: str,
    authority_type: str,
    provisioned_via: str,
    actor: User | None = None,
    must_change_password: bool = True,
    **profile: Any,
) -> User:
    """Create a User + its UserSecurityState in one transaction.

    Shared by the bootstrap command and (future) admin account-creation flows.
    """
    profile = _apply_name_fields(profile)
    user = User.objects.create_user(
        username=username,
        password=password,
        authority_type=authority_type,
        **profile,
    )
    UserSecurityState.objects.create(
        user=user,
        must_change_password=must_change_password,
        provisioned_via=provisioned_via,
    )
    return user


# ---------------------------------------------------------------------------
# Login / sessions
# ---------------------------------------------------------------------------


def authenticate_user(request: Any, username: str, password: str) -> User | None:
    """Verify credentials through Django's auth (so django-axes observes attempts).

    Returns the user on success or ``None`` on any failure (wrong password,
    unknown user, blocked, or axes lockout) — uniformly, with no enumeration.
    ModelBackend runs a constant-time dummy hash for unknown users.
    """
    normalized = UserManager.normalize_username(username)
    try:
        user = django_authenticate(request, username=normalized, password=password)
    except PermissionDenied:
        # Raised by AxesStandaloneBackend when the (username, ip) pair is locked.
        return None
    return user


def _session_lifetimes() -> tuple[Any, Any]:
    now = timezone.now()
    return now + settings.AUTH_SESSION_IDLE_LIFETIME, now + settings.AUTH_SESSION_ABSOLUTE_LIFETIME


def build_access_token(user: User, session: AuthSession, must_change_password: bool) -> str:
    """Build a signed access JWT bound to a session (carries sid + authority claims)."""
    from rest_framework_simplejwt.tokens import AccessToken

    token = AccessToken.for_user(user)
    token[CLAIM_SESSION_ID] = str(session.id)
    token[CLAIM_AUTHORITY_TYPE] = user.authority_type
    token[CLAIM_MUST_CHANGE_PASSWORD] = must_change_password
    return str(token)


def revoke_session(session: AuthSession, reason: str) -> None:
    """Deactivate a single session (idempotent)."""
    if not session.is_active:
        return
    session.is_active = False
    session.revoked_at = timezone.now()
    session.revoked_reason = reason
    session.save(update_fields=["is_active", "revoked_at", "revoked_reason", "updated_at"])


def revoke_family(family_id: Any, reason: str) -> int:
    """Revoke every active session sharing a rotation family. Returns count."""
    count = 0
    for session in AuthSession.objects.filter(family_id=family_id, is_active=True):
        revoke_session(session, reason)
        count += 1
    return count


def revoke_all_user_sessions(user: User, reason: str) -> int:
    """Revoke every active session for a user (e.g. on password change/block)."""
    count = 0
    for session in AuthSession.objects.filter(user=user, is_active=True):
        revoke_session(session, reason)
        count += 1
    return count


@transaction.atomic
def issue_session(
    *,
    user: User,
    device_id: str,
    device_name: str = "",
    ip_address: str | None = None,
    user_agent: str = "",
) -> tuple[AuthSession, str]:
    """Create a device-bound session, enforcing per-device and device-count rules.

    - Re-login from the same device revokes that device's active session.
    - A new device beyond ``AUTH_MAX_ACTIVE_DEVICES`` raises ``DeviceLimitError``.
    Returns ``(session, raw_refresh_token)``; the raw token is returned once only.
    """
    active = list(AuthSession.objects.select_for_update().filter(user=user, is_active=True))
    same_device = next((s for s in active if s.device_id == device_id), None)
    if same_device is not None:
        revoke_session(same_device, SessionRevocationReason.REPLACED_SAME_DEVICE)
    elif len(active) >= settings.AUTH_MAX_ACTIVE_DEVICES:
        raise DeviceLimitError

    raw_token = generate_refresh_token()
    idle_expires_at, expires_at = _session_lifetimes()
    session = AuthSession.objects.create(
        user=user,
        device_id=device_id,
        device_name=device_name,
        refresh_token_hash=hash_refresh_token(raw_token),
        ip_address=ip_address,
        user_agent=user_agent,
        idle_expires_at=idle_expires_at,
        expires_at=expires_at,
    )
    return session, raw_token


def login(
    *,
    request: Any,
    username: str,
    password: str,
    device_id: str,
    device_name: str = "",
    ip_address: str | None = None,
    user_agent: str = "",
) -> dict[str, Any]:
    """Full login: verify credentials, issue a session, return tokens + user.

    Raises ``InvalidCredentialsError`` (uniform) or ``DeviceLimitError``.
    """
    user = authenticate_user(request, username, password)
    if user is None:
        record_auth_event(
            event_type=AuthEventType.LOGIN_FAILURE,
            subject_username=UserManager.normalize_username(username),
            success=False,
            reason="invalid_credentials",
            ip_address=ip_address,
            user_agent=user_agent,
            device_id=device_id,
        )
        raise InvalidCredentialsError

    security_state = _get_or_create_security_state(user)
    must_change = security_state.must_change_password

    try:
        session, raw_token = issue_session(
            user=user,
            device_id=device_id,
            device_name=device_name,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except DeviceLimitError:
        record_auth_event(
            event_type=AuthEventType.LOGIN_FAILURE,
            subject=user,
            subject_username=user.username,
            success=False,
            reason="device_limit_reached",
            ip_address=ip_address,
            user_agent=user_agent,
            device_id=device_id,
        )
        raise

    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

    record_auth_event(
        event_type=AuthEventType.LOGIN_SUCCESS,
        actor=user,
        subject=user,
        subject_username=user.username,
        success=True,
        reason="forced_password_change_pending" if must_change else "",
        ip_address=ip_address,
        user_agent=user_agent,
        device_id=device_id,
    )
    return {
        "access": build_access_token(user, session, must_change),
        "refresh": raw_token,
        "session": session,
        "user": user,
        "must_change_password": must_change,
    }


def refresh_session(
    *,
    raw_token: str,
    ip_address: str | None = None,
    user_agent: str = "",
) -> dict[str, Any]:
    """Rotate a refresh session: issue a new access + refresh, retire the old.

    Reuse of a retired token revokes the whole family (``RefreshTokenReuseError``).
    """
    token_hash = hash_refresh_token(raw_token)
    session = get_active_session_by_refresh_hash(token_hash)
    if session is None:
        stale = get_session_by_refresh_hash(token_hash)
        # Reuse detection fires only for a *rotated* (retired-by-refresh) token.
        # A token whose session was revoked for any other reason (logout, block,
        # a prior family kill) is simply invalid — not a fresh reuse event.
        if stale is not None and not stale.is_active and stale.revoked_reason == SessionRevocationReason.ROTATED:
            revoke_family(stale.family_id, SessionRevocationReason.ROTATED_REUSE)
            record_auth_event(
                event_type=AuthEventType.SESSION_REVOKED,
                subject=stale.user,
                subject_username=stale.user.username,
                success=False,
                reason="refresh_reuse_detected",
                ip_address=ip_address,
                user_agent=user_agent,
                device_id=stale.device_id,
            )
            raise RefreshTokenReuseError
        raise InvalidRefreshTokenError

    now = timezone.now()
    if now >= session.expires_at or now >= session.idle_expires_at or not session.user.is_active:
        revoke_session(session, SessionRevocationReason.ADMIN_REVOKED)
        raise InvalidRefreshTokenError

    with transaction.atomic():
        # Retire the old session FIRST so the one-active-session-per-device unique
        # constraint is never momentarily violated by two active rows.
        session.is_active = False
        session.revoked_at = now
        session.revoked_reason = SessionRevocationReason.ROTATED
        session.save(update_fields=["is_active", "revoked_at", "revoked_reason", "updated_at"])

        new_raw = generate_refresh_token()
        idle_expires_at = now + settings.AUTH_SESSION_IDLE_LIFETIME
        new_session = AuthSession.objects.create(
            user=session.user,
            device_id=session.device_id,
            device_name=session.device_name,
            refresh_token_hash=hash_refresh_token(new_raw),
            family_id=session.family_id,
            previous_session=session,
            ip_address=ip_address,
            user_agent=user_agent,
            idle_expires_at=idle_expires_at,
            expires_at=session.expires_at,
        )

    security_state = _get_or_create_security_state(session.user)
    must_change = security_state.must_change_password
    record_auth_event(
        event_type=AuthEventType.SESSION_REFRESHED,
        actor=session.user,
        subject=session.user,
        subject_username=session.user.username,
        success=True,
        ip_address=ip_address,
        user_agent=user_agent,
        device_id=session.device_id,
    )
    return {
        "access": build_access_token(session.user, new_session, must_change),
        "refresh": new_raw,
        "session": new_session,
        "user": session.user,
        "must_change_password": must_change,
    }


def logout(session: AuthSession, *, ip_address: str | None = None, user_agent: str = "") -> None:
    """Revoke the current session (logout of this device)."""
    revoke_session(session, SessionRevocationReason.LOGOUT)
    record_auth_event(
        event_type=AuthEventType.LOGOUT,
        actor=session.user,
        subject=session.user,
        subject_username=session.user.username,
        success=True,
        ip_address=ip_address,
        user_agent=user_agent,
        device_id=session.device_id,
    )


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------


def change_own_password(
    *,
    user: User,
    current_password: str,
    new_password: str,
    ip_address: str | None = None,
    user_agent: str = "",
) -> None:
    """Change a user's own password after confirming the current one.

    Validates strength (Django validators), stamps ``password_changed_at``,
    clears ``must_change_password``, and revokes ALL sessions (client re-logs in).
    Raises ``PasswordIncorrectError``; strength errors propagate as
    ``django.core.exceptions.ValidationError``.
    """
    if not user.check_password(current_password):
        record_auth_event(
            event_type=AuthEventType.PASSWORD_CHANGE,
            actor=user,
            subject=user,
            subject_username=user.username,
            success=False,
            reason="current_password_incorrect",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        raise PasswordIncorrectError

    validate_password_strength(new_password, user=user)

    security_state = _get_or_create_security_state(user)
    was_forced = security_state.must_change_password

    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password"])
        security_state.must_change_password = False
        security_state.password_changed_at = timezone.now()
        security_state.save(update_fields=["must_change_password", "password_changed_at", "updated_at"])
        revoke_all_user_sessions(user, SessionRevocationReason.PASSWORD_CHANGE)

    record_auth_event(
        event_type=AuthEventType.FORCED_PASSWORD_CHANGE if was_forced else AuthEventType.PASSWORD_CHANGE,
        actor=user,
        subject=user,
        subject_username=user.username,
        success=True,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def bootstrap_superadmin(
    *,
    username: str,
    password: str,
    display_name: str = "",
    email: str = "",
) -> tuple[User, bool]:
    """Create the initial superadmin. Idempotent: re-running returns the existing
    superadmin without creating a duplicate.

    Returns ``(user, created)``. Raises ``ValueError`` if the username exists but
    is not a superadmin.
    """
    normalized = UserManager.normalize_username(username)
    existing = User.objects.filter(username=normalized).first()
    if existing is not None:
        if existing.authority_type != AuthorityType.SUPERADMIN:
            raise ValueError(f"Username {normalized!r} already exists and is not a superadmin.")
        return existing, False

    user = create_account(
        username=normalized,
        password=password,
        authority_type=AuthorityType.SUPERADMIN,
        provisioned_via=ProvisionedVia.BOOTSTRAP_COMMAND,
        must_change_password=True,
        display_name=display_name or normalized,
        email=email,
    )
    record_auth_event(
        event_type=AuthEventType.SUPERADMIN_BOOTSTRAP,
        subject=user,
        subject_username=user.username,
        success=True,
        reason="bootstrap_command",
    )
    return user, True


def _get_or_create_security_state(user: User) -> UserSecurityState:
    state, _ = UserSecurityState.objects.get_or_create(
        user=user,
        defaults={"provisioned_via": ProvisionedVia.ADMIN_CREATED},
    )
    return state
