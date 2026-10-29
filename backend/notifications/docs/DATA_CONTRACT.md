# Data Contract — Notifications

**Owner app:** `notifications`
**Version:** 1.2.0
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the user-facing alert stream — one row per recipient per thing that needs attention — and, since 2026-10-29, each user's preferences about what they are told. It owns **no business state whatsoever**: `checklists` owns what is outstanding, `offers` owns response deadlines, `applicants` owns passport and language-test expiry, applicant status and assignment, `leads` owns the enquiry lifecycle, `documents` owns document readiness, `uploaded_files` owns file rejections, and `applicant_journeys` owns lifecycle stage. This app records that someone was told, when, and whether they have dealt with it. Every notification points at a source record and never replaces it.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial contract — one model, dedupe-key idempotency, sweep + signal generation, in-app delivery only |
| 1.1.0 | 2026-08-17 | AI (Claude) | Added the `custom_reminder` sweep type (staff-set follow-up reminders from the new `reminders` app): type choice, `normal` priority, dedupe discriminator (due date), sweep generator + `reminders` cross-app row. Additive — no existing shape changed |
| 1.2.0 | 2026-10-29 | AI (Claude Opus 5.5) | Phase 5 (frontend updates.md §4). Ten event-driven types raised from `core.events` domain events (`lead_*`, `applicant_*`, `visit_note_added`, `document_ready`), and the sweep now generates `test_score_expiring`. Derived `category` vocabulary (`TYPE_CATEGORY`, never stored). `Notification` gains `applicant_id` and `payload` (migration `0003_categories_payload_preferences`). New model §2 `NotificationPreference` (mute by category, assigned-only) applied at write time in `services.dispatch`. `FeedSummary` gains `by_category`; new `ReadAllRequest` and `NotificationPreferences` payloads. Recipient Routing rewritten — applicant-related alerts now also reach the applicant's assignee. **First deletion in the app:** the sweep's retention purge hard-deletes old event alerts and resolved deadline alerts, so `Soft Delete` changes from "never deleted". Corrected a stale reference to a non-existent `services.resolve_recipients` and the `SweepReport` shape, which listed a `recipients` figure the command never reported |

---

## Deliberate Deviations

`concepts/notifications.txt` leaves five questions open and names two source apps that do not exist. Each departure below is a decision taken with the user before implementation, not an oversight:

