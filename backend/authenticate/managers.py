"""Model managers for the authenticate app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager
from django.db import models

from authenticate.constants import AuthorityType
from authenticate.exceptions import ImmutabilityError

if TYPE_CHECKING:
    from authenticate.models import User


class UserManager(BaseUserManager):
    """Manager for the custom username-based ``User`` model.

    Username normalization is centralized here so every creation path (admin,
    bootstrap command, account services) applies the same rule.
    """

    use_in_migrations = True

    @staticmethod
    def normalize_username(username: str) -> str:
        return (username or "").strip().lower()

    def _create_user(
        self,
        username: str,
        password: str | None,
        authority_type: str,
        **extra_fields: Any,
    ) -> User:
        if not username:
            raise ValueError("A username is required.")
        username = self.normalize_username(username)
        # Treat a blank/absent display_name as "use the username" (§39.1 requires it).
        if not extra_fields.get("display_name"):
            extra_fields["display_name"] = username
        user = self.model(username=username, authority_type=authority_type, **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(
        self,
        username: str,
        password: str | None = None,
        authority_type: str = AuthorityType.LEAD_MANAGER,
        **extra_fields: Any,
    ) -> User:
        extra_fields.setdefault("is_staff", authority_type != AuthorityType.LEAD_MANAGER)
        extra_fields.setdefault("is_superuser", authority_type == AuthorityType.SUPERADMIN)
        return self._create_user(username, password, authority_type, **extra_fields)

    def create_superuser(
        self,
        username: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Django's ``createsuperuser`` entry point — maps to a superadmin account.

        Platform bootstrap should use the ``bootstrap_superadmin`` command instead;
        this exists so ``manage.py`` tooling and tests keep working.
        """
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self._create_user(username, password, AuthorityType.SUPERADMIN, **extra_fields)


class AuthEventQuerySet(models.QuerySet):
    """Append-only QuerySet: bulk deletion is blocked.

    ``reset_dev_data`` detects that ``delete`` differs from the base QuerySet's
    and preserves the table rather than clearing it.
    """

    def delete(self) -> None:  # type: ignore[override]
        raise ImmutabilityError("AuthEvent is append-only; bulk delete is not allowed.")
