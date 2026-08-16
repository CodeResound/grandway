# Data Contract — Notifications

**Owner app:** `notifications`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the user-facing alert stream — one row per recipient per thing that needs attention. It owns **no business state whatsoever**: `checklists` owns what is outstanding, `offers` owns response deadlines, `applicants` owns passport expiry, `uploaded_files` owns file rejections, and `applicant_journeys` owns lifecycle stage. This app records that someone was told, when, and whether they have dealt with it. Every notification points at a source record and never replaces it.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial contract — one model, dedupe-key idempotency, sweep + signal generation, in-app delivery only |
| 1.1.0 | 2026-08-17 | AI (Claude) | Added the `custom_reminder` sweep type (staff-set follow-up reminders from the new `reminders` app): type choice, `normal` priority, dedupe discriminator (due date), sweep generator + `reminders` cross-app row. Additive — no existing shape changed |

---

## Deliberate Deviations

`concepts/notifications.txt` leaves five questions open and names two source apps that do not exist. Each departure below is a decision taken with the user before implementation, not an oversight:

- **`title` and `body` are single English fields.** They are sentences this system composes from a source record — "Passport expires in 21 days" — not names.
- **The feed is own-recipient only — stricter than any other app in this project.** Every other app lets an Admin read everything. Here an Admin cannot read another user's notifications over the API, because a notification is one person's work queue rather than a record about the business. It costs an Admin nothing operationally — everything a notification points at is readable through the source app's own endpoints — and it removes the ability to read somebody's inbox without leaving a trace. Cross-user inspection stays in Django admin, where it is attributable. Fetching another user's notification by id returns **404, not 403**: a 403 would confirm the id exists on somebody else's feed. See `API.md` §1.
- **Three type values ship with no generator.** `missing_information`, `appointment_reminder`, and `test_score_expiring` are named in the concept file but have no source: no app defines what "required information" is, and the `appointments` and `test_scores` apps do not exist. The values are declared so the frontend gets the whole vocabulary at once and so adding a generator later is not a schema change. Nothing produces them today.
- **The concept's `expired` lifecycle state is folded into `resolved`.** The concept lists "resolved, dismissed, or expired" as terminal states. `expired` and `resolved` would be written by the same code path for the same reason — the source condition stopped being true — so a separate value would only ever be a second name for one fact. `resolution = source_cleared` carries the distinction where it matters.
- **No `snooze`.** The concept lists it as optional. Deferring an alert without acting on it is the behaviour that makes an inbox stop being read, and the escalation mechanism below already handles "not now, but soon."

---

## The idempotency contract — `dedupe_key`

Every other rule in this file follows from this one, so it is stated before the model.

A nightly sweep re-asks "what is overdue?" and would create a duplicate row every night. A `post_save` receiver fires on every save and would create a duplicate row every time an unrelated field changed. Both are the same problem, and both are solved by one column rather than two mechanisms:

```
dedupe_key = "<notification_type>:<source_entity_type>:<source_entity_id>[:<discriminator>]"
```

under an **unconditional** `UniqueConstraint(recipient, dedupe_key)`. Every generator writes through `get_or_create` on that pair. Three properties follow:

1. **Re-running is free.** A second sweep on the same day creates nothing. Re-saving a journey creates nothing.
2. **The key is the change detector.** No `pre_save` receiver stashes a previous value anywhere in this app. A journey's key carries its stage, so a stage *change* produces a new key and a save-without-change does not.
3. **Escalation, not nagging.** An item crossing from due-soon to overdue changes the type segment of its key, so it legitimately raises one new, higher-priority alert. The old one is auto-resolved by the same sweep. This is the answer to the concept's open question "how aggressively should overdue items keep resurfacing": they do not resurface under the same key once dismissed — escalation to a higher severity is the only re-entry.

**Discriminators actually used** (the discriminator is what makes a genuinely new instance of the same condition raisable):

