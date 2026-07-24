# API Documentation — Notifications

**App:** `notifications`
**Version:** 1.0.0
**Base prefix:** `/api/v1/notifications/`
**Auth:** JWT bearer token on every endpoint. Admin and Lead Manager only; Superadmin is refused on every route (`CLAUDE.md` §9, `access.py`).
**Throttle:** project defaults. No endpoint here is public, and none performs an expensive operation — the heaviest is a two-query aggregate.
**Access level:** Staff-only, and **own-recipient only** — see §1 below.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial API documentation — seven endpoints, no authoring surface |
| 1.0.1 | 2026-07-24 | AI (Claude Opus 4.8) | Corrections from the §19.5 consumer-contract review. The feed filter `type` was renamed `notification_type` to match its payload field (every other parameter already did); a malformed `?fiscal_year=` was returning **500** and is now validated in the serializer; documented the date-parameter formats and their Kathmandu-midnight boundaries, and that `/summary/` validates the whole filter set rather than ignoring it |

---

## Generic envelopes (referenced throughout)

**Success:**
```json
{ "success": true, "message": "...", "data": { ... }, "meta": {} }
```

**Error:**
```json
{ "success": false, "error": { "code": "...", "message": "...", "details": {} }, "meta": {} }
```

**AI debugging notes (app-wide) — read these before the endpoints:**

1. **Every lookup is recipient-scoped before it is id-scoped.** `selectors.get_own_notification` filters by `recipient` first. A notification that exists but belongs to another user is `None` to this app, and the view answers **404, not 403**. This is deliberate: a 403 would confirm the id exists on somebody else's feed, and a notification title names an applicant and the document they are missing. If you are debugging an unexpected 404, check the recipient before checking the id.
2. **There is no create, update, or delete endpoint, and there will not be one.** Notifications are produced by `sweep_notifications` and by the five `post_save` receivers in `signals.py`. A `POST` to the feed returns 405. If a notification is missing, the bug is in a generator, not in the API.
3. **`due_bucket` and `is_read` are derived at read time**, never stored. `due_bucket` is computed against a single clock resolved once per response, so a page straddling a boundary cannot split two identically-due rows. If a bucket looks wrong, compare `due_at` to the response's own moment rather than to the database.
4. **`?is_read=` is the one filter that can silently invert a query.** DRF reads a query string as HTML input and resolves a *missing* `BooleanField` to `False`. `views._search_params` intersects validated data with the keys actually supplied, which is what stops a plain `GET /` from meaning "unread only". Do not bypass that helper.
5. **Anything a client cannot see is intentional.** `dedupe_key`, `dismissed_by`, and `recipient` are stored and withheld — see `DATA_CONTRACT.md` §1.

---

## 1. Access model — the app-wide rule

Every endpoint below operates on **the calling user's own notifications and nothing else.** An Admin cannot list, read, or act on another user's feed through this API.

This is stricter than every other app in the project, and the reasoning is in `access.py` in full. In short: everywhere else the record is a fact about the business, legitimately shared between staff; a notification is a fact about *one person's queue* — what they were told, what they read, what they decided to make go away. Reading somebody else's is closer to reading their unread mail than to reading a shared applicant file, and it discloses nothing about the business an Admin cannot already reach through `checklists`, `offers`, `applicants`, and `uploaded_files` directly. Cross-user inspection lives in Django admin, where it is a deliberate act by a named superuser.

Two consequences a client author must plan for:

- There is no "notifications for user X" endpoint, and no `?recipient=` filter.
- A notification id from somebody else's feed is indistinguishable from a made-up one.

---

## 2. Notification Feed

### 2.1 List own notifications — `GET /api/v1/notifications/`

**Policy key(s):** `notifications.notification.list` (risk: medium)
**Response:** paginated array of the read shape in `DATA_CONTRACT.md §1`, plus the derived `is_read`, `due_at_bs`, and `due_bucket` fields.

**Query parameters:**

