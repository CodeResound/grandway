# Integration — Dashboards

**Owner app:** `dashboards`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial integration contract — 8 read-only section endpoints, one shared filter set |

---

## 1. Module

- **Name:** Dashboards — the operational command centre. Eight read-only sections summarising what needs attention now, what is moving, and where work is stuck. It owns no data and writes nothing.
- **Base path:** `/api/v1/dashboard/` (singular path, plural app — there is one dashboard, assembled from eight sections)
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. Two authority types may use this module: `admin` and `lead_manager`. A `superadmin` token is rejected with 403 everywhere.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which decides whether the caller may read at all and how the lead figures are scoped. | Every endpoint returns 401. Without a recognised `authority_type` the caller gets 403 `DASHBOARDS_ACTOR_FORBIDDEN`. |
| `leads` | service call | Every lead figure — funnel counts, source conversion, stale leads, lead workload — is read through this module, **including its owner scoping**. | `pipeline.leads_by_stage`, `conversion.by_source`, `conversion.rates.lead_to_applicant`, `today.stale_leads`, `workload.leads`, and `summary.alerts.stale_leads` are all empty or absent. |
| `applicants` | service call | Applicant status counts and the expiring-passport blocker. | `pipeline.applicants_by_status`, `blockers.expiring_passports`, `outcomes.applicants_archived`, and the applicant-to-journey rate lose their data. |
| `applicant_journeys` | service call | Journey stage and outcome counts, and the denominator of two conversion rates. It is also what the `country` filter resolves through for most sections. | `pipeline.journeys_by_stage`, `outcomes.journey_outcomes`, and two of the four conversion rates lose their data. |
| `offers` | service call | Offer status counts, decisions, the awaiting-response worklist, and the offer workload. | `today.offers_awaiting_response`, `blockers.overdue_offers`, `pipeline.offers_by_status`, `outcomes.offer_decisions`, `workload.offers`, and the acceptance rate lose their data. |
| `checklists` | service call | The overdue, due-soon, and blocked worklists, checklist status counts, the assignee workload, and the journeys-without-a-checklist safety net — the largest single contributor to this module. | Today's work and Blockers lose most of their content. `summary.alerts` loses three of its eight figures. |
| `documents` | service call | Document status counts and the stalled-draft list. | `pipeline.documents_by_status` and `today.documents_in_progress` lose their data. |
| `uploaded_files` | service call | File verification counts and the awaiting-verification and rejected worklists, **including that module's own per-record visibility rule**. | `today.files_awaiting_verification`, `blockers.rejected_files`, and `pipeline.files_by_verification` lose their data. |
| `audit` | service call | The entire recent-activity feed is a projection of the central audit log. This module stores no activity of its own. | `GET /api/v1/dashboard/activity/` returns an empty page. |
| `institutions` | indirect FK read | The `country` filter is a `institutions.Country` id. This module never queries the catalogue; it passes the id to the apps that hold a foreign key to it. | The `country` filter matches nothing. Every section still works unfiltered. |

**This module has no inbound dependencies.** Nothing reads it, nothing points at it, and removing it would break no other app. It is a leaf.

## 3. Conventions

- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Seven of the eight sections return a single object under `data`; only `activity` returns an array.