| Type | Key |
|---|---|
| `checklist_item_due` / `checklist_item_overdue` | `<type>:checklist_item:<id>:<due date>` — a re-scheduled item raises a fresh alert |
| `offer_response_due` / `offer_expired` | `<type>:offer:<id>:<response deadline>` |
| `passport_expiring` | `passport_expiring:passport_detail:<id>:<expiry date>` — a renewed passport raises a fresh alert |
| `custom_reminder` | `custom_reminder:reminder:<id>:<due date>` — a rescheduled reminder raises a fresh alert on its new date |
| `missing_documents` | `missing_documents:checklist:<id>` — no discriminator; see Known Limitations |
| `assignment_received` | `assignment_received:<checklist\|checklist_item>:<id>:<assignee id>` — reassignment alerts the new assignee |
| `file_rejected` | `file_rejected:uploaded_file:<id>` |
| `journey_stage_changed` / `journey_closed` | `<type>:applicant_journey:<id>:<stage>` |
| `offer_decided` | `offer_decided:offer:<id>:<status>` |

**Known Limitations of this scheme**, stated rather than discovered later:

- `missing_documents` carries no discriminator, so once it is resolved for a checklist it is never raised again for that checklist even if a new document requirement is added. Putting the pending count in the key was considered and rejected: collecting one of five documents would resolve the old alert and raise a new one on every sweep, which is the noise the whole design exists to prevent.
- `journey_stage_changed` will not re-alert on a move *back* to a stage the journey already held.
- `file_rejected` will not re-alert if a file is rejected, verified, and rejected again. In practice a corrected file is a new `UploadedFile` row (that app versions rather than overwrites), so the same key never recurs.

---

## 1. Notification

**Purpose:** One alert, for one recipient, about one source record. Created only by this app's sweep command or its signal receivers — there is no create endpoint, and no other app calls in.
**Table:** `notifications_notification`

**`notification_type` choices:** `checklist_item_due`, `checklist_item_overdue`, `missing_documents`, `missing_information`, `offer_response_due`, `offer_expired`, `passport_expiring`, `custom_reminder`, `test_score_expiring`, `appointment_reminder`, `assignment_received`, `file_rejected`, `journey_stage_changed`, `journey_closed`, `offer_decided`
**`priority` choices:** `low`, `normal`, `high`, `urgent`
**`status` choices:** `active`, `dismissed`, `resolved`
**`resolution` choices:** `source_cleared`, `dismissed_by_user` (blank while `active`)
**`delivery_channel` choices:** `in_app` (the only value in v1)
**`delivery_state` choices:** `pending`, `delivered`, `failed`
**`generated_by` choices:** `sweep`, `signal`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| recipient | FK → `authenticate.User` | Yes | No | No | `PROTECT`. Who must act. One row per person — a condition affecting three Admins is three rows |
| notification_type | CharField(30) | Yes | No | No | Drives priority, grouping, and iconography. Never business logic |
| priority | CharField(10) | No | No | Yes | Mapped from `notification_type` at creation by `constants.TYPE_PRIORITY`. **Stored, not derived** — re-rating a type later must not silently rewrite what past alerts claimed |
| title | CharField(200) | Yes | No | Yes | Composed from the source record. What happened, in one line |
| body | TextField | No | No | Yes | Why it needs attention and what to do next. Blank when the title says everything |
| source_app | CharField(50) | Yes | No | Yes | The app that owns the record, e.g. `checklists` |
| source_entity_type | CharField(50) | Yes | No | Yes | The record kind, e.g. `checklist_item`. Matches the `audit.AuditEvent.entity_type` vocabulary |
| source_entity_id | UUIDField | No | Yes | Yes | The exact record. Null only for a type that has no single source record — none today |
| source_api_path | CharField(255) | No | No | Yes | Canonical API path of the source, e.g. `/api/v1/checklists/<id>/`. Backend-owned so a client is not guessing routes. Blank when the source has no retrievable endpoint |
| due_at | DateTimeField | No | Yes | Yes | When this becomes urgent, copied from the source deadline. Null for a lifecycle alert. Drives the due-bucket grouping |
| read_at | DateTimeField | No | Yes | Yes | Null means unread. **Orthogonal to `status`** — a read alert is still active work |
| status | CharField(15) | No | No | Yes | Defaults to `active` |
| resolution | CharField(20) | No | No | Yes | Blank while `active` |
| resolved_at | DateTimeField | No | Yes | Yes | Set when `status` leaves `active`, whichever terminal state it enters |
| dismissed_by | FK → `authenticate.User` | No | Yes | No | `SET_NULL`. Set only on a manual dismiss; always equals `recipient` today |
| delivery_channel | CharField(15) | No | No | Yes | `in_app` in v1 |
| delivery_state | CharField(15) | No | No | Yes | `in_app` is `delivered` the moment the row exists |
| delivered_at | DateTimeField | No | Yes | Yes | Equal to `created_at` for `in_app` |
| dedupe_key | CharField(255) | Yes | No | Yes | See the idempotency contract above |
| generated_by | CharField(10) | Yes | No | Yes | The resolve pass only ever touches `sweep` rows — a signal alert records that something happened and has no ongoing condition to re-check |
| created_at | DateTimeField | — | No | Yes | `auto_now_add` |
| updated_at | DateTimeField | — | No | Yes | `auto_now` |

