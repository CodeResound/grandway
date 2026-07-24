# Integration — Offers

**Owner app:** `offers`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial integration contract — 11 endpoints across two resources |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. Named the two calls that back the Offer Detail supporting-files section |

---

## 1. Module

- **Name:** Offers — the formal admission decisions institutions make against applicant journeys. Records what was offered, for which program and intake, on what money terms, under what conditions, and how the applicant responded. It is **the source of truth for decision records**, not for the study plan: a journey's stage may say offers are being awaited, but only this module knows what was actually offered.
- **Base path:** `/api/v1/offers/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. Two authority types may use this module — `admin` and `lead_manager` — with **identical** rights on every endpoint. A `superadmin` token is rejected with 403 everywhere, including on reads.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which decides whether the caller may act at all. | Every endpoint returns 401; a `superadmin` gets 403 `OFFERS_ACTOR_FORBIDDEN` everywhere, reads included. |
| `applicant_journeys` | FK + service call | Every offer belongs to exactly one journey, supplied on create and never changeable. The journey is also where the applicant's identity is reached from. | Offers cannot be created at all — there is nothing to attach them to. `POST` returns 400 `OFFERS_JOURNEY_NOT_FOUND` for any journey id that does not resolve. |
| `institutions` | FK (optional) | Supplies the catalogue records an offer is built from, and the names copied into its snapshot. | Catalogue-sourced offers become impossible; manual offers still work in full, so the module degrades rather than fails. The `institution` and `program` list filters return nothing. |
| `audit` | service call | Every mutation, including every condition change, appends one immutable event carrying the changed fields' previous and new values. This module stores no history of its own. | Offers still record correctly but leave no trace of who decided what — and `GET /offers/<id>/history/` returns an empty list rather than failing. |

**This module writes to nothing outside itself.** Recording, issuing, or deciding an offer does **not** change the journey's `stage`, the applicant's `status`, or any catalogue record. A client that expects a journey to advance to `offer_stage` when an offer is recorded must make that call itself, against `applicant_journeys.journey.change_stage`.

**This is the first module that links `institutions` to `applicant_journeys`.** Both apps shipped as islands — journeys still store their destination as free text (`target_country`, `target_institution_name`, `target_program_name`) and do not reference the catalogue. An offer references both, but does not reconcile them: a journey saying "Melbourne" and an offer pointing at a catalogue Melbourne record are still two unconnected facts. See §9.

## 3. Conventions

- **Access — one rule, everywhere.** `admin` and `lead_manager` may do everything on every endpoint; `superadmin` may do nothing, reads included. There is **no read/write split** here — unlike `institutions`, where writes are Admin-only. Do not carry that assumption across: an offers screen needs no authority-based control hiding.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint in this module**, and no way to remove an offer or a condition. An offer that no longer applies gets a terminal status; a condition that does not apply becomes `not_applicable`. Do not build a delete button; build a decision control and a condition-status control.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is **abridged to three fields to show the envelope**; a real create returns the full `Offer` shape defined in §4.

```json
{
  "success": true,
  "message": "Offer recorded.",
  "data": { "id": "9a1f4c2e-7b3d-4e58-9a01-2c3d4e5f6071", "program_title": "Master of Information Technology", "status": "draft" },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract, and may change without a version bump. Branch on the HTTP status and, for errors, on `error.code`.

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object that is always present — `{}` when there are no field-level errors.

```json
{
  "success": false,
  "error": {
    "code": "OFFERS_ACCEPTED_OFFER_EXISTS",
    "message": "This journey already has an accepted offer.",
    "details": {}
  },
  "meta": {}
}
```

Field-level validation failures come from the serializer layer and put the offending fields inside `details`:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { "outcome": ["\"issued\" is not a valid choice."] }
  },
  "meta": {}
}
```

- **HTTP status codes:** `POST` that creates returns **201**; `POST` that acts on an existing record (issue, decision, condition status) returns **200**. `GET` and `PATCH` return **200**. Domain-rule violations are **400**, except state conflicts — issuing a non-draft, deciding a decided offer, accepting a second offer — which are **409**. Missing records named in the **URL path** are **404**. Authority failures are **403**. An unrouted method is **405** with the project-wide `METHOD_NOT_ALLOWED` code, still inside the standard envelope.
- **Auth failures:** 401 with no token, an expired token, or a revoked session — produced by the authentication framework. 403 `OFFERS_ACTOR_FORBIDDEN` when the token is valid but the authority may not act, which in this module means exactly one case: a `superadmin`. Its body:

```json
{
  "success": false,
  "error": {
    "code": "OFFERS_ACTOR_FORBIDDEN",
    "message": "Your authority level may not perform this action.",
    "details": {}
  },
  "meta": {}
}
```

  **This module's 403 code replaces the project-wide `PERMISSION_DENIED`, it does not coexist with it.** You will not see `PERMISSION_DENIED` from `/api/v1/offers/`. It is omitted from the per-endpoint `Errors` lists in §7, since it applies identically to all eleven.

- **Unknown ids in the request *body* are 400, not 404.** Sending a `journey`, `institution`, `campus`, or `program` id that does not exist returns 400 with a module code (`OFFERS_JOURNEY_NOT_FOUND` or `OFFERS_CATALOGUE_REFERENCE_INVALID`). A **404 is only ever about the record named in the URL path** — the offer id or the condition id.
- **The reference block and `status` are immutable, and a `PATCH` carrying them is REJECTED, not ignored.** `journey`, `institution`, `campus`, `program`, `reference_source`, all seven snapshot fields, `status`, and `conditions` return 400 `OFFERS_REFERENCE_IMMUTABLE` with every offending field listed in `details`. **This is the opposite of the `institutions` convention**, where immutable fields are silently dropped — do not carry a read-modify-write-the-whole-object edit form across from that module, or every save will fail. Send only the fields the user actually changed.
- **A `PATCH` that changes nothing writes no audit event.** The response is still 200 with the unchanged record. A UI reporting "saved, history updated" after an unchanged submit will be claiming something that did not happen.
- **Query parameter encoding.** Invalid query parameters are **rejected with 400, not ignored** — `?deadline_before=soon` or `?status=maybe` returns a validation error rather than an unfiltered result set. Dates are `YYYY-MM-DD` (Gregorian, never Bikram Sambat). `page_size` above the 100 maximum is clamped, not rejected.
- **Request encoding:** `application/json`.
- **Pagination:** page-number based. Params `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `next`/`previous` are absolute URLs including scheme and host, or `null`. Applied to **every** list endpoint here, including the conditions list and the history list.
- **IDs:** UUID strings throughout. There is no human-readable code on any resource. `offer_reference` is the *institution's* own letter number — free text, not unique, not an identifier you can address a record by.
- **Times.** Two different rules, and the difference matters:
  - System timestamps — `created_at`, `updated_at` — are ISO 8601 UTC with **no** `_bs` sibling.
  - **User-facing dates carry a Bikram Sambat sibling** (§39.4): `issue_date_bs`, `response_deadline_bs`, `deposit_due_date_bs`, `decided_at_bs`, and on conditions `due_date_bs` and `resolved_at_bs`. Each is an object or `null`, never a string. Shape: `{ year, month, day, month_name_en, month_name_np, display_en, display_np }`. **Write the Gregorian field; read either.** There is no BS input anywhere — `POST`/`PATCH` accept `YYYY-MM-DD` only.
  - `is_response_overdue` is computed in **Nepal time** (UTC+5:45), not UTC. Near midnight NPT a client computing it locally from `response_deadline` may briefly disagree with the server; trust the server's flag.
