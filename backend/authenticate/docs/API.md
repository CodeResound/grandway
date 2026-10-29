# API Documentation — Authenticate

**App:** `authenticate`
**Version:** 1.5.0
**Base prefix:** `/api/v1/auth/`
**Auth:** Mixed. `login`/`refresh` are public; `logout`/`me`/`password/change` require a Bearer access token validated by `authenticate.authentication.SessionBoundJWTAuthentication` (see `SECURITY.md` §1). No `is_staff` gate — the three protected endpoints are self-service (any authenticated user acting on their own account).
**Throttle:** Custom scopes — `login` uses `LoginIPThrottle` + `LoginUsernameThrottle` (`auth_login_ip` 20/min, `auth_login_user` 10/min); `refresh` uses `RefreshThrottle` (`auth_refresh`, per IP, `AUTH_REFRESH_RATE`, default 300/min) + `RefreshTokenThrottle` (`auth_refresh_token`, per presented refresh token, 10/min). Stateful account lockout is handled by django-axes (see `SECURITY.md` §3), not DRF.
**Access level:** Public (`login`, `refresh`) + authenticated self-service (`logout`, `me`, `password/change`, `mfa/*`, own `sessions/*`, and the personal clipboard `me/clipboard/*` — §6) + the one-tier account-management hierarchy (`users/*`, §4). The clipboard endpoints use the project default user throttle (1000/hour).

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial API docs — Phase 1 foundation (5 endpoints) |
| 1.1.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 2 MFA — 3 mfa endpoints, login `otp_code` + MFA errors, `me` mfa fields |
| 1.2.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 3 — account management (users CRUD + block/restore + admin password/MFA reset), session management, auth-activity review |
| 1.3.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (User `full_name`). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |
| 1.4.0 | 2026-10-28 | AI (Claude Opus 5.5) | Refresh reuse grace window; `access_expires_at` on login/refresh; `error.details.reason` on `AUTH_REFRESH_INVALID`; per-token refresh throttle; persistent refresh cookie with configurable `SameSite`/`Domain`; own-session revoke no longer clears the caller's cookie when only other sessions go. Non-breaking |
| 1.5.0 | 2026-10-29 | AI (Claude Opus 5.5) | §6 Personal clipboard — 9 endpoints under `/api/v1/auth/me/clipboard/` (entries: list/create/update/delete/use; categories: list/create/rename/delete). Every authority, Superadmin included; owner-only. Additive, non-breaking |

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
**Response:** `data` = `{ access, access_expires_at, must_change_password, mfa_enrollment_required, user }` (+ `refresh` in the body in development only; HttpOnly cookie in production). `access_expires_at` is the access token's `exp` as ISO 8601 UTC (`…Z`); refresh ahead of it. The cookie (`grandway_refresh`, `Path=/api/v1/auth/`, `HttpOnly`, `Secure`, `SameSite` = `AUTH_REFRESH_COOKIE_SAMESITE` default `Lax`, `Domain` = `AUTH_REFRESH_COOKIE_DOMAIN` default host-only) expires with the session's absolute lifetime (7 days), so it survives a browser restart. `user` is the **User** read shape — see `DATA_CONTRACT.md §1`.
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
**Response:** `data` = `{ access, access_expires_at, must_change_password }` (+ rotated `refresh` via body/cookie — **absent** on a grace-window answer, see business rules).
**Throttle:** `auth_refresh` per IP (default 300/min, `AUTH_REFRESH_RATE`) and `auth_refresh_token` per presented token (10/min) → `RATE_LIMIT_EXCEEDED` (429).
**Error codes:**
- `AUTH_REFRESH_INVALID` (401) — the credential cannot be used. `error.details.reason` says why: `missing` (none sent), `not_found` (unknown token), `expired` (idle 12h / absolute 7d), `blocked` (account inactive), or the revoked session's reason — `logout`, `password_change`, `replaced_same_device` (this `device_id` logged in again), `rotated_reuse`, `admin_revoked`, `mfa_change`, `device_limit`. Every rejection with a token writes a `refresh_rejected` `AuthEvent`.
- `AUTH_REFRESH_REUSED` (401) — a retired (already-rotated) token was replayed **outside** the grace window; the whole device family is revoked.
**Business rules:** Rotation — a new session row is created in the same `family_id` with `previous_session` set; the old row is retired (`revoked_reason=rotated`). Reuse detection keys off the retired row. **Reuse grace window:** a rotated token presented within `AUTH_REFRESH_REUSE_GRACE_SECONDS` (default 30) of its rotation, while its family still has a live session for an active user, is a concurrent refresh (two tabs, a burst of 401s), not reuse: the response is 200 with an access token for the family's *current* session, no new refresh token and no `Set-Cookie` (the winning request already set it); audited as `session_refreshed` with reason `grace_window`. An expired session is revoked with `revoked_reason=expired` (previously mislabelled `admin_revoked`, and rolled back so it stayed active).

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
**Request (create):** `{ username, authority_type, display_name?, full_name?, email?, phone?, password? }`
**Response:** `list` → paginated list[User] (`DATA_CONTRACT.md §1`); `create` → `201` `{ user, temporary_password? }` (`DATA_CONTRACT.md` Request/Response Payload Contracts).
**Error codes:**
- `AUTH_INVALID_AUTHORITY` (403) — `authority_type` is not the tier the caller may create.
- `AUTH_USERNAME_TAKEN` (409) — username already used.
- `VALIDATION_ERROR` (400) — missing/invalid fields.
**Business rules:** Created accounts are `must_change_password=true`; a temp password is generated (returned once) when `password` is omitted. Writes `account_created`.
**Query access pattern:** `select_related("security_state")` plus an `Exists` annotation for the confirmed-TOTP flag — the two MFA fields previously cost up to two device queries per row (2026-08-17 audit, P2). Fixed query count asserted by `tests/test_accounts.py::TestAccountListQueryCount`.

