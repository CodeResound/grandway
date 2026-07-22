"""Management command: reset_superadmin_password.

Deployment-level recovery for a superadmin who has lost their password. There is
no self-service forgot-password flow and no actor with authority over a superadmin,
so this shell command is the only superadmin password-recovery path.

Sets a temporary password, forces a change at next login, and revokes the
superadmin's sessions. Refuses to run against a non-superadmin account.

Usage:
    python manage.py reset_superadmin_password --username superadmin
    python manage.py reset_superadmin_password --username superadmin --password <temp>
"""

from __future__ import annotations

import os
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from authenticate.constants import AuthorityType
from authenticate.managers import UserManager
from authenticate.models import User
from authenticate.services import admin_reset_password

_DEFAULT_USERNAME = "superadmin"


class Command(BaseCommand):
    help = "Reset a superadmin's password (deployment recovery)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--username",
            default=None,
            help="Superadmin username (env SUPERADMIN_USERNAME, else 'superadmin').",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Temporary password (env SUPERADMIN_PASSWORD; unset → generated and printed once).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        raw = options["username"] or os.environ.get("SUPERADMIN_USERNAME") or _DEFAULT_USERNAME
        username = UserManager.normalize_username(raw)
        password = options["password"] or os.environ.get("SUPERADMIN_PASSWORD")

        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"No user with username {username!r}.")
        if user.authority_type != AuthorityType.SUPERADMIN:
            raise CommandError(f"User {username!r} is not a superadmin; refusing to reset.")

        try:
            # actor=None marks this as a deployment-level (non-actor) reset.
            temp_password = admin_reset_password(actor=None, target=user, new_password=password)
        except ValidationError as exc:
            raise CommandError("Password is too weak: " + "; ".join(exc.messages)) from exc

        self.stdout.write(
            self.style.SUCCESS(f"Reset password for superadmin {username!r} and revoked their sessions.")
        )
        if temp_password is not None:
            self.stdout.write(self.style.WARNING(f"Temporary password (store securely, shown once): {temp_password}"))
        self.stdout.write("The account must change its password on next login.")