```json
{
  "success": true,
  "message": "Dashboard summary retrieved.",
  "data": {
    "alerts": { "overdue_checklist_items": 12, "stale_leads": 4 },
    "volumes": { "leads_total": 187, "applicants_active": 63, "journeys_total": 74 },
    "due_within_days": 7
  },
  "meta": {}
}
```

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object holding field-level problems.

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input.",
    "details": { "date_to": ["Must fall on or after 'date_from'."] }
  },
  "meta": {}
}
```

- **Auth failures:** 401 with no token, an expired token, or a revoked session — produced by the authentication framework, not this module. 403 `DASHBOARDS_ACTOR_FORBIDDEN` when the token is valid but the authority may not read: a `superadmin` on any of the eight endpoints.
- **Pagination:** applies to `activity` **only**. Page-number based, params `page` and `page_size` (default 20, max 100, clamped not rejected). `meta` carries `count`, `page`, `page_size`, `next`, `previous`. The other seven sections are unpaginated objects and their `meta` is `{}`.
- **Worklist previews.** Sections that carry a list of records return `{ total, has_more, items }`. `total` is the **real** backlog; `items` is capped at **10** rows. `has_more` is `true` when `total` exceeds what was returned. Show `total`, and link to the owning module's list endpoint for the rest — this module is deliberately not a second list view.
- **IDs:** UUID strings.
- **Times:** ISO 8601 UTC for datetimes; `YYYY-MM-DD` for dates. User-facing **dates** carry a `<field>_bs` sibling holding a Bikram Sambat object; `created_at` and `updated_at` do not.
- **Filter params — one set, all eight endpoints.** `date_from`, `date_to`, `fiscal_year`, `country`, `institution`, `owner`, `journey_stage`, `offer_status`, `document_status`, `checklist_status`, `due_within_days`, `passport_within_days`. All optional. They narrow the same underlying data rather than selecting different dashboards, so the same values may be sent to every section. **Not every section honours every filter** — see §7 per-section notes and §9.
- **`date_to` is inclusive.** "Up to the 24th" includes the whole of the 24th. Day boundaries are Kathmandu days (UTC+05:45), not UTC days.
- **`fiscal_year` is the coarse control, `date_from`/`date_to` the fine one.** Sending both applies the explicit dates; the fiscal year does not widen them back.
- **Zero-filled buckets.** Every count map returns **every** enum value, including zeros. An absent key means the field does not exist, never that the count is nil.
- **Ordering** is fixed per section and not client-controllable anywhere in this module.

## 4. Models

**BsDate** — `{ year, month, day, month_name, display }`

**UserBrief** — `{ id, username, display_name }`

**Preview** — `{ total, has_more, items:[…] }`

- The wrapper every worklist uses. `total` is the full count; `items` holds at most 10 rows.

**OwnerRow** — `{ owner_id?, owner_username, owner_display_name }`

- `owner_id` is `null` and `owner_display_name` reads `"Unassigned"` for the bucket of work nobody owns. Returned deliberately — unowned work is the most likely to be missed.

**LeadWorkloadRow** — OwnerRow plus `{ open_leads }`

**ChecklistWorkloadRow** — OwnerRow plus `{ open_items, overdue_items, blocked_items }`

**OfferWorkloadRow** — OwnerRow plus `{ awaiting_response }`

**SourceConversionRow** — `{ source_id, source_code, source_name, total, converted, lost, in_progress }`

- Only sources with at least one lead in the window appear. `in_progress` is `total - converted - lost`.

**ChecklistItemRow** — `{ id, label, status:[enum], item_type:[enum], is_required, due_at?, due_at_bs?:BsDate, status_note, checklist_id, checklist_title, journey_id, applicant_id, applicant_name, country_name, assigned_to?:UserBrief }`

- `country_name` is `""` for a checklist built by hand with no country.

**OfferRow** — `{ id, status:[enum], institution_name, program_title, intake_label, response_deadline?, response_deadline_bs?:BsDate, is_response_overdue, journey_id, applicant_id, applicant_name }`

**FileRow** — `{ id, original_filename, category:[enum], verification_status:[enum], rejection_reason, created_at, reviewed_at?, applicant_id?, journey_id? }`

- `applicant_id` and `journey_id` are both `null` when the file belongs to an offer, document, or snapshot instead.

**DocumentRow** — `{ id, label, family:[enum], status:[enum], updated_at, applicant_id?, applicant_name }`

- `applicant_id` is `null` and `applicant_name` is `""` for a standalone document.

**PassportRow** — `{ applicant_id, applicant_name, passport_number, expiry_date, expiry_date_bs:BsDate, has_expired }`

- `has_expired` is computed against today in **Nepal**, not UTC. Already-expired passports are included, not filtered out.

**LeadRow** — `{ id, full_name, stage:[enum], last_followed_up_at?, created_at, owner_display_name }`

**JourneyRow** — `{ id, stage:[enum], applicant_id, applicant_name, country_id?, country_name }`

- `country_name` falls back to the journey's free-text destination when there is no catalogue link.

**ActivityRow** — `{ id, app_label, action, entity_type, entity_id?, actor_type:[enum], actor_label, summary, success, created_at, created_at_bs:BsDate }`

**Rate** — `{ numerator, denominator, percent? }`

- `percent` is `null` — never `0` — when `denominator` is `0`. "Nobody arrived" and "people arrived and none converted" are different facts.

### Worked examples

**Summary** (`GET /api/v1/dashboard/summary/`)

```json
{
  "success": true,
  "message": "Dashboard summary retrieved.",
  "data": {
    "alerts": {
      "overdue_checklist_items": 12,
      "due_soon_checklist_items": 7,
      "blocked_checklist_items": 3,
      "offers_awaiting_response": 5,
      "files_awaiting_verification": 18,
      "rejected_files": 2,
      "stale_leads": 4,
      "journeys_without_a_checklist": 1
    },
    "volumes": { "leads_total": 187, "applicants_active": 63, "journeys_total": 74 },
    "due_within_days": 7
  },
  "meta": {}
}
```

**Today's work** (`GET /api/v1/dashboard/today/`) — one worklist shown in full, the rest elided for length

```json
{
  "success": true,
  "message": "Today's work retrieved.",
  "data": {
    "due_within_days": 7,
    "overdue_checklist_items": {
      "total": 12,
      "has_more": true,
      "items": [
        {
          "id": "3f4e5d6c-7b8a-9012-3456-789abcdef012",
          "label": "Passport bio page scan",
          "status": "pending",
          "item_type": "document",
          "is_required": true,
          "due_at": "2026-07-20T10:00:00Z",
          "due_at_bs": {
            "year": 2083, "month": 4, "day": 5,
            "month_name": "Shrawan",
            "display": "2083 Shrawan 5"
          },
          "status_note": "",
          "checklist_id": "aabbccdd-1122-3344-5566-778899aabbcc",
          "checklist_title": "Australia — Student Visa",
          "journey_id": "1f2e3d4c-5b6a-7089-9a8b-7c6d5e4f3021",
          "applicant_id": "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5",
          "applicant_name": "Ram Shrestha",
          "country_name": "Australia",
          "assigned_to": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "adminuser", "display_name": "Adminuser" }
        }
      ]
    },
    "due_soon_checklist_items": { "total": 7, "has_more": false, "items": [] },
    "offers_awaiting_response": { "total": 5, "has_more": false, "items": [] },
    "files_awaiting_verification": { "total": 18, "has_more": true, "items": [] },
    "documents_in_progress": { "total": 9, "has_more": false, "items": [] },
    "stale_leads": { "total": 4, "has_more": false, "items": [] }
  },
  "meta": {}
}
```

**Pipeline health** (`GET /api/v1/dashboard/pipeline/`)

```json
{
  "success": true,
  "message": "Pipeline health retrieved.",
  "data": {
    "leads_by_stage": {
      "new": 21, "contact_attempted": 8, "contacted": 14, "counselling": 11,
      "follow_up": 9, "ready_for_conversion": 3, "converted": 96, "lost": 25
    },
    "applicants_by_status": { "active": 63, "dormant": 12, "archived": 21 },
    "journeys_by_stage": {
      "planning": 9, "profile_building": 14, "shortlisting": 7, "applying": 12,
      "offer_stage": 11, "visa_stage": 6, "completed": 8, "closed": 5, "deferred": 2
    },
    "offers_by_status": {
      "draft": 3, "issued": 14, "accepted": 22, "rejected": 6,
      "withdrawn": 1, "deferred": 2, "expired": 4
    },
    "checklists_by_status": { "draft": 5, "active": 48, "completed": 19, "archived": 3 },
    "documents_by_status": { "draft": 9, "ready": 41, "archived": 6 },
    "documents_by_status_is_country_filtered": false,
    "files_by_verification": { "pending": 18, "verified": 132, "rejected": 2 }
  },
  "meta": {}
}
```

**Conversion** (`GET /api/v1/dashboard/conversion/`)

```json
{
  "success": true,
  "message": "Conversion retrieved.",
  "data": {
    "by_source": [
      {
        "source_id": "0f1c2b3a-4d5e-6f70-8192-a3b4c5d6e7f8",
        "source_code": "walk_in",
        "source_name": "वाक-इन",
        "source_name": "Walk-in",
        "total": 84, "converted": 41, "lost": 12, "in_progress": 31
      }
    ],
    "rates": {
      "lead_to_applicant": { "numerator": 96, "denominator": 187, "percent": 51.3 },
      "applicant_to_journey": { "numerator": 71, "denominator": 96, "percent": 74.0 },
      "journey_to_offer": { "numerator": 39, "denominator": 74, "percent": 52.7 },
      "offer_acceptance": { "numerator": 22, "denominator": 35, "percent": 62.9 }
    }
  },
  "meta": {}
}
```

**Workload** (`GET /api/v1/dashboard/workload/`)

```json
{
  "success": true,
  "message": "Workload retrieved.",
  "data": {
    "is_scoped_to_caller": false,
    "leads": [
      { "owner_id": "aaaa1111-2222-3333-4444-555566667777", "owner_username": "leadmgr", "owner_display_name": "Lead Manager", "open_leads": 23 }
    ],
    "checklist_items": [
      { "owner_id": null, "owner_username": "", "owner_display_name": "Unassigned", "open_items": 14, "overdue_items": 6, "blocked_items": 1 }
    ],
    "offers": [
      { "owner_id": "aaaa1111-2222-3333-4444-555566667777", "owner_username": "adminuser", "owner_display_name": "Adminuser", "awaiting_response": 5 }
    ]
  },
  "meta": {}
}
```

**Recent activity** (`GET /api/v1/dashboard/activity/`) — the one paginated section

```json
{
  "success": true,
  "message": "",
  "data": [
    {
      "id": "9182a3b4-c5d6-e7f0-1234-56789abcdef0",
      "app_label": "checklists",
      "action": "checklist_item_status_changed",
      "entity_type": "checklist",
      "entity_id": "aabbccdd-1122-3344-5566-778899aabbcc",
      "actor_type": "admin",
      "actor_label": "adminuser",
      "summary": "Item marked completed.",
      "success": true,
      "created_at": "2026-07-24T09:15:00Z",
      "created_at_bs": {
        "year": 2083, "month": 4, "day": 9,
        "month_name": "Shrawan",
        "display": "2083 Shrawan 9"
      }
    }
  ],
  "meta": {
    "count": 1482,
    "page": 1,
    "page_size": 20,
    "next": "https://api.example.com/api/v1/dashboard/activity/?page=2",
    "previous": null
  }
}
```

## 5. Enums

- `filter.journey_stage` / `JourneyRow.stage` / `ChecklistItemRow` journey stage: `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage` | `completed` | `closed` | `deferred` — owned by `applicant_journeys`
- `filter.offer_status` / `OfferRow.status`: `draft` | `issued` | `accepted` | `rejected` | `withdrawn` | `deferred` | `expired` — owned by `offers`
- `filter.document_status` / `DocumentRow.status`: `draft` | `ready` | `archived` — owned by `documents`
- `filter.checklist_status`: `draft` | `active` | `completed` | `archived` — owned by `checklists`
- `ChecklistItemRow.status`: `pending` | `completed` | `waived` | `blocked` | `not_applicable` — owned by `checklists`
- `ChecklistItemRow.item_type`: `document` | `stage` | `task` — owned by `checklists`
- `LeadRow.stage`: `new` | `contact_attempted` | `contacted` | `counselling` | `follow_up` | `ready_for_conversion` | `converted` | `lost` — owned by `leads`
- `FileRow.verification_status`: `pending` | `verified` | `rejected` — owned by `uploaded_files`
- `FileRow.category`: `passport` | `photograph` | `academic_transcript` | `academic_certificate` | `test_score_report` | `offer_letter` | `financial` | `sponsorship` | `signature_image` | `generated_document` | `other` — owned by `uploaded_files`
- `DocumentRow.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate` — owned by `documents`
- `ActivityRow.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai` — owned by `audit`
- `outcomes.journey_outcomes` keys: `successful` | `withdrawn` | `rejected` | `not_qualified` | `cancelled` | `other` — owned by `applicant_journeys`
- `outcomes.offer_decisions` keys: `accepted` | `rejected` | `withdrawn` | `deferred` | `expired` — the terminal subset of `offers` statuses. Note `draft` and `issued` never appear here.
- `ActivityRow.action` is **not** an enum with a fixed set — every app contributes its own action strings. Render `summary` as the label rather than branching on `action`.

## 6. Dependency order

- Every section needs an authenticated `admin` or `lead_manager` session *(external module: `authenticate`)*.
- Nothing in this module needs to be created first. It owns no resources, accepts no writes, and has no create endpoint of any kind.
- Sections return **empty or zeroed** data on a fresh installation rather than failing. A dashboard with nothing on it is the correct answer for a system with nothing in it.
- The `country` filter needs a `institutions.Country` id, obtained from `GET /api/v1/catalogue/countries/` *(external module: `institutions`)*.
- The `owner` filter needs a user id, obtained from the `authenticate` module *(external module: `authenticate`)*.

**Start here:** `GET /api/v1/dashboard/summary/`. It needs nothing but a session and tells you which of the other seven sections is worth opening.

## 7. Endpoints

### Dashboard summary — `/api/v1/dashboard/summary/`

**Use it when:** the alert strip at the top of the dashboard home screen, and any badge count in a navigation bar.
**Methods:**
- `GET /api/v1/dashboard/summary/` — top-line alerts and volumes (permission: `dashboards.summary.read`, risk: low)

**Send (create/update):** none
**Returns:** an object with `alerts` (eight integer counts), `volumes` (three integer counts), and the `due_within_days` actually applied.
**Requires state:** an authenticated Admin or Lead Manager. Nothing else — every count is `0` on an empty system.
**Side effects:** none. This module writes nothing, anywhere, ever.
**Notes:**
- Every figure here is duplicated in a fuller section below. This is the strip a user reads first, not the only place a number appears.
- `due_within_days` is echoed back so a client can label the "due soon" figure without assuming the default.
- `alerts.stale_leads` is owner-scoped for a Lead Manager; the other seven are not.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Today's work — `/api/v1/dashboard/today/`

**Use it when:** the main worklist panel — the section this module exists for.
**Methods:**
- `GET /api/v1/dashboard/today/` — overdue and due-soon work (permission: `dashboards.today.read`, risk: low)

**Send (create/update):** none
**Returns:** an object of six Preview blocks — `overdue_checklist_items` and `due_soon_checklist_items` (list[ChecklistItemRow]), `offers_awaiting_response` (list[OfferRow]), `files_awaiting_verification` (list[FileRow]), `documents_in_progress` (list[DocumentRow]), `stale_leads` (list[LeadRow]) — plus `due_within_days`.
**Requires state:** an authenticated Admin or Lead Manager. A checklist item appears only if it has a `due_at` set and its checklist is in `draft` or `active`; an offer appears only if it is `issued` **and** carries a `response_deadline`.
**Side effects:** none.
**Notes:**
- **Overdue and due-soon are disjoint.** An already-late item appears in `overdue_checklist_items` only, never in both. Summing the two totals is safe.
- **An offer or checklist item with no due date never appears here at all.** Nothing is late about a deadline that was never set — but it also means this list is not "all outstanding work", and a client should not present it as such.
- `stale_leads` means "no follow-up recorded in 7 days", falling back to creation date for a lead never followed up. A lead has no due date; silence is the only signal there is. The 7 days is **not** configurable via `due_within_days`.
- `documents_in_progress` is ordered **oldest edit first** — it is a stalled-work list, not a recent-activity list.
- `files_awaiting_verification` is ordered **oldest upload first**: it is a review queue, and newest-first would starve the backlog.
- `documents_in_progress` ignores the `country` filter entirely — a document belongs to a person, not a study plan.
- Verification is a record of human judgement, **not a gate**. Nothing in Grandway refuses to proceed on an unverified file. Present it as work outstanding, never as a blocked state.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Pipeline health — `/api/v1/dashboard/pipeline/`

**Use it when:** the funnel panel showing where volume sits across the business.
**Methods:**
- `GET /api/v1/dashboard/pipeline/` — stage and status counts (permission: `dashboards.pipeline.read`, risk: low)

**Send (create/update):** none
**Returns:** an object of seven count maps — `leads_by_stage`, `applicants_by_status`, `journeys_by_stage`, `offers_by_status`, `checklists_by_status`, `documents_by_status`, `files_by_verification` — plus the boolean `documents_by_status_is_country_filtered`.
**Requires state:** an authenticated Admin or Lead Manager.
**Side effects:** none.
**Notes:**
- Every map is zero-filled across its full enum. An empty stage shows as `0`, never as an absent key.
- **Windowed on creation date.** "Of the records created in this window, where has each got to." A journey running for two years is absent from a one-month window even though it is live today.
- `documents_by_status_is_country_filtered` is always `false` and exists so a client can label that panel honestly when a country filter is applied elsewhere on the screen. A document belongs to an applicant, not to a journey, so it has no destination to filter by.
- `leads_by_stage` is owner-scoped for a Lead Manager. The other six maps are not, because those apps are not owner-scoped either.
- `files_by_verification` excludes archived and superseded files, so it counts live work rather than history.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Blockers and risk — `/api/v1/dashboard/blockers/`

**Use it when:** the risk panel — the most visible section after Today's work.
**Methods:**
- `GET /api/v1/dashboard/blockers/` — work that is stuck (permission: `dashboards.blockers.read`, risk: medium)

**Send (create/update):** none
**Returns:** an object of five Preview blocks — `blocked_checklist_items` (list[ChecklistItemRow]), `journeys_without_a_checklist` (list[JourneyRow]), `expiring_passports` (list[PassportRow]), `overdue_offers` (list[OfferRow]), `rejected_files` (list[FileRow]) — plus the `passport_within_days` actually applied.
**Requires state:** an authenticated Admin or Lead Manager.
**Side effects:** none.
**Notes:**
- **Grouped by cause, deliberately not merged into one ranked list.** The five call for five different people to act.
- `journeys_without_a_checklist` is the safety net behind automatic checklist inheritance: a journey names a destination, but nobody has authored that country's requirement template, so no checklist was created and **no error was raised**. This is the only place that silence becomes visible. The fix is to author the template in the `checklists` module, not to touch the journey.
- `overdue_offers` contains **only** deadlines already past. The approaching ones are in Today's work, where they can still be acted on in time. The two do not overlap.
- `expiring_passports` **includes already-expired ones** — the applicant whose passport lapsed last month is the most blocked person on the list. Read `has_expired` to distinguish; it is computed against today in Nepal.
- The passport horizon defaults to **180 days**, not `due_within_days`. Renewing a Nepali passport is not a same-week errand. Override with `passport_within_days`.
- `rejected_files` shows only files still current: uploading a replacement supersedes the rejected version, which drops off this list on its own.
- `blocked_checklist_items` is a status a human set deliberately; `status_note` is mandatory for it and says why.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Workload by owner — `/api/v1/dashboard/workload/`

**Use it when:** the manager's rebalancing panel.
**Methods:**
- `GET /api/v1/dashboard/workload/` — per-owner counts (permission: `dashboards.workload.read`, risk: medium)

**Send (create/update):** none
**Returns:** `{ is_scoped_to_caller, leads:[LeadWorkloadRow], checklist_items:[ChecklistWorkloadRow], offers:[OfferWorkloadRow] }`
**Requires state:** an authenticated Admin or Lead Manager.
**Side effects:** none.
**Notes:**
- **`is_scoped_to_caller` is `true` for a Lead Manager and `false` for an Admin.** When `true`, `leads` holds at most one row — the caller's own. Label the panel from this flag; do not infer team size from the row count.
- **The three lists are not joinable into one row per person and must not be summed.** An open lead is a prospect being worked, an overdue checklist item is a task already late, and an offer awaiting response is someone else's decision to chase. A combined total would mean nothing.
- `checklist_items` includes an **unassigned** bucket with `owner_id: null` and `owner_display_name: "Unassigned"`. It is the most important row on the panel and must not be filtered out.
- `offers` counts by **who recorded the offer**, not who is assigned to it — an offer has no assignee. Label it "recorded by".
- `checklist_items` is not owner-scoped even for a Lead Manager, because checklists are shared across the consultancy.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Source and conversion — `/api/v1/dashboard/conversion/`

**Use it when:** the intake-health panel.
**Methods:**
- `GET /api/v1/dashboard/conversion/` — source mix and stage-to-stage rates (permission: `dashboards.conversion.read`, risk: medium)

**Send (create/update):** none
**Returns:** `{ by_source:[SourceConversionRow], rates: { lead_to_applicant:Rate, applicant_to_journey:Rate, journey_to_offer:Rate, offer_acceptance:Rate } }`
**Requires state:** an authenticated Admin or Lead Manager.
**Side effects:** none.
**Notes:**
- **The four rates are not one funnel and must not be multiplied together.** Each is windowed on its own stage, so a lead that arrived in Ashadh and converted in Shrawan counts toward Ashadh's intake and Shrawan's conversions. Rendering them as a single funnel chart would report something the data does not say.
- Every `Rate.percent` is `null` — never `0` — when its denominator is `0`. Render "—", not "0%".
- `by_source` lists only sources with at least one lead in the window. A channel nobody came through contributes nothing to a conversion comparison.
- `by_source` and `lead_to_applicant` are owner-scoped for a Lead Manager; the other three rates are not, so a Lead Manager's four rates are **not** internally consistent with one another. Present them as four independent measures.
- `offer_acceptance` counts only **decided** offers in the window, keyed on when the decision was recorded. Undecided offers are in neither the numerator nor the denominator.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Final outcomes — `/api/v1/dashboard/outcomes/`

**Use it when:** the leadership summary panel.
**Methods:**
- `GET /api/v1/dashboard/outcomes/` — how work ended (permission: `dashboards.outcomes.read`, risk: low)

**Send (create/update):** none
**Returns:** `{ journey_outcomes:{…}, offer_decisions:{…}, journeys_completed, journeys_closed, applicants_archived, applicants_dormant, checklists_completed, checklists_archived }`
**Requires state:** an authenticated Admin or Lead Manager.
**Side effects:** none.
**Notes:**
- **`journey_outcomes` and `offer_decisions` are windowed on when the thing *ended***, not when it started — a journey opened last year and closed this month belongs to this month. `journeys_completed`/`journeys_closed` are windowed on **creation**, like Pipeline. The two can legitimately disagree about the same journey, and that is not a bug.
- `journey_outcomes` counts only journeys that carry an outcome, so live journeys contribute to nothing here.
- `offer_decisions` has keys only for the five terminal statuses; `draft` and `issued` never appear.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

### Recent activity — `/api/v1/dashboard/activity/`

**Use it when:** the change-feed panel at the foot of the dashboard.
**Methods:**
- `GET /api/v1/dashboard/activity/` — paginated audit feed (permission: `dashboards.activity.list`, risk: low)

**Send (create/update):** none
**Returns:** list[ActivityRow], paginated, newest first.
**Requires state:** an authenticated **Admin**. This is the one section a Lead Manager may not read — see the access note below.
**Side effects:** none.
**Notes:**
- **The only paginated section**, and the only one whose `meta` carries page data. The other seven return objects with `meta: {}`.
- **Admin-only, unlike every other section.** This endpoint returns rows from the central audit log rather than a figure derived from an already-scoped selector, so it carries `audit`'s access rule (`is_staff`) as well as this module's. A Lead Manager receives `DASHBOARDS_ACTOR_FORBIDDEN` (403) — the same refusal `GET /api/v1/audit/events/` gives them. **Hide this panel for a Lead Manager rather than letting it 403 on load.**
- **Not narrowed among those who may read it.** The audit log is not owner-scoped, so an Admin sees every event including those actioned by others. Access is binary here, not a scope.
- *Changed 2026-08-01:* this endpoint was previously readable by a Lead Manager, documented as consistent with an audit endpoint "the same users may already call". That was incorrect — Lead Managers were always refused there — and the feed leaked the log to them. A client built against the old behaviour must stop rendering this panel for Lead Managers.
- **Only `fiscal_year` is honoured.** `date_from`, `date_to`, `country`, `owner`, and the rest are accepted and validated but **ignored** by this section. Do not present the full filter bar as active over this panel.
- `action` values are contributed by every app and are not a fixed set. Render `summary` as the label.

**Errors:**
- `DASHBOARDS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `VALIDATION_ERROR` (400) — a malformed filter value

