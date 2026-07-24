# API Documentation — Applicant Journeys

**App:** `applicant_journeys`
**Version:** 1.1.0
**Base prefix:** `/api/v1/journeys/`
**Auth:** Bearer access JWT on every endpoint (`IsAuthenticated`). Journeys are **shared**, not owner-scoped; see `SECURITY.md` §1.
**Throttle:** Project DRF defaults only. No custom scopes.
**Access level:** Admin and Lead Manager, with identical rights including creation. Superadmin is denied everywhere. Nothing is public.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial API documentation — 9 endpoints |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | No endpoint added, changed, or retired. `target_country_ref` (optional catalogue country) is accepted on create and update, returned as a nested object, and filterable exactly — additive, so non-breaking under §22. New error code `JOURNEYS_COUNTRY_NOT_FOUND`. **Recorded the cross-app side effect** setting it now carries: an applicant's checklist appears |

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

**Paginated list `meta`:**
```json
{ "count": 100, "page": 1, "page_size": 20, "next": "https://host/api/v1/journeys/?page=2", "previous": null }
```

**AI debugging notes (app-wide):**
- Every endpoint returns 401 unauthenticated and 403 `JOURNEYS_ACTOR_FORBIDDEN` for a Superadmin. Neither is repeated per endpoint.
- 404 `JOURNEYS_JOURNEY_NOT_FOUND` always means the record does not exist — there is no scoping to hide.
- The three non-active stages (`completed`, `closed`, `deferred`) are **never** settable via §1.4 or §1.5. Each has its own action. Sending one to the stage endpoint fails DRF choice validation with 400 and the field under `error.details`.
- `applicant`, `creation_source`, and `created_by` are immutable and never accepted on update.
- Lifecycle datetimes (`closed_at`, `deferred_at`) carry a `<field>_bs` companion (§39.4). `created_at`/`updated_at` do not.

---

## 1. Journeys

### 1.1 List — `GET /api/v1/journeys/`

**Policy key(s):** `applicant_journeys.journey.list` (risk: low)
**Request query params:** `applicant` (id), `stage`, `target_country` (partial match on the typed string), `target_country_ref` (exact catalogue id), `fiscal_year` (`YYYY/YY`), `page`, `page_size`.
**Response:** paginated array of the journey **list** shape — `DATA_CONTRACT.md` §1, minus `notes` and all lifecycle-state fields. Newest first.
**Business rules:** every Admin and Lead Manager sees every journey. Filtering by `applicant` gives the per-person view; filtering by `stage` gives the operational worklist.
**Query access pattern:** `selectors.get_journeys` applies `select_related("applicant", "created_by")`, so a page costs a constant number of queries despite embedding applicant identity in every row. `applicant` and `stage` filters are served by `journey_applicant_recent_idx` and `journey_stage_recent_idx`.
**Error codes:** none beyond the app-wide 401/403.

### 1.2 Create — `POST /api/v1/journeys/`

**Policy key(s):** `applicant_journeys.journey.create` (risk: medium)
**Request:**
```json
{
  "applicant": "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5",
  "target_country": "Australia",
  "target_country_ref": "3a7c1d90-5b2e-4f81-9a03-6c4d8e2b7f15",
  "target_institution_name": "University of Melbourne",
  "study_level": "masters",
  "field_of_study": "Computer Science",
  "preferred_intake": "Fall 2026",
  "budget_amount": "2500000.00",
  "budget_currency": "NPR",
  "scholarship_interest": true
}
```
**Response:** the created journey in the **detail** shape, HTTP 201.
**Validation rules:** only `applicant` is required — a journey often begins as little more than an intention. `stage` is not accepted; a new journey always starts at `planning`.
**Error codes:**
- `JOURNEYS_APPLICANT_NOT_FOUND` (400) — no applicant with that id.
- `JOURNEYS_COUNTRY_NOT_FOUND` (400) — `target_country_ref` names no catalogue country. Returned identically by create and update, so a client cannot learn one code from `POST` and a different one from `PATCH` for the same bad id.
**Business rules:** recorded as `creation_source: "manual"`. The conversion path (`POST /api/v1/leads/<id>/convert/`) calls the same service with `creation_source: "lead_conversion"`. Unlike applicant creation, this is **not** Admin-only — adding an objective for an existing client is ordinary work. Writes one `journey_created` event.

### 1.3 Retrieve — `GET /api/v1/journeys/<journey_id>/`

**Policy key(s):** `applicant_journeys.journey.read` (risk: low)
**Response:** the journey **detail** shape — the list shape plus `notes`, `outcome`, `closure_reason`, `closed_at`/`_bs`/`_by`, `deferred_at`/`_bs`/`_to_intake`/`_reason`/`_by`, and `stage_before_terminal`.
**Error codes:** app-wide 404 only.

### 1.4 Update — `PATCH /api/v1/journeys/<journey_id>/`

