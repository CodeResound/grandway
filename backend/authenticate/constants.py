"""Enums, error codes, and claim/scope constants for the authenticate app."""

from django.db import models


class AuthorityType(models.TextChoices):
    SUPERADMIN = "superadmin", "Superadmin"
    ADMIN = "admin", "Admin"
    LEAD_MANAGER = "lead_manager", "Lead Manager"


class ProvisionedVia(models.TextChoices):
    BOOTSTRAP_COMMAND = "bootstrap_command", "Bootstrap Command"
    SUPERADMIN_CREATED = "superadmin_created", "Created by Superadmin"
    ADMIN_CREATED = "admin_created", "Created by Admin"


class SessionRevocationReason(models.TextChoices):
    LOGOUT = "logout", "Logout"
    PASSWORD_CHANGE = "password_change", "Password Change"
    REPLACED_SAME_DEVICE = "replaced_same_device", "Replaced (same device re-login)"
    ROTATED = "rotated", "Rotated (normal refresh rotation)"
    ROTATED_REUSE = "rotated_reuse", "Rotated token reuse detected"
    DEVICE_LIMIT = "device_limit", "Device limit enforcement"
    BLOCKED = "blocked", "Account blocked"
    ADMIN_REVOKED = "admin_revoked", "Revoked by administrator"
    MFA_CHANGE = "mfa_change", "MFA changed (enabled/disabled/reset)"
    EXPIRED = "expired", "Expired (idle or absolute lifetime)"


class RefreshRejectReason(models.TextChoices):
    """``error.details.reason`` values of ``AUTH_REFRESH_INVALID`` that are not a revocation.

    A refresh token whose session was revoked reports that session's
    ``SessionRevocationReason`` instead, so a client can tell "signed out because
    this device logged in again" (``replaced_same_device``) from "the session ran
    out" (``expired``) without a new error code.
    """

    MISSING = "missing", "No refresh credential supplied"
    NOT_FOUND = "not_found", "Unknown refresh credential"


