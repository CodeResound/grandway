# Session 20261028_2349 — refresh/session sign-out fix (branch `fix/refresh_session_logouts_20261028_2349`)

## Authenticate

## 1. Module
- Name: Authenticate
- Base path: `/api/v1/auth/`
- Auth: unchanged this session (`login`/`refresh` public; everything else Bearer access token)

## 2. Conventions
- Response: `login` and `refresh` add `access_expires_at` (ISO 8601 UTC, `Z`-suffixed) — the access token's expiry
- Error: `AUTH_REFRESH_INVALID` now carries `error.details.reason` (previously `details` was `{}`)
- Auth failures:
  - an expired, malformed, or revoked-session access token returns `AUTHENTICATION_FAILED` (401); `AUTHENTICATION_REQUIRED` (401) only when no token is sent
  - documentation previously named only `AUTHENTICATION_REQUIRED`; clients must refresh on any 401 from a protected call
- Pagination: no changes this session
- IDs: no changes this session
- Times: no changes this session
- List/search/filter/order params: no changes this session
- Refresh cookie (production): `grandway_refresh`, `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/api/v1/auth/`; now expires with the session's absolute lifetime (7 days) instead of at browser close
- Throttling: `refresh` — 300/min per IP (was 60/min) plus 10/min per refresh credential; `RATE_LIMIT_EXCEEDED` (429)

## 3. Models
- **Session tokens** `{ access, access_expires_at, refresh?, must_change_password, mfa_enrollment_required }`
  - `access_expires_at` is new
  - `refresh` is absent (both transports) on a grace-window refresh answer
  - `refresh` responses omit `mfa_enrollment_required`

## 4. Enums
- Session.revoked_reason: adds `expired`
- AuthEvent.event_type: adds `refresh_rejected`
- AUTH_REFRESH_INVALID error.details.reason: `missing` | `not_found` | `expired` | `blocked` | `logout` | `password_change` | `replaced_same_device` | `rotated_reuse` | `admin_revoked` | `mfa_change` | `device_limit`

## 5. Dependency order
- No changes this session.

## 6. Endpoints

### Login — `/api/v1/auth/login/`
**Use it when:** the login screen signs a user in.
**Methods:**
- POST `/api/v1/auth/login/`
**Send (create/update):** none — request body unchanged
**Returns:** Session tokens + nested `user` (now with `access_expires_at`)
**Notes:**
- The refresh cookie (production) persists across browser restarts for the session's absolute lifetime
**Errors:**
- none new

### Refresh — `/api/v1/auth/refresh/`
**Use it when:** any authenticated screen keeps the user signed in — ahead of `access_expires_at`, or after any 401 from a protected call.
**Methods:**
- POST `/api/v1/auth/refresh/`
**Send (create/update):** none — request unchanged (cookie in production, `refresh` in the body in development)
**Returns:** Session tokens (without `mfa_enrollment_required`)
**Notes:**
- Concurrent refreshes with one credential (several tabs, a burst of 401s) all succeed: within 30 s of a rotation the old credential is answered with an access token for the current session, no new refresh credential, and no `Set-Cookie`
- A rotated credential replayed after 30 s still revokes the device's session family
**Errors:**
- `AUTH_REFRESH_INVALID` (401) — credential unusable; `error.details.reason` says why (`replaced_same_device` = this device signed in again)
- `AUTH_REFRESH_REUSED` (401) — rotated credential replayed after the grace window; session family revoked
- `RATE_LIMIT_EXCEEDED` (429) — throttled; the session is intact, retry later

### Revoke own sessions — `/api/v1/auth/sessions/revoke/`
**Use it when:** the "my devices" screen signs out other devices or this one.
**Methods:**
- POST `/api/v1/auth/sessions/revoke/`
**Send (create/update):** none — request unchanged (`session_id?`, `others_only?`)
**Returns:** `{ revoked:int }` — unchanged
**Notes:**
- The refresh cookie is cleared only when the caller's own session is revoked; `others_only: true` or another session's id now keeps the caller signed in (previously it signed them out at the next refresh)
**Errors:**
- none new

## 7. Flows
**Stay signed in**
1. `POST /api/v1/auth/login/` → store `data.access` and `data.access_expires_at`.
2. Shortly before `access_expires_at`, `POST /api/v1/auth/refresh/` → new `access` + `access_expires_at`.
   - Any protected call returns 401 first → refresh, then retry that call once.
   - `RATE_LIMIT_EXCEEDED` (429) → back off and retry; do not sign out.
   - `AUTH_REFRESH_INVALID` / `AUTH_REFRESH_REUSED` (401) → go to login; word the notice from `error.details.reason`.

**Sign out other devices**
1. `POST /api/v1/auth/sessions/revoke/` with `{ others_only: true }` → `data.revoked` = count.
2. Keep using the current session; no re-login needed.

## 8. Gaps
- In development body mode a grace-window refresh returns no `refresh`; the client must keep the newest refresh token it has received.

## Core

## 1. Module
- Name: Core (project-level conventions)
- Base path: `/api/v1/`
- Auth: unchanged this session

## 2. Conventions
- Error: global codes now list `AUTHENTICATION_FAILED` (401) beside `AUTHENTICATION_REQUIRED` (401)
- Auth failures: refresh on any 401 from a protected endpoint (see Authenticate)
- All other conventions: no changes this session

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint changes this session.

## 7. Flows
- No new flows.

## 8. Gaps
- none
