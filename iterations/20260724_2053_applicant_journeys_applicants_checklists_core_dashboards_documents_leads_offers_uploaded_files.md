# Iteration — 2026-07-24 20:53

## Dashboards

## 1. Module

- **Name:** Dashboards — the operational command centre, summarising every other app. Owns no table and writes nothing.
- **Base path:** `/api/v1/dashboard/`
- **Auth:** Bearer access JWT on every endpoint. Admin and Lead Manager only; Superadmin is rejected with 403 everywhere.

## 2. Conventions

- **Response:** the standard project envelope — `{ success, message, data, meta }`. Seven sections return a single object under `data`; only `activity` returns an array.
- **Error:** `{ success: false, error: { code, message, details }, meta: {} }`.
- **Auth failures:** 401 unauthenticated (produced by the authentication framework, shape not documented here). 403 `DASHBOARDS_ACTOR_FORBIDDEN` for a Superadmin on any of the eight endpoints.
- **Pagination:** applies to `activity` only. `page` and `page_size` (default 20, max 100, clamped not rejected); `meta` carries `count`, `page`, `page_size`, `next`, `previous`. The other seven sections carry `meta: {}`.
- **Worklist previews:** sections holding records return `{ total, has_more, items }`. `total` is the real backlog; `items` is capped at 10.
- **IDs:** UUID strings.
- **Times:** ISO 8601 UTC for datetimes, `YYYY-MM-DD` for dates. User-facing dates carry a `<field>_bs` Bikram Sambat sibling.
- **List/search/filter/order params:** one shared set on all eight endpoints — `date_from`, `date_to`, `fiscal_year`, `country`, `institution`, `owner`, `journey_stage`, `offer_status`, `document_status`, `checklist_status`, `due_within_days`, `passport_within_days`. `date_to` is inclusive. Day boundaries are Kathmandu days. Ordering is fixed per section and never client-controlled.

## 3. Models

- **Preview** — `{ total, has_more, items:[…] }`
- **OwnerRow** — `{ owner_id?, owner_username, owner_display_name }`
- **LeadWorkloadRow** — `{ owner_id?, owner_username, owner_display_name, open_leads }`
- **ChecklistWorkloadRow** — `{ owner_id?, owner_username, owner_display_name, open_items, overdue_items, blocked_items }`
- **OfferWorkloadRow** — `{ owner_id?, owner_username, owner_display_name, awaiting_response }`
- **SourceConversionRow** — `{ source_id, source_code, source_name_np, source_name_en, total, converted, lost, in_progress }`
- **ChecklistItemRow** — `{ id, label, status:[enum], item_type:[enum], is_required, due_at?, due_at_bs?, status_note, checklist_id, checklist_title, journey_id, applicant_id, applicant_name, country_name_en, assigned_to? }`
- **OfferRow** — `{ id, status:[enum], institution_name_en, program_title, intake_label, response_deadline?, response_deadline_bs?, is_response_overdue, journey_id, applicant_id, applicant_name }`
- **FileRow** — `{ id, original_filename, category:[enum], verification_status:[enum], rejection_reason, created_at, reviewed_at?, applicant_id?, journey_id? }`
- **DocumentRow** — `{ id, label, family:[enum], status:[enum], updated_at, applicant_id?, applicant_name }`
- **PassportRow** — `{ applicant_id, applicant_name, passport_number, expiry_date, expiry_date_bs, has_expired }`
- **LeadRow** — `{ id, full_name_np, full_name_en, stage:[enum], last_followed_up_at?, created_at, owner_display_name }`
- **JourneyRow** — `{ id, stage:[enum], applicant_id, applicant_name, country_id?, country_name_en }`
- **ActivityRow** — `{ id, app_label, action, entity_type, entity_id?, actor_type:[enum], actor_label, summary, success, created_at, created_at_bs }`
- **Rate** — `{ numerator, denominator, percent? }`
  - `percent` is `null`, never `0`, when `denominator` is `0`.

## 4. Enums

