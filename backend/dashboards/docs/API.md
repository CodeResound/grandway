# API Documentation — Dashboards

**App:** `dashboards`
**Version:** 1.0.0
**Base prefix:** `/api/v1/dashboard/` (singular path, plural app — one dashboard, eight sections)
**Auth:** Bearer access JWT on every endpoint (`IsAuthenticated`). Authority rules are enforced inline per §9 via `access.py` — Admin and Lead Manager only, Superadmin denied everywhere.
**Throttle:** Project DRF defaults only. No custom scopes — see the AI debugging notes below for why this is a live question rather than a settled one.
**Access level:** Read-only for Admin and Lead Manager, with one exception: `activity` (§1.8) is Admin-only, because it returns the central audit log verbatim rather than a figure derived from an already-scoped selector. Nothing here is public, and no endpoint accepts a write of any kind.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial API documentation — 8 read-only section endpoints sharing one filter set |

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

**Paginated list `meta`** (the `activity` endpoint only):
```json
{ "count": 1482, "page": 1, "page_size": 20, "next": "https://host/api/v1/dashboard/activity/?page=2", "previous": null }
```

**AI debugging notes (app-wide):**

- **This app owns no table and writes nothing.** There is no `models.py`, no `migrations/` directory, and no `services.py`. If you are looking for where a number is stored, it is not stored — every figure is derived at request time.
- **It never queries another app's tables.** Every figure comes from a summary selector in the app that owns the rows (§4). `dashboards/selectors.py` composes; it does not query. A bug in a count is almost always in the owning app's selector, not here.
- Every endpoint returns 401 unauthenticated and 403 `DASHBOARDS_ACTOR_FORBIDDEN` for a Superadmin. Neither is repeated per endpoint.
- **Every endpoint accepts the same filter set** (§1.0), validated once by `DashboardFilterSerializer`. Not every section honours every filter — the unhonoured ones are listed per endpoint and in `INTEGRATION.md` §9.
- **Scoping is inherited, never re-implemented here.** Lead figures pass through `leads.selectors.get_leads_for_actor`; file figures pass through `uploaded_files.selectors.get_visible_files`. The consequence: **an Admin and a Lead Manager calling the same URL legitimately see different numbers**, and only `workload.is_scoped_to_caller` marks it. A client reporting this as a bug is reporting the scoping working.
- **No caching.** Every request runs live queries. There is no ETag, no `Last-Modified`, and no stored rollup, deliberately (§37 pushes back on infrastructure, and §28 item 15 gates it).
- **Throttling is an open question, not a settled one.** These are the most query-expensive read endpoints in the project — `summary` alone issues roughly a dozen aggregates — and they carry only the project's default rates. If dashboard load becomes a problem, a per-view scope here is the first thing to add (§6, rate limiting).
- Worklist sections return at most **10** rows with an accurate `total`. There is no pagination on the seven object sections; getting past the first 10 means calling the owning app's list endpoint.

---

## 1. Dashboard sections

All eight endpoints share one request contract, documented once here and referenced by each sub-section below.

### 1.0 Shared query parameters

| Param | Type | Notes |
|-------|------|-------|
| `date_from` | date `YYYY-MM-DD` | Inclusive lower bound |
| `date_to` | date `YYYY-MM-DD` | **Inclusive** upper bound. Converted to a half-open SQL bound once, in `core.querying.resolve_window` |
| `fiscal_year` | `YYYY/YY` | Nepali fiscal year (§39.4). The coarse control; an explicit `date_from`/`date_to` overrides it rather than being widened back |
| `country` | UUID | An `institutions.Country` id |
| `institution` | UUID | An `institutions.Institution` id. **Honoured by offer figures only** |
| `owner` | UUID | An `authenticate.User` id. **Honoured by checklist item worklists only** |
| `journey_stage` | enum | Accepted and validated, **currently unused by every section** |
| `offer_status` | enum | Accepted and validated, **currently unused by every section** |
| `document_status` | enum | Accepted and validated, **currently unused by every section** |
| `checklist_status` | enum | Accepted and validated, **currently unused by every section** |
| `due_within_days` | int 1–90 | Default 7. The "due soon" horizon |
| `passport_within_days` | int 1–730 | Default 180. The expiring-passport horizon, deliberately far longer |

