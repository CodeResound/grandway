# Integration — Audit

**Owner app:** `audit`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-22

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial contract — read-only central audit log (Phase 4) |

---

## 1. Module

- **Name:** Audit — the central, immutable, cross-app activity/change history for Grandway. Read-only over HTTP; events are written only by other apps through an internal service call (the audit `record_event` service), never over the API.
- **Base path:** `/api/v1/audit/`
- **Auth:** Every endpoint requires a Bearer access token AND Admin/Superadmin authority (`is_staff`). No public endpoints. Lead Managers have no audit access in V1.

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `core` | framework | Response envelope, pagination, exception handler | Responses lose the `{ success, message, data, meta }` shape |
| `authenticate` | framework | Supplies the request user; the read gate reads `request.user.is_authenticated` + `is_staff` | Every endpoint returns 401/403; no caller can be recognised as an administrator |

**Note for consumers:** `audit` has NO write API and does not import any other app's models. Actors and affected records are stored as type + UUID values passed in by the emitting app, so audit stays decoupled. `authenticate` depends on `audit` (it emits events); the reverse is only the framework-level user dependency above.

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
- **Pagination:** the list endpoint paginates — `?page=` / `?page_size=` (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous`.
- **IDs:** UUID strings. **Times:** ISO 8601, UTC, `Z`-suffixed (audit timestamps are system times — no BS representation).
- **List/search/filter/order params:** the list endpoint accepts `?app=` (matches `app_label`), `?action=`, `?actor_type=`, `?actor_id=`, `?entity_type=`, `?entity_id=`, `?success=` (`true`/`false`), and `?fiscal_year=<YYYY/YY>` (e.g. `2082/83`, a Nepali fiscal-year range). All are **exact-match** and **AND-combined**; no free-text search or ordering params; results are always newest-first. A malformed filter value (bad UUID, non-boolean `success`, bad `fiscal_year`) returns `VALIDATION_ERROR` (400) with per-field messages in `error.details` — it does not 500.

## 4. Models

**AuditEvent** — `{ id:uuid, actor_type:string[enum], actor_id:uuid|null, actor_label:string, app_label:string, action:string, entity_type:string, entity_id:uuid|null, reason:string, source:string, ip_address:string|null, success:bool, summary:string, changes:json, metadata:json, created_at:string }`
- Read-only. To read a record's timeline, filter by `entity_type` + `entity_id`.
- **Nullable / empty:** `actor_id` is null and `actor_label` may be empty for `system`/`ai`/unknown actors; `entity_id` is null (and `entity_type` empty) when the action is not scoped to a single record; `ip_address` is null when not applicable; `reason`/`source`/`summary` may be empty strings. `summary` is a best-effort human label and is often empty — do not rely on it as the sole row text.
- **`changes`** is a compact before/after map `{ "<field>": { "old": <any-json>, "new": <any-json> } }` — `old`/`new` are arbitrary JSON (string, number, bool, null, object); default `{}`.
- **`metadata`** is an open, non-secret bag (default `{}`); for `actor_type=ai` it carries AI provenance (e.g. `model`, `prompt_version` per §38) — its keys are not a fixed schema.
- **`entity_type`** and **`source`** look structured (`app.model`, `app.module.function`) but that shape is a convention, not a guaranteed contract — do not parse them.
- Never contains secrets, hashes, tokens, or full document/file content.

### Worked examples

`GET /events/<id>/` → **AuditEvent** (as `data`):

```json
{
  "id": "e1a2b3c4-d5e6-4f70-8a1b-2c3d4e5f6071",
  "actor_type": "admin",
  "actor_id": "6f1c2e2a-9b7e-4d3a-8c2f-1a2b3c4d5e6f",
  "actor_label": "ramesh.admin",
  "app_label": "authenticate",
  "action": "account_blocked",
  "entity_type": "authenticate.user",
  "entity_id": "9b7e4d3a-8c2f-4a1b-2c3d-4e5f60718293",
  "reason": "policy violation",
  "source": "authenticate.services.block_account",
  "ip_address": "203.0.113.7",
  "success": true,
  "summary": "",
  "changes": {},
  "metadata": {},
  "created_at": "2026-07-22T10:15:00Z"
}
```

## 5. Enums

- `AuditEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `AuditEvent.action` and `AuditEvent.app_label` are open strings (app-defined), not a closed enum — the emitting app owns its own action vocabulary (e.g. `authenticate` reuses its `AuthEvent` event types as `action` values).

## 6. Dependency order

- Nothing to create — audit is read-only and populated by other apps' actions. `audit.event.read` needs `audit.event.list`.
- **Start here:** as an administrator, `GET /api/v1/audit/events/` (optionally filtered).

## 7. Endpoints

### Audit events — `/api/v1/audit/`

**Use it when:** an administrator reviews system-wide activity, investigates what happened to a record (filter by `entity_type`+`entity_id`), or reviews an actor's actions (filter by `actor_id`).

**Methods:**
- `GET /api/v1/audit/events/` (`audit.event.list`)
- `GET /api/v1/audit/events/<id>/` (`audit.event.read`)

**Send:** none (read-only; filtering is via query params in §3).

**Returns:** `list` → paginated list[AuditEvent] (newest first); `read` → one AuditEvent.

**Requires state:** a valid access token for an Admin/Superadmin. There are no preconditions on the data — the log may be empty.

**Side effects:** none — these endpoints never write.

**Notes:**
- The log is append-only and populated by other apps; there is no create/update/delete endpoint by design.
- A record's timeline is the list endpoint filtered by `entity_type` + `entity_id`.

**Errors:**
- `AUDIT_EVENT_NOT_FOUND` (404) — no event with that id (detail only).
- `VALIDATION_ERROR` (400) — a malformed list filter (bad UUID, non-boolean `success`, bad `fiscal_year`); per-field messages in `error.details`.

## 8. Flows

**Review system activity**
1. `GET /api/v1/audit/events/` (optionally `?app=authenticate&action=login_failure&fiscal_year=2082/83`) → a paginated, newest-first list.
2. `GET /api/v1/audit/events/<id>/` for full detail including `changes` before/after.
   - Failure `AUTHENTICATION_REQUIRED`/`PERMISSION_DENIED` → not an administrator; hide the audit UI.

**Reconstruct a record's history**
1. `GET /api/v1/audit/events/?entity_type=authenticate.user&entity_id=<uuid>` → every event affecting that record, newest first.
2. Reverse-read for the oldest-to-newest timeline (there is no ascending-order param in V1).

## 9. Gaps

- **No write API.** Events are appended only by other apps via the audit `record_event` service; a consumer cannot POST an event. This is by design.
- **Emission is best-effort (federated).** An emitting app's central emit is wrapped so a failure is logged, not raised — so a successful action may occasionally have NO central audit event, even though it happened (the app's own log still recorded it). Do NOT use the central audit as proof that an action did or did not occur; it is an aggregate, not a guarantee.
- **Ordering is fixed newest-first** — no ascending option or arbitrary sort. Reversing one page gives a chronological view only within that page; for a full chronological timeline of a record with more than `page_size` (max 100) events you must fetch all pages first, then reverse.
- **`permission_key`s are descriptive, not enforced.** The real gate is `is_authenticated` + `is_staff` (see `core/docs/INTEGRATION.md` §4). The `audit.event.*` keys describe the surface for the policy registry; they do not gate requests yet.
- **Federated, so not exhaustive yet.** Only apps that have been wired to emit appear here — in V1 that is `authenticate`. Absence of an event for another app means that app has not yet been integrated, not that nothing happened.
- **Lead Managers have no access** in V1 (Admin/Superadmin only); own-scope access is deferred.
- **No date range beyond `fiscal_year`** — arbitrary `from`/`to` filtering is not exposed yet.
- **`action`/`app_label` value sets are not enumerated here** — they are open, app-owned vocabularies (e.g. see `authenticate/docs/INTEGRATION.md` for its event types, reused as `action`).
