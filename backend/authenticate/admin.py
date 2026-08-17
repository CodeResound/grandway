"""Django admin registration for the authenticate app.

Sensitive material (password hash, refresh-token hash) is never editable, and
the password hash is excluded from the user form outright — it earlier sat in
``readonly_fields``, which still renders the value (caught by the 2026-08-17
security audit, S3).

**Fields with a service-layer invariant are read-only here (§13).** The admin
form calls a model's own validation and nothing else — not the authority
hierarchy in ``services``, not ``normalize_unicode`` (§39.2), and not a single
``record_auth_event``. So any field this module leaves editable is a field whose
business rules can be bypassed silently, by a ``is_superuser`` account, with no
entry in either audit trail.

Two were, and a probe on 2026-08-01 exercised both:

* ``authority_type`` / ``is_staff`` / ``is_superuser`` — editable, so a
  Superadmin could promote a Lead Manager straight to Superadmin, bypassing
  ``_MANAGED_TIER`` (which confines them to the Admin tier) and writing no
  event of any kind.
* ``is_active`` — editable, so a blocked account could be reactivated while
  ``UserSecurityState.blocked_at`` stayed set. Not merely unaudited: it leaves
  the two rows *disagreeing*, so anything reporting on ``blocked_at`` says the
  account is blocked while login says it is not.

Both now go through their endpoints, which maintain both sides and audit the
change. This narrows what the admin can do; it does not decide who may reach
it, which is a separate question (§28 item 5) and still open.
"""

from __future__ import annotations

from django.contrib import admin

from authenticate.models import AuthEvent, AuthSession, User, UserSecurityState


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "authority_type", "display_name", "is_active", "is_staff", "created_at")
    list_filter = ("authority_type", "is_active", "is_staff")
    search_fields = ("username", "display_name", "full_name", "email")
    # The hash is *excluded*, not read-only: a readonly field still renders its
    # value, and an Argon2 hash on screen is disclosure of hash material.
    exclude = ("password",)
    readonly_fields = (
        "id",
        "last_login",
        "created_at",
        "updated_at",
        # Immutable by contract: the login identifier never changes (models.User).
        "username",
        # Authority and its derived Django flags are set by create_managed_account
        # under the _MANAGED_TIER hierarchy, and changed nowhere else. Editing
        # them here is straight privilege escalation, unaudited.
        "authority_type",
        "is_staff",
        "is_superuser",
        # Blocking is a two-row operation (User.is_active + UserSecurityState),
        # done by block_account/restore_account. Flipping this alone leaves the
        # two disagreeing about whether the account is blocked.
        "is_active",
        # Group/permission membership is how a non-superuser staff account would
        # gain model access in this admin. Granting it is an authorization change
        # (§28 item 5), not a row edit.
        "groups",
        "user_permissions",
    )
    ordering = ("username",)

    def has_add_permission(self, request: object) -> bool:
        """Accounts come from ``POST /api/v1/auth/users/`` or ``bootstrap_superadmin``.

        Both create the ``UserSecurityState`` in the same transaction, hash a
        real password, and record an ``ACCOUNT_CREATED`` event. This form does
        none of the three, and with ``authority_type`` and ``password``
        read-only it could only produce an account with no authority and an
        unusable password.
        """
        return False


@admin.register(UserSecurityState)
class UserSecurityStateAdmin(admin.ModelAdmin):
    list_display = ("user", "must_change_password", "password_changed_at", "provisioned_via", "blocked_at")
    list_filter = ("must_change_password", "provisioned_via")
    search_fields = ("user__username",)
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "password_changed_at",
        "user",
        # The other half of the block. block_account/restore_account write these
        # together with User.is_active; editing one side here re-creates exactly
        # the divergence making User.is_active read-only was meant to prevent.
        "blocked_at",
        "blocked_by",
        "blocked_reason",
        # Cleared by change_own_password and set by admin_reset_password, both of
        # which also rotate the password and revoke sessions. Clearing the flag
        # alone would retire a forced password change that never happened.
        "must_change_password",
        "provisioned_via",
    )

    def has_add_permission(self, request: object) -> bool:
        """Created by ``create_account`` alongside its User, never on its own.

        A row added here would either duplicate the OneToOne or orphan itself,
        and in neither case would it carry the provisioning history the model
        exists to record.
        """
        return False


@admin.register(AuthSession)
class AuthSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device_id", "is_active", "last_used_at", "expires_at", "revoked_reason")
    list_filter = ("is_active", "revoked_reason")
    search_fields = ("user__username", "device_id", "device_name")
    readonly_fields = (
        "id",
        "user",
        "device_id",
        "device_name",
        "refresh_token_hash",
        "family_id",
        "previous_session",
        "ip_address",
        "user_agent",
        "last_used_at",
        "idle_expires_at",
        "expires_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: object) -> bool:
        return False


@admin.register(AuthEvent)
class AuthEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "subject_username", "success", "reason", "ip_address", "created_at")
    list_filter = ("event_type", "success")
    search_fields = ("subject_username", "reason", "device_id")
    readonly_fields = (
        "id",
        "event_type",
        "actor",
        "subject",
        "subject_username",
        "success",
        "reason",
        "ip_address",
        "user_agent",
        "device_id",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
