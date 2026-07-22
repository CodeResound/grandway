# API Documentation — Authenticate

**App:** `authenticate`
**Version:** 1.2.0
**Base prefix:** `/api/v1/auth/`
**Auth:** Mixed. `login`/`refresh` are public; `logout`/`me`/`password/change` require a Bearer access token validated by `authenticate.authentication.SessionBoundJWTAuthentication` (see `SECURITY.md` §1). No `is_staff` gate — the three protected endpoints are self-service (any authenticated user acting on their own account).
**Throttle:** Custom scopes — `login` uses `LoginIPThrottle` + `LoginUsernameThrottle` (`auth_login_ip` 20/min, `auth_login_user` 10/min); `refresh` uses `RefreshThrottle` (`auth_refresh` 60/min). Stateful account lockout is handled by django-axes (see `SECURITY.md` §3), not DRF.
**Access level:** Public (`login`, `refresh`) + authenticated self-service (`logout`, `me`, `password/change`).

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial API docs — Phase 1 foundation (5 endpoints) |
| 1.1.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 2 MFA — 3 mfa endpoints, login `otp_code` + MFA errors, `me` mfa fields |
| 1.2.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 3 — account management (users CRUD + block/restore + admin password/MFA reset), session management, auth-activity review |

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
{ "username": "ramesh.admin", "password": "…", "device_id": "web-9f3a-uuid", "device_name": "Chrome/macOS", "otp_code": "123456" }
```
**Response:** `data` = `{ access, must_change_password, mfa_enrollment_required, user }` (+ `refresh` in the body in development only; HttpOnly cookie in production). `user` is the **User** read shape — see `DATA_CONTRACT.md §1`.
**Validation rules:** `username`, `password`, `device_id` required; `device_name`, `otp_code` optional.
**Error codes:**
- `AUTH_CREDENTIALS_INVALID` (401) — wrong password, unknown user, blocked, or axes lockout (uniform, no enumeration).
- `AUTH_MFA_REQUIRED` (401) — password correct, account has MFA enabled, no `otp_code` supplied (only reachable after a correct password).
- `AUTH_MFA_INVALID` (401) — supplied `otp_code` is wrong or expired.
- `AUTH_DEVICE_LIMIT_REACHED` (409) — new device while 3 devices already active.
- `VALIDATION_ERROR` (400) — missing/blank required field.
**Business rules:** Credentials verified via `django.contrib.auth.authenticate()` (axes observes the attempt). If the account has a confirmed TOTP device, an `otp_code` is required and verified BEFORE a session is issued — the MFA check is unreachable without a correct password, so MFA status never leaks to an unauthenticated attacker. On success, `issue_session()` enforces one-session-per-device (same `device_id` replaces its prior session) and the ≤3 active-device cap, inside `atomic()`. Sets `last_login`; writes a `login_success`/`login_failure`/`mfa_verification_failure` `AuthEvent`.

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
**Response:** the **User** read shape — see `DATA_CONTRACT.md §1`; adds `must_change_password` (from `UserSecurityState`), `mfa_enabled` and `mfa_enrollment_required` (derived live from django-otp `TOTPDevice.confirmed`).
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

## 3. MFA

TOTP-based multi-factor auth via `django-otp` (`TOTPDevice`). No recovery/backup codes (concept-locked). The TOTP secret is stored by django-otp; it is returned only once at enrollment and never logged, audited, or re-returned.

### 3.1 Begin enrollment — `POST /api/v1/auth/mfa/enroll/`

**Policy key(s):** `authenticate.mfa.enroll` (risk: medium)
**Access:** Authenticated (self).
**Request:** none.
**Response:** `data` = `{ secret, otpauth_url }` — base32 secret (manual entry) + `otpauth://totp/…` URL (QR). Returned once.
**Error codes:** `AUTH_MFA_ALREADY_ENROLLED` (409) — MFA already active; `AUTHENTICATION_REQUIRED` (401).
**Business rules:** Deletes any stale pending device, creates a fresh unconfirmed `TOTPDevice`. Not active until confirmed via 3.2.

### 3.2 Confirm enrollment — `POST /api/v1/auth/mfa/verify/`

**Policy key(s):** `authenticate.mfa.verify` (risk: medium)
**Access:** Authenticated (self).
**Request:** `{ "code": "123456" }`
**Response:** empty `data`, message "MFA enabled."
**Error codes:**
- `AUTH_MFA_ALREADY_ENROLLED` (409) — MFA already active.
- `AUTH_MFA_NOT_ENROLLED` (400) — no pending enrollment to confirm.
- `AUTH_MFA_INVALID` (400) — code wrong or expired.
- `AUTHENTICATION_REQUIRED` (401).
**Business rules:** Verifies the code against the pending device and marks it confirmed. Writes `mfa_enabled`/`mfa_verification_failure` `AuthEvent`. Subsequent logins then require `otp_code`.

### 3.3 Disable MFA — `POST /api/v1/auth/mfa/disable/`

