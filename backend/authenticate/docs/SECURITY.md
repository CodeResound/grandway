# Security — Authenticate

**Owner app:** `authenticate`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-22

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial security notes — Phase 1 foundation |

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

## §9 Deferred (later phases)

MFA (`django-otp` TOTP) is not yet implemented — superadmin-mandatory MFA is therefore
not enforced in Phase 1. Admin-driven account management, session listing/remote
revocation, and account block/restore endpoints are planned but not exposed. Auth
events are persisted in-app; integration with a central `audit` app is deferred.
