# FLOWS — Offers

**Owner app:** `offers`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/offers.txt` to the callable endpoints in `backend/offers/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **Four things govern every flow below.**
>
> 1. **No authority-based control hiding.** Every Admin and Lead Manager may do everything here,
>    read and write alike. This is **not** the `institutions` split — do not carry a "hide write
>    controls from Lead Managers" rule across from the catalogue screens. Only a Superadmin is
>    refused, and a Superadmin has no reason to be on these screens at all.
> 2. **There is no delete, anywhere.** No screen gets a delete button — not for an offer, not for a
>    condition. An offer that no longer applies gets a decision; a condition that does not apply is
>    marked `not_applicable`.
> 3. **A decision is final.** There is no reopen action, unlike an applicant journey. Once an offer
>    is decided, the Decision Dialog must be closed to the user, not merely disabled. An institution
>    that changes its mind means recording a *second* offer.
> 4. **Nothing here moves the journey.** Recording, issuing, or deciding an offer leaves the
>    journey's stage exactly where it was. If the UI should advance the journey on acceptance, it
>    must make that call itself — see the "Accept an offer" flow, step 4.

---

## Flow: Record an offer against a journey

- **Actor:** Admin or Lead Manager
- **Goal:** Turn an institution's letter into a record on the applicant's journey.
- **Entry point:** Journey Detail → Offers panel → "Add offer"

**Steps:**

1. **Journey Detail → Offers panel** — load what already exists →
   `GET /api/v1/offers/?journey=<journey_id>` (`offers.offer.list`)
   - **Requires state:** the journey being viewed.
   - **Side effects:** none.
   - Rows are newest first. Show institution, program, intake, status, and response deadline — the columns the concept's "Journey Detail → Offers panel" asks for.
   - **`is_response_overdue` is on every row**; use it for the deadline warning rather than comparing dates client-side. It is computed in Nepal time and only ever true for an `issued` offer.

2. **New Offer Form** — find the program in the catalogue →
   `GET /api/v1/catalogue/programs/?q=...` (`institutions.program.list`) *(cross-app: institutions)*
   - **Requires state:** nothing. The catalogue is independently browsable.
   - **Side effects:** none.
   - **Sending just the program id is enough** — it implies its own institution and campus. The form does not need three pickers.
   - **Skip this step entirely** for a historical offer with no catalogue record; go to step 3 with the manual branch.

3. **New Offer Form** — record the decision →
   `POST /api/v1/offers/` (`offers.offer.create`)
   - **Requires state:** an existing journey. **The journey's stage is not checked** — an offer may be recorded against a journey at any stage, including a closed one.
   - **Side effects:** appends `offer_created` to the audit log. Conditions sent in the same request are created atomically with the offer. **Nothing outside this module changes.**
   - **The form has two branches and must make clear which one the user is in** (`concepts/offers.txt` — "It must be clear whether the offer was created from the catalogue or entered as a manual historical record"). Send `program` for the catalogue branch, or `institution_name_en` + `program_title` for the manual branch. The response's `reference_source` confirms which was recorded.
   - *Failure — `OFFERS_PROGRAM_REFERENCE_REQUIRED`:* neither branch was completed. Show it against the program field, not as a form-level error.
   - *Failure — `OFFERS_CATALOGUE_REFERENCE_INVALID`:* the campus or program picker was not filtered to the chosen institution — a UI bug, not user error. Reset and refilter.
   - *Failure — `OFFERS_AMOUNT_INCOMPLETE`:* highlight the amount and its currency together. Treat each of tuition, scholarship, and deposit as one composite control that is filled or empty as a unit.
   - *Failure — `OFFERS_JOURNEY_NOT_FOUND`:* the journey was deleted or the id is stale — refetch the journey.
   - **Enter the real intake in `intake_label`.** Sending it alongside a `program` overrides the catalogue's generic `intake_pattern` ("Feb / Jul") with the actual one ("Feb 2027"). This is the only way a real intake gets recorded while intakes remain uncatalogued.

4. **Offer Detail** — mark it issued →
   `POST /api/v1/offers/<offer_id>/issue/` (`offers.offer.issue`)
   - **Requires state:** the offer's status is `draft`.
   - **Side effects:** appends `offer_issued`. From here `is_response_overdue` becomes meaningful.
   - *Failure — `OFFERS_OFFER_NOT_ISSUABLE` (409):* already issued or already decided. Refetch — someone else acted on it.
   - **Skip this step** when recording a historical offer that was resolved long ago; a decision may be recorded directly on a draft.

---

## Flow: Manage an offer's conditions

- **Actor:** Admin or Lead Manager
- **Goal:** See at a glance what still stands between the applicant and an unconditional place.
- **Entry point:** Offer Detail → Conditions panel

**Steps:**

1. **Offer Detail** — the conditions are already there →
   `GET /api/v1/offers/<offer_id>/` (`offers.offer.read`)
   - **Requires state:** the offer.
   - **Side effects:** none.
   - **Do not call the conditions list endpoint to render this panel.** The detail response already nests the full `conditions` array in `display_order`. `offers.condition.list` exists for a standalone conditions view and for refreshing the panel alone.

