# Integration — Applicant Journeys

**Owner app:** `applicant_journeys`
**Version:** 1.1.1
**Status:** Active
**Created:** 2026-07-23

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial integration contract — 9 endpoints |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | No endpoint added, changed, or retired. Added the optional `target_country_ref` catalogue reference to the model shape, the create/update fields, and the list filters, plus the `CountryBrief` shape and the `JOURNEYS_COUNTRY_NOT_FOUND` error. **Documented the cross-app side effect it triggers** — setting it creates the applicant's checklist in the `checklists` module, asynchronously and invisibly from this app's responses |
| 1.1.1 | 2026-07-24 | AI (Claude Opus 4.8) | No endpoint or schema change — `HistoryEntry` already carried every field of the now-shared shape. Recorded that the shape is owned by the `audit` module and identical across all six modules with a history endpoint, and corrected §2 `Requires`: the `audit` coupling is a read dependency as well as a write one. Also corrected the header version, which still read 1.0.0 after the 1.1.0 row was added |

---

## 1. Module

- **Name:** Applicant Journeys — one overseas-study objective pursued by one applicant. Holds where they want to go, what they want to study, when they intend to start, what they can afford, how far along they are, and how it ended. One applicant may have many journeys.
- **Base path:** `/api/v1/journeys/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. Two authority types may use this module: `admin` and `lead_manager`, with identical rights. A `superadmin` token is rejected with 403 everywhere.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which decides whether the caller may act at all. | Every endpoint returns 401; an unrecognised authority gets 403 `JOURNEYS_ACTOR_FORBIDDEN`. |
| `applicants` | FK | Every journey belongs to exactly one applicant. `POST /api/v1/journeys/` requires an existing applicant id. | No journey can be created — there is nothing to attach one to. An applicant referenced by any journey also cannot be removed. |
| `authenticate` | FK | `created_by`, `closed_by`, and `deferred_by` reference user accounts. | Journeys cannot be created; attribution is unresolvable. |
| `audit` | service call + read shape | Every mutation appends one immutable event; the history endpoint reads it back through audit's selector and renders audit's shared entry shape. This module stores no history of its own. | Hard dependency in both directions of use — without it this module does not start. If only the write path failed, `GET /api/v1/journeys/<id>/history/` would return an empty list; the journey itself still works. |

**This module depends on `leads` for nothing.** `leads` calls this module during conversion and owns the link between the two; nothing here points back at a lead.

## 3. Conventions

- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`.

```json
{
  "success": true,
  "message": "Journey closed.",
  "data": { "id": "3f4e5d6c-7b8a-9012-3456-789abcdef012", "stage": "completed", "outcome": "successful" },
  "meta": {}
}
```

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object.

```json
{
  "success": false,
  "error": {
    "code": "JOURNEYS_OUTCOME_DETAIL_REQUIRED",
    "message": "The 'other' outcome requires an explanation.",
    "details": { "reason": ["This field is required for the selected outcome."] }
  },
  "meta": {}
}
```

- **Auth failures:** 401 with no token, an expired token, or a revoked session — produced by the authentication framework. 403 `JOURNEYS_ACTOR_FORBIDDEN` when the token is valid but the authority may not act (a `superadmin`, on any endpoint).
- **Pagination:** page-number based. Params `page` and `page_size` (default 20, max 100). `meta` carries `count`, `page`, `page_size`, `next`, `previous`. Applied to the journey list and the history list — the only two list endpoints here.
- **IDs:** UUID strings.
- **Times:** ISO 8601 UTC. `closed_at` and `deferred_at` carry a `<field>_bs` sibling holding a Bikram Sambat object; `created_at` and `updated_at` do not.
- **List/search/filter/order params:** on `GET /api/v1/journeys/` only — `applicant` (exact id), `stage` (exact), `target_country` (partial, case-insensitive, against the typed string), `target_country_ref` (exact catalogue country id), `fiscal_year` (`YYYY/YY`). There is **no** free-text search endpoint and no client-controlled ordering; results are always newest first.

