# Integration — Notifications

**Owner app:** `notifications`
**Version:** 1.2.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial integration contract for the seven endpoints |
| 1.0.1 | 2026-07-24 | AI (Claude Opus 4.8) | Corrections from the §19.5 consumer-contract review, which read only this file and the project-level one. Two code defects it exposed are fixed: the feed filter `type` is now `notification_type` (the one parameter of twelve that did not match its field), and a malformed `?fiscal_year=` returned **500** rather than 400. Added to the contract: **the lifecycle table** — the review found the sweep's `active` → `resolved`/`source_cleared` transition, the module's central event, was documented only by the existence of an enum value; **the source-triple table**, since `source_app` and `source_entity_type` were exposed as both filter and payload with no value set anywhere; worked `400` and `404` bodies; the deduplication guarantee (one alert per condition, not one per night); date-parameter formats and timezone; `405`/trailing-slash/page-past-end behaviour; what each produced type actually means; and the dismissed-but-unread state. Corrected: "suppresses permanently" contradicting the escalation note two lines below it, and the badge recommendation, which paired `unread` with a `?status=active` inbox without saying they count different populations. §9 gained the missing ordering parameter — ranked first, since an inbox that cannot sort by priority buries its own urgent rows — plus search, retention, polling cost, and the absence of any lead-follow-up alert |
| 1.1.0 | 2026-08-17 | AI (Claude) | New `custom_reminder` type in the vocabulary (§5) and a `reminders` row in §2 — the nightly sweep now raises staff-set follow-up reminders to every active Admin. Additive; no endpoint changed |
| 1.2.0 | 2026-10-29 | AI (Claude Opus 5.5) | Phase 5 (frontend updates.md §4). Ten event-driven types (`lead_*`, `applicant_*`, `visit_note_added`, `document_ready`) raised from other modules' events, and `test_score_expiring` is now produced. New derived `category` vocabulary (§5) with its full type mapping. `Notification` gains `category`, `applicant_id`, `payload` (§4, with a per-type payload table). Feed filters `?category=a,b` and `?applicant_id=`; `FeedSummary.by_category`; optional `{ category }` body on `read-all/`. New resource `NotificationPreferences` and two endpoints, `GET`/`PATCH /preferences/` (`notifications.preference.read`, `notifications.preference.update`). §2 gains `leads` and `documents` and the domain-event signal. Routing summary added: applicant-related alerts now reach the applicant's assignee. **Retention:** event alerts and resolved deadline alerts older than 90 days are deleted. §8 gains per-category tabs and preferences flows; §9 drops the "leads produces no notifications" and "no per-user mute" gaps and adds delivery timing, null `applicant_id` on older rows, retention loss, the checklist-assignment routing exception, and the frontend asks that were declined (cursor pagination, `unread-count/`, SSE, a `case_journey` category) |

---

## 1. Module

- **Name:** Notifications — the in-app alert stream. It turns deadlines and lifecycle events in the other modules into a per-person inbox: what needs attention, why, and which record to open next — and lets each person choose which categories they are told about. It owns **no business state** — every alert points at a record another module owns.
- **Base path:** `/api/v1/notifications/`
- **Auth:** Every endpoint requires a JWT bearer token. Admin and Lead Manager may reach every endpoint; Superadmin is refused on all nine. **Every endpoint operates on the calling user's own notifications and own preferences only** — there is no way to read or act on another user's feed or preferences through this API, for any authority. See §3.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework + FK + service call | Issues the bearer token; supplies the recipient and the preference owner; `get_active_admins()` is the Admin fan-out; `get_active_lead_actors()` is the every-Admin-and-Lead-Manager fallback for an unassigned applicant; `get_active_user_by_id()` resolves the assignees named in an applicant assignment | Every endpoint returns 401. With no active Admin account, offer alerts — and passport, language-test, and journey alerts about unassigned applicants — are raised for nobody and silently vanish |
| `checklists` | service call + **signal** | The overdue, due-soon, and missing-document alerts read that module's own selectors; assignment alerts listen on its saves | Those four alert types stop being produced. The feed still works and still serves everything else |
| `offers` | service call + **signal** | Response-deadline and expiry alerts read `get_offers_awaiting_response`; decision alerts listen on offer saves | `offer_response_due`, `offer_expired`, and `offer_decided` stop being produced |
| `applicants` | service call + **signal** | Passport-expiry and language-test-expiry alerts read `get_expiring_passports` and `get_expiring_language_tests`; status, restore, assignment, and visit-note alerts listen to its domain events; the applicant's assignee is read to route applicant-related alerts | `passport_expiring`, `test_score_expiring`, `applicant_*`, and applicant `visit_note_added` stop being produced, and applicant alerts lose their assignee recipient |
| `leads` | **signal** | `lead_created`, `lead_converted`, `lead_deleted`, `lead_restored`, and lead `visit_note_added` listen to its domain events; the lead's owner is read for routing | Those alert types stop being produced |
| `documents` | **signal** | `document_ready` listens to its domain event | `document_ready` stops being produced |
| `reminders` | service call | `custom_reminder` alerts read `get_due_reminders` — staff-set follow-ups due today or earlier, raised to every active Admin plus, for an applicant reminder, the applicant's assignee | `custom_reminder` stops being produced; a failing generator withholds its type from the resolve pass, so existing reminder alerts freeze rather than mass-resolve |
| `uploaded_files` | **signal** | Rejection alerts listen on file saves | `file_rejected` stops being produced |
| `applicant_journeys` | **signal** | Stage-change and closure alerts listen on journey saves | `journey_stage_changed` and `journey_closed` stop being produced |
| `audit` | service call | Records dismissals and generator failures | Dismissal still works, but nothing records who closed what, and a broken generator becomes indistinguishable from a quiet night |
| `core` | framework + **signal** | Response envelope, pagination, date-window resolution, Bikram Sambat rendering; the post-commit domain-event signal (`core.events`) that `leads`, `applicants`, and `documents` raise and this module listens to | Responses lose the `{ success, message, data, meta }` envelope; errors return raw DRF bodies. Without the event signal, every lead, applicant, visit-note, and document alert stops |

**Two notes for consumers, both easy to get wrong from outside:**

- **Every dependency above runs one way, and none is visible from the other side.** No module knows this one exists. A client that completes a checklist item will not see any mention of a notification in the checklist response — the alert is resolved by the next nightly sweep, and the client must ask this module to see that. Likewise a client that converts a lead gets no notification id back; the alert appears on *other* people's feeds.
- **Nothing depends on `notifications`.** No other module imports it, and none should. That is what keeps a failure to alert from ever becoming a failure to save the thing being alerted about. The event-driven alerts run **after** the source write has committed, synchronously in the same server process (not on a queue); a failure there is logged and audited here and never affects the source module's response.

## 3. Conventions

