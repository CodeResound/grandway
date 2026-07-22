"""Data models for the authenticate app.

See ``authenticate/docs/DATA_CONTRACT.md`` for the authoritative contract.
"""

from __future__ import annotations

import uuid

from core.models import BaseModel
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from authenticate.constants import (
    AuthEventType,
    AuthorityType,
    ProvisionedVia,
    SessionRevocationReason,
)
from authenticate.exceptions import ImmutabilityError
from authenticate.managers import AuthEventQuerySet, UserManager
from authenticate.validators import validate_username_format


class User(AbstractBaseUser, PermissionsMixin):
    """Permanent login account. Username is the immutable login identifier."""

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    username = models.CharField(max_length=150, unique=True, validators=[validate_username_format])
    authority_type = models.CharField(max_length=20, choices=AuthorityType.choices, db_index=True)

    display_name = models.CharField(max_length=255)
    full_name_np = models.CharField(max_length=255, blank=True)
    full_name_en = models.CharField(max_length=255, blank=True)
    full_name_romanized = models.CharField(max_length=255, blank=True)

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        db_table = "authenticate_user"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self) -> str:
        return f"{self.username} ({self.authority_type})"

    @property
    def is_blocked(self) -> bool:
        return not self.is_active


class UserSecurityState(BaseModel):
    """Per-account security/lifecycle state kept off the identity row."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="security_state")
    must_change_password = models.BooleanField(default=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    provisioned_via = models.CharField(max_length=20, choices=ProvisionedVia.choices)

    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blocks_performed",
    )
    blocked_reason = models.TextField(blank=True)

    class Meta:
        db_table = "authenticate_usersecuritystate"
        verbose_name = "User Security State"
        verbose_name_plural = "User Security States"

    def __str__(self) -> str:
        return f"security_state<{self.user.username}>"


class AuthSession(BaseModel):
    """Server-known, device-bound, revocable refresh session.

    ``id`` is carried as the ``sid`` claim in every access JWT.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    device_id = models.CharField(max_length=255, db_index=True)
    device_name = models.CharField(max_length=255, blank=True)

    refresh_token_hash = models.CharField(max_length=64, unique=True)
    family_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    previous_session = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=30, choices=SessionRevocationReason.choices, blank=True)

    last_used_at = models.DateTimeField(auto_now_add=True)
    idle_expires_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "authenticate_authsession"
        verbose_name = "Auth Session"
        verbose_name_plural = "Auth Sessions"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "device_id"],
                condition=models.Q(is_active=True),
                name="uniq_active_session_per_device",
            )
        ]
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self) -> str:
        state = "active" if self.is_active else "revoked"
        return f"session<{self.user.username}/{self.device_id}:{state}>"


class AuthEvent(BaseModel):
    """Immutable, append-only authentication audit trail."""

    event_type = models.CharField(max_length=40, choices=AuthEventType.choices, db_index=True)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auth_events_performed",
    )
    subject = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auth_events_about",
    )
    subject_username = models.CharField(max_length=150, blank=True, db_index=True)
    success = models.BooleanField(default=True)
    reason = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = AuthEventQuerySet.as_manager()

    class Meta:
        db_table = "authenticate_authevent"
        verbose_name = "Auth Event"
        verbose_name_plural = "Auth Events"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        outcome = "ok" if self.success else "fail"
        return f"{self.event_type}:{self.subject_username or '-'}:{outcome}"

    def delete(self, *args: object, **kwargs: object) -> None:
        raise ImmutabilityError("AuthEvent is append-only; delete is not allowed.")