- **`title` and `body` are single English fields.** They are sentences this system composes from a source record — "Passport expires in 21 days" — not names.
- **The feed is own-recipient only — stricter than any other app in this project.** Every other app lets an Admin read everything. Here an Admin cannot read another user's notifications over the API, because a notification is one person's work queue rather than a record about the business. It costs an Admin nothing operationally — everything a notification points at is readable through the source app's own endpoints — and it removes the ability to read somebody's inbox without leaving a trace. Cross-user inspection stays in Django admin, where it is attributable. Fetching another user's notification by id returns **404, not 403**: a 403 would confirm the id exists on somebody else's feed. See `API.md` §1.
- **Two type values ship with no generator.** `missing_information` and `appointment_reminder` are named in the concept file but have no source: no app defines what "required information" is, and the `appointments` app does not exist. The values are declared so the frontend gets the whole vocabulary at once and so adding a generator later is not a schema change. Nothing produces them today. (`test_score_expiring` was the third until 2026-10-29, when `applicants` gained language tests and the sweep began raising it.)
- **The concept's `expired` lifecycle state is folded into `resolved`.** The concept lists "resolved, dismissed, or expired" as terminal states. `expired` and `resolved` would be written by the same code path for the same reason — the source condition stopped being true — so a separate value would only ever be a second name for one fact. `resolution = source_cleared` carries the distinction where it matters.
- **No `snooze`.** The concept lists it as optional. Deferring an alert without acting on it is the behaviour that makes an inbox stop being read, and the escalation mechanism below already handles "not now, but soon." The per-user **mute** the concept's open questions also raised *was* built on 2026-10-29 (§2 `NotificationPreference`) — muting is a standing choice about a whole category, which is a different act from deferring one alert.
- **`category` is derived, never stored.** The frontend groups, counts, and mutes by a coarser vocabulary than `notification_type` ("stop telling me about leads" is one decision, not four). `constants.TYPE_CATEGORY` maps every type to exactly one category and is applied at read time and at write time; no column holds it, so regrouping a type later rewrites no rows.
- **Preferences are applied at write time, not read time.** A muted alert is never written, rather than written and hidden. That keeps the badge, the feed, and `read-all` in agreement without a preference join on every read — at the cost that unmuting a category does not bring back what was skipped while it was muted.
- **Old rows are deleted (2026-10-29).** The original contract retained every row forever. The frontend asked for a retention window; the sweep now hard-deletes event alerts and resolved deadline alerts older than 90 days. Dismissed and active deadline alerts are kept regardless of age — see `Soft Delete`.

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
| `test_score_expiring` | `test_score_expiring:language_test:<id>:<expiry date>` — a retake with a new expiry raises a fresh alert; removing the test, or replacing it with a later expiry beyond the horizon, resolves the old one on the next sweep |
| `lead_created` / `lead_converted` / `lead_deleted` / `lead_restored` | `<type>:lead:<lead id>:<event id>` |
| `applicant_status_changed` / `applicant_restored` / `applicant_assigned` / `applicant_unassigned` | `<type>:applicant:<applicant id>:<event id>` |
| `visit_note_added` | `visit_note_added:<lead\|applicant>:<owner id>:<event id>` |
| `document_ready` | `document_ready:document:<id>:<event id>` |

**Event alerts use the domain event's own `event_id` as the discriminator** (2026-10-29). Each `core.events.emit` call mints a fresh UUID, so a lead deleted, restored, and deleted again is three alerts — three facts — rather than one key colliding with itself. The flip side: unlike the stage-keyed journey alerts, nothing here deduplicates two *different* events that happen to say the same thing.

**Known Limitations of this scheme**, stated rather than discovered later:

- `missing_documents` carries no discriminator, so once it is resolved for a checklist it is never raised again for that checklist even if a new document requirement is added. Putting the pending count in the key was considered and rejected: collecting one of five documents would resolve the old alert and raise a new one on every sweep, which is the noise the whole design exists to prevent.
- `journey_stage_changed` will not re-alert on a move *back* to a stage the journey already held.
- `file_rejected` will not re-alert if a file is rejected, verified, and rejected again. In practice a corrected file is a new `UploadedFile` row (that app versions rather than overwrites), so the same key never recurs.

---

## 1. Notification

**Purpose:** One alert, for one recipient, about one source record. Created only by this app's sweep command or its signal receivers — there is no create endpoint, and no other app calls in.
**Table:** `notifications_notification`

**`notification_type` choices:** `checklist_item_due`, `checklist_item_overdue`, `missing_documents`, `offer_response_due`, `offer_expired`, `passport_expiring`, `custom_reminder`, `assignment_received`, `file_rejected`, `journey_stage_changed`, `journey_closed`, `offer_decided`, `lead_created`, `lead_converted`, `lead_deleted`, `lead_restored`, `applicant_status_changed`, `applicant_restored`, `applicant_assigned`, `applicant_unassigned`, `visit_note_added`, `document_ready`, `test_score_expiring`, `missing_information`, `appointment_reminder`
**`category` (derived, not a column) choices:** `lead`, `applicant_status`, `journey`, `assignment`, `notes`, `follow_up`, `documents`, `checklist`, `offer`, `file`, `expiry`
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
| applicant_id | UUIDField | No | Yes | Yes | The applicant the alert is about, when the builder knows one (2026-10-29). A bare UUID, not an FK, for the same reason as `source_entity_id`. Powers `?applicant_id=` and the `assigned_only` preference. Indexed. **Null on every row raised before 2026-10-29** (no backfill) and on alerts with no applicant — see the payload table below for which types set it |
| payload | JSONField (object) | No | No | Yes | Structured, non-sensitive facts for the client to render, keyed by type (table below). Defaults to `{}`. Never identity numbers, scores, note text, or delete reasons |
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
- `priority` is never accepted from a caller. `services.dispatch` maps it from the type.
- `payload` holds only plain, non-sensitive values (ids, enum strings). The builders in `services.py` are the only writers, and none copies a score, an identity number, a note body, or a delete reason — the feed is the one place a record's details are copied out of the app that owns them.
- Nothing here is user-entered, so §39.2 Unicode normalization has no write path to apply to. Titles and bodies are composed from fields the owning app already normalized on write.
- No `create`, `update`, or `delete` endpoint exists. The only field a client may change is `read_at`, plus a one-way move to `dismissed`.

