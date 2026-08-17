# Security — Authenticate

**Owner app:** `authenticate`
**Version:** 1.3.0
**Status:** Active
**Created:** 2026-07-22

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial security notes — Phase 1 foundation |
| 1.1.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 2 MFA — TOTP section (§9), placement/secret/mandatory/recovery |
| 1.2.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 3 — inline authority-hierarchy authorization (§10), enumeration-safe targeting, session-invalidating admin actions |
| 1.3.0 | 2026-08-17 | AI (Claude Fable 5) | §11: /admin/ OTP-gated via OTPAdminSite + OTPMiddleware; password hash excluded from the user form (was readonly-rendered). Security audit S3. Old §11 renumbered §12 |

---

## §1 Session-bound JWT (immediate revocation)

Access tokens are short-lived (15 min) signed JWTs carrying a session id (`sid`),
`authority_type`, and `must_change_password`. A valid signature is **not**
sufficient: `SessionBoundJWTAuthentication` re-loads the `AuthSession` on every
request and rejects it (401) if the session is revoked/expired, the account is
inactive (blocked), the token's authority no longer matches the user, or the
password was changed after the session began (`password_changed_at > session.created_at`).
This makes blocking, logout, session revocation, and password change take effect
immediately regardless of the token's remaining lifetime. The signing algorithm is
pinned server-side (`HS256`); an incoming token's `alg` header is never trusted, and
`iss`/`aud` are validated on decode.

## §2 Refresh tokens — opaque, hashed, rotated, reuse-detected

The refresh credential is an opaque 48-byte URL-safe random token, never a JWT.
Only its SHA-256 hash is stored (`AuthSession.refresh_token_hash`), so a database
leak does not expose reusable credentials. Every refresh rotates the token: a new
session row is created in the same `family_id` with `previous_session` set, and the
presented token's row is retired. Presenting a **retired** token (reuse) revokes the
entire `family_id` — the standard mitigation for a stolen/copied refresh token.
Transport: HttpOnly + Secure + SameSite cookie in production (never readable by JS,
never in local storage); response body in development only.

## §3 Brute-force lockout — django-axes

`django-axes` is the sole failed-attempt counter (there is deliberately no
`failed_login_count` field). Login routes credential checks through
`django.contrib.auth.authenticate()` so axes observes every attempt, including
`/admin/login/`. Lockout is by `(username, ip_address)` (balances self-DoS against
distributed credential stuffing); `AxesMiddleware` is the last middleware and
`AxesStandaloneBackend` precedes `ModelBackend`. On lockout the backend raises
`PermissionDenied`, `authenticate()` returns `None`, and the service returns the
generic `AUTH_CREDENTIALS_INVALID`.

## §4 Anti-enumeration and uniform errors

Login never reveals whether the username exists, the password was wrong, the account
is blocked, or the account is locked — all return the identical
`AUTH_CREDENTIALS_INVALID` (401). `ModelBackend` runs a constant-time dummy hash for
unknown users, so response timing does not leak account existence. **Deliberate
tension:** account lockout is enforced but never signaled to the caller — preserving
non-enumeration is prioritized over telling a legitimate user they are locked out.

## §5 Password hashing

Argon2id (`Argon2PasswordHasher`, argon2-cffi backend) is the primary hasher; PBKDF2
variants remain as fallback verifiers so legacy hashes still validate and upgrade on
next login. New/reset accounts carry `must_change_password=true` and receive only a
temporary password that must be replaced on first login. Strength is enforced by
Django's configured validators (min length 12, common-password, numeric, similarity).

## §6 Device limits

Login requires a client-supplied stable `device_id`. At most one active session per
`(user, device_id)` (DB unique constraint, `condition=is_active=True`) and at most
`AUTH_MAX_ACTIVE_DEVICES` (3) active sessions per user (enforced in the service inside
`atomic()` with `select_for_update`). Re-login on a known device replaces that
device's session; a new device beyond the cap is rejected (`AUTH_DEVICE_LIMIT_REACHED`,
409) rather than silently evicting another device.

## §7 Secret handling and audit

Passwords, temporary passwords, password hashes, JWTs, refresh tokens/hashes, and
(future) MFA secrets are never logged, never placed in `AuthEvent` rows, and never
returned in API responses. `AuthEvent` is an append-only audit log (its `delete()`
raises `ImmutabilityError`); it records actor, subject, outcome, reason category, IP,
user agent, and device id — but no secret material. Login failures are audited even
for unknown usernames (via `subject_username`), yet the caller still receives only the
generic error.

## §8 Rate limiting