- **Response:** the project-standard envelope — `{ success: true, message, data, meta }`. See `core/docs/INTEGRATION.md` §3.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when no access token is sent; `AUTHENTICATION_FAILED` (401) when it is expired, malformed, or bound to a revoked session (`core/docs/INTEGRATION.md` §3); `NOTIFICATIONS_ACTOR_FORBIDDEN` (403) when the caller is a Superadmin. **Both apply to all nine endpoints** and are not repeated in each §7 `Errors` list.
- **Success statuses:** `200` on every endpoint. No route returns `201` — the one write that can create a row (`PATCH /preferences/` on first use) still answers `200` with the full preferences — and no route returns `204`; every response carries a body.
- **Own-recipient scoping is absolute, and it changes what a 404 means.** Fetching or acting on a notification that belongs to another user returns **404, not 403** — identical to a made-up id. A 403 would confirm the id exists on somebody else's feed, and a notification title names an applicant and the document they are missing. There is no `?recipient=` filter and no "notifications for user X" endpoint; an Admin cannot build one.
- **Pagination:** on `GET /` only. `?page=` and `?page_size=` (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous` as absolute URLs or `null`. `data` is a **bare array** of resources — it is not nested under `results`.
- **IDs:** UUID strings everywhere, including in URL segments.
- **Times:** ISO 8601, UTC, `Z`-suffixed. `due_at` additionally carries a `due_at_bs` sibling holding its Bikram Sambat rendering, or `null`. `created_at` carries no `_bs` sibling — it is a system timestamp, not a date staff plan around.
- **`error.details` is a field-name-to-array-of-strings map on validation errors** — the key is the **query parameter name**, or for the two body-validated routes the **body field name** (`category` on `read-all/`, `categories` / `assigned_only` on `PATCH /preferences/`). The message is always `"Validation failed."`. One code deviates: `NOTIFICATIONS_ALREADY_TERMINAL` puts the current status under `details.status` as a **bare string, not an array**. Type `details` as an open map and narrow by code. Every other error in this module carries `details: {}`.
- **Methods:** each route accepts exactly the verbs listed against it in §7 and returns `405` with the global `METHOD_NOT_ALLOWED` code for anything else. In particular `PATCH`, `PUT`, and `DELETE` on `/api/v1/notifications/<id>/` all return `405`, never `404`, `POST` to the feed root returns `405`, and `/preferences/` accepts only `GET` and `PATCH` (`PUT` returns `405`). Every path ends in a trailing slash and should be sent with one.
- **List/search/filter/order params:** `GET /` accepts `status`, `is_read`, `notification_type`, `category`, `priority`, `applicant_id`, `source_app`, `source_entity_id`, `due_bucket`, `due_within_days`, `date_from`, `date_to`, `fiscal_year`, `page`, `page_size`. **Every parameter name is exactly its payload field name** — there is no shortened alias. `GET /summary/` *uses* only `due_within_days`, but it **validates the whole set**, so `GET /summary/?status=bogus` returns `400` rather than being ignored. Repeating a parameter (`?status=active&status=dismissed`) is not multi-value: the last occurrence wins and the rest are discarded. **There is no search parameter and no ordering parameter** on either — see §9, this is the module's most consequential omission.

Filter semantics, since several are not self-evident:

- `status` absent means **all statuses, including dismissed and resolved**. This is deliberate — the alert history is preserved after the source issue is fixed, and defaulting to `active` would hide it behind a parameter nobody knew to pass. A client rendering a working inbox should send `?status=active` explicitly.
- `is_read` absent means all. Sending `is_read=false` gives unread only.
- `category` takes **one or more category values, comma-separated** — `?category=lead,notes` returns rows in either category. It is the only multi-value parameter. Any unknown value in the list returns `400` naming `category`; an empty value means no narrowing. Category is derived from `notification_type` (mapping in §5), so `?category=` and `?notification_type=` combine with AND like everything else.
- `applicant_id` is an exact match on the row's `applicant_id`. Rows raised before 2026-10-29, and alert types that are not about an applicant, carry `null` and never match — see §9. For "every alert about this applicant's record", `?applicant_id=` is the parameter; `?source_entity_id=` matches only alerts whose source *is* the applicant row itself.
- `due_bucket` is computed from `due_at` against the moment of the request: `overdue` is past, `due_soon` is within `due_within_days`, `later` is beyond it, `none` is a null `due_at`.
- `due_within_days` (1–365, default 7) moves the `due_soon`/`later` boundary for the **filter and for the `due_bucket` value rendered on every row of that response**. Two requests with different values legitimately return different buckets for the same notification. **Consequence for a normalized client cache:** `due_bucket` is not a property of the notification, it is a property of the *request*. Caching a row by id across two screens that use different windows will cross-contaminate them. Store the window alongside the row, or recompute the bucket client-side from `due_at`.
- `date_from` and `date_to` take a **plain calendar date, `YYYY-MM-DD`** — not a datetime. `fiscal_year` takes a **Nepali fiscal-year label, `YYYY/YY`**, e.g. `2082/83`; anything else returns `400`. All three window on `created_at`. `date_to` is **inclusive**, and every boundary is evaluated at **Kathmandu midnight (UTC+05:45)**, not UTC — so "up to the 24th" means the whole of the 24th as staff experience it. An explicit date beats `fiscal_year` where both are given.
- Filters combine with AND. An unrecognized enum value returns `400` with `VALIDATION_ERROR` and the offending parameter named in `details` — never an empty page.
- Requesting a page past the end returns **`404` with the global `NOT_FOUND` code and the message `Invalid page.`** — not an empty array. This is DRF's paginator, not this module.

Worked success envelope, `GET /api/v1/notifications/?status=active&due_bucket=overdue`:

```json
{
  "success": true,
  "message": "",
  "data": [
    {
      "id": "5c2b9a41-7e3d-4f18-a0c6-1d8b4e6f2a90",
      "notification_type": "checklist_item_overdue",
      "category": "checklist",
      "priority": "high",
      "title": "Overdue: Passport bio page scan",
      "body": "Required for Sita Sharma on 'Australia — Student Visa'. It was due 6 days ago.",
      "applicant_id": null,
      "payload": {},
      "source_app": "checklists",
      "source_entity_type": "checklist_item",
      "source_entity_id": "a91c4f77-2b0e-4c3a-8d15-6f2e9b7a4c81",
      "source_api_path": "/api/v1/checklists/3f8e4c22-1a2b-4c3d-9e8f-7a6b5c4d3e2f/items/a91c4f77-2b0e-4c3a-8d15-6f2e9b7a4c81/",
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
  ],
  "meta": { "count": 1, "page": 1, "page_size": 20, "next": null, "previous": null }
}
```

Worked error envelope, `POST /api/v1/notifications/<id>/dismiss/` on an alert already closed (`409`):

```json
{
  "success": false,
  "error": {
    "code": "NOTIFICATIONS_ALREADY_TERMINAL",
    "message": "This notification is already resolved.",
    "details": { "status": "resolved" }
  },
  "meta": {}
}
```

Worked validation error, `GET /api/v1/notifications/?due_bucket=urgent` (`400`) — the classic mistake, since `urgent` is a valid `priority` but not a valid `due_bucket`:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { "due_bucket": ["\"urgent\" is not a valid choice."] }
  },
  "meta": {}
}
```

Worked not-found, `GET /api/v1/notifications/<id>/` for an id that is absent **or belongs to another user** (`404`) — the two are deliberately identical:

```json
{
  "success": false,
  "error": {
    "code": "NOTIFICATIONS_NOTIFICATION_NOT_FOUND",
    "message": "No such notification on your feed.",
    "details": {}
  },
  "meta": {}
}
```

## 4. Models

**Notification** — `{ id, notification_type:[enum], category:[enum], priority:[enum], title, body, applicant_id?, payload:json, source_app, source_entity_type, source_entity_id?, source_api_path, due_at?, due_at_bs?:json, due_bucket:[enum], is_read, read_at?, status:[enum], resolution:[enum], resolved_at?, delivery_channel:[enum], delivery_state:[enum], generated_by:[enum], created_at }`

- **Identical on list and retrieve.** There are no retrieve-only extras — the feed row *is* the whole resource, so a client never needs a second request to render one.
- `source_app` + `source_entity_type` + `source_entity_id` identify the record the alert is about. They are **strings and a bare UUID, never a nested object**: this module holds no foreign key into any other module, so it cannot embed one. To show details, follow `source_api_path`.
- `source_api_path` is the **nearest retrievable endpoint** for the source, which is not always the entity itself. A `passport_expiring` alert has `source_entity_type: "passport_detail"` but a `source_api_path` pointing at the applicant, because a passport has no endpoint of its own. Treat it as "where to send the user", not as "the canonical URL of `source_entity_id`".
- `title` is at most **200 characters**; `body` is unbounded. Both are **plain text, English only** — there are no `_np` variants and no markup. Render them escaped; do not treat `body` as HTML.
- `category` is derived from `notification_type` (mapping in §5) — it is never stored, so it always agrees with the type.
- `applicant_id` is the applicant the alert is about, as a bare UUID, when the alert has one; otherwise `null`. It is **`null` on every alert raised before 2026-10-29**, whatever its type. Link to the applicant with `/api/v1/applicants/<applicant_id>/`.
- `payload` is a JSON **object**, never `null`, holding a few non-sensitive structured facts for rendering — ids and enum strings, never a score, an identity number, a note's text, or a delete reason. Its keys depend on `notification_type` (table below); every type not listed there has `{}`. Treat unknown keys as additive and ignore them. Older rows have `{}`.

**The source triple is fully determined by `notification_type`.** A client can build its routing table from this and never has to parse `source_api_path`:

| `notification_type` | `source_app` | `source_entity_type` | `source_api_path` shape |
|---|---|---|---|
| `checklist_item_due`, `checklist_item_overdue` | `checklists` | `checklist_item` | `/api/v1/checklists/<checklist id>/items/<id>/` |
| `missing_documents` | `checklists` | `checklist` | `/api/v1/checklists/<id>/` |
| `assignment_received` | `checklists` | `checklist_item` **or** `checklist` | the matching path above |
| `offer_response_due`, `offer_expired`, `offer_decided` | `offers` | `offer` | `/api/v1/offers/<id>/` |
| `passport_expiring` | `applicants` | `passport_detail` | `/api/v1/applicants/<applicant id>/` — **not** the passport |
| `file_rejected` | `uploaded_files` | `uploaded_file` | `/api/v1/files/<id>/` |
| `journey_stage_changed`, `journey_closed` | `applicant_journeys` | `applicant_journey` | `/api/v1/journeys/<id>/` |
| `custom_reminder` | `reminders` | `reminder` | `/api/v1/reminders/<id>/` |
| `test_score_expiring` | `applicants` | `language_test` | `/api/v1/applicants/<applicant id>/` — **not** the test |
| `lead_created`, `lead_converted`, `lead_deleted`, `lead_restored` | `leads` | `lead` | `/api/v1/leads/<id>/` |
| `applicant_status_changed`, `applicant_restored`, `applicant_assigned`, `applicant_unassigned` | `applicants` | `applicant` | `/api/v1/applicants/<id>/` |
| `visit_note_added` | `leads` **or** `applicants` | `lead` **or** `applicant` — the record the note is on | `/api/v1/leads/<id>/notes/` or `/api/v1/applicants/<id>/notes/` — the notes feed; a single note has no `GET`, so pick it out by `payload.note_id` |
| `document_ready` | `documents` | `document` | `/api/v1/documents/<id>/` |

So `source_app` takes one of `checklists`, `offers`, `applicants`, `uploaded_files`, `applicant_journeys`, `reminders`, `leads`, `documents`, and `source_entity_type` one of `checklist`, `checklist_item`, `offer`, `passport_detail`, `uploaded_file`, `applicant_journey`, `reminder`, `language_test`, `lead`, `applicant`, `document`. **Neither is a closed enum in the database** — the column has no constraint, so a future module can add a value without a schema change. Treat both as open strings with the sets above as today's observed domain, and do not fail on an unrecognized one. As *filter* values, however, an unrecognized `source_app` simply matches nothing (it is a free-text exact match, not a choice field) and returns an empty page rather than a `400`.
**`applicant_id` and `payload` by type.** Only these types set them; every other type has `applicant_id: null` and `payload: {}`:

| `notification_type` | `applicant_id` | `payload` keys |
|---|---|---|
| `journey_stage_changed`, `journey_closed` | the journey's applicant | `stage` — the journey's stage value (`applicant_journeys` vocabulary) |
| `passport_expiring` | the passport's applicant | none (`{}`) |
| `custom_reminder` | the applicant, for an applicant reminder; `null` for a client reminder | none |
| `test_score_expiring` | the test's applicant | `test_type` — the language test type (`applicants` vocabulary, e.g. `ielts`) |
| `lead_converted` | the applicant the lead became | `applicant_id` — the same id, as a string |
| `lead_created`, `lead_deleted`, `lead_restored` | `null` | none |
| `applicant_status_changed` | the applicant | `from`, `to` — applicant status values; `originating_lead_id` — the lead it was converted from, or `null` |
| `applicant_restored` | the applicant | `from` (always `archived`), `to`, `originating_lead_id` |
| `applicant_assigned`, `applicant_unassigned` | the applicant | none |
| `visit_note_added` | the applicant, for a note on an applicant; `null` for a note on a lead | `note_id` |
| `document_ready` | the document's applicant, or `null` if it has none | `family` — the document family (`documents` vocabulary, e.g. `bank_statement`) |

- Following `source_api_path` is a **separate authorization question** answered by the owning module. Receiving an alert does not imply permission to open what it points at; a client should handle a 403 or 404 from that follow-up request.
- `is_read` and `due_bucket` are derived at read time, not stored. `is_read` is `read_at != null`.
- **Read state and status are independent.** An alert that has been read is still `active` work. Do not treat `is_read: true` as "handled". The converse also occurs: dismissing does **not** mark an alert read, so `status: "dismissed"` with `is_read: false` is a normal state a client must render.

### Lifecycle — the three states, and exactly what moves between them

There are only three transitions in this module, plus deletion by age, and only two actors can cause them:

| From | To | Caused by | Resulting `resolution` |
|---|---|---|---|
| *(nothing)* | `active` | the nightly sweep, or a source event | `""` |
| any | *(deleted)* | **the nightly sweep's retention purge**, once the row is older than the retention window (90 days by default) — event alerts in any status, deadline alerts only when `resolved` | — |
| `active` | `dismissed` | **the recipient**, calling the dismiss endpoint | `dismissed_by_user` |
| `active` | `resolved` | **the nightly sweep**, on finding the source condition no longer true | `source_cleared` |

`resolved_at` is set on entry to either terminal state and is `null` while `active`. `resolution` is `""` while `active` and non-empty in both terminal states — it is a string field whose empty value means "not applicable yet", not a fourth enum member. Type it as `"source_cleared" | "dismissed_by_user" | ""`.

**There is no transition out of a terminal state, and no transition between the two of them.** A dismissed alert is never later rewritten to `resolved`, even when its source condition does clear — the sweep only ever touches `active` rows, so the user's decision is preserved as the reason it closed. Nothing anywhere returns an alert to `active`.

**Only sweep-raised alerts are ever auto-resolved.** A lifecycle alert (`generated_by: "signal"` — assignment, file rejection, journey stage, offer decision) records that something *happened*, and there is no ongoing condition left to re-check; resolving one would mean deciding a stage change had un-happened. Those alerts stay `active` until the recipient dismisses them — or until the retention purge deletes them, about 90 days after they were raised (since 2026-10-29). A client should therefore expect a growing set of active signal alerts unless the user clears them, and may reasonably present those types with dismissal foregrounded. A dismissed or still-active *deadline* alert is never purged, however old: its row is what stops the sweep raising the same condition again.

**One alert per condition per recipient, not one per night.** A still-overdue checklist item does **not** produce a new row each time the sweep runs — the sweep recognizes the alert it already raised and leaves it, including its original `created_at` and `title`. An alert is never rewritten after creation, so a `body` saying "due 6 days ago" keeps saying that as the days pass; the live truth is on the source record. The one way the same underlying problem produces a second alert is **escalation** — see the dismiss endpoint in §7.
- Three stored fields are deliberately **not** published: the internal deduplication key, the dismissing user (it always equals the recipient), and the recipient (every row returned belongs to the caller).

**FeedSummary** — `{ unread, active, by_priority:json, by_due_bucket:json, by_category:json }`

- All integers. `by_priority` is keyed by every `priority` value; `by_due_bucket` by every `due_bucket` value; `by_category` by every `category` value (all eleven). All three are always fully zero-filled — a key is never absent.
- `unread` counts unread notifications **in any status**; `by_category` is the same population split by category, and `unread` is **exactly** the sum of its values — so a per-tab badge and the total badge cannot disagree. `active`, `by_priority`, and `by_due_bucket` count only `status: "active"`. So `unread` can legitimately exceed `active`: an alert resolved or dismissed before anybody read it is still unread.

**Which number belongs on a bell badge — read this before choosing.** The two count different populations, and neither is the obvious answer:

- **`unread`** is what the "mark all read" button drives to zero, so if the badge shows anything else that button will look broken. But it counts closed alerts nobody happened to read, so the badge can read `7` while an inbox opened with `?status=active` shows fewer rows.
- **`active`** matches the working inbox exactly, but nothing a user can click drives it to zero — only dismissing every alert does.

There is no third count combining them, and **this module does not provide "unread *and* active" in one call.** If that is the number the product wants, get it with `GET /api/v1/notifications/?status=active&is_read=false&page_size=1` and read `meta.count` — a second request, which is the cost of a figure this endpoint does not compute. The recommendation in §8 uses `unread` and pairs it with a `?status=active` inbox; a client that does so should be aware it is showing a badge whose population is slightly wider than the list behind it.

**BulkReadResult** — `{ marked_read }`

- One integer: how many notifications the call changed. Returned instead of the affected rows, which on this endpoint would be the largest and least useful response the module produces.

**NotificationPreferences** — `{ categories:json, assigned_only }`

- `categories` is an object keyed by **every** `category` value (all eleven, always present on read); each value is `{ in_app }`, a boolean. `in_app: false` means that category is muted for this user. The value is an object rather than a bare boolean so a second delivery channel can be added inside it without a breaking change.
- `assigned_only` is a boolean. When `true`, an alert that names an applicant (`applicant_id` set) reaches this user only if they are that applicant's assignee; alerts with no applicant are unaffected, and so are `applicant_assigned` / `applicant_unassigned` (always about the recipient).
- Defaults, when the user has never saved anything: every category `in_app: true`, `assigned_only: false`.
- **Preferences decide which alerts are created for this user from now on.** A muted alert is never written — it does not exist to be fetched, counted, or unmuted later. Changing preferences never hides, deletes, or restores alerts already in the feed.
- There is no `id` and no owner field: the resource is always "mine".

### Worked examples

`GET /api/v1/notifications/summary/`:

```json
{
  "success": true,
  "message": "Notification summary retrieved.",
  "data": {
    "unread": 7,
    "active": 12,
    "by_priority": { "low": 1, "normal": 4, "high": 6, "urgent": 1 },
    "by_due_bucket": { "overdue": 3, "due_soon": 4, "later": 2, "none": 3 },
    "by_category": {
      "lead": 2, "applicant_status": 1, "journey": 0, "assignment": 1, "notes": 0, "follow_up": 0,
      "documents": 0, "checklist": 2, "offer": 1, "file": 0, "expiry": 0
    }
  },
  "meta": {}
}
```

An event alert, as it appears in the feed — `applicant_status_changed` raised when a colleague moved an applicant from `active` to `dormant`:

```json
{
  "id": "0b7e3c55-91d2-4a6f-b8e4-2c9d1f0a7e63",
  "notification_type": "applicant_status_changed",
  "category": "applicant_status",
  "priority": "normal",
  "title": "Sita Sharma is now dormant",
  "body": "Moved from active to dormant by Ram Karki.",
  "applicant_id": "e4c1a2b3-5d6f-4a7b-9c8d-0e1f2a3b4c5d",
  "payload": {
    "from": "active",
    "to": "dormant",
    "originating_lead_id": "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
  },
  "source_app": "applicants",
  "source_entity_type": "applicant",
  "source_entity_id": "e4c1a2b3-5d6f-4a7b-9c8d-0e1f2a3b4c5d",
  "source_api_path": "/api/v1/applicants/e4c1a2b3-5d6f-4a7b-9c8d-0e1f2a3b4c5d/",
  "due_at": null,
  "due_at_bs": null,
  "due_bucket": "none",
  "is_read": false,
  "read_at": null,
  "status": "active",
  "resolution": "",
  "resolved_at": null,
  "delivery_channel": "in_app",
  "delivery_state": "delivered",
  "generated_by": "signal",
  "created_at": "2026-10-29T05:12:40.118Z"
}
```

`GET /api/v1/notifications/preferences/` for a user who muted leads and visit notes and wants only their own applicants:

```json
{
  "success": true,
  "message": "Preferences retrieved.",
  "data": {
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
  },
  "meta": {}
}
```

`POST /api/v1/notifications/read-all/`:

```json
{
  "success": true,
  "message": "Notifications marked read.",
  "data": { "marked_read": 7 },
  "meta": {}
}
```

## 5. Enums

- `Notification.notification_type`: `checklist_item_due` | `checklist_item_overdue` | `missing_documents` | `missing_information` | `offer_response_due` | `offer_expired` | `passport_expiring` | `custom_reminder` | `test_score_expiring` | `appointment_reminder` | `assignment_received` | `file_rejected` | `journey_stage_changed` | `journey_closed` | `offer_decided` | `lead_created` | `lead_converted` | `lead_deleted` | `lead_restored` | `applicant_status_changed` | `applicant_restored` | `applicant_assigned` | `applicant_unassigned` | `visit_note_added` | `document_ready`
- `Notification.category` (also the `?category=` filter, the `by_category` keys, the `read-all` body, and the `NotificationPreferences.categories` keys): `lead` | `applicant_status` | `journey` | `assignment` | `notes` | `follow_up` | `documents` | `checklist` | `offer` | `file` | `expiry`
- `Notification.priority`: `low` | `normal` | `high` | `urgent`
- `Notification.status`: `active` | `dismissed` | `resolved`
- `Notification.resolution`: `source_cleared` | `dismissed_by_user` | `""` (empty while active)
- `Notification.due_bucket`: `overdue` | `due_soon` | `later` | `none`
- `Notification.delivery_channel`: `in_app` — the only value produced in this version
- `Notification.delivery_state`: `pending` | `delivered` | `failed` — only `delivered` is produced in this version, because in-app delivery completes the moment the row exists
- `Notification.generated_by`: `sweep` | `signal`

**Category mapping — every type belongs to exactly one category:**

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

There is no `case` category: this project has no "case" concept, and journeys are its equivalent — a frontend expecting `case_journey` should use `journey`.

**Payload value sets are owned elsewhere:** `payload.stage` uses the journey-stage vocabulary of `applicant_journeys`; `payload.from` / `payload.to` the applicant status vocabulary of `applicants` (`active` | `dormant` | `archived`); `payload.test_type` the language-test-type vocabulary of `applicants`; `payload.family` the document-family vocabulary of `documents`. See those modules' contracts.

**Two `notification_type` values are declared but never produced in this version:** `missing_information` and `appointment_reminder`. The first has no source — no module defines what "required information" is — and the second belongs to an appointments module that does not exist yet. They are in the vocabulary so a client can handle the full enum once and so adding a generator later is not a breaking change. A client should render them rather than treat them as invalid, but will not receive one today. (`test_score_expiring` was in this group until 2026-10-29 and is now produced.)

**What each produced type means**, since several names are ambiguous from outside:

- `checklist_item_due` / `checklist_item_overdue` — one requirement on one applicant's checklist is approaching, or has passed, its due date.
- `missing_documents` — a checklist holds document requirements with **no due date at all** and nothing collected. Nobody is being chased for them, which is why they need their own alert: the two above are driven by dates these items do not have.
- `offer_response_due` / `offer_expired` — an **issued** offer's response deadline is approaching or has passed. `offer_expired` names the deadline, not the offer's status: the offer is still `issued` in the offers module, because nothing here changes business state.
- `passport_expiring` — an applicant's passport has expired or expires within roughly six months. Raised for already-lapsed passports too.
- `test_score_expiring` — one of an applicant's language-test results has expired or expires within roughly three months (90 days by default). Raised for already-expired results too; archived applicants are skipped. The title names the test type and the applicant, never the score. Resolves on a later sweep when the test is removed or replaced by one with a later expiry.
- `custom_reminder` — a staff-set follow-up reminder (`reminders` module) whose date has arrived. The body is the reminder's own note.
- `assignment_received` — **a checklist or a single checklist item has been assigned to you.** Always about checklist work. Assignment of a whole applicant is the separate `applicant_assigned`.
- `lead_created` / `lead_converted` / `lead_deleted` / `lead_restored` — something happened to a lead, done by the person named in `body`. A converted lead's alert carries the new applicant in `applicant_id`.
- `applicant_status_changed` / `applicant_restored` — an applicant's status changed (`payload.from` → `payload.to`), or an archived applicant was restored.
- `applicant_assigned` / `applicant_unassigned` — an applicant was assigned to you, or taken off you.
- `visit_note_added` — someone recorded an **in-person office visit** note on a lead or an applicant. General notes raise nothing. The note text is not copied; follow `source_api_path`.
- `document_ready` — a document was marked ready. Only Admins receive it.
- `file_rejected` — an uploaded file's review came back rejected. The rejection reason is in `body`.
- `journey_stage_changed` / `journey_closed` — an applicant journey reached a new stage, or reached a terminal one. A move into `completed`, `closed`, or `deferred` raises **only** `journey_closed`; any other stage raises **only** `journey_stage_changed`.
- `offer_decided` — an offer reached a terminal status (accepted, rejected, withdrawn, deferred, expired).

**Who receives what** (decided server-side; a client cannot query or influence it beyond its own preferences). "Admin" here never includes a Superadmin, and "every Lead Manager" means every *active* one. For the event alerts raised from `leads`, `applicants`, and `documents`, and for `file_rejected`, the person who performed the action is never notified of it. Checklist, offer, and journey alerts are raised from record saves that do not carry an actor, so **an Admin who moves a journey or decides an offer does receive that alert themselves**:

- Checklist due/overdue and missing documents → the item's or checklist's assignee, else every Admin. `assignment_received` → the new assignee.
- Offer deadlines and decisions → every Admin.
- `passport_expiring`, `test_score_expiring`, journey alerts, and applicant `custom_reminder` → every Admin, plus the applicant's assignee when there is one. Client reminders → every Admin.
- `file_rejected` → the uploader and every Admin.
- `lead_created` → every Admin. `lead_converted` / `lead_deleted` / `lead_restored` → the lead's owner (the Lead Manager who created it) and every Admin. A visit note on a lead → the lead's owner.
- `applicant_status_changed` / `applicant_restored` → the assignee and every Admin; **if the applicant is unassigned, every Admin and every Lead Manager**. A visit note on an applicant → the assignee only; if unassigned, every Admin and every Lead Manager.
- `applicant_assigned` → the new assignee; `applicant_unassigned` → the previous assignee.
- `document_ready` → every Admin.
- A **deactivated assignee counts as no assignee**: the applicant's alerts take the unassigned routing until an Admin reassigns or clears it.

Each recipient's preferences then apply: a muted category is never written — **for every type, including assignment alerts** — and `assigned_only` drops alerts about applicants not assigned to them. `applicant_assigned` / `applicant_unassigned` are exempt from `assigned_only` only (they are always about the recipient), not from muting the `assignment` category.

**Priority is fixed per type**, assigned when the alert is raised: `offer_expired` → `urgent`; `checklist_item_overdue`, `offer_response_due`, `passport_expiring`, `test_score_expiring`, `file_rejected` → `high`; `journey_stage_changed`, `lead_restored`, `applicant_unassigned`, `visit_note_added` → `low`; everything else → `normal`. A client can rely on this mapping for display but should read `priority` from the payload rather than recompute it — a stored priority is not rewritten if the mapping is ever changed.

## 6. Dependency order

- A `Notification` needs a **recipient**, which is a user account `authenticate` issues (external module).
- A `Notification` needs a **source record** in `checklists`, `offers`, `applicants`, `reminders`, `uploaded_files`, `applicant_journeys`, `leads`, or `documents` (external modules) — the alert is raised *from* that record or event and cannot exist before it.
- `NotificationPreferences` needs only the calling user (external module: `authenticate`). It always exists from the client's point of view — reading it before anything was saved returns the defaults.
- A `Notification` does **not** need `NotificationPreferences`, but preferences decide whether one is created for a given user. Set them before the alerts they should filter are raised; they never apply retroactively.

**Start here:** there is nothing for a client to create. Call `GET /api/v1/notifications/summary/` to render a badge, then `GET /api/v1/notifications/?status=active` to render the inbox. `GET /api/v1/notifications/preferences/` backs a settings screen.

## 7. Endpoints

### Notification feed — `/api/v1/notifications/`

**Use it when:** rendering the alert inbox — the screen a staff member opens to see what needs attention today; a per-category tab via `?category=`; and the per-record alert history reached from an applicant or checklist screen via `?applicant_id=` or `?source_entity_id=`.

**Methods:**

- `GET /api/v1/notifications/` — the caller's own feed, paginated, newest first (permission: `notifications.notification.list`, risk: medium, version 1.1.0)

**Send:** `none` — this endpoint accepts no body under any method. `POST`, `PATCH`, `PUT`, and `DELETE` all return `405`.

**Returns:** `list[Notification]`

**Requires state:**

- An authenticated Admin or Lead Manager session.
- Nothing else. The feed is valid and returns an empty array for a user who has never received an alert.

**Side effects:** none. Reading the feed does not mark anything read.

**Notes:**

- Scoped to the calling user. No authority can widen it.
- `status` absent returns **all** statuses including `dismissed` and `resolved`. Send `?status=active` for a working inbox.
- Alerts appear here without any client action, produced by a nightly deadline sweep and by events in the other modules. Event alerts are written as soon as the triggering change commits (within the same server request, not via a queue), so they are visible on the next poll. A client should poll `GET /summary/` for the badge rather than the full feed; there is no push channel, no websocket, no server-sent events, and no long-poll in this version.
- Pagination is page-number (`?page=`), not cursor. Because rows are newest-first, a new alert arriving between two page requests shifts later pages by one row; a client paging deep should tolerate a duplicate.
- Rows older than the retention window (90 days by default) may have been deleted — see §4 Lifecycle.

**Errors:**

- `VALIDATION_ERROR` (400) — an unrecognized enum value or category, a malformed UUID, or `due_within_days` outside 1–365

---

### Notification summary — `/api/v1/notifications/summary/`

**Use it when:** rendering the bell badge, the per-category tab badges (`by_category`), and the inbox's grouping headers. Two queries regardless of feed size — a client should never page the feed to produce a count. This is also the "unread count" endpoint; there is no separate one.

**Methods:**

- `GET /api/v1/notifications/summary/` (permission: `notifications.notification.summary`, risk: low, version 1.1.0)

**Send:** `none`

**Returns:** `FeedSummary`

**Requires state:**

- An authenticated Admin or Lead Manager session.

**Side effects:** none.

**Notes:**

- Only `due_within_days` changes the result. Every other feed parameter is validated (a bad value is a `400`) but does not narrow anything, so the badge cannot disagree with itself between screens — `?category=` does **not** filter the summary; read `by_category` instead.
- `unread` may exceed `active` — see §4. `unread` equals the sum of `by_category`.

**Errors:**

- `VALIDATION_ERROR` (400) — `due_within_days` outside 1–365, or any other feed parameter with an invalid value

---

### One notification — `/api/v1/notifications/<id>/`

**Use it when:** re-fetching a single alert after acting on it, or deep-linking into one from outside the inbox.

**Methods:**

- `GET /api/v1/notifications/<id>/` (permission: `notifications.notification.read`, risk: low, version 1.1.0)

**Send:** `none`

**Returns:** `Notification` — the same shape as a feed row, with no extra fields.

**Requires state:**

- The notification must exist **and be addressed to the calling user**.

**Side effects:** none.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404) — no such notification on the caller's own feed. Also returned for a notification that exists on another user's feed, deliberately indistinguishable from a made-up id

---

### Mark read — `/api/v1/notifications/<id>/read/`

**Use it when:** the user opens or expands an alert in the inbox.

**Methods:**

- `POST /api/v1/notifications/<id>/read/` (permission: `notifications.notification.mark_read`, risk: low)

**Send:** `none` — no body.

**Returns:** `Notification` — the updated row, with `is_read: true` and `read_at` set.

**Requires state:**

- The notification must exist and be addressed to the calling user. It may be in any `status`; a resolved or dismissed alert can still be marked read.

**Side effects:** sets `read_at` on this notification. Nothing changes in any other module.

**Notes:**

- Idempotent, and a second call **keeps the first timestamp** — the receipt answers when the alert was first seen, not when the list was last opened.
- Does **not** change `status`. Reading is not deciding.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404)

