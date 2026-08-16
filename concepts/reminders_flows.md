# FLOWS — Reminders

**Owner app:** `reminders`
**Updated:** 2026-08-17
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/reminders.txt` to the callable endpoints in `backend/reminders/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

---

## Flow: Set a follow-up on a record

- **Actor:** Admin or Lead Manager
- **Goal:** Leave a dated note on an applicant or client so the consultancy is prompted to revisit it.
- **Entry point:** Reminders panel (on the applicant detail or client detail screen)

**Steps** — each step binds a screen action to the endpoint that realizes it:

1. **Reminders panel** — open the record's panel →
   `GET /api/v1/reminders/?applicant=<id>` or `?client=<id>` (`reminders.reminder.list`)
   - **Requires state:** the record exists (any status).
   - **Side effects:** none
2. **Reminders panel** — "Add reminder" with a due date and a note →
   `POST /api/v1/reminders/` (`reminders.reminder.create`)
   - **Requires state:** the owning record exists; the due date is Nepal's today or later.
   - **Side effects:** one `reminder_created` audit event; from the due date onward, the nightly
     sweep raises a `custom_reminder` alert to every active Admin (cross-app: `notifications`).
   - *Failure — `VALIDATION_ERROR`:* inline field errors (past date, blank note).
   - *Failure — `REMINDERS_OWNER_NOT_FOUND`:* the record id is stale — refresh the record screen.
3. **Reminders panel** — refresh the list to show the new entry →
   `GET /api/v1/reminders/?applicant=<id>&status=active` (`reminders.reminder.list`)
   - **Requires state:** none
   - **Side effects:** none

## Flow: Act on a due reminder alert

- **Actor:** Admin
- **Goal:** A reminder's date has arrived; deal with the follow-up and make the alert go away.
- **Entry point:** Notification feed (existing notifications screen)

**Steps:**

1. **Notification feed** — a `custom_reminder` alert appears →
   `GET /api/v1/notifications/` (`notifications.notification.list`) **(cross-app: `notifications`)**
   - **Requires state:** the nightly sweep has run since the reminder's date began.
   - **Side effects:** none
2. **Reminders panel / reminder detail** — follow the alert's `source_api_path` →
   `GET /api/v1/reminders/<id>/` (`reminders.reminder.read`)
   - **Requires state:** none
   - **Side effects:** none
   - *Failure — `REMINDERS_REMINDER_NOT_FOUND`:* show "this reminder no longer resolves" and let
     the user dismiss the notification manually — should not occur, since reminders are never deleted.
3. **Reminder detail** — jump to the owning record via its `applicant`/`client` id →
   `GET /api/v1/applicants/<id>/` (`applicants.applicant.read`) **(cross-app: `applicants`)** or
   `GET /api/v1/clients/<id>/` (`clients.client.read`) **(cross-app: `clients`)**
   - **Requires state:** none
   - **Side effects:** none
4. **Reminder detail** — the follow-up happened → "Complete" (or "Dismiss" if no longer relevant) →
   `POST /api/v1/reminders/<id>/complete/` (`reminders.reminder.complete`) or
   `POST /api/v1/reminders/<id>/dismiss/` (`reminders.reminder.dismiss`)
   - **Requires state:** the reminder is `active`.
   - **Side effects:** `closed_at`/`closed_by` stamped; one audit event; the pending admin alert
     auto-resolves as `source_cleared` on the next nightly sweep (cross-app: `notifications`) —
     **do not also dismiss the notification**.
   - *Failure — `REMINDERS_REMINDER_ALREADY_CLOSED` (409):* a colleague got there first — refresh;
     the alert clears on the next sweep.

## Flow: Reschedule a follow-up

- **Actor:** Admin or Lead Manager
- **Goal:** The follow-up should happen on a different day (or the note needs correcting).
- **Entry point:** Reminders panel

**Steps:**

1. **Reminders panel** — "Reschedule" with a new date and/or revised note →
   `PATCH /api/v1/reminders/<id>/` (`reminders.reminder.update`)
   - **Requires state:** the reminder is `active`; the new date is Nepal's today or later.
   - **Side effects:** a `reminder_rescheduled` (date moved) or `reminder_updated` (note only)
     audit event with the old→new values; any already-raised alert auto-resolves on the next sweep
     and a fresh one fires when the new date arrives (cross-app: `notifications`).
   - *Failure — `REMINDERS_FIELD_IMMUTABLE`:* the edit form sent an owner or lifecycle field —
     send only `due_date`/`note`.
   - *Failure — `REMINDERS_REMINDER_ALREADY_CLOSED` (409):* closed reminders cannot move; offer
     "create a new reminder" instead.
2. **Reminder history** — show what changed →
   `GET /api/v1/reminders/<id>/history/` (`reminders.reminder.list_history`)
   - **Requires state:** none
   - **Side effects:** none

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `reminders.reminder.list` | `GET /api/v1/reminders/` | Set a follow-up on a record | Also the due-window worklist (`?due_before=`), which has no dedicated flow yet |
| `reminders.reminder.create` | `POST /api/v1/reminders/` | Set a follow-up on a record | |
| `reminders.reminder.read` | `GET /api/v1/reminders/<id>/` | Act on a due reminder alert | The `source_api_path` target of a `custom_reminder` notification |
| `reminders.reminder.update` | `PATCH /api/v1/reminders/<id>/` | Reschedule a follow-up | |
| `reminders.reminder.complete` | `POST /api/v1/reminders/<id>/complete/` | Act on a due reminder alert | Also available from the reminders panel directly |
| `reminders.reminder.dismiss` | `POST /api/v1/reminders/<id>/dismiss/` | Act on a due reminder alert | The "no longer relevant" branch |
| `reminders.reminder.list_history` | `GET /api/v1/reminders/<id>/history/` | Reschedule a follow-up | The concept's "operational memory" — also useful on the reminder detail view unconditionally |

## Cross-app dependencies

- **This app references (outbound):** `notifications.notification.list` (the due alert is the entry
  point of "Act on a due reminder alert"), `applicants.applicant.read` and `clients.client.read`
  (jumping from a reminder back to its record).
- **Referenced by other apps (inbound):** `concepts/notifications_flows.md` names this file as the
  destination of a `custom_reminder` click-through (its outbound edge is data-driven via
  `source_api_path`).

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.

## Open questions

- **No due-reminders worklist screen is named in the concept.** The list endpoint supports
  `?due_before=<today>&status=active` for a "what needs chasing" view, but the concept only names the
  record panels and the notification feed. If the frontend wants that screen, the endpoint is ready.
- **The sweep's run time is not exposed** (same gap as `notifications`): "the alert fires on the due
  date" means "after that night's sweep", and no endpoint says when that is.
