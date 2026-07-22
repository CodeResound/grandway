# Integration — Authenticate

**Owner app:** `authenticate`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-22

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial contract — Phase 1 (login, refresh, logout, me, change password) |

---

## 1. Module

- **Name:** Authenticate — platform identity: who is calling and at what authority level. Issues session-bound JWT access tokens and revocable device sessions.
- **Base path:** `/api/v1/auth/`
- **Auth:** `login` and `refresh` are public. `logout`, `me`, and `password/change` require a Bearer access token. There is no registration, invitation, or forgot-password flow — accounts are provisioned by a higher authority (superadmin bootstrap → admin → lead manager).

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `core` | framework | Response envelope, exception handler, `BaseModel`, Nepali text helpers | Responses lose the `{ success, message, data, meta }` shape; models fail to import |
| `django-axes` | framework | Sole brute-force lockout counter; login routes through `django.contrib.auth.authenticate()` so axes observes attempts | Repeated wrong passwords are never throttled/locked at the account level |
| `rest_framework_simplejwt` | framework | Signs/verifies the access JWT | No access token can be issued or validated; every protected call returns 401 |
| `argon2-cffi` | framework | Argon2id password hashing (primary hasher) | Passwords fall back to PBKDF2; below the app's security target |

**Note for consumers:** this app authenticates and sizes authority (`superadmin`/`admin`/`lead_manager`); it does NOT authorize access to business resources. It has no dependency on an application-level permission system in Phase 1.

## 3. Conventions

- **Response:** project envelope — `{ success: true, message, data, meta }`. See `core/docs/INTEGRATION.md` §3.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.

```json
{ "success": true, "message": "Login successful.", "data": { "access": "<jwt>", "must_change_password": false, "user": { "…full User model — see §4…": "" } }, "meta": {} }
```

```json
{ "success": false, "error": { "code": "AUTH_CREDENTIALS_INVALID", "message": "Invalid username or password.", "details": {} }, "meta": {} }
```

- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when no/invalid access token; `PERMISSION_DENIED` (403) is not used by this app in Phase 1 (endpoints are public or self-service). Session-revocation/expiry surface as `AUTHENTICATION_REQUIRED` (401) on the next protected call.
- **Access token:** short-lived (15 min) Bearer JWT sent as `Authorization: Bearer <access>`. It carries a session id; the server re-validates the session on every request, so blocking/logout/password-change take effect immediately regardless of token lifetime.
- **Refresh credential:** opaque, NOT a JWT. In development it is returned in the response body as `data.refresh`; in production it is set as a `Secure; HttpOnly; SameSite` cookie (`grandway_refresh`, path `/api/v1/auth/`) and must be sent back automatically by the browser — it is never readable by JavaScript.
- **Device binding:** `login` requires a client-generated stable `device_id` — an opaque string up to 255 chars (a UUID is recommended but not server-validated; any stable non-empty string works). Persist one per browser/device. One active session per device; a user may hold at most 3 active devices concurrently. `device_name` is an optional free-text label up to 255 chars (write-only in Phase 1 — no endpoint reads it back yet).
- **HTTP status:** `login` success is `200` (not `201`). Other successes are `200`. Error statuses are given per endpoint below.
- **Throttling:** `login` — 20/min per IP and 10/min per username; `refresh` — 60/min per IP. Exceeding a limit returns `RATE_LIMIT_EXCEEDED` (429). This is separate from the django-axes account lockout (which returns the uniform `AUTH_CREDENTIALS_INVALID`, never 429). Neither threshold is exposed in response headers.
- **Pagination:** not applicable — no list endpoints in Phase 1.
- **IDs:** UUID strings. **Times:** ISO 8601, UTC, `Z`-suffixed. **`details`:** the error `details` object is `{}` for every failure here except `AUTH_PASSWORD_WEAK`, which carries `{ "new_password": [ "...message...", ... ] }`.
- **List/search/filter/order params:** none.

## 4. Models