**Indexes:**

- `(recipient, status, -created_at)` — `notif_feed_idx`. The feed, which is always scoped to one recipient and almost always to `active`.
- `(recipient, read_at)` — `notif_unread_idx`. The bell badge, the single most frequently-run query in the app.
- `(status, due_at)` — `notif_status_due_idx`. The sweep's resolve pass and the due-bucket filter.
- `(source_entity_type, source_entity_id)` — `notif_source_idx`. "Every alert ever raised about this record", which is what makes the retained history usable.
- `dedupe_key` carries an index implicitly through the unique constraint.
- `applicant_id` — single-column `db_index` (2026-10-29). Supports `?applicant_id=` on the feed, which is always also recipient-scoped.
- The retention purge (`selectors.get_purgeable`) filters on `created_at` plus `generated_by`/`status`; it runs once a night and needed no new index.

**Soft Delete:** N/A — there is no soft delete; rows are **hard-deleted by retention** (2026-10-29). `dismissed` and `resolved` remain terminal states, and the row is retained after either — until the sweep's purge removes it. The purge deletes rows older than `--retention-days` (default 90) that are either `generated_by = signal` (any status) or `generated_by = sweep` with `status = resolved`. **Dismissed and active sweep alerts are never purged, however old**: their row is what holds the dedupe key, and deleting it would let the next sweep raise the same condition again. See the top-level `Soft Delete` section.