- **Money:** decimal **strings**, never numbers — `"49824.00"`. Never parse into a float. Every amount has a separate currency field and is `null` when unrecorded; an empty currency is `""`, not `null`. **Amounts are stored exactly as the institution quoted them and are never converted** — two offers on one journey may be in different currencies, and nothing in this module normalizes them. Render the currency on every figure.
- **Empty text fields are `""`, never `null`.** Nullable fields are the dates (`issue_date`, `response_deadline`, `deposit_due_date`, `due_date`), the amounts, `decided_at`, `resolved_at`, the three catalogue FKs, and the `*_username` fields.

## 4. Models

**Offer (list shape)** — `{ id, journey, journey_stage:[enum], applicant_id, applicant_name, institution_name_en, campus_name, program_title, qualification_level:[enum], intake_label, offer_type:[enum], status:[enum], issue_date?, issue_date_bs?:json, response_deadline?, response_deadline_bs?:json, is_response_overdue, has_open_conditions, created_at }`

- `applicant_name` and `journey_stage` are reached **through** the journey and are read-only here. `journey_stage` is `applicant_journeys`' enum, not this module's.
- `is_response_overdue` is true only when `status` is `issued` **and** the deadline has passed. An overdue `draft` reports `false` — a draft was never issued, so nothing is late.
- `has_open_conditions` is true when any condition is not `satisfied`, `waived`, or `not_applicable`. It is **independent of `offer_type`**: an `unconditional` offer with a pending condition attached reports `true`.