## 4. Models

**BsDate** — `{ year, month, day, month_name, display }`

**UserBrief** — `{ id, username, display_name }`

**CountryBrief** — `{ id, code, name }`

- The nested read shape of `target_country_ref`. Written as a bare UUID, read back as this object — the same asymmetry `applicant` has. `null` on any journey whose destination was never resolved to a catalogue country.

**ApplicantBrief** — `{ id, full_name, status }`

- Just enough of the applicant to label the journey. The journey never duplicates the person's contact details — fetch the applicant from the `applicants` module for those.

**Journey (list shape)** — `{ id, applicant:ApplicantBrief, target_country, target_country_ref?:CountryBrief, target_institution_name, target_program_name, study_level:[enum], field_of_study, preferred_intake, budget_amount?, budget_currency, scholarship_interest, stage:[enum], creation_source:[enum], created_by:UserBrief, created_at, updated_at }`

- `budget_amount` is a decimal **string** or `null`.

**Journey (detail shape)** — the list shape plus `{ notes, outcome:[enum], closure_reason, closed_at?, closed_at_bs?:BsDate, closed_by?:UserBrief, deferred_at?, deferred_at_bs?:BsDate, deferred_to_intake, deferment_reason, deferred_by?:UserBrief, stage_before_terminal:[enum] }`

- The detail shape is returned by retrieve, create, update, **and every lifecycle action**. Only the list returns the shorter shape.
- The closure fields populate together when `stage` is `completed` or `closed`; the deferment fields when `stage` is `deferred`. All of them clear together on reopen.
- `outcome` and `stage_before_terminal` are empty strings — not `null` — when the journey is active.

**HistoryEntry** — `{ id, action:[enum], actor_type:[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:BsDate }`

- Owned by the `audit` module, where the same shape is called **AuditEventHistoryEntry** (`audit/docs/INTEGRATION.md` §4). This module renders it; it does not define it. Every module's `/history/` endpoint returns this identical shape, so one renderer serves all of them.
- `changes` maps a field name to `{ from, to }`; `{}` when the action carried no diff.
- Journey notes, closure reasons, and deferment reasons are deliberately **never** present in `changes` or `metadata`.

### Worked examples

**Journey (detail shape)**

```json
{
  "id": "3f4e5d6c-7b8a-9012-3456-789abcdef012",
  "applicant": {
    "id": "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5",
    "full_name": "Ram Shrestha",
    "status": "active"
  },
  "target_country": "Australia",
  "target_institution_name": "University of Melbourne",
  "target_program_name": "MSc Computer Science",
  "study_level": "masters",
  "field_of_study": "Computer Science",
  "preferred_intake": "Fall 2026",
  "budget_amount": "2500000.00",
  "budget_currency": "NPR",
  "scholarship_interest": true,
  "notes": "Prefers Melbourne.",
  "stage": "offer_stage",
  "creation_source": "lead_conversion",
  "created_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "adminuser", "display_name": "Adminuser" },
  "outcome": "",
  "closure_reason": "",
  "closed_at": null,
  "closed_at_bs": null,
  "closed_by": null,
  "deferred_at": null,
  "deferred_at_bs": null,
  "deferred_to_intake": "",
  "deferment_reason": "",
  "deferred_by": null,
  "stage_before_terminal": "",
  "created_at": "2026-07-23T05:00:00Z",
  "updated_at": "2026-07-23T07:00:00Z"
}
```

**Journey after being closed as successful**