**Example:**
```json
{
  "id": "5c2b9a41-7e3d-4f18-a0c6-1d8b4e6f2a90",
  "notification_type": "checklist_item_overdue",
  "category": "checklist",
  "priority": "high",
  "title": "Overdue: Passport bio page scan",
  "body": "Required for Sita Sharma (Australia — Student Visa). Due 2026-07-18, 6 days ago.",
  "applicant_id": null,
  "payload": {},
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

`dedupe_key` and `dismissed_by` are stored but not serialized: the first is an internal idempotency detail no client can act on, the second always equals the recipient today and would invite a client to build a "dismissed by X" display that is not yet true of anyone else. `category` is serialized but not stored — it is `TYPE_CATEGORY[notification_type]`.

**Category mapping** (`constants.TYPE_CATEGORY` — every type maps to exactly one category; a test asserts none is missing):

| `category` | `notification_type` values |
|---|---|
| `lead` | `lead_created`, `lead_converted`, `lead_deleted`, `lead_restored` |
| `applicant_status` | `applicant_status_changed`, `applicant_restored` |
| `journey` | `journey_stage_changed`, `journey_closed` |
| `assignment` | `assignment_received`, `applicant_assigned`, `applicant_unassigned` |
| `notes` | `visit_note_added` |
| `follow_up` | `custom_reminder`, `appointment_reminder` |
| `documents` | `document_ready` |
| `checklist` | `checklist_item_due`, `checklist_item_overdue`, `missing_documents`, `missing_information` |
| `offer` | `offer_response_due`, `offer_expired`, `offer_decided` |
| `file` | `file_rejected` |
| `expiry` | `passport_expiring`, `test_score_expiring` |

**Priority, source, `applicant_id`, and `payload` by the 2026-10-29 types** (the older types' source triples are unchanged; of them, `passport_expiring`, `custom_reminder` for an applicant reminder, and `journey_stage_changed`/`journey_closed` now also set `applicant_id`, and the journey types carry `payload: { stage }`):

| `notification_type` | Priority | `source_app` / `source_entity_type` | `applicant_id` set? | `payload` |
|---|---|---|---|---|
| `lead_created` | `normal` | `leads` / `lead` | No | `{}` |
| `lead_converted` | `normal` | `leads` / `lead` | Yes — the new applicant | `{ applicant_id }` |
| `lead_deleted` | `normal` | `leads` / `lead` | No | `{}` |
| `lead_restored` | `low` | `leads` / `lead` | No | `{}` |
| `applicant_status_changed` | `normal` | `applicants` / `applicant` | Yes | `{ from, to, originating_lead_id }` — `originating_lead_id` null when the applicant did not come from a lead |
| `applicant_restored` | `normal` | `applicants` / `applicant` | Yes | `{ from, to, originating_lead_id }` — `from` is always `archived` |
| `applicant_assigned` | `normal` | `applicants` / `applicant` | Yes | `{}` |
| `applicant_unassigned` | `low` | `applicants` / `applicant` | Yes | `{}` |
| `visit_note_added` | `low` | `leads` / `lead` or `applicants` / `applicant` | Only on an applicant note | `{ note_id }` |
| `document_ready` | `normal` | `documents` / `document` | When the document has an applicant | `{ family }` |
| `test_score_expiring` | `high` | `applicants` / `language_test` | Yes | `{ test_type }` |

`source_entity_type` gains four values: `lead`, `applicant`, `document`, `language_test`. A `test_score_expiring` alert's `source_api_path` points at the applicant (a language test has no endpoint of its own), as a passport alert's does. Titles and bodies name the applicant or lead and who acted; never a score, note text, or delete reason.

**Cross-App Dependencies:** `authenticate.User` (FK, `PROTECT` on `recipient`, `SET_NULL` on `dismissed_by`). Every other app referenced by a notification is referenced by **id and string only** — `source_app` / `source_entity_type` / `source_entity_id`, and `applicant_id` — never by foreign key. That is deliberate and is the mechanism that keeps this app from becoming a second copy of the business graph: a notification can point at a record in an app that does not exist yet, and deleting nothing anywhere can break this table.

**Security Notes:** A notification body names an applicant and the document they are missing. The own-recipient access rule means that disclosure follows the routing table below rather than any app's general read permission. Nothing in `title` or `body` may carry a token, a file path on disk, or a full document body (§17) — the composers use labels and names the recipient could already see through the source app's own endpoints. The same applies to `payload` (2026-10-29): ids and enum strings only — never a test score, a passport number, a visit note's text, or a delete reason — which is why the payload is **not role-projected**: there is nothing in it to project. `document_ready` alerts are routed to Admins only because documents themselves are Admin-only.

---

## 2. NotificationPreference

**Purpose:** What one user has chosen not to be told (2026-10-29). At most one row per user, created lazily by the first `PATCH /api/v1/notifications/preferences/`; a user with no row has the defaults — every category on, `assigned_only` off. Read and written only for the calling user.
**Table:** `notifications_preference`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key. Never exposed — the resource is addressed as "mine", not by id |
| user | OneToOne → `authenticate.User` | Yes | No | No | `PROTECT`. Users are deactivated, never deleted, so it never fires in practice |
| muted_categories | JSONField (list of strings) | No | No | No | `NotificationCategory` values this user does not want in-app. Default `[]`. **Stored in vocabulary order** (the order of the `category` choices in §1), whatever order the client sent, so the stored value is stable |
| assigned_only | BooleanField | No | No | No | Default `false`. When `true`, an alert that names an applicant is delivered only if this user is that applicant's assignee. Alerts with no `applicant_id` are unaffected |
| created_at | DateTimeField | — | No | Yes | `auto_now_add` |
| updated_at | DateTimeField | — | No | Yes | `auto_now` |

**Validation Rules:**

- Every entry in `muted_categories` is a `NotificationCategory` value; an unknown category in a `PATCH` is rejected with `VALIDATION_ERROR` (400) before anything is written.
- A `PATCH` changes only what it sends: categories left out keep their setting, and `assigned_only` is untouched unless supplied. Implemented in `services.update_preferences`.
- Nothing here is free text, so §39.2 normalization has nothing to apply to.

**How it is applied:** inside `services.dispatch`, the single write path, before any row is created — one query for the whole recipient list. A recipient is dropped when the alert's category is in `muted_categories`, or when `assigned_only` is on, the alert has an `applicant_id`, and the alert's assignee is not this recipient. A dropped recipient gets **no row**: muting is applied at write time, so changing preferences neither hides nor deletes alerts already in the feed, and unmuting does not bring back what was skipped.

**Indexes:** the unique index implied by the `OneToOne` on `user`. No other.

**Soft Delete:** N/A — the row is never deleted; resetting to defaults is a `PATCH` that turns everything back on.

**Example (stored):**
```json
{
  "user": "7d1e2f3a-4b5c-4d6e-8f90-a1b2c3d4e5f6",
  "muted_categories": ["lead", "notes"],
  "assigned_only": true
}
```

**Cross-App Dependencies:** `authenticate.User` (OneToOne, `PROTECT`).

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
  "by_due_bucket": { "overdue": 3, "due_soon": 4, "later": 2, "none": 3 },
  "by_category": {
    "lead": 2, "applicant_status": 1, "journey": 0, "assignment": 1, "notes": 0, "follow_up": 0,
    "documents": 0, "checklist": 2, "offer": 1, "file": 0, "expiry": 0
  }
}
```
**Produced by:** `notifications.selectors.get_feed_summary`
**Consumed by:** `GET /api/v1/notifications/summary/`