- `filter.journey_stage` / `JourneyRow.stage`: `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage` | `completed` | `closed` | `deferred`
- `filter.offer_status` / `OfferRow.status`: `draft` | `issued` | `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`
- `filter.document_status` / `DocumentRow.status`: `draft` | `ready` | `archived`
- `filter.checklist_status`: `draft` | `active` | `completed` | `archived`
- `ChecklistItemRow.status`: `pending` | `completed` | `waived` | `blocked` | `not_applicable`
- `ChecklistItemRow.item_type`: `document` | `stage` | `task`
- `LeadRow.stage`: `new` | `contact_attempted` | `contacted` | `counselling` | `follow_up` | `ready_for_conversion` | `converted` | `lost`
- `FileRow.verification_status`: `pending` | `verified` | `rejected`
- `FileRow.category`: `passport` | `photograph` | `academic_transcript` | `academic_certificate` | `test_score_report` | `offer_letter` | `financial` | `sponsorship` | `signature_image` | `generated_document` | `other`
- `DocumentRow.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate`
- `ActivityRow.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `outcomes.journey_outcomes` keys: `successful` | `withdrawn` | `rejected` | `not_qualified` | `cancelled` | `other`
- `outcomes.offer_decisions` keys: `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`
- `ActivityRow.action` is not a fixed set — every app contributes its own values.

## 5. Dependency order

- Every section needs an authenticated `admin` or `lead_manager` session `(external module: authenticate)`.
- Nothing in this module is created first — it owns no resources and accepts no writes.
- The `country` filter needs a country id `(external module: institutions)`.
- The `owner` filter needs a user id `(external module: authenticate)`.

**Start here:** `GET /api/v1/dashboard/summary/`.

## 6. Endpoints

### Dashboard summary — `/api/v1/dashboard/summary/`

**Use it when:** the alert strip at the top of the dashboard home screen, and navigation badge counts.
**Methods:**
- `GET /api/v1/dashboard/summary/` (`dashboards.summary.read`, risk low)

**Send (create/update):** none
**Returns:** an object with `alerts` (eight integer counts), `volumes` (three integer counts), and `due_within_days`.
**Notes:**
- Every figure is duplicated in a fuller section below.
- `alerts.stale_leads` and `volumes.leads_total` are owner-scoped; the rest are not.
- `due_within_days` is echoed back so a client need not assume the default.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Today's work — `/api/v1/dashboard/today/`

**Use it when:** the main worklist panel.
**Methods:**
- `GET /api/v1/dashboard/today/` (`dashboards.today.read`, risk low)

**Send (create/update):** none
**Returns:** six Preview blocks — `overdue_checklist_items`, `due_soon_checklist_items` (list[ChecklistItemRow]), `offers_awaiting_response` (list[OfferRow]), `files_awaiting_verification` (list[FileRow]), `documents_in_progress` (list[DocumentRow]), `stale_leads` (list[LeadRow]) — plus `due_within_days`.
**Notes:**
- Overdue and due-soon are disjoint; their totals may be summed.
- An item or offer with no due date never appears at all.
- `blocked` items appear when overdue.
- Only `draft`/`active` checklists contribute items.
- Only an `issued` offer can await a response; the comparison is against today in Nepal.
- `stale_leads` uses a fixed 7-day rule and does not respond to `due_within_days`.
- `documents_in_progress` is ordered oldest edit first and ignores `country`.
- `files_awaiting_verification` is ordered oldest upload first.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Pipeline health — `/api/v1/dashboard/pipeline/`

**Use it when:** the funnel panel showing where volume sits.
**Methods:**
- `GET /api/v1/dashboard/pipeline/` (`dashboards.pipeline.read`, risk low)

**Send (create/update):** none
**Returns:** seven count maps — `leads_by_stage`, `applicants_by_status`, `journeys_by_stage`, `offers_by_status`, `checklists_by_status`, `documents_by_status`, `files_by_verification` — plus `documents_by_status_is_country_filtered`.
**Notes:**
- Every map is zero-filled across its full enum.
- Windowed on creation date.
- `documents_by_status_is_country_filtered` is always `false`.
- `leads_by_stage` is owner-scoped; the other six are not.
- `files_by_verification` excludes archived and superseded files.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Blockers and risk — `/api/v1/dashboard/blockers/`

**Use it when:** the risk panel.
**Methods:**
- `GET /api/v1/dashboard/blockers/` (`dashboards.blockers.read`, risk medium)

**Send (create/update):** none
**Returns:** five Preview blocks — `blocked_checklist_items` (list[ChecklistItemRow]), `journeys_without_a_checklist` (list[JourneyRow]), `expiring_passports` (list[PassportRow]), `overdue_offers` (list[OfferRow]), `rejected_files` (list[FileRow]) — plus `passport_within_days`.
**Notes:**
- Grouped by cause, not merged into one ranked list.
- `journeys_without_a_checklist` is the safety net behind automatic checklist inheritance.
- `overdue_offers` holds only deadlines already past; approaching ones are in Today's work.
- `expiring_passports` includes already-expired ones; archived applicants are excluded.
- The passport horizon defaults to 180 days, overridden by `passport_within_days`.
- `rejected_files` shows only current versions.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Workload by owner — `/api/v1/dashboard/workload/`

**Use it when:** the manager's rebalancing panel.
**Methods:**
- `GET /api/v1/dashboard/workload/` (`dashboards.workload.read`, risk medium)

**Send (create/update):** none
**Returns:** `{ is_scoped_to_caller, leads:[LeadWorkloadRow], checklist_items:[ChecklistWorkloadRow], offers:[OfferWorkloadRow] }`
**Notes:**
- `is_scoped_to_caller` is `true` for a Lead Manager, whose `leads` list then holds at most one row.
- The three lists are not joinable and must not be summed.
- `checklist_items` includes an unassigned bucket with `owner_id: null`.
- `offers` counts by who recorded the offer, not an assignee.
- `checklist_items` is not owner-scoped even for a Lead Manager.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Source and conversion — `/api/v1/dashboard/conversion/`

**Use it when:** the intake-health panel.
**Methods:**
- `GET /api/v1/dashboard/conversion/` (`dashboards.conversion.read`, risk medium)

**Send (create/update):** none
**Returns:** `{ by_source:[SourceConversionRow], rates: { lead_to_applicant:Rate, applicant_to_journey:Rate, journey_to_offer:Rate, offer_acceptance:Rate } }`
**Notes:**
- The four rates are not one funnel and must not be multiplied together.
- Every `percent` is `null`, never `0`, on an empty denominator.
- `by_source` lists only sources with at least one lead in the window.
- `by_source` and `lead_to_applicant` are owner-scoped; the other three rates are not.
- `offer_acceptance` counts only decided offers, keyed on when the decision was recorded.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Final outcomes — `/api/v1/dashboard/outcomes/`

**Use it when:** the leadership summary panel.
**Methods:**
- `GET /api/v1/dashboard/outcomes/` (`dashboards.outcomes.read`, risk low)

**Send (create/update):** none
**Returns:** `{ journey_outcomes, offer_decisions, journeys_completed, journeys_closed, applicants_archived, applicants_dormant, checklists_completed, checklists_archived }`
**Notes:**
- `journey_outcomes` and `offer_decisions` are windowed on when the thing ended; `journeys_completed`/`journeys_closed` on creation. The two can disagree about the same journey.
- `journey_outcomes` counts only journeys carrying an outcome.
- `offer_decisions` has keys only for the five terminal statuses.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Recent activity — `/api/v1/dashboard/activity/`

**Use it when:** the change-feed panel at the foot of the dashboard.
**Methods:**
- `GET /api/v1/dashboard/activity/` (`dashboards.activity.list`, risk low)

**Send (create/update):** none
**Returns:** list[ActivityRow], paginated, newest first.
**Notes:**
- The only paginated section, and the only one whose `meta` carries page data.
- Not narrowed by the caller's authority — the audit log is not owner-scoped anywhere in the project.
- Only `fiscal_year` is honoured; every other filter is accepted and ignored.
- `action` values are not a fixed set; render `summary` as the label.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

## 7. Flows

**Morning triage**
1. `GET /api/v1/dashboard/summary/` → read `alerts.overdue_checklist_items`.
2. `GET /api/v1/dashboard/today/` → capture `overdue_checklist_items.items[].checklist_id` and `.id`.
   - `total` greater than `items.length`: only the first 10 are here; this endpoint has no pagination.
3. `GET /api/v1/checklists/<checklist_id>/` → the full list in context.
4. `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` → resolve or reassign.
5. `GET /api/v1/dashboard/summary/` again → the count has dropped; nothing caches.

**Unblock a stalled file**
1. `GET /api/v1/dashboard/blockers/` → read `journeys_without_a_checklist.items[]`.
   - Empty: every destination in play has an authored template.
2. Note `country_id` on a row.
3. `GET /api/v1/checklists/templates/?country=<country_id>` → confirm none is active and default.
4. `POST /api/v1/checklists/templates/`, then activate → future journeys inherit automatically.
   - Already-affected journeys do not retroactively gain one; apply by hand.

**Rebalance the team**
1. `GET /api/v1/dashboard/workload/` → check `is_scoped_to_caller`.
   - `true`: the caller is a Lead Manager; render their own row and stop.
2. Read `checklist_items[]`, ordered by `overdue_items` descending.
3. Note the `owner_id: null` row — unassigned work, which needs an owner rather than a reassignment.
4. `GET /api/v1/checklists/?assigned_to=<owner_id>` → that person's items.

**Review intake health**
1. `GET /api/v1/catalogue/countries/` → capture a `country` id.
2. `GET /api/v1/dashboard/conversion/?country=<id>&fiscal_year=2081/82` → the rates.
   - Any `percent` is `null`: the denominator was zero; render "—", not "0%".
3. `GET /api/v1/dashboard/outcomes/?country=<id>&fiscal_year=2081/82` → what happened to that cohort.
4. `GET /api/v1/applicants/?country=<id>` → the people behind the numbers.

## 8. Gaps

- No appointments module exists, so the concept's appointment figures are absent, not zero.
- No notifications module exists, so there is no pending-alert count in any response.
- No branch concept exists anywhere in the backend, so the concept's branch filter is unbuildable.
- Only passport expiry is available as a time-sensitive blocker; `test_scores` is not built.
- `journey_stage`, `offer_status`, `document_status`, and `checklist_status` are validated and then ignored by every section.
- `institution` narrows only offer figures; `owner` narrows only checklist item worklists.
- `activity` ignores every filter but `fiscal_year`.
- Worklist previews cap at 10 rows with no `limit`/`offset` on the seven object sections.
- No caching, no ETag, no `Last-Modified`, and no documented latency budget.
- No cross-section consistency guarantee — the eight endpoints are separate live requests.
- Owner scoping is not uniform within a response, and nothing marks which figures were scoped except `workload.is_scoped_to_caller`.
- 401 body shape is not specified here.
- `VALIDATION_ERROR` details keys are the filter field names; the full message set is not enumerated.
- No export, no scheduled report, and no time-series endpoint.

---

## Applicants

## 1. Module

- **Name:** Applicants — the permanent identity record of a person.
- **Base path:** `/api/v1/applicants/`
- **Auth:** Bearer access JWT. Admin and Lead Manager; Superadmin denied.

## 2. Conventions

- **Response:** the standard project envelope — `{ success, message, data, meta }`. Unchanged this session.
- **Error:** `{ success: false, error: { code, message, details }, meta: {} }`. Unchanged this session.
- **Auth failures:** unchanged this session.
- **Pagination:** unchanged this session — `page`, `page_size` (default 20, max 100).
- **IDs:** UUID strings.
- **Times:** unchanged this session.
- **List/search/filter/order params:** `?search=` now matches `full_name_np`, `full_name_en`, `full_name_romanized`, `email`, any contact number, and the passport number — all partial, case-insensitive. New filters `country` (a country id), `country_code` (case-insensitive ASCII code), and `journey_stage`. **A searched list is relevance-ordered, not newest-first**: `3` a name equals the query, `2` a name starts with it, `1` a name contains it, `0` matched only on email/phone/passport, tie-broken by `-created_at` then `-id`. Every other list stays newest-first. The score is not returned in the response.

## 3. Models

- **Destination** *(new)* — `{ journey_id, stage:[enum], country_id?, country_code, country_name_en, target_country }`
  - One entry per journey the applicant holds; a read-only projection of `applicant_journeys`.
  - `country_id`, `country_code`, and `country_name_en` are `null`/`""` together for a journey with no catalogue link; `target_country` is then the only destination that journey has.
- **Applicant (list shape)** — gained `destinations:[Destination]`. Every other field unchanged.
- **Applicant (detail shape)** — the list shape plus its existing extras; `destinations` appears on both.

## 4. Enums

- `Destination.stage`: `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage` | `completed` | `closed` | `deferred` — owned by `applicant_journeys`. Also the accepted values for `?journey_stage=`.

## 5. Dependency order

- `Applicant` needs an authenticated **Admin** account *(external module: authenticate)*.
- The `country`/`country_code`/`journey_stage` filters need the applicant to already hold a journey *(external module: applicant_journeys)* — an applicant created a moment ago matches none of the three.
- `country`/`country_code` values come from the catalogue *(external module: institutions)*.

**Start here:** `POST /api/v1/applicants/` as an Admin, or convert an existing lead.

## 6. Endpoints

### Applicant — `/api/v1/applicants/`

**Use it when:** the applicant list/search screen, the destination-cohort view, and the applicant file page.
**Methods:**
- `GET /api/v1/applicants/` — list, search, and filter (`applicants.applicant.list`, risk low, version 1.1.0)
- `POST /api/v1/applicants/` — unchanged this session
- `GET /api/v1/applicants/<applicant_id>/` — unchanged this session
- `PATCH /api/v1/applicants/<applicant_id>/` — unchanged this session

**Send (create/update):** unchanged this session — no write field was added, removed, or renamed.
**Returns:** Applicant (detail shape) for create, retrieve, and update; list[Applicant (list shape)] for the list, paginated. Both shapes gained `destinations`.
**Notes:**
- An applicant has no country of its own; `country`/`country_code`/`journey_stage` mean "has **a** journey matching this", including a closed one.
- An applicant with two journeys to the same country is returned once.
- An unknown `country`/`country_code` returns an empty page and `200`, not a `400`.
- The filters compose with `search` and with each other.
- `destinations` is `[]` for a person with no journey — a normal state, not an error.
- Search is substring-based, not fuzzy: a misspelling matches nothing.

**Errors:** no new code this session. The existing set is unchanged.

## 7. Flows

**Find a person from a fragment**
1. `GET /api/v1/applicants/?search=<fragment>` → matches names in either script, email, any contact number, and the passport number; relevance-ordered, so an exact name match is `data[0]`.
   - Empty `data`: nothing matched. The search is not fuzzy — retry with a shorter fragment rather than a corrected guess.
2. Read `destinations` on each row to disambiguate two people with the same name.
3. `GET /api/v1/applicants/<applicant_id>/` → the full record.

**Work a destination cohort**
1. `GET /api/v1/catalogue/countries/` → capture the `id` or `code`.
2. `GET /api/v1/applicants/?country_code=au&status=active&journey_stage=offer_stage` → the cohort, narrowed three ways in one request.
   - Empty page and `200`: either nobody matches or the code does not exist; the two are indistinguishable.
3. `GET /api/v1/journeys/?applicant=<applicant_id>` → the journeys themselves, if the projected summary is not enough.

## 8. Gaps

- Search is substring-based, not fuzzy — no did-you-mean, no similarity threshold, no minimum query length.
- The relevance score is not returned, so a client cannot show match quality or set its own cut-off.
- There is no "current destination" — `destinations` lists every journey in no documented order and nothing marks the live one.
- There is no filter for "has no journey", so the applicants with no destination cannot be listed.
- `destinations[].country_code` casing follows however the catalogue row was created; compare case-insensitively.

---

## Leads

## 1. Module

- **Name:** Leads — enquiry tracking before applicant conversion.
- **Base path:** `/api/v1/leads/`
- **Auth:** Bearer access JWT. Admin and Lead Manager; Superadmin denied. Owner-scoped.

## 2. Conventions

- **Response:** unchanged this session.
- **Error:** unchanged this session.
- **Auth failures:** unchanged this session.
- **Pagination:** unchanged this session.
- **IDs:** UUID strings.
- **Times:** unchanged this session.
- **List/search/filter/order params:** `?search=` now matches `full_name_np`, `full_name_en`, `full_name_romanized`, `email`, and any contact number — all partial, case-insensitive. **A searched lead list is relevance-ordered, not newest-first**, using the same scoring as `applicants`. Notes, history, sources, and loss reasons keep their existing fixed ordering. Ranking composes on top of owner scoping and never widens it.

## 3. Models

No model shape changed this session — no field was added, removed, or renamed on any lead resource.

## 4. Enums

No enum changed this session.

## 5. Dependency order

Unchanged this session.

## 6. Endpoints

### Lead — `/api/v1/leads/`

**Use it when:** the lead funnel and search screen.
**Methods:**
- `GET /api/v1/leads/` — list, search, and filter (`leads.lead.list`, risk low, version 1.1.0)

**Send (create/update):** unchanged this session.
**Returns:** list[Lead (list shape)], paginated. Unchanged this session.
**Notes:**
- Search now also matches the email and any contact number — a lead is often a number in a call log before anyone has agreed how to spell the name.
- A searched result set is relevance-ordered; every other list in this module is newest-first.
- Ranking never widens scope: a Lead Manager's search reorders their own leads only.

**Errors:** no new code this session.

## 7. Flows

**Find a lead from a phone number**
1. `GET /api/v1/leads/?search=<number fragment>` → matches any of the lead's contact numbers.
   - Empty result: substring matching only; there is no fuzzy fallback.
2. `GET /api/v1/leads/<lead_id>/` → the record.
   - `LEADS_LEAD_NOT_FOUND`: missing or owned by another Lead Manager — the API does not distinguish the two.

## 8. Gaps

- A lead still cannot be filtered by country of interest. `study_interest.interested_countries` is a JSON array whose containment lookup is PostgreSQL-only and could not be covered by the SQLite test suite, so it was deliberately not built rather than shipped untested. The equivalent filter exists one stage later on `applicants.applicant.list`.
- Search is substring-based, not fuzzy.
- The relevance score is not returned.

---

## Applicant Journeys

No endpoint changed this session. No route, method, request shape, response shape, or error code was added, modified, or retired.

The only change is documentary: `applicants` now reads this app's rows back through the reverse `journeys` accessor to project a `destinations` array and serve three list filters. It is the first inbound dependency holding no ForeignKey and importing nothing, so it is recorded in this app's `DATA_CONTRACT.md` Cross-App Dependencies where it would otherwise be invisible.

---

## Checklists

No endpoint changed this session. No route, method, request shape, response shape, or error code was added, modified, or retired.

Four read-only summary selectors were added for the dashboards app to compose. They are internal and are not reachable over HTTP.

---

## Offers

No endpoint changed this session. No route, method, request shape, response shape, or error code was added, modified, or retired.

Five read-only summary selectors were added for the dashboards app to compose. They are internal and are not reachable over HTTP.

---

## Documents

No endpoint changed this session. No route, method, request shape, response shape, or error code was added, modified, or retired.

Two read-only summary selectors were added for the dashboards app to compose. They are internal and are not reachable over HTTP.

---

## Uploaded Files

No endpoint changed this session. No route, method, request shape, response shape, or error code was added, modified, or retired.

Three read-only summary selectors were added for the dashboards app to compose. Each takes `is_admin` and starts from the app's existing visibility rule, so the counts obey the same restriction the list obeys. They are internal and are not reachable over HTTP.

---

## Core

No endpoint changed this session. No route, method, request shape, response shape, or error code was added, modified, or retired.

`core.querying` was added — one shared queryset helper resolving a date window from `date_from`/`date_to`/`fiscal_year`, used identically by seven apps' summary selectors. The project-level `INTEGRATION.md` gained the `dashboards` inventory row and dependency-graph node.