```json
{
  "id": "3f4e5d6c-7b8a-9012-3456-789abcdef012",
  "applicant": {
    "id": "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5",
    "full_name": "Ram Shrestha",
    "status": "active"
  },
  "target_country": "Australia",
  "target_institution_name": "University of Melbourne",
  "target_program_name": "MSc Computer Science",
  "study_level": "masters",
  "field_of_study": "Computer Science",
  "preferred_intake": "Fall 2026",
  "budget_amount": "2500000.00",
  "budget_currency": "NPR",
  "scholarship_interest": true,
  "notes": "Prefers Melbourne.",
  "stage": "completed",
  "creation_source": "lead_conversion",
  "created_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "adminuser", "display_name": "Adminuser" },
  "outcome": "successful",
  "closure_reason": "Visa granted, departing August.",
  "closed_at": "2026-07-23T09:00:00Z",
  "closed_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name": "Shrawan",
    "display": "2083 Shrawan 8"
  },
  "closed_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "adminuser", "display_name": "Adminuser" },
  "deferred_at": null,
  "deferred_at_bs": null,
  "deferred_to_intake": "",
  "deferment_reason": "",
  "deferred_by": null,
  "stage_before_terminal": "visa_stage",
  "created_at": "2026-07-23T05:00:00Z",
  "updated_at": "2026-07-23T09:00:00Z"
}
```

**HistoryEntry**

```json
{
  "id": "d0d1d2d3-1234-5678-9abc-def012345678",
  "action": "journey_closed",
  "actor_type": "lead_manager",
  "actor_id": "aaaa1111-2222-3333-4444-555566667777",
  "actor_label": "leadmgr",
  "summary": "Journey closed as successful.",
  "reason": "successful",
  "changes": { "stage": { "from": "visa_stage", "to": "completed" } },
  "metadata": { "outcome": "successful", "has_reason": true },
  "created_at": "2026-07-23T09:00:00Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name": "Shrawan",
    "display": "2083 Shrawan 8"
  }
}
```

## 5. Enums

- `Journey.stage`: `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage` | `completed` | `closed` | `deferred`
- **Selectable stages** (the only values accepted by the stage-change and reopen endpoints): `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage`. The other three are reached only through the close and defer actions.
- `Journey.stage_before_terminal`: same set as `Journey.stage`, plus `""` while active.
- `Journey.outcome`: `successful` | `withdrawn` | `rejected` | `not_qualified` | `cancelled` | `other` | `""` (empty while active)
- `Journey.creation_source`: `lead_conversion` | `manual`
- `Journey.study_level`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other` | `""`
- `HistoryEntry.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `HistoryEntry.action`: `journey_created` | `journey_updated` | `journey_stage_changed` | `journey_deferred` | `journey_closed` | `journey_reopened`
- `target_country`, `target_institution_name`, `target_program_name`, `preferred_intake`, `deferred_to_intake`: **not enums** — unvalidated free text (see §9). `target_country_ref` is the validated alternative for the country alone.

## 6. Dependency order

- `Journey` needs `Applicant` *(other module: `applicants`)* — a journey cannot exist without a person pursuing it.
- `Applicant` needs an authenticated Admin *(other module: `applicants`)*.
- Closing a journey needs an `outcome` from the fixed enum in §5 — there is no configurable outcome table.
- Deferring needs a target intake, supplied as free text.
- `HistoryEntry` needs `Journey` and is never created by a client.

**Start here:** create or find an applicant in the `applicants` module, then `POST /api/v1/journeys/` with their id. A lead conversion produces both in one call.

## 7. Endpoints

### Journey — `/api/v1/journeys/`

**Use it when:** the operational worklist ("everything at Offer Stage"), the journeys panel on an applicant's file, the new-journey form, and the journey detail page.
**Methods:**
- `GET /api/v1/journeys/` — list journeys (permission: `applicant_journeys.journey.list`, risk: low)
- `POST /api/v1/journeys/` — record a new objective (permission: `applicant_journeys.journey.create`, risk: medium)
- `GET /api/v1/journeys/<journey_id>/` — retrieve one (permission: `applicant_journeys.journey.read`, risk: low)
- `PATCH /api/v1/journeys/<journey_id>/` — correct one (permission: `applicant_journeys.journey.update`, risk: medium)

