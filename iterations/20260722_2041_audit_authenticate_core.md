# Session Iteration Log — 2026-07-22 20:41

Branch: `add_audit_app_20260722_2025`

## Audit

## 1. Module

- **Name:** Audit
- **Base path:** `/api/v1/audit/`
- **Auth:** Bearer token + `is_staff` (Admin/Superadmin). Read-only over HTTP; events are written only by other apps via an internal service call.

## 2. Conventions

- **Response/Error:** standard envelope.
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401); `PERMISSION_DENIED` (403, non-staff).
- **Pagination:** list paginates (`?page=`/`?page_size=`, default 20 / max 100), newest-first.
- **Filters:** `?app=` (→ app_label), `?action=`, `?actor_type=`, `?actor_id=`, `?entity_type=`, `?entity_id=`, `?success=`, `?fiscal_year=YYYY/YY` — exact-match, AND-combined; malformed → `VALIDATION_ERROR` (400).
- **IDs:** UUID. **Times:** ISO 8601 UTC (system times, no BS).

## 3. Models

- **AuditEvent** — `{ id, actor_type[enum], actor_id?, actor_label, app_label, action, entity_type, entity_id?, reason, source, ip_address?, success, summary, changes:json, metadata:json, created_at }`. Read-only, append-only. `changes` = `{ field: { old, new } }`; `metadata` open bag (AI provenance when `actor_type=ai`). No secrets, no record copies (actor/entity are UUID references).

## 4. Enums

- `AuditEvent.actor_type`: `superadmin | admin | lead_manager | system | ai`.
- `action`/`app_label` are open, app-owned vocabularies (not a closed enum).

## 5. Dependency order

- Nothing to create — read-only, populated by other apps. `audit.event.read` needs `audit.event.list`.
- **Start here:** as an administrator, `GET /api/v1/audit/events/`.

## 6. Endpoints

### Audit events — `/api/v1/audit/`

**Use it when:** an administrator reviews system activity, reconstructs a record's timeline (filter `entity_type`+`entity_id`), or reviews an actor's actions (`actor_id`).

**Methods:**
- `GET /api/v1/audit/events/` (`audit.event.list`)
- `GET /api/v1/audit/events/<id>/` (`audit.event.read`)

**Send:** none (read-only; filtering via query params).

**Returns:** `list` → paginated list[AuditEvent] (newest first); `read` → one AuditEvent.

**Notes:**
- No write endpoint by design; events arrive via other apps' `record_event` calls (federated, best-effort).

**Errors:**
- `AUDIT_EVENT_NOT_FOUND` (404) — unknown id.
- `VALIDATION_ERROR` (400) — malformed list filter.

## 7. Flows

- **Review system activity:** `GET /events/` (filtered) → `GET /events/<id>/`.
- **Reconstruct a record's history:** `GET /events/?entity_type=&entity_id=` (newest-first; reverse for chronological).
- **Review an account's auth activity:** `GET /events/?app=authenticate&actor_id=` (complements authenticate's own `/users/<id>/events/`).

## 8. Gaps

- Best-effort emission — a successful action may occasionally have no central event; not proof of (non-)occurrence.
- Newest-first only; a full chronological timeline past 100 events needs all pages fetched then reversed.
- Lead Managers have no access in V1; no arbitrary date-range filter; `permission_key`s are descriptive, not request-path enforced.

## Authenticate

## 1. Module

- **Name:** Authenticate. **Base path:** `/api/v1/auth/`. **Auth:** unchanged.

## 2. Conventions

- No changes.

## 3. Models

- No endpoint-facing model or shape changes this session. Internal only: `record_auth_event` now also emits each event to the central audit log (federated, best-effort) — no change to `AuthEvent`, `/users/<id>/events/`, or any response shape.

## 4. Enums

- No changes.

## 5. Dependency order

- No changes (adds a runtime dependency on `audit` for the emit; documented in §2 Requires).

## 6. Endpoints

- No authenticate endpoint added, changed, or retired. The only change is a non-visible side effect: successful/failed auth events now also appear in `/api/v1/audit/events/` (`app=authenticate`).

## 7. Flows

- No endpoint-flow changes. (An admin can now also review a user's auth activity centrally via the audit app.)

## 8. Gaps

- Central audit emission is best-effort; `AuthEvent` remains authoritative for `/users/<id>/events/`.

## Core

## 1. Module

- **Name:** Core + Core Policy Engine. **Base path:** `/api/v1/policy/`. **Auth:** unchanged.

## 2–5.

- No convention/model/enum/dependency-order changes.

## 6. Endpoints

- No `core.policy_engine` endpoint changes. `INSTALLED_APPS`/`api_urls` gained the `audit` app; the project-level `core/docs/INTEGRATION.md` gained the `audit` inventory row and dependency-graph edges (`authenticate → audit`, `audit → core/authenticate`).

## 7. Flows

- No changes.

## 8. Gaps

- No new gaps in `core`.
