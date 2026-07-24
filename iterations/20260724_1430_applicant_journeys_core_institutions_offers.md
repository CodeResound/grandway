# Iteration — 2026-07-24 14:30 — applicant_journeys, core, institutions, offers

Session branch: `add_offers_app_20260724_1404`

---

## Offers

### 1. Module

- **Name:** Offers — institutions' formal admission decisions against applicant journeys.
- **Base path:** `/api/v1/offers/`
- **Auth:** Bearer access JWT on every endpoint. Admin and Lead Manager have identical rights, read and write; Superadmin is refused everywhere with 403 `OFFERS_ACTOR_FORBIDDEN`.

### 2. Conventions

- **Response:** `{ success, message, data, meta }`. The resource is always under `data`; `meta` is `{}` when there is nothing to report.
- **Error:** `{ success: false, error: { code, message, details }, meta }`. `details` is always present, `{}` when there are no field-level errors.
- **Auth failures:** 401 from the authentication framework with no/expired/revoked token. 403 `OFFERS_ACTOR_FORBIDDEN` when the token is valid but the authority may not act — in this module that is exactly one case, a Superadmin. This code replaces the project-wide `PERMISSION_DENIED`; that code is never returned from `/api/v1/offers/`.
- **Pagination:** page-number based, `page` and `page_size` (default 20, max 100). `data` is the bare array of rows, not nested under `results`. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `next`/`previous` are absolute URLs or `null`. Applied to every list endpoint including conditions and history.
- **IDs:** UUID strings throughout. No human-readable code on any resource. `offer_reference` is the institution's own letter number — free text, not unique, not addressable.
- **Times:** system timestamps `created_at` and `updated_at` are ISO 8601 UTC with no BS sibling. User-facing dates carry a Bikram Sambat sibling object: `issue_date_bs`, `response_deadline_bs`, `deposit_due_date_bs`, `decided_at_bs`, `due_date_bs`, `resolved_at_bs`. Each is `{ year, month, day, month_name_en, month_name_np, display_en, display_np }` or `null`. Writes accept Gregorian `YYYY-MM-DD` only.
- **Money:** decimal strings, never numbers. Every amount has a separate currency field and is `null` when unrecorded; an empty currency is `""`. Amounts are stored exactly as quoted and are never converted.
- **List/search/filter params:** on the offer list only — `journey`, `applicant`, `institution`, `program` (exact UUID), `status`, `offer_type` (exact enum), `intake` (substring of `intake_label`), `deadline_before` (`YYYY-MM-DD`, inclusive, excludes offers with no deadline), `fiscal_year` (`YYYY/YY`, on `created_at`). No text search parameter exists. Ordering is fixed newest-first and is not client-controllable.
- **Invalid query parameters are rejected with 400, not ignored.**
- **Empty text fields are `""`, never `null`.**

### 3. Models

**Offer (list shape)** — `{ id, journey, journey_stage:[enum], applicant_id, applicant_name, institution_name_en, campus_name, program_title, qualification_level:[enum], intake_label, offer_type:[enum], status:[enum], issue_date?, issue_date_bs?:json, response_deadline?, response_deadline_bs?:json, is_response_overdue, has_open_conditions, created_at }`

- `applicant_name` and `journey_stage` are reached through the journey and are read-only.
- `is_response_overdue` is true only when `status` is `issued` and the deadline has passed, computed in Nepal time.
- `has_open_conditions` is independent of `offer_type` — an `unconditional` offer with a pending condition reports `true`.

**Offer (detail shape)** — the list shape plus `{ institution?, campus?, program?, reference_source:[enum], institution_name_np, country_name, offer_reference, tuition_amount?, tuition_currency, tuition_fee_period:[enum], scholarship_amount?, scholarship_currency, scholarship_notes, deposit_amount?, deposit_currency, deposit_due_date?, deposit_due_date_bs?:json, deposit_notes, notes, is_terminal, decided_at?, decided_at_bs?:json, decision_reason, decided_by_username?, deferred_to_intake, created_by_username, conditions:list[Condition], updated_at }`

- Returned by retrieve, create, update, issue, and the decision action. Only the list returns the shorter shape.
- `institution`, `campus`, `program` are bare UUID strings or `null`, not nested objects. All three are `null` on a manually recorded offer.
- The seven snapshot fields are copied at creation and never change; they, not the foreign keys, are what the offer means.
- `deferred_to_intake` is non-empty only when `status` is `deferred`.
- `conditions` is always present, `[]` when there are none.