---

### Mark unread — `/api/v1/notifications/<id>/unread/`

**Use it when:** the user opens something they cannot deal with now and wants it back in the unread count.

**Methods:**

- `POST /api/v1/notifications/<id>/unread/` (permission: `notifications.notification.mark_unread`, risk: low)

**Send:** `none`

**Returns:** `Notification` — with `is_read: false` and `read_at: null`.

**Requires state:**

- The notification must exist and be addressed to the calling user. Calling it on an already-unread notification succeeds and changes nothing.

**Side effects:** clears `read_at` on this notification.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404)

---

### Mark all read — `/api/v1/notifications/read-all/`

**Use it when:** the user clicks "mark all as read" to clear the badge — or, with a category, "mark all read" on one tab of a categorised inbox.

**Methods:**

- `POST /api/v1/notifications/read-all/` (permission: `notifications.notification.mark_all_read`, risk: low, version 1.1.0)

**Send:**

- No body, an empty object, or `{ "category": "" }` — clears everything unread on the caller's feed.
- `{ "category": "<category>" }` — clears only that category's unread notifications. One category per call; a comma list (`"lead,notes"`) is an unknown value and returns 400 — a combined tab clears with one call per category.

**Returns:** `BulkReadResult`

**Requires state:**

- An authenticated Admin or Lead Manager session. Succeeds with `marked_read: 0` when nothing is unread.