2. **Conditions panel** — add a requirement →
   `POST /api/v1/offers/<offer_id>/conditions/` (`offers.condition.create`)
   - **Requires state:** the offer. **Its status is not checked** — a condition may be added after the offer has been accepted, which institutions routinely do. Do not disable this control on a decided offer.
   - **Side effects:** appends `offer_condition_created` **to the offer's history**, and may flip the offer's `has_open_conditions` to `true`.
   - `description` is required whatever the type is, so `other` loses nothing.

3. **Conditions panel** — resolve one →
   `POST /api/v1/offers/conditions/<condition_id>/status/` (`offers.condition.change_status`)
   - **Requires state:** the condition.
   - **Side effects:** appends `offer_condition_status_changed` to the **offer's** history; stamps `resolved_at` and `resolved_by_username`; may flip `has_open_conditions`.
   - *Failure — `OFFERS_CONDITION_NOTE_REQUIRED`:* `waived` and `not_applicable` require a note; `satisfied` does not. Make the note input appear on selecting either of those two, not on all four.
   - **`has_open_conditions` is not in this response** — the response is the condition alone. Refetch the offer, or recompute locally, before re-rendering the offer's header.
   - **Moving back to `pending` is allowed** and clears the resolution stamp. Offer it: a document rejected on review is a real event, and both transitions stay in the history.

4. **Conditions panel** — correct the wording →
   `PATCH /api/v1/offers/conditions/<condition_id>/` (`offers.condition.update`)
   - **Requires state:** the condition.
   - **Side effects:** appends `offer_condition_updated` to the offer's history. A no-op edit writes no event.
   - **Status is not editable here.** An edit form covering both wording and status must call two endpoints.

---

## Flow: Record the applicant's decision

- **Actor:** Admin or Lead Manager
- **Goal:** Close out one institutional response with what the applicant actually decided.
- **Entry point:** Offer Detail → "Record decision" → Decision Dialog

**Steps:**

1. **Offer Detail** — check the conditions, deposit, and deadline →
   `GET /api/v1/offers/<offer_id>/` (`offers.offer.read`)
   - **Requires state:** the offer.
   - **Side effects:** none.
   - **Hide the "Record decision" action entirely when `is_terminal` is true.** There is no reopen, so a disabled-but-visible control implies a capability that does not exist.

2. **Decision Dialog** — record the outcome →
   `POST /api/v1/offers/<offer_id>/decision/` (`offers.offer.record_decision`)
   - **Requires state:** the offer's status is `draft` or `issued`. For `accepted`, the journey must have no other accepted offer.
   - **Side effects:** appends `offer_decision_recorded`; stamps `decided_at`, `decided_by_username`, and the reason. **The journey's stage and the applicant's status are both untouched.**
   - **The dialog is one form with a conditional required field** (`concepts/offers.txt` — "It should require the reason or follow-up detail whenever the selected outcome needs explanation"): `reason` becomes required for `rejected` and `withdrawn`; `to_intake` becomes required for `deferred`; `accepted` and `expired` require neither.
   - *Failure — `OFFERS_DECISION_REASON_REQUIRED` / `OFFERS_DEFER_INTAKE_REQUIRED`:* the conditional field was not enforced client-side. Show inline on that field.
   - *Failure — `OFFERS_OFFER_NOT_DECIDABLE` (409):* already decided. Refetch and close the dialog.
   - *Failure — `OFFERS_ACCEPTED_OFFER_EXISTS` (409):* this journey already has an accepted offer. **Name it** — fetch it with `GET /api/v1/offers/?journey=<journey_id>&status=accepted` and tell the user which one, rather than showing a bare error.
   - **Deferring an offer is not deferring the journey.** This moves one institutional decision to a later intake. If the whole plan is being deferred, that is `applicant_journeys.journey.defer` — a different action with a different meaning.

3. **Offer Detail** — read the trail →
   `GET /api/v1/offers/<offer_id>/history/` (`offers.offer.list_history`)
   - **Requires state:** the offer.
   - **Side effects:** none.
   - **Condition events appear here too**, carrying `metadata.condition_id`. This is the offer's complete history; there is no separate condition history.