**Condition** — `{ id, condition_type:[enum], description, status:[enum], is_resolved, due_date?, due_date_bs?:json, display_order, resolution_note, resolved_at?, resolved_at_bs?:json, resolved_by_username?, created_at, updated_at }`

- Identical whether nested in the offer detail shape or returned as a row of the conditions list.

**HistoryEvent** — `{ id, action, actor_type:[enum], actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`

- `changes` maps field name to `{ from, to }`, both stringified; `{}` on events recording no field change.
- Condition events appear here carrying the offer's id, with the condition's id in `metadata.condition_id`.

### 4. Enums

- `Offer.status`: `draft` | `issued` | `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`
- Terminal statuses, where `is_terminal` is true: `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`
- `decision.outcome` request field: `accepted` | `rejected` | `withdrawn` | `deferred` | `expired` — a strict subset of `Offer.status`; sending `draft` or `issued` is a 400
- `Offer.offer_type`: `conditional` | `unconditional`
- `Offer.reference_source`: `catalogue` | `manual` — read-only, derived at creation
- `Offer.qualification_level`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other`, or `""`
- `Offer.tuition_fee_period`: `per_year` | `per_semester` | `total_program`, or `""`. Scholarship and deposit have no period field
- `Condition.condition_type`: `academic_result` | `english_test` | `document_submission` | `deposit_payment` | `interview` | `identity_confirmation` | `other`
- `Condition.status`: `pending` | `satisfied` | `waived` | `not_applicable`
- Resolved condition statuses, where `is_resolved` is true: `satisfied` | `waived` | `not_applicable`
- `HistoryEvent.action`: `offer_created` | `offer_updated` | `offer_issued` | `offer_decision_recorded` | `offer_condition_created` | `offer_condition_updated` | `offer_condition_status_changed`
- `HistoryEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `Offer.intake_label` and `Offer.deferred_to_intake` are **not** enums — free text, because intakes are not catalogued

### 5. Dependency order

- `Offer` needs an `ApplicantJourney` (external module: `applicant_journeys`) — sent in the body, never changeable afterwards.
- `Offer` optionally needs a `Program`, `Institution`, or `Campus` (external module: `institutions`) — only for a catalogue-sourced offer.
- `Condition` needs an `Offer` — supplied in the URL path on create.
- `ApplicantJourney` needs an `Applicant` (external module: `applicants`).

**Start here:** obtain a journey id, then `POST /api/v1/offers/`. Nothing in this module can be created from empty.

### 6. Endpoints

#### Offer — `/api/v1/offers/`

**Use it when:** the Offer List worklist, the Journey Detail offers panel via `?journey=`, the Offer Detail screen, and the New / Edit Offer form.

**Methods:**
- `GET /api/v1/offers/` — `offers.offer.list`
- `POST /api/v1/offers/` — `offers.offer.create`
- `GET /api/v1/offers/<offer_id>/` — `offers.offer.read`
- `PATCH /api/v1/offers/<offer_id>/` — `offers.offer.update`

**Send (create/update):**
- create: `journey` required; then either `program`, or `institution_name_en` + `program_title`; plus optional `institution`, `campus`, `institution_name_np`, `campus_name`, `country_name`, `qualification_level`, `intake_label`, `offer_type`, `offer_reference`, `issue_date`, `response_deadline`, `tuition_amount`, `tuition_currency`, `tuition_fee_period`, `scholarship_amount`, `scholarship_currency`, `scholarship_notes`, `deposit_amount`, `deposit_currency`, `deposit_due_date`, `deposit_notes`, `notes`, `conditions`
- update: any subset of `offer_type`, `offer_reference`, `issue_date`, `response_deadline`, the nine money fields, and `notes` — nothing else

**Returns:** Offer (detail shape) for create, retrieve, update; list[Offer (list shape)] for the list.

**Notes:**
- A `program` implies its own institution and campus; sending the program alone is sufficient.
- Caller-supplied snapshot text overrides the catalogue's on create — this is how a real `intake_label` is recorded while intakes remain uncatalogued.
- `reference_source` is derived, never sent.
- Defaults: `offer_type` is `conditional`, `status` is `draft`.
- On update, sending the journey, a catalogue reference, a snapshot field, `status`, or `conditions` returns 400 with every offending field in `details` — rejected, not silently dropped. This is the inverse of the `institutions` convention.
- `institution` and `program` filters match the catalogue foreign key, not the snapshot text, so manually recorded offers are correctly absent from them.
- There is no delete.