**User** — `{ id:uuid, username:string, authority_type:string[enum], display_name:string, full_name_np:string, full_name_en:string, email:string, phone:string, is_active:bool, must_change_password:bool, last_login:string|null, created_at:string }`
- Read-only. Returned in FULL by both `login` (nested under `data.user`) and `me` — the two return the identical User object. `must_change_password` is `true` on a freshly provisioned/reset account and until the first password change. All timestamps are ISO 8601 UTC (`Z`); `last_login` is `null` before the first login.

**Session tokens** — `{ access:string(jwt), refresh?:string(opaque), must_change_password:bool }`
- `refresh` appears in the body only in development; in production it is a cookie and absent from the body. `access` is always in the body. `must_change_password` here always equals the User object's field — they cannot disagree.

### Worked examples

`GET /me/` → **User** (as `data`):

```json
{
  "id": "6f1c2e2a-9b7e-4d3a-8c2f-1a2b3c4d5e6f",
  "username": "ramesh.admin",
  "authority_type": "admin",
  "display_name": "Ramesh Shrestha",
  "full_name_np": "रमेश श्रेष्ठ",
  "full_name_en": "Ramesh Shrestha",
  "email": "ramesh@example.com",
  "phone": "",
  "is_active": true,
  "must_change_password": false,
  "last_login": "2026-07-22T09:20:00Z",
  "created_at": "2026-07-22T09:15:00Z"
}
```

`POST /login/` → `data`:

```json
{
  "access": "<jwt>",
  "must_change_password": true,
  "refresh": "<opaque-dev-only>",
  "user": {
    "id": "6f1c2e2a-9b7e-4d3a-8c2f-1a2b3c4d5e6f",
    "username": "ramesh.admin",
    "authority_type": "admin",
    "display_name": "Ramesh Shrestha",
    "full_name_np": "रमेश श्रेष्ठ",
    "full_name_en": "Ramesh Shrestha",
    "email": "ramesh@example.com",
    "phone": "",
    "is_active": true,
    "must_change_password": true,
    "last_login": null,
    "created_at": "2026-07-22T09:15:00Z"
  }
}
```

## 5. Enums

- `User.authority_type`: `superadmin` | `admin` | `lead_manager`

## 6. Dependency order

- A `session` needs a `User` that was provisioned by a higher authority (external to the API in Phase 1: `bootstrap_superadmin` command creates the first superadmin).
- `refresh`, `logout`, `me`, `password change` all need an active `session` (call `login` first).
- **Start here:** obtain credentials out-of-band, then `POST /login/` with a `device_id`.

## 7. Endpoints

### Session — `/api/v1/auth/`

**Use it when:** signing a user in, keeping them signed in, and signing them out.

**Methods:**
- `POST /api/v1/auth/login/` (`authenticate.session.login`)
- `POST /api/v1/auth/refresh/` (`authenticate.session.refresh`)
- `POST /api/v1/auth/logout/` (`authenticate.session.logout`)

**Send (login):**
- `username` (string, required)
- `password` (string, required)
- `device_id` (string, required — stable per-device UUID)
- `device_name` (string, optional)

**Send (refresh):**
- `refresh` (string) — development only; in production the cookie is used and the body is empty

**Send (logout):** none (uses the access token + its session)

**Returns:** `login` → Session tokens + nested `user`; `refresh` → `{ access, must_change_password }` (+ rotated refresh via body/cookie); `logout` → empty `data`.

**Requires state:**
- `login`: the target account exists and is active (not blocked); the `(username, ip)` pair is not locked out; fewer than 3 active devices unless re-using an existing `device_id`.
- `refresh`: a currently-active session whose refresh credential you hold; not expired (idle 12h / absolute 7d).
- `logout`: a valid access token.

**Side effects:**
- `login`: creates an `AuthSession`; if the same `device_id` was already active, that prior session is revoked and replaced; sets `last_login`; writes an `AuthEvent`.
- `refresh`: rotates the session (new refresh issued, old one retired); presenting a retired refresh token revokes the whole device family; writes an `AuthEvent`.
- `logout`: revokes the current session; clears the refresh cookie (prod); writes an `AuthEvent`.

**Notes:**
- `login`/`refresh` are throttled (per-IP and, for login, per-username) and are the only public endpoints.
- Login errors are deliberately uniform — the same `AUTH_CREDENTIALS_INVALID` is returned for wrong password, unknown user, blocked account, and lockout (no enumeration).