## 8. Flows

**Morning triage** *(the primary flow this module exists for)*
1. `GET /api/v1/dashboard/summary/` → read `alerts.overdue_checklist_items`. If it is `0`, the rest of the triage can be skipped.
2. `GET /api/v1/dashboard/today/` → capture `overdue_checklist_items.items[].checklist_id` and `.id`.
   - `total` greater than `items.length`: only the first 10 are here. Send the user to the checklist module for the rest, do not paginate this endpoint — it has no pagination.
3. `GET /api/v1/checklists/<checklist_id>/` *(external module: `checklists`)* → the full list in context.
4. `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` *(external module: `checklists`)* → resolve or reassign it.
5. `GET /api/v1/dashboard/summary/` again → the count has dropped. Nothing in this module caches, so the change is immediate.

**Unblock a stalled file**
1. `GET /api/v1/dashboard/blockers/` → read `journeys_without_a_checklist.items[]`.
   - Empty: every destination in play has an authored template. This is the healthy state.
2. For a row, note `country_id` and `country_name` — the destination whose requirements nobody wrote.
3. `GET /api/v1/checklists/templates/?country=<country_id>` *(external module: `checklists`)* → confirm none is active and default.
4. `POST /api/v1/checklists/templates/` *(external module: `checklists`)*, then activate it → new journeys to that country inherit it automatically.
   - The already-affected journeys do **not** retroactively gain one; apply a checklist to each by hand.

