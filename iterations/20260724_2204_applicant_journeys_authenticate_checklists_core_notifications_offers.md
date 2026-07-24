# 20260724_2204 — notifications

## Notifications

## 1. Module

- **Name:** Notifications
- **Base path:** `/api/v1/notifications/`
- **Auth:** JWT bearer token on every endpoint; Admin and Lead Manager only, Superadmin refused on all seven. Every endpoint is scoped to the calling user's own notifications.

## 2. Conventions

- **Response:** `{ "success": true, "message": "...", "data": ..., "meta": {} }`
- **Error:** `{ "success": false, "error": { "code": "...", "message": "...", "details": {} }, "meta": {} }`
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when the token is missing or invalid; `NOTIFICATIONS_ACTOR_FORBIDDEN` (403) for a Superadmin. Both apply to all seven endpoints.
- **Pagination:** `GET /` only. `page`, `page_size` (default 20, max 100). `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `data` is a bare array. A page past the end returns 404 `NOT_FOUND` with message `Invalid page.`
- **IDs:** UUID strings, including in URL segments.
- **Times:** ISO 8601 UTC, `Z`-suffixed. `due_at` carries a `due_at_bs` sibling; `created_at` does not.
- **List/search/filter/order params:** `GET /` accepts `status`, `is_read`, `notification_type`, `priority`, `source_app`, `source_entity_id`, `due_bucket`, `due_within_days`, `date_from`, `date_to`, `fiscal_year`, `page`, `page_size`. `GET /summary/` honours `due_within_days` and validates the rest. No search parameter and no ordering parameter on either.

## 3. Models

- **Notification** — `{ id, notification_type:[enum], priority:[enum], title, body, source_app, source_entity_type, source_entity_id?, source_api_path, due_at?, due_at_bs?:json, due_bucket:[enum], is_read, read_at?, status:[enum], resolution:[enum], resolved_at?, delivery_channel:[enum], delivery_state:[enum], generated_by:[enum], created_at }`
  - Identical on list and retrieve — no retrieve-only extras.
  - `is_read` and `due_bucket` are derived at read time. `due_bucket` depends on the request's `due_within_days`.
  - `resolution` is `""` while `status` is `active` and non-empty in both terminal states.
  - `dedupe_key`, `dismissed_by`, and `recipient` are stored and not serialized.
- **FeedSummary** — `{ unread, active, by_priority:json, by_due_bucket:json }`
  - `unread` counts unread rows in any status; `active` and both breakdowns count only `active`, so `unread` may exceed `active`.
- **BulkReadResult** — `{ marked_read }`

## 4. Enums

- `Notification.notification_type`: `checklist_item_due` | `checklist_item_overdue` | `missing_documents` | `missing_information` | `offer_response_due` | `offer_expired` | `passport_expiring` | `test_score_expiring` | `appointment_reminder` | `assignment_received` | `file_rejected` | `journey_stage_changed` | `journey_closed` | `offer_decided`
- `Notification.priority`: `low` | `normal` | `high` | `urgent`
- `Notification.status`: `active` | `dismissed` | `resolved`
- `Notification.resolution`: `source_cleared` | `dismissed_by_user` | `""`
- `Notification.due_bucket`: `overdue` | `due_soon` | `later` | `none`
- `Notification.delivery_channel`: `in_app`
- `Notification.delivery_state`: `pending` | `delivered` | `failed` — only `delivered` is produced
- `Notification.generated_by`: `sweep` | `signal`
- `Notification.source_app`: `checklists` | `offers` | `applicants` | `uploaded_files` | `applicant_journeys` (observed — the column has no database constraint)
- `Notification.source_entity_type`: `checklist` | `checklist_item` | `offer` | `passport_detail` | `uploaded_file` | `applicant_journey` (observed — the column has no database constraint)

## 5. Dependency order

- A `Notification` needs a recipient user account (external module `authenticate`).
- A `Notification` needs a source record in `checklists`, `offers`, `applicants`, `uploaded_files`, or `applicant_journeys` (external modules).
- No resource in this module depends on another resource in this module.

**Start here:** nothing is created by a client. Call `GET /api/v1/notifications/summary/`.

## 6. Endpoints

### Notification — `/api/v1/notifications/`

**Use it when:** rendering the alert inbox, and rendering the per-record alert history from an applicant, checklist, or offer screen via `?source_entity_id=`.

**Methods:**

- `GET /api/v1/notifications/` — `notifications.notification.list`
- `GET /api/v1/notifications/<id>/` — `notifications.notification.read`

**Send:** `none` — no endpoint in this module accepts a request body.

**Returns:** `list[Notification]` | `Notification`

**Notes:**

- Scoped to the calling user. No authority can widen it; there is no `?recipient=` filter.
- A notification belonging to another user returns 404, not 403.
- `status` absent returns all statuses including `dismissed` and `resolved`.
- Newest first with `id` as a tiebreaker; not configurable.
- `POST`, `PATCH`, `PUT`, and `DELETE` return 405 on both routes.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404) — no such notification on the caller's own feed
- `VALIDATION_ERROR` (400) — unrecognized enum value, malformed UUID, `due_within_days` outside 1–365, or a `fiscal_year` that is not a `YYYY/YY` label

### Notification summary — `/api/v1/notifications/summary/`

**Use it when:** rendering a bell badge and the inbox's grouping headers without paging the feed.

**Methods:**

- `GET /api/v1/notifications/summary/` — `notifications.notification.summary`

**Send:** `none`

**Returns:** `FeedSummary`

**Notes:**

- Only `due_within_days` changes the result; the whole filter set is still validated.
- Two queries regardless of how many notifications the user holds.

**Errors:**

- `VALIDATION_ERROR` (400) — `due_within_days` outside 1–365, or any other filter value that fails validation

### Mark read — `/api/v1/notifications/<id>/read/`

**Use it when:** the user opens or expands an alert.

**Methods:**

- `POST /api/v1/notifications/<id>/read/` — `notifications.notification.mark_read`

**Send:** `none`

**Returns:** `Notification`

**Notes:**

- Idempotent; a second call keeps the first timestamp.
- Does not change `status`.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404)

### Mark unread — `/api/v1/notifications/<id>/unread/`

**Use it when:** the user wants an already-opened alert back in the unread count.

**Methods:**

- `POST /api/v1/notifications/<id>/unread/` — `notifications.notification.mark_unread`

**Send:** `none`

**Returns:** `Notification`

**Notes:**

- Calling it on an already-unread notification succeeds and changes nothing.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404)

### Mark all read — `/api/v1/notifications/read-all/`

**Use it when:** the user clears the badge.

**Methods:**

- `POST /api/v1/notifications/read-all/` — `notifications.notification.mark_all_read`

**Send:** `none` — the call takes no filters.

**Returns:** `BulkReadResult`

**Notes:**

- Marks every unread notification on the caller's feed read, including dismissed and resolved ones.
- Nothing is dismissed or resolved; no other user's feed is touched.
- Succeeds with `marked_read: 0` when nothing is unread.

**Errors:** `none`

### Dismiss — `/api/v1/notifications/<id>/dismiss/`

**Use it when:** the user decides a flagged item needs no action.

**Methods:**

- `POST /api/v1/notifications/<id>/dismiss/` — `notifications.notification.dismiss`

**Send:** `none` — no reason field.

**Returns:** `Notification` with `status: "dismissed"`, `resolution: "dismissed_by_user"`, and `resolved_at` set.

**Notes:**

- The notification must be `active`.
- Writes an audit event in the `audit` module.
- Permanently suppresses this alert — no later sweep raises it again. There is no un-dismiss.
- Escalation still applies: an item dismissed while `checklist_item_due` raises a separate `checklist_item_overdue` alert if it later passes its deadline.
- Changes nothing in the module that owns the source record.

**Errors:**

- `NOTIFICATIONS_NOTIFICATION_NOT_FOUND` (404)
- `NOTIFICATIONS_ALREADY_TERMINAL` (409) — already dismissed or resolved; `details.status` carries the current value

## 7. Flows

**Working the daily inbox**

1. `GET /api/v1/notifications/summary/` → badge from `unread`, section headers from `by_due_bucket`.
2. `GET /api/v1/notifications/?status=active` → the working inbox; group client-side on each row's `due_bucket`.
3. User opens an alert → `POST /api/v1/notifications/<id>/read/`.
4. User clicks through → follow the row's `source_api_path` into the owning module.
   - 403 or 404 from that module → the alert's `title` and `body` are all the user gets; receiving an alert does not grant access to the record.
5. User completes the work in the owning module.
   - The alert stays `active` until the next nightly sweep moves it to `resolved` / `source_cleared`.

**Clearing an alert that needs no action**

1. `GET /api/v1/notifications/?status=active` → find the alert.
2. `POST /api/v1/notifications/<id>/dismiss/` → `status` becomes `dismissed`.
   - `NOTIFICATIONS_ALREADY_TERMINAL` (409) → another session closed it; re-fetch with `GET /api/v1/notifications/<id>/`.
3. The alert remains under `?status=dismissed` and never returns to `active`.

**Clearing the badge**

1. `POST /api/v1/notifications/read-all/` → `{ "marked_read": n }`.
2. `GET /api/v1/notifications/summary/` → `unread` is `0`; `active` is unchanged.

**Reviewing the alert history for one record**

1. Take the record id from an applicant, checklist, or offer screen.
2. `GET /api/v1/notifications/?source_entity_id=<record id>` → every alert the calling user received about that record.
   - Partial by design: alerts sent to other staff are not returned.

## 8. Gaps

- No ordering parameter on the feed. Rows are always newest-created first, so an `urgent` alert raised last week sorts below a `low` alert raised this morning, and client-side sorting cannot fix it across pages.
- No search parameter.
- No push channel — no websocket, no server-sent events, no long-poll. No polling interval is recommended, and no `ETag` or conditional-request support exists on any endpoint.
- The nightly sweep's run time is not exposed, so a client cannot say when an alert will resolve.
- No snooze, no un-dismiss, no per-user mute or category preference.
- No delivery beyond in-app; `delivery_channel` and `delivery_state` only ever hold `in_app` and `delivered`.
- `missing_information`, `appointment_reminder`, and `test_score_expiring` are declared in the enum and produced by nothing.
- `source_api_path` is the nearest retrievable endpoint, not necessarily the URL of `source_entity_id` — for `passport_detail` it points at the applicant.
- Recipient routing is decided server-side and is neither queryable nor influenceable; no endpoint reports who else received an alert.
- Nothing is ever deleted and no retention policy exists, so an unfiltered feed grows without bound.
- `leads` produces no notifications of any kind.
- `status: "active"` means the alert is open, not that the underlying work is still outstanding; the two can disagree between sweeps.

---

## Authenticate

## 1. Module

- **Name:** Authenticate
- **Base path:** `/api/v1/auth/`
- **Auth:** unchanged this session.

## 2. Conventions

No changes this session.

## 3. Models

No changes this session.

## 4. Enums

No changes this session.

## 5. Dependency order

No changes this session.

## 6. Endpoints

No endpoints were added, changed, or retired this session. One internal selector was added — `get_active_admins()`, returning active Admin accounts — consumed by `notifications` for the recipient fan-out. It is not exposed over HTTP.

## 7. Flows

No changes this session.

## 8. Gaps

No changes this session.

---

## Checklists

## 1. Module

- **Name:** Checklists
- **Base path:** `/api/v1/checklists/`
- **Auth:** unchanged this session.

## 2. Conventions

No changes this session.

## 3. Models

No changes this session.

## 4. Enums

No changes this session. One internal constant was added — `UNRESOLVED_ITEM_STATUSES`, derived from the existing `ItemStatus` set — with no effect on any response.

## 5. Dependency order

No changes this session.

## 6. Endpoints

No endpoints were added, changed, or retired this session. One internal selector was added — `get_checklists_with_pending_documents()`, returning live checklists holding unresolved `document`-type items with no due date — consumed by `notifications` for the `missing_documents` alert. It is not exposed over HTTP.

## 7. Flows

No changes this session.

## 8. Gaps

No changes this session.

---

## Offers

## 1. Module

- **Name:** Offers
- **Base path:** `/api/v1/offers/`
- **Auth:** unchanged this session.

## 2. Conventions

No changes this session.

## 3. Models

No changes this session.

## 4. Enums

No changes this session. `OfferStatus.EXPIRED` is still set only by a person: the new nightly sweep raises an alert on a lapsed `response_deadline` but changes no offer status.

## 5. Dependency order

No changes this session.

## 6. Endpoints

No endpoints were added, changed, or retired this session.

## 7. Flows

No changes this session.

## 8. Gaps

No changes this session.

---

## Applicant Journeys

## 1. Module

- **Name:** Applicant Journeys
- **Base path:** `/api/v1/journeys/`
- **Auth:** unchanged this session.

## 2. Conventions

No changes this session.

## 3. Models

No changes this session.

## 4. Enums

No changes this session.

## 5. Dependency order

No changes this session.

## 6. Endpoints

No endpoints were added, changed, or retired this session. Saving a journey now additionally triggers a `notifications` receiver, which is invisible from this module's responses.

## 7. Flows

No changes this session.

## 8. Gaps

No changes this session.

---

## Core

## 1. Module

- **Name:** Core
- **Base path:** `/api/v1/`
- **Auth:** unchanged this session.

## 2. Conventions

No changes this session.

## 3. Models

No changes this session.

## 4. Enums

No changes this session.

## 5. Dependency order

`notifications` was added to `INSTALLED_APPS` and mounted at `/api/v1/notifications/`.

## 6. Endpoints

No `core`-owned endpoints were added, changed, or retired this session. The project-level `INTEGRATION.md` gained the `notifications` inventory row and dependency-graph edge, and three statements in its §10 access-model section were corrected: the access-shape table gained a fifth row for caller-scoped reads, the claim that `uploaded_files` is the only app scoping per record was narrowed, and the claim that every app other than `leads` returns 404 only for genuinely absent records was corrected to name three apps.

## 7. Flows

No changes this session.

## 8. Gaps

No changes this session.