**Policy key(s):** `applicant_journeys.journey.update` (risk: medium)
**Request:** any subset of the create payload except `applicant`.
**Response:** the updated journey, detail shape.
**Error codes:** app-wide 404 only.
**Business rules:** `applicant` is **immutable** — the serializer drops it, so a journey can never be moved to another person. `stage`, `creation_source`, and `created_by` are likewise not writable; sending them is ignored, not rejected. Writes `journey_updated` when something actually moved; a no-op `PATCH` writes no event.

### 1.5 Change stage — `POST /api/v1/journeys/<journey_id>/stage/`

**Policy key(s):** `applicant_journeys.journey.change_stage` (risk: medium)
**Request:** `{ "stage": "applying" }`
**Response:** the updated journey, detail shape.
**Validation rules:** `stage` must be one of the six **active** stages — `planning`, `profile_building`, `shortlisting`, `applying`, `offer_stage`, `visa_stage`.
**Error codes:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — the journey is completed, closed, or deferred; reopen it first.
- `JOURNEYS_STAGE_INVALID_TRANSITION` (400) — a terminal stage reached the service directly.
**Business rules:** moving to the stage already held is a no-op and writes no event. `visa_stage` records that a visa step is underway; Grandway does not manage the visa case itself.

### 1.6 Defer — `POST /api/v1/journeys/<journey_id>/defer/`

**Policy key(s):** `applicant_journeys.journey.defer` (risk: medium)
**Request:** `{ "to_intake": "Spring 2027", "reason": "Test result delayed." }`
**Response:** the updated journey with `stage: "deferred"` and the deferment fields populated.
**Validation rules:** `to_intake` is required.
**Error codes:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — already terminal or deferred.
- `JOURNEYS_DEFER_INTAKE_REQUIRED` (400) — no target intake reached the service.
**Business rules:** deferment is **not an outcome** and closes nothing — the applicant intends to continue, just not on the current timeline. `outcome` stays blank. `stage_before_terminal` remembers where the journey was. Resume with §1.8.

### 1.7 Close — `POST /api/v1/journeys/<journey_id>/close/`

**Policy key(s):** `applicant_journeys.journey.close` (risk: high)
**Request:** `{ "outcome": "rejected", "reason": "No offer received." }`
**Response:** the updated journey with `stage`, `outcome`, `closed_at`/`_bs`/`_by`, and `stage_before_terminal` populated.
**Validation rules:** `outcome` is required.
**Error codes:**
- `JOURNEYS_STAGE_NOT_EDITABLE` (409) — already terminal or deferred.
- `JOURNEYS_OUTCOME_REQUIRED` (400) — no outcome reached the service.
- `JOURNEYS_OUTCOME_DETAIL_REQUIRED` (400) — `outcome` is `other` but `reason` was blank.
**Business rules:** closing with `successful` sets `stage = completed`; **every other outcome** sets `stage = closed`. This keeps "how did it end" one recorded fact rather than something inferred from the stage. A journey that should not have existed is closed as `cancelled` — there is no delete. Writes `journey_closed` with the outcome in the event's `reason` field.

### 1.8 Reopen — `POST /api/v1/journeys/<journey_id>/reopen/`

**Policy key(s):** `applicant_journeys.journey.reopen` (risk: high)
**Request:** `{ "stage": "applying" }` — optional; defaults to `planning`.
**Response:** the updated journey with closure and deferment state cleared.
**Error codes:**
- `JOURNEYS_JOURNEY_NOT_TERMINAL` (409) — the journey is already active.
- `JOURNEYS_STAGE_INVALID_TRANSITION` (400) — the requested target stage is terminal.
**Business rules:** the **only** way back from a terminal or deferred state, and it works identically for all three. Clears `outcome`, `closure_reason`, `closed_at`, `closed_by`, `deferred_at`, `deferred_to_intake`, `deferment_reason`, `deferred_by`, and `stage_before_terminal`. **The audit events recording the closure or deferment are never removed** — a journey that was completed and then reopened still shows both facts in its history.

### 1.9 History — `GET /api/v1/journeys/<journey_id>/history/`

**Policy key(s):** `applicant_journeys.journey.list_history` (risk: low)
**Response:** paginated array of history entries, newest first — same shape as the `leads` and `applicants` history endpoints.
**Error codes:** app-wide 404 only.
**Business rules:** this app owns no history table; the response is the central `audit` log filtered to this journey. The full action vocabulary is in `DATA_CONTRACT.md` §2. Free text (notes, closure and deferment reasons) is deliberately not copied into events.
**Query access pattern:** `selectors.get_history_for_journey` delegates to `audit.selectors.get_events`.

---

## 2. Lifecycle independence (applies across §1)

No endpoint in this module changes anything on the applicant. Closing a journey does not archive the applicant; archiving an applicant does not close their journeys. The two lifecycles are independent by design, and both directions are covered by tests. If a UI wants to prompt "this was their last open journey — mark them dormant?", that is a client-side suggestion, not a server behaviour.