**Side effects:** sets `read_at` on every unread notification belonging to the caller (within the category, if one was sent), **including dismissed and resolved ones**. That is intentional: clearing the badge must leave nothing unread, or the number returns on the next page load. Nothing is dismissed or resolved, and no other user's feed is touched.

**Errors:**

- `VALIDATION_ERROR` (400) — `category` is not one of the eleven category values

---

### Dismiss — `/api/v1/notifications/<id>/dismiss/`

**Use it when:** the user decides a flagged item needs no action — the inbox's "clear this one" affordance.

**Methods:**

- `POST /api/v1/notifications/<id>/dismiss/` (permission: `notifications.notification.dismiss`, risk: medium)

**Send:** `none` — no reason field. This version records the decision, not its rationale.

**Returns:** `Notification` — with `status: "dismissed"`, `resolution: "dismissed_by_user"`, and `resolved_at` set.

**Requires state:**

- The notification must exist, be addressed to the calling user, and be `status: "active"`.

**Side effects:**

- Moves the notification to a terminal state. It stays in the feed and is still returned by an unfiltered `GET /` — dismissing deletes nothing. (A dismissed *event* alert is later removed by the 90-day retention purge like any other event alert; a dismissed *deadline* alert is kept indefinitely, because its row is what stops the sweep raising it again.)
- Writes an audit event in the `audit` module recording who dismissed what and when. This is the only endpoint in this module that writes outside its own table.
- **Suppresses this alert permanently — but not necessarily the underlying problem.** The nightly sweep will never re-raise *this* alert: the row holds its deduplication slot forever, so dismissing is not "hide until tomorrow". There is no snooze and no un-dismiss. What can still reach the user is **escalation**, and it is worth being precise about, because it is the one thing that makes "permanent" less than absolute: severity is part of what an alert is, so a checklist item dismissed while merely `checklist_item_due` will raise a **separate, new** `checklist_item_overdue` alert if it later passes its deadline. The dismissed row stays dismissed; a second row appears beside it. The reverse never happens — dismissing the overdue alert ends it, because there is no higher severity to escalate to. Present dismissal to the user as a decision.
- Does **not** change anything in the module that owns the source record. Dismissing an overdue-item alert does not complete, waive, or reschedule the checklist item; the work is still outstanding there.