**Offer (detail shape)** — the list shape plus `{ institution?, campus?, program?, reference_source:[enum], institution_name_np, country_name, offer_reference, tuition_amount?, tuition_currency, tuition_fee_period:[enum], scholarship_amount?, scholarship_currency, scholarship_notes, deposit_amount?, deposit_currency, deposit_due_date?, deposit_due_date_bs?:json, deposit_notes, notes, is_terminal, decided_at?, decided_at_bs?:json, decision_reason, decided_by_username?, deferred_to_intake, created_by_username, conditions:list[Condition], updated_at }`

- The detail shape is returned by retrieve, create, update, issue, **and** the decision action. Only the list returns the shorter shape.
- `institution`, `campus`, and `program` are **bare UUID strings or `null`** — not nested objects. To show the live catalogue record, fetch it from `/api/v1/catalogue/`. They are `null` on a manually recorded offer.
- **The snapshot fields, not the FKs, are what the offer means.** `institution_name_en`, `campus_name`, `program_title`, `country_name`, `qualification_level`, and `intake_label` are copied at creation and never change afterwards — a program renamed or an institution marked inactive in the catalogue leaves them untouched. Render these, not a freshly-fetched catalogue record, anywhere the offer is displayed.
- `deferred_to_intake` is non-empty only when `status` is `deferred`.
- `conditions` is always present on the detail shape, `[]` when there are none.

**Condition** — `{ id, condition_type:[enum], description, status:[enum], is_resolved, due_date?, due_date_bs?:json, display_order, resolution_note, resolved_at?, resolved_at_bs?:json, resolved_by_username?, created_at, updated_at }`

- Returned nested inside the offer detail shape, and as the row shape of the conditions list endpoint. The two are identical.
- Ordered by `display_order`, then `created_at`. Not client-controllable.

**HistoryEvent** — `{ id, action, actor_type:[enum], actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`

- `changes` is a map of field name to `{ "from": "...", "to": "..." }`, both stringified. `{}` on events that record no field change (creation, condition events).
- `metadata` is free-form per action — do not rely on a key being present without checking.
- **Condition events appear in the offer's history**, not in a separate log: `offer_condition_created`, `offer_condition_updated`, and `offer_condition_status_changed` all carry the *offer's* id, with the condition's id inside `metadata.condition_id`.

### Worked examples

**Offer (detail shape), issued with one outstanding condition**

```json
{
  "id": "9a1f4c2e-7b3d-4e58-9a01-2c3d4e5f6071",
  "journey": "5e6f7081-9a2b-4c3d-8e4f-5061728394a5",
  "journey_stage": "offer_stage",
  "applicant_id": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819",
  "applicant_name": "राम बहादुर",
  "institution": "2d3e4f50-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
  "campus": "3e4f5061-7b8c-4d9e-af01-2b3c4d5e6f70",
  "program": "4f506172-8c9d-4e0f-b112-3c4d5e6f7081",
  "reference_source": "catalogue",
  "institution_name_en": "University of Melbourne",
  "institution_name_np": "",
  "campus_name": "Parkville",
  "program_title": "Master of Information Technology",
  "country_name": "Australia",
  "qualification_level": "masters",
  "intake_label": "Feb 2027",
  "offer_type": "conditional",
  "offer_reference": "UOM-2026-118842",
  "issue_date": "2026-07-18",
  "issue_date_bs": {
    "year": 2083, "month": 4, "day": 2,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 2", "display_np": "२०८३ श्रावण २"
  },
  "response_deadline": "2026-09-30",
  "response_deadline_bs": {
    "year": 2083, "month": 6, "day": 14,
    "month_name_en": "Ashwin", "month_name_np": "आश्विन",
    "display_en": "2083 Ashwin 14", "display_np": "२०८३ आश्विन १४"
  },
  "is_response_overdue": false,
  "tuition_amount": "49824.00",
  "tuition_currency": "AUD",
  "tuition_fee_period": "total_program",
  "scholarship_amount": "12456.00",
  "scholarship_currency": "AUD",
  "scholarship_notes": "Graduate Access Scholarship — 25% of tuition.",
  "deposit_amount": "5000.00",
  "deposit_currency": "AUD",
  "deposit_due_date": "2026-08-29",
  "deposit_due_date_bs": {
    "year": 2083, "month": 5, "day": 13,
    "month_name_en": "Bhadra", "month_name_np": "भाद्र",
    "display_en": "2083 Bhadra 13", "display_np": "२०८३ भाद्र १३"
  },
  "deposit_notes": "Non-refundable after the response deadline.",
  "status": "issued",
  "is_terminal": false,
  "has_open_conditions": true,
  "notes": "",
  "decided_at": null,
  "decided_at_bs": null,
  "decision_reason": "",
  "decided_by_username": null,
  "deferred_to_intake": "",
  "created_by_username": "leadmgr",
  "conditions": [
    {
      "id": "7c8d9e0f-1a2b-4c3d-9e4f-506172839405",
      "condition_type": "english_test",
      "description": "IELTS overall 6.5 with no band below 6.0.",
      "status": "pending",
      "is_resolved": false,
      "due_date": "2026-08-15",
      "due_date_bs": {
        "year": 2083, "month": 4, "day": 30,
        "month_name_en": "Shrawan", "month_name_np": "श्रावण",
        "display_en": "2083 Shrawan 30", "display_np": "२०८३ श्रावण ३०"
      },
      "display_order": 0,
      "resolution_note": "",
      "resolved_at": null,
      "resolved_at_bs": null,
      "resolved_by_username": null,
      "created_at": "2026-07-24T09:18:47Z",
      "updated_at": "2026-07-24T09:18:47Z"
    }
  ],
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T09:20:11Z"
}
```