### 4.2 Read / update account — `GET|PATCH /api/v1/auth/users/<id>/`

**Policy key(s):** `authenticate.user.read` (low), `authenticate.user.update` (medium)
**Request (update):** partial `{ display_name?, full_name?, email?, phone? }` — `username`/`authority_type`/status immutable.
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
**Business rules:** revokes selected sessions (`revoked_reason=logout`). The refresh cookie is cleared only when the caller's own session is among them (omit both fields, or `session_id` = the current session); `others_only=true` or another session's id leaves the caller signed in. Revoking the current session ends it (re-login required).

## 6. Personal clipboard (own)

A per-account store of saved text snippets (frequently typed names, addresses, ward details) that the user copies into document forms. **Every authority has one — Superadmin included** — which makes it the one feature outside account self-service that a Superadmin can use. Strictly owner-only: every lookup starts from `request.user`, so another account's entry or category id returns the same 404 as a made-up id (never 403). No sharing, no applicant-linked entries. Response shapes: `DATA_CONTRACT.md §6` (ClipboardCategory) and `§7` (ClipboardEntry).

**Access (all of §6):** Authenticated (self), any `authority_type`. No `must_change_password` or MFA-enrollment gate — consistent with every other authenticated endpoint here. **Throttle:** project default `user` scope (1000/hour). Admin site: not registered (see `SECURITY.md` §12).

### 6.1 List / save entries — `GET|POST /api/v1/auth/me/clipboard/`

**Policy key(s):** `authenticate.clipboard_entry.list` (low), `authenticate.clipboard_entry.create` (low)
**Request (list, query):** `?field_key=a,b` (comma list, exact match, each key must match `^[a-z0-9_]+(\.[a-z0-9_]+)*$`; whole param ≤500 chars), `?category=<uuid>|none` (`none` = uncategorized; another account's category id simply matches nothing), `?search=` (≤100; `icontains` on label, text, or category name, OR'd), `?page=`/`?page_size=` (standard pagination).
**Request (create):**
```json
{ "label": "Ward 7 chairman", "text": "Ram Bahadur Thapa", "field_key": "ward.spokesperson.name", "category": "3c1f7e0a-5d2b-4b8e-9a61-0f2d4c6b8e11" }
```
**Response:** `list` → paginated list[ClipboardEntry] (`message` is `""`, as on every paginated list); `create` → `201` ClipboardEntry, message "Clipboard entry saved."
**Validation rules:** `label` required, ≤120, Unicode-normalized, trimmed, blank rejected; `text` required, ≤2000 (`MAX_CLIPBOARD_TEXT`), normalized, trimmed, blank rejected; `field_key` optional, ≤100, blank allowed (stored as `""`), must match the regex above ("Use lowercase dotted words, e.g. 'father.name'."); `category` optional UUID or `null`.
**Error codes:**
- `AUTH_CLIPBOARD_LIMIT_REACHED` (400) — "A clipboard holds at most 200 entries."
- `AUTH_CLIPBOARD_CATEGORY_INVALID` (400) — `category` is not one of the caller's categories (another account's, or non-existent); "That category is not one of yours.", repeated in `error.details.category`.
- `VALIDATION_ERROR` (400) — field rules above, or a bad `field_key`/`category` filter value ("Expected a category id or 'none'.").
- `AUTHENTICATION_REQUIRED` / `AUTHENTICATION_FAILED` (401).
**Business rules:** create locks the owner's `User` row (`select_for_update`) inside `atomic()` before counting, so two concurrent saves cannot both pass the 200 cap. Writes a central `audit` event `clipboard_entry_created` (metadata `{field_key}` only). List ordering: `usage_count` desc, then `last_used_at` desc (never-used last), then `created_at` desc. There is no `ordering` parameter.
**Query access pattern:** `ClipboardEntry.objects.select_related("category").filter(user=…)`; indexes `(user, -usage_count)` serve the ordering and `(user, field_key)` the form lookup. One query per page plus the count.