**Validation Rules:**

- `(recipient, dedupe_key)` is unique — constraint `notification_one_per_recipient_key`. This is not a tidiness rule; it is the whole idempotency guarantee, and it lives in the database because the sweep, the signals, the admin, and the shell can all write.
- `status = active` requires `resolution` blank and `resolved_at` null; any terminal status requires both set. Constraint `notification_resolution_matches_status` — the same lifecycle-boolean/timestamp coherence §35 item 15 requires of the policy engine, applied to this app's own denormalized state.
- `priority` is never accepted from a caller. `services.create_notification` maps it from the type.
- Nothing here is user-entered, so §39.2 Unicode normalization has no write path to apply to. Titles and bodies are composed from fields the owning app already normalized on write.
- No `create`, `update`, or `delete` endpoint exists. The only field a client may change is `read_at`, plus a one-way move to `dismissed`.

**Indexes:**

- `(recipient, status, -created_at)` — `notif_feed_idx`. The feed, which is always scoped to one recipient and almost always to `active`.
- `(recipient, read_at)` — `notif_unread_idx`. The bell badge, the single most frequently-run query in the app.
- `(status, due_at)` — `notif_status_due_idx`. The sweep's resolve pass and the due-bucket filter.
- `(source_entity_type, source_entity_id)` — `notif_source_idx`. "Every alert ever raised about this record", which is what makes the retained history usable.
- `dedupe_key` carries an index implicitly through the unique constraint.

**Soft Delete:** N/A — nothing in this table is ever deleted. `dismissed` and `resolved` are terminal states and the row is retained, because `concepts/notifications.txt` requires it in as many words: "preserve the alert history even after the source issue is fixed." A retention policy for very old resolved rows is a future decision and is deliberately not implemented as a silent default.

**Example:**
```json
{
  "id": "5c2b9a41-7e3d-4f18-a0c6-1d8b4e6f2a90",
  "notification_type": "checklist_item_overdue",
  "priority": "high",
  "title": "Overdue: Passport bio page scan",
  "body": "Required for Sita Sharma (Australia — Student Visa). Due 2026-07-18, 6 days ago.",
  "source_app": "checklists",
  "source_entity_type": "checklist_item",
  "source_entity_id": "a91c4f77-2b0e-4c3a-8d15-6f2e9b7a4c81",
  "source_api_path": "/api/v1/checklists/3f8e.../items/a91c4f77-2b0e-4c3a-8d15-6f2e9b7a4c81/",
  "due_at": "2026-07-18T09:00:00Z",
  "due_at_bs": {
    "year": 2083, "month": 4, "day": 2,
    "month_name": "Shrawan",
    "display": "2083 Shrawan 2"
  },
  "due_bucket": "overdue",
  "is_read": false,
  "read_at": null,
  "status": "active",
  "resolution": "",
  "resolved_at": null,
  "delivery_channel": "in_app",
  "delivery_state": "delivered",
  "generated_by": "sweep",
  "created_at": "2026-07-24T02:00:11.421Z"
}
```

