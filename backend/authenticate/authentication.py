"""Session-bound JWT authentication.

A valid access JWT is not sufficient on its own: every request re-checks the
server-side ``AuthSession`` so that blocking, logout, session revocation, and
password resets take effect immediately regardless of the token's remaining
lifetime.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken

from authenticate.constants import (
    CLAIM_AUTHORITY_TYPE,
    CLAIM_SESSION_ID,
)
from authenticate.models import User
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

        security_state = getattr(user, "security_state", None)
        if security_state is not None and security_state.password_changed_at is not None:
            if session.created_at < security_state.password_changed_at:
                raise AuthenticationFailed("Password was changed after this session began.", code="password_changed")

        # Expose the session + forced-change flag for views/permission gates.
        user.auth_session = session
        user.must_change_password = bool(security_state and security_state.must_change_password)
        return user
