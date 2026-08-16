# Integration — Reminders

**Owner app:** `reminders`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-08-17

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-17 | AI (Claude) | Initial integration contract — seven endpoints |

---

## 1. Module

- **Name:** Reminders — one-off, date-only follow-up notes set by staff against an applicant or client, surfaced to Admins as a notification when the date arrives.
- **Base path:** `/api/v1/reminders/`
- **Auth:** JWT (project-standard). `admin` and `lead_manager` may do everything on every endpoint; `superadmin` may do nothing, reads included.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `core` | framework | Response envelope, pagination, Bikram Sambat rendering, Nepal-time "today" | Responses lose the `{ success, message, data, meta }` envelope; the due-date floor and BS siblings disappear |
| `authenticate` | framework + FK | JWT sessions and the `authority_type` the access rule reads; FKs for `created_by` and `closed_by` (surfaced as the `*_username` fields) | Every request is 401/403 |
| `applicants` | FK (`PROTECT`) | A reminder may be owned by an applicant | Creating with `applicant` returns 400 `REMINDERS_OWNER_NOT_FOUND` |
| `clients` | FK (`PROTECT`) | A reminder may be owned by a client | Creating with `client` returns 400 `REMINDERS_OWNER_NOT_FOUND` |
| `audit` | service call | Every mutation appends one history event; `/history/` reads them back | Mutations fail; history is empty |
| `notifications` | service call (inbound) | The nightly sweep reads this app's due reminders and raises `custom_reminder` alerts to Admins | Reminders still store and list, but no alert ever surfaces — the feature's trigger half is gone |

Both owner FKs are `PROTECT`: a record with reminders against it cannot be removed while they exist. Nothing in this project deletes applicants or clients anyway, but the constraint is real and this module is the one creating it.

## 3. Conventions

- **Permission keys are registry metadata, not the enforced gate.** The `permission_key` on each §7 endpoint is registered in the policy engine for future wiring; no view consults one today (project-level `INTEGRATION.md` §4/§10). The enforced rule is the flat authority check below — do not generate a client capability map from the keys.
- **Access — one rule, everywhere.** `admin` and `lead_manager` may do everything on every endpoint; `superadmin` may do nothing, reads included. There is no read/write split. Only Admins *receive* the due alert, but that is `notifications` routing — it does not restrict anything here.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint in this module**. A reminder ends as `completed` or `dismissed` and stays retrievable forever. Build complete/dismiss controls, not a delete button.
- **No reopen.** `completed` and `dismissed` are terminal. "Remind me again later" is a **new** reminder (`POST /`), not an edit to the finished one.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is abridged to three fields to show the envelope; a real create returns the full `Reminder` shape defined in §4.

```json
{
  "success": true,
  "message": "Reminder set.",
  "data": { "id": "9a0b1c2d-3e4f-4a5b-8c6d-7e8f90123456", "due_date": "2026-08-25", "status": "active" },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract. Branch on the HTTP status and, for errors, on `error.code`.

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object that is always present — `{}` when there are no field-level errors. Field-level validation failures use the project-wide `VALIDATION_ERROR` code with the offending fields inside `details`:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { "due_date": ["The due date may not be in the past."] }
  },
  "meta": {}
}
```