**Errors:**
- `OFFERS_JOURNEY_NOT_FOUND` (400) — no journey with that id
- `OFFERS_PROGRAM_REFERENCE_REQUIRED` (400) — neither a catalogue program nor the institution and program names were given
- `OFFERS_CATALOGUE_REFERENCE_INVALID` (400) — a catalogue id does not exist, or the campus/program does not belong to the institution
- `OFFERS_AMOUNT_INCOMPLETE` (400) — an amount was sent without its currency
- `OFFERS_REFERENCE_IMMUTABLE` (400) — a PATCH carried an immutable field
- `OFFERS_OFFER_NOT_FOUND` (404)

#### Offer: issue — `/api/v1/offers/<offer_id>/issue/`

**Use it when:** the Offer Detail primary action on a draft.

**Methods:**
- `POST /api/v1/offers/<offer_id>/issue/` — `offers.offer.issue`

**Send:** nothing.

**Returns:** Offer (detail shape) with `status` now `issued`.

**Notes:**
- The only transition into `issued`. Skipped when recording a historical offer, since a decision may be taken directly on a draft.

**Errors:**
- `OFFERS_OFFER_NOT_ISSUABLE` (409) — the offer is not a draft
- `OFFERS_OFFER_NOT_FOUND` (404)

#### Offer: decision — `/api/v1/offers/<offer_id>/decision/`

**Use it when:** the Decision Dialog.

**Methods:**
- `POST /api/v1/offers/<offer_id>/decision/` — `offers.offer.record_decision`

**Send:**
- `outcome` required
- `reason` — required for `rejected` and `withdrawn`
- `to_intake` — required for `deferred`, ignored otherwise

**Returns:** Offer (detail shape) with `status` set to the outcome and `decided_at` / `decided_by_username` stamped.

**Notes:**
- Permitted from `draft` or `issued`. A draft may be decided directly.
- A decision is final. There is no reopen endpoint, deliberately unlike `applicant_journeys`.
- Deferring an offer is not deferring the journey — the journey is untouched.
- The journey's stage and the applicant's status are never changed by this call.

**Errors:**
- `OFFERS_OFFER_NOT_DECIDABLE` (409) — the offer already has a terminal status
- `OFFERS_ACCEPTED_OFFER_EXISTS` (409) — the journey already has an accepted offer
- `OFFERS_DECISION_REASON_REQUIRED` (400)
- `OFFERS_DEFER_INTAKE_REQUIRED` (400)
- `OFFERS_OFFER_NOT_FOUND` (404)

#### Offer: history — `/api/v1/offers/<offer_id>/history/`

**Use it when:** the history panel on the Offer Detail screen.

**Methods:**
- `GET /api/v1/offers/<offer_id>/history/` — `offers.offer.list_history`

**Send:** none.

**Returns:** list[HistoryEvent], newest first, paginated.

**Notes:**
- Condition events are included; there is no separate condition history endpoint.
- Never empty for an existing offer — creation always writes one event.

**Errors:**
- `OFFERS_OFFER_NOT_FOUND` (404)

#### Offer Condition — `/api/v1/offers/<offer_id>/conditions/` and `/api/v1/offers/conditions/<condition_id>/`

**Use it when:** the conditions panel on the Offer Detail screen, and the condition list on the New / Edit Offer form.

**Methods:**
- `GET /api/v1/offers/<offer_id>/conditions/` — `offers.condition.list`
- `POST /api/v1/offers/<offer_id>/conditions/` — `offers.condition.create`
- `PATCH /api/v1/offers/conditions/<condition_id>/` — `offers.condition.update`

**Send (create/update):**
- create: `condition_type` required, `description` required, `due_date`, `display_order`
- update: any subset of `condition_type`, `description`, `due_date`, `display_order` — not `status`

**Returns:** Condition for create and update; list[Condition] for the list.

**Notes:**
- List and create are nested under the offer; update is not, because a condition never moves between offers.
- A condition may be added to an already-decided offer — institutions routinely do this.
- The offer detail response already nests the conditions, so this list is not needed to render that screen.
- Ordering is `display_order` then `created_at`, not client-controllable.
- There is no delete; use the status action with `not_applicable`.