**Notes:**

- The condition can still produce a *new* alert by escalation — an item dismissed while merely due-soon will alert again if it later becomes overdue, because that is a different alert type. That is the only path back.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404)
- `NOTIFICATIONS_ALREADY_TERMINAL` (409) — already dismissed or resolved; `details.status` carries the current value

---

### Notification preferences — `/api/v1/notifications/preferences/`

**Use it when:** rendering the notification settings screen — per-category on/off switches and an "only my applicants" toggle.

**Methods:**

- `GET /api/v1/notifications/preferences/` — the caller's own preferences (permission: `notifications.preference.read`, risk: low, version 1.0.0)

**Send:** `none`

**Returns:** `NotificationPreferences` — always complete; defaults when nothing has been saved.

**Requires state:**

- An authenticated Admin or Lead Manager session. Nothing else — a user who has never saved preferences gets the defaults.

**Side effects:** none. Reading never creates anything.

**Errors:** `none` beyond the global auth failures.

---

### Update notification preferences — `/api/v1/notifications/preferences/`

**Use it when:** the user flips a category switch or the "only my applicants" toggle on the settings screen.

**Methods:**

- `PATCH /api/v1/notifications/preferences/` (permission: `notifications.preference.update`, risk: low, version 1.0.0)

**Send:**

