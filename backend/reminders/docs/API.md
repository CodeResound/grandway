# API — Reminders

**Owner app:** `reminders`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-08-17
**Base prefix:** `/api/v1/reminders/`
**Auth:** Bearer access JWT (`authenticate.SessionBoundJWTAuthentication`) on every endpoint
**Throttle:** project defaults only — `UserRateThrottle` at 1000/hour. No endpoint here is public, and none is expensive: every list is paginated at 100 rows max and every detail read is a single-row lookup with `select_related`.
**Access level:** protected. Reads and writes: Admin + Lead Manager. Superadmin denied on every route including reads.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-17 | AI (Claude) | Initial API documentation — 7 endpoints across one resource |

---

## Access model (§9 interim inline pattern)

This app uses the interim inline access checks in `reminders/access.py`. There is no `permissions.py`.

| Check | Applies to | Allows | Denies |
|-------|-----------|--------|--------|
| `require_reminder_actor` | every route | `admin`, `lead_manager` | `superadmin` → 403 `REMINDERS_ACTOR_FORBIDDEN` |

One rule for read and write, as in `offers`: a reminder is a note on a record the actor already works, and letting them see it but not complete it would put an Admin in the middle of every routine follow-up. The concept's Admin-only rule is about who *receives* the due alert — that is `notifications` routing (`recipients_for_admins`), not an access rule here. **No endpoint in this app is public.**

**No `DELETE` method is exposed on any resource.** A reminder ends as `completed` or `dismissed` and is retained forever — see `DATA_CONTRACT.md` "Soft Delete".

---

## Error codes

All codes live in `reminders/constants.py` `ErrorCode`.

| Code | HTTP | Meaning |
|------|------|---------|
| `REMINDERS_ACTOR_FORBIDDEN` | 403 | The caller's authority may not use reminders — a Superadmin |
| `REMINDERS_REMINDER_NOT_FOUND` | 404 | No reminder with the id in the URL path |
| `REMINDERS_OWNER_REQUIRED` | 400 | Zero or two owner references in the create body |
| `REMINDERS_OWNER_NOT_FOUND` | 400 | The named owner record does not exist — `error.details` names the field |
| `REMINDERS_FIELD_IMMUTABLE` | 400 | A `PATCH` carried `applicant`, `client`, `status`, `closed_at`, or `closed_by` |
| `REMINDERS_REMINDER_ALREADY_CLOSED` | 409 | Update, complete, or dismiss on a completed or dismissed reminder |

Serializer-level failures (past `due_date`, blank `note`, empty `PATCH`, malformed query parameters) return the project-wide `VALIDATION_ERROR` (400) with the offending fields in `error.details`.

---

## Module-wide rules

These hold on every endpoint below and are not repeated per endpoint.

- **Standard envelope** (§7) on success and error.
- **Ownership is exactly-one-of-two and immutable.** A reminder points at one applicant **or** one client, fixed at creation. Enforced three times: serializer (usable field error), service (`resolve_owner` — a direct caller cannot bypass it), and the `reminder_single_owner` database constraint.
- **Terminal is final.** `completed` and `dismissed` cannot be left. "Remind me again" is a new reminder.
- **Dates.** `due_date` is date-only Gregorian `YYYY-MM-DD`, must be Nepal's today (§39.5) or later on create and reschedule. Responses carry `due_date_bs`, `closed_at_bs`, and `created_at_bs` Bikram Sambat siblings (§39.4).
- **Unicode normalization** (§39.2) on `note` and `reason`, in the serializer and again in the service.
- **The due alert is not raised here.** The nightly `sweep_notifications` command (notifications app) reads `selectors.get_due_reminders()` and fans a `custom_reminder` alert out to every active Admin. Completing, dismissing, or rescheduling drops the reminder's dedupe key from the sweep's live set, which auto-resolves the alert on the next run.

---

## 1. Reminder

### 1.1 List reminders

- **URI:** `GET /api/v1/reminders/`
- **Permission key:** `reminders.reminder.list` (risk: low)
- **Query parameters** (validated — an invalid value is 400, not ignored): `applicant` (UUID), `client` (UUID), `status` (`active` | `completed` | `dismissed`), `due_before` / `due_after` (`YYYY-MM-DD`, inclusive, on `due_date`), `fiscal_year` (`YYYY/YY`, over `due_date` per §39.4), `page`, `page_size`.
- **Response:** paginated list of the Reminder shape (`DATA_CONTRACT.md` §1 example). Newest first.
- **Query access pattern:** `selectors.get_reminders()` — `select_related("applicant", "client", "created_by", "closed_by")`, so the list is four joins and zero N+1; owner filters hit `reminder_applicant_idx` / `reminder_client_idx`, status+window filters hit `reminder_sweep_idx`.
- **Business rules:** omitting `status` returns open and closed reminders alike — hiding finished follow-ups is the client's presentation decision.
- **AI debugging notes:** an empty panel on a record screen usually means the filter id is for the *other* owner type — a client id passed as `?applicant=` matches nothing rather than erroring.

