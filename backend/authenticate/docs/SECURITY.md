# Security — Authenticate

**Owner app:** `authenticate`
**Version:** 1.5.0
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
| 1.4.0 | 2026-10-28 | AI (Claude Opus 5.5) | §2: reuse grace window, persistent cookie, configurable SameSite/Domain, rejected refreshes audited. §8: per-token refresh throttle; per-IP refresh rate raised and env-configurable |
| 1.5.0 | 2026-10-29 | AI (Claude Opus 5.5) | New §12 Personal clipboard — owner-only for every authority, 404 not 403, text/label/category name kept out of the audit log and logs, deliberately not in Django admin, no `must_change_password`/MFA gate, PII at rest. Old §12 renumbered §13 |

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

**Reuse grace window.** Reuse detection alone signed users out every time two tabs,
or a burst of requests answered 401 by one expired access token, refreshed with the
same cookie: the row lock serializes them, the loser finds its token already rotated,
and the family died. A token rotated less than `AUTH_REFRESH_REUSE_GRACE_SECONDS`
(default 30) ago is therefore answered with an access token for the family's current
session — no rotation, no new refresh token, no cookie — provided that session is
live and its user active. Outside the window, or once the successor is revoked, the
reuse path runs unchanged. The trade-off is the standard one: a thief replaying a
copied token within 30 s of the victim's own refresh obtains one access token (15 min,
still session-bound, so revocable); they never obtain a refresh token, and any later
replay kills the family. Set the window to 0 to disable it.

**Cookie attributes.** `SameSite` comes from `AUTH_REFRESH_COOKIE_SAMESITE` (default
`Lax`, correct for a frontend and API on one site; `None` only for a cross-site
deployment, which browsers accept only with `Secure` — always set here) and `Domain`
from `AUTH_REFRESH_COOKIE_DOMAIN` (default host-only). The cookie expires with the
session's absolute lifetime (7 days) so a browser restart does not end the session;
the server still enforces the 12-hour idle timeout on every refresh, so a persistent
cookie never outlives the server-side session. Refresh needs no CSRF token: with
`SameSite=Lax` a cross-site POST carries no cookie, and the response is unreadable
cross-origin under CORS, so a forged refresh at most rotates the victim's own token.

**Audit.** Every rejected refresh that carries a token writes a `refresh_rejected`
`AuthEvent` with the reason; a grace answer writes `session_refreshed` with reason
`grace_window`. `python manage.py auth_session_report --username <u>` summarises both
for one account.

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
`auth_refresh` (per-IP, `AUTH_REFRESH_RATE`, default 300/min) plus `auth_refresh_token`
(per presented refresh token, 10/min). These return `RATE_LIMIT_EXCEEDED` (429).

The refresh limit was per IP only at 60/min. An office behind one public IP shares
that bucket, and so does every user if `NUM_PROXIES` is wrong behind the reverse
proxy, so a busy office could throttle everyone out of refreshing. The per-IP rate is
now a ceiling and the per-token scope is the working limit. The per-IP scope cannot
be dropped: a client presenting a fresh random token each time gets a fresh per-token
bucket, but refresh tokens are 48 random bytes, so guessing is not a practical attack.

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

## §12 Personal clipboard — owner-only, PII-bearing

Every account — Superadmin, Admin, Lead Manager — has a personal clipboard of saved
snippets (`ClipboardEntry`, `ClipboardCategory`, `/api/v1/auth/me/clipboard/*`). It is the
one feature outside account self-service a Superadmin can use; it holds no consultancy
record, which is why it lives here and not in an operational app. Its `text` routinely
holds personal data (names, addresses, citizenship numbers), so:

- **Owner-only by construction.** There is no authority hierarchy here: every selector
  filters on `user=request.user` first (`get_own_clipboard*`), and every service takes the
  owning user. No endpoint accepts a user id, and no authority — Superadmin included — can
  read or change another account's clipboard through the API.
- **404, not 403.** Another account's entry or category id returns the same
  `AUTH_CLIPBOARD_ENTRY_NOT_FOUND` / `AUTH_CLIPBOARD_CATEGORY_NOT_FOUND` (404, identical
  message) as a made-up id, so ids cannot be probed. An entry write naming someone else's
  category is `AUTH_CLIPBOARD_CATEGORY_INVALID` (400) — also indistinguishable from a
  non-existent category. A list filter on someone else's category id returns an empty page.
- **Kept out of the audit trail and logs.** Writes are recorded in the central `audit` log
  only (`app_label="authenticate"`, entity types `authenticate.clipboard_entry` /
  `authenticate.clipboard_category`), carrying ids, `field_key`, the names of changed fields,
  and `entries_uncategorized` — **never the label, text, or category name**. They are not
  `AuthEvent` rows (the clipboard is a personal tool, not account security). `use` is not
  audited. No clipboard code path logs request data (CLAUDE.md §17). Tested in
  `tests/test_clipboard.py` (`test_audit_never_holds_the_text_or_label`,
  `test_category_audit_never_holds_the_name`).
- **Deliberately not registered in Django admin.** Admin would display every account's
  personal text to any staff user who can open `/admin/`, bypassing the owner-only rule.
  Inspecting a clipboard requires database access.
- **No `must_change_password` or MFA-enrollment gate**, consistent with every other
  authenticated endpoint in this app: the gate is client-side routing on the login/`me`
  flags. A session issued before a forced password change can therefore use its own
  clipboard; it cannot reach anyone else's.
- **Bounded per account:** 200 entries × 2000 characters and 50 categories, with the cap
  checked under a `select_for_update` lock on the owner's `User` row so concurrent saves
  cannot exceed it. Default authenticated throttle (1000/hour).
- **At rest:** plain database columns, protected by database access control only — no
  per-entry encryption (an accepted gap, listed in `INTEGRATION.md` §9). Entries and
  categories CASCADE-delete with the account; users are blocked, not deleted, in normal
  operation.

## §13 Deferred (later phases)

The permission-key request-path engine (a `permissions` app + `RequiresPermission` DRF
class) is not built — authorization is the inline hierarchy above. A standalone central
`audit` app is deferred until its concept file exists; authentication activity is
reviewable per-account via `GET /users/<id>/events/` over this app's own `AuthEvent` rows.