- `categories` — optional; an object with **any subset** of category keys, each value `{ in_app: boolean }`. Categories not sent keep their current setting.
- `assigned_only` — optional boolean. Unchanged when not sent.

**Returns:** `NotificationPreferences` — the full set after the change, not just what was sent.

**Requires state:**

- An authenticated Admin or Lead Manager session. Nothing needs to exist first; the first `PATCH` creates the user's stored preferences.

**Side effects:**

- Changes which alerts are **created** for the caller from now on. A muted category's alerts are never written for this user, and with `assigned_only` alerts about applicants not assigned to them are never written.
- Does **not** hide, delete, or restore anything already in the feed, and does not change any count in `GET /summary/` until new alerts arrive (or fail to).
- Nothing changes in any other module or on any other user's feed. Not audited.

**Notes:**

- Only the caller's own preferences can be read or changed; there is no id in the path.
- `PUT` is not supported (`405`); send only what changed.

**Errors:**

- `VALIDATION_ERROR` (400) — an unknown category key, e.g. `details: { "categories": ["Unknown categories: case_journey."] }`; or a value that is not a boolean / not shaped `{ in_app: boolean }`. Success messages are `"Preferences retrieved."` (GET) and `"Preferences updated."` (PATCH)

## 8. Flows

**Working the daily inbox**