### 1.2 Set a reminder

- **URI:** `POST /api/v1/reminders/`
- **Permission key:** `reminders.reminder.create` (risk: medium)
- **Request:** `{ "applicant" | "client": "<uuid>" (exactly one), "due_date": "YYYY-MM-DD", "note": "..." }`
- **Response:** 201, the created Reminder.
- **Validation rules:** exactly one owner; owner must exist (any status — an archived applicant or retired client may still carry a follow-up); `due_date >= nepal_today()`; `note` required, ≤5000 chars, NFC-normalized.
- **Business rules:** `status` starts `active`; `created_by` is the caller; an audit event `reminder_created` is appended with the owner and due date in metadata.
- **Error codes:** `REMINDERS_OWNER_REQUIRED`, `REMINDERS_OWNER_NOT_FOUND`, `VALIDATION_ERROR`.

### 1.3 Retrieve a reminder

- **URI:** `GET /api/v1/reminders/<reminder_id>/`
- **Permission key:** `reminders.reminder.read` (risk: low)
- **Response:** the Reminder shape. This is also the `source_api_path` target of a `custom_reminder` notification.
- **Error codes:** `REMINDERS_REMINDER_NOT_FOUND`.

### 1.4 Reschedule / correct

- **URI:** `PATCH /api/v1/reminders/<reminder_id>/`
- **Permission key:** `reminders.reminder.update` (risk: medium)
- **Request:** `due_date` and/or `note` — at least one.
- **Validation rules:** same `due_date` floor as create; owner and lifecycle fields are rejected with `REMINDERS_FIELD_IMMUTABLE`, never silently dropped.
- **Business rules:** only while `active` (else 409). A `due_date` change is audited as `reminder_rescheduled` with the old→new pair in `changes`; a note-only edit as `reminder_updated`. A no-op `PATCH` writes no audit event. A reschedule also re-keys the notification dedupe, so a pending alert auto-resolves on the next sweep and a fresh one fires on the new date.
- **Error codes:** `REMINDERS_FIELD_IMMUTABLE`, `REMINDERS_REMINDER_ALREADY_CLOSED`, `VALIDATION_ERROR`, `REMINDERS_REMINDER_NOT_FOUND`.

### 1.5 Complete

- **URI:** `POST /api/v1/reminders/<reminder_id>/complete/`
- **Permission key:** `reminders.reminder.complete` (risk: medium)
- **Request:** `{ "reason": "..." }` — optional; recorded on the audit event only.
- **Response:** 200, the Reminder with `status=completed`, `closed_at`/`closed_by` stamped.
- **Business rules:** only while `active`; terminal thereafter. Audited as `reminder_completed`. The pending admin alert (if any) auto-resolves as `source_cleared` on the next sweep.
- **Error codes:** `REMINDERS_REMINDER_ALREADY_CLOSED`, `REMINDERS_REMINDER_NOT_FOUND`.

### 1.6 Dismiss

- **URI:** `POST /api/v1/reminders/<reminder_id>/dismiss/`
- **Permission key:** `reminders.reminder.dismiss` (risk: medium)
- Same contract as 1.5 with `status=dismissed` and audit action `reminder_dismissed`.

### 1.7 History

- **URI:** `GET /api/v1/reminders/<reminder_id>/history/`
- **Permission key:** `reminders.reminder.list_history` (risk: low)
- **Response:** paginated audit events, newest first, serialized by audit's canonical `AuditEventHistorySerializer`.
- **Query access pattern:** `selectors.get_history_for_reminder` → `audit.selectors.get_events_for_entity(entity_type="reminder", entity_id=..., app_label="reminders")` — the central log's `(entity_type, entity_id)` index.
- **Error codes:** `REMINDERS_REMINDER_NOT_FOUND`.

---

## AI debugging notes

- "The alert never appeared" is almost always one of: the sweep has not run since the due date began (it is nightly cron, not real-time), the reminder was closed before the sweep ran, or the recipient is not an active Admin (`authority_type=admin, is_active=True` — Lead Managers never receive reminder alerts).
- "The alert came back after dismissal" cannot happen from this app: a dismissed notification keeps its dedupe key. If a fresh alert appeared, the reminder was rescheduled — check the reminder's history for `reminder_rescheduled`.
- The service layer does **not** enforce the due-date floor (a reminder legitimately *becomes* past-due by aging); only the serializers do. A management command creating past-dated reminders is creating already-due ones, which the next sweep will raise.