**Errors:**
- `OFFERS_OFFER_NOT_FOUND` (404) — no offer with that id in the path
- `OFFERS_CONDITION_NOT_FOUND` (404)

#### Offer Condition: status — `/api/v1/offers/conditions/<condition_id>/status/`

**Use it when:** the tick / waive control on each row of the conditions panel.

**Methods:**
- `POST /api/v1/offers/conditions/<condition_id>/status/` — `offers.condition.change_status`

**Send:**
- `status` required
- `note` — required for `waived` and `not_applicable`

**Returns:** Condition, with `resolved_at` / `resolved_by_username` stamped for a resolved status and cleared for `pending`.

**Notes:**
- Moving back to `pending` is allowed and clears the resolution stamp; both transitions stay in the history.
- Re-sending the current status with no note is a no-op returning 200 and writing no event.
- The parent offer's `has_open_conditions` may change and is **not** in this response.

**Errors:**
- `OFFERS_CONDITION_NOTE_REQUIRED` (400)
- `OFFERS_CONDITION_NOT_FOUND` (404)

### 7. Flows

**Record an offer from the catalogue and run it to acceptance**

1. Obtain the journey id from the Journey Detail screen or `GET /api/v1/journeys/`.
2. Find the program — `GET /api/v1/catalogue/programs/?q=...` — and take its `id`.
3. `POST /api/v1/offers/` with `journey`, `program`, the money terms, `response_deadline`, and a `conditions` array. Returns the offer id at `status: draft`.
   - Neither branch of the reference completed → 400 `OFFERS_PROGRAM_REFERENCE_REQUIRED`.
   - An amount without its currency → 400 `OFFERS_AMOUNT_INCOMPLETE`.
4. `POST /api/v1/offers/<id>/issue/` → `status: issued`.
5. `POST /api/v1/offers/conditions/<condition_id>/status/` with `satisfied` as each requirement is met.
   - Waiving without a note → 400 `OFFERS_CONDITION_NOTE_REQUIRED`.
6. `POST /api/v1/offers/<id>/decision/` with `outcome: accepted` → `status: accepted`, `is_terminal: true`.
   - The journey already has an accepted offer → 409 `OFFERS_ACCEPTED_OFFER_EXISTS`.
7. To advance the journey, call `applicant_journeys.journey.change_stage` separately. This module never does it.

**Compare competing offers on one journey**

1. `GET /api/v1/offers/?journey=<journey_id>` → every offer, newest first.
2. Render `tuition_currency` beside every `tuition_amount` — amounts are never converted between currencies.
3. `POST /api/v1/offers/<id>/decision/` with `accepted` on the chosen one.
4. `POST /api/v1/offers/<other_id>/decision/` with `rejected` and a reason on each of the rest.
   - Already decided → 409 `OFFERS_OFFER_NOT_DECIDABLE`; refetch, someone else resolved it.

**Record a historical offer with no catalogue record**

1. `POST /api/v1/offers/` with `journey`, `institution_name_en`, and `program_title`, and no `program`. Returns `reference_source: manual` with all three catalogue foreign keys `null`.
2. `POST /api/v1/offers/<id>/decision/` immediately with the outcome it actually had — no issue step required.
3. The offer will not appear under `?institution=` or `?program=` filters, by design.

**Handle a lapsed offer**

1. `GET /api/v1/offers/?status=issued` and read `is_response_overdue` per row — nothing expires automatically.
2. `POST /api/v1/offers/<id>/decision/` with `outcome: expired`. No reason required.
3. If the applicant later responds, record a new offer; the expired one cannot be reopened.

### 8. Gaps

- No text search on the offer list. There is no `q` parameter, and the snapshot institution and program names cannot be searched at all. `intake` is the only substring filter.
- No `superseded_by` link, despite the concept mentioning supersession. Infer it from the newest-first ordering and from which offer is `accepted`.
- Intakes are free text in both `intake_label` and `deferred_to_intake`, because `institutions` has no Intake table. No date-based intake search, and `?intake=` misses `"February 2027"` when the stored value is `"Feb 2027"`.
- No supporting files. Nothing can be attached to an offer; the offer letter PDF has nowhere to live until `uploaded_files` exists.
- Offer conditions are owned entirely by this module and are not reusable across offers; whether they should become `checklists` items is undecided.
- Nothing reconciles a journey's free-text destination with the catalogue reference on its offers.
- The journey's stage is never driven by offer activity, so a journey can sit at `planning` with three issued offers and nothing flags it.
- No notification of an approaching or passed deadline. `is_response_overdue` is computed on read only.
- No currency conversion anywhere. Two offers on one journey may quote different currencies with no rate stored.
- Amounts are `Decimal(12,2)`; exceeding ten integer digits is a 400 from serializer validation.