**Validation rules:**
- `date_from > date_to` → 400 with `details.date_to`. Returning zero rows instead would look exactly like a quiet period, and the user would read the dashboard as reporting no work rather than as refusing their input.
- A malformed `fiscal_year` → 400 with `details.fiscal_year`. Validated here rather than in seven selectors, so one mistake produces one error shape.
- `due_within_days` outside 1–90 → 400. A year-long "due soon" window is the whole table, not a worklist.
- A malformed UUID in `country`/`institution`/`owner` → 400. A **well-formed** id that matches nothing returns 200 with empty data — a nonexistent country is not a client error.

**Day boundaries are Kathmandu days**, not UTC days (§39.5). Comparing a naive date against a `DateTimeField` would shift every window by 5¾ hours and put a record created at 09:00 NPT in the previous day's bucket.

### 1.1 Summary — `GET /api/v1/dashboard/summary/`

**Policy key(s):** `dashboards.summary.read` (risk: low)
**Request query params:** §1.0
**Response:** `DATA_CONTRACT.md` §1.
**Business rules:** every figure here is duplicated in a fuller section below — this is the strip a user reads first, never the only place a number appears. `alerts.stale_leads` is owner-scoped for a Lead Manager; the other seven alerts are not.
**Query access pattern:** the heaviest endpoint in the app — roughly a dozen aggregate queries across seven apps, each a `COUNT` over an indexed predicate. No row is serialized. `checklist_selectors.get_overdue_checklist_items` and its siblings are counted, not evaluated, so the `select_related` chain they carry costs nothing here.
**Error codes:** `DASHBOARDS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

### 1.2 Today's work — `GET /api/v1/dashboard/today/`

**Policy key(s):** `dashboards.today.read` (risk: low)
**Request query params:** §1.0. Honours `due_within_days`, `country`, `owner`, `institution`, and the date window.
**Response:** `DATA_CONTRACT.md` §2.
**Business rules:**
- **Overdue and due-soon are disjoint.** An already-late item appears in `overdue_checklist_items` only, so the two totals may be summed safely.
- An item or offer with **no due date never appears**. Nothing is late about a deadline that was never set — which also means this is not "all outstanding work".
- Only `draft`/`active` checklists contribute items; a completed or archived checklist's items are finished work.
- `blocked` items **do** appear when overdue — a stuck requirement is still not done (`ChecklistItem.is_resolved`).
- Only an `issued` offer can await a response. The comparison is against today in Nepal, mirroring `Offer.is_response_overdue`.
- `stale_leads` means no follow-up in 7 days, falling back to creation date for a lead never followed up. **Not** configurable via `due_within_days` — a lead has no due date, and silence is the only signal there is.
- `documents_in_progress` is ordered oldest-edit-first (a stalled-work list) and ignores `country` entirely — a document belongs to a person, not a study plan.
- `files_awaiting_verification` is ordered oldest-upload-first: a review queue, where newest-first would starve the backlog.

**Query access pattern:** six worklists, each a `COUNT` plus a `LIMIT 10` slice. Every row-returning selector carries its owning app's `select_related` chain (`checklist__journey__applicant`, `journey__applicant`, and so on), so serializing ten rows never fires a query per row. The heaviest join is `ChecklistItemRow`, which reaches four tables deep to name the applicant.
**Error codes:** `DASHBOARDS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

### 1.3 Pipeline health — `GET /api/v1/dashboard/pipeline/`

**Policy key(s):** `dashboards.pipeline.read` (risk: low)
**Request query params:** §1.0. Honours `country`, `institution` (offers only), and the date window.
**Response:** `DATA_CONTRACT.md` §3.
**Business rules:**
- Every map is **zero-filled across its full enum**. An empty stage shows as `0`, never as an absent key — a funnel that hides its dead ends cannot show you one.
- **Windowed on creation date**: "of the records created in this window, where has each got to". A journey running two years is absent from a one-month window even though it is live today. The date controls would otherwise be silently inert on this section.
- `documents_by_status_is_country_filtered` is always `false`, returned so a client can label that panel honestly when a country filter is applied elsewhere on screen.
- `files_by_verification` excludes archived and superseded files — live work, not history.
- `leads_by_stage` is owner-scoped for a Lead Manager; the other six are not.