Every count in this payload is scoped to the calling user and to `status = active`, except `unread` and `by_category`, which count unread rows in any status — an alert resolved before it was ever read still deserves to be noticed once. `by_category` (2026-10-29) is zero-filled across all eleven categories, and `unread` is exactly the sum of its values.

### ReadAllRequest

**Purpose:** Optional body of `POST /api/v1/notifications/read-all/` (2026-10-29) — narrows the clear to one category, for a per-tab "mark all read".
**Shape:**
```json
{ "category": "lead" }
```
**Fields:** `category` — optional, one `NotificationCategory` value. Absent, empty string, or no body at all clears every unread notification, as before. An unknown value is `VALIDATION_ERROR` (400).
**Produced by:** the client. **Consumed by:** `notifications.serializers.ReadAllSerializer` → `services.mark_all_read`.

### NotificationPreferences

**Purpose:** The read and write shape of `GET`/`PATCH /api/v1/notifications/preferences/` (2026-10-29). A projection of §2 `NotificationPreference`, not the row: categories are presented as per-category switches rather than a muted list, so a second delivery channel can be added inside each category object without a breaking change.
**Shape (response — always complete):**
```json
{
  "categories": {
    "lead": { "in_app": false },
    "applicant_status": { "in_app": true },
    "journey": { "in_app": true },
    "assignment": { "in_app": true },
    "notes": { "in_app": false },
    "follow_up": { "in_app": true },
    "documents": { "in_app": true },
    "checklist": { "in_app": true },
    "offer": { "in_app": true },
    "file": { "in_app": true },
    "expiry": { "in_app": true }
  },
  "assigned_only": true
}
```
**Request (`PATCH`):** any subset — `categories` with any subset of category keys, each value `{ "in_app": bool }`, and/or `assigned_only: bool`. Both keys optional; an empty body changes nothing (but does create the row on first use). An unknown category key is `VALIDATION_ERROR` (400) under `details.categories`.
**Produced by:** `notifications.selectors.get_preferences` (defaults when no row exists). **Consumed by:** `notifications.serializers.NotificationPreferenceSerializer` → `services.update_preferences`.