**Offer (detail shape), manually recorded historical entry, no catalogue record**

```json
{
  "id": "8b0e3d1f-6a2c-4d47-8f90-1b2c3d4e5f60",
  "journey": "5e6f7081-9a2b-4c3d-8e4f-5061728394a5",
  "journey_stage": "completed",
  "applicant_id": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819",
  "applicant_name": "राम बहादुर",
  "institution": null,
  "campus": null,
  "program": null,
  "reference_source": "manual",
  "institution_name_en": "Ancient Polytechnic",
  "institution_name_np": "",
  "campus_name": "",
  "program_title": "Diploma in Hospitality",
  "country_name": "",
  "qualification_level": "",
  "intake_label": "Sep 2019",
  "offer_type": "unconditional",
  "offer_reference": "",
  "issue_date": null,
  "issue_date_bs": null,
  "response_deadline": null,
  "response_deadline_bs": null,
  "is_response_overdue": false,
  "tuition_amount": null,
  "tuition_currency": "",
  "tuition_fee_period": "",
  "scholarship_amount": null,
  "scholarship_currency": "",
  "scholarship_notes": "",
  "deposit_amount": null,
  "deposit_currency": "",
  "deposit_due_date": null,
  "deposit_due_date_bs": null,
  "deposit_notes": "",
  "status": "rejected",
  "is_terminal": true,
  "has_open_conditions": false,
  "notes": "Recorded from the paper file during migration.",
  "decided_at": "2026-07-24T10:02:00Z",
  "decided_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
  },
  "decision_reason": "Applicant chose a different destination.",
  "decided_by_username": "adminuser",
  "deferred_to_intake": "",
  "created_by_username": "adminuser",
  "conditions": [],
  "created_at": "2026-07-24T10:01:12Z",
  "updated_at": "2026-07-24T10:02:00Z"
}
```

## 5. Enums

- `Offer.status`: `draft` | `issued` | `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`
  - **Terminal statuses** (`is_terminal` is true, no further decision accepted): `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`.
  - **There is no `awaiting_response`** — `issued` covers it. An issued offer is by definition awaiting a response.
  - `expired` is only ever set by a person through the decision action. **Nothing expires automatically**; use `is_response_overdue` to surface offers that have lapsed.
