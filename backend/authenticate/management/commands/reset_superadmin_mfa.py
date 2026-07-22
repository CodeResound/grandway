"""Management command: reset_superadmin_mfa.

Deployment-level recovery for a superadmin who has lost their authenticator.
Removes the superadmin's TOTP device(s) and revokes their sessions so they can
log in with password alone and re-enroll MFA. There are no recovery/backup codes
by design (concept-locked), so this shell command is the only superadmin MFA
recovery path.

Refuses to run against a non-superadmin account (use the Phase 3 admin reset flow
for Admin/Lead Manager accounts once it ships).

Usage:
    python manage.py reset_superadmin_mfa --username superadmin
"""

from __future__ import annotations

import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from authenticate.constants import AuthorityType
from authenticate.managers import UserManager
from authenticate.models import User
from authenticate.services import reset_mfa

_DEFAULT_USERNAME = "superadmin"


class Command(BaseCommand):
    help = "Remove a superadmin's MFA device(s) so they can re-enroll (recovery)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--username",
            default=None,
            help="Superadmin username (env SUPERADMIN_USERNAME, else 'superadmin').",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        raw = options["username"] or os.environ.get("SUPERADMIN_USERNAME") or _DEFAULT_USERNAME
        username = UserManager.normalize_username(raw)

        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"No user with username {username!r}.")
        if user.authority_type != AuthorityType.SUPERADMIN:
            raise CommandError(f"User {username!r} is not a superadmin; refusing to reset.")

        removed = reset_mfa(user, actor=None, reason="deployment_recovery_command")
        if removed:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Removed MFA for {username!r} and revoked their sessions. "
                    "They can now log in with password only and re-enroll MFA."
                )
            )
        else:
            self.stdout.write(self.style.WARNING(f"{username!r} had no MFA device; sessions were revoked anyway."))