### SweepReport

**Purpose:** What one run of `sweep_notifications` did. Written to stdout as text lines, not to any endpoint — one line per generator (`<type>: N raised (M conditions true)`) and a final `Sweep complete: X raised, Y resolved, Z purged.` (prefixed `[dry run] ` under `--dry-run`). The logical content:
**Shape:**
```json
{
  "raised": { "checklist_item_overdue": 4, "offer_response_due": 1 },
  "resolved": 2,
  "purged": 37,
  "dry_run": false
}
```
`purged` is always `0` under `--dry-run`, under `--limit`, and with `--retention-days 0`.
**Produced by:** `notifications.management.commands.sweep_notifications`
**Consumed by:** an operator, and the cron log

---

## Recipient Routing

Who receives an alert is a data-contract question, not an implementation detail — it decides who sees an applicant's missing-document list. The rules live in one region of `services.py` — the `recipients_for_*` functions — plus the event handlers in `signals.py`, and in one table:

| Source | Recipients |
|---|---|
| `ChecklistItem` | `item.assigned_to`, else `checklist.assigned_to`, else every active Admin |
| `Checklist` | `checklist.assigned_to`, else every active Admin |
| Checklist / item assignment (`assignment_received`) | The new assignee only |
| `Offer` (deadline, expiry, decision) | Every active Admin |
| `PassportDetail` (`passport_expiring`) | Every active Admin, **plus** the applicant's assignee when one is set (2026-10-29) |
| `ApplicantLanguageTest` (`test_score_expiring`) | Every active Admin, plus the applicant's assignee when one is set |
| `ApplicantJourney` (stage change, closure) | Every active Admin, plus the applicant's assignee when one is set (2026-10-29) |
| `Reminder` (`custom_reminder`) | Applicant reminder: every active Admin plus the applicant's assignee when set (2026-10-29). Client reminder: every active Admin |
| `UploadedFile` (rejection) | `file.uploaded_by`, **plus** every active Admin |
| `lead.created` | Every active Admin |
| `lead.converted` / `lead.deleted` / `lead.restored` | The lead's owner (`created_by`) **plus** every active Admin |
| `lead.note_added` (visit notes only) | The lead's owner |
| `applicant.status_changed` / `applicant.restored` | Assigned: the assignee plus every active Admin. **Unassigned: every active Admin and every active Lead Manager** |
| `applicant.note_added` (visit notes only) | Assigned: the assignee only. Unassigned: every active Admin and every active Lead Manager |
| `applicant.assigned` | `applicant_assigned` to the new assignee; `applicant_unassigned` to the previous assignee |
| `document.ready` | Every active Admin — never a Lead Manager, because documents are Admin-only |

Rules that apply across that table:

- **The actor is never notified about their own action.** The Admin who rejects a file does not receive an alert telling them it was rejected; a Lead Manager who takes an applicant themselves gets no `applicant_assigned`. Passed as `exclude_actor` and applied by `_finalize`. **Exception:** the checklist/item `assignment_received` receiver dispatches straight to the assignee without `_finalize`, so self-assignment does alert — see Known Limitations below.
- **Only active accounts.** A deactivated account (`is_active = False`, which is what `is_blocked` means in `authenticate`) receives nothing; its existing notifications are retained but nothing new is written to a queue nobody reads. The same `assignment_received` exception applies.
- **The two applicant fallbacks differ on purpose.** For the new event alerts (status, restore, visit notes), an unassigned applicant fans out to every Admin **and Lead Manager** (`authenticate.get_active_lead_actors`) — somebody on the team has to pick it up. The older applicant alerts (journeys, passports, language tests, applicant reminders) gained the assignee when one is set but, when unassigned, stay **Admin-only** with no Lead Manager fallback — the product owner's decision, so that existing Lead Manager inboxes did not suddenly widen.
- **Preferences are applied last**, after routing, in `services.dispatch` — see §2.