| Param | Values | Notes |
|---|---|---|
| `status` | `active`, `dismissed`, `resolved` | Absent means **all**, deliberately — see business rules |
| `is_read` | `true`, `false` | Absent means all |
| `notification_type` | any type value | Named for the field, not shortened to `type` — every other parameter here matches its payload field, and the odd one out is a guaranteed client bug |
| `priority` | `low`, `normal`, `high`, `urgent` | |
| `source_app` | e.g. `checklists` | Exact string match |
| `source_entity_id` | UUID | "Every alert about this record", for the caller |
| `due_bucket` | `overdue`, `due_soon`, `later`, `none` | Computed against `due_at` |
| `due_within_days` | 1–365, default 7 | The boundary between `due_soon` and `later`. Applies to the filter **and** to the `due_bucket` rendered on every row of the response |
| `date_from`, `date_to`, `fiscal_year` | `YYYY-MM-DD`, `YYYY-MM-DD`, `YYYY/YY` | Windowed on `created_at`. `date_to` is inclusive; boundaries are Kathmandu midnight (§39.5). A malformed `fiscal_year` is rejected in the serializer — it reached the selector and surfaced as a 500 until the §19.5 review asked what format it took |
| `page`, `page_size` | default 20, max 100 | |

**Error codes:** `NOTIFICATIONS_ACTOR_FORBIDDEN` (403 — Superadmin); `VALIDATION_ERROR` (400 — an unrecognized enum value or an out-of-range `due_within_days`).

**Business rules:**

- **The feed is not narrowed to `active` by default.** `concepts/notifications.txt` requires the alert history survive after the source issue is fixed; defaulting to `active` would put that history behind a parameter nobody knew to pass. A client rendering a working inbox should send `?status=active` explicitly.
- Ordering is newest first, with `id` as a tiebreaker. There is no ordering parameter — a non-unique sort key under page pagination lets a row appear on two pages or on none, so the tiebreaker is not optional and not configurable.
- Filters combine with AND.

**Query access pattern:** `selectors.get_feed` → `filter_feed`. Backed by `notif_feed_idx` `(recipient, status, -created_at)` for the common case and `notif_source_idx` for `?source_entity_id=`. `select_related("recipient")` is applied at the root, so a page is one query plus the count. No N+1 exists here because the serializer touches no relation — every field a client sees is a local column or is derived from one.

### 2.2 Read own summary — `GET /api/v1/notifications/summary/`

**Policy key(s):** `notifications.notification.summary` (risk: low)
**Response:** the `FeedSummary` payload — `DATA_CONTRACT.md`, Request/Response Payload Contracts.

**Query parameters:** `due_within_days` is the only one that changes the result — this endpoint answers "what is on my desk", and a summary that could be filtered would produce a badge that disagreed with itself between screens. The whole filter set is still **validated**, though, so `?status=bogus` returns 400 rather than being silently ignored: a client sending a parameter this endpoint will not honour has made a mistake worth hearing about.

**Error codes:** `NOTIFICATIONS_ACTOR_FORBIDDEN` (403).

**Business rules:**

- `unread` counts unread rows **in any status**; every other figure is scoped to `active`. An alert resolved before anybody read it still deserves to be noticed once.
- Every count is zero-filled across the full priority and bucket vocabulary. A missing key and a zero are the same fact to a human and different facts to a client that indexes into the dict.

**Query access pattern:** `selectors.get_feed_summary` — one `aggregate()` with conditional `Count`s plus one `count()`, so it is two queries regardless of how many notifications the user holds. This is the point of the endpoint: the alternative is a client paging the whole feed to render one number.

### 2.3 Read one notification — `GET /api/v1/notifications/<id>/`

**Policy key(s):** `notifications.notification.read` (risk: low)
**Response:** the read shape in `DATA_CONTRACT.md §1`.
**Error codes:** `NOTIFICATIONS_ACTOR_FORBIDDEN` (403); `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404 — no such notification **on the caller's feed**, including one that exists on somebody else's).

---

## 3. Read State

### 3.1 Mark read — `POST /api/v1/notifications/<id>/read/`

**Policy key(s):** `notifications.notification.mark_read` (risk: low)
**Request:** no body.
**Response:** the updated notification.
**Error codes:** `NOTIFICATIONS_ACTOR_FORBIDDEN` (403); `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404).

**Business rules:**

- Idempotent, and a second call **keeps the first timestamp**. "When did they first see this" is the question a read receipt answers; refreshing it on every page load would make it answer "when did they last look at the list".
- Does not change `status`. Reading is not deciding — an alert someone has read is still active work.

### 3.2 Mark unread — `POST /api/v1/notifications/<id>/unread/`

**Policy key(s):** `notifications.notification.mark_unread` (risk: low)
**Request:** no body.
**Response:** the updated notification.
**Error codes:** as §3.1.
**Business rules:** clears `read_at`. Offered because an inbox without it punishes clicking through a list — the user who opens something they cannot deal with now needs a way to put it back.