**Rebalance the team** *(Admin only in practice)*
1. `GET /api/v1/dashboard/workload/` → check `is_scoped_to_caller`. If `true`, the caller is a Lead Manager and there is no distribution to rebalance; render their own row and stop.
2. Read `checklist_items[]`, sorted by `overdue_items` descending by the server.
3. Note the `owner_id: null` row — unassigned work, which no reassignment will fix and which needs an owner first.
4. `GET /api/v1/checklists/?assigned_to=<owner_id>` *(external module: `checklists`)* → that person's actual items.

**Chase an intake question**
1. `GET /api/v1/catalogue/countries/` *(external module: `institutions`)* → capture a `country` id.
2. `GET /api/v1/dashboard/conversion/?country=<id>&fiscal_year=2081/82` → the rates for that destination and year.
   - Any `percent` is `null`: the denominator was zero. Render "—", not "0%".
3. `GET /api/v1/dashboard/outcomes/?country=<id>&fiscal_year=2081/82` → what actually happened to that cohort.
4. `GET /api/v1/applicants/?country=<id>` *(external module: `applicants`)* → the people behind the numbers.

## 9. Gaps

- **No appointments anywhere.** `concepts/dashboards.txt` asks for "upcoming appointments" and "appointments that were missed or are about to occur". There is no appointments module in this backend, so those figures are **absent**, not zero. Do not build a panel expecting them.
- **No notifications.** The concept asks this module to summarise pending alerts and follow-ups from a `notifications` module. That module does not exist. There is no notification count in any response.
- **No branch filter, and no branch concept at all.** The concept lists "branch" among the useful filters. Nothing anywhere in this backend models a branch or office, so the filter cannot be built and is absent from the filter set.
- **No test-score or other expiry blockers.** Only passport expiry is available. The `test_scores` module is specified but not built, so an expiring language-test result is not surfaced.
- **Four filters are accepted but not used by any section.** `journey_stage`, `offer_status`, `document_status`, and `checklist_status` are validated and silently ignored. They are reserved for narrowing the pipeline and worklist sections and are not wired up. **Sending them changes nothing** — do not present them as active controls.
- **`institution` narrows only offers.** It is honoured by `today.offers_awaiting_response` and `pipeline.offers_by_status`, and ignored everywhere else.
- **`owner` narrows only checklist worklists.** It is honoured by the checklist item lists in Today's work and Blockers, and ignored by every count map and by the workload section itself.
- **`activity` ignores every filter but `fiscal_year`.** Stated in §7, repeated here because a client rendering one filter bar over the whole page will otherwise get this wrong.
- **Worklist previews cap at 10 rows with no way to page.** There is no `limit` or `offset` on the seven object sections. Getting past the first 10 means calling the owning module's list endpoint, and this module does not tell you which query parameters would reproduce its filtering there.
- **No caching and no `Last-Modified`.** Every request runs live queries. There is no ETag, no cache header, and no documented latency budget — a section over a large dataset may be slow and the contract does not say how slow.
- **No cross-section consistency guarantee.** The eight endpoints are separate requests against a live database. A record changing between two of them will make the sections disagree, and nothing reconciles them. Do not assert `summary.alerts.overdue_checklist_items == today.overdue_checklist_items.total` in a client.
- **Owner scoping is not uniform within a response, and nothing marks which figures were scoped** except `workload.is_scoped_to_caller`. For a Lead Manager, lead figures are narrowed and everything else is not, so an Admin and a Lead Manager legitimately see different numbers on the same URL. There is no per-field flag.
- **401 body shape is not specified here.** Unauthenticated and expired-token responses come from the authentication framework; consult the `authenticate` module's contract.
- **`VALIDATION_ERROR` details keys are the filter field names**, but the full set of messages is not enumerated. Observed: `date_to` for a reversed range, `fiscal_year` for a malformed label, `due_within_days` for out-of-range.
- **No export, no scheduled report, no historical trend series.** Every section is a point-in-time snapshot for the requested window. There is no time-series endpoint, so a sparkline cannot be built from this module.