Lead Managers receive alerts by assignment (checklist work and, since 2026-10-29, applicants), by owning a lead, and through the unassigned-applicant fallback above. Offers carry no owner anywhere in this project, so offer alerts still fan out to Admins only.

**Known Limitations of routing:**

- `assignment_received` (checklists) bypasses actor exclusion and the inactive-account filter — it is the one receiver that predates `_finalize` being applied to targeted alerts.
- `applicant_assigned` and `applicant_unassigned` always pass `assigned_only`: each is matched against its own recipient (the person gaining or losing the applicant), never against the applicant's current assignee.

---

## Generation

### Sweep — `python manage.py sweep_notifications`

Cron-run, not queued: no Celery, no broker, no new infrastructure (§37). Three passes in one command — raise, resolve, and (since 2026-10-29) purge:

1. **Raise.** Iterate the owning apps' existing deadline selectors — `checklists.get_overdue_checklist_items`, `checklists.get_due_soon_checklist_items`, `checklists.get_checklists_with_pending_documents`, `offers.get_offers_awaiting_response`, `applicants.get_expiring_passports`, `applicants.get_expiring_language_tests` (2026-10-29: tests whose `expiry_date` is on or before Nepal-today + `--test-score-horizon-days`, default 90, already-expired included, archived applicants excluded), `reminders.get_due_reminders` — build a dedupe key per row and `get_or_create`. **No query in this app re-implements another app's definition of "overdue."**
2. **Resolve.** The raise pass yields the set of keys that are true right now. Every `active`, `generated_by = sweep` notification whose key is not in that set is moved to `resolved` / `source_cleared`. One `UPDATE`, no per-row re-query.
3. **Purge (2026-10-29).** `services.purge_expired` deletes rows older than `--retention-days` (default 90; `0` disables) that are `generated_by = signal` in any status, or `generated_by = sweep` and `resolved`. One `DELETE`. Runs only on a full writing run — skipped under `--dry-run` and `--limit`. Dismissed and active sweep rows are never purged, because their dedupe key is what stops the condition being raised again.

Idempotency: guaranteed by the unique constraint, not by convention. A second run in the same minute creates nothing and resolves nothing new.
Failure behaviour: a generator that raises is logged and skipped; the other generators still run, and the resolve pass is skipped entirely for the failed generator's types so a transient failure can never mass-resolve live alerts.

### Signals — `notifications/signals.py`

`post_save` receivers on `checklists.Checklist`, `checklists.ChecklistItem`, `uploaded_files.UploadedFile`, `applicant_journeys.ApplicantJourney`, and `offers.Offer`, registered in `apps.py::ready()` (§11), each with a `dispatch_uid`, all deferred to `transaction.on_commit`, all honouring `settings.DISABLE_SIGNALS`.

**Domain events (2026-10-29).** One more receiver, `on_domain_event` (`dispatch_uid = notifications_domain_event`), listens on `core.events.domain_event`. `leads`, `applicants`, and `documents` call `core.events.emit` from their services with the acting user, and `emit` itself defers the send to `transaction.on_commit` — so the handler runs directly, after commit, **synchronously in the same process** (no queue, no Celery). Events handled: `lead.created`, `lead.converted`, `lead.deleted`, `lead.restored`, `lead.note_added`, `applicant.status_changed`, `applicant.restored`, `applicant.assigned`, `applicant.note_added`, `document.ready`; any other event name is ignored. `*.note_added` raises an alert only for `category = visit`; `document.ready` is emitted only by a status change to `ready`. Each handler re-reads the record by id (the event carries ids, never instances) and runs inside `_safely`, so a failure is logged and audited via `record_generation_failure` and never reaches the source write. `post_save` could not be used here because it cannot say *who* saved a row, and "never notify someone of their own action" needs exactly that.