`dedupe_key` and `dismissed_by` are stored but not serialized: the first is an internal idempotency detail no client can act on, the second always equals the recipient today and would invite a client to build a "dismissed by X" display that is not yet true of anyone else.

**Cross-App Dependencies:** `authenticate.User` (FK, `PROTECT` on `recipient`, `SET_NULL` on `dismissed_by`). Every other app referenced by a notification is referenced by **id and string only** — `source_app` / `source_entity_type` / `source_entity_id` — never by foreign key. That is deliberate and is the mechanism that keeps this app from becoming a second copy of the business graph: a notification can point at a record in an app that does not exist yet, and deleting nothing anywhere can break this table.

**Security Notes:** A notification body names an applicant and the document they are missing. The own-recipient access rule means that disclosure follows the routing table below rather than any app's general read permission. Nothing in `title` or `body` may carry a token, a file path on disk, or a full document body (§17) — the composers use labels and names the recipient could already see through the source app's own endpoints.

---

## Request/Response Payload Contracts

### FeedSummary

**Purpose:** The bell badge and the feed's grouping headers, in one call. Without it every client must page the whole feed to render a single number.
**Shape:**
```json
{
  "unread": 7,
  "active": 12,
  "by_priority": { "low": 1, "normal": 4, "high": 6, "urgent": 1 },
  "by_due_bucket": { "overdue": 3, "due_soon": 4, "later": 2, "none": 3 }
}
```
**Produced by:** `notifications.selectors.get_feed_summary`
**Consumed by:** `GET /api/v1/notifications/summary/`

Every count in this payload is scoped to the calling user and to `status = active`, except `unread`, which counts unread rows in any status — an alert resolved before it was ever read still deserves to be noticed once.

### SweepReport

**Purpose:** What one run of `sweep_notifications` did. Written to stdout, not to any endpoint.
**Shape:**
```json
{
  "raised": { "checklist_item_overdue": 4, "offer_response_due": 1 },
  "resolved": 2,
  "recipients": 3,
  "dry_run": false
}
```
**Produced by:** `notifications.management.commands.sweep_notifications`
**Consumed by:** an operator, and the cron log

---

## Recipient Routing

Who receives an alert is a data-contract question, not an implementation detail — it decides who sees an applicant's missing-document list. The rule is one function, `services.resolve_recipients`, and one table:

| Source | Recipients |
|---|---|
| `ChecklistItem` | `item.assigned_to`, else `checklist.assigned_to`, else every active Admin |
| `Checklist` | `checklist.assigned_to`, else every active Admin |
| `Offer` (deadline, expiry, decision) | Every active Admin |
| `PassportDetail` | Every active Admin |
| `ApplicantJourney` (stage change, closure) | Every active Admin |
| `UploadedFile` (rejection) | `file.uploaded_by`, **plus** every active Admin |

Two rules apply to every row of that table:

- **The actor is never notified about their own action.** The Admin who rejects a file does not receive an alert telling them it was rejected. Passed as `exclude_actor`.
- **Only active Admins.** A deactivated account (`is_active = False`, which is what `is_blocked` means in `authenticate`) receives nothing; its existing notifications are retained but nothing new is written to a queue nobody reads.