- **HTTP status codes:** `POST /` returns **201**; `POST .../complete/` and `.../dismiss/` act on an existing record and return **200**. `GET` and `PATCH` return **200**. Acting on a closed reminder is **409**. A missing reminder named in the **URL path** is **404**; an unknown owner id in the request **body** is **400** `REMINDERS_OWNER_NOT_FOUND`. Authority failures are **403**.
- **Auth failures:** 401 with no token, an expired token, or a revoked session — produced by the authentication framework. 403 `REMINDERS_ACTOR_FORBIDDEN` when the token is valid but the authority may not act — in this module exactly one case, a `superadmin`. This module's 403 code replaces the project-wide `PERMISSION_DENIED`; it is omitted from the per-endpoint `Errors` lists in §7 since it applies identically to all seven.
- **The owner and lifecycle fields are immutable, and a `PATCH` carrying them is REJECTED, not ignored.** `applicant`, `client`, `status`, `closed_at`, `closed_by` return 400 `REMINDERS_FIELD_IMMUTABLE` with every offending field listed in `details`. Send only the fields the user actually changed (`due_date`, `note`).
- **A `PATCH` that changes nothing writes no audit event.** The response is still 200 with the unchanged record.
- **Query parameter encoding.** Invalid query parameters are **rejected with 400, not ignored**. Dates are `YYYY-MM-DD` (Gregorian, never Bikram Sambat). `page_size` above the 100 maximum is clamped, not rejected.
- **Request encoding:** `application/json`.
- **List ordering:** newest-created first, always. There is no `?ordering=` parameter — a due-date-ordered worklist must sort its page client-side or narrow with the due-window filters.
- **One alert per due date, never a nightly re-nag.** The sweep raises at most one `custom_reminder` notification per Admin per reminder per due date (the date is part of the idempotency key). A reminder that stays open past its date does not generate further alerts — the existing one simply stays active in the feed until the reminder is closed. Only a reschedule (new date) can produce a new alert.
- **Pagination:** page-number based. Params `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `next`/`previous` are absolute URLs or `null`. Applied to both list endpoints here (the reminder list and the history list).
- **IDs:** UUID strings throughout.
- **Times (deviation from the project-wide "ISO 8601 UTC" convention, per the global contract):** `updated_at` is ISO 8601 UTC with no `_bs` sibling. User-facing dates carry a Bikram Sambat sibling (`due_date_bs`, `closed_at_bs`, `created_at_bs`) — each an object or `null`, never a string, shaped `{ year, month, day, month_name, display }`. `created_at` carries one because when a reminder was set is itself operational memory. **Write the Gregorian field; read either** — `POST`/`PATCH` accept `YYYY-MM-DD` only, and `due_date` must be Nepal's today or later.
- **"Due" is a Nepal-calendar day.** A reminder is due at the start of its `due_date` in Asia/Kathmandu (+05:45), and the surfaced alert appears after the next nightly sweep run — not at the stroke of midnight. Near midnight NPT a client computing "due today" locally from UTC may briefly disagree with the server.
- **Empty text fields are `""`, never `null`.** Nullable fields are `applicant`, `client` (exactly one is always set, the other `null`), `closed_at`, `closed_at_bs`, and `closed_by_username`.

## 4. Models

**Reminder** — `{ id, owner_type:[enum], applicant?:uuid, client?:uuid, due_date, due_date_bs:json, note, status:[enum], is_active, closed_at?, closed_at_bs?:json, closed_by_username?, created_by_username, created_at, created_at_bs:json, updated_at }`

- Exactly one of `applicant`/`client` is a UUID and the other is `null`; `owner_type` names which. They are bare UUID strings, not nested objects — fetch the record from `/api/v1/applicants/` or `/api/v1/clients/` to display it.
- `is_active` is derived: `status == "active"`.
- The same shape is returned by every endpoint (list rows included); there is no separate list/detail split.

**HistoryEvent** — `{ id, action, actor_type:[enum], actor_id:uuid|null, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`

- Owned by the `audit` module (`audit/docs/INTEGRATION.md` §4, there called **AuditEventHistoryEntry**). This app renders it; it does not define it.
- `changes` is a map of field name to `{ "from": "...", "to": "..." }`, both stringified — a reschedule carries `due_date`; `{}` on creation and closure events' unchanged fields.

### Worked examples

**Reminder (active, applicant-owned)**

```json
{
  "id": "9a0b1c2d-3e4f-4a5b-8c6d-7e8f90123456",
  "owner_type": "applicant",
  "applicant": "1f2e3d4c-5b6a-4798-8695-a4b3c2d1e0f9",
  "client": null,
  "due_date": "2026-08-25",
  "due_date_bs": { "year": 2083, "month": 5, "day": 9, "month_name": "Bhadra", "display": "2083 Bhadra 9" },
  "note": "Chase IELTS certificate before the SOP review call.",
  "status": "active",
  "is_active": true,
  "closed_at": null,
  "closed_at_bs": null,
  "closed_by_username": null,
  "created_by_username": "adminuser",
  "created_at": "2026-08-17T05:12:30Z",
  "created_at_bs": { "year": 2083, "month": 5, "day": 1, "month_name": "Bhadra", "display": "2083 Bhadra 1" },
  "updated_at": "2026-08-17T05:12:30Z"
}
```

## 5. Enums

- `Reminder.owner_type`: `applicant` | `client`
- `Reminder.status`: `active` | `completed` | `dismissed`
- `HistoryEvent.action`: `reminder_created` | `reminder_rescheduled` | `reminder_updated` | `reminder_completed` | `reminder_dismissed`
- `HistoryEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai` (owned by `audit`)

## 6. Dependency order

- `Reminder` needs an `Applicant` (other app) **or** a `Client` (other app) — exactly one, existing before the create call.

**Start here:** `POST /api/v1/reminders/` against an applicant or client you already have.

## 7. Endpoints

### Reminder — `/api/v1/reminders/`

**Use it when:** a record's reminders panel (filtered by `?applicant=` / `?client=`), a due-window worklist, or setting a new follow-up.
**Methods:**
- `GET /api/v1/reminders/` — list, filterable (permission: `reminders.reminder.list`, risk: low)
- `POST /api/v1/reminders/` — set a follow-up (permission: `reminders.reminder.create`, risk: medium)
- `GET /api/v1/reminders/<id>/` — one reminder (permission: `reminders.reminder.read`, risk: low)
- `PATCH /api/v1/reminders/<id>/` — reschedule and/or correct the note (permission: `reminders.reminder.update`, risk: medium)
**Send (create/update):**
- create: exactly one of `applicant`/`client` (UUID), `due_date` (`YYYY-MM-DD`, today NPT or later), `note` (required, ≤5000 chars)
- update: `due_date` and/or `note` — at least one; owner and lifecycle fields are rejected (`REMINDERS_FIELD_IMMUTABLE`)
**Returns:** `Reminder` | list[`Reminder`]
**Requires state:** the owner record must exist (any status — a reminder may be set on an archived applicant or retired client). For `PATCH`, the reminder must be `active`.
**Side effects:** every mutation appends one `HistoryEvent` (audit module). A create or a reschedule also determines what the **nightly notifications sweep** does later: when `due_date` arrives, each active Admin receives a `custom_reminder` notification (notifications module); a reschedule of a not-yet-closed reminder auto-resolves any already-raised alert on the next sweep and a fresh one is raised when the new date arrives.
**Notes:**
- List filters: `applicant`, `client`, `status`, `due_before`, `due_after` (both inclusive, on `due_date`), `fiscal_year` (`YYYY/YY` — a **Nepali (Bikram Sambat) fiscal-year label**, e.g. `2082/83`, Shrawan 1 to Ashadh end, resolved server-side to a Gregorian range over `due_date`). Omitting `status` returns open **and** closed reminders — hide finished ones client-side if the panel wants only open follow-ups.
- `status`, `closed_at`, `closed_by`, `created_by` are set by the server, never accepted from a client.
**Errors:**
- `REMINDERS_OWNER_REQUIRED` (400) — zero or two owner references in the create body
- `REMINDERS_OWNER_NOT_FOUND` (400) — the named owner id does not exist; `details` is `{ "<field>": ["Not found."] }`, e.g. `{ "applicant": ["Not found."] }`
- `REMINDERS_FIELD_IMMUTABLE` (400) — a `PATCH` carried `applicant`, `client`, `status`, `closed_at`, or `closed_by`; `details` maps each offending field to a one-message array
- `VALIDATION_ERROR` (400) — past `due_date`, blank `note`, empty `PATCH`, or a malformed query parameter
- `REMINDERS_REMINDER_NOT_FOUND` (404) — the id in the URL path
- `REMINDERS_REMINDER_ALREADY_CLOSED` (409) — `PATCH` on a completed or dismissed reminder; `details` is `{}` and the message names the current status — re-fetch the reminder for `closed_at`/`closed_by_username`

### Complete / Dismiss — `/api/v1/reminders/<id>/complete/`, `/api/v1/reminders/<id>/dismiss/`

**Use it when:** the follow-up happened (complete) or is no longer relevant (dismiss) — from the record panel or straight from the due alert.
**Methods:**
- `POST /api/v1/reminders/<id>/complete/` — mark done (permission: `reminders.reminder.complete`, risk: medium)
- `POST /api/v1/reminders/<id>/dismiss/` — drop it (permission: `reminders.reminder.dismiss`, risk: medium)
**Send (create/update):**
- optional `reason` (≤2000 chars) — recorded in the history event only, not on the reminder
**Returns:** `Reminder` (now terminal; `closed_at`/`closed_by_username` set)
**Requires state:** the reminder must be `active`.
**Side effects:** appends one `HistoryEvent`. If a `custom_reminder` notification is already active for this reminder, the **next nightly sweep auto-resolves it** (notifications module, resolution `source_cleared`) — closing the reminder is what clears the alert; a client should not also dismiss the notification.
**Errors:**
- `REMINDERS_REMINDER_NOT_FOUND` (404) — the id in the URL path
- `REMINDERS_REMINDER_ALREADY_CLOSED` (409) — it was already completed or dismissed

### History — `/api/v1/reminders/<id>/history/`

**Use it when:** showing what was set, when, and what happened to it later — the concept's "operational memory".
**Methods:**
- `GET /api/v1/reminders/<id>/history/` — chronological events, newest first (permission: `reminders.reminder.list_history`, risk: low)
**Send (create/update):** none
**Returns:** list[`HistoryEvent`]
**Requires state:** the reminder must exist (any status).
**Side effects:** none
**Errors:**
- `REMINDERS_REMINDER_NOT_FOUND` (404) — the id in the URL path

## 8. Flows

**Set a follow-up from a record screen**
1. On an applicant or client detail screen, `POST /api/v1/reminders/` with that record's id, a `due_date`, and a `note` → capture `id`.
2. Show it in the record's reminders panel via `GET /api/v1/reminders/?applicant=<record_id>` (or `?client=`).
   - 400 `REMINDERS_OWNER_NOT_FOUND`: the record id is stale — refresh the record screen.

**Act on a due alert (cross-app: notifications)**
1. A `custom_reminder` notification appears in an Admin's feed (`GET /api/v1/notifications/`); its `source_entity_id` is the reminder id and `source_api_path` is `/api/v1/reminders/<id>/`.
2. `GET /api/v1/reminders/<id>/` → show the note and the owning record (follow `applicant`/`client`).
3. `POST /api/v1/reminders/<id>/complete/` (or `/dismiss/`) → 200, terminal.
4. Do **not** dismiss the notification as well — the next nightly sweep resolves it automatically because the reminder is closed.
   - 409 `REMINDERS_REMINDER_ALREADY_CLOSED`: a colleague got there first — refresh; the alert will clear on the next sweep.

**Reschedule**
1. `PATCH /api/v1/reminders/<id>/` with a new `due_date` (and optionally a revised `note`) → 200.
2. The history (`GET /api/v1/reminders/<id>/history/`) now carries a `reminder_rescheduled` event with the old and new date in `changes`.
3. Any already-raised alert clears on the next sweep; a fresh alert is raised when the new date arrives.

## 9. Gaps

- No reminder search (`?search=`) exists — the list is filtered by owner/status/window only.
- There is no per-owner convenience route (`/api/v1/applicants/<id>/reminders/`); record panels use the `?applicant=`/`?client=` filters.
- The sweep's run time is a deployment decision and is not exposed through the API — "the alert appears on the due date" means "after that night's sweep", and this module cannot tell a client when that is.
- No bulk actions (complete/dismiss several at once).
- **A Lead Manager never receives the due alert, and cannot be shown anyone else's feed** — notification reads are scoped to the calling user, and reminder alerts route to Admins only. A Lead Manager's own follow-ups therefore surface nowhere automatically for them. A client that wants Lead Managers to see their due work must build it from this module directly: `GET /api/v1/reminders/?status=active&due_before=<npt_today>`.
- The payload carries `created_by_username`/`closed_by_username` but no user UUIDs — an avatar or profile link needs an out-of-band username lookup, and usernames are not guaranteed immutable.