The dependency runs one way and must keep running one way: `notifications` knows the source apps exist; **no source app ever learns this one does.** A checklist save that succeeds must not fail because an alert could not be written, so every receiver swallows its exceptions, logs them, and records an unsuccessful `audit` event — the same contract `checklists/signals.py` established for inheritance, for the same reason.

For bulk imports, set `DISABLE_SIGNALS = True` (which also silences `core.events.emit`) and rebuild afterwards with `python manage.py sweep_notifications`. Note that the sweep rebuilds only the deadline types; lifecycle alerts for events that happened during a signal-disabled import are not reconstructible, and should not be — nobody needs to be told about a stage change that happened during an import three days ago.

---

## Cross-App Dependencies

**This app references:**

| App | Kind | Why |
|---|---|---|
| `authenticate` | FK + selector | `recipient`/`dismissed_by`, `NotificationPreference.user`; `get_active_admins()` for the Admin fan-out; `get_active_lead_actors()` for the unassigned-applicant fallback; `get_active_user_by_id()` to resolve the assignees named in an `applicant.assigned` event |
| `checklists` | selectors + signal | Due/overdue items, pending-document checklists, assignment events |
| `offers` | selector + signal | Response deadlines, decisions |
| `applicants` | selector + model read + domain event | Passport and language-test expiry (`get_expiring_passports`, `get_expiring_language_tests`); re-reads `Applicant` (with `assigned_to`, `originating_lead`) for event alerts; listens to `applicant.*` events |
| `leads` | model read + domain event | Re-reads `Lead` (with `created_by`) for `lead.*` events and lead visit notes |
| `documents` | model read + domain event | Re-reads `Document` for `document.ready` |
| `reminders` | selector | Staff-set follow-ups whose date has arrived — the first sweep source whose rows exist only to be swept |
| `uploaded_files` | signal | Rejections |
| `applicant_journeys` | signal | Stage changes and closures |
| `audit` | service | Failure events from signal receivers |
| `core` | framework + signal | `BaseModel`, response envelope, pagination, `querying.narrow_to_window`, `nepal.calendar`, `constants.NoteCategory`; `events.domain_event`, the post-commit signal the domain-event receiver listens on |

**Referenced by:** nothing. No app imports `notifications`, and none should — that is what keeps an alerting failure from ever becoming a business-write failure.

**Selectors added to other apps for this app**, because §3 puts a query in the app that owns the rows:

- `authenticate.selectors.get_active_admins()` — active users with Admin authority.
- `checklists.selectors.get_checklists_with_pending_documents()` — active checklists holding unresolved `document`-type items with no due date, which the existing due/overdue selectors structurally cannot see.
- `authenticate.selectors.get_active_lead_actors()` (2026-10-29) — every active Admin and Lead Manager, the unassigned-applicant fallback.
- `applicants.selectors.get_expiring_language_tests()` (2026-10-29) — the `test_score_expiring` source.

The source apps that emit domain events (`leads`, `applicants`, `documents`) do not import this app; they call `core.events.emit` and do not know who listens.

---

## Soft Delete

N/A — no model in this app is soft-deleted. **`Notification` rows are hard-deleted by retention** (2026-10-29): `sweep_notifications` purges rows older than `--retention-days` (default 90) that are event alerts (`generated_by = signal`, any status) or resolved deadline alerts (`generated_by = sweep`, `status = resolved`). Dismissed and active deadline alerts are kept indefinitely, because their row holds the dedupe key that stops the sweep raising the same condition again. There is no archive and no undo: purged history is gone, and `audit` keeps only dismissals and generator failures, not the alerts themselves. `NotificationPreference` rows are never deleted.