**Policy key(s):** `authenticate.mfa.disable` (risk: high)
**Access:** Authenticated (self). Superadmin MFA is mandatory and cannot be self-disabled.
**Request:** `{ "current_password": "…", "code": "123456" }`
**Response:** empty `data`, message "MFA disabled. Please log in again."
**Error codes:**
- `AUTH_MFA_MANDATORY` (403) — superadmin cannot disable mandatory MFA.
- `AUTH_MFA_NOT_ENROLLED` (400) — MFA is not enabled.
- `AUTH_PASSWORD_INCORRECT` (400) — wrong `current_password`.
- `AUTH_MFA_INVALID` (400) — code wrong or expired.
- `AUTHENTICATION_REQUIRED` (401).
**Business rules:** Requires password + a current code. Deletes the TOTP device and **revokes all sessions** (`revoked_reason=mfa_change`); clears the refresh cookie. Writes `mfa_disabled`/`mfa_verification_failure` `AuthEvent`. Superadmin recovery (lost authenticator) is the `reset_superadmin_mfa` management command, not this endpoint.

## 4. Account management

Cross-user account administration. Authorized by an inline authority hierarchy (superadmin→admin, admin→lead manager); see `SECURITY.md` §10. A target outside the caller's managed tier returns `AUTH_USER_NOT_FOUND` (404, enumeration-safe). `list` and `events` are paginated (`?page=`, `?page_size=`, default 20 / max 100).

### 4.1 List / create accounts — `GET|POST /api/v1/auth/users/`

**Policy key(s):** `authenticate.user.list` (low), `authenticate.user.create` (high)
**Access:** Authenticated; caller manages the tier below them.
**Request (create):** `{ username, authority_type, display_name?, full_name_np?, full_name_en?, email?, phone?, password? }`
**Response:** `list` → paginated list[User] (`DATA_CONTRACT.md §1`); `create` → `201` `{ user, temporary_password? }` (`DATA_CONTRACT.md` Request/Response Payload Contracts).
**Error codes:**
- `AUTH_INVALID_AUTHORITY` (403) — `authority_type` is not the tier the caller may create.
- `AUTH_USERNAME_TAKEN` (409) — username already used.
- `VALIDATION_ERROR` (400) — missing/invalid fields.
**Business rules:** Created accounts are `must_change_password=true`; a temp password is generated (returned once) when `password` is omitted. Writes `account_created`.

### 4.2 Read / update account — `GET|PATCH /api/v1/auth/users/<id>/`

**Policy key(s):** `authenticate.user.read` (low), `authenticate.user.update` (medium)
**Request (update):** partial `{ display_name?, full_name_np?, full_name_en?, email?, phone? }` — `username`/`authority_type`/status immutable.
**Response:** User.
**Error codes:** `AUTH_USER_NOT_FOUND` (404). **Business rules:** update writes `account_updated`.

### 4.3 Block / restore — `POST /api/v1/auth/users/<id>/block/` · `/restore/`

**Policy key(s):** `authenticate.user.block` (high), `authenticate.user.restore` (medium)
**Request (block):** `{ reason? }`. **Response:** empty `data`.
**Error codes:** `AUTH_USER_NOT_FOUND` (404).
**Business rules:** block deactivates + records block metadata + **revokes all target sessions** (`account_blocked`); restore reactivates + clears block metadata (`account_restored`).

### 4.4 Reset password / MFA — `POST /api/v1/auth/users/<id>/reset-password/` · `/reset-mfa/`

**Policy key(s):** `authenticate.user.reset_password` (high), `authenticate.user.reset_mfa` (high)
**Request (reset-password):** `{ password? }` (omit to auto-generate). **Response:** `{ temporary_password? }` / empty.
**Error codes:** `AUTH_USER_NOT_FOUND` (404); `AUTH_PASSWORD_WEAK` (400, reset-password) — messages in `error.details.password`.
**Business rules:** reset-password sets a temp password + `must_change_password` + **revokes all target sessions** (`admin_password_reset`); reset-mfa removes the TOTP device + **revokes all target sessions** (`mfa_reset`).

### 4.5 Account sessions & activity — `GET /users/<id>/sessions/`, `POST /users/<id>/sessions/revoke/`, `GET /users/<id>/events/`

**Policy key(s):** `authenticate.user.list_sessions` (low), `authenticate.user.revoke_sessions` (high), `authenticate.user.list_events` (low)
**Request (revoke):** `{ session_id? }` (omit to revoke all). **Response:** `sessions` → list[Session] (`DATA_CONTRACT.md` §3-style shape); `revoke` → `{ revoked:int }`; `events` → paginated list[AuthEvent].
**Error codes:** `AUTH_USER_NOT_FOUND` (404); `AUTH_SESSION_NOT_FOUND` (404, revoke with a foreign `session_id`).
**Business rules:** revoke writes `session_revoked`. `events` lists the target's `AuthEvent` rows (auth-activity review; no secrets).

## 5. Session management (own)

### 5.1 List own sessions — `GET /api/v1/auth/sessions/`

**Policy key(s):** `authenticate.session.list` (low)
**Access:** Authenticated (self). **Response:** list[Session] of the caller's active sessions.
**Error codes:** `AUTHENTICATION_REQUIRED` (401).

### 5.2 Revoke own sessions — `POST /api/v1/auth/sessions/revoke/`

**Policy key(s):** `authenticate.session.revoke` (medium)
**Access:** Authenticated (self).
**Request:** `{ session_id?, others_only? }` — one, all-but-current, or (omit both) all.
**Response:** `{ revoked:int }`.
**Error codes:** `AUTH_SESSION_NOT_FOUND` (404) — `session_id` not one of yours.
**Business rules:** revokes selected sessions (`revoked_reason=logout`); clears the refresh cookie. Revoking the current session ends it (re-login required).