- `decision.outcome` (request field, not a stored enum): `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`. A strict subset of `Offer.status` — sending `draft` or `issued` is a 400.
- `Offer.offer_type`: `conditional` | `unconditional`
- `Offer.reference_source`: `catalogue` | `manual`. Read-only, derived at creation.
- `Offer.qualification_level`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other`, or `""` when unrecorded. **The same value set as `institutions` `Program.qualification_level` and `applicant_journeys` `Journey.study_level`**, deliberately.
- `Offer.tuition_fee_period`: `per_year` | `per_semester` | `total_program`, or `""`. Same set as `institutions` `Program.tuition_fee_period`. **Scholarship and deposit have no period field** — only tuition does.
- `Condition.condition_type`: `academic_result` | `english_test` | `document_submission` | `deposit_payment` | `interview` | `identity_confirmation` | `other`
- `Condition.status`: `pending` | `satisfied` | `waived` | `not_applicable`
  - **Resolved statuses** (`is_resolved` is true, no longer counts toward `has_open_conditions`): `satisfied` | `waived` | `not_applicable`.
- `HistoryEvent.action`: `offer_created` | `offer_updated` | `offer_issued` | `offer_decision_recorded` | `offer_condition_created` | `offer_condition_updated` | `offer_condition_status_changed`
- `HistoryEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai` — the `audit` module's enum. In practice only `admin` and `lead_manager` appear here.
- `Offer.intake_label` and `Offer.deferred_to_intake`: **not enums** — free text, because intakes are not catalogued in this phase (see §9).
- `Offer.offer_reference`: **not an enum and not an identifier** — the institution's own letter number, free text.

## 6. Dependency order

- `Offer` needs an `ApplicantJourney` **(external module: `applicant_journeys`)** — supplied in the request body, never changeable afterwards.
- `Offer` optionally needs a `Program`, `Institution`, or `Campus` **(external module: `institutions`)** — only for a catalogue-sourced offer. A manual offer needs none.
- `Condition` needs an `Offer` — supplied in the URL path on create.
- An `ApplicantJourney` needs an `Applicant` **(external module: `applicants`)**, which needs no offer.

**Start here:** you cannot create anything in this module from empty. Obtain a journey id first — either from `GET /api/v1/journeys/` or from the journey you are already viewing — then `POST /api/v1/offers/`.

## 7. Endpoints

### Offer — `/api/v1/offers/`

**Use it when:** the Offer List worklist, the Journey Detail offers panel (`?journey=<id>`), the Offer Detail screen, and the New / Edit Offer form.

**Methods:**
- `GET /api/v1/offers/` — list (permission: `offers.offer.list`, risk: low)
- `POST /api/v1/offers/` — create (permission: `offers.offer.create`, risk: medium)
- `GET /api/v1/offers/<offer_id>/` — retrieve (permission: `offers.offer.read`, risk: low)
- `PATCH /api/v1/offers/<offer_id>/` — update (permission: `offers.offer.update`, risk: medium)

**Send (create/update):**
- create: `journey` (required, UUID); **the reference, one of two ways** — either `program` (UUID, which implies its own institution and campus) or the snapshot text `institution_name_en` + `program_title`; plus optionally `institution`, `campus`, `institution_name_np`, `campus_name`, `country_name`, `qualification_level`, `intake_label`, `offer_type`, `offer_reference`, `issue_date`, `response_deadline`, `tuition_amount`, `tuition_currency`, `tuition_fee_period`, `scholarship_amount`, `scholarship_currency`, `scholarship_notes`, `deposit_amount`, `deposit_currency`, `deposit_due_date`, `deposit_notes`, `notes`, and `conditions` (an array of `{condition_type, description, due_date?, display_order?}`)
- update: any subset of `offer_type`, `offer_reference`, `issue_date`, `response_deadline`, the nine money fields, and `notes` — **and nothing else**

**Returns:** Offer (detail shape) for create, retrieve, and update; list[Offer (list shape)] for the list, paginated.

**Requires state:** an existing journey. For a catalogue-sourced offer, an existing program — and if `campus` or `program` is sent alongside `institution`, each must belong to that institution. Nothing about the journey's stage is checked: an offer may be recorded against a journey at any stage, including a closed or completed one.

**Side effects:** appends `offer_created` / `offer_updated` to the central audit log. Conditions supplied at create are created in the same transaction and each appears in the returned `conditions` array. **Nothing outside this module changes** — in particular the journey's `stage` is untouched.

**Notes:**
- **List filters:** `journey`, `applicant`, `institution`, `program` (all exact UUIDs), `status`, `offer_type` (exact enums), `intake` (partial match on `intake_label`), `deadline_before` (`YYYY-MM-DD`, inclusive, and excludes offers with no deadline), `fiscal_year` (`YYYY/YY`, Nepali fiscal year, filtered on `created_at`).
- **`institution` and `program` filter the catalogue FK, not the snapshot text.** A manually recorded offer has no FK and is therefore correctly absent from those filters — including when its snapshot names the same institution. There is no text search on this endpoint at all (see §9).
- Ordering is fixed: newest `created_at` first. Not client-controllable — there is no `sort` or `ordering` parameter.
- **Defaults for omitted write fields:** `offer_type` → `"conditional"`, `status` → `"draft"`. Every unset text field is `""`; every unset date and amount is `null`.
- `reference_source` is **derived, never sent**: `catalogue` when any catalogue FK resolved, `manual` otherwise.
- **Caller-supplied snapshot text wins over the catalogue's** on create. Sending `program` *and* `intake_label: "Feb 2027"` stores your intake label, not the program's generic `intake_pattern`. This is how a real intake gets recorded while intakes remain uncatalogued.
- **On update, sending an immutable field is a 400, not a silent no-op.** See §3.
- There is no delete.

**Errors:**
- `OFFERS_JOURNEY_NOT_FOUND` (400) — no journey with that id, on create
- `OFFERS_PROGRAM_REFERENCE_REQUIRED` (400) — neither a catalogue program nor the institution and program names were given
- `OFFERS_CATALOGUE_REFERENCE_INVALID` (400) — a catalogue id does not exist, or the campus/program does not belong to the institution
- `OFFERS_AMOUNT_INCOMPLETE` (400) — a tuition, scholarship, or deposit amount was sent without its currency
- `OFFERS_REFERENCE_IMMUTABLE` (400) — a `PATCH` carried the journey, a catalogue reference, a snapshot field, `status`, or `conditions`
- `OFFERS_OFFER_NOT_FOUND` (404) — no offer with that id in the path

### Offer: issue — `/api/v1/offers/<offer_id>/issue/`

**Use it when:** the Offer Detail screen's primary action on a draft — the institution has now formally issued what was recorded.

**Methods:**
- `POST /api/v1/offers/<offer_id>/issue/` — (permission: `offers.offer.issue`, risk: medium)

**Send:** nothing. An empty JSON object is fine.

**Returns:** Offer (detail shape), with `status` now `issued`.

**Requires state:** the offer's `status` must be `draft`. This is the only transition into `issued`.

**Side effects:** appends `offer_issued` to the audit log. From this point `is_response_overdue` becomes meaningful.

**Errors:**
- `OFFERS_OFFER_NOT_ISSUABLE` (409) — the offer is not a draft
- `OFFERS_OFFER_NOT_FOUND` (404)

### Offer: decision — `/api/v1/offers/<offer_id>/decision/`

**Use it when:** the Decision Dialog — accept, reject, withdraw, defer, or mark expired.

**Methods:**
- `POST /api/v1/offers/<offer_id>/decision/` — (permission: `offers.offer.record_decision`, risk: high)

**Send:**
- `outcome` (required): `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`
- `reason`: **required for `rejected` and `withdrawn`**, optional otherwise
- `to_intake`: **required for `deferred`**, ignored for every other outcome

**Returns:** Offer (detail shape), with `status` set to the outcome and `decided_at` / `decided_by_username` stamped.

**Requires state:** the offer's `status` must be `draft` or `issued`. **A decision may be recorded on a draft** — an offer entered from a paper file that was resolved years ago never needs issuing first. For `accepted`, the journey must have no other accepted offer.

**Side effects:** appends `offer_decision_recorded` to the audit log with the outcome as the event's `reason`. **The journey's stage is not changed, and neither is the applicant's status** — if the UI should advance the journey on acceptance, it must call `applicant_journeys.journey.change_stage` itself.

**Notes:**
- **A decision is final. There is no reopen endpoint** — unlike `applicant_journeys`, which has one. An institution that changes its position has issued a new offer; record a second offer rather than looking for a way to undo the first.
- `deferred` on an offer is not the same as deferring the *journey* (`applicant_journeys.journey.defer`). This one moves a single institutional decision to a later intake and leaves the journey untouched.

**Errors:**
- `OFFERS_OFFER_NOT_DECIDABLE` (409) — the offer already has a terminal status
- `OFFERS_ACCEPTED_OFFER_EXISTS` (409) — this journey already has an accepted offer
- `OFFERS_DECISION_REASON_REQUIRED` (400) — `rejected` or `withdrawn` sent with no reason
- `OFFERS_DEFER_INTAKE_REQUIRED` (400) — `deferred` sent with no `to_intake`
- `OFFERS_OFFER_NOT_FOUND` (404)

### Offer: history — `/api/v1/offers/<offer_id>/history/`

**Use it when:** the history panel on the Offer Detail screen.

**Methods:**
- `GET /api/v1/offers/<offer_id>/history/` — (permission: `offers.offer.list_history`, risk: low)

**Send:** nothing.

**Returns:** list[HistoryEvent], newest first, paginated.

**Requires state:** the offer must exist.

**Side effects:** none.

**Notes:**
- **Condition events are included here**, carrying the offer's id with `metadata.condition_id` naming the condition. There is no separate condition history endpoint.
- The list is never empty for an existing offer — creation always writes one event.

**Errors:**
- `OFFERS_OFFER_NOT_FOUND` (404)

### Offer Condition — `/api/v1/offers/<offer_id>/conditions/` and `/api/v1/offers/conditions/<condition_id>/`

**Use it when:** the conditions panel on the Offer Detail screen, and the condition list on the New / Edit Offer form.

**Methods:**
- `GET /api/v1/offers/<offer_id>/conditions/` — list one offer's conditions (permission: `offers.condition.list`, risk: low)
- `POST /api/v1/offers/<offer_id>/conditions/` — create (permission: `offers.condition.create`, risk: medium)
- `PATCH /api/v1/offers/conditions/<condition_id>/` — update (permission: `offers.condition.update`, risk: medium)

**Send (create/update):**
- create: `condition_type` (required), `description` (required), `due_date`, `display_order`
- update: any subset of `condition_type`, `description`, `due_date`, `display_order` — **not `status`**

**Returns:** Condition for create and update; list[Condition] for the list, paginated.

**Requires state:** an existing offer, named in the URL path on list and create. **The offer's status is not checked** — a condition may be added to a decided offer, because institutions routinely attach one after acceptance.

**Side effects:** appends `offer_condition_created` / `offer_condition_updated` to the audit log, **against the offer's id**. Adding an unresolved condition flips the offer's `has_open_conditions` to `true`.

**Notes:**
- **The list and create routes are nested under the offer; update is not.** A condition never moves between offers, so the offer is a path segment on create and carries no information once you hold the condition id.
- `offer` is **never sent in the body**; sending it is ignored.
- The conditions returned nested in the offer detail shape are the same objects this endpoint lists — you do not need to call it separately to render the Offer Detail screen.
- Ordering is `display_order`, then `created_at`. Not client-controllable.
- There is no delete. Use the status action with `not_applicable`.

**Errors:**
- `OFFERS_OFFER_NOT_FOUND` (404) — no offer with that id in the path
- `OFFERS_CONDITION_NOT_FOUND` (404) — no condition with that id

### Offer Condition: status — `/api/v1/offers/conditions/<condition_id>/status/`

**Use it when:** the tick / waive control on each row of the conditions panel.

**Methods:**
- `POST /api/v1/offers/conditions/<condition_id>/status/` — (permission: `offers.condition.change_status`, risk: medium)

**Send:**
- `status` (required): `pending` | `satisfied` | `waived` | `not_applicable`
- `note`: **required for `waived` and `not_applicable`**, optional otherwise

**Returns:** Condition, with `resolved_at` / `resolved_by_username` stamped when the new status is a resolved one.

**Requires state:** the condition must exist. Its offer's status is not checked.

**Side effects:** appends `offer_condition_status_changed` to the audit log against the **offer's** id. May flip the offer's `has_open_conditions` — refetch the offer, or recompute locally, after this call.

**Notes:**
- **Moving back to `pending` is allowed** and clears `resolved_at` and `resolved_by_username`. A document rejected on review is a real event; both transitions stay in the history.
- Sending the current status again with no note is a no-op that still returns 200 and writes no event.
- `satisfied` deliberately requires no note — it is a fact, whereas waiving an institution's requirement is a judgement someone may have to defend.

**Errors:**
- `OFFERS_CONDITION_NOTE_REQUIRED` (400) — `waived` or `not_applicable` sent with no note
- `OFFERS_CONDITION_NOT_FOUND` (404)

## 8. Flows

**Record an offer from the catalogue and run it to acceptance**

1. Obtain the journey id — from the Journey Detail screen the user is on, or `GET /api/v1/journeys/`.
2. Find the program — `GET /api/v1/catalogue/programs/?q=...` (cross-module). Take its `id`.
3. `POST /api/v1/offers/` with `journey`, `program`, the money terms from the offer letter, `response_deadline`, and a `conditions` array. → offer id, `status: "draft"`.
   - Missing both a program and the snapshot names → 400 `OFFERS_PROGRAM_REFERENCE_REQUIRED`.
   - An amount without its currency → 400 `OFFERS_AMOUNT_INCOMPLETE`; highlight the amount and currency inputs together as one control.
4. `POST /api/v1/offers/<id>/issue/` → `status: "issued"`. `is_response_overdue` now becomes meaningful.
5. Work the conditions — `POST /api/v1/offers/conditions/<condition_id>/status/` with `satisfied` as each is met.
   - Waiving one without a note → 400 `OFFERS_CONDITION_NOTE_REQUIRED`; the note input is mandatory for `waived` and `not_applicable` only.
6. `POST /api/v1/offers/<id>/decision/` with `outcome: "accepted"` → `status: "accepted"`, `is_terminal: true`.
   - The journey already has an accepted offer → 409 `OFFERS_ACCEPTED_OFFER_EXISTS`. Show which one, from `GET /api/v1/offers/?journey=<id>&status=accepted`.
7. **If the journey should now advance**, call `applicant_journeys.journey.change_stage` separately. This module will not do it.

**Compare competing offers on one journey**

1. `GET /api/v1/offers/?journey=<journey_id>` → every offer, newest first.
2. Render `institution_name_en`, `program_title`, `intake_label`, `status`, `response_deadline`, and `is_response_overdue` per row.
   - **Render `tuition_currency` beside every `tuition_amount`.** Amounts are never converted, so two rows may be in different currencies and are not directly comparable.
3. Accept one — `POST /api/v1/offers/<id>/decision/` with `accepted`.
4. Resolve the others — `POST /api/v1/offers/<other_id>/decision/` with `rejected` and a reason.
   - No reason → 400 `OFFERS_DECISION_REASON_REQUIRED`.
   - Already decided → 409 `OFFERS_OFFER_NOT_DECIDABLE`. Refetch; someone else resolved it.

**Record a historical offer with no catalogue record**

1. `POST /api/v1/offers/` with `journey`, `institution_name_en`, `program_title`, and whatever else is known — **no `program`**. → `reference_source: "manual"`, all three catalogue FKs `null`.
2. Optionally `POST /api/v1/offers/<id>/decision/` straight away with the outcome it actually had. **No issue step is required** — a decision may be recorded on a draft.
3. The offer will not appear under `?institution=` or `?program=` filters, by design. It has no catalogue link to filter on.

**Handle a lapsed offer**

1. `GET /api/v1/offers/?status=issued` and read `is_response_overdue` on each row — **nothing expires automatically**; there is no background job in this deployment.
2. `POST /api/v1/offers/<id>/decision/` with `outcome: "expired"` → `status: "expired"`, `is_terminal: true`. No reason is required.
3. If the applicant later responds after all, record a **new** offer. The expired one cannot be reopened.

## 9. Gaps

- **No text search on the offer list.** There is no `q` parameter. `intake` matches `intake_label` partially and that is the only substring filter — the snapshot institution and program names cannot be searched at all. A client wanting "find offers from Melbourne" must either filter by the catalogue `institution` id (which misses every manual offer) or fetch and filter client-side.
- **No `superseded_by` link.** The concept says an offer "may be superseded by a later offer for the same journey", but nothing records that relationship. Infer it from the newest-first ordering of `GET /offers/?journey=<id>`, or from which offer is `accepted`. If a UI needs an explicit "superseded" badge, it must define the rule itself.
- **Intakes are free text.** `intake_label` and `deferred_to_intake` are unstructured strings, because `institutions` has no Intake table in its Phase 1 (`concepts/institutions.txt` — "Still open, and blocking Phase 2"). So there is no date-based intake search, no way to group offers by intake reliably, and `?intake=` is a substring match that will miss `"February 2027"` when the stored value is `"Feb 2027"`. Normalise on input in the UI if you need grouping.
- **No supporting files *on this resource*.** The concept lists supporting files as offer information; only `notes` exists here. **The `uploaded_files` module (`/api/v1/files/`) is now built** and an offer letter does have a home: `POST /api/v1/files/` with `offer=<offer_id>`, `category=offer_letter`, listed with `GET /api/v1/files/?offer=<offer_id>`. But **an offer payload carries no file references of any kind** — no count, no ids. A screen showing an offer and its letter makes two calls and joins them itself.
- **Offer conditions are not `checklists`.** The `checklists` domain is named in the project overview and not built. Whether offer conditions should eventually become checklist items is an open question; today they are owned entirely by this module and are not reusable across offers.
- **Nothing reconciles a journey's free-text destination with the offer's catalogue reference.** A journey may say `target_institution_name: "Melbourne Uni"` while an offer on it points at the catalogue's "University of Melbourne". Both are stored; nothing compares them, and no endpoint reports a mismatch.
- **The journey's stage is never driven by offer activity.** Deliberate, but it means a journey can sit at `planning` with three issued offers on it, and no API surface flags the inconsistency.
- **No notification of an approaching or passed deadline.** `is_response_overdue` is computed on read only. Nothing polls, emails, or alerts — the `notifications` module does not exist. A client must poll `?status=issued` itself to build a deadline view.
- **No currency conversion or normalization anywhere.** Two offers on one journey may quote different currencies with no exchange rate stored. Any comparison across currencies is the client's problem.
- **Money precision:** amounts are `Decimal(12,2)` — up to 10 integer digits. An amount exceeding that is a 400 from serializer validation, with the field in `details`.
