# API Documentation — Audit

**App:** `audit`
**Version:** 1.1.0
**Base prefix:** `/api/v1/audit/`
**Auth:** Bearer access token AND `is_staff` (Admin/Superadmin). Interim access pattern (`CLAUDE.md` §9); Lead Managers have no access.
**Throttle:** Project defaults (`AnonRateThrottle`/`UserRateThrottle`).
**Access level:** Staff-only (Admin/Superadmin). Read-only — no write endpoints.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial API docs — read-only central audit log (2 endpoints) |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | Added `?search=`/`?date_from=`/`?date_to=`/`?order=` and `created_at_bs` to §1.1–§1.2; added the filter-values endpoint (§1.3); corrected the emitter inventory |

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

**AI debugging notes (app-wide):** Audit is read-only over HTTP. Events are appended only by other apps through `audit.services.record_event` (never over the API). Twelve apps emit today — see `DATA_CONTRACT.md` `Cross-App Dependencies` for the list. A missing event usually means that particular action was never wired to emit, not that the write was lost; `authenticate`'s emit is additionally best-effort (a failure there is logged, not raised), so its absence proves even less. Non-staff callers get `PERMISSION_DENIED` (403).

---

## 1. Audit events

### 1.1 List / filter events — `GET /api/v1/audit/events/`

**Policy key(s):** `audit.event.list` (risk: medium)
**Access:** Admin/Superadmin (`is_staff`).
**Request:** query params only, all optional, AND-combined:

| Param | Form | Meaning |
|-------|------|---------|
| `app` | string | Exact match on `app_label` |
| `action`, `actor_type`, `entity_type` | string | Exact match |
| `actor_id`, `entity_id` | UUID | Exact match |
| `success` | `true`/`1`/`false`/`0` | Outcome marker |
| `search` | string, min 2 chars | Case-insensitive substring of `summary` only |
| `date_from`, `date_to` | `YYYY-MM-DD` | Inclusive range; each names a **NPT** calendar day, not a UTC one |
| `fiscal_year` | `YYYY/YY` | Nepali fiscal year; combinable with `date_from`/`date_to` |
| `order` | `desc` (default) / `asc` | Sort direction on `created_at` |

**Response:** paginated `data` = list[AuditEvent] (newest first unless `order=asc`) — see `DATA_CONTRACT.md §1`. Each item carries `created_at` (UTC) and `created_at_bs` (the BS projection, §39.4). `meta` carries `count`/`page`/`page_size`/`next`/`previous`.
**Validation rules:** a bad UUID, non-boolean `success`, unparseable date, `date_from` later than `date_to`, `search` under 2 characters, or an unknown `order` returns `VALIDATION_ERROR` (400) with per-field messages in `error.details` — never a 500.
**Error codes:** `VALIDATION_ERROR` (400); `AUTHENTICATION_REQUIRED` (401); `PERMISSION_DENIED` (403, non-staff).
**Business rules:** No side effects. A record's timeline = this endpoint filtered by `entity_type` + `entity_id`, with `order=asc` for chronological reading — clients must not reverse a page instead, since page 1 of a descending list is the newest page. `fiscal_year` maps to a Gregorian range via `core.nepal.calendar.fiscal_year_gregorian_range`; `date_from`/`date_to` convert to NPT day boundaries in the selector.
**Query access pattern:** indexed on `(entity_type, entity_id)`, `actor_id`, `app_label`, `action`, `actor_type`, `created_at`; `?search=` is served by the `audit_summary_trgm_idx` GIN trigram index (`DATA_CONTRACT.md §1` `Indexes`). Ordered by `-created_at` (or `created_at`).

### 1.2 Read one event — `GET /api/v1/audit/events/<id>/`

**Policy key(s):** `audit.event.read` (risk: low)
**Access:** Admin/Superadmin (`is_staff`).
**Response:** the **AuditEvent** read shape, including `created_at_bs` — see `DATA_CONTRACT.md §1`.
**Error codes:**
- `AUDIT_EVENT_NOT_FOUND` (404) — no event with that id.
- `AUTHENTICATION_REQUIRED` (401); `PERMISSION_DENIED` (403).

### 1.3 Filter values — `GET /api/v1/audit/events/facets/`

**Policy key(s):** `audit.event.facets` (risk: low)
**Access:** Admin/Superadmin (`is_staff`).
**Request:** none.
**Response:** `data` = `{ apps: string[], actions: string[], entity_types: string[], actor_types: string[] }`, not paginated. `apps`/`actions`/`entity_types` are the distinct values currently in the log, sorted; `actor_types` is the full `ActorType` enum, including values not yet observed.
**Error codes:** `AUTHENTICATION_REQUIRED` (401); `PERMISSION_DENIED` (403).
**Business rules:** No side effects. Exists because `action`, `app_label` and `entity_type` are open strings owned by the emitting apps — there is no enum for the log screen's filter dropdowns to read, so they are populated from the data. Empty lists are a valid response for an empty log.
**Query access pattern:** three `DISTINCT` queries, one per column, each over an indexed column, no joins. Cost grows with the number of *distinct* values, not rows — but Postgres still scans to find them, so this is a per-screen-load call, not a per-keystroke one. If the log grows to where this is measurably slow, a materialized facet table is the fix (it needs its own approval, §28).
