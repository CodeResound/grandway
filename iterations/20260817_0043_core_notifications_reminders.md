# Iteration — 2026-08-17 — reminders app, custom-reminder sweep alerts

## Reminders

## 1. Module

- Name: Reminders — one-off, date-only follow-up notes set by staff against an applicant or client, surfaced to Admins as a notification when the date arrives. New app this session.
- Base path: `/api/v1/reminders/`
- Auth: Bearer JWT. Admin and Lead Manager may do everything; Superadmin denied everything, reads included.

## 2. Conventions

- Response: standard project envelope — `success`, `message`, `data`, `meta`.
- Error: `success` false with `error.code` / `error.message` / `error.details` (always present, `{}` when empty). This module's 403 is `REMINDERS_ACTOR_FORBIDDEN`, replacing the project-wide `PERMISSION_DENIED`. Field validation uses `VALIDATION_ERROR` with fields in `details`.
- Auth failures: 401 from the authentication framework (no/expired/revoked token); 403 only for Superadmin.
- Pagination: page-number based, `page`/`page_size` (default 20, max 100 — over-max clamped), `data` is the bare array, `meta` carries `count`/`page`/`page_size`/`next`/`previous` (absolute URLs or null). Both list endpoints.
- IDs: UUID strings.
- Times: `updated_at` ISO 8601 UTC with no BS sibling; `due_date`, `closed_at`, `created_at` carry `_bs` Bikram Sambat siblings (object or null, shape `{ year, month, day, month_name, display }`). Write Gregorian `YYYY-MM-DD` only.
- List/search/filter/order params: `applicant`, `client`, `status`, `due_before`, `due_after` (inclusive, on `due_date`), `fiscal_year` (`YYYY/YY`, over `due_date`); newest first, no ordering param, no search.

## 3. Models

- **Reminder** — `{ id, owner_type:[enum], applicant?:uuid, client?:uuid, due_date, due_date_bs:json, note, status:[enum], is_active, closed_at?, closed_at_bs?:json, closed_by_username?, created_by_username, created_at, created_at_bs:json, updated_at }`
  - Exactly one of `applicant`/`client` is set; the other is null; `owner_type` names which. Bare UUIDs, not nested objects.
  - Same shape from every endpoint — no list/detail split.
- **HistoryEvent** — `{ id, action, actor_type:[enum], actor_id?:uuid, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`
  - Owned by the `audit` module; this app renders it. A reschedule carries `due_date` old→new in `changes`.

## 4. Enums

- `Reminder.owner_type`: `applicant` | `client`
- `Reminder.status`: `active` | `completed` | `dismissed`
- `HistoryEvent.action`: `reminder_created` | `reminder_rescheduled` | `reminder_updated` | `reminder_completed` | `reminder_dismissed`

## 5. Dependency order

- `Reminder` needs an `Applicant` (external module) or a `Client` (external module) — exactly one, existing first.

**Start here:** `POST /api/v1/reminders/` against a record you already have.

## 6. Endpoints

### Reminder — `/api/v1/reminders/`

**Use it when:** a record screen's reminders panel (`?applicant=` / `?client=`), a due-window worklist, or setting a follow-up.
**Methods:**
- `GET /api/v1/reminders/` — list, filterable
- `POST /api/v1/reminders/` — set a follow-up (201)
- `GET /api/v1/reminders/<id>/` — one reminder
- `PATCH /api/v1/reminders/<id>/` — reschedule and/or correct the note
**Send (create/update):**
- create: exactly one of `applicant`/`client`, `due_date` (today NPT or later), `note` (required)
- update: `due_date` and/or `note` (at least one); owner and lifecycle fields rejected
**Returns:** Reminder | list[Reminder]
**Notes:**
- `status`, `closed_at`, `closed_by`, `created_by` are server-set, never accepted.
- Owner is immutable after create; a wrong-record reminder is dismissed and recreated.
- A `PATCH` carrying an immutable field is rejected loudly, not silently dropped.
- A no-op `PATCH` writes no history event.
**Errors:**
- `REMINDERS_OWNER_REQUIRED` (400) — zero or two owners on create
- `REMINDERS_OWNER_NOT_FOUND` (400) — the named owner id does not exist; `details` names the field
- `REMINDERS_FIELD_IMMUTABLE` (400) — `PATCH` carried `applicant`, `client`, `status`, `closed_at`, or `closed_by`
- `REMINDERS_REMINDER_NOT_FOUND` (404) — the id in the URL path
- `REMINDERS_REMINDER_ALREADY_CLOSED` (409) — `PATCH` on a closed reminder

### Complete / Dismiss — `/api/v1/reminders/<id>/complete/`, `/dismiss/`

