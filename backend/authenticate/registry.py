"""Core Policy Engine endpoint declarations for the authenticate app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "authenticate",
    "app_display_name": "Authenticate",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "authentication",
    "category_display_name": "Authentication",
}

_REQUIRES_LOGIN = [
    {
        "target_permission_key": "authenticate.session.login",
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": "A session must be established by login before this endpoint is usable.",
    }
]

POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. Login — public entry point; establishes a device-bound session. Root dep.
    {
        **_BASE,
        "endpoint_key": "session-login",
        "permission_key": "authenticate.session.login",
        "model_key": "session",
        "model_display_name": "Auth Session",
        "operation_type": "custom",
        "display_name": "Login",
        "description": "Authenticate with username + password (+ device_id) and open a revocable session.",
        "http_method": "POST",
        "route_pattern": "/api/v1/auth/login/",
        "view_import_path": "authenticate.views.LoginView",
        "risk_level": "high",
        "is_dependency_root": True,
        "dependencies": [],
        "change_summary": "Initial registration of the login endpoint.",
        "change_reason": "authenticate app Phase 1 foundation.",
    },
    # 2. Refresh — rotate the session; requires an existing session (login).
    {
        **_BASE,
        "endpoint_key": "session-refresh",
        "permission_key": "authenticate.session.refresh",
        "model_key": "session",
        "model_display_name": "Auth Session",
        "operation_type": "custom",
        "display_name": "Refresh Session",
        "description": "Rotate the refresh session, issuing a new access + refresh credential.",
        "http_method": "POST",
        "route_pattern": "/api/v1/auth/refresh/",
        "view_import_path": "authenticate.views.RefreshView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_LOGIN,
        "change_summary": "Initial registration of the refresh endpoint.",
        "change_reason": "authenticate app Phase 1 foundation.",
    },
    # 3. Logout — revoke the current session.
    {
        **_BASE,
        "endpoint_key": "session-logout",
        "permission_key": "authenticate.session.logout",
        "model_key": "session",
        "model_display_name": "Auth Session",
        "operation_type": "custom",
        "display_name": "Logout",
        "description": "Revoke the caller's current session (logout of this device).",
        "http_method": "POST",
        "route_pattern": "/api/v1/auth/logout/",
        "view_import_path": "authenticate.views.LogoutView",
        "risk_level": "low",
        "dependencies": _REQUIRES_LOGIN,
        "change_summary": "Initial registration of the logout endpoint.",
        "change_reason": "authenticate app Phase 1 foundation.",
    },
    # 4. Current user — read the authenticated user.
    {
        **_BASE,
        "endpoint_key": "user-me",
        "permission_key": "authenticate.user.me",
        "model_key": "user",
        "model_display_name": "User",
        "operation_type": "read",
        "display_name": "Current User",
        "description": "Return the currently authenticated user and forced-password-change state.",
        "http_method": "GET",
        "route_pattern": "/api/v1/auth/me/",
        "view_import_path": "authenticate.views.CurrentUserView",
        "risk_level": "low",
        "dependencies": _REQUIRES_LOGIN,
        "change_summary": "Initial registration of the current-user endpoint.",
        "change_reason": "authenticate app Phase 1 foundation.",
    },
    # 5. Change own password — clears must_change_password; revokes all sessions.
    {
        **_BASE,
        "endpoint_key": "user-change-password",
        "permission_key": "authenticate.user.change_password",
        "model_key": "user",
        "model_display_name": "User",
        "operation_type": "custom",
        "display_name": "Change Password",
        "description": "Change the caller's own password after confirming the current one.",
        "http_method": "POST",
        "route_pattern": "/api/v1/auth/password/change/",
        "view_import_path": "authenticate.views.PasswordChangeView",
        "risk_level": "high",
        "dependencies": _REQUIRES_LOGIN,
        "change_summary": "Initial registration of the change-password endpoint.",
        "change_reason": "authenticate app Phase 1 foundation.",
    },
    # 6. MFA enroll — begin TOTP enrollment.
    {
        **_BASE,
        "endpoint_key": "mfa-enroll",
        "permission_key": "authenticate.mfa.enroll",
        "model_key": "mfa",
        "model_display_name": "MFA Device",
        "operation_type": "custom",
        "display_name": "Begin MFA Enrollment",
        "description": "Create a pending TOTP device and return its secret + otpauth URL.",
        "http_method": "POST",
        "route_pattern": "/api/v1/auth/mfa/enroll/",
        "view_import_path": "authenticate.views.MfaEnrollView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_LOGIN,
        "change_summary": "Initial registration of the MFA enroll endpoint.",
        "change_reason": "authenticate app Phase 2 (MFA).",
    },
    # 7. MFA verify — confirm/activate TOTP.
    {
        **_BASE,
        "endpoint_key": "mfa-verify",
        "permission_key": "authenticate.mfa.verify",
        "model_key": "mfa",
        "model_display_name": "MFA Device",
        "operation_type": "custom",
        "display_name": "Confirm MFA Enrollment",
        "description": "Confirm a pending TOTP enrollment with a current code, activating MFA.",
        "http_method": "POST",
        "route_pattern": "/api/v1/auth/mfa/verify/",
        "view_import_path": "authenticate.views.MfaVerifyView",
        "risk_level": "medium",
        "dependencies": [
            {
                "target_permission_key": "authenticate.mfa.enroll",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Enrollment must be started before it can be confirmed.",
            }
        ],
        "change_summary": "Initial registration of the MFA verify endpoint.",
        "change_reason": "authenticate app Phase 2 (MFA).",
    },
    # 8. MFA disable — turn off own MFA (not superadmin).
    {
        **_BASE,
        "endpoint_key": "mfa-disable",
        "permission_key": "authenticate.mfa.disable",
        "model_key": "mfa",
        "model_display_name": "MFA Device",
        "operation_type": "custom",
        "display_name": "Disable MFA",
        "description": "Disable the caller's own MFA after confirming password + a current code.",
        "http_method": "POST",
        "route_pattern": "/api/v1/auth/mfa/disable/",
        "view_import_path": "authenticate.views.MfaDisableView",
        "risk_level": "high",
        "dependencies": [
            {
                "target_permission_key": "authenticate.mfa.verify",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "MFA must be enabled (enrolled and confirmed) before it can be disabled.",
            }
        ],
        "change_summary": "Initial registration of the MFA disable endpoint.",
        "change_reason": "authenticate app Phase 2 (MFA).",
    },
]