**Query access pattern:** seven `GROUP BY` aggregates, one per app. Each is a single query served by that app's status/stage index (`lead_stage_recent_idx`, `journey_stage_recent_idx`, `offer_status_recent_idx`, `cl_status_recent_idx`). The country filter on applicants traverses the reverse `journeys` relation and applies `distinct()`.
**Error codes:** `DASHBOARDS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

### 1.4 Blockers and risk — `GET /api/v1/dashboard/blockers/`

**Policy key(s):** `dashboards.blockers.read` (risk: **medium** — it names specific applicants who are stuck, a sharper disclosure than an aggregate)
**Request query params:** §1.0. Honours `country`, `owner`, `passport_within_days`.
**Response:** `DATA_CONTRACT.md` §4.
**Business rules:**
- Grouped by cause, deliberately not merged into one ranked list — the five call for five different people to act.
- `journeys_without_a_checklist` is the safety net behind automatic inheritance: a journey names a destination but nobody authored that country's template, so no checklist was created **and no error was raised**. This is the only place that silence becomes visible.
- `overdue_offers` contains **only** deadlines already past; the approaching ones are in §1.2, where they can still be acted on. The two do not overlap.
- `expiring_passports` **includes already-expired ones** — the applicant whose passport lapsed last month is the most blocked person on the list, and a forward-only query would drop exactly them. Archived applicants are excluded.
- `rejected_files` shows only current versions: uploading a replacement supersedes the rejected file, which drops off on its own.

**Query access pattern:** five worklists, same `COUNT` + `LIMIT 10` shape as §1.2. `get_journeys_missing_checklist` is the only one using an `EXCLUDE` subquery rather than an indexed predicate, and is the most expensive query in the app. `get_expiring_passports` is served by `PassportDetail.expiry_date`'s index.
**Error codes:** `DASHBOARDS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

### 1.5 Workload by owner — `GET /api/v1/dashboard/workload/`

**Policy key(s):** `dashboards.workload.read` (risk: **medium** — it discloses how much work each named staff member carries, which is about people rather than records)
**Request query params:** §1.0. Honours `country` and the date window.
**Response:** `DATA_CONTRACT.md` §5.
**Business rules:**
- **`is_scoped_to_caller` is `true` for a Lead Manager**, whose `leads` list then holds at most one row — their own. That is the scoping working, not a degraded view: the section answers "how is work distributed", and a Lead Manager's honest answer is "here is mine".
- **The three lists are not joinable and must not be summed.** An open lead is a prospect being worked, an overdue checklist item is a task already late, and an offer awaiting response is someone else's decision to chase. A combined total would mean nothing.
- `checklist_items` includes an **unassigned** bucket (`owner_id: null`). Work nobody owns is the most likely to be missed, so a workload view that hid it would hide the worst case it exists to surface.
- `offers` counts by **who recorded the offer** — an offer has no assignee, and `created_by` is the only ownership this app records.
- `checklist_items` is not owner-scoped even for a Lead Manager, because checklists are shared.

**Query access pattern:** three `GROUP BY` aggregates over the owner column, served by `lead_owner_recent_idx` and `cl_item_assignee_idx`. The checklist aggregate additionally computes overdue and blocked counts as conditional `Count` annotations in the same pass, rather than three queries.
**Error codes:** `DASHBOARDS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

### 1.6 Source and conversion — `GET /api/v1/dashboard/conversion/`

**Policy key(s):** `dashboards.conversion.read` (risk: **medium** — intake performance by channel is commercially sensitive in a way a stage count is not)
**Request query params:** §1.0. Honours `country` and the date window.
**Response:** `DATA_CONTRACT.md` §6.
**Business rules:**
- **The four rates are not one funnel and must not be multiplied together.** Each is windowed on its own stage's dates, so a lead that arrived in Ashadh and converted in Shrawan counts toward Ashadh's intake and Shrawan's conversions. Rendering them as a single funnel chart would report something the data does not say.
- Every `percent` is `null` — never `0` — when its denominator is `0`. "Nobody arrived" and "people arrived and none converted" are different facts, and a zero would present the first as the second.
- `by_source` lists only sources with at least one lead in the window; a channel nobody came through contributes nothing to a conversion comparison and would bury the ones that matter.
- `by_source` and `lead_to_applicant` are owner-scoped for a Lead Manager while the other three rates are not, so **a Lead Manager's four rates are not internally consistent with one another**.

**Query access pattern:** one `GROUP BY` over lead source with three conditional `Count` annotations, plus five scalar counts. `count_applicants_with_a_journey` and `count_journeys_with_an_offer` are `DISTINCT` counts on the foreign key — a person pursuing three objectives converted once, and a journey collecting four offers converted once.
**Error codes:** `DASHBOARDS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

