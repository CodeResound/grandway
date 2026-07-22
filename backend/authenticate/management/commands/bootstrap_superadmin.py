"""Management command: bootstrap_superadmin.

Creates the initial platform Superadmin outside the normal application interface
(there is no registration or invitation flow). Safe to rerun: an existing
superadmin with the same username is returned without creating a duplicate.

The account is always flagged ``must_change_password`` so the temporary password
must be replaced on first login. Never bake a production password into automation
— leave ``--password`` unset (or ``SUPERADMIN_PASSWORD`` unexported) to have a
secure password generated and printed once.

Each of ``--username``/``--email``/``--password``/``--display-name`` falls back to
the matching ``SUPERADMIN_*`` environment variable, then a built-in default.

Usage:
    python manage.py bootstrap_superadmin
    python manage.py bootstrap_superadmin --username admin --email admin@example.com
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from authenticate.services import bootstrap_superadmin
from authenticate.validators import validate_password_strength

_GENERATED_PASSWORD_BYTES = 18
_DEFAULT_USERNAME = "superadmin"


class Command(BaseCommand):
    help = "Create (idempotently) the initial platform Superadmin account."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--username", default=None, help="Login username (env SUPERADMIN_USERNAME, else 'superadmin')."
        )
        parser.add_argument("--email", default=None, help="Contact email (env SUPERADMIN_EMAIL).")
        parser.add_argument(
            "--password", default=None, help="Temporary password (env SUPERADMIN_PASSWORD; unset → generated)."
        )
        parser.add_argument(
            "--display-name", default=None, help="Display name (env SUPERADMIN_DISPLAY_NAME, else username)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        username = options["username"] or os.environ.get("SUPERADMIN_USERNAME") or _DEFAULT_USERNAME
        email = options["email"] or os.environ.get("SUPERADMIN_EMAIL", "")
        display_name = options["display_name"] or os.environ.get("SUPERADMIN_DISPLAY_NAME", "")
        password, generated = self._resolve_password(options)

        try:
            validate_password_strength(password)
        except ValidationError as exc:
            raise CommandError("Temporary password is too weak: " + "; ".join(exc.messages)) from exc

        try:
            user, created = bootstrap_superadmin(
                username=username,
                password=password,
                display_name=display_name,
                email=email,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if not created:
            self.stdout.write(
                self.style.WARNING(f"Superadmin {user.username!r} already exists; no changes made (idempotent).")
            )
            return

        self.stdout.write(self.style.SUCCESS(f"Superadmin {user.username!r} created."))
        if generated:
            self.stdout.write(self.style.WARNING(f"Temporary password (store securely, shown once): {password}"))
        self.stdout.write("The account must change its password on first login.")

    def _resolve_password(self, options: dict[str, Any]) -> tuple[str, bool]:
        password = options["password"] or os.environ.get("SUPERADMIN_PASSWORD")
        if password:
            return password, False
        return secrets.token_urlsafe(_GENERATED_PASSWORD_BYTES), True