1. `GET /api/v1/notifications/summary/` → render the bell badge from `unread`, and the section headers from `by_due_bucket`. Read the badge note in §4 first: `unread` is the number "mark all read" clears, and it counts a slightly wider population than the `?status=active` list in step 2.
2. `GET /api/v1/notifications/?status=active&due_bucket=overdue` → the "needs attention now" section. Repeat with `due_bucket=due_soon` and `due_bucket=later` for the other sections, or fetch once unfiltered and group client-side on the `due_bucket` field each row carries.
3. User opens an alert → `POST /api/v1/notifications/<id>/read/`.
4. User clicks through to the work → follow `source_api_path` into the owning module.
   - That request may return 403 or 404 on its own terms — receiving an alert does not imply permission to open the record it names.
5. User finishes the work in the owning module (e.g. completes the checklist item).
   - The alert does **not** update immediately. The next nightly sweep moves it to `status: "resolved"` / `resolution: "source_cleared"`. Until then it stays `active` and looks outstanding. A client that wants the inbox to look correct at once should re-fetch and treat the alert as stale, or let the user dismiss it — dismissal and resolution close the alert equally, they only differ in what they record about *why*.

**Clearing an alert that does not need action**

1. `GET /api/v1/notifications/?status=active` → find the alert.
2. `POST /api/v1/notifications/<id>/dismiss/` → `status` becomes `dismissed`.
   - `409 NOTIFICATIONS_ALREADY_TERMINAL` → another session already closed it; re-fetch with `GET /api/v1/notifications/<id>/` and show the current state.
3. The alert stays in the feed under `?status=dismissed` and never returns to `active`.

**Reviewing everything ever raised about one record**