**Send (create/update):**
- create: `applicant` (required), `target_country` (free text), `target_country_ref` (catalogue country **id** — written as a bare UUID, read back as an object), `target_institution_name`, `target_program_name`, `study_level`, `field_of_study`, `preferred_intake`, `budget_amount`, `budget_currency`, `scholarship_interest`, `notes`
- update: any subset of the same fields **except `applicant`**, which is immutable

**Returns:** Journey (detail shape) for create, retrieve, and update; list[Journey (list shape)] for the list, paginated.
**Requires state:** an existing applicant. Nothing else.
**Side effects:**
- create — appends `journey_created` to the audit log. Does **not** touch the applicant's status.
- update — appends `journey_updated` when something moved. A no-op `PATCH` writes no event.
- **create or update with `target_country_ref` set — that applicant's document checklist is created, in the `checklists` module** (cross-app: `checklists`). This response says nothing about it: that module watches journey saves, and this app does not know it exists. The checklist is written **after this request's transaction commits**, so a read issued immediately afterwards may not see it yet; retry. Nothing happens if the country has no authored checklist template, which is not an error — `GET /api/v1/checklists/?journey_missing_checklist=true` lists those journeys. Re-saving never produces a second checklist.

**Notes:**
- **Shared, not owner-scoped.** Every Admin and Lead Manager sees and edits every journey.
- **Creation is open to Lead Managers**, unlike applicant creation. Adding an objective for an existing client is ordinary work.
- Only `applicant` is required — a journey often begins as little more than "Australia, sometime next year."
- `applicant` is **immutable**: a journey belongs to one person and is never transferred. Sending it on update is ignored.
- `stage`, `creation_source`, and `created_by` are not writable; sending them is ignored, not rejected.
- One applicant may hold many journeys, including two for the same country and intake — nothing prevents it.
- Filter by `applicant` for the per-person view; filter by `stage` for the worklist. There is no free-text search.

**Errors:**
- `JOURNEYS_ACTOR_FORBIDDEN` (403) — the caller is a Superadmin
- `JOURNEYS_JOURNEY_NOT_FOUND` (404) — no journey with that id
- `JOURNEYS_APPLICANT_NOT_FOUND` (400) — the `applicant` id on create does not exist
- `JOURNEYS_COUNTRY_NOT_FOUND` (400) — `target_country_ref` names no catalogue country. Identical on create and update

### Journey stage change — `POST /api/v1/journeys/<journey_id>/stage/`

**Use it when:** the user picks a new stage from the dropdown on the journey detail page.
**Methods:**
- `POST /api/v1/journeys/<journey_id>/stage/` — move between active stages (permission: `applicant_journeys.journey.change_stage`, risk: medium)

**Send (create/update):**
- `stage` (required) — one of the six selectable stages in §5

**Returns:** Journey (detail shape)
**Requires state:** the journey must **not** be completed, closed, or deferred.
**Side effects:** appends `journey_stage_changed` with `changes.stage = {from, to}`. Moving to the stage already held is a no-op. Nothing on the applicant changes.
**Notes:**
- Offer only the six active stages in the dropdown. `Completed`, `Closed`, and `Deferred` are separate buttons.
- `visa_stage` records that a visa step is underway; Grandway does not manage the visa case itself.

**Errors:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — the journey is completed, closed, or deferred
- `JOURNEYS_STAGE_INVALID_TRANSITION` (400) — a terminal stage was requested

### Journey defer — `POST /api/v1/journeys/<journey_id>/defer/`

**Use it when:** the applicant intends to continue but not on the current timeline — a missed intake, a delayed test result, a family reason.
**Methods:**
- `POST /api/v1/journeys/<journey_id>/defer/` — pause to a later intake (permission: `applicant_journeys.journey.defer`, risk: medium)

**Send (create/update):**
- `to_intake` (required) — the intake being deferred to, free text
- `reason` (optional)

