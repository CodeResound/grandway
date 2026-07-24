"""Read-only query logic for the authenticate app (no side effects)."""

from __future__ import annotations

from django.db.models import QuerySet
from django_otp.plugins.otp_totp.models import TOTPDevice

from authenticate.constants import AuthorityType
from authenticate.managers import UserManager
from authenticate.models import AuthEvent, AuthSession, User

# Which authority tier each actor tier may manage (concept hierarchy):
# superadmin manages admins; admin manages lead managers; lead managers manage none.
_MANAGED_TIER: dict[str, str | None] = {
    AuthorityType.SUPERADMIN: AuthorityType.ADMIN,
    AuthorityType.ADMIN: AuthorityType.LEAD_MANAGER,
    AuthorityType.LEAD_MANAGER: None,
}


def managed_tier_for(actor: User) -> str | None:
    """The single authority tier this actor may manage, or None."""
    return _MANAGED_TIER.get(actor.authority_type)


# All accounts use a single TOTP device under this fixed name.
TOTP_DEVICE_NAME = "default"


def get_user_by_username(username: str) -> User | None:
    """Return the active-or-blocked user for a normalized username, or None."""
    normalized = UserManager.normalize_username(username)
    return User.objects.filter(username=normalized).select_related("security_state").first()


def get_active_user_by_id(user_id: str) -> User | None:
    """Return the active user with this id, or None.

    Added for the apps that assign work to a member of staff (``checklists`` is
    the first). Deliberately excludes deactivated accounts: a record whose owner
    can no longer log in is unowned in every sense that matters, and a client
    that assigned it would get a 200 back for work nobody will do.

    Authority-tier rules are the caller's business, not this selector's — one
    app may want to exclude Superadmins from an assignee picker while another
    does not, and encoding either preference here would push one app's policy
    onto the next.
    """
    return User.objects.filter(pk=user_id, is_active=True).first()


def get_active_admins() -> QuerySet[User]:
    """Every active account holding Admin authority, by username.

    Added for ``notifications``, which needs a recipient for an alert about a
    record nobody owns — an offer deadline, an expiring passport. Only
    ``checklists`` and ``leads`` carry ownership today, so most deadline alerts
    fall through to this fan-out.

    Deactivated accounts are excluded for the same reason
    ``get_active_user_by_id`` excludes them: writing to a queue nobody can log in
    to read is not delivery. Superadmins are excluded because they are a platform
    authority that does not participate in consultancy operations
    (``concepts/authenticate.txt``) — the one place this module does encode an
    authority-tier rule, and it does so because "who is an Admin" is this app's
    question, not the caller's.
    """
    return User.objects.filter(authority_type=AuthorityType.ADMIN, is_active=True).order_by("username")


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


def get_confirmed_totp_device(user: User) -> TOTPDevice | None:
    """The user's active, confirmed TOTP device, or None."""
    return TOTPDevice.objects.filter(user=user, name=TOTP_DEVICE_NAME, confirmed=True).first()


def get_unconfirmed_totp_device(user: User) -> TOTPDevice | None:
    """The user's pending (unconfirmed) TOTP device, or None."""
    return TOTPDevice.objects.filter(user=user, name=TOTP_DEVICE_NAME, confirmed=False).first()


def has_confirmed_mfa(user: User) -> bool:
    """Whether the user has completed MFA enrollment (derived — never stored)."""
    return TOTPDevice.objects.filter(user=user, name=TOTP_DEVICE_NAME, confirmed=True).exists()


def get_manageable_users(actor: User) -> QuerySet[User]:
    """Accounts the actor is authorized to manage (their one managed tier)."""
    tier = managed_tier_for(actor)
    if tier is None:
        return User.objects.none()
    return User.objects.filter(authority_type=tier).select_related("security_state").order_by("username")


def get_manageable_user(actor: User, user_id: str) -> User | None:
    """A single account within the actor's managed tier, or None."""
    return get_manageable_users(actor).filter(pk=user_id).first()


def get_user_session_by_id(user: User, session_id: str) -> AuthSession | None:
    """A session belonging to ``user`` by id (active or not), or None."""
    return AuthSession.objects.filter(user=user, pk=session_id).first()


def get_events_for_user(user: User) -> QuerySet[AuthEvent]:
    """Authentication audit events where ``user`` is the subject, newest first."""
    return AuthEvent.objects.filter(subject=user).select_related("actor").order_by("-created_at")