**Use it when:** the follow-up happened (complete) or is no longer relevant (dismiss), from the record panel or straight from the due alert.
**Methods:**
- `POST /api/v1/reminders/<id>/complete/` — mark done (200)
- `POST /api/v1/reminders/<id>/dismiss/` — drop it (200)
**Send (create/update):**
- optional `reason` — recorded in history only, not on the reminder
**Returns:** Reminder (terminal; `closed_at`/`closed_by_username` set)
**Notes:**
- Only while `active`; terminal is final — no reopen anywhere. "Remind me again" is a new reminder.
- Closing the reminder is what clears the pending admin alert (next nightly sweep); the client must not also dismiss the notification.
**Errors:**
- `REMINDERS_REMINDER_ALREADY_CLOSED` (409) — already completed or dismissed
- `REMINDERS_REMINDER_NOT_FOUND` (404) — the id in the URL path

### History — `/api/v1/reminders/<id>/history/`

**Use it when:** showing what was set, when, and what happened to it later.
**Methods:**
- `GET /api/v1/reminders/<id>/history/` — events newest first
**Send (create/update):** none
**Returns:** list[HistoryEvent]
**Errors:**
- `REMINDERS_REMINDER_NOT_FOUND` (404) — the id in the URL path

## 7. Flows

**Set a follow-up from a record screen**
1. `POST /api/v1/reminders/` with the record's id, a due date, and a note → capture `id`.
2. `GET /api/v1/reminders/?applicant=<record_id>` to render the record's panel.
   - `REMINDERS_OWNER_NOT_FOUND` → the record id is stale; refresh the record screen.

**Act on a due alert (cross-app: notifications)**
1. A `custom_reminder` notification arrives in an Admin's feed; its `source_api_path` is `/api/v1/reminders/<id>/`.
2. `GET /api/v1/reminders/<id>/` → show the note; follow `applicant`/`client` to the record.
3. `POST /api/v1/reminders/<id>/complete/` (or `/dismiss/`).
   - 409 → a colleague closed it first; refresh, the alert clears on the next sweep.
4. Do not dismiss the notification — the next sweep resolves it as `source_cleared`.

**Reschedule**
1. `PATCH /api/v1/reminders/<id>/` with a new `due_date` → the old alert (if raised) resolves on the next sweep; a fresh one fires when the new date arrives.
2. `GET /api/v1/reminders/<id>/history/` shows `reminder_rescheduled` with the old and new date.

## 8. Gaps

- No reminder search and no ordering parameter — owner/status/window filters only.
- No per-owner nested route; record panels use query filters.
- The nightly sweep's run time is not exposed anywhere — "the alert fires on the due date" means "after that night's sweep".
- No bulk complete/dismiss.

## Notifications

## 1. Module

- Name: Notifications — in-app alert stream. This session: one new sweep-raised type; no endpoint changes.
- Base path: `/api/v1/notifications/`
- Auth: unchanged.

## 2. Conventions

- No changes this session.

## 3. Models

- No shape changes. Existing Notification shape now also carries `notification_type: "custom_reminder"` rows with `source_app: "reminders"`, `source_entity_type: "reminder"`, `source_api_path: /api/v1/reminders/<id>/`, and `due_at` at Kathmandu midnight of the reminder's due date.

## 4. Enums

- `Notification.notification_type`: gained `custom_reminder` (sweep-raised; priority `normal`). Full set is now 15 values; the three declared-but-ungenerated values are unchanged.

## 5. Dependency order

- `custom_reminder` alerts need an active, due `Reminder` (external module) and at least one active Admin account.

**Start here:** unchanged.

## 6. Endpoints

- No endpoints added, changed, or retired this session. The new type flows through the existing feed, summary, read/unread, and dismiss endpoints unchanged.

## 7. Flows

**Receive and clear a custom reminder alert**
1. The nightly sweep raises one `custom_reminder` alert per active Admin when a reminder's date arrives; idempotent across runs.
2. The Admin clears it by closing the *reminder* (cross-app: reminders) — the next sweep resolves the alert as `source_cleared`.
   - Dismissing the alert instead leaves the reminder open and the dismissal sticks — no re-nag under the same key; a reschedule mints a new key and may legitimately alert again.

## 8. Gaps

- The stale "remind me tomorrow does not exist" gap was narrowed: date-based follow-ups now exist as reminders records, but notification-level snooze still does not.

## Core

## 1. Module

- Name: core — global URL table and project-level consumer docs. No endpoints of its own changed.
- Base path: `/api/v1/`
- Auth: unchanged.

## 2. Conventions

- No changes this session.

## 3. Models

- No changes.

## 4. Enums

- No changes.

## 5. Dependency order

- The app inventory and dependency graph gained `reminders`; the `notifications` edge gained its fourth sweep-read; `clients` is no longer an island (first inbound business-app FK, from `reminders`).

## 6. Endpoints

- No endpoints added, changed, or retired. `/api/v1/reminders/` was mounted into the global URL table.

## 7. Flows

- No changes.

## 8. Gaps

- none
