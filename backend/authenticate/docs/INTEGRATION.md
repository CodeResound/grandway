# Integration — Authenticate

**Owner app:** `authenticate`
**Version:** 1.2.0
**Status:** Active
**Created:** 2026-07-22

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial contract — Phase 1 (login, refresh, logout, me, change password) |
| 1.1.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 2 MFA — mfa/enroll·verify·disable, login `otp_code`, `mfa_enabled`/`mfa_enrollment_required` |
| 1.2.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 3 — account management (users CRUD, block/restore, admin password/MFA reset), own + admin session management, per-account auth-activity review |

---

## 1. Module

- **Name:** Authenticate — platform identity: who is calling and at what authority level. Issues session-bound JWT access tokens and revocable device sessions.
- **Base path:** `/api/v1/auth/`
- **Auth:** `login` and `refresh` are public. Everything else requires a Bearer access token. Self-service endpoints (`logout`, `me`, `password/change`, `mfa/*`, own `sessions/*`) act on your own account. Account-management endpoints (`users/*`) additionally require that your authority tier is exactly one above the target's (superadmin→admin, admin→lead manager) — enforced inline (no permission-key engine yet). There is no registration, invitation, or forgot-password flow — accounts are provisioned by a higher authority (superadmin bootstrap → admin → lead manager).

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `core` | framework | Response envelope, exception handler, `BaseModel`, Nepali text helpers | Responses lose the `{ success, message, data, meta }` shape; models fail to import |
| `django-axes` | framework | Sole brute-force lockout counter; login routes through `django.contrib.auth.authenticate()` so axes observes attempts | Repeated wrong passwords are never throttled/locked at the account level |
| `rest_framework_simplejwt` | framework | Signs/verifies the access JWT | No access token can be issued or validated; every protected call returns 401 |
| `argon2-cffi` | framework | Argon2id password hashing (primary hasher) | Passwords fall back to PBKDF2; below the app's security target |
| `django-otp` | framework | Stores the TOTP secret (`TOTPDevice`) and verifies authenticator codes | MFA enrollment/verification and the login MFA step cannot function |
| `audit` | service call | `record_auth_event` also emits each event to the central audit log (federated, best-effort) | Auth events stop appearing in the central `/api/v1/audit/` log; this app's own `AuthEvent` log and its `/users/<id>/events/` endpoint are unaffected (the emit is best-effort and never breaks auth) |

**Note for consumers:** this app authenticates and sizes authority (`superadmin`/`admin`/`lead_manager`); it does NOT authorize access to business resources. Its own account-management authority is a fixed one-tier hierarchy enforced inline — there is no application-level permission-key engine in the request path yet.

## 3. Conventions

- **Response:** project envelope — `{ success: true, message, data, meta }`. See `core/docs/INTEGRATION.md` §3.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.

```json
{ "success": true, "message": "Login successful.", "data": { "access": "<jwt>", "must_change_password": false, "user": { "…full User model — see §4…": "" } }, "meta": {} }
```

```json
{ "success": false, "error": { "code": "AUTH_CREDENTIALS_INVALID", "message": "Invalid username or password.", "details": {} }, "meta": {} }
```

- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when no/invalid access token. `403` is used for authority failures via specific codes (`AUTH_INVALID_AUTHORITY`, `AUTH_MFA_MANDATORY`), not a bare `PERMISSION_DENIED`; an out-of-authority *target* returns `AUTH_USER_NOT_FOUND` (404, enumeration-safe) rather than 403. Session-revocation/expiry surface as `AUTHENTICATION_REQUIRED` (401) on the next protected call.
- **Access token:** short-lived (15 min) Bearer JWT sent as `Authorization: Bearer <access>`. It carries a session id; the server re-validates the session on every request, so blocking/logout/password-change take effect immediately regardless of token lifetime.
- **Refresh credential:** opaque, NOT a JWT. In development it is returned in the response body as `data.refresh`; in production it is set as a `Secure; HttpOnly; SameSite` cookie (`grandway_refresh`, path `/api/v1/auth/`) and must be sent back automatically by the browser — it is never readable by JavaScript.
- **Device binding:** `login` requires a client-generated stable `device_id` — an opaque string up to 255 chars (a UUID is recommended but not server-validated; any stable non-empty string works). Persist one per browser/device. One active session per device; a user may hold at most 3 active devices concurrently. `device_name` is an optional free-text label up to 255 chars (returned in the Session read shape).
- **HTTP status:** successes are `200` EXCEPT account creation (`POST /users/`), which returns `201`. `mfa/enroll` is `200` (not 201). Error statuses are given per endpoint below.
- **MFA codes:** the authenticator code is a 6-digit numeric TOTP (30-second period, replay-protected — a code cannot be reused within its window). **Field-name split (by design):** `login` takes it as `otp_code`; `mfa/verify` and `mfa/disable` take it as `code`. Same value, different field name per endpoint — send the right key. `AUTH_MFA_INVALID` is `401` at `login` (an authentication failure) but `400` at `mfa/verify`/`mfa/disable` (bad input on an already-authenticated request) — branch on the code string, not the status alone.
- **One-step vs two-step MFA login:** you may send `otp_code` on the FIRST `login` and succeed in one call. The two-step form (login → `AUTH_MFA_REQUIRED` → resend with `otp_code`) is what happens when you omit it; both are valid. Note each `login` attempt (including an MFA reject and each wrong-code retry) counts toward the per-username login throttle — a wrong `otp_code` does NOT count toward the django-axes account lockout (that tracks passwords), but rapid retries can hit `RATE_LIMIT_EXCEEDED` (429).
- **Throttling:** `login` — 20/min per IP and 10/min per username; `refresh` — 60/min per IP. Exceeding a limit returns `RATE_LIMIT_EXCEEDED` (429). This is separate from the django-axes account lockout (which returns the uniform `AUTH_CREDENTIALS_INVALID`, never 429). Neither threshold is exposed in response headers.
- **Pagination:** applies to `GET /users/` and `GET /users/<id>/events/` — `?page=` / `?page_size=` (default 20, max 100); the paginated envelope carries `meta.count/page/page_size/next/previous` (see `core/docs/INTEGRATION.md` §3). Other list responses (`GET /sessions/`, `GET /users/<id>/sessions/`) are a bare `data` array with `meta: {}` and return **active sessions only**. `events` are ordered newest-first.
- **IDs:** UUID strings. **Times:** ISO 8601, UTC, `Z`-suffixed. **`details`:** the error `details` object is `{}` for every failure here except password-strength failures — `password/change` → `{ "new_password": [...] }`, `users/<id>/reset-password/` → `{ "password": [...] }` — and field-shape validation, which uses the global `VALIDATION_ERROR` (400) with per-field messages in `details`.
- **List/search/filter/order params:** none (audit `events` and session lists have no filters; events are newest-first).

## 4. Models

**User** — `{ id:uuid, username:string, authority_type:string[enum], display_name:string, full_name_np:string, full_name_en:string, email:string, phone:string, is_active:bool, must_change_password:bool, mfa_enabled:bool, mfa_enrollment_required:bool, last_login:string|null, created_at:string }`
- Read-only. Returned in FULL by both `login` (nested under `data.user`) and `me` — the two return the identical User object. `must_change_password` is `true` on a freshly provisioned/reset account and until the first password change. `mfa_enabled` is `true` once a TOTP device is confirmed. `mfa_enrollment_required` is `true` for a superadmin who has not yet enrolled MFA (mandatory). All timestamps are ISO 8601 UTC (`Z`); `last_login` is `null` before the first login.

**MFA enrollment** — `{ secret:string(base32), otpauth_url:string }`
- Returned ONCE by `mfa/enroll`. `secret` is the base32 TOTP secret for manual entry. `otpauth_url` is a standard `otpauth://totp/<issuer>:<username>?secret=<base32>&issuer=<issuer>&algorithm=SHA1&digits=6&period=30` URI to render as a QR code (issuer defaults to `Grandway`, SHA1 / 6 digits / 30s — the standard TOTP defaults). The secret is never returned again after enrollment.

