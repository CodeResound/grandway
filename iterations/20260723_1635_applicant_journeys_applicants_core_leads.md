# Session 20260723_1635 — applicant_journeys, applicants, core, leads

Branch: `add_applicants_journeys_20260723_1558`

## Applicants

## 1. Module

- Name: Applicants — the permanent identity record of a person the consultancy works with.
- Base path: `/api/v1/applicants/`
- Auth: Bearer access JWT on every endpoint; Admin and Lead Manager only, Superadmin rejected with 403. Creation is Admin-only.

## 2. Conventions

- Response: the standard envelope `{ success, message, data, meta }`.
- Error: `{ success: false, error: { code, message, details }, meta }`.
- Auth failures: 401 unauthenticated; 403 `APPLICANTS_ACTOR_FORBIDDEN` when the authority may not act.
- Pagination: `page` and `page_size` params (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous`. Applied to the applicant list and the history list.
- IDs: UUID strings.
- Times: ISO 8601 UTC for datetimes, `YYYY-MM-DD` for dates. Every user-facing date carries a `<field>_bs` sibling; `created_at` and `updated_at` do not.
- List/search/filter/order params:
  - `GET /api/v1/applicants/` accepts `status`, `creation_source`, `search`, `fiscal_year`.
  - Ordering is fixed newest-first; there is no client-controlled ordering.

## 3. Models

**BsDate** — `{ year, month, day, month_name_en, month_name_np, display_en, display_np }`

**UserBrief** — `{ id, username, display_name }`

**ContactNumber** — `{ id, number, label:[enum], is_primary }`

**Address** — `{ id, address_type:[enum], country, province, district, municipality, ward, street_address, postal_code }`

- At most one per `address_type` per applicant.

**Passport** — `{ passport_number, issuing_country, place_of_issue, issued_date?, issued_date_bs?:BsDate, expiry_date?, expiry_date_bs?:BsDate }`

- No `id` — one per applicant, not a collection member.

**FamilyMember** — `{ id, relationship:[enum], full_name_np, full_name_en, occupation, contact_number }`

**EmergencyContact** — `{ id, full_name_np, full_name_en, relationship, contact_number, email, address }`

- `relationship` is free text here, unlike the `FamilyMember` enum.

**Applicant (list shape)** — `{ id, full_name_np, full_name_en, full_name_romanized, date_of_birth?, date_of_birth_bs?:BsDate, gender:[enum], nationality, email, status:[enum], creation_source:[enum], created_by:UserBrief, contact_numbers:[ContactNumber], created_at, updated_at }`

**Applicant (detail shape)** — the list shape plus `{ addresses:[Address], passport?:Passport, family_members:[FamilyMember], emergency_contacts:[EmergencyContact], originating_lead_id? }`

- Returned by retrieve, create, update, and the status action. Only the list returns the shorter shape.
- `originating_lead_id` is a bare id string, `null` for a directly created applicant.

**HistoryEntry** — `{ id, action:[enum], actor_type:[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:BsDate }`

## 4. Enums

- `Applicant.status`: `active` | `dormant` | `archived`
- `Applicant.creation_source`: `lead_conversion` | `direct_admin`
- `Applicant.gender`: `male` | `female` | `other` | `undisclosed` | empty string
- `Address.address_type`: `permanent` | `current`
- `ContactNumber.label`: `mobile` | `home` | `work` | `whatsapp` | `viber` | `other`
- `FamilyMember.relationship`: `father` | `mother` | `spouse` | `sibling` | `child` | `guardian` | `other`
- `HistoryEntry.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `HistoryEntry.action`: `applicant_created` | `applicant_updated` | `applicant_contact_changed` | `applicant_address_changed` | `applicant_passport_changed` | `applicant_family_changed` | `applicant_emergency_contact_changed` | `applicant_status_changed`
- `EmergencyContact.relationship` is not an enum — free text.

## 5. Dependency order

- `Applicant` needs an authenticated Admin account (external module: `authenticate`).
- `ContactNumber`, `Address`, `Passport`, `FamilyMember`, `EmergencyContact` all need `Applicant` and are sent nested in its payload.
- `HistoryEntry` needs `Applicant` and is written only by the server (external module: `audit`).

**Start here:** `Applicant` — create one as an Admin, or convert a lead.

## 6. Endpoints

### Applicant — `/api/v1/applicants/`

**Use it when:** the applicant list/search screen, the create form, and the applicant file page.

**Methods:**
- `GET /api/v1/applicants/` — list every applicant (`applicants.applicant.list`)
- `POST /api/v1/applicants/` — create one directly (`applicants.applicant.create`), Admin only
- `GET /api/v1/applicants/<applicant_id>/` — retrieve one (`applicants.applicant.read`)
- `PATCH /api/v1/applicants/<applicant_id>/` — correct one (`applicants.applicant.update`)

**Send (create/update):**
- create: `full_name_np`, `full_name_en`, `date_of_birth`, `gender`, `nationality`, `email`, `contact_numbers`, `addresses`, `passport`, `family_members`, `emergency_contacts`
- update: any subset of the same fields

**Returns:** Applicant (detail shape) for create, retrieve, and update; list[Applicant (list shape)] for the list

**Notes:**
- Shared, not owner-scoped — every Admin and Lead Manager sees and edits every applicant.
- Creation is Admin-only by both paths; editing is not.
- All five sub-resources are nested in the payload; sending a collection replaces it entirely.
- `status`, `creation_source`, and `created_by` are not writable.
- `full_name_romanized` is generated server-side.
- `search` matches all three name forms simultaneously.
- Archived applicants still appear in unfiltered lists.

**Errors:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — a Superadmin called any method, or a Lead Manager attempted create
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id
- `APPLICANTS_CONTACT_REQUIRED` (400) — no contact number supplied
- `APPLICANTS_PASSPORT_EXPIRY_INVALID` (400) — expiry is not after the issue date

### Applicant status — `/api/v1/applicants/<applicant_id>/status/`

**Use it when:** the status control in the applicant file header.

**Methods:**
- `POST /api/v1/applicants/<applicant_id>/status/` — set the standing (`applicants.applicant.change_status`)

**Send (create/update):**
- `status` — required

**Returns:** Applicant (detail shape)

**Notes:**
- Always manual; never changed by journey activity.
- Archiving deletes nothing and is fully reversible.
- Archival is not a privacy control — archived records stay visible.

**Errors:**
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id

### Applicant History — `/api/v1/applicants/<applicant_id>/history/`

**Use it when:** the activity panel on the applicant file page.

**Methods:**
- `GET /api/v1/applicants/<applicant_id>/history/` — chronological history (`applicants.applicant.list_history`)

**Send (create/update):** none

**Returns:** list[HistoryEntry]

**Notes:**
- Written by the server on every mutation; entries are immutable.
- Nested-collection events carry only a count; no passport numbers, addresses, or family names ever appear.

**Errors:**
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id

## 7. Flows

**Create an applicant directly**

1. `POST /api/v1/applicants/` with `full_name_np` and at least one contact number — capture `applicant.id`. Recorded as `direct_admin`.
   - `APPLICANTS_ACTOR_FORBIDDEN`: the caller is a Lead Manager; this path is Admin-only.
2. `PATCH /api/v1/applicants/<applicant.id>/` to fill in passport, addresses, and family as they become known.
3. `POST /api/v1/journeys/` with the applicant id (external module) to record what they are trying to do.

**Complete a file that arrived from conversion**

1. `GET /api/v1/applicants/<applicant_id>/` — `creation_source` reads `lead_conversion` and `originating_lead_id` points back at the lead.
2. `PATCH /api/v1/applicants/<applicant_id>/` to add date of birth, passport, family, and emergency contacts, none of which a lead carried.

**Maintain a file over time**

1. `GET /api/v1/applicants/?search=<name>` — find the person in either script.
2. `PATCH /api/v1/applicants/<applicant.id>/` with the complete contact list to add a number.
   - Sending only the new number silently drops the existing ones; this is replace, not append.
3. `GET /api/v1/applicants/<applicant.id>/history/` — confirm what changed and who changed it.

**Wind a file down**

1. `POST /api/v1/applicants/<applicant.id>/status/` with `dormant`, later `archived`.
2. `POST /api/v1/applicants/<applicant.id>/status/` with `active` if they return — archival destroyed nothing.
   - Their journeys were untouched throughout; close those separately if appropriate.

## 8. Gaps

- No photograph. `concepts/applicants.txt` lists one, but no file handling exists in this module.
- No academic history, test scores, documents, or files — the `education` and `test_scores` modules are specified but not built.
- No duplicate detection or merging.
- No field-level redaction: every lead actor reads the whole record including passport and date of birth.
- Passport renewal history is not kept; a renewal overwrites the record.
- `HistoryEntry.metadata` keys are per-action and not exhaustively specified. Observed: `creation_source`, `count`.
- No bulk operations and no export.
- `nationality` is unvalidated free text.

## Applicant Journeys

## 1. Module

- Name: Applicant Journeys — one overseas-study objective pursued by one applicant.
- Base path: `/api/v1/journeys/`
- Auth: Bearer access JWT on every endpoint; Admin and Lead Manager have identical rights including creation, Superadmin rejected with 403.

## 2. Conventions

- Response, error, pagination, and ID conventions are identical to the applicants module above.
- Times: ISO 8601 UTC. `closed_at` and `deferred_at` carry a `<field>_bs` sibling; `created_at` and `updated_at` do not.
- List/search/filter/order params:
  - `GET /api/v1/journeys/` accepts `applicant` (exact id), `stage` (exact), `target_country` (partial), `fiscal_year`.
  - There is no free-text search endpoint and no client-controlled ordering.

## 3. Models

**ApplicantBrief** — `{ id, full_name_np, full_name_en, status }`

- Enough to label the journey. The journey holds no contact details.

**Journey (list shape)** — `{ id, applicant:ApplicantBrief, target_country, target_institution_name, target_program_name, study_level:[enum], field_of_study, preferred_intake, budget_amount?, budget_currency, scholarship_interest, stage:[enum], creation_source:[enum], created_by:UserBrief, created_at, updated_at }`

- `budget_amount` is a decimal string or `null`.

**Journey (detail shape)** — the list shape plus `{ notes, outcome:[enum], closure_reason, closed_at?, closed_at_bs?:BsDate, closed_by?:UserBrief, deferred_at?, deferred_at_bs?:BsDate, deferred_to_intake, deferment_reason, deferred_by?:UserBrief, stage_before_terminal:[enum] }`

- Returned by retrieve, create, update, and every lifecycle action.
- `outcome` and `stage_before_terminal` are empty strings, not null, while the journey is active.

**HistoryEntry** — same shape as the applicants module.

## 4. Enums

- `Journey.stage`: `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage` | `completed` | `closed` | `deferred`
- `Journey.stage` (selectable subset accepted by stage-change and reopen): `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage`
- `Journey.outcome`: `successful` | `withdrawn` | `rejected` | `not_qualified` | `cancelled` | `other` | empty string
- `Journey.creation_source`: `lead_conversion` | `manual`
- `Journey.study_level`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other` | empty string
- `HistoryEntry.action`: `journey_created` | `journey_updated` | `journey_stage_changed` | `journey_deferred` | `journey_closed` | `journey_reopened`
- `target_country`, `target_institution_name`, `target_program_name`, `preferred_intake`, `deferred_to_intake` are not enums — unvalidated free text.

## 5. Dependency order

- `Journey` needs `Applicant` (external module: `applicants`).
- Closing needs an `outcome` from the fixed enum; there is no configurable outcome table.
- Deferring needs a target intake, supplied as free text.
- `HistoryEntry` needs `Journey` and is written only by the server (external module: `audit`).

**Start here:** an `Applicant`, then `Journey`.

## 6. Endpoints

### Journey — `/api/v1/journeys/`

**Use it when:** the operational worklist, the journeys panel on an applicant's file, and the journey detail page.

**Methods:**
- `GET /api/v1/journeys/` — list journeys (`applicant_journeys.journey.list`)
- `POST /api/v1/journeys/` — record a new objective (`applicant_journeys.journey.create`)
- `GET /api/v1/journeys/<journey_id>/` — retrieve one (`applicant_journeys.journey.read`)
- `PATCH /api/v1/journeys/<journey_id>/` — correct one (`applicant_journeys.journey.update`)

**Send (create/update):**
- create: `applicant` (required), `target_country`, `target_institution_name`, `target_program_name`, `study_level`, `field_of_study`, `preferred_intake`, `budget_amount`, `budget_currency`, `scholarship_interest`, `notes`
- update: any subset of the same fields except `applicant`

**Returns:** Journey (detail shape) for create, retrieve, and update; list[Journey (list shape)] for the list

**Notes:**
- Shared, not owner-scoped.
- Creation is open to Lead Managers, unlike applicant creation.
- Only `applicant` is required.
- `applicant` is immutable — a journey is never transferred between people.
- `stage`, `creation_source`, and `created_by` are not writable.
- One applicant may hold many journeys, including two for the same country and intake.

**Errors:**
- `JOURNEYS_ACTOR_FORBIDDEN` (403) — the caller is a Superadmin
- `JOURNEYS_JOURNEY_NOT_FOUND` (404) — no journey with that id
- `JOURNEYS_APPLICANT_NOT_FOUND` (400) — the applicant id on create does not exist

### Journey stage change — `/api/v1/journeys/<journey_id>/stage/`

**Use it when:** the stage dropdown on the journey detail page.

**Methods:**
- `POST /api/v1/journeys/<journey_id>/stage/` — move between active stages (`applicant_journeys.journey.change_stage`)

**Send (create/update):**
- `stage` — required, one of the six selectable stages

**Returns:** Journey (detail shape)

**Notes:**
- Offer only the six active stages; the other three have their own actions.
- Moving to the stage already held is a no-op.
- Nothing on the applicant changes.

**Errors:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — the journey is completed, closed, or deferred
- `JOURNEYS_STAGE_INVALID_TRANSITION` (400) — a terminal stage was requested

### Journey defer — `/api/v1/journeys/<journey_id>/defer/`

**Use it when:** the applicant intends to continue on a later timeline.

**Methods:**
- `POST /api/v1/journeys/<journey_id>/defer/` — pause to a later intake (`applicant_journeys.journey.defer`)

**Send (create/update):**
- `to_intake` — required
- `reason` — optional

**Returns:** Journey (detail shape)

**Notes:**
- Deferment is not an outcome; `outcome` stays empty and nothing is ended.
- `stage_before_terminal` remembers where the journey was.

**Errors:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — already terminal or deferred
- `JOURNEYS_DEFER_INTAKE_REQUIRED` (400) — no target intake supplied

### Journey close — `/api/v1/journeys/<journey_id>/close/`

**Use it when:** the objective has ended, successfully or otherwise.

**Methods:**
- `POST /api/v1/journeys/<journey_id>/close/` — end the journey (`applicant_journeys.journey.close`)

**Send (create/update):**
- `outcome` — required
- `reason` — required when the outcome is `other`

**Returns:** Journey (detail shape)

**Notes:**
- `successful` sets the stage to `completed`; every other outcome sets it to `closed`. Read `outcome`, not `stage`, to report how a journey ended.
- A journey that should not have existed is closed as `cancelled`; there is no delete.
- Nothing on the applicant changes.

**Errors:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — already terminal or deferred
- `JOURNEYS_OUTCOME_REQUIRED` (400) — no outcome supplied
- `JOURNEYS_OUTCOME_DETAIL_REQUIRED` (400) — `other` chosen without an explanation

### Journey reopen — `/api/v1/journeys/<journey_id>/reopen/`

**Use it when:** a closed objective revives or a deferred one resumes.

**Methods:**
- `POST /api/v1/journeys/<journey_id>/reopen/` — return to active work (`applicant_journeys.journey.reopen`)

**Send (create/update):**
- `stage` — optional selectable stage, defaults to `planning`

**Returns:** Journey (detail shape)

**Notes:**
- The only way back from a terminal or deferred state, and it serves all three identically.
- Clears all nine closure and deferment fields.
- Reopening a completed journey does not remove the closure from its history.

**Errors:**
- `JOURNEYS_JOURNEY_NOT_TERMINAL` (409) — the journey is already active
- `JOURNEYS_STAGE_INVALID_TRANSITION` (400) — the requested target stage is terminal

### Journey History — `/api/v1/journeys/<journey_id>/history/`

**Use it when:** the activity timeline on the journey detail page.

**Methods:**
- `GET /api/v1/journeys/<journey_id>/history/` — chronological history (`applicant_journeys.journey.list_history`)

**Send (create/update):** none

**Returns:** list[HistoryEntry]

**Notes:**
- Entries are immutable and are never removed, including on reopen.
- Closure and deferment reasons live on the journey record, not in the history entry.

**Errors:**
- `JOURNEYS_JOURNEY_NOT_FOUND` (404) — no journey with that id

## 7. Flows

**Add an objective for an existing client**

1. `GET /api/v1/applicants/?search=<name>` (external module) — capture the applicant id.
2. `POST /api/v1/journeys/` with that id — capture the journey id. Starts at `planning`.
   - `JOURNEYS_APPLICANT_NOT_FOUND`: the id is wrong or the applicant was never created.
3. `PATCH /api/v1/journeys/<journey.id>/` to fill in level, field, intake, and budget as counselling progresses.

**Work an objective forward**

1. `GET /api/v1/journeys/?stage=<stage>` — the worklist for a phase.
2. `POST /api/v1/journeys/<journey.id>/stage/` through `shortlisting`, `applying`, `offer_stage`.
   - `JOURNEYS_STAGE_NOT_EDITABLE`: someone closed or deferred it; refresh and offer Reopen.

**End an objective**

1. `POST /api/v1/journeys/<journey.id>/close/` with an outcome and, for `other`, a reason.
2. `GET /api/v1/applicants/<applicant.id>/` (external module) — the applicant's status is unchanged. Wind the file down explicitly if appropriate.

**Pause and resume**

1. `POST /api/v1/journeys/<journey.id>/defer/` with the target intake.
2. `POST /api/v1/journeys/<journey.id>/reopen/` when work restarts.
3. `GET /api/v1/journeys/<journey.id>/history/` — both the deferment and the resumption are present.

## 8. Gaps

- Institution and program are unvalidated free text; there is no institution catalogue and no autocomplete.
- Intakes are free text with no date semantics.
- No offer records; a journey at `offer_stage` says nothing about which offers exist.
- No documents, files, or checklists.
- No free-text search; the list filters on exact applicant and stage and partial country only.
- No priority or target date, so the worklist can only be ordered newest-first.
- Nothing prevents two open journeys for the same country and intake.
- `HistoryEntry.metadata` keys are per-action and not exhaustively specified. Observed: `creation_source`, `applicant_id`, `deferred_to_intake`, `outcome`, `has_reason`.
- No bulk operations.

## Leads

## 1. Module

- Name: Leads — enquiry tracking before applicant conversion.
- Base path: `/api/v1/leads/`
- Auth: unchanged this session. Admin and Lead Manager only; Superadmin rejected.

## 2. Conventions

No conventions changed this session.

## 3. Models

**Lead (detail shape)** — gained four fields this session: `converted_applicant_id?`, `converted_journey_id?`, alongside the existing `converted_at?` and `converted_by?`.

- The `converted_*` fields populate together at conversion and are never cleared, not even by reopen.
- `converted_applicant_id` and `converted_journey_id` are bare id strings for navigating into the other two modules.

No other model shape changed.

## 4. Enums

- `HistoryEntry.action` gained two emitted values: `lead_converted` and `lead_applicant_created`. Both were previously defined but unreachable; they are now always emitted together by the conversion endpoint.

No other enum changed.

## 5. Dependency order

- Converting needs an Admin account and a lead in an active stage. It produces an `Applicant` (external module: `applicants`) and an `ApplicantJourney` (external module: `applicant_journeys`); neither needs to exist beforehand.

## 6. Endpoints

### Lead convert — `/api/v1/leads/<lead_id>/convert/`

**Use it when:** an Admin is admitting the person to the applicant lifecycle. The one point where the lead cycle meets the applicant cycle.

**Methods:**
- `POST /api/v1/leads/<lead_id>/convert/` — create an applicant and initial journey from the lead (`leads.lead.convert`)

**Send (create/update):** none — the body is empty and everything is taken from the lead.

**Returns:** an object with `lead` (the Lead detail shape, now at `stage: converted`), `applicant_id`, and `journey_id`.

**Notes:**
- Admin only; a Lead Manager gets 403.
- Requires an active stage; a lost or converted lead must be reopened first. Any active stage qualifies — `ready_for_conversion` is a signal, not a gate.
- Idempotent at two levels: a service guard, and a database one-to-one constraint making a second applicant per lead structurally impossible.
- Atomic: the applicant and journey are created together or not at all.
- Copies name, email, contact numbers, and address to the applicant. A lead holds no date of birth, passport, or family.
- Six of the ten study-interest fields map directly to the journey.
- `interested_countries` populates `target_country` only when it holds exactly one entry; two or more leaves it blank with the list written to the journey notes.
- `highest_qualification` and `language_test_status` are appended to journey notes, since the `education` and `test_scores` modules do not exist.
- Deletes and alters nothing else on the lead; notes, contact numbers, and history all survive.

**Errors:**
- `LEADS_ACTOR_FORBIDDEN` (403) — the caller is a Lead Manager or Superadmin
- `LEADS_LEAD_NOT_FOUND` (404) — no such lead, or it belongs to another Lead Manager
- `LEADS_LEAD_ALREADY_CONVERTED` (409) — this lead already produced an applicant
- `LEADS_CONVERSION_NOT_READY` (409) — the lead is lost or converted; reopen it first

No other lead endpoint changed this session.

## 7. Flows

**Convert a lead into a client**

1. `GET /api/v1/leads/<lead_id>/` — confirm the lead is in an active stage.
2. `POST /api/v1/leads/<lead_id>/convert/` with an empty body — capture `applicant_id` and `journey_id`.
   - `LEADS_ACTOR_FORBIDDEN`: only an Admin converts.
   - `LEADS_CONVERSION_NOT_READY`: the lead is lost; reopen it first.
   - `LEADS_LEAD_ALREADY_CONVERTED`: read `converted_applicant_id` off the lead and navigate there rather than retrying.
3. `GET /api/v1/applicants/<applicant_id>/` (external module) — prompt the user to add what a lead never held.
4. `GET /api/v1/journeys/<journey_id>/` (external module) — if the lead named more than one country, `target_country` is blank and the list is in the notes.
5. `GET /api/v1/leads/<lead_id>/` — now `stage: converted`, with both link ids populated.

## 8. Gaps

- Two study-interest fields survive conversion only as prose in the journey notes: `highest_qualification` and `language_test_status`. When `education` and `test_scores` ship, the conversion mapping needs revisiting.
- A multi-country lead produces a journey with no target country, by design; the client must prompt the user to resolve it.
- Direct applicant creation lives in the `applicants` module, not here.

## Core

## 1. Module

- Name: Core — project settings, routing, response envelope, pagination, shared constants and validators, Nepal utilities, and the policy engine.
- Base path: not applicable; `core` exposes no new endpoint this session.
- Auth: unchanged.

## 2. Conventions

No conventions changed this session.

## 3. Models

No models were added or modified in `core` this session.

## 4. Enums

Three enums moved **into** `core.constants` from `leads.constants`, with their values unchanged:

- `StudyLevel`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other`
- `LanguageTestStatus`: `not_taken` | `preparing` | `booked` | `taken` | `not_required`
- `ContactNumberLabel`: `mobile` | `home` | `work` | `whatsapp` | `viber` | `other`

They are now shared by two or more apps, which §3 requires and §2 permits. No database migration was needed — the choice values deconstruct identically regardless of which class defines them.

## 5. Dependency order

- `leads`, `applicants`, and `applicant_journeys` all need `core` (framework: base model, response envelope, pagination, shared constants and validators, Nepal calendar and text utilities).

**Start here:** not applicable; no new `core` resource was added.

## 6. Endpoints

No endpoints were added, changed, or retired in `core` this session. The changes were configuration, shared code, and documentation only:

- `applicants` and `applicant_journeys` added to installed apps and mounted at `/api/v1/applicants/` and `/api/v1/journeys/`.
- `StudyLevel`, `LanguageTestStatus`, and `ContactNumberLabel` moved into `core.constants`.
- `validate_contact_number` moved into a new `core.validators`, shared by `leads` and `applicants`.
- The project-level integration contract gained two app-inventory rows, three dependency-graph edges, a note on the one-directional lead→applicant boundary, and a warning that access models differ per app.

## 7. Flows

No `core` flows changed this session.

## 8. Gaps

- Permission-key authorization is still not enforced in the request path for any app. Every endpoint has a registered permission key, but no view consults one; each app uses its own inline authority rules in the meantime.
- Access models now differ between apps — `leads` is owner-scoped while `applicants` and `applicant_journeys` are shared — so a consumer cannot generalise from one app to another.
