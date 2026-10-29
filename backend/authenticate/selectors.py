"""Read-only query logic for the authenticate app (no side effects)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.db.models.functions import Lower
from django_otp.plugins.otp_totp.models import TOTPDevice

from authenticate.constants import CLIPBOARD_UNCATEGORIZED, AuthorityType
from authenticate.managers import UserManager
from authenticate.models import AuthEvent, AuthSession, ClipboardCategory, ClipboardEntry, User

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


def get_active_lead_actors() -> QuerySet[User]:
    """Every active Admin and Lead Manager, by username — everyone who works the files.

    Added for ``notifications`` (2026-10-29): an event about an applicant nobody
    is assigned to goes to the whole team. Superadmins are excluded for the same
    reason ``get_active_admins`` excludes them.
    """
    return User.objects.filter(
        authority_type__in=(AuthorityType.ADMIN, AuthorityType.LEAD_MANAGER), is_active=True
    ).order_by("username")


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


def get_active_session_by_refresh_hash_for_update(refresh_hash: str) -> AuthSession | None:
    """As above, but locking the session row for the caller's transaction.

    Rotation is a read-then-write: refresh reads the active session, retires it,
    and inserts its replacement. Without a lock two requests carrying the same
    token both read the row as active, both retire it, and both insert — and the
    second insert violates ``uniq_active_session_per_device``, surfacing as a 500
    and logging the user out. That is not an exotic interleaving: an expired
    access token makes every in-flight request 401 at once, and a client that
    refreshes on 401 fires several rotations for one token as a matter of course.

    ``of=("self",)`` locks the session row alone. ``select_related`` pulls
    ``user__security_state`` through a LEFT OUTER JOIN (a reverse one-to-one),
    and PostgreSQL refuses ``FOR UPDATE`` against the nullable side of an outer
    join — so an unqualified lock here would fail on the production engine while
    passing on SQLite. Must be called inside ``transaction.atomic()``.
    """
    return (
        AuthSession.objects.select_related("user", "user__security_state")
        .select_for_update(of=("self",))
        .filter(refresh_token_hash=refresh_hash, is_active=True)
        .first()
    )


def get_session_by_refresh_hash(refresh_hash: str) -> AuthSession | None:
    """Any session (active or not) for a refresh hash — used for reuse detection."""
    return AuthSession.objects.filter(refresh_token_hash=refresh_hash).first()


def get_active_session_in_family(family_id: Any) -> AuthSession | None:
    """The live session of a rotation family (at most one per device), or None."""
    return (
        AuthSession.objects.select_related("user", "user__security_state")
        .filter(family_id=family_id, is_active=True)
        .first()
    )


def get_session_by_id(session_id: str) -> AuthSession | None:
    """Session by primary key (the JWT ``sid``), or None."""
    return AuthSession.objects.select_related("user", "user__security_state").filter(pk=session_id).first()


def get_confirmed_totp_devices(user: User) -> QuerySet[TOTPDevice]:
    """Every confirmed TOTP device for this user, whatever its name.

    **Deliberately not scoped to ``TOTP_DEVICE_NAME``.** This app's own
    enrollment only ever creates ``"default"``, but ``django_otp.plugins.otp_totp``
    is installed and registers ``TOTPDevice`` in the Django admin, so a device
    can arrive under another name. Scoping the *detection* of MFA to one name
    while ``reset_mfa``/``disable_mfa`` delete across all names left the two
    disagreeing in the dangerous direction: a confirmed device the user could
    see in the admin, believed was protecting the account, and which login
    silently ignored. Asking "does any confirmed device exist" fails closed.
    """
    return TOTPDevice.objects.filter(user=user, confirmed=True)


def get_confirmed_totp_device(user: User) -> TOTPDevice | None:
    """The user's active, confirmed TOTP device, or None (see above on naming)."""
    return get_confirmed_totp_devices(user).first()


def get_unconfirmed_totp_device(user: User) -> TOTPDevice | None:
    """The user's pending (unconfirmed) TOTP device, or None.

    Name-scoped, unlike the confirmed lookups: this addresses the enrollment
    *this app* started, and picking up a half-finished device from somewhere
    else would let ``mfa/verify/`` confirm a secret the user never scanned here.
    """
    return TOTPDevice.objects.filter(user=user, name=TOTP_DEVICE_NAME, confirmed=False).first()


def has_confirmed_mfa(user: User) -> bool:
    """Whether the user has completed MFA enrollment (derived — never stored)."""
    return get_confirmed_totp_devices(user).exists()