**Session tokens** — `{ access:string(jwt), refresh?:string(opaque), must_change_password:bool, mfa_enrollment_required:bool }`
- `refresh` appears in the body only in development; in production it is a cookie and absent from the body. `access` is always in the body. `must_change_password` and `mfa_enrollment_required` here always equal the User object's fields.

**Session** — `{ id:uuid, device_id:string, device_name:string, ip_address:string|null, user_agent:string, is_active:bool, revoked_reason:string[enum], revoked_at:string|null, last_used_at:string, idle_expires_at:string, expires_at:string, created_at:string }`
- Returned by the own-session list (`GET /sessions/`) and the admin per-account session list (`GET /users/<id>/sessions/`). Never includes the refresh token or its hash.

**AuthEvent** — `{ id:uuid, event_type:string[enum], actor_username:string|null, subject_username:string, success:bool, reason:string, ip_address:string|null, device_id:string, created_at:string }`
- Returned by `GET /users/<id>/events/`. Append-only audit; never contains secrets.

**Account create/reset result** — `{ user?:User, temporary_password?:string }`
- `POST /users/` returns `{ user, temporary_password? }`; `POST /users/<id>/reset-password/` returns `{ temporary_password? }`. `temporary_password` is present ONLY when the server generated it (i.e. no `password` was supplied) and is shown once — the account must change it at next login.

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
  "mfa_enabled": true,
  "mfa_enrollment_required": false,
  "last_login": "2026-07-22T09:20:00Z",
  "created_at": "2026-07-22T09:15:00Z"
}
```

`POST /login/` → `data`:

```json
{
  "access": "<jwt>",
  "must_change_password": true,
  "mfa_enrollment_required": false,
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
    "mfa_enabled": false,
    "mfa_enrollment_required": false,
    "last_login": null,
    "created_at": "2026-07-22T09:15:00Z"
  }
}
```

## 5. Enums

- `User.authority_type`: `superadmin` | `admin` | `lead_manager`
- `Session.revoked_reason`: `logout` | `password_change` | `replaced_same_device` | `rotated` | `rotated_reuse` | `device_limit` | `blocked` | `admin_revoked` | `mfa_change` — empty string `""` on an active (non-revoked) session.
- `AuthEvent.event_type`: `superadmin_bootstrap` | `login_success` | `login_failure` | `forced_password_change` | `password_change` | `logout` | `session_refreshed` | `session_revoked` | `account_created` | `account_updated` | `account_blocked` | `account_restored` | `admin_password_reset` | `mfa_enabled` | `mfa_disabled` | `mfa_verification_failure` | `mfa_reset`

## 6. Dependency order

- A `session` needs a `User` that was provisioned by a higher authority (external to the API in Phase 1: `bootstrap_superadmin` command creates the first superadmin).
- `refresh`, `logout`, `me`, `password change`, and all `mfa/*` endpoints need an active `session` (call `login` first).
- `mfa/verify` needs a pending `mfa/enroll`; `mfa/disable` needs a confirmed (enrolled) device.
- Account management: `user.list` needs a session; `user.read`/`create` need `user.list`; `update`/`block`/`restore`/`reset-password`/`reset-mfa`/`sessions`/`events` need `user.read`; `sessions/revoke` needs `user.list_sessions`. Own-session `revoke` needs `session.list`.
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
- `otp_code` (string, optional — required only when the account has MFA enabled; see the MFA login flow in §8)

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
- `AUTH_MFA_REQUIRED` (401) — password correct but the account has MFA enabled and no `otp_code` was sent; resend `login` with `otp_code`.
- `AUTH_MFA_INVALID` (401) — the supplied `otp_code` is wrong or expired.
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

### MFA — `/api/v1/auth/mfa/`

**Use it when:** enrolling an authenticator app, and (for non-superadmins) turning MFA off. Superadmin MFA is mandatory and cannot be disabled here.

**Methods:**
- `POST /api/v1/auth/mfa/enroll/` (`authenticate.mfa.enroll`)
- `POST /api/v1/auth/mfa/verify/` (`authenticate.mfa.verify`)
- `POST /api/v1/auth/mfa/disable/` (`authenticate.mfa.disable`)

**Send (enroll):** none
**Send (verify):**
- `code` (string, required — current 6-digit authenticator code)

**Send (disable):**
- `current_password` (string, required)
- `code` (string, required — current authenticator code)

**Returns:** `enroll` → MFA enrollment `{ secret, otpauth_url }` (see §4); `verify` → empty `data`; `disable` → empty `data`.

**Requires state:**
- `enroll`: authenticated; MFA not already confirmed.
- `verify`: authenticated; a pending enrollment started by `enroll`.
- `disable`: authenticated; MFA currently enabled; the account is not a superadmin.

**Side effects:**
- `verify`: marks the TOTP device confirmed (MFA now active); writes an `AuthEvent`. Subsequent logins require `otp_code`.
- `disable`: deletes the TOTP device and **revokes all of the user's sessions** (client must log in again); clears the refresh cookie (prod); writes an `AuthEvent`.

**Notes:**
- The `enroll` `secret`/`otpauth_url` are returned only once — re-enrolling generates a new secret and invalidates any prior pending one.
- MFA does not affect the device/session model; the `otp_code` is checked at login only, after the password.
- `verify` does NOT revoke the current session (unlike `disable`/`password change`) — the access token you enrolled with stays valid.
- Ordering with forced password change: when a freshly provisioned superadmin has both `must_change_password` and `mfa_enrollment_required` true, do the password change first (it revokes sessions → re-login), then enroll MFA. Enrollment is not blocked while `must_change_password` is true, but the intended sequence is password → MFA.

**Errors:**
- `AUTH_MFA_ALREADY_ENROLLED` (409) — `enroll`/`verify` when MFA is already active.
- `AUTH_MFA_NOT_ENROLLED` (400) — `verify` with no pending enrollment, or `disable` when MFA is off.
- `AUTH_MFA_INVALID` (400) — the `code` is wrong or expired.
- `AUTH_MFA_MANDATORY` (403) — a superadmin tried to `disable` mandatory MFA.
- `AUTH_PASSWORD_INCORRECT` (400) — `disable` with a wrong `current_password`.

### Accounts — `/api/v1/auth/users/`

**Use it when:** an admin/superadmin manages the tier below them. Superadmin manages **admins**; admin manages **lead managers**; a lead manager manages no one (these endpoints return empty lists or `404` for them). Nobody manages a superadmin via the API.

**Methods:**
- `GET /api/v1/auth/users/` (`authenticate.user.list`)
- `POST /api/v1/auth/users/` (`authenticate.user.create`)
- `GET /api/v1/auth/users/<id>/` (`authenticate.user.read`)
- `PATCH /api/v1/auth/users/<id>/` (`authenticate.user.update`)
- `POST /api/v1/auth/users/<id>/block/` (`authenticate.user.block`)
- `POST /api/v1/auth/users/<id>/restore/` (`authenticate.user.restore`)
- `POST /api/v1/auth/users/<id>/reset-password/` (`authenticate.user.reset_password`)
- `POST /api/v1/auth/users/<id>/reset-mfa/` (`authenticate.user.reset_mfa`)
- `GET /api/v1/auth/users/<id>/sessions/` (`authenticate.user.list_sessions`)
- `POST /api/v1/auth/users/<id>/sessions/revoke/` (`authenticate.user.revoke_sessions`)
- `GET /api/v1/auth/users/<id>/events/` (`authenticate.user.list_events`)

**Send (create):**
- `username` (required), `authority_type` (required — must be the tier you manage), `display_name`, `full_name_np`, `full_name_en`, `email`, `phone` (optional), `password` (optional — omit to auto-generate a temporary one)

**Send (update):** any of `display_name`, `full_name_np`, `full_name_en`, `email`, `phone` (partial). `username`, `authority_type`, and account status are immutable here.

**Send (block):** `reason` (optional). **Send (reset-password):** `password` (optional — omit to auto-generate). **Send (restore / reset-mfa):** none. **Send (sessions/revoke):** `session_id` (optional — omit to revoke all of the account's sessions).

**Returns:** `list` → paginated list[User]; `create` → Account create result (`{ user, temporary_password? }`); `read`/`update` → User; `block`/`restore`/`reset-mfa` → empty `data`; `reset-password` → `{ temporary_password? }`; `sessions` → list[Session]; `sessions/revoke` → `{ revoked:int }`; `events` → paginated list[AuthEvent].

**Requires state:**
- All: a valid access token AND the caller's authority tier must be exactly one above the target's. The target must exist within the caller's managed tier — otherwise `AUTH_USER_NOT_FOUND` (not distinguishable from "no authority", by design).
- `create`: `authority_type` must equal the tier the caller manages (superadmin→admin, admin→lead_manager).

**Side effects:**
- `create`: creates the account with `must_change_password=true`; audit `account_created`.
- `block`: deactivates, records block metadata, revokes all the target's sessions; audit `account_blocked`.
- `restore`: reactivates, clears block metadata; audit `account_restored`.
- `reset-password`: sets a temp password, forces change at next login, revokes all the target's sessions; audit `admin_password_reset`.
- `reset-mfa`: removes the target's TOTP device and revokes all its sessions; audit `mfa_reset`.
- `sessions/revoke`: revokes one or all of the target's sessions; audit `session_revoked`.
- `update`: audit `account_updated`. `list`/`read`/`sessions`/`events`: none.

**Notes:**
- **Scope is by tier (type), not ownership.** An admin manages *every* lead manager in the system, not only ones they created; a superadmin manages every admin. There is no per-creator ownership. (Grandway V1 is a single consultancy.)
- **Self is not manageable here.** Acting on your own id via `users/<id>/*` returns `AUTH_USER_NOT_FOUND` (404) — you are not "one tier below" yourself. Manage your own account via `me`, `password/change`, `mfa/*`, and `sessions/*`.
- Pagination applies to `list` and `events` (`?page=`, `?page_size=`); `sessions` returns an unpaginated array of active sessions.
- `temporary_password` is present once and only when generated (no `password` supplied) — the key is **absent** otherwise, not null.

**Errors:**
- `AUTH_USER_NOT_FOUND` (404) — the target is not within the caller's managed tier (or does not exist).
- `AUTH_INVALID_AUTHORITY` (403) — `create` with an `authority_type` the caller may not create.
- `AUTH_USERNAME_TAKEN` (409) — `create` with an existing username.
- `AUTH_PASSWORD_WEAK` (400) — `reset-password` with a too-weak `password`; messages in `error.details.password`.
- `AUTH_SESSION_NOT_FOUND` (404) — `sessions/revoke` with a `session_id` not belonging to the target.
- `VALIDATION_ERROR` (400) — malformed input on `create`/`update` (missing `username`/`authority_type`, invalid email, etc.); per-field messages in `error.details`.

### Own sessions — `/api/v1/auth/sessions/`

**Use it when:** a signed-in user reviews their own devices and signs out specific ones or everywhere.

**Methods:**
- `GET /api/v1/auth/sessions/` (`authenticate.session.list`)
- `POST /api/v1/auth/sessions/revoke/` (`authenticate.session.revoke`)

**Send (revoke):**
- `session_id` (optional — revoke that one), `others_only` (optional bool — revoke all except the current session). Omit both to revoke ALL of your sessions.

**Returns:** `list` → list[Session] (your active sessions); `revoke` → `{ revoked:int }`.

**Requires state:** a valid access token.

**Side effects:** `revoke` deactivates the selected sessions; clears the refresh cookie (prod). A full/others revoke that includes the current session ends it — re-login required.

**Errors:**
- `AUTH_SESSION_NOT_FOUND` (404) — `session_id` is not one of your sessions.

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

**Enroll MFA**
1. `POST /mfa/enroll/` → `data.secret` + `data.otpauth_url`; render the URL as a QR code and show the secret for manual entry.
   - On `AUTH_MFA_ALREADY_ENROLLED` (409): MFA is already on; skip enrollment.
2. `POST /mfa/verify/` with the current authenticator `code` → MFA enabled.
   - On `AUTH_MFA_INVALID` (400): wrong/expired code → retry.
3. All future logins on this account now require `otp_code`.

**Log in with MFA enabled**
1. `POST /login/` with `username`/`password`/`device_id` (no `otp_code`) → `AUTH_MFA_REQUIRED` (401).
2. Re-`POST /login/` with the same fields plus a current `otp_code` → success.
   - On `AUTH_MFA_INVALID` (401): wrong/expired code → prompt again.

**Superadmin mandatory MFA**
1. Superadmin completes first-login password change, then `login` → `data.mfa_enrollment_required` is `true`.
2. Frontend routes to enrollment: `POST /mfa/enroll/` → `POST /mfa/verify/`.
3. `mfa_enrollment_required` becomes `false`; `disable` is refused for superadmin (`AUTH_MFA_MANDATORY`, 403).

**Provision and hand off a subordinate account** (admin creating a lead manager)
1. `POST /users/` with `{ username, authority_type: "lead_manager" }` (no `password`) → `201` with `data.temporary_password` (shown once).
   - `AUTH_INVALID_AUTHORITY` (403): you tried an `authority_type` you can't create.
   - `AUTH_USERNAME_TAKEN` (409): pick another username.
2. Deliver the temp password to the user out-of-band. They `POST /login/` → `must_change_password: true` → `POST /password/change/` (see the first-login flow).

**Recover a locked-out subordinate**
1. Lost password → `POST /users/<id>/reset-password/` (no body) → `data.temporary_password`; their sessions are revoked.
2. Lost authenticator → `POST /users/<id>/reset-mfa/` → their MFA is removed and sessions revoked; they re-enroll after next login.
3. Compromise → `POST /users/<id>/block/` (revokes all sessions); later `POST /users/<id>/restore/`.

**Review a subordinate's activity / sessions**
1. `GET /users/<id>/events/` (paginated) to review login/lockout/MFA history.
2. `GET /users/<id>/sessions/` to see active devices; `POST /users/<id>/sessions/revoke/` (optionally `{ session_id }`) to sign one or all out.

## 9. Gaps

- **MFA is TOTP-only, no recovery/backup codes** (a deliberate concept decision). A user who loses their authenticator is reset by their manager (`POST /users/<id>/reset-mfa/`); a superadmin is recovered only by the `reset_superadmin_mfa` deployment command (shell access). There is no self-service MFA recovery.
- **The management hierarchy is strictly one tier deep.** Superadmin manages admins; admin manages lead managers. A superadmin cannot directly manage a lead manager via the API, and no one manages a superadmin (recovery is the deployment commands). This is by concept design, not a limitation to work around.
- **Central audit app not built.** Authentication activity is reviewable per-account via `GET /users/<id>/events/`, but a cross-app `audit` domain is deferred until its concept file exists. These events are this app's own `AuthEvent` rows only.
- The first superadmin is still created only by the `bootstrap_superadmin` management command (no self-service signup).
- **No self-profile-edit endpoint.** `me` is read-only and `users/<id>/*` is tier-below only, so a user cannot currently change their own `email`/`phone`/`display_name` via the API — only a manager can (or an admin edits a lead manager). A self-edit endpoint is a candidate for a later phase.
- **Compromise remediation is not a single call.** `block`/`restore` alone do not rotate credentials — to fully secure a compromised account, chain `block` (or `reset-password` + `reset-mfa`, which both revoke sessions) rather than relying on block/restore alone.
- **Single-tier recovery only.** A lead manager's only API recoverer is an admin (a superadmin cannot reach a lead manager directly). If the managing tier is unavailable, there is no documented API escalation — recovery would require operator/deployment intervention.
- **Token issuance for machine clients** is not provided; only the interactive username/password login exists. In production the refresh credential is a browser HttpOnly cookie — there is no documented refresh transport for a non-browser (native/mobile) production client.
- The exact **password strength rules** are Django's configured validators (min length 12, common-password, numeric, similarity); the precise message text is returned in `error.details.new_password` rather than enumerated here.
- **Base URL** is not published here — obtain it from whoever runs the backend (locally `http://localhost:8000`). And the **first account** must be created server-side via `bootstrap_superadmin` (no self-service signup), so a purely external client cannot obtain its very first credential without operator help.
- **`authority_type`** values (`superadmin`/`admin`/`lead_manager`, §5) are the complete Phase 1 set; treat any unknown value defensively if the enum is later extended.
