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


# Access-token claim keys (added on top of SimpleJWT's standard claims).
CLAIM_SESSION_ID = "sid"
CLAIM_AUTHORITY_TYPE = "authority_type"
CLAIM_MUST_CHANGE_PASSWORD = "must_change_password"

# DRF throttle scopes (rates live in settings DEFAULT_THROTTLE_RATES).
THROTTLE_SCOPE_LOGIN_IP = "auth_login_ip"
THROTTLE_SCOPE_LOGIN_USER = "auth_login_user"
THROTTLE_SCOPE_REFRESH = "auth_refresh"

# Length of the opaque refresh token in URL-safe bytes before encoding.
REFRESH_TOKEN_BYTES = 48
