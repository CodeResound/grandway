# Session Iteration Log — 2026-07-22 19:49

Branch: `add_mfa_totp_20260722_1928`

## Authenticate

## 1. Module

- **Name:** Authenticate
- **Base path:** `/api/v1/auth/`
- **Auth:** `login`/`refresh` public; `logout`, `me`, `password/change`, and all `mfa/*` require a Bearer access token. This session adds TOTP MFA.

## 2. Conventions

- **Response/Error:** unchanged standard envelope.
- **MFA codes:** 6-digit numeric TOTP, 30s period, replay-protected. Field-name split by design: `login` uses `otp_code`; `mfa/verify`/`mfa/disable` use `code`.
- **`AUTH_MFA_INVALID` status:** `401` at `login`, `400` at `mfa/verify`/`mfa/disable`.
- **MFA login:** one-step (send `otp_code` on first `login`) or two-step (omit → `AUTH_MFA_REQUIRED` → resend with code) both valid.

## 3. Models

- **User** — adds derived read-only fields `mfa_enabled:bool` and `mfa_enrollment_required:bool` (returned by `login.data.user` and `me`).
- **Session tokens** — adds `mfa_enrollment_required:bool` at top level of `login` `data`.
- **MFA enrollment** — `{ secret:string(base32), otpauth_url:string }`, returned once by `mfa/enroll`.
- No new `authenticate` DB model — MFA secret lives in django-otp's external `TOTPDevice`; MFA state is derived from `TOTPDevice.confirmed`.

## 4. Enums

- No client-facing enum changes. (Internal: `AuthEvent.event_type` gained `mfa_enabled`/`mfa_disabled`/`mfa_verification_failure`/`mfa_reset`; `AuthSession.revoked_reason` gained `mfa_change` — not surfaced over HTTP.)

## 5. Dependency order

- `mfa/enroll` needs an active session (login first).
- `mfa/verify` needs a pending `mfa/enroll`.
- `mfa/disable` needs a confirmed (enrolled) device; refused for superadmin.
- **Start here:** `POST /login/`, then `POST /mfa/enroll/`.

## 6. Endpoints

### Login — `/api/v1/auth/login/` (changed)

**Use it when:** signing in an account that may have MFA enabled.

**Methods:**
- `POST /api/v1/auth/login/` (`authenticate.session.login`)

**Send (create):**
- `username`, `password`, `device_id` (required)
- `device_name` (optional)
- `otp_code` (optional — required when the account has MFA enabled)

**Returns:** Session tokens + nested full `User`, now including `mfa_enrollment_required`.

**Errors:**
- `AUTH_MFA_REQUIRED` (401) — password correct, MFA enabled, no `otp_code`.
- `AUTH_MFA_INVALID` (401) — `otp_code` wrong or expired.

### MFA — `/api/v1/auth/mfa/`

**Use it when:** enrolling an authenticator and (non-superadmins) disabling it.

**Methods:**
- `POST /api/v1/auth/mfa/enroll/` (`authenticate.mfa.enroll`)
- `POST /api/v1/auth/mfa/verify/` (`authenticate.mfa.verify`)
- `POST /api/v1/auth/mfa/disable/` (`authenticate.mfa.disable`)

**Send (enroll):**
- none

**Send (verify):**
- `code` (required)

**Send (disable):**
- `current_password` (required)
- `code` (required)

**Returns:** `enroll` → `{ secret, otpauth_url }` (once); `verify` → empty `data`; `disable` → empty `data`.

**Notes:**
- `verify` activates MFA and does not revoke the current session; `disable` deletes the device and revokes all sessions.
- Superadmin MFA is mandatory: `disable` is refused (`AUTH_MFA_MANDATORY`); recovery is the `reset_superadmin_mfa` deployment command.

**Errors:**
- `AUTH_MFA_ALREADY_ENROLLED` (409) — enroll/verify when MFA already active.
- `AUTH_MFA_NOT_ENROLLED` (400) — verify with no pending device, or disable with MFA off.
- `AUTH_MFA_INVALID` (400) — code wrong or expired.
- `AUTH_MFA_MANDATORY` (403) — superadmin tried to disable.
- `AUTH_PASSWORD_INCORRECT` (400) — disable with wrong `current_password`.

## 7. Flows

- **Enroll MFA:** `mfa/enroll` (get secret+otpauth_url) → scan → `mfa/verify` with `code` → MFA active → future logins need `otp_code`.
- **Log in with MFA:** `login` (no code) → `AUTH_MFA_REQUIRED` → `login` + `otp_code` → success. (Or send `otp_code` on the first call.)
- **Superadmin mandatory MFA:** after forced password change, `login` → `data.mfa_enrollment_required = true` → enroll+verify → flag clears; `disable` refused (`AUTH_MFA_MANDATORY`).

## 8. Gaps

- No recovery/backup codes (concept-locked); no API-callable MFA recovery for any actor yet. Non-superadmin reset is Phase 3 (cross-user); superadmin recovery is the `reset_superadmin_mfa` shell command.
- Repeated wrong `otp_code` retries count toward the per-username login throttle (429), not the axes password lockout.

## Core

## 1. Module

- **Name:** Core (infrastructure) + Core Policy Engine
- **Base path:** `/api/v1/policy/`; health/admin outside `/api/v1/`.
- **Auth:** unchanged.

## 2. Conventions

- No changes.

## 3. Models

- No endpoint-facing model changes. (Infrastructure: `django_otp` + `otp_totp` added to `INSTALLED_APPS`; `OTP_TOTP_ISSUER` setting added.)

## 4. Enums

- No changes.

## 5. Dependency order

- No changes.

## 6. Endpoints

- No `core.policy_engine` endpoint changes this session. Settings and the project-level `core/docs/INTEGRATION.md` dependency graph were updated to reflect the `authenticate` app's new `django-otp` dependency; no `core` endpoint's path, method, contract, or permission key changed.

## 7. Flows

- No changes.

## 8. Gaps

- No new gaps introduced in `core`.