### 3.3 Mark all read — `POST /api/v1/notifications/read-all/`

**Policy key(s):** `notifications.notification.mark_all_read` (risk: low)
**Request:** no body.
**Response:**
```json
{ "success": true, "message": "Notifications marked read.", "data": { "marked_read": 7 }, "meta": {} }
```
**Error codes:** `NOTIFICATIONS_ACTOR_FORBIDDEN` (403).

**Business rules:**

- The concept file's "bulk clear for low-priority items", implemented as clear *everything unread* rather than a priority-scoped clear. A partial clear leaves a non-zero badge after the user asked for zero, and the button that does not do what it says is the one people stop trusting.
- **Not narrowed to `active`.** Clearing the badge must actually leave nothing unread, or the number the user just cleared returns on their next page load.
- Nothing is dismissed or resolved.

**Query access pattern:** one `UPDATE` over `selectors.get_unread`, not a loop. This is the action a user takes when their feed has got away from them — exactly when it is longest.

---

## 4. Dismissal

### 4.1 Dismiss — `POST /api/v1/notifications/<id>/dismiss/`

**Policy key(s):** `notifications.notification.dismiss` (risk: medium)
**Request:** no body.
**Response:** the notification in its terminal state — `status: "dismissed"`, `resolution: "dismissed_by_user"`, `resolved_at` set.
**Error codes:** `NOTIFICATIONS_ACTOR_FORBIDDEN` (403); `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404); `NOTIFICATIONS_ALREADY_TERMINAL` (409 — already dismissed or resolved; `details.status` carries the current value).

**Business rules:**

- **Dismissal is permanent in effect.** The row keeps its `dedupe_key` forever, so no later sweep raises the same condition again. A client should present this as a decision, not as "hide for now" — there is no snooze in v1.
- The one action in this app that writes an `audit` event (`notification_dismissed`). Creating a notification is not audited — the row *is* the record, and auditing each one would double the nightly sweep's write volume to say the system told somebody something.
- Refusing an already-terminal notification with 409, rather than returning 200 for a write it did not perform, is deliberate: two clients on the same feed, or one holding a stale list, otherwise never learn the server disagrees with them.
- The condition can still re-alert through **escalation** — an overdue item that was dismissed while merely due-soon carries a different type and therefore a different key. That is the only re-entry path.

---

## 5. Generation (not an endpoint — context for debugging)

No client can create a notification. If one is missing, look here:

- **Deadline alerts** come from `python manage.py sweep_notifications`, intended to run nightly from cron. It reads the owning apps' own selectors (`checklists`, `offers`, `applicants`) and never re-implements their definition of "overdue". Run it with `--dry-run` to see what it would raise without writing.
- **Lifecycle alerts** come from `post_save` receivers on `checklists.Checklist`, `checklists.ChecklistItem`, `uploaded_files.UploadedFile`, `applicant_journeys.ApplicantJourney`, and `offers.Offer`. They honour `settings.DISABLE_SIGNALS` and defer to `transaction.on_commit`, so nothing appears until the triggering transaction commits — a common source of "the alert did not fire" in a test written on `TestCase` rather than `TransactionTestCase`.
- **A silent generator failure is audited**, not swallowed: look for `notification_generation_failed` in the audit log with `success=false`. Without that record, "the passport sweep has been broken for a week" and "no passports are expiring" are the same observation.
- **Three declared types have no generator**: `missing_information`, `appointment_reminder`, `test_score_expiring`. Nothing produces them. See `DATA_CONTRACT.md`, Deliberate Deviations.

---

## Error code reference

All codes are defined in `notifications/constants.py`.

| Code | HTTP | Notes |
|---|---|---|
| `NOTIFICATIONS_ACTOR_FORBIDDEN` | 403 | The caller's authority may not use the feed — Superadmin. The only 403 this app returns |
| `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` | 404 | No such notification on the caller's own feed. Also returned for another user's notification, deliberately, so an id cannot be probed for existence |
| `NOTIFICATIONS_ALREADY_TERMINAL` | 409 | Dismissing something already dismissed or resolved. `details.status` carries the current status |

This app declares **three** codes and no more. Filter validation is answered by the project-wide `VALIDATION_ERROR` (400) from the global handler, which names the offending field — more useful than an app-specific code saying only "a filter was wrong". `AUTHENTICATION_REQUIRED` (401) applies to every route and comes from the same place.