Beyond axes' stateful lockout, DRF scoped throttles cap burst rate before credentials
are checked: `auth_login_ip` (per-IP), `auth_login_user` (per submitted username), and
`auth_refresh` (per-IP). These return `RATE_LIMIT_EXCEEDED` (429).

## §9 MFA (TOTP)

TOTP MFA is provided by `django-otp` (`TOTPDevice`); the authenticate service verifies
codes directly (no `OTPMiddleware`). Key properties:

- **Login placement:** the `otp_code` is checked only AFTER a correct password, so MFA
  status never leaks to an attacker without valid credentials. A correct password with
  MFA enabled and no/invalid code returns `AUTH_MFA_REQUIRED`/`AUTH_MFA_INVALID` — both
  reachable only post-password.
- **Enrollment:** `mfa/enroll` creates an unconfirmed device and returns the secret +
  otpauth URL exactly once; `mfa/verify` confirms it with a live code. The secret is
  never returned again, never logged, and never placed in an `AuthEvent`.
- **Secret at rest:** stored by django-otp's own model (DB-level protection). No app-level
  field encryption is added; the concept's "or otherwise strongly protected at rest" is
  met by database protection. Recorded as an accepted decision, not an oversight.
- **Mandatory for superadmin:** `mfa_enrollment_required` is derived (`superadmin` AND not
  enrolled) and surfaced on login/`me`; superadmins cannot self-disable MFA
  (`AUTH_MFA_MANDATORY`). Frontends force enrollment after the first password change.
- **No recovery codes** (concept-locked). Loss of an authenticator is resolved by the reset
  hierarchy: a non-superadmin via admin reset (Phase 3), a superadmin via the
  `reset_superadmin_mfa` deployment command. Disabling or resetting MFA revokes all sessions
  (`revoked_reason=mfa_change`).
- **Replay protection:** django-otp's `verify_token` enforces the TOTP step counter, so a
  code cannot be reused within its window.

## §10 Authorization — inline authority hierarchy (Phase 3)

Cross-user account and session management is authorized by a strict, one-tier-deep
hierarchy enforced in the service layer (there is NO permission-key engine in the
request path yet — that remains a separate, separately-approved effort per `CLAUDE.md`
§9):

- Superadmin manages **admins**; admin manages **lead managers**; a lead manager manages
  no one. Nobody manages a superadmin via the API (recovery is the deployment commands).
- The managed target is resolved through `get_managed_target`, which returns the account
  only if it is in the caller's single managed tier. A target outside that tier — or a
  non-existent one — yields the **same** `AUTH_USER_NOT_FOUND` (404), so an actor cannot
  enumerate or probe accounts they have no authority over (self is likewise not in the
  managed set, so self-management via these endpoints returns 404).
- `create` additionally checks that the requested `authority_type` equals the tier the
  caller manages (`AUTH_INVALID_AUTHORITY`, 403).
- **Session-invalidating side effects:** block, administrative password reset, and MFA
  reset each revoke ALL of the target's sessions immediately (the session-bound auth in §1
  makes this effective on the next request). Account creation forces a password change at
  first login.
- Every management action writes an `AuthEvent` with the acting `actor` and the `subject`,
  so cross-user actions are always attributable (the concept's accountability requirement).

## §11 Django admin — OTP-gated, no service-layer side door

Since 2026-08-17 (pre-production security audit, finding S3) `/admin/` is served by
`django_otp.admin.OTPAdminSite` (swapped in `core.apps.CoreConfig.ready()`, backed by
`OTPMiddleware` in `MIDDLEWARE`): admin login requires a **verified TOTP device** in the
same session, so the password-only side door around the API's MFA mandate is closed. An
account with no confirmed device cannot enter the admin at all — fail closed; enrol via
the API's MFA endpoints first. This narrows the earlier posture (§13 field hardening only)
where any `is_staff` password login was admitted.

The admin remains a read surface: accounts cannot be created, authority/staff/active
flags are read-only, and the password hash is **excluded** from the user form outright —
it earlier sat in `readonly_fields`, which still renders the value. Admin sessions are
still Django sessions, not `AuthSession` rows — they remain outside the API's server-side
revocation model, which is why the OTP gate and the read-only surface both matter.
Tested in `core/tests/test_admin_otp.py` and `tests/test_admin_hardening.py`.

## §12 Deferred (later phases)

The permission-key request-path engine (a `permissions` app + `RequiresPermission` DRF
class) is not built — authorization is the inline hierarchy above. A standalone central
`audit` app is deferred until its concept file exists; authentication activity is
reviewable per-account via `GET /users/<id>/events/` over this app's own `AuthEvent` rows.
