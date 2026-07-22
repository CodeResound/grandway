# API Documentation — Authenticate

**App:** `authenticate`
**Version:** 1.0.0
**Base prefix:** `/api/v1/auth/`
**Auth:** Mixed. `login`/`refresh` are public; `logout`/`me`/`password/change` require a Bearer access token validated by `authenticate.authentication.SessionBoundJWTAuthentication` (see `SECURITY.md` §1). No `is_staff` gate — the three protected endpoints are self-service (any authenticated user acting on their own account).
**Throttle:** Custom scopes — `login` uses `LoginIPThrottle` + `LoginUsernameThrottle` (`auth_login_ip` 20/min, `auth_login_user` 10/min); `refresh` uses `RefreshThrottle` (`auth_refresh` 60/min). Stateful account lockout is handled by django-axes (see `SECURITY.md` §3), not DRF.
**Access level:** Public (`login`, `refresh`) + authenticated self-service (`logout`, `me`, `password/change`).

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial API docs — Phase 1 foundation (5 endpoints) |

---

## Generic envelopes (referenced throughout)

**Success:**
```json
{ "success": true, "message": "...", "data": { ... }, "meta": {} }
```

**Error:**
```json
{ "success": false, "error": { "code": "...", "message": "...", "details": {} }, "meta": {} }
```

**AI debugging notes (app-wide):** All protected endpoints re-load the `AuthSession` named by the access token's `sid` claim and reject revoked/expired sessions with `AUTHENTICATION_REQUIRED` (401) — a valid-looking JWT is never sufficient. Login errors are intentionally uniform (no enumeration); when debugging a "wrong" login, check `AuthEvent` rows and the axes `AccessAttempt` table, not the API response.

---

## 1. Session

### 1.1 Login — `POST /api/v1/auth/login/`

**Policy key(s):** `authenticate.session.login` (risk: high)
**Access:** Public (documented public endpoint).
**Request:**
```json
{ "username": "ramesh.admin", "password": "…", "device_id": "web-9f3a-uuid", "device_name": "Chrome/macOS" }
```
**Response:** `data` = `{ access, must_change_password, user }` (+ `refresh` in the body in development only; HttpOnly cookie in production). `user` is the **User** read shape — see `DATA_CONTRACT.md §1`.
**Validation rules:** `username`, `password`, `device_id` required; `device_name` optional.
**Error codes:**
- `AUTH_CREDENTIALS_INVALID` (401) — wrong password, unknown user, blocked, or axes lockout (uniform, no enumeration).
- `AUTH_DEVICE_LIMIT_REACHED` (409) — new device while 3 devices already active.
- `VALIDATION_ERROR` (400) — missing/blank required field.
**Business rules:** Credentials verified via `django.contrib.auth.authenticate()` (axes observes the attempt). On success, `issue_session()` enforces one-session-per-device (same `device_id` replaces its prior session) and the ≤3 active-device cap, inside `atomic()`. Sets `last_login`; writes a `login_success`/`login_failure` `AuthEvent`.

### 1.2 Refresh — `POST /api/v1/auth/refresh/`

**Policy key(s):** `authenticate.session.refresh` (risk: medium)
**Access:** Public (credential is the refresh token itself).
**Request:** `{ "refresh": "…" }` in development; in production the token comes from the `grandway_refresh` HttpOnly cookie and the body is empty.
**Response:** `data` = `{ access, must_change_password }` (+ rotated `refresh` via body/cookie).
**Error codes:**
- `AUTH_REFRESH_INVALID` (401) — missing, unknown, or expired (idle 12h / absolute 7d) refresh credential.
- `AUTH_REFRESH_REUSED` (401) — a retired (already-rotated) token was replayed; the whole device family is revoked.
**Business rules:** Rotation — a new session row is created in the same `family_id` with `previous_session` set; the old row is retired (`revoked_reason=rotated`). Reuse detection keys off the retired row.

### 1.3 Logout — `POST /api/v1/auth/logout/`

**Policy key(s):** `authenticate.session.logout` (risk: low)
**Access:** Authenticated (self).
**Request:** none.
**Response:** empty `data`.
**Error codes:** `AUTHENTICATION_REQUIRED` (401) — no/invalid access token.
**Business rules:** Revokes the current session (`revoked_reason=logout`), clears the refresh cookie (prod), writes a `logout` `AuthEvent`. Idempotent.

## 2. User

### 2.1 Current user — `GET /api/v1/auth/me/`

**Policy key(s):** `authenticate.user.me` (risk: low)
**Access:** Authenticated (self).
**Response:** the **User** read shape — see `DATA_CONTRACT.md §1`; adds `must_change_password` (from `UserSecurityState`).
**Error codes:** `AUTHENTICATION_REQUIRED` (401).

### 2.2 Change own password — `POST /api/v1/auth/password/change/`

**Policy key(s):** `authenticate.user.change_password` (risk: high)
**Access:** Authenticated (self); permitted while `must_change_password` is set (this is how a user clears it).
**Request:** `{ "current_password": "…", "new_password": "…" }`
**Response:** empty `data`, message "Password changed. Please log in again."
**Error codes:**
- `AUTH_PASSWORD_INCORRECT` (400) — `current_password` did not match.
- `AUTH_PASSWORD_WEAK` (400) — `new_password` failed Django's strength validators; messages in `error.details.new_password`.
- `AUTHENTICATION_REQUIRED` (401).
**Business rules:** Verifies the current password, validates new-password strength, stamps `password_changed_at`, clears `must_change_password`, then **revokes ALL of the user's sessions** — the client must log in again. Writes `password_change`/`forced_password_change` `AuthEvent`.