4. **Journey Detail** — *(optional, and the client's decision)* advance the journey →
   `POST /api/v1/journeys/<journey_id>/stage/` (`applicant_journeys.journey.change_stage`) *(cross-app: applicant_journeys)*
   - **Requires state:** the journey is not completed, closed, or deferred.
   - **Side effects:** appends `journey_stage_changed` to the *journey's* history.
   - **This step is not automatic and never will be.** Journey stage and offer status are separate lifecycles by project rule. If accepting an offer should move a journey to `visa_stage`, the client makes that call; the backend will not.
   - *Failure — `JOURNEYS_STAGE_NOT_EDITABLE`:* the journey is terminal. The offer decision still stands — do not roll it back or present the two as one transaction.

---

## Flow: Compare competing offers on one journey

- **Actor:** Admin or Lead Manager
- **Goal:** Decide between several institutional responses without losing any of them.
- **Entry point:** Journey Detail → Offers panel

**Steps:**

1. **Offers panel** — list them all →
   `GET /api/v1/offers/?journey=<journey_id>` (`offers.offer.list`)
   - **Requires state:** the journey.
   - **Side effects:** none.
   - **Render `tuition_currency` beside every `tuition_amount`.** Amounts are stored exactly as quoted and are never converted — two rows may be in different currencies and are not directly comparable. A comparison table that shows bare numbers will mislead.
   - The full money picture — scholarship and deposit — is on the detail shape, not the list. A side-by-side comparison needs one `offers.offer.read` per offer.

2. **Decision Dialog** — accept one →
   `POST /api/v1/offers/<chosen_id>/decision/` with `accepted` (`offers.offer.record_decision`)
   - **Requires state:** no other accepted offer on this journey.
   - **Side effects:** as above.

3. **Decision Dialog** — resolve the rest →
   `POST /api/v1/offers/<other_id>/decision/` with `rejected` and a reason (`offers.offer.record_decision`)
   - **Requires state:** each offer is still `draft` or `issued`.
   - **Side effects:** as above.
   - **Do not delete or hide the rejected offers.** They stay on the panel as part of the journey's decision trail — that is the reason this flow exists rather than one mutable "current offer" field.

**There is no "supersede" action, and no superseded badge from the API.** The concept mentions supersession; nothing records it. If the UI wants to mark older offers, it must define the rule itself from the newest-first ordering and which offer is `accepted`.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `offers.offer.list` | `GET /api/v1/offers/` | Record an offer (step 1); Compare competing offers | Backs both the standalone **Offer List** and the **Journey Detail offers panel** (`?journey=`) |
| `offers.offer.create` | `POST /api/v1/offers/` | Record an offer | Two branches: catalogue or manual |
| `offers.offer.read` | `GET /api/v1/offers/<offer_id>/` | Manage conditions; Record the decision; Compare competing offers | The **Offer Detail** screen. Nests `conditions` |
| `offers.offer.update` | `PATCH /api/v1/offers/<offer_id>/` | Edit Offer form | Rejects the snapshot, journey, catalogue refs, and `status` with `OFFERS_REFERENCE_IMMUTABLE` — send only changed fields |
| `offers.offer.issue` | `POST /api/v1/offers/<offer_id>/issue/` | Record an offer (step 4) | Skipped for historical offers |
| `offers.offer.record_decision` | `POST /api/v1/offers/<offer_id>/decision/` | Record the decision; Compare competing offers | The **Decision Dialog**. Final — no reopen |
| `offers.offer.list_history` | `GET /api/v1/offers/<offer_id>/history/` | Record the decision (step 3) | Includes condition events |
| `offers.condition.list` | `GET /api/v1/offers/<offer_id>/conditions/` | — | `unused by the flows above — the offer detail response already nests the conditions. Exists for a standalone conditions view and for refreshing the panel without refetching the offer` |
| `offers.condition.create` | `POST /api/v1/offers/<offer_id>/conditions/` | Manage conditions (step 2) | Allowed on a decided offer |
| `offers.condition.update` | `PATCH /api/v1/offers/conditions/<condition_id>/` | Manage conditions (step 4) | Wording only; not status |
| `offers.condition.change_status` | `POST /api/v1/offers/conditions/<condition_id>/status/` | Manage conditions (step 3) | The tick / waive control |

**Every screen in `concepts/offers.txt` is backed**, with two qualifications:

- The **Offer List**'s filters are backed except for text search — there is no `q` parameter, so "find offers from Melbourne" can only be done by catalogue `institution` id, which misses every manually recorded offer. Filter client-side, or narrow by journey first.
- The **Offer Detail** screen's "supporting files" section has no endpoint at all. Nothing can be attached to an offer today; this waits on `uploaded_files`.

## Cross-app dependencies

- **This app references (outbound):**
  - `institutions.program.list` and `institutions.program.read` — the catalogue lookup in the New Offer form. A *client-side* call; the backend resolves the ids it is sent.
  - `applicant_journeys.journey.change_stage` — the optional journey advance after a decision. Also client-side, and deliberately never automatic.
  - `applicant_journeys.journey.list` / `.read` — how a client reaches the journey id an offer needs.
- **Backend runtime coupling** (distinct from the client-side calls above): `offers` holds FKs into `applicant_journeys` and `institutions` and calls their selectors. See `backend/offers/docs/INTEGRATION.md` §2.
- **Referenced by other apps (inbound):** none yet. No other app's flow file references an `offers.*` permission key.

**These flows all live here, not in `concepts/project_flows.md`,** because each advances an offer — this app's primary resource. The end-to-end "enquiry → offer → outcome" journey that spans several apps delegates to the flows above rather than restating them.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.
