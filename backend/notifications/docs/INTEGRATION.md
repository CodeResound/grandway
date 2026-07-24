# Integration — Notifications

**Owner app:** `notifications`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial integration contract for the seven endpoints |
| 1.0.1 | 2026-07-24 | AI (Claude Opus 4.8) | Corrections from the §19.5 consumer-contract review, which read only this file and the project-level one. Two code defects it exposed are fixed: the feed filter `type` is now `notification_type` (the one parameter of twelve that did not match its field), and a malformed `?fiscal_year=` returned **500** rather than 400. Added to the contract: **the lifecycle table** — the review found the sweep's `active` → `resolved`/`source_cleared` transition, the module's central event, was documented only by the existence of an enum value; **the source-triple table**, since `source_app` and `source_entity_type` were exposed as both filter and payload with no value set anywhere; worked `400` and `404` bodies; the deduplication guarantee (one alert per condition, not one per night); date-parameter formats and timezone; `405`/trailing-slash/page-past-end behaviour; what each produced type actually means; and the dismissed-but-unread state. Corrected: "suppresses permanently" contradicting the escalation note two lines below it, and the badge recommendation, which paired `unread` with a `?status=active` inbox without saying they count different populations. §9 gained the missing ordering parameter — ranked first, since an inbox that cannot sort by priority buries its own urgent rows — plus search, retention, polling cost, and the absence of any lead-follow-up alert |

---

## 1. Module

- **Name:** Notifications — the in-app alert stream. It turns deadlines and lifecycle events in the other modules into a per-person inbox: what needs attention, why, and which record to open next. It owns **no business state** — every alert points at a record another module owns.
- **Base path:** `/api/v1/notifications/`
- **Auth:** Every endpoint requires a JWT bearer token. Admin and Lead Manager may reach every endpoint; Superadmin is refused on all seven. **Every endpoint operates on the calling user's own notifications only** — there is no way to read or act on another user's feed through this API, for any authority. See §3.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework + FK + service call | Issues the bearer token; supplies the recipient; `get_active_admins()` is the fan-out for alerts about records nobody owns | Every endpoint returns 401. With no active Admin account, offer, passport, and journey alerts are raised for nobody and silently vanish |
| `checklists` | service call + **signal** | The overdue, due-soon, and missing-document alerts read that module's own selectors; assignment alerts listen on its saves | Those four alert types stop being produced. The feed still works and still serves everything else |
| `offers` | service call + **signal** | Response-deadline and expiry alerts read `get_offers_awaiting_response`; decision alerts listen on offer saves | `offer_response_due`, `offer_expired`, and `offer_decided` stop being produced |
| `applicants` | service call | Passport-expiry alerts read `get_expiring_passports` | `passport_expiring` stops being produced |
| `uploaded_files` | **signal** | Rejection alerts listen on file saves | `file_rejected` stops being produced |
| `applicant_journeys` | **signal** | Stage-change and closure alerts listen on journey saves | `journey_stage_changed` and `journey_closed` stop being produced |
| `audit` | service call | Records dismissals and generator failures | Dismissal still works, but nothing records who closed what, and a broken generator becomes indistinguishable from a quiet night |
| `core` | framework | Response envelope, pagination, date-window resolution, Bikram Sambat rendering | Responses lose the `{ success, message, data, meta }` envelope; errors return raw DRF bodies |

**Two notes for consumers, both easy to get wrong from outside:**

- **Every dependency above runs one way, and none is visible from the other side.** No module knows this one exists. A client that completes a checklist item will not see any mention of a notification in the checklist response — the alert is resolved by the next nightly sweep, and the client must ask this module to see that.
- **Nothing depends on `notifications`.** No other module imports it, and none should. That is what keeps a failure to alert from ever becoming a failure to save the thing being alerted about.

## 3. Conventions

