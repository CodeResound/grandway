# Data Contract — Authenticate

**Owner app:** `authenticate`
**Version:** 1.2.0
**Status:** Active
**Created:** 2026-07-22
**Purpose:** Owns platform identity: the login account (`User`), its non-identity security state (`UserSecurityState`), revocable device-bound refresh sessions (`AuthSession`), and an append-only authentication audit log (`AuthEvent`). It establishes *who* is calling and *which authority level* applies. It does NOT own authorization decisions (which leads/applicants/documents a user may touch — those stay with operational apps), the failed-login counter (owned by `django-axes`), or MFA device secrets (owned by `django-otp`, MFA phase).

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial contract — Phase 1 foundation (User, UserSecurityState, AuthSession, AuthEvent) |
| 1.1.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 2 MFA — external `TOTPDevice`, `mfa_change` revocation reason, 4 MFA event types, derived MFA state |
| 1.2.0 | 2026-07-22 | AI (Claude Opus 4.8) | Phase 3 — account/session management: 3 new event types, block metadata usage, account create/reset payloads (no new tables) |

---

## Deliberate Deviations

The concept file (`concepts/authenticate.txt`) and the initial session plan are realized through the platform template's pre-existing human-approved design:

- Brute-force lockout uses `django-axes`, not a `failed_login_count` field on `User` — matches the approved `core/docs/THIRD_PARTY_LIBRARIES.md` entry; a custom counter was explicitly rejected there.
- Security state lives in a separate `UserSecurityState` model, not as columns on `User`.
- Authentication audit is an in-app append-only `AuthEvent` model (not deferred to structured logging), which `core/management/commands/reset_dev_data.py` already treats as immutable.
- MFA is deferred to a later phase; no MFA fields are stored (`mfa_enrolled` will be derived from `django-otp`'s `TOTPDevice.confirmed`, never stored here).

---

## 1. User

**Purpose:** The permanent login account and its authority level. Username is the immutable login identifier; bilingual display names follow §39.1.
**Table:** `authenticate_user`
**`authority_type` choices:** `superadmin`, `admin`, `lead_manager`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Public primary key |
| username | CharField(150) | Yes | No | No | Unique, ASCII-only, normalized; immutable after creation |
| authority_type | CharField(20) | Yes | No | No | Platform authority level (choices above) |
| display_name | CharField(255) | Yes | No | No | Required human-facing label (§39.1 legacy required) |
| full_name_np | CharField(255) | No | No | No | Devanagari official name (blank allowed) |
| full_name_en | CharField(255) | No | No | No | Roman-script name (blank allowed) |
| full_name_romanized | CharField(255) | No | No | Yes | Auto-populated ASCII of `full_name_np` for trigram search; never hand-entered |
| email | EmailField | No | No | No | Optional contact email (blank allowed); not a login field |
| phone | CharField(32) | No | No | No | Optional contact phone (blank allowed) |
| is_active | Boolean | — | No | No | `False` == blocked; blocking never deletes |
| is_staff | Boolean | — | No | No | Django-admin access; `True` for superadmin/admin |
| is_superuser | Boolean | — | No | No | PermissionsMixin; `True` for superadmin |
| last_login | DateTime | No | Yes | Yes | Set on successful login |
| created_at | DateTime | — | No | Yes | Creation timestamp (UTC) |
| updated_at | DateTime | — | No | Yes | Last update timestamp (UTC) |

**Validation Rules:**
- `username`: ASCII-only (no Devanagari), normalized (case-folded, trimmed) before uniqueness check; immutable — write serializers reject changes.
- `full_name_np` / `full_name_en` / `display_name`: `normalize_unicode` applied on write (§39.2).
- `full_name_romanized`: auto-populated from `full_name_np` in the service layer; never required in write serializers (§39.3).
- `authority_type`: must be one of the three choices; only a higher authority may create a lower one (enforced in service, later phases).

**Indexes:** `username` (unique); `authority_type` (filtering); trigram GIN on `full_name_np`/`full_name_en`/`full_name_romanized` deferred to the search phase.

**Soft Delete:** N/A — accounts are never deleted; blocking sets `is_active=False` (see `UserSecurityState` block metadata). Historical attribution is preserved.

**Example:**
```json
{
  "id": "6f1c2e2a-9b7e-4d3a-8c2f-1a2b3c4d5e6f",
  "username": "ramesh.admin",
  "authority_type": "admin",
  "display_name": "Ramesh Shrestha",
  "full_name_np": "रमेश श्रेष्ठ",
  "full_name_en": "Ramesh Shrestha",
  "email": "ramesh@example.com",
  "is_active": true,
  "created_at": "2026-07-22T09:15:00Z"
}
```

**Security Notes:** Password hash (Argon2id) is stored in the inherited `password` column and is never serialized, logged, or returned. `username` is stable and safe to log; the password never is.

---

## 2. UserSecurityState

**Purpose:** Per-account security/lifecycle state kept off the identity row: forced-password-change flag, password-change timestamp (drives immediate session revocation), provisioning provenance, and block metadata.
**Table:** `authenticate_usersecuritystate`
**`provisioned_via` choices:** `bootstrap_command`, `superadmin_created`, `admin_created`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| user | OneToOne(User) | Yes | No | No | Owning account (`related_name="security_state"`) |
| must_change_password | Boolean | — | No | No | `True` forces a password change before normal access |
| password_changed_at | DateTime | No | Yes | No | Last successful password change; sessions issued before this are invalid |
| provisioned_via | CharField(20) | Yes | No | No | How the account was created (choices above) |
| blocked_at | DateTime | No | Yes | No | When the account was blocked (`is_active=False`) |
| blocked_by | FK(User) | No | Yes | No | Actor who blocked (`on_delete=SET_NULL`, `related_name="blocks_performed"`) |
| blocked_reason | TextField | No | No | No | Reason for block (blank when active); normalized on write |
| created_at | DateTime | — | No | Yes | Creation timestamp |
| updated_at | DateTime | — | No | Yes | Last update timestamp |

**Validation Rules:**
- Exactly one row per `User` (OneToOne). Created together with the `User` in the same `atomic()` block by the account-creation service.
- `password_changed_at` is set by the password-change service, never by clients.
- `blocked_reason` normalized via `normalize_unicode` (§39.2).

**Indexes:** `user` (unique via OneToOne).

**Soft Delete:** N/A — deleted only by cascade when a `User` is hard-deleted (dev reset only); never soft-deleted in normal operation.

**Example:**
```json
{
  "must_change_password": true,
  "password_changed_at": null,
  "provisioned_via": "bootstrap_command",
  "blocked_at": null,
  "blocked_reason": ""
}
```

**Security Notes:** Never stores `failed_login_count` (owned by `django-axes`) or MFA secrets (owned by `django-otp`). `mfa_enrolled` is intentionally not stored — it will be derived live in the MFA phase.

---

## 3. AuthSession

**Purpose:** A server-known, device-bound, revocable refresh session. Its `id` is the `sid` claim carried by every access JWT; the opaque refresh credential is stored only as a hash. Enforces device limits and rotation/reuse detection.
**Table:** `authenticate_authsession`
**`revoked_reason` choices:** `logout`, `password_change`, `replaced_same_device`, `rotated`, `rotated_reuse`, `device_limit`, `blocked`, `admin_revoked`, `mfa_change`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key; used as the JWT `sid` claim |
| user | FK(User) | Yes | No | No | Session owner (`related_name="sessions"`) |
| device_id | CharField(255) | Yes | No | No | Client-supplied stable device identifier (indexed) |
| device_name | CharField(255) | No | No | No | Human label for the device (blank allowed) |
| refresh_token_hash | CharField(64) | Yes | No | Yes | SHA-256 hex of the opaque refresh token; unique |
| family_id | UUID | — | No | Yes | Rotation family; reuse of a retired token revokes the whole family |
| previous_session | FK(self) | No | Yes | No | Prior session in the rotation chain (`on_delete=SET_NULL`) |
| ip_address | GenericIPAddress | No | Yes | No | Source IP at issue/last use |
| user_agent | TextField | No | No | No | Source user agent (blank allowed) |
| is_active | Boolean | — | No | No | `True` while the session is usable (indexed) |
| revoked_at | DateTime | No | Yes | No | When revoked |
| revoked_reason | CharField(30) | No | No | No | Why revoked (choices above; blank while active) |
| last_used_at | DateTime | — | No | Yes | Last successful use (login/refresh) |
| idle_expires_at | DateTime | — | No | No | Sliding idle expiry (extended on refresh) |
| expires_at | DateTime | — | No | No | Absolute expiry (fixed at issue) |
| created_at | DateTime | — | No | Yes | Issue timestamp |
| updated_at | DateTime | — | No | Yes | Last update timestamp |

**Validation Rules:**
- At most one **active** session per `(user, device_id)` — DB `UniqueConstraint` with `condition=Q(is_active=True)`.
- At most `AUTH_MAX_ACTIVE_DEVICES` (default 3) active sessions per user — enforced in the service inside `atomic()`; a new device beyond the cap is rejected (`AUTH_DEVICE_LIMIT_REACHED`).
- A session is valid only while `is_active` and `now < idle_expires_at` and `now < expires_at`.
- On refresh: the presented token's hash must match an active session; a match on an already-rotated (inactive) token revokes every session sharing `family_id` (`rotated_reuse`).

**Indexes:** `device_id`; `is_active`; `refresh_token_hash` (unique); `family_id`; composite active-per-device unique constraint (above).

**Soft Delete:** Revocation is the soft-delete mechanism — `is_active=False` + `revoked_at`/`revoked_reason`. Rows are retained (never deleted in normal operation) so the rotation chain and audit remain intact.

**Example:**
```json
{
  "id": "b21e...","user": "6f1c...","device_id": "web-9f3a-uuid",
  "device_name": "Ramesh — Chrome/macOS","is_active": true,
  "last_used_at": "2026-07-22T09:20:00Z","expires_at": "2026-07-29T09:15:00Z"
}
```

**Security Notes:** The raw refresh token is returned to the client exactly once (body in dev, HttpOnly cookie in prod) and never stored — only its SHA-256 hash is persisted, so a DB leak does not expose reusable credentials. `refresh_token_hash`, `sid`, and IPs are never returned in the `me` payload.

---

## 4. AuthEvent

**Purpose:** Immutable, append-only authentication audit trail. One row per security-relevant event, carrying actor, subject, outcome, and source — never any secret.
**Table:** `authenticate_authevent`
**`event_type` choices:** `superadmin_bootstrap`, `login_success`, `login_failure`, `forced_password_change`, `password_change`, `logout`, `session_refreshed`, `session_revoked`, `account_created`, `account_updated`, `account_blocked`, `account_restored`, `admin_password_reset`, `mfa_enabled`, `mfa_disabled`, `mfa_verification_failure`, `mfa_reset`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| event_type | CharField(40) | Yes | No | No | Event kind (choices above) |
| actor | FK(User) | No | Yes | No | Who performed the action (`on_delete=SET_NULL`, `related_name="auth_events_performed"`); null for system/unknown |
| subject | FK(User) | No | Yes | No | Account acted upon (`on_delete=SET_NULL`, `related_name="auth_events_about"`); null when the username is unknown (failed login) |
| subject_username | CharField(150) | No | No | No | Attempted/target username as a string (always recorded; survives unknown-user failures) |
| success | Boolean | — | No | No | Whether the action succeeded |
| reason | CharField(100) | No | No | No | Short category (e.g. revocation reason, failure category) — never the password |
| ip_address | GenericIPAddress | No | Yes | No | Source IP |
| user_agent | TextField | No | No | No | Source user agent (blank allowed) |
| device_id | CharField(255) | No | No | No | Device identifier when applicable (blank allowed) |
| metadata | JSONField | — | No | No | Extra non-secret context (default `{}`) |
| created_at | DateTime | — | No | Yes | Event time (UTC) |

**Validation Rules:**
- Append-only: `AuthEvent.objects.delete()` and instance `delete()` raise `ImmutabilityError`; rows are never updated.
- `metadata`, `reason`, `subject_username` must never contain passwords, hashes, tokens, or MFA secrets (§17).

**Indexes:** `event_type`; `subject_username`; `created_at`.

**Soft Delete:** N/A — append-only; rows are never deleted or soft-deleted. `reset_dev_data` detects the blocked bulk-`delete()` and preserves the table.

**Example:**
```json
{
  "id": "c9a1...","event_type": "login_failure","actor": null,"subject": null,
  "subject_username": "unknown.user","success": false,"reason": "invalid_credentials",
  "ip_address": "203.0.113.7","device_id": "web-9f3a-uuid","created_at": "2026-07-22T09:19:12Z"
}
```

**Security Notes:** Login-failure events are recorded even for unknown usernames (via `subject_username`) for security monitoring, but the API response to the caller stays generic (`AUTH_CREDENTIALS_INVALID`) — the audit row is internal and never disclosed to the failing caller.

---

## 5. MFA (django-otp `TOTPDevice` — external model)

**Purpose:** TOTP multi-factor auth. `authenticate` adds NO model of its own for MFA — django-otp's `otp_totp.TOTPDevice` is the single source of truth for the secret.
**Table:** `otp_totp_totpdevice` (owned by django-otp).

- One device per user under the fixed name `default`. `confirmed=False` while enrolling, `True` once activated.
- **Derived state (never stored on `authenticate` models):**
  - `mfa_enabled` = a confirmed `TOTPDevice` exists for the user.
  - `mfa_enrollment_required` = user is `superadmin` AND `mfa_enabled` is false (MFA is mandatory for superadmins).
  Both are computed live in selectors/serializers to avoid drift.
- **Secret at rest:** stored by django-otp (DB-level protection); no app-level field encryption. Returned to the client exactly once at `mfa/enroll` (base32 secret + otpauth URL) and never again — never logged, never in `AuthEvent`.
- **No recovery/backup codes** (concept-locked): `otp_static` is not installed. MFA loss → reset hierarchy (admin reset in Phase 3; superadmin via the `reset_superadmin_mfa` command).

**Soft Delete:** N/A — a disabled/reset device is hard-deleted from django-otp's table; the action is captured by an `AuthEvent` (`mfa_disabled`/`mfa_reset`).

**Cross-App Dependencies:** `django-otp` (`otp_totp.TOTPDevice`) — see Cross-App Dependencies below.

## Request/Response Payload Contracts

### Account create/reset result

**Purpose:** the non-model response from account creation and administrative password reset.
**Shape:**
```json
{ "user": { "…User…": "" }, "temporary_password": "<shown-once>" }
```
- `POST /users/` returns `{ user, temporary_password? }`; `POST /users/<id>/reset-password/` returns `{ temporary_password? }`.
- `temporary_password` is present ONLY when the server generated it (no `password` supplied). It is returned exactly once, never stored in retrievable form, and the account is flagged `must_change_password`.
**Produced by:** `authenticate.services.create_managed_account` / `admin_reset_password`.
**Consumed by:** the creating admin/superadmin UI (display once, deliver out-of-band).

## Cross-App Dependencies

- **Depends on `django-axes`** (framework): the sole failed-login counter; the login service routes credential checks through `django.contrib.auth.authenticate()` so axes observes them. Axes' own tables (`AccessAttempt`/`AccessLog`/`AccessFailureLog`) are owned by axes, not modeled here.
- **Depends on `django-otp`** (framework): `otp_totp.TOTPDevice` stores the TOTP secret and verifies codes for the MFA endpoints and the login MFA step. No custom MFA model is defined; MFA state is derived from `TOTPDevice.confirmed`.
- **Depends on `audit`** (service call): `record_auth_event` also calls `audit.services.record_event` to federate each auth event into the central audit log. Best-effort — a failure is logged, never raised; `AuthEvent` remains this app's authoritative log. No model coupling (actor/subject are passed to audit as UUID values). Documented in `audit/docs/DATA_CONTRACT.md` and `INTEGRATION.md` §2.
- **Depends on `core`** (framework): `core.models.BaseModel` (UUID+timestamps) for `UserSecurityState`/`AuthSession`/`AuthEvent`; `core.nepal.text` for name normalization/romanization.
- **Referenced by:** no other app yet. Future apps reference `authenticate.User` by FK for ownership/attribution and call `authenticate.selectors`/`services` (to be documented in both apps' contracts and this app's `INTEGRATION.md` §2 when that coupling is added).

## Soft Delete

`User` and `UserSecurityState`: N/A (never deleted; blocking via `is_active`). `AuthSession`: revocation (`is_active=False` + `revoked_*`) is the retention-preserving soft delete. `AuthEvent`: N/A — append-only, immutable.
