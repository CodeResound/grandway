# Data Contract — Reminders

**Owner app:** `reminders`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-08-17
**Purpose:** Owns operational follow-up reminders — a future, date-only note set by staff against exactly one applicant or client record. It does **not** own the records reminders point at (`applicants`, `clients`), the alert that surfaces when a reminder falls due (`notifications` raises and owns it), or any history table — a reminder's history is the central `audit` log filtered to that reminder.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-17 | AI (Claude) | Initial contract — `Reminder` |

---

## Deliberate Deviations

`concepts/reminders.txt` settles the feature's shape; the departures and decisions worth recording are:

- **One `closed_at`/`closed_by` pair, not per-action timestamps.** Complete and dismiss are both terminal; `status` already says which one happened. Separate `completed_at`/`dismissed_at` pairs would need a four-way coherence constraint to keep them honest, for no query that a `status` filter doesn't already answer.
- **The owner is immutable after create.** A reminder set against the wrong record is dismissed and recreated, keeping the audit trail and the notification source stable. Allowing the FK to move would silently re-point history written about a different record.
- **No reschedule history on the row.** The audit log carries every `due_date` change (`reminder_rescheduled` with old→new in `changes`), and the notification layer's dedupe discriminator carries the current date. A `previous_due_date` column would be a second source of truth.
- **`due_date` may be today, not strictly future.** The concept says "future due date"; a today-dated reminder is legitimate ("chase this before end of day") and fires on the next nightly sweep. Only past dates are rejected.
- **The optional `reason` on complete/dismiss is not a column.** It is recorded on the audit event only — the concept's traceability requirement is about history, and a mostly-empty column duplicating the audit log fails the same second-source-of-truth test as reschedule history.
- **`owner_type` is a derived property, not a column** — same rationale as `uploaded_files`: a stored copy could disagree with the foreign keys.
- **No trigram index on `note`.** `note` is prose context, not an identity field, and the concept defines no reminder search (§39.6 applies to searchable name fields).

---

## 1. Reminder

**Purpose:** A one-off future follow-up tied to exactly one source record. Three essential parts: the source record (applicant or client), a date-only due date, and a note explaining why the reminder exists. Due at the start of the chosen day, Nepal time.
**Table:** `reminders_reminder`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → `applicants.Applicant` | One of two | Yes | No | `PROTECT`. Exactly one of `applicant`/`client` — DB-enforced |
| client | FK → `clients.Client` | One of two | Yes | No | `PROTECT`. Exactly one of `applicant`/`client` — DB-enforced |
| due_date | Date | Yes | No | No | Date-only; the reminder is due at the start of this day (NPT). Today or later on create/reschedule |
| note | Text | Yes | No | No | Why the reminder exists. Unicode-normalized on write |
| status | CharField(15) | No | No | No | Defaults to `active`; indexed |
| closed_at | DateTime | No | Yes | Yes | Stamped by complete or dismiss; `status` says which |
| closed_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL`; stamped by complete or dismiss |
| created_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`status`** — `active` | `completed` | `dismissed`. Defined in `reminders/constants.py` `ReminderStatus`. `completed` and `dismissed` are terminal (`TERMINAL_STATUSES`); there is no reopen — the concept says a follow-up that outlives its reminder gets a new reminder.

**Validation Rules:**

- Exactly one of `applicant`/`client` must be set — validated in the serializer (`Supply exactly one of: applicant, client`) and enforced by the `reminder_single_owner` CheckConstraint (explicit Q-disjunction derived from `OWNER_FIELDS`, the `uploaded_files` pattern).
- The owner FKs are **immutable after create** — the update serializer does not accept them.
- `due_date >= nepal_today()` on create and on reschedule (§39.5 — "today" is Nepal's today, not UTC's).
- `note` is required, non-blank, and Unicode-normalized (§39.2) in the serializer **and** the service layer, as is the optional `reason` on complete/dismiss.
- `PATCH` may change `due_date` and/or `note` (at least one), only while `status=active`. Acting on a closed reminder (update, complete, dismiss) → `REMINDERS_REMINDER_ALREADY_CLOSED` (409).
- `status`, `closed_at`, `closed_by` never move through the update endpoint — only through the complete/dismiss actions, which stamp who acted.
- `reminder_closure_matches_status` CheckConstraint: `active` ⇒ `closed_at` is null; terminal ⇒ `closed_at` is set. (`closed_by` is outside the constraint — it is `SET_NULL`, same reason `notifications` keeps `dismissed_by` outside its coherence constraint.)

**Derived, read-only:** `owner_type` (`applicant` | `client`, walked from whichever FK is set), `owner_id`, `is_active` (the status is `active`).

**Indexes:**

- `(applicant, -created_at)` — `reminder_applicant_idx`. The applicant detail screen's reminders panel.
- `(client, -created_at)` — `reminder_client_idx`. The client detail screen's reminders panel.
- `(status, due_date)` — `reminder_sweep_idx`. The nightly sweep's due query (`status=active, due_date<=today`) and the list's status + due-window filters.

**Soft Delete:** `N/A — no deletion at all.` There is no delete endpoint and no delete service. A reminder ends as `completed` or `dismissed` and is retained forever — reminders are operational memory; the consultancy should be able to tell why a reminder existed after the date has passed (`concepts/reminders.txt`). Both owner FKs and `created_by` are `PROTECT`.

**Cross-App Dependencies:**

- `applicants.Applicant`, `clients.Client` — owner FKs (`PROTECT`), exactly one set.
- `authenticate.User` — FKs for `created_by` (`PROTECT`) and `closed_by` (`SET_NULL`).
- `audit` — service call. Every mutation appends one event (`reminder_created` / `reminder_rescheduled` / `reminder_updated` / `reminder_completed` / `reminder_dismissed`); `entity_type="reminder"`.
- **Referenced by: `notifications`** — the nightly sweep calls `reminders.selectors.get_due_reminders()` to raise `custom_reminder` alerts to Admins, and auto-resolves them when a reminder is closed or rescheduled. The coupling runs inward to `notifications` (it imports this app's selector); `reminders` imports nothing from `notifications`. Documented in `notifications/docs/INTEGRATION.md` §2.

**Example:**

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
  "closed_at": null,
  "closed_at_bs": null,
  "closed_by_username": null,
  "created_by_username": "adminuser",
  "created_at": "2026-08-17T05:12:30Z",
  "created_at_bs": { "year": 2083, "month": 5, "day": 1, "month_name": "Bhadra", "display": "2083 Bhadra 1" },
  "updated_at": "2026-08-17T05:12:30Z"
}
```

---

## Cross-App Dependencies

- **Outward (this app's models reference):** `applicants` (owner FK), `clients` (owner FK), `authenticate` (`created_by`, `closed_by`). Runtime service call to `audit.services.record_event` for every mutation.
- **Inward (who references this app):** `notifications` — runtime service-call coupling only (the sweep reads `get_due_reminders()` and composes alerts from reminder rows); no FK to `Reminder` exists anywhere. Per §4 this is recorded here and in `notifications/docs/INTEGRATION.md` §2 `Requires`.

---

## Soft Delete

`N/A — no model in this app deletes.` `Reminder` ends in a terminal status and is retained; see the per-model section above.