- **Response:** the project-standard envelope — `{ success: true, message, data, meta }`. See `core/docs/INTEGRATION.md` §3.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when the JWT is missing or invalid; `NOTIFICATIONS_ACTOR_FORBIDDEN` (403) when the caller is a Superadmin. **Both apply to all seven endpoints** and are not repeated in each §7 `Errors` list.
- **Success statuses:** `200` on every endpoint. Nothing here creates a resource, so no route returns `201`, and no route returns `204` — every response carries a body.
- **Own-recipient scoping is absolute, and it changes what a 404 means.** Fetching or acting on a notification that belongs to another user returns **404, not 403** — identical to a made-up id. A 403 would confirm the id exists on somebody else's feed, and a notification title names an applicant and the document they are missing. There is no `?recipient=` filter and no "notifications for user X" endpoint; an Admin cannot build one.
- **Pagination:** on `GET /` only. `?page=` and `?page_size=` (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous` as absolute URLs or `null`. `data` is a **bare array** of resources — it is not nested under `results`.
- **IDs:** UUID strings everywhere, including in URL segments.
- **Times:** ISO 8601, UTC, `Z`-suffixed. `due_at` additionally carries a `due_at_bs` sibling holding its Bikram Sambat rendering, or `null`. `created_at` carries no `_bs` sibling — it is a system timestamp, not a date staff plan around.
- **`error.details` is a field-name-to-array-of-strings map on validation errors** — the key is the **query parameter name**. One code deviates: `NOTIFICATIONS_ALREADY_TERMINAL` puts the current status under `details.status` as a **bare string, not an array**. Type `details` as an open map and narrow by code. Every other error in this module carries `details: {}`.
- **Methods:** each route accepts exactly the verbs listed against it in §7 and returns `405` with the global `METHOD_NOT_ALLOWED` code for anything else. In particular `PATCH`, `PUT`, and `DELETE` on `/api/v1/notifications/<id>/` all return `405`, never `404`, and `POST` to the feed root returns `405`. Every path ends in a trailing slash and should be sent with one.
- **List/search/filter/order params:** `GET /` accepts `status`, `is_read`, `notification_type`, `priority`, `source_app`, `source_entity_id`, `due_bucket`, `due_within_days`, `date_from`, `date_to`, `fiscal_year`, `page`, `page_size`. **Every parameter name is exactly its payload field name** — there is no shortened alias. `GET /summary/` *uses* only `due_within_days`, but it **validates the whole set**, so `GET /summary/?status=bogus` returns `400` rather than being ignored. Repeating a parameter (`?status=active&status=dismissed`) is not multi-value: the last occurrence wins and the rest are discarded. **There is no search parameter and no ordering parameter** on either — see §9, this is the module's most consequential omission.

Filter semantics, since several are not self-evident:

- `status` absent means **all statuses, including dismissed and resolved**. This is deliberate — the alert history is preserved after the source issue is fixed, and defaulting to `active` would hide it behind a parameter nobody knew to pass. A client rendering a working inbox should send `?status=active` explicitly.
- `is_read` absent means all. Sending `is_read=false` gives unread only.
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
      "priority": "high",
      "title": "Overdue: Passport bio page scan",
      "body": "Required for Sita Sharma on 'Australia — Student Visa'. It was due 6 days ago.",
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

**Notification** — `{ id, notification_type:[enum], priority:[enum], title, body, source_app, source_entity_type, source_entity_id?, source_api_path, due_at?, due_at_bs?:json, due_bucket:[enum], is_read, read_at?, status:[enum], resolution:[enum], resolved_at?, delivery_channel:[enum], delivery_state:[enum], generated_by:[enum], created_at }`

- **Identical on list and retrieve.** There are no retrieve-only extras — the feed row *is* the whole resource, so a client never needs a second request to render one.
- `source_app` + `source_entity_type` + `source_entity_id` identify the record the alert is about. They are **strings and a bare UUID, never a nested object**: this module holds no foreign key into any other module, so it cannot embed one. To show details, follow `source_api_path`.
- `source_api_path` is the **nearest retrievable endpoint** for the source, which is not always the entity itself. A `passport_expiring` alert has `source_entity_type: "passport_detail"` but a `source_api_path` pointing at the applicant, because a passport has no endpoint of its own. Treat it as "where to send the user", not as "the canonical URL of `source_entity_id`".
- `title` is at most **200 characters**; `body` is unbounded. Both are **plain text, English only** — there are no `_np` variants and no markup. Render them escaped; do not treat `body` as HTML.

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

So `source_app` takes one of `checklists`, `offers`, `applicants`, `uploaded_files`, `applicant_journeys`, and `source_entity_type` one of `checklist`, `checklist_item`, `offer`, `passport_detail`, `uploaded_file`, `applicant_journey`. **Neither is a closed enum in the database** — the column has no constraint, so a future module can add a value without a schema change. Treat both as open strings with the sets above as today's observed domain, and do not fail on an unrecognized one. As *filter* values, however, an unrecognized `source_app` simply matches nothing (it is a free-text exact match, not a choice field) and returns an empty page rather than a `400`.
- Following `source_api_path` is a **separate authorization question** answered by the owning module. Receiving an alert does not imply permission to open what it points at; a client should handle a 403 or 404 from that follow-up request.
- `is_read` and `due_bucket` are derived at read time, not stored. `is_read` is `read_at != null`.
- **Read state and status are independent.** An alert that has been read is still `active` work. Do not treat `is_read: true` as "handled". The converse also occurs: dismissing does **not** mark an alert read, so `status: "dismissed"` with `is_read: false` is a normal state a client must render.

### Lifecycle — the three states, and exactly what moves between them

There are only three transitions in this module, and only two actors can cause them:

| From | To | Caused by | Resulting `resolution` |
|---|---|---|---|
| *(nothing)* | `active` | the nightly sweep, or a source event | `""` |
| `active` | `dismissed` | **the recipient**, calling the dismiss endpoint | `dismissed_by_user` |
| `active` | `resolved` | **the nightly sweep**, on finding the source condition no longer true | `source_cleared` |

`resolved_at` is set on entry to either terminal state and is `null` while `active`. `resolution` is `""` while `active` and non-empty in both terminal states — it is a string field whose empty value means "not applicable yet", not a fourth enum member. Type it as `"source_cleared" | "dismissed_by_user" | ""`.

**There is no transition out of a terminal state, and no transition between the two of them.** A dismissed alert is never later rewritten to `resolved`, even when its source condition does clear — the sweep only ever touches `active` rows, so the user's decision is preserved as the reason it closed. Nothing anywhere returns an alert to `active`.

**Only sweep-raised alerts are ever auto-resolved.** A lifecycle alert (`generated_by: "signal"` — assignment, file rejection, journey stage, offer decision) records that something *happened*, and there is no ongoing condition left to re-check; resolving one would mean deciding a stage change had un-happened. Those alerts stay `active` until the recipient dismisses them, indefinitely. A client should therefore expect a permanently-growing set of active signal alerts unless the user clears them, and may reasonably present those types with dismissal foregrounded.

**One alert per condition per recipient, not one per night.** A still-overdue checklist item does **not** produce a new row each time the sweep runs — the sweep recognizes the alert it already raised and leaves it, including its original `created_at` and `title`. An alert is never rewritten after creation, so a `body` saying "due 6 days ago" keeps saying that as the days pass; the live truth is on the source record. The one way the same underlying problem produces a second alert is **escalation** — see the dismiss endpoint in §7.
- Three stored fields are deliberately **not** published: the internal deduplication key, the dismissing user (it always equals the recipient), and the recipient (every row returned belongs to the caller).

**FeedSummary** — `{ unread, active, by_priority:json, by_due_bucket:json }`

- All integers. `by_priority` is keyed by every `priority` value; `by_due_bucket` by every `due_bucket` value. Both are always fully zero-filled — a key is never absent.
- `unread` counts unread notifications **in any status**; `active` and both breakdowns count only `status: "active"`. So `unread` can legitimately exceed `active`: an alert resolved or dismissed before anybody read it is still unread.

**Which number belongs on a bell badge — read this before choosing.** The two count different populations, and neither is the obvious answer:

- **`unread`** is what the "mark all read" button drives to zero, so if the badge shows anything else that button will look broken. But it counts closed alerts nobody happened to read, so the badge can read `7` while an inbox opened with `?status=active` shows fewer rows.
- **`active`** matches the working inbox exactly, but nothing a user can click drives it to zero — only dismissing every alert does.

There is no third count combining them, and **this module does not provide "unread *and* active" in one call.** If that is the number the product wants, get it with `GET /api/v1/notifications/?status=active&is_read=false&page_size=1` and read `meta.count` — a second request, which is the cost of a figure this endpoint does not compute. The recommendation in §8 uses `unread` and pairs it with a `?status=active` inbox; a client that does so should be aware it is showing a badge whose population is slightly wider than the list behind it.

**BulkReadResult** — `{ marked_read }`

- One integer: how many notifications the call changed. Returned instead of the affected rows, which on this endpoint would be the largest and least useful response the module produces.

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
    "by_due_bucket": { "overdue": 3, "due_soon": 4, "later": 2, "none": 3 }
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

- `Notification.notification_type`: `checklist_item_due` | `checklist_item_overdue` | `missing_documents` | `missing_information` | `offer_response_due` | `offer_expired` | `passport_expiring` | `test_score_expiring` | `appointment_reminder` | `assignment_received` | `file_rejected` | `journey_stage_changed` | `journey_closed` | `offer_decided`
- `Notification.priority`: `low` | `normal` | `high` | `urgent`
- `Notification.status`: `active` | `dismissed` | `resolved`
- `Notification.resolution`: `source_cleared` | `dismissed_by_user` | `""` (empty while active)
- `Notification.due_bucket`: `overdue` | `due_soon` | `later` | `none`
- `Notification.delivery_channel`: `in_app` — the only value produced in this version
- `Notification.delivery_state`: `pending` | `delivered` | `failed` — only `delivered` is produced in this version, because in-app delivery completes the moment the row exists
- `Notification.generated_by`: `sweep` | `signal`

**Three `notification_type` values are declared but never produced in this version:** `missing_information`, `appointment_reminder`, and `test_score_expiring`. The first has no source — no module defines what "required information" is — and the other two belong to modules that do not exist yet. They are in the vocabulary so a client can handle the full enum once and so adding a generator later is not a breaking change. A client should render them rather than treat them as invalid, but will not receive one today.

**What each produced type means**, since several names are ambiguous from outside:

- `checklist_item_due` / `checklist_item_overdue` — one requirement on one applicant's checklist is approaching, or has passed, its due date.
- `missing_documents` — a checklist holds document requirements with **no due date at all** and nothing collected. Nobody is being chased for them, which is why they need their own alert: the two above are driven by dates these items do not have.
- `offer_response_due` / `offer_expired` — an **issued** offer's response deadline is approaching or has passed. `offer_expired` names the deadline, not the offer's status: the offer is still `issued` in the offers module, because nothing here changes business state.
- `passport_expiring` — an applicant's passport has expired or expires within roughly six months. Raised for already-lapsed passports too.
- `assignment_received` — **a checklist or a single checklist item has been assigned to you.** It is the only alert with a genuinely targeted recipient rather than a fan-out, and it is always about checklist work; there is no lead, applicant, or offer assignment in this project to alert on.
- `file_rejected` — an uploaded file's review came back rejected. The rejection reason is in `body`.
- `journey_stage_changed` / `journey_closed` — an applicant journey reached a new stage, or reached a terminal one (completed, closed, deferred).
- `offer_decided` — an offer reached a terminal status (accepted, rejected, withdrawn, deferred, expired).

**Priority is fixed per type**, assigned when the alert is raised: `offer_expired` → `urgent`; `checklist_item_overdue`, `offer_response_due`, `passport_expiring`, `test_score_expiring`, `file_rejected` → `high`; `journey_stage_changed` → `low`; everything else → `normal`. A client can rely on this mapping for display but should read `priority` from the payload rather than recompute it — a stored priority is not rewritten if the mapping is ever changed.

## 6. Dependency order

- A `Notification` needs a **recipient**, which is a user account `authenticate` issues (external module).
- A `Notification` needs a **source record** in `checklists`, `offers`, `applicants`, `uploaded_files`, or `applicant_journeys` (external modules) — the alert is raised *from* that record and cannot exist before it.
- Nothing in this module needs anything else in this module. There is no parent/child resource here, and no ordering constraint between calls.

**Start here:** there is nothing for a client to create. Call `GET /api/v1/notifications/summary/` to render a badge, then `GET /api/v1/notifications/?status=active` to render the inbox.

## 7. Endpoints

### Notification feed — `/api/v1/notifications/`

**Use it when:** rendering the alert inbox — the screen a staff member opens to see what needs attention today, and the per-record alert history reached from an applicant or checklist screen via `?source_entity_id=`.

**Methods:**

- `GET /api/v1/notifications/` — the caller's own feed, paginated, newest first (permission: `notifications.notification.list`, risk: medium)

**Send:** `none` — this endpoint accepts no body under any method. `POST`, `PATCH`, `PUT`, and `DELETE` all return `405`.

**Returns:** `list[Notification]`

**Requires state:**

- An authenticated Admin or Lead Manager session.
- Nothing else. The feed is valid and returns an empty array for a user who has never received an alert.

**Side effects:** none. Reading the feed does not mark anything read.

**Notes:**

- Scoped to the calling user. No authority can widen it.
- `status` absent returns **all** statuses including `dismissed` and `resolved`. Send `?status=active` for a working inbox.
- Alerts appear here without any client action, produced by a nightly deadline sweep and by events in the other modules. A client should poll `GET /summary/` for the badge rather than the full feed; there is no push channel, no websocket, and no long-poll in this version.

**Errors:**

- `VALIDATION_ERROR` (400) — an unrecognized enum value, a malformed UUID, or `due_within_days` outside 1–365

---

### Notification summary — `/api/v1/notifications/summary/`

**Use it when:** rendering the bell badge and the inbox's grouping headers. Two queries regardless of feed size — a client should never page the feed to produce a count.

**Methods:**

- `GET /api/v1/notifications/summary/` (permission: `notifications.notification.summary`, risk: low)

**Send:** `none`

**Returns:** `FeedSummary`

**Requires state:**

- An authenticated Admin or Lead Manager session.

**Side effects:** none.

**Notes:**

- Accepts `due_within_days` only. Every other query parameter is ignored, so the badge cannot disagree with itself between screens.
- `unread` may exceed `active` — see §4.

**Errors:**

- `VALIDATION_ERROR` (400) — `due_within_days` outside 1–365

---

### One notification — `/api/v1/notifications/<id>/`

**Use it when:** re-fetching a single alert after acting on it, or deep-linking into one from outside the inbox.

**Methods:**

- `GET /api/v1/notifications/<id>/` (permission: `notifications.notification.read`, risk: low)

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

**Use it when:** the user clicks "mark all as read" to clear the badge.

**Methods:**

- `POST /api/v1/notifications/read-all/` (permission: `notifications.notification.mark_all_read`, risk: low)

**Send:** `none` — the call takes no filters. It clears everything unread on the caller's feed.

**Returns:** `BulkReadResult`

**Requires state:**

- An authenticated Admin or Lead Manager session. Succeeds with `marked_read: 0` when nothing is unread.

**Side effects:** sets `read_at` on every unread notification belonging to the caller, **including dismissed and resolved ones**. That is intentional: clearing the badge must leave nothing unread, or the number returns on the next page load. Nothing is dismissed or resolved, and no other user's feed is touched.

**Errors:** `none` beyond the global auth failures.

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

- Moves the notification to a terminal state. It stays in the feed and is still returned by an unfiltered `GET /` — nothing is deleted.
- Writes an audit event in the `audit` module recording who dismissed what and when. This is the only endpoint in this module that writes outside its own table.
- **Suppresses this alert permanently — but not necessarily the underlying problem.** The nightly sweep will never re-raise *this* alert: the row holds its deduplication slot forever, so dismissing is not "hide until tomorrow". There is no snooze and no un-dismiss. What can still reach the user is **escalation**, and it is worth being precise about, because it is the one thing that makes "permanent" less than absolute: severity is part of what an alert is, so a checklist item dismissed while merely `checklist_item_due` will raise a **separate, new** `checklist_item_overdue` alert if it later passes its deadline. The dismissed row stays dismissed; a second row appears beside it. The reverse never happens — dismissing the overdue alert ends it, because there is no higher severity to escalate to. Present dismissal to the user as a decision.
- Does **not** change anything in the module that owns the source record. Dismissing an overdue-item alert does not complete, waive, or reschedule the checklist item; the work is still outstanding there.

**Notes:**

- The condition can still produce a *new* alert by escalation — an item dismissed while merely due-soon will alert again if it later becomes overdue, because that is a different alert type. That is the only path back.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404)
- `NOTIFICATIONS_ALREADY_TERMINAL` (409) — already dismissed or resolved; `details.status` carries the current value

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
2. `GET /api/v1/notifications/?source_entity_id=<record id>` → every alert the **calling user** received about that record, active and historical.
   - This is a partial history by design: alerts sent to other people are not visible. A client should not label this "all alerts for this record".

**Clearing the badge**

1. `POST /api/v1/notifications/read-all/` → returns `{ "marked_read": n }`.
2. `GET /api/v1/notifications/summary/` → `unread` is now `0`. `active` is unchanged: reading is not deciding, and the work is still on the desk.

## 9. Gaps

- **The feed cannot be ordered, and for an inbox that is the most consequential thing missing here.** There is no `ordering` parameter. Rows come back newest-created first, always — so an `urgent` offer-expiry alert raised last week sits below a `low` journey-stage alert raised this morning, and no request can reverse that. Sorting a single page client-side does not fix it, because the rows that should be on page 1 are on page 3. The workarounds are partial: `?priority=urgent` then `?priority=high` as separate sections, or `?due_bucket=overdue` first. A `?ordering=priority,due_at` parameter is the obvious fix and is not built.
- **No search.** There is no way to find "the alert about Sita" other than paging or filtering by `source_entity_id`, which requires already knowing the record.
- **No bulk action except all-or-one.** `read-all` takes no filters, and there is no "dismiss these five" or "dismiss all overdue".
- **Nothing is ever deleted, and there is no retention policy.** A long-lived account's unfiltered feed grows without bound, and with no ordering parameter the oldest rows are simply unreachable in practice. Always send `?status=active` unless the history is genuinely what is wanted.
- **`leads` produces no notifications at all.** Lead follow-up is a named part of a Lead Manager's job and half the user base are Lead Managers, yet no alert type covers it — the only alert a Lead Manager receives by targeted routing is `assignment_received` on checklist work. This is a real hole in the product, not a documentation gap.
- **No push channel.** There is no websocket, server-sent-event stream, or long-poll endpoint. A client must poll `GET /summary/`. No polling interval is recommended by this module, and no `ETag`, `Last-Modified`, or conditional-request support exists on any endpoint, so every poll is a full response. The project-wide authenticated rate limit is the only budget to plan against; there is no per-endpoint exemption for `/summary/` despite it being the endpoint designed to be polled.
- **Alerts resolve on a schedule, not on the event.** Finishing work in another module does not close the alert immediately — the nightly `sweep_notifications` job does. The exact run time is a deployment decision and is not exposed through the API, so a client cannot tell a user when an alert will clear.
- **No snooze, no un-dismiss, and no per-user mute.** Dismissal is one-way and there is no preference resource in this version. If the product needs "remind me tomorrow", it does not exist here yet.
- **No delivery beyond in-app.** `delivery_channel` and `delivery_state` are in the payload but only ever hold `in_app` and `delivered`. No email or SMS is sent by this version.
- **Three enum values are unproduceable** (`missing_information`, `appointment_reminder`, `test_score_expiring`) — see §5.
- **`source_api_path` is not a guaranteed-resolvable URL for `source_entity_id`.** It is the nearest retrievable endpoint, which for `passport_detail` is the applicant. A client cannot infer the entity's own URL from the pair.
- **Lifecycle alerts about a source record's *history* are lossy by design.** A journey moved back to a stage it already held raises nothing, and a file rejected, verified, and rejected again raises one alert. A client must not treat the feed as a complete event log — `audit` is that, and it is a different module.
- **Recipient routing is not documented in this contract and is not visible to a client.** Which staff member receives which alert is decided server-side (assignee first, falling back to every active Admin). A client cannot query, predict, or influence it, and there is no endpoint that reports it.
- **Whether an alert's underlying work is still outstanding is not in this payload.** `status: "active"` means the alert has not been closed, which is not the same as the checklist item still being incomplete between sweeps. To render the current truth, follow `source_api_path`.