class AuthEventType(models.TextChoices):
    SUPERADMIN_BOOTSTRAP = "superadmin_bootstrap", "Superadmin Bootstrap"
    LOGIN_SUCCESS = "login_success", "Login Success"
    LOGIN_FAILURE = "login_failure", "Login Failure"
    FORCED_PASSWORD_CHANGE = "forced_password_change", "Forced Password Change"
    PASSWORD_CHANGE = "password_change", "Password Change"
    LOGOUT = "logout", "Logout"
    SESSION_REFRESHED = "session_refreshed", "Session Refreshed"
    SESSION_REVOKED = "session_revoked", "Session Revoked"
    ACCOUNT_CREATED = "account_created", "Account Created"
    ACCOUNT_UPDATED = "account_updated", "Account Updated"
    ACCOUNT_BLOCKED = "account_blocked", "Account Blocked"
    ACCOUNT_RESTORED = "account_restored", "Account Restored"
    ADMIN_PASSWORD_RESET = "admin_password_reset", "Administrative Password Reset"
    MFA_ENABLED = "mfa_enabled", "MFA Enabled"
    MFA_DISABLED = "mfa_disabled", "MFA Disabled"
    MFA_VERIFICATION_FAILURE = "mfa_verification_failure", "MFA Verification Failure"
    MFA_RESET = "mfa_reset", "MFA Reset (recovery)"
    REFRESH_REJECTED = "refresh_rejected", "Refresh Rejected"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the authenticate app (§7)."""

    CREDENTIALS_INVALID = "AUTH_CREDENTIALS_INVALID"
    DEVICE_LIMIT_REACHED = "AUTH_DEVICE_LIMIT_REACHED"
    PASSWORD_CHANGE_REQUIRED = "AUTH_PASSWORD_CHANGE_REQUIRED"
    REFRESH_INVALID = "AUTH_REFRESH_INVALID"
    REFRESH_REUSED = "AUTH_REFRESH_REUSED"
    SESSION_REVOKED = "AUTH_SESSION_REVOKED"
    PASSWORD_INCORRECT = "AUTH_PASSWORD_INCORRECT"
    PASSWORD_WEAK = "AUTH_PASSWORD_WEAK"
    MFA_REQUIRED = "AUTH_MFA_REQUIRED"
    MFA_INVALID = "AUTH_MFA_INVALID"
    MFA_ALREADY_ENROLLED = "AUTH_MFA_ALREADY_ENROLLED"
    MFA_NOT_ENROLLED = "AUTH_MFA_NOT_ENROLLED"
    MFA_MANDATORY = "AUTH_MFA_MANDATORY"
    USER_NOT_FOUND = "AUTH_USER_NOT_FOUND"
    FORBIDDEN_HIERARCHY = "AUTH_FORBIDDEN_HIERARCHY"
    USERNAME_TAKEN = "AUTH_USERNAME_TAKEN"
    INVALID_AUTHORITY = "AUTH_INVALID_AUTHORITY"
    SESSION_NOT_FOUND = "AUTH_SESSION_NOT_FOUND"
    CLIPBOARD_ENTRY_NOT_FOUND = "AUTH_CLIPBOARD_ENTRY_NOT_FOUND"
    CLIPBOARD_LIMIT_REACHED = "AUTH_CLIPBOARD_LIMIT_REACHED"
    CLIPBOARD_CATEGORY_NOT_FOUND = "AUTH_CLIPBOARD_CATEGORY_NOT_FOUND"
    CLIPBOARD_CATEGORY_INVALID = "AUTH_CLIPBOARD_CATEGORY_INVALID"
    CLIPBOARD_CATEGORY_NAME_TAKEN = "AUTH_CLIPBOARD_CATEGORY_NAME_TAKEN"
    CLIPBOARD_CATEGORY_LIMIT_REACHED = "AUTH_CLIPBOARD_CATEGORY_LIMIT_REACHED"


# --- Personal clipboard (2026-10-29) -----------------------------------------
MAX_CLIPBOARD_ENTRIES = 200
MAX_CLIPBOARD_CATEGORIES = 50
MAX_CLIPBOARD_TEXT = 2000
#: An optional, opaque dotted key naming a document form field (``father.name``).
CLIPBOARD_FIELD_KEY_RE = r"^[a-z0-9_]+(\.[a-z0-9_]+)*$"
#: ``?category=none`` — entries in no category.
CLIPBOARD_UNCATEGORIZED = "none"

#: ``audit.AuditEvent`` labels for clipboard writes. Recorded centrally only, not
#: as ``AuthEvent`` rows: the clipboard is a personal tool, not account security.
AUDIT_APP_LABEL = "authenticate"
AUDIT_ENTITY_CLIPBOARD_ENTRY = "authenticate.clipboard_entry"
AUDIT_ENTITY_CLIPBOARD_CATEGORY = "authenticate.clipboard_category"


class ClipboardAuditAction:
    """``audit.AuditEvent.action`` names for clipboard writes. Using an entry is not audited."""

    ENTRY_CREATED = "clipboard_entry_created"
    ENTRY_UPDATED = "clipboard_entry_updated"
    ENTRY_DELETED = "clipboard_entry_deleted"
    CATEGORY_CREATED = "clipboard_category_created"
    CATEGORY_UPDATED = "clipboard_category_updated"
    CATEGORY_DELETED = "clipboard_category_deleted"


# Access-token claim keys (added on top of SimpleJWT's standard claims).
CLAIM_SESSION_ID = "sid"
CLAIM_AUTHORITY_TYPE = "authority_type"
CLAIM_MUST_CHANGE_PASSWORD = "must_change_password"

# DRF throttle scopes (rates live in settings DEFAULT_THROTTLE_RATES).
THROTTLE_SCOPE_LOGIN_IP = "auth_login_ip"
THROTTLE_SCOPE_LOGIN_USER = "auth_login_user"
THROTTLE_SCOPE_REFRESH = "auth_refresh"
THROTTLE_SCOPE_REFRESH_TOKEN = "auth_refresh_token"

# ``AuthEvent.reason`` on a ``session_refreshed`` event answered from the reuse
# grace window (a concurrent refresh with the token just rotated away).
REFRESH_GRACE_EVENT_REASON = "grace_window"

# Length of the opaque refresh token in URL-safe bytes before encoding.
REFRESH_TOKEN_BYTES = 48
