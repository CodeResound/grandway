# Session Iteration Log — 2026-07-22 19:19

Branch: `build_authenticate_phase1_20260722_1835`

## Authenticate

## 1. Module

- **Name:** Authenticate
- **Base path:** `/api/v1/auth/`
- **Auth:** `login` and `refresh` are public; `logout`, `me`, `password/change` require a Bearer access token (session-bound). No registration/invitation/forgot-password.

## 2. Conventions

- **Response:** standard envelope `{ success, message, data, meta }`.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when the access token is missing/invalid or its session is revoked/expired.
- **Pagination:** not applicable — no list endpoints.
- **IDs:** UUID strings.
- **Times:** ISO 8601 UTC, `Z`-suffixed.
- **Access token:** 15-min Bearer JWT carrying a session id; the server re-validates the session every request.
- **Refresh credential:** opaque (not a JWT); response body in development, `Secure; HttpOnly; SameSite` cookie (`grandway_refresh`) in production.
- **Device binding:** `login` requires a client-supplied `device_id`; `device_name` optional.
- **Throttling:** login 20/min per IP + 10/min per username; refresh 60/min per IP; `RATE_LIMIT_EXCEEDED` (429).
- **List/search/filter/order params:** none.

## 3. Models

- **User** — `{ id:uuid, username, authority_type[enum], display_name, full_name_np, full_name_en, email, phone, is_active:bool, must_change_password:bool, last_login?:string, created_at:string }`. Returned in full by `login` (nested `data.user`) and `me`.
- **Session tokens** — `{ access, refresh?, must_change_password:bool }`. `refresh` present in body only in development.

## 4. Enums

- `User.authority_type`: `superadmin` | `admin` | `lead_manager`

## 5. Dependency order

- A session needs a `User` provisioned by a higher authority (the first superadmin via the `bootstrap_superadmin` command).
- `refresh`, `logout`, `me`, `change_password` need an active session — call `login` first.
- **Start here:** `POST /api/v1/auth/login/` with a `device_id`.

## 6. Endpoints

### Session — `/api/v1/auth/`

**Use it when:** signing a user in, keeping them signed in, signing them out.

**Methods:**
- `POST /api/v1/auth/login/` (`authenticate.session.login`)
- `POST /api/v1/auth/refresh/` (`authenticate.session.refresh`)
- `POST /api/v1/auth/logout/` (`authenticate.session.logout`)

**Send (login):**
- `username` (required)
- `password` (required)
- `device_id` (required)
- `device_name` (optional)

**Send (refresh):**
- `refresh` (development only; production uses the cookie)

**Send (logout):**
- none

**Returns:** `login` → Session tokens + nested full `User`; `refresh` → `{ access, must_change_password }` + rotated refresh; `logout` → empty `data`.

**Notes:**
- `login`/`refresh` are the only public endpoints and are throttled.
- Login errors are uniform (`AUTH_CREDENTIALS_INVALID`) across wrong password, unknown user, blocked, and lockout — no enumeration.
- Same-`device_id` re-login replaces that device's session; max 3 active devices.

**Errors:**
- `AUTH_CREDENTIALS_INVALID` (401) — any login failure.
- `AUTH_DEVICE_LIMIT_REACHED` (409) — new device beyond the 3-device cap.
- `AUTH_REFRESH_INVALID` (401) — missing/unknown/expired refresh credential.
- `AUTH_REFRESH_REUSED` (401) — retired refresh token replayed; family revoked.

### User — `/api/v1/auth/`

**Use it when:** loading the signed-in user, and changing the password (including forced first-login change).

**Methods:**
- `GET /api/v1/auth/me/` (`authenticate.user.me`)
- `POST /api/v1/auth/password/change/` (`authenticate.user.change_password`)

**Send (password change):**
- `current_password` (required)
- `new_password` (required)

**Returns:** `me` → full `User`; `password change` → empty `data`.

**Notes:**
- `password change` is allowed while `must_change_password` is set (this is how it is cleared) and revokes ALL sessions on success — the client must log in again.

**Errors:**
- `AUTH_PASSWORD_INCORRECT` (400) — wrong `current_password`.
- `AUTH_PASSWORD_WEAK` (400) — `new_password` fails strength rules; messages in `error.details.new_password`.

## 7. Flows

- **First login:** provisioned out-of-band (temp password, `must_change_password=true`) → `login` (id `sid1`) returns `must_change_password:true` → `password/change` clears it and revokes all sessions → `login` again with the new password.
  - Failure `AUTH_PASSWORD_WEAK` → show `error.details.new_password`, retry.
- **Session lifecycle:** `login` (device A) → use access token → on 401, `refresh` (rotates) → `logout`.
  - Failure `AUTH_REFRESH_REUSED`/`AUTH_REFRESH_INVALID` → family gone → `login` again.
- **Multi-device limit:** `login` A, B, C succeed → `login` D → `AUTH_DEVICE_LIMIT_REACHED` (409). Resolve by logging out a device or re-login on an existing `device_id`.

## 8. Gaps

- MFA not implemented (planned via django-otp); no MFA step or code field yet.
- Account management (create/block/restore) and session listing/remote revocation not exposed yet.
- No machine-client token issuance; only interactive username/password login. No documented refresh transport for non-browser production clients.
- Base URL not published; first superadmin requires the `bootstrap_superadmin` shell command.

## Core

## 1. Module

- **Name:** Core (infrastructure) + Core Policy Engine
- **Base path:** `/api/v1/policy/` (policy engine); `/health/`, `/ready/`, `/admin/` outside `/api/v1/`.
- **Auth:** unchanged.

## 2. Conventions

- No changes this session.

## 3. Models

- No endpoint-facing model changes. (Infrastructure change only: `AUTH_USER_MODEL` is now `authenticate.User`; `core.policy_engine` endpoints are unchanged.)

## 4. Enums

- No changes.

## 5. Dependency order

- No changes.

## 6. Endpoints

- No endpoint changes to `core.policy_engine` this session. Settings, the project-level `core/docs/INTEGRATION.md` (auth section, app inventory, dependency graph), and policy-engine view tests were updated as a consequence of introducing the `authenticate` app and switching `AUTH_USER_MODEL`, but no `core` endpoint's path, method, contract, or permission key changed.

## 7. Flows

- No changes.

## 8. Gaps

- No new gaps introduced in `core`. The project-level integration doc's stale "no token-issuance endpoint exists" warning was corrected now that `authenticate` ships login/refresh.
