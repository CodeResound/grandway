"""Read-only query logic for the authenticate app (no side effects)."""

from __future__ import annotations

from django.db.models import QuerySet

from authenticate.managers import UserManager
from authenticate.models import AuthSession, User


def get_user_by_username(username: str) -> User | None:
    """Return the active-or-blocked user for a normalized username, or None."""
    normalized = UserManager.normalize_username(username)
    return User.objects.filter(username=normalized).select_related("security_state").first()


def get_active_sessions_for_user(user: User) -> QuerySet[AuthSession]:
    """All currently-active sessions for a user (one per device)."""
    return AuthSession.objects.filter(user=user, is_active=True).order_by("last_used_at")


def get_active_session_for_device(user: User, device_id: str) -> AuthSession | None:
    """The single active session bound to a given device, or None."""
    return AuthSession.objects.filter(user=user, device_id=device_id, is_active=True).first()


def get_active_session_by_refresh_hash(refresh_hash: str) -> AuthSession | None:
    """Active session whose refresh token hashes to ``refresh_hash``, or None."""
    return (
        AuthSession.objects.select_related("user", "user__security_state")
        .filter(refresh_token_hash=refresh_hash, is_active=True)
        .first()
    )


def get_session_by_refresh_hash(refresh_hash: str) -> AuthSession | None:
    """Any session (active or not) for a refresh hash — used for reuse detection."""
    return AuthSession.objects.filter(refresh_token_hash=refresh_hash).first()


def get_session_by_id(session_id: str) -> AuthSession | None:
    """Session by primary key (the JWT ``sid``), or None."""
    return AuthSession.objects.select_related("user", "user__security_state").filter(pk=session_id).first()