Lead Managers receive alerts only through assignment. This follows the ownership model the rest of the project already has: `checklists` is the only app carrying `assigned_to`, and `applicants`/`applicant_journeys` are deliberately not owner-scoped. The consequence is worth stating plainly — **today most deadline alerts fan out to Admins**, and that will narrow on its own as ownership is introduced elsewhere, with no change to this app.

---

## Generation

### Sweep — `python manage.py sweep_notifications`

Cron-run, not queued: no Celery, no broker, no new infrastructure (§37). Two passes in one command, in one transaction per pass:

1. **Raise.** Iterate the owning apps' existing deadline selectors — `checklists.get_overdue_checklist_items`, `checklists.get_due_soon_checklist_items`, `checklists.get_checklists_with_pending_documents`, `offers.get_offers_awaiting_response`, `applicants.get_expiring_passports`, `reminders.get_due_reminders` — build a dedupe key per row and `get_or_create`. **No query in this app re-implements another app's definition of "overdue."**
2. **Resolve.** The raise pass yields the set of keys that are true right now. Every `active`, `generated_by = sweep` notification whose key is not in that set is moved to `resolved` / `source_cleared`. One `UPDATE`, no per-row re-query.

Idempotency: guaranteed by the unique constraint, not by convention. A second run in the same minute creates nothing and resolves nothing new.
Failure behaviour: a generator that raises is logged and skipped; the other generators still run, and the resolve pass is skipped entirely for the failed generator's types so a transient failure can never mass-resolve live alerts.

### Signals — `notifications/signals.py`

`post_save` receivers on `checklists.Checklist`, `checklists.ChecklistItem`, `uploaded_files.UploadedFile`, `applicant_journeys.ApplicantJourney`, and `offers.Offer`, registered in `apps.py::ready()` (§11), each with a `dispatch_uid`, all deferred to `transaction.on_commit`, all honouring `settings.DISABLE_SIGNALS`.

The dependency runs one way and must keep running one way: `notifications` knows the source apps exist; **no source app ever learns this one does.** A checklist save that succeeds must not fail because an alert could not be written, so every receiver swallows its exceptions, logs them, and records an unsuccessful `audit` event — the same contract `checklists/signals.py` established for inheritance, for the same reason.

For bulk imports, set `DISABLE_SIGNALS = True` and rebuild afterwards with `python manage.py sweep_notifications`. Note that the sweep rebuilds only the deadline types; lifecycle alerts for events that happened during a signal-disabled import are not reconstructible, and should not be — nobody needs to be told about a stage change that happened during an import three days ago.

---

## Cross-App Dependencies

**This app references:**

| App | Kind | Why |
|---|---|---|
| `authenticate` | FK + selector | `recipient`/`dismissed_by`; `get_active_admins()` for the fan-out |
| `checklists` | selectors + signal | Due/overdue items, pending-document checklists, assignment events |
| `offers` | selector + signal | Response deadlines, decisions |
| `applicants` | selector | Passport expiry |
| `reminders` | selector | Staff-set follow-ups whose date has arrived — the first sweep source whose rows exist only to be swept |
| `uploaded_files` | signal | Rejections |
| `applicant_journeys` | signal | Stage changes and closures |
| `audit` | service | Failure events from signal receivers |
| `core` | framework | `BaseModel`, response envelope, pagination, `querying.narrow_to_window`, `nepal.calendar` |

**Referenced by:** nothing. No app imports `notifications`, and none should — that is what keeps an alerting failure from ever becoming a business-write failure.

**Two selectors were added to other apps for this build**, because §3 puts a query in the app that owns the rows:

- `authenticate.selectors.get_active_admins()` — active users with Admin authority.
- `checklists.selectors.get_checklists_with_pending_documents()` — active checklists holding unresolved `document`-type items with no due date, which the existing due/overdue selectors structurally cannot see.

---

## Soft Delete

N/A — no model in this app is ever deleted or soft-deleted. `Notification.status` reaching `dismissed` or `resolved` is the terminal state, and the row is retained permanently as alert history.
