# Session Iteration Log — 2026-07-22 20:17

Branch: `add_account_session_mgmt_20260722_1955`

## Authenticate

## 1. Module

- **Name:** Authenticate
- **Base path:** `/api/v1/auth/`
- **Auth:** `login`/`refresh` public; everything else needs a Bearer token. `users/*` additionally requires the caller's authority tier be exactly one above the target (superadmin→admin, admin→lead manager), enforced inline.

## 2. Conventions

- **Pagination (new):** `GET /users/` and `GET /users/<id>/events/` paginate (`?page=`/`?page_size=`, default 20 / max 100); other lists are bare active-only arrays.
- **HTTP status:** account creation is `201`; all other successes `200`.
- **403 usage:** `AUTH_INVALID_AUTHORITY`, `AUTH_MFA_MANDATORY`. An out-of-authority target returns `AUTH_USER_NOT_FOUND` (404, enumeration-safe).
- **Scope by tier, not ownership:** an admin manages every lead manager; a superadmin every admin. Self is not manageable via `users/*` (404).

## 3. Models

- **Session** — `{ id, device_id, device_name, ip_address?, user_agent, is_active, revoked_reason[enum], revoked_at?, last_used_at, idle_expires_at, expires_at, created_at }`. Returned by own + admin session lists.
- **AuthEvent** — `{ id, event_type[enum], actor_username?, subject_username, success, reason, ip_address?, device_id, created_at }`. Returned by `GET /users/<id>/events/`.
- **Account create/reset result** — `{ user?, temporary_password? }`; `temporary_password` present once, only when server-generated.
- No new DB tables; block metadata already on `UserSecurityState`.

## 4. Enums

- `Session.revoked_reason`: `logout | password_change | replaced_same_device | rotated | rotated_reuse | device_limit | blocked | admin_revoked | mfa_change` (empty on active).
- `AuthEvent.event_type`: adds `account_created | account_updated | account_blocked | account_restored | admin_password_reset` to the Phase 1/2 set.

## 5. Dependency order

- `user.list` needs a session; `user.read`/`create` need `user.list`; `update`/`block`/`restore`/`reset-*`/`sessions`/`events` need `user.read`; `sessions/revoke` needs `user.list_sessions`.
- Own-session `revoke` needs `session.list`.
- **Start here:** `POST /login/`, then `GET /users/` (managers) or `GET /sessions/` (self).

## 6. Endpoints

### Accounts — `/api/v1/auth/users/`

**Use it when:** an admin/superadmin manages the tier below.

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
- `username`, `authority_type` (required — the managed tier)
- `display_name`, `full_name_np`, `full_name_en`, `email`, `phone`, `password` (optional; omit `password` to auto-generate)

**Send (update):**
- any of `display_name`, `full_name_np`, `full_name_en`, `email`, `phone` (partial)

**Send (block):**
- `reason` (optional)

**Send (reset-password):**
- `password` (optional; omit to auto-generate)

**Send (sessions/revoke):**
- `session_id` (optional; omit to revoke all)

**Returns:** `list` → paginated list[User]; `create` → `201` `{ user, temporary_password? }`; `read`/`update` → User; `block`/`restore`/`reset-mfa` → empty; `reset-password` → `{ temporary_password? }`; `sessions` → list[Session]; `sessions/revoke` → `{ revoked }`; `events` → paginated list[AuthEvent].

**Notes:**
- Scope is by tier (type), not ownership; self returns 404.
- `block`/`reset-password`/`reset-mfa`/`sessions-revoke` revoke the target's sessions.

**Errors:**
- `AUTH_USER_NOT_FOUND` (404) — target not in the caller's managed tier.
- `AUTH_INVALID_AUTHORITY` (403) — `create` with a non-creatable `authority_type`.
- `AUTH_USERNAME_TAKEN` (409) — `create` with an existing username.
- `AUTH_PASSWORD_WEAK` (400) — weak `reset-password` (`details.password`).
- `AUTH_SESSION_NOT_FOUND` (404) — `sessions/revoke` with a foreign `session_id`.
- `VALIDATION_ERROR` (400) — malformed `create`/`update` input.

### Own sessions — `/api/v1/auth/sessions/`

**Use it when:** a user reviews their own devices and signs some/all out.

**Methods:**
- `GET /api/v1/auth/sessions/` (`authenticate.session.list`)
- `POST /api/v1/auth/sessions/revoke/` (`authenticate.session.revoke`)

**Send (revoke):**
- `session_id` (optional), `others_only` (optional bool); omit both to revoke all.

**Returns:** `list` → list[Session]; `revoke` → `{ revoked }`.

**Errors:**
- `AUTH_SESSION_NOT_FOUND` (404) — `session_id` is not yours.

## 7. Flows

- **Provision a subordinate:** `GET /users/` → `POST /users/` (no password → temp password once) → deliver out-of-band → user does forced-password-change.
- **Recover a subordinate:** `reset-password` (lost password), `reset-mfa` (lost authenticator), or `block`/`restore` (compromise); review via `events`/`sessions`, force sign-out via `sessions/revoke`.
- **Manage own devices:** `GET /sessions/` → `POST /sessions/revoke/` (`session_id` / `others_only` / all).

## 8. Gaps

- No self-profile-edit endpoint (`me` is read-only; `users/*` is tier-below only).
- Single-tier recovery only (a superadmin cannot recover a lead manager directly; no API escalation).
- Standalone central `audit` app still deferred (per-account review only, over this app's `AuthEvent`).

## Core

## 1. Module

- **Name:** Core (infrastructure) + Core Policy Engine. **Base path:** `/api/v1/policy/`. **Auth:** unchanged.

## 2. Conventions

- No changes.

## 3. Models

- No endpoint-facing model changes. (Infra: none this session beyond the `authenticate` app.)

## 4. Enums

- No changes.

## 5. Dependency order

- No changes.

## 6. Endpoints

- No `core.policy_engine` endpoint changes. The project-level `core/docs/INTEGRATION.md` app-inventory row for `authenticate` was updated to reflect account/session management; no `core` endpoint changed.

## 7. Flows

- No changes.

## 8. Gaps

- No new gaps introduced in `core`.
