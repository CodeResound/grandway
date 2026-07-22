# FLOWS — Authenticate

**Owner app:** `authenticate`
**Updated:** 2026-07-22
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/authenticate.txt` to the callable endpoints in `backend/authenticate/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

---

## Flow: Sign in and load the current user

- **Actor:** Any staff user (Superadmin / Admin / Lead Manager)
- **Goal:** Authenticate on a device and obtain the session needed to use the app.
- **Entry point:** Login screen

**Steps:**

1. **Login screen** — submit username + password + the device's stored `device_id` →
   `POST /api/v1/auth/login/` (`authenticate.session.login`)
   - **Requires state:** the account exists and is active; the `(username, ip)` pair is not locked; fewer than 3 active devices unless reusing an existing `device_id`.
   - **Side effects:** creates a session (replacing this device's prior session if any); sets `last_login`; issues an access token + refresh credential (cookie in prod, body in dev).
   - *Failure — `AUTH_CREDENTIALS_INVALID`:* inline non-specific "invalid username or password" under the form (never reveal which field or that the account is locked).
   - *Failure — `AUTH_DEVICE_LIMIT_REACHED`:* blocking dialog — "You're signed in on the maximum number of devices"; offer to continue to the Session management screen.
2. **Current-user load** — after login, hydrate the signed-in user →
   `GET /api/v1/auth/me/` (`authenticate.user.me`)
   - **Requires state:** a valid access token.
   - **Side effects:** none.
   - *Failure — `AUTHENTICATION_REQUIRED`:* redirect back to the Login screen.

## Flow: First login — forced password change

- **Actor:** A newly provisioned or admin-reset user
- **Goal:** Replace the temporary password before gaining normal access.
- **Entry point:** Login screen → Forced password change screen

**Steps:**

1. **Login screen** — sign in with the temporary password →
   `POST /api/v1/auth/login/` (`authenticate.session.login`)
   - **Requires state:** account active; temporary password valid.
   - **Side effects:** returns `must_change_password: true`; the frontend routes to the Forced password change screen instead of the home area.
   - *Failure — `AUTH_CREDENTIALS_INVALID`:* inline form error (as above).
2. **Forced password change screen** — submit temporary password + new password →
   `POST /api/v1/auth/password/change/` (`authenticate.user.change_password`)
   - **Requires state:** a valid access token (allowed even while `must_change_password` is set).
   - **Side effects:** clears `must_change_password`; **revokes ALL sessions** — the user must sign in again.
   - *Failure — `AUTH_PASSWORD_INCORRECT`:* inline error on the current-password field.
   - *Failure — `AUTH_PASSWORD_WEAK`:* inline errors on the new-password field from `error.details.new_password`.
3. **Login screen** — sign in again with the new password → `POST /api/v1/auth/login/` (`authenticate.session.login`) (see the sign-in flow).

## Flow: Stay signed in and sign out

- **Actor:** Any signed-in staff user
- **Goal:** Keep the short-lived access token fresh, then end the session.
- **Entry point:** Any authenticated screen

**Steps:**

1. **Any authenticated screen** — when a protected call returns 401, silently rotate →
   `POST /api/v1/auth/refresh/` (`authenticate.session.refresh`)
   - **Requires state:** a currently-active session whose refresh credential the client holds (cookie in prod; stored token in dev); not past idle (12h) / absolute (7d) limits.
   - **Side effects:** issues a new access token and rotates the refresh credential; the old refresh token is retired.
   - *Failure — `AUTH_REFRESH_INVALID`:* redirect to the Login screen.
   - *Failure — `AUTH_REFRESH_REUSED`:* the device family was revoked (possible token theft) — redirect to the Login screen and surface a "you were signed out for security" notice.
2. **Any authenticated screen** — sign out →
   `POST /api/v1/auth/logout/` (`authenticate.session.logout`)
   - **Requires state:** a valid access token.
   - **Side effects:** revokes the current session; clears the refresh cookie (prod).
   - *Failure — `AUTHENTICATION_REQUIRED`:* treat as already signed out; go to the Login screen.

## Flow: Enroll and use MFA

- **Actor:** Any signed-in staff user
- **Goal:** Protect the account with an authenticator app.
- **Entry point:** Security settings screen

**Steps:**

1. **Security settings screen** — start enrollment →
   `POST /api/v1/auth/mfa/enroll/` (`authenticate.mfa.enroll`)
   - **Requires state:** a valid access token; MFA not already active.
   - **Side effects:** creates a pending TOTP device; returns `secret` + `otpauth_url` once.
   - *Failure — `AUTH_MFA_ALREADY_ENROLLED`:* MFA already on — skip to a "manage MFA" view.
2. **Security settings screen** — render `otpauth_url` as a QR, user scans, submits a code →
   `POST /api/v1/auth/mfa/verify/` (`authenticate.mfa.verify`)
   - **Requires state:** a pending enrollment from step 1.
   - **Side effects:** activates MFA; all future logins require `otp_code`.
   - *Failure — `AUTH_MFA_INVALID`:* wrong/expired code — prompt to re-enter.
3. **Login screen (next sign-in)** — submit username/password/`device_id` →
   `POST /api/v1/auth/login/` (`authenticate.session.login`) returns `AUTH_MFA_REQUIRED`; resubmit with `otp_code`.
   - *Failure — `AUTH_MFA_INVALID`:* wrong/expired code — prompt again.

## Flow: Superadmin mandatory MFA

- **Actor:** Superadmin
- **Goal:** Satisfy the mandatory-MFA requirement before normal use.
- **Entry point:** Login screen → Forced MFA enrollment screen

**Steps:**

1. **Login screen** — after the forced password change, sign in →
   `POST /api/v1/auth/login/` (`authenticate.session.login`) returns `data.mfa_enrollment_required = true`.
   - **Side effects:** frontend routes to the Forced MFA enrollment screen instead of home.
2. **Forced MFA enrollment screen** — enroll then confirm →
   `POST /api/v1/auth/mfa/enroll/` (`authenticate.mfa.enroll`) then `POST /api/v1/auth/mfa/verify/` (`authenticate.mfa.verify`).
   - **Side effects:** `mfa_enrollment_required` becomes false; the account is now fully usable.
   - Note: `POST /api/v1/auth/mfa/disable/` (`authenticate.mfa.disable`) is refused for superadmins (`AUTH_MFA_MANDATORY`). Lost-authenticator recovery is the `reset_superadmin_mfa` deployment command (cross-app: operator/CLI, not an API).

## Flow: Provision a subordinate account

- **Actor:** Superadmin (creates admins) or Admin (creates lead managers)
- **Goal:** Create the next-tier account and hand off a temporary password.
- **Entry point:** Account management screen

**Steps:**

1. **Account management screen** — open the create form →
   `GET /api/v1/auth/users/` (`authenticate.user.list`) to show existing accounts.
2. **Create account form** — submit username + one-tier-below `authority_type` →
   `POST /api/v1/auth/users/` (`authenticate.user.create`)
   - **Requires state:** caller's tier is exactly one above the requested `authority_type`.
   - **Side effects:** account created `must_change_password`; `temporary_password` returned once.
   - *Failure — `AUTH_INVALID_AUTHORITY`:* the chosen tier isn't creatable by you.
   - *Failure — `AUTH_USERNAME_TAKEN`:* choose another username.
3. Deliver the temp password out-of-band; the user then follows the **First login — forced password change** flow.

## Flow: Recover or secure a subordinate

- **Actor:** Admin/Superadmin managing the tier below
- **Goal:** Resolve a lost password, lost authenticator, or compromised account.
- **Entry point:** Account detail screen

**Steps:**

1. **Account detail screen** — load the account and its state →
   `GET /api/v1/auth/users/<id>/` (`authenticate.user.read`).
   - *Failure — `AUTH_USER_NOT_FOUND`:* the account is outside your authority (or absent) — show not-found.
2. **Account detail screen** — pick a remedy:
   - Lost password → `POST /api/v1/auth/users/<id>/reset-password/` (`authenticate.user.reset_password`) → `temporary_password` once; sessions revoked.
   - Lost authenticator → `POST /api/v1/auth/users/<id>/reset-mfa/` (`authenticate.user.reset_mfa`) → MFA removed; sessions revoked.
   - Compromise → `POST /api/v1/auth/users/<id>/block/` (`authenticate.user.block`); later `POST /api/v1/auth/users/<id>/restore/` (`authenticate.user.restore`).
3. **Optional review** — `GET /api/v1/auth/users/<id>/events/` (`authenticate.user.list_events`) and `GET /api/v1/auth/users/<id>/sessions/` (`authenticate.user.list_sessions`); force sign-out via `POST /api/v1/auth/users/<id>/sessions/revoke/` (`authenticate.user.revoke_sessions`).

## Flow: Manage my own devices

- **Actor:** Any signed-in user
- **Goal:** Review active devices and sign specific ones (or all others) out.
- **Entry point:** My sessions screen

**Steps:**

1. **My sessions screen** — list active devices →
   `GET /api/v1/auth/sessions/` (`authenticate.session.list`).
2. **My sessions screen** — revoke one, all-others, or all →
   `POST /api/v1/auth/sessions/revoke/` (`authenticate.session.revoke`) with `{ session_id }` or `{ others_only: true }` or empty.
   - **Side effects:** selected sessions end; revoking the current one requires re-login.
   - *Failure — `AUTH_SESSION_NOT_FOUND`:* the `session_id` isn't yours.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `authenticate.session.login` | `POST /api/v1/auth/login/` | Sign in; First login; Stay signed in | Public |
| `authenticate.session.refresh` | `POST /api/v1/auth/refresh/` | Stay signed in and sign out | Public (credential is the refresh token) |
| `authenticate.session.logout` | `POST /api/v1/auth/logout/` | Stay signed in and sign out | |
| `authenticate.user.me` | `GET /api/v1/auth/me/` | Sign in and load the current user | |
| `authenticate.user.change_password` | `POST /api/v1/auth/password/change/` | First login — forced password change | Also used for voluntary change; revokes all sessions |
| `authenticate.mfa.enroll` | `POST /api/v1/auth/mfa/enroll/` | Enroll MFA; Superadmin mandatory MFA | Returns secret + otpauth URL once |
| `authenticate.mfa.verify` | `POST /api/v1/auth/mfa/verify/` | Enroll MFA; Superadmin mandatory MFA | Activates MFA |
| `authenticate.mfa.disable` | `POST /api/v1/auth/mfa/disable/` | Disable MFA | Not permitted for superadmin; revokes all sessions |
| `authenticate.user.list` | `GET /api/v1/auth/users/` | Provision a subordinate; Manage a subordinate | Paginated; scoped to managed tier |
| `authenticate.user.create` | `POST /api/v1/auth/users/` | Provision a subordinate | Returns temp password once |
| `authenticate.user.read` | `GET /api/v1/auth/users/<id>/` | Manage a subordinate | |
| `authenticate.user.update` | `PATCH /api/v1/auth/users/<id>/` | Manage a subordinate | Profile fields only |
| `authenticate.user.block` | `POST /api/v1/auth/users/<id>/block/` | Recover/secure a subordinate | Revokes all sessions |
| `authenticate.user.restore` | `POST /api/v1/auth/users/<id>/restore/` | Recover/secure a subordinate | |
| `authenticate.user.reset_password` | `POST /api/v1/auth/users/<id>/reset-password/` | Recover/secure a subordinate | Temp password once; revokes sessions |
| `authenticate.user.reset_mfa` | `POST /api/v1/auth/users/<id>/reset-mfa/` | Recover/secure a subordinate | Removes MFA; revokes sessions |
| `authenticate.user.list_sessions` | `GET /api/v1/auth/users/<id>/sessions/` | Review a subordinate | |
| `authenticate.user.revoke_sessions` | `POST /api/v1/auth/users/<id>/sessions/revoke/` | Review a subordinate | One or all |
| `authenticate.user.list_events` | `GET /api/v1/auth/users/<id>/events/` | Review a subordinate | Paginated; auth-activity review |
| `authenticate.session.list` | `GET /api/v1/auth/sessions/` | Manage my own devices | |
| `authenticate.session.revoke` | `POST /api/v1/auth/sessions/revoke/` | Manage my own devices | One / others / all |

## Cross-app dependencies

- **This app references (outbound):** none
- **Referenced by other apps (inbound):** none yet — future apps will depend on a valid session (access token) issued here, but no other app's flow file references these endpoints today.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.

## Open questions

- **MFA shipped in Phase 2** (TOTP enroll/verify/disable + login `otp_code` + superadmin-mandatory). No recovery/backup codes (concept-locked); cross-user admin MFA reset is Phase 3.
- **Session management screen** (list active devices, revoke a specific device, revoke all) is referenced by the device-limit dialog but its endpoints are not built yet (later phase).
- Whether a voluntary password change should keep the current session alive instead of revoking all sessions is unresolved; Phase 1 revokes all. The same open question applies to MFA disable.
