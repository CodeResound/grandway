# Integration — Audit

**Owner app:** `audit`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-22

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial contract — read-only central audit log (Phase 4) |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | Added `?search=`, `?date_from=`, `?date_to=`, `?order=`, the filter-values endpoint, `created_at_bs`, and the shared `AuditEventHistoryEntry` shape; corrected the `changes` key names and the emitter inventory |

---

## 1. Module

- **Name:** Audit — the central, immutable, cross-app activity/change history for Grandway. Read-only over HTTP; events are written only by other apps through an internal service call (the audit `record_event` service), never over the API.
- **Base path:** `/api/v1/audit/`
- **Auth:** Every endpoint requires a Bearer access token AND Admin/Superadmin authority (`is_staff`). No public endpoints. Lead Managers have no audit access in V1.

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `core` | framework | Response envelope, pagination, exception handler, `core.nepal.calendar` for the BS projection and fiscal-year ranges | Responses lose the `{ success, message, data, meta }` shape; `created_at_bs` and `?fiscal_year=` stop working |
| `authenticate` | framework | Supplies the request user; the read gate reads `request.user.is_authenticated` + `is_staff` | Every endpoint returns 401/403; no caller can be recognised as an administrator |

**Note for consumers:** `audit` has NO write API and does not import any other app's models. Actors and affected records are stored as type + UUID values passed in by the emitting app, so audit stays decoupled.

**Populated by (inbound, service call — not a dependency of this app):** `applicant_journeys`, `applicants`, `authenticate`, `checklists`, `clients`, `document_history`, `document_templates`, `documents`, `institutions`, `leads`, `notifications`, `offers`. Each calls the audit `record_event` service after an important action. Those apps depend on `audit`; `audit` does not depend on them.

## 3. Conventions

- **Response:** project envelope — `{ success: true, message, data, meta }`. See `core/docs/INTEGRATION.md` §3.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.

```json
{ "success": true, "message": "Audit events retrieved.", "data": [ { "…AuditEvent…": "" } ], "meta": { "count": 1, "page": 1, "page_size": 20, "next": null, "previous": null } }
```

```json
{ "success": false, "error": { "code": "AUDIT_EVENT_NOT_FOUND", "message": "Audit event not found.", "details": {} }, "meta": {} }
```

- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when no/invalid token; `PERMISSION_DENIED` (403) when authenticated but not an administrator (`is_staff`).
- **Pagination:** the list endpoint paginates — `?page=` / `?page_size=` (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous`. The filter-values endpoint does not paginate.
- **IDs:** UUID strings. **Times:** `created_at` is ISO 8601, UTC, `Z`-suffixed. Every event also carries `created_at_bs`, the same instant projected to the Bikram Sambat calendar in Nepal Standard Time (UTC+05:45) — see §4 for its shape. UTC remains the stored value; BS is always derived.
- **List/search/filter/order params** (all optional, **AND-combined**):
  - `?app=` (matches `app_label`), `?action=`, `?actor_type=`, `?entity_type=` — exact match.
  - `?actor_id=`, `?entity_id=` — exact match, must be valid UUIDs.
  - `?success=` — `true`/`1` or `false`/`0`.
  - `?search=` — case-insensitive substring match against `summary` only (not `reason`, `action`, or actor). Minimum 2 characters.
  - `?date_from=` / `?date_to=` — `YYYY-MM-DD`, **both bounds inclusive**. Each names a calendar day in Nepal Standard Time, not a UTC day.
  - `?fiscal_year=<YYYY/YY>` — e.g. `2082/83`, a Nepali fiscal-year range. Combinable with `date_from`/`date_to` (both apply).
  - `?order=` — `desc` (default, newest first) or `asc` (oldest first).
- A malformed filter value (bad UUID, non-boolean `success`, bad `fiscal_year`, unparseable date, `date_from` later than `date_to`, `search` under 2 characters, unknown `order`) returns `VALIDATION_ERROR` (400) with per-field messages in `error.details` — it does not 500.

## 4. Models

**AuditEvent** — `{ id:uuid, actor_type:string[enum], actor_id:uuid|null, actor_label:string, app_label:string, action:string, entity_type:string, entity_id:uuid|null, reason:string, source:string, ip_address:string|null, success:bool, summary:string, changes:json, metadata:json, created_at:string, created_at_bs:json }`
- Read-only. To read a record's timeline, filter by `entity_type` + `entity_id` (add `?order=asc` for chronological).
- **Nullable / empty:** `actor_id` is null and `actor_label` may be empty for `system`/`ai`/unknown actors; `entity_id` is null (and `entity_type` empty) when the action is not scoped to a single record; `ip_address` is null when not applicable; `reason`/`source`/`summary` may be empty strings. `summary` is a best-effort human label and is often empty — do not rely on it as the sole row text, and note that `?search=` therefore cannot find events whose `summary` is blank.
- **`changes`** is a compact before/after map `{ "<field>": { "from": <any-json>, "to": <any-json> } }` — `from`/`to` are arbitrary JSON (string, number, bool, null, object); default `{}`. Not every field of the changed record appears — only the ones the emitting app judged meaningful.
- **`metadata`** is an open, non-secret bag (default `{}`); for `actor_type=ai` it carries AI provenance (e.g. `model`, `prompt_version` per §38) — its keys are not a fixed schema.
- **`created_at_bs`** is `{ year:int, month:int, day:int, month_name_en:string, month_name_np:string, display_en:string, display_np:string }`, derived from `created_at`. Never null on a stored event.
- **`entity_type`** and **`source`** look structured (`app.model`, `app.module.function`) but that shape is a convention, not a guaranteed contract — do not parse them. In practice most apps emit a bare `entity_type` (`lead`, `applicant`, `offer`) while `authenticate` emits a dotted one (`authenticate.user`); treat the value as opaque and read the live set from the filter-values endpoint.

**AuditEventHistoryEntry** — `{ id:uuid, action:string, actor_type:string[enum], actor_id:uuid|null, actor_label:string, summary:string, reason:string, changes:json, metadata:json, created_at:string, created_at_bs:json }`
- The narrower projection of the same row returned by **other apps'** `/history/` endpoints (`leads`, `applicants`, `applicant_journeys`, `clients`, `offers`, `documents`). Defined here because the shape is audit's to own — those apps render it, they do not redefine it.
- Drops `app_label`, `entity_type`, `entity_id` (constant within one record's history), `success`, `source`, and `ip_address`. Field semantics are otherwise identical to **AuditEvent** above.
- Not returned by any endpoint under `/api/v1/audit/` — see the owning app's `INTEGRATION.md` for how to reach it.

**AuditFacets** — `{ apps:string[], actions:string[], entity_types:string[], actor_types:string[] }`
- The distinct values present in the log, for populating filter controls. `apps`, `actions` and `entity_types` are read from the data and grow as new events are recorded; `actor_types` is the full closed enum from §5, including values not yet observed.
- Never contains secrets, hashes, tokens, or full document/file content — neither does **AuditEvent**.

### Worked examples

`GET /events/<id>/` → **AuditEvent** (as `data`):

```json
{
  "id": "e1a2b3c4-d5e6-4f70-8a1b-2c3d4e5f6071",
  "actor_type": "admin",
  "actor_id": "6f1c2e2a-9b7e-4d3a-8c2f-1a2b3c4d5e6f",
  "actor_label": "ramesh.admin",
  "app_label": "leads",
  "action": "lead_stage_changed",
  "entity_type": "lead",
  "entity_id": "9b7e4d3a-8c2f-4a1b-2c3d-4e5f60718293",
  "reason": "",
  "source": "",
  "ip_address": "203.0.113.7",
  "success": true,
  "summary": "Moved the lead from contacted to qualified.",
  "changes": { "stage": { "from": "contacted", "to": "qualified" } },
  "metadata": {},
  "created_at": "2026-07-22T10:15:00Z",
  "created_at_bs": {
    "year": 2082, "month": 4, "day": 6,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2082 Shrawan 6", "display_np": "२०८२ श्रावण ६"
  }
}
```

`GET /events/facets/` → **AuditFacets** (as `data`):

```json
{
  "apps": ["applicants", "authenticate", "leads", "offers"],
  "actions": ["account_blocked", "lead_created", "lead_stage_changed", "login_success", "offer_issued"],
  "entity_types": ["applicant", "authenticate.user", "lead", "offer"],
  "actor_types": ["superadmin", "admin", "lead_manager", "system", "ai"]
}
```

## 5. Enums

- `AuditEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `AuditEvent.action`, `AuditEvent.app_label` and `AuditEvent.entity_type` are open strings (app-defined), not closed enums — the emitting app owns its own vocabulary (e.g. `authenticate` reuses its `AuthEvent` event types as `action` values). `GET /api/v1/audit/events/facets/` returns the values actually present, and is the only authoritative source for them; do not hard-code a list.

## 6. Dependency order

- Nothing to create — audit is read-only and populated by other apps' actions. `audit.event.read` and `audit.event.facets` both need `audit.event.list`.
- **Start here:** as an administrator, `GET /api/v1/audit/events/` (optionally filtered).

## 7. Endpoints

### Audit events — `/api/v1/audit/`

**Use it when:** an administrator reviews system-wide activity, investigates what happened to a record (filter by `entity_type`+`entity_id`, add `?order=asc`), reviews an actor's actions (filter by `actor_id`), or searches the log by what an event says (`?search=`).

**Methods:**
- `GET /api/v1/audit/events/` (`audit.event.list`)
- `GET /api/v1/audit/events/<id>/` (`audit.event.read`)

**Send:** none (read-only; filtering is via query params in §3).

**Returns:** `list` → paginated list[AuditEvent] (newest first unless `?order=asc`); `read` → one AuditEvent.

**Requires state:** a valid access token for an Admin/Superadmin. There are no preconditions on the data — the log may be empty.

**Side effects:** none — these endpoints never write, in this app or any other.

**Notes:**
- The log is append-only and populated by other apps; there is no create/update/delete endpoint by design.
- A record's timeline is the list endpoint filtered by `entity_type` + `entity_id`, with `?order=asc` for chronological reading. Do not reverse a page client-side — page 1 of a descending list is the *newest* page, so reversing it gives the wrong end of the timeline.
- `?search=` matches `summary` only, and matching is substring, not word- or prefix-based.

**Errors:**
- `AUDIT_EVENT_NOT_FOUND` (404) — no event with that id (detail only).
- `VALIDATION_ERROR` (400) — a malformed list filter; per-field messages in `error.details`. See §3 for every case.

### Audit filter values — `/api/v1/audit/events/facets/`

**Use it when:** rendering the audit-log screen's filter controls, before the operator has filtered anything. `action`, `app_label` and `entity_type` have no enum a client could read them from, so their dropdowns are populated from here.

**Methods:**
- `GET /api/v1/audit/events/facets/` (`audit.event.facets`)

**Send:** none.

**Returns:** one **AuditFacets** object (not paginated, not a list).

**Requires state:** a valid access token for an Admin/Superadmin. Returns empty lists (and the full `actor_types` enum) when the log is empty.

**Side effects:** none.

**Notes:**
- Values reflect the log as it stands; a newly-deployed app's actions appear only after its first event.
- Cheap to call but not free — it scans the log's distinct values. Fetch once per screen load, not per keystroke.

**Errors:** none beyond the global auth failures in §3.

## 8. Flows

**Review system activity**
1. `GET /api/v1/audit/events/facets/` → populate the filter dropdowns.
2. `GET /api/v1/audit/events/` (optionally `?app=authenticate&action=login_failure&date_from=2026-07-01&date_to=2026-07-24`) → a paginated, newest-first list.
3. `GET /api/v1/audit/events/<id>/` for full detail including the `changes` before/after.
   - Failure `AUTHENTICATION_REQUIRED`/`PERMISSION_DENIED` → not an administrator; hide the audit UI.

**Reconstruct a record's history**
1. `GET /api/v1/audit/events/?entity_type=lead&entity_id=<uuid>&order=asc` → every event affecting that record, oldest first, paginated in chronological order.
2. `GET /api/v1/audit/events/<id>/` on any entry for the full before/after.
   - The owning app's own `/history/` endpoint returns the same rows in the narrower **AuditEventHistoryEntry** shape and is the better choice inside that record's screen.

**Search the log**
1. `GET /api/v1/audit/events/?search=<term>&date_from=<day>` → events whose `summary` contains the term within the window.
   - Failure `VALIDATION_ERROR` on `search` → the term was under 2 characters.
   - Empty result is not proof of absence: events with a blank `summary` cannot match (see §9).

## 9. Gaps

- **No write API.** Events are appended only by other apps via the audit `record_event` service; a consumer cannot POST an event. This is by design.
- **Emission is best-effort (federated).** An emitting app's central emit is wrapped so a failure is logged, not raised — so a successful action may occasionally have NO central audit event, even though it happened (the app's own log still recorded it). Do NOT use the central audit as proof that an action did or did not occur; it is an aggregate, not a guarantee.
- **`?search=` covers `summary` only.** Events emitted with a blank `summary` are unreachable by search, and no endpoint reports how many those are. Searching `reason`, `action`, or actor is not supported.
- **`permission_key`s are descriptive, not enforced.** The real gate is `is_authenticated` + `is_staff` (see `core/docs/INTEGRATION.md` §4). The `audit.event.*` keys describe the surface for the policy registry; they do not gate requests yet.
- **Coverage is per-app and not provably complete.** Twelve apps emit (§2), but nothing verifies that every important action in them does — absence of an event may mean the action was not wired, not that nothing happened.
- **`source` is effectively unpopulated.** Only `authenticate` sets it; every other emitter leaves it an empty string. Do not build a UI column on it.
- **Lead Managers have no access** in V1 (Admin/Superadmin only); own-scope access is deferred.
- **Date filters are Gregorian on input.** `?date_from=`/`?date_to=` take `YYYY-MM-DD` Gregorian dates (interpreted as NPT days) even though responses render BS. A BS-native date filter is not exposed; use `?fiscal_year=` for BS-aligned ranges.
- **One entity per event.** An action touching two records (e.g. converting a lead into an applicant) is recorded against one `entity_id`; any second reference is at the emitting app's discretion inside `metadata`, with no guaranteed key.
- **No retention policy is stated.** Events are never deleted, so a record's timeline grows without bound; plan for pagination rather than fetching a full history.
