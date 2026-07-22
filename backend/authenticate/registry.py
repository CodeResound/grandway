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
]
