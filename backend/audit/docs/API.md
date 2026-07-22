# API Documentation — Audit

**App:** `audit`
**Version:** 1.0.0
**Base prefix:** `/api/v1/audit/`
**Auth:** Bearer access token AND `is_staff` (Admin/Superadmin). Interim access pattern (`CLAUDE.md` §9); Lead Managers have no access.
**Throttle:** Project defaults (`AnonRateThrottle`/`UserRateThrottle`).
**Access level:** Staff-only (Admin/Superadmin). Read-only — no write endpoints.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial API docs — read-only central audit log (2 endpoints) |

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

**AI debugging notes (app-wide):** Audit is read-only over HTTP. Events are appended only by other apps through `audit.services.record_event` (never over the API). The write path is federated and best-effort for emitters, so a missing event usually means the emitting app was not wired to audit (V1: only `authenticate`), not a lost action. Non-staff callers get `PERMISSION_DENIED` (403).

---

## 1. Audit events

### 1.1 List / filter events — `GET /api/v1/audit/events/`

**Policy key(s):** `audit.event.list` (risk: medium)
**Access:** Admin/Superadmin (`is_staff`).
**Request:** query params only — `app`, `action`, `actor_type`, `actor_id`, `entity_type`, `entity_id`, `success`, `fiscal_year` (`YYYY/YY`). All optional; combine freely.
**Response:** paginated `data` = list[AuditEvent] (newest first) — see `DATA_CONTRACT.md §1`. `meta` carries `count`/`page`/`page_size`/`next`/`previous`.
**Error codes:** `AUTHENTICATION_REQUIRED` (401); `PERMISSION_DENIED` (403, non-staff).
**Business rules:** No side effects. A record's timeline = this endpoint filtered by `entity_type` + `entity_id`. `fiscal_year` maps to a Gregorian range via `core.nepal.calendar.fiscal_year_gregorian_range`.
**Query access pattern:** indexed on `(entity_type, entity_id)`, `actor_id`, `app_label`, `action`, `actor_type`, `created_at`; ordered by `-created_at`.

### 1.2 Read one event — `GET /api/v1/audit/events/<id>/`

**Policy key(s):** `audit.event.read` (risk: low)
**Access:** Admin/Superadmin (`is_staff`).
**Response:** the **AuditEvent** read shape — see `DATA_CONTRACT.md §1`.
**Error codes:**
- `AUDIT_EVENT_NOT_FOUND` (404) — no event with that id.
- `AUTHENTICATION_REQUIRED` (401); `PERMISSION_DENIED` (403).