**Errors:**
- `AUTH_CREDENTIALS_INVALID` (401) — login failed (any reason; uniform).
- `AUTH_DEVICE_LIMIT_REACHED` (409) — login from a new device while 3 devices are already active.
- `AUTH_REFRESH_INVALID` (401) — refresh credential missing, unknown, or expired.
- `AUTH_REFRESH_REUSED` (401) — a retired refresh token was replayed; the session family was revoked.

### User — `/api/v1/auth/`

**Use it when:** loading the signed-in user after login, and letting them change their password (including the forced first-login change).

**Methods:**
- `GET /api/v1/auth/me/` (`authenticate.user.me`)
- `POST /api/v1/auth/password/change/` (`authenticate.user.change_password`)

**Send (password change):**
- `current_password` (string, required)
- `new_password` (string, required)

**Returns:** `me` → **User**; `password change` → empty `data`.

**Requires state:**
- Both: a valid access token. `password change` is permitted even while `must_change_password` is `true` (it is how the user clears it).

**Side effects:**
- `password change`: replaces the password hash, sets `must_change_password=false` + `password_changed_at`, and **revokes all of the user's sessions** — the client must log in again afterward; clears the refresh cookie (prod); writes an `AuthEvent`.

**Notes:**
- After a successful password change every session (including the current one) is invalidated by design; treat a `200` as "now redirect to login".

**Errors:**
- `AUTH_PASSWORD_INCORRECT` (400) — `current_password` did not match.
- `AUTH_PASSWORD_WEAK` (400) — `new_password` failed strength rules; offending messages are in `error.details.new_password`.

## 8. Flows

**First login after provisioning**
1. Superadmin/admin provisions the account out-of-band; the user receives a temporary password and `must_change_password=true`.
2. `POST /login/` with `device_id` → `data.must_change_password` is `true`; you receive an access token.
3. `POST /password/change/` with the temporary password as `current_password` and the new password.
   - On `AUTH_PASSWORD_WEAK` (400): show `error.details.new_password` and retry.
4. All sessions are revoked → send the user back to `POST /login/` with the new password.

**Steady-state session lifecycle**
1. `POST /login/` (device A) → store access in memory; refresh is a cookie (prod) or `data.refresh` (dev).
2. Use the access token until a protected call returns `AUTHENTICATION_REQUIRED` (401).
3. `POST /refresh/` → new access (+ rotated refresh).
   - On `AUTH_REFRESH_REUSED`/`AUTH_REFRESH_INVALID` (401): the family is gone → `POST /login/` again.
4. `POST /logout/` to end the session on this device.

**Multi-device limit**
1. `login` on devices A, B, C (distinct `device_id`s) → three active sessions.
2. `login` on device D → `AUTH_DEVICE_LIMIT_REACHED` (409).
   - Resolve by `logout` on one device, then retry device D; or re-login on an existing `device_id` (replaces that device's session, no new device slot used).

## 9. Gaps

- **MFA** is not implemented in Phase 1 (planned via `django-otp`). Login is username + password only; there is no MFA step or code field yet.
- **Account management** (create/block/restore admin & lead-manager accounts) and **session listing / remote revocation** are not exposed yet — planned for later phases. The first superadmin is created only by the `bootstrap_superadmin` management command.
- **Token issuance for machine clients** is not provided; only the interactive username/password login exists. In production the refresh credential is a browser HttpOnly cookie — there is no documented refresh transport for a non-browser (native/mobile) production client.
- The exact **password strength rules** are Django's configured validators (min length 12, common-password, numeric, similarity); the precise message text is returned in `error.details.new_password` rather than enumerated here.
- **Base URL** is not published here — obtain it from whoever runs the backend (locally `http://localhost:8000`). And the **first account** must be created server-side via `bootstrap_superadmin` (no self-service signup), so a purely external client cannot obtain its very first credential without operator help.
- **`authority_type`** values (`superadmin`/`admin`/`lead_manager`, §5) are the complete Phase 1 set; treat any unknown value defensively if the enum is later extended.