### 6.2 Update / delete an entry — `PATCH|DELETE /api/v1/auth/me/clipboard/<entry_id>/`

**Policy key(s):** `authenticate.clipboard_entry.update` (low), `authenticate.clipboard_entry.delete` (low)
**Request (update):** any subset of `{ label, text, field_key, category }` — same rules as 6.1; `field_key: ""` clears it; `category: null` uncategorizes.
**Response:** `update` → ClipboardEntry, "Clipboard entry updated."; `delete` → `{ "deleted": true }`, "Clipboard entry deleted."
**Error codes:**
- `AUTH_CLIPBOARD_ENTRY_NOT_FOUND` (404) — "No such entry on your clipboard." (checked before body validation).
- `AUTH_CLIPBOARD_CATEGORY_INVALID` (400) — update names a category that is not the caller's.
- `VALIDATION_ERROR` (400).
**Business rules:** update writes `clipboard_entry_updated` only when a value actually changed (metadata `{fields: [names], field_key}` — never values); an unchanged PATCH returns 200 and writes nothing. Delete is a **hard delete** (nothing references an entry) and writes `clipboard_entry_deleted` (metadata `{field_key}`).

### 6.3 Use an entry — `POST /api/v1/auth/me/clipboard/<entry_id>/use/`

**Policy key(s):** `authenticate.clipboard_entry.use` (low)
**Request:** none.
**Response:** the ClipboardEntry with `usage_count` incremented and `last_used_at` (and `updated_at`) set to now; "Clipboard entry used."
**Error codes:** `AUTH_CLIPBOARD_ENTRY_NOT_FOUND` (404).
**Business rules:** one `UPDATE … SET usage_count = usage_count + 1` (race-safe). **Not audited** — a ranking signal, not an act. Call it when the user copies the entry.

### 6.4 List / create categories — `GET|POST /api/v1/auth/me/clipboard/categories/`

**Policy key(s):** `authenticate.clipboard_category.list` (low), `authenticate.clipboard_category.create` (low)
**Request (create):** `{ "name": "Ward office" }`
**Response:** `list` → **bare, unpaginated** list[ClipboardCategory] (≤50), ordered by name ignoring case, "Clipboard categories retrieved."; `create` → `201` ClipboardCategory, "Clipboard category created."
**Validation rules:** `name` required, ≤60, normalized, trimmed, blank rejected; unique per account ignoring case.
**Error codes:**
- `AUTH_CLIPBOARD_CATEGORY_NAME_TAKEN` (400) — "You already have a category with that name.", repeated in `error.details.name`. Checked before the limit.
- `AUTH_CLIPBOARD_CATEGORY_LIMIT_REACHED` (400) — "A clipboard holds at most 50 categories."
- `VALIDATION_ERROR` (400).
**Business rules:** create locks the owner row inside `atomic()` before the name and count checks; DB backstop `UniqueConstraint(Lower("name"), "user")`. Writes `clipboard_category_created` (no metadata — the name is never recorded).
**Query access pattern:** one query — `filter(user=…).annotate(entry_count=Count("entries")).order_by(Lower("name"), "id")`.

### 6.5 Rename / delete a category — `PATCH|DELETE /api/v1/auth/me/clipboard/categories/<category_id>/`

**Policy key(s):** `authenticate.clipboard_category.update` (low), `authenticate.clipboard_category.delete` (low)
**Request (rename):** `{ "name": "…" }` (required — not partial).
**Response:** `rename` → ClipboardCategory, "Clipboard category renamed."; `delete` → `{ "deleted": true, "entries_uncategorized": 3 }`, "Clipboard category deleted."
**Error codes:**
- `AUTH_CLIPBOARD_CATEGORY_NOT_FOUND` (404) — "No such category on your clipboard."
- `AUTH_CLIPBOARD_CATEGORY_NAME_TAKEN` (400) — rename to another of the caller's names (a case-only change of its own name is allowed).
- `VALIDATION_ERROR` (400).
**Business rules:** rename to the identical name is a no-op (no audit). Delete keeps the entries — FK `SET_NULL` makes them uncategorized — and writes `clipboard_category_deleted` with metadata `{entries_uncategorized}`.

**AI debugging notes (§6):** a "missing" entry is almost always another account's id — the 404 is deliberate. Clipboard writes appear only in the central `audit` log (`app_label="authenticate"`, `entity_type` `authenticate.clipboard_entry`/`authenticate.clipboard_category`), never in `AuthEvent`. The audit write is a direct `audit.services.record_event` call, not the best-effort federation `record_auth_event` uses: a failure surfaces as a 500 and the write rolls back — every clipboard service is `@transaction.atomic`, so the change and its audit event commit together.