1. From an applicant, checklist, or offer screen, take the record's id.
2. For an applicant: `GET /api/v1/notifications/?applicant_id=<applicant id>` → every alert the **calling user** received about that applicant — status, assignment, visit notes, journeys, passport and test expiry, reminders. For any other record: `GET /api/v1/notifications/?source_entity_id=<record id>`.
   - This is a partial history by design: alerts sent to other people are not visible. A client should not label this "all alerts for this record".
   - `?applicant_id=` misses alerts raised before 2026-10-29 (their `applicant_id` is `null`) and alerts older than the retention window.

**Clearing the badge**

1. `POST /api/v1/notifications/read-all/` → returns `{ "marked_read": n }`.
2. `GET /api/v1/notifications/summary/` → `unread` is now `0`. `active` is unchanged: reading is not deciding, and the work is still on the desk.

**Per-category inbox tabs**

1. `GET /api/v1/notifications/summary/` → render one tab per category, each badged from `by_category.<category>`; the "All" tab from `unread`.
2. User opens a tab → `GET /api/v1/notifications/?category=<category>&status=active`. A combined tab (e.g. "People") may send several: `?category=lead,applicant_status,notes`.
   - `400 VALIDATION_ERROR` naming `category` → the client sent a category this server does not know. Treat as a client bug.
3. User clicks "mark all read" on that tab → `POST /api/v1/notifications/read-all/` with `{ "category": "<category>" }` → `{ "marked_read": n }`. One category per call; a combined tab issues one call per category.
4. `GET /api/v1/notifications/summary/` → that tab's `by_category` count is `0`; `unread` dropped by `n`; other tabs are unchanged.

**Setting my notification preferences**

1. Settings screen opens → `GET /api/v1/notifications/preferences/` → render one switch per key in `categories` (from `in_app`) and the "only my applicants" toggle from `assigned_only`.
2. User turns a category off → `PATCH /api/v1/notifications/preferences/` with `{ "categories": { "<category>": { "in_app": false } } }` → the full updated preferences; re-render from the response.
   - `400 VALIDATION_ERROR` under `details.categories` → unknown category key; a client bug.
3. User turns on "only my applicants" → `PATCH /api/v1/notifications/preferences/` with `{ "assigned_only": true }`.
4. Nothing in the existing inbox changes. Tell the user the setting applies to new alerts: alerts already in the feed stay (they can be dismissed or marked read), and alerts skipped while a category is muted will not appear when it is turned back on.

## 9. Gaps

- **The feed cannot be ordered, and for an inbox that is the most consequential thing missing here.** There is no `ordering` parameter. Rows come back newest-created first, always — so an `urgent` offer-expiry alert raised last week sits below a `low` journey-stage alert raised this morning, and no request can reverse that. Sorting a single page client-side does not fix it, because the rows that should be on page 1 are on page 3. The workarounds are partial: `?priority=urgent` then `?priority=high` as separate sections, or `?due_bucket=overdue` first. A `?ordering=priority,due_at` parameter is the obvious fix and is not built.
- **No search.** There is no way to find "the alert about Sita" other than paging or filtering by `applicant_id` / `source_entity_id`, which requires already knowing the record.
- **No bulk action except all-or-one.** `read-all` takes at most one category, and there is no "dismiss these five" or "dismiss all overdue".
- **History is deleted after 90 days for most alerts.** The nightly sweep purges event alerts (`generated_by: "signal"`, any status) and resolved deadline alerts older than its retention window — 90 days by default, an operator setting not exposed through the API. There is no archive and no undo; an inbox showing "everything about this applicant" shows at most that window of event history. Dismissed and still-active deadline alerts are kept indefinitely.
- **Delivery is not a queue, and there is no push.** Event alerts are written synchronously, in-process, right after the triggering change commits — there is no Celery/worker, no retry, and a failed write is logged and audited server-side but never surfaced to any client. There is no websocket, server-sent-event stream, or long-poll endpoint (SSE was requested and declined). A client must poll `GET /summary/`. No polling interval is recommended by this module, and no `ETag`, `Last-Modified`, or conditional-request support exists on any endpoint, so every poll is a full response. The project-wide authenticated rate limit is the only budget to plan against; there is no per-endpoint exemption for `/summary/` despite it being the endpoint designed to be polled.
- **Requested and declined:** cursor pagination (the feed stays page-number — see §7 feed notes on shifting pages), a dedicated `unread-count/` endpoint (`GET /summary/` serves every count, including per category), server-sent events (above), and a `case_journey` category (there is no "case" concept; `journey` is the equivalent).
- **Alerts resolve on a schedule, not on the event.** Finishing work in another module does not close the alert immediately — the nightly `sweep_notifications` job does. The exact run time is a deployment decision and is not exposed through the API, so a client cannot tell a user when an alert will clear.
- **No snooze and no un-dismiss.** Dismissal is one-way. Per-category mute and "only my applicants" exist (`NotificationPreferences`), but no individual notification can be snoozed. "Remind me tomorrow" exists only as a *new record elsewhere*: staff can set a date-based follow-up in the `reminders` module (`/api/v1/reminders/`), which raises a `custom_reminder` alert here when the date arrives.
- **Muting is lossy.** A muted category's alerts are never written; turning the category back on does not recover what was skipped, and nothing records that an alert was suppressed.
- **`applicant_id` is `null` on every alert raised before 2026-10-29**, and `payload` is `{}` on them. `?applicant_id=` and `assigned_only` do not see those rows.
- **`payload` is not role-projected.** Every recipient sees the same `payload`; it is safe to do so only because it never holds sensitive data (no scores, identity numbers, note text, or delete reasons). A client must not expect richer detail there for privileged users — follow `source_api_path`.
- **Checklist `assignment_received` is the one routing exception.** Unlike every other alert, it does not exclude the person who made the assignment and does not skip deactivated accounts, so assigning a checklist item to yourself alerts you.
- **No delivery beyond in-app.** `delivery_channel` and `delivery_state` are in the payload but only ever hold `in_app` and `delivered`. No email or SMS is sent by this version; `NotificationPreferences` has only an `in_app` switch per category.
- **Two enum values are unproduceable** (`missing_information`, `appointment_reminder`) — see §5.
- **`source_api_path` is not a guaranteed-resolvable URL for `source_entity_id`.** It is the nearest retrievable endpoint, which for `passport_detail` and `language_test` is the applicant, and for `visit_note_added` is the note under its lead or applicant. A client cannot infer the entity's own URL from the pair.
- **Lifecycle alerts about a source record's *history* are lossy by design.** A journey moved back to a stage it already held raises nothing, and a file rejected, verified, and rejected again raises one alert. Event alerts (`lead_*`, `applicant_*`, `visit_note_added`, `document_ready`) are not lossy in that way — each occurrence is its own alert — but they are purged after the retention window. A client must not treat the feed as a complete event log — `audit` is that, and it is a different module.
- **Recipient routing is summarized in §5 but not queryable.** A client cannot ask who else received an alert, and there is no endpoint that reports it.
- **Whether an alert's underlying work is still outstanding is not in this payload.** `status: "active"` means the alert has not been closed, which is not the same as the checklist item still being incomplete between sweeps. To render the current truth, follow `source_api_path`.