**Returns:** Journey (detail shape) with `stage: "deferred"` and the deferment fields set.
**Requires state:** the journey must not already be completed, closed, or deferred.
**Side effects:** appends `journey_deferred`. Sets `stage_before_terminal` to the stage held beforehand. Nothing on the applicant changes.
**Notes:**
- Deferment is **not an outcome** — `outcome` stays empty and nothing is ended. Resume with the reopen action.
- Do not present deferment as a way to close a journey; the two are distinct and reported differently.

**Errors:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — already terminal or deferred
- `JOURNEYS_DEFER_INTAKE_REQUIRED` (400) — no target intake supplied

### Journey close — `POST /api/v1/journeys/<journey_id>/close/`

**Use it when:** the objective has ended, successfully or otherwise.
**Methods:**
- `POST /api/v1/journeys/<journey_id>/close/` — end the journey (permission: `applicant_journeys.journey.close`, risk: high)

**Send (create/update):**
- `outcome` (required) — one of the six values in §5
- `reason` (conditionally required) — mandatory when `outcome` is `other`

**Returns:** Journey (detail shape) with `stage`, `outcome`, and the closure fields set.
**Requires state:** the journey must not already be completed, closed, or deferred.
**Side effects:** appends `journey_closed` carrying the outcome in the entry's `reason` field. Sets `stage_before_terminal`. **Nothing on the applicant changes** — closing a journey never archives the person.
**Notes:**
- `successful` sets `stage` to `completed`; **every other outcome** sets it to `closed`. Do not infer the outcome from the stage — read `outcome`.
- A journey that should not have existed is closed as `cancelled`. There is no delete anywhere in this module.
- Closing is reversible via reopen, but the closure remains in the history permanently.

**Errors:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — already terminal or deferred
- `JOURNEYS_OUTCOME_REQUIRED` (400) — no outcome supplied
- `JOURNEYS_OUTCOME_DETAIL_REQUIRED` (400) — `outcome` is `other` but `reason` was blank

### Journey reopen — `POST /api/v1/journeys/<journey_id>/reopen/`

**Use it when:** a closed objective revives, or a deferred one resumes.
**Methods:**
- `POST /api/v1/journeys/<journey_id>/reopen/` — return to active work (permission: `applicant_journeys.journey.reopen`, risk: high)

**Send (create/update):**
- `stage` (optional) — a selectable stage; defaults to `planning`

**Returns:** Journey (detail shape) with closure and deferment state cleared.
**Requires state:** the journey must currently be completed, closed, or deferred.
**Side effects:** appends `journey_reopened`. Clears all nine closure and deferment fields.
**Notes:**
- The **only** way back from a terminal or deferred state, and it works identically for all three.
- Reopening a completed journey does not undo that it was completed — the `journey_closed` event stays in the history. Show both.

**Errors:**
- `JOURNEYS_JOURNEY_NOT_TERMINAL` (409) — the journey is already active
- `JOURNEYS_STAGE_INVALID_TRANSITION` (400) — the requested target stage is terminal

### Journey History — `GET /api/v1/journeys/<journey_id>/history/`

**Use it when:** the activity timeline on the journey detail page.
**Methods:**
- `GET /api/v1/journeys/<journey_id>/history/` — chronological history (permission: `applicant_journeys.journey.list_history`, risk: low)

**Send (create/update):** none
**Returns:** list[HistoryEntry], paginated, newest first
**Requires state:** the journey must exist.
**Side effects:** none — this is a read.
**Notes:**
- Written by the server on every mutation; a client never creates entries.
- Entries are immutable and are never rewritten or removed, including on reopen.
- Render `summary` as the primary label; `changes` is populated only for stage moves and field edits.

**Errors:**
- `JOURNEYS_JOURNEY_NOT_FOUND` (404) — no journey with that id

## 8. Flows

