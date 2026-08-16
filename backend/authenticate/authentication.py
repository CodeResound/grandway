"""Session-bound JWT authentication.

A valid access JWT is not sufficient on its own: every request re-checks the
server-side ``AuthSession`` so that blocking, logout, session revocation, and
password resets take effect immediately regardless of the token's remaining
lifetime.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken

from authenticate.constants import (
    CLAIM_AUTHORITY_TYPE,
    CLAIM_SESSION_ID,
)
from authenticate.models import AuthSession, User
from authenticate.selectors import get_session_by_id


class SessionBoundJWTAuthentication(JWTAuthentication):
    """JWTAuthentication + mandatory server-side session validation."""

    def get_user(self, validated_token: Any) -> User:
        user = super().get_user(validated_token)  # validates user_id + is_active

        session_id = validated_token.get(CLAIM_SESSION_ID)
        if not session_id:
            raise InvalidToken("Token is missing the session claim.")

        session = get_session_by_id(str(session_id))
        if session is None or not session.is_active:
            raise AuthenticationFailed("Session has been revoked.", code="session_revoked")

        if session.user_id != user.id:
            raise AuthenticationFailed("Session does not match token subject.", code="session_mismatch")

        now = timezone.now()
        if now >= session.expires_at or now >= session.idle_expires_at:
            raise AuthenticationFailed("Session has expired.", code="session_expired")

        if validated_token.get(CLAIM_AUTHORITY_TYPE) != user.authority_type:
            raise AuthenticationFailed("Authority level has changed.", code="authority_changed")

        # Read the security state off ``session.user`` rather than ``user``.
        # ``get_session_by_id`` already joined ``user__security_state``, while
        # ``user`` came from SimpleJWT's own lookup with nothing joined — so
        # touching it there costs a third query on **every authenticated
        # request** in the project for a row that is already in memory. The two
        # are the same account: ``session.user_id == user.id`` is checked above,
        # and a mismatch has already been rejected by then.
        security_state = getattr(session.user, "security_state", None)
        if security_state is not None and security_state.password_changed_at is not None:
            if session.created_at < security_state.password_changed_at:
                raise AuthenticationFailed("Password was changed after this session began.", code="password_changed")

        _touch_last_used(session, now)

        # Expose the session + forced-change flag for views/permission gates.
        user.auth_session = session
        user.must_change_password = bool(security_state and security_state.must_change_password)
        return user


def _touch_last_used(session: AuthSession, now: datetime) -> None:
    """Keep ``last_used_at`` honest, at a bounded cost.

    The column is declared ``auto_now_add`` and nothing ever wrote it, so it held
    the session's *creation* time while being labelled "last used" on the screen
    where a user decides whether a device is still theirs — the one place a wrong
    answer matters. Writing it on every authenticated request would put an UPDATE
    in front of every call in the project, so it is refreshed only once its value
    is older than ``AUTH_SESSION_LAST_USED_RESOLUTION``.

    ``QuerySet.update`` rather than ``save``: it is one statement, it skips the
    ``auto_now`` on ``updated_at`` (session *use* is not session *modification*),
    and it does not disturb the instance the request is about to authenticate on.
    """
    resolution = getattr(settings, "AUTH_SESSION_LAST_USED_RESOLUTION", timedelta(minutes=5))
    if session.last_used_at and now - session.last_used_at < resolution:
        return
    AuthSession.objects.filter(pk=session.pk).update(last_used_at=now)
    session.last_used_at = now