### 1.7 Final outcomes — `GET /api/v1/dashboard/outcomes/`

**Policy key(s):** `dashboards.outcomes.read` (risk: low)
**Request query params:** §1.0. Honours `country` and the date window.
**Response:** `DATA_CONTRACT.md` §7.
**Business rules:**
- **`journey_outcomes` and `offer_decisions` are windowed on when the thing *ended*** (`closed_at`, `decided_at`), not when it started. A journey opened last year and closed this month belongs to this month. `journeys_completed`/`journeys_closed` are windowed on creation, like §1.3 — **so this section and Pipeline can legitimately disagree about the same journey**, and that is not a bug.
- `journey_outcomes` counts only journeys carrying an outcome; live journeys contribute to nothing here.
- `offer_decisions` has keys only for the five terminal statuses — `draft` and `issued` are not decisions and never appear.

**Query access pattern:** two `GROUP BY` aggregates plus reuse of the stage and status maps already computed for §1.3's selectors. No row is serialized.
**Error codes:** `DASHBOARDS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

### 1.8 Recent activity — `GET /api/v1/dashboard/activity/`

**Policy key(s):** `dashboards.activity.list` (risk: low)
**Request query params:** §1.0, plus `page` and `page_size` (max 100). **Only `fiscal_year` is honoured** — every other filter is accepted, validated, and ignored.
**Response:** paginated array of `DATA_CONTRACT.md` §8.
**Business rules:**
- The only paginated section, and the only one whose `meta` carries page data.
- **Admin only — the one section a Lead Manager may not read.** This endpoint returns rows from the central audit log rather than figures derived from an app that already scoped them, so it carries `audit`'s own access rule (`is_staff`, per `audit/docs/API.md` §1) in addition to this app's. A Lead Manager receives `DASHBOARDS_ACTOR_FORBIDDEN` (403), matching what `GET /api/v1/audit/events/` already returns them.
- **Not narrowed by the caller's authority, for those who may read it.** The audit log is not owner-scoped anywhere in the project, so an Admin sees every event including those actioned by others. Access here is binary, not a scope.
- *Superseded guidance:* until 2026-08-01 this section documented itself as readable by a Lead Manager, on the stated grounds that `GET /api/v1/audit/events/` is an endpoint "the same users may already call". That was never true of a Lead Manager, and the endpoint leaked the log to them. A client that relied on the old behaviour must treat activity as Admin-only.
- `action` values are contributed by every app and are not a fixed set. Render `summary` as the label rather than branching on `action`.

**Query access pattern:** a single ordered scan of `audit_auditevent`, served by the `created_at` index, sliced by the shared paginator. No joins — the actor is denormalized onto the event as `actor_label`.
**Error codes:** `DASHBOARDS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

---

## 2. Error codes

| Code | HTTP | Meaning |
|------|------|---------|
| `DASHBOARDS_ACTOR_FORBIDDEN` | 403 | A Superadmin called any of the eight endpoints, **or** a Lead Manager called `activity` (§1.8 — Admin-only, because it returns the central audit log rather than a derived figure) |
| `DASHBOARDS_FILTER_INVALID` | 400 | Reserved for a filter rejection this app raises itself. **Not currently emitted** — every filter failure today is caught by the serializer and surfaces as the global `VALIDATION_ERROR`. Declared so the code is stable if a future filter needs a domain-specific refusal |
| `VALIDATION_ERROR` | 400 | A malformed or contradictory filter value; `details` is keyed by the filter field name |