**Add an objective for an existing client**
1. `GET /api/v1/applicants/?search=राम` *(other module: `applicants`)* → capture `applicant.id`.
2. `POST /api/v1/journeys/` with `{"applicant": "<applicant.id>", "target_country": "Canada"}` → capture `journey.id`. Starts at `planning`.
   - `JOURNEYS_APPLICANT_NOT_FOUND`: the id is wrong or the applicant was never created.
3. `PATCH /api/v1/journeys/<journey.id>/` to fill in level, field, intake, and budget as counselling progresses.

**Work an objective forward**
1. `GET /api/v1/journeys/?stage=profile_building` → the worklist for this phase.
2. `POST /api/v1/journeys/<journey.id>/stage/` with `{"stage": "shortlisting"}`, then `applying`, then `offer_stage` as work progresses.
   - `JOURNEYS_STAGE_NOT_EDITABLE`: someone closed or deferred it; refresh and show the current state with a Reopen action.
3. `GET /api/v1/journeys/<journey.id>/history/` → who moved it and when.

**End an objective**
1. `POST /api/v1/journeys/<journey.id>/close/` with `{"outcome": "successful", "reason": "Visa granted."}` → `stage` becomes `completed`.
   - Any other outcome sets `stage` to `closed` instead — read `outcome`, not `stage`, to report how it ended.
   - `JOURNEYS_OUTCOME_DETAIL_REQUIRED`: `other` was chosen without an explanation.
2. `GET /api/v1/applicants/<applicant.id>/` *(other module: `applicants`)* → the applicant's status is **unchanged**. If the file should be wound down, do it explicitly via the applicant status endpoint.

**Pause and resume**
1. `POST /api/v1/journeys/<journey.id>/defer/` with `{"to_intake": "Spring 2027"}` → `stage` becomes `deferred`, `outcome` stays empty.
2. `POST /api/v1/journeys/<journey.id>/reopen/` with `{"stage": "applying"}` when work restarts.
   - `JOURNEYS_JOURNEY_NOT_TERMINAL`: it was already resumed by someone else.
3. `GET /api/v1/journeys/<journey.id>/history/` → both the deferment and the resumption are present.

**Arrive from a lead conversion** *(crosses into `leads`)*
1. `POST /api/v1/leads/<lead_id>/convert/` *(other module: `leads`)* → returns `applicant_id` and `journey_id`.
2. `GET /api/v1/journeys/<journey_id>/` → `creation_source` reads `lead_conversion`, and the objective is seeded from whatever preliminary interest the Lead Manager recorded.
   - Expect gaps: `target_country` is blank when the lead named more than one country, and the unmapped interest fields are appended to `notes`. Prompt the user to complete it.
3. `PATCH /api/v1/journeys/<journey_id>/` to turn the seeded starting point into a real objective.

## 9. Gaps

- **Institution and program are unvalidated free text.** There is no institution catalogue, so two staff will spell the same university differently and nothing prevents it. Do not use these fields as a join key or a filter value you depend on. They become real references when the `institutions` module ships.
- **Intakes are free text too**, for both `preferred_intake` and `deferred_to_intake`. There is no intake catalogue and no date semantics — `"Fall 2026"` is a string.
- **No offers.** A journey reaching `offer_stage` records only that it got there. Offer records, conditions, and deposits belong to a separate module that does not exist.
- **No documents, files, or checklists** attached to a journey.
- **No free-text search.** The list filters on exact `applicant` and `stage` and partial `target_country` only — there is no equivalent of the applicant name search.
- **No priority or target date**, so the worklist can only be ordered newest-first.
- **Nothing prevents two open journeys for the same country and intake** for one applicant.
- **401 body shape is not specified here** — it comes from the authentication framework; consult the `authenticate` module's contract.
- **`HistoryEntry.metadata` keys are per-action and not exhaustively specified.** Observed keys: `creation_source`, `applicant_id`, `deferred_to_intake`, `outcome`, `has_reason`.
- **No bulk operations.** Each journey is acted on individually.