def get_manageable_users(actor: User) -> QuerySet[User]:
    """Accounts the actor is authorized to manage (their one managed tier).

    ``has_mfa`` is annotated so the account list's two MFA fields read one
    subquery result per row instead of issuing up to two ``TOTPDevice``
    queries per user (2026-08-17 audit, P2). Same rule as
    ``get_confirmed_totp_devices``: any confirmed device counts, whatever its
    name.
    """
    tier = managed_tier_for(actor)
    if tier is None:
        return User.objects.none()
    return (
        User.objects.filter(authority_type=tier)
        .select_related("security_state")
        .annotate(has_mfa=Exists(TOTPDevice.objects.filter(user=OuterRef("pk"), confirmed=True)))
        .order_by("username")
    )


def get_manageable_user(actor: User, user_id: str) -> User | None:
    """A single account within the actor's managed tier, or None."""
    return get_manageable_users(actor).filter(pk=user_id).first()


def get_user_session_by_id(user: User, session_id: str) -> AuthSession | None:
    """A session belonging to ``user`` by id (active or not), or None."""
    return AuthSession.objects.filter(user=user, pk=session_id).first()


def get_events_for_user(user: User) -> QuerySet[AuthEvent]:
    """Authentication audit events where ``user`` is the subject, newest first."""
    return AuthEvent.objects.filter(subject=user).select_related("actor").order_by("-created_at")


def get_auth_event_counts_for_user(user: User, since: datetime) -> list[dict[str, Any]]:
    """``AuthEvent`` counts about ``user`` since ``since``, grouped by type/reason/outcome.

    Matches on ``subject_username`` as well as ``subject`` because failed logins
    are recorded by username alone. Feeds the ``auth_session_report`` command.
    """
    return list(
        AuthEvent.objects.filter(Q(subject=user) | Q(subject_username=user.username), created_at__gte=since)
        .values("event_type", "reason", "success")
        .annotate(count=Count("id"))
        .order_by("event_type", "reason", "success")
    )


def get_session_revocation_counts_for_user(user: User, since: datetime) -> list[dict[str, Any]]:
    """``AuthSession`` rows of ``user`` revoked since ``since``, counted per ``revoked_reason``."""
    return list(
        AuthSession.objects.filter(user=user, revoked_at__gte=since)
        .values("revoked_reason")
        .annotate(count=Count("id"))
        .order_by("revoked_reason")
    )


# ---------------------------------------------------------------------------
# Personal clipboard (2026-10-29) — every query starts from the owner
# ---------------------------------------------------------------------------


def get_own_clipboard(
    user: User,
    *,
    field_keys: list[str] | None = None,
    category: str | None = None,
    search: str | None = None,
) -> QuerySet[ClipboardEntry]:
    """This user's clipboard, most used first. Never another account's rows.

    ``category`` is a category id, or ``none`` for entries in no category.
    ``search`` matches the label, the text, or the category name.
    """
    queryset = ClipboardEntry.objects.select_related("category").filter(user=user)
    if field_keys:
        queryset = queryset.filter(field_key__in=field_keys)
    if category == CLIPBOARD_UNCATEGORIZED:
        queryset = queryset.filter(category__isnull=True)
    elif category:
        queryset = queryset.filter(category_id=category)
    if search:
        queryset = queryset.filter(
            Q(label__icontains=search) | Q(text__icontains=search) | Q(category__name__icontains=search)
        )
    return queryset


def get_own_clipboard_entry(user: User, entry_id: Any) -> ClipboardEntry | None:
    """One of this user's entries, or None — another account's id reads as missing."""
    return ClipboardEntry.objects.select_related("category").filter(user=user, pk=entry_id).first()


def count_own_clipboard_entries(user: User) -> int:
    return ClipboardEntry.objects.filter(user=user).count()


def get_own_clipboard_categories(user: User) -> QuerySet[ClipboardCategory]:
    """This user's categories by name (ignoring case), each with ``entry_count``.

    Ordered explicitly: an aggregating query drops the model's default ordering.
    """
    return (
        ClipboardCategory.objects.filter(user=user)
        .annotate(entry_count=Count("entries"))
        .order_by(Lower("name"), "id")
    )


def get_own_clipboard_category(user: User, category_id: Any) -> ClipboardCategory | None:
    return ClipboardCategory.objects.filter(user=user, pk=category_id).first()


def own_clipboard_category_name_exists(user: User, name: str, *, exclude_id: Any = None) -> bool:
    """Whether this user already has a category of that name, ignoring case."""
    queryset = ClipboardCategory.objects.filter(user=user, name__iexact=name)
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    return queryset.exists()


def count_own_clipboard_categories(user: User) -> int:
    return ClipboardCategory.objects.filter(user=user).count()