---

## Applicant Journeys

### 1. Module

- **Name:** Applicant Journeys
- **Base path:** `/api/v1/journeys/`
- **Auth:** unchanged.

### 2. Conventions

No changes this session.

### 3. Models

No changes this session. `ApplicantJourney` gained no field; the response shape is unchanged.

### 4. Enums

No changes this session.

### 5. Dependency order

- Unchanged outbound. **Inbound gained one:** `offers.Offer.journey` is a `PROTECT` foreign key pointing here, so a journey with any offer cannot be removed. This app still references `offers` for nothing.

### 6. Endpoints

**No endpoint was added, changed, or retired in this app this session.** Documentation only: `docs/DATA_CONTRACT.md` records the new inbound dependency.

### 7. Flows

No flow in `concepts/applicant_journeys_flows.md` changed. `concepts/offers_flows.md` references `applicant_journeys.journey.change_stage` as an optional client-side step after an offer decision; that endpoint's own behaviour is unchanged.

### 8. Gaps

- A journey's stage is not driven by, and does not gate, offer activity. An offer may be recorded against a journey at any stage including a closed one, and no endpoint reports an inconsistency between the two.
- A journey still stores its destination as free text and has no reference into the catalogue, even though offers on it now do.

---

## Institutions

### 1. Module

- **Name:** Institutions
- **Base path:** `/api/v1/catalogue/`
- **Auth:** unchanged.

### 2. Conventions

No changes this session.

### 3. Models

No changes this session. No field, index, or response shape changed; `makemigrations --check` reports no change for this app.

### 4. Enums

`FeePeriod` moved from `institutions.constants` to `core.constants` and is re-exported, so every import site and every emitted value is unchanged. The value set `per_year` | `per_semester` | `total_program` is untouched.

### 5. Dependency order

- Unchanged outbound. **Inbound gained one:** `offers.Offer.institution`, `.campus`, and `.program` are nullable `PROTECT` foreign keys pointing here. A catalogue record referenced by any offer cannot be removed, but may still be renamed or deactivated freely — offers snapshot the names rather than reading through.

### 6. Endpoints

**No endpoint was added, changed, or retired in this app this session.** Documentation only.

### 7. Flows

No flow in `concepts/institutions_flows.md` changed. Its "Cross-app dependencies" note that no other app's flow file references an `institutions.*` key is now superseded by `concepts/offers_flows.md`, which references `institutions.program.list` and `institutions.program.read` as client-side steps.

### 8. Gaps

- Unchanged from the app's own contract. The `institutions` catalogue remains without an Intake table, which is why offers carry a free-text `intake_label`.

---

## Core

### 1. Module

- **Name:** Core — global infrastructure. Not a business app.
- **Base path:** none of its own beyond `/health/`, `/ready/`, and the `/api/v1/` mount.
- **Auth:** unchanged.

### 2. Conventions

No changes this session. The project-wide envelope, pagination, error-code naming, and money-as-string rules are unchanged.

### 3. Models

No changes this session. `core/models.py` still contains only the abstract `BaseModel`.

### 4. Enums

`core.constants.FeePeriod` is **new**, promoted from `institutions`: `per_year` | `per_semester` | `total_program`. Shared vocabulary now that two apps record a fee period.

### 5. Dependency order

Unchanged. `core` depends on no business app; every app depends on it.

### 6. Endpoints

**No endpoint was added, changed, or retired in `core` this session.** `core/api_urls.py` gained one include line mounting `offers` at `/api/v1/offers/`; the routes it exposes belong to `offers` and are documented under that app above.

### 7. Flows

No core-owned flow exists. `concepts/project_flows.md` gained two steps in the "Enquiry to study objective" journey, both delegating to `concepts/offers_flows.md`.

### 8. Gaps

- Permission-key-based authorization is still not enforced in the request path. Every `offers` endpoint has a registered `permission_key`, and no view consults one — the interim inline authority check is what actually gates access.
- Immutable-field handling on `PATCH` now differs between apps: `institutions` ignores, `offers` rejects. Recorded in `core/docs/INTEGRATION.md` §10 because a shared edit-form component carried between the two will fail on every save.
