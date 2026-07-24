# Data Contract — Offers

**Owner app:** `offers`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the formal admission decisions institutions make against applicant journeys — what was offered, for which program and intake, under what conditions and money terms, and how the applicant responded. It does **not** own the study plan (`applicant_journeys`), the person (`applicants`), or the catalogue the offer references (`institutions`). It owns no history table — an offer's history is the central `audit` log filtered to that offer.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial contract — `Offer` and `OfferCondition` |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. An offer letter now has a home in `uploaded_files`; this model still holds no reference to it |

---

## Deliberate Deviations

`concepts/offers.txt` lists five open questions and one out-of-scope item that the project's current state decides for it. Each departure is recorded here rather than left to be inferred.

- **§39.1 bilingual identity is inverted, inherited from `institutions`.** `institution_name_en` is required and `institution_name_np` is optional; there is no `_romanized` field. The snapshot copies foreign proper nouns from the catalogue, which has the same shape and the same reason: a required Devanagari name would force invented transliterations for "University of Melbourne". **Unicode normalization (§39.2) still applies in full** to every user-entered text field. See `institutions/docs/DATA_CONTRACT.md` — "Deliberate Deviations" for the original rationale.
- **No supporting files *on this model*.** The concept lists "Notes and supporting files" among offer information. `notes` ships; a file field does not. **`uploaded_files` now exists** and holds a `PROTECT` foreign key to `Offer`, so an offer letter has a home — `POST /api/v1/files/` with `offer=<id>`. What is still deliberately absent is a reference in the other direction: this model has no file column and this app does not call that one, so an offer payload says nothing about the letter attached to it. Adding a count or a primary-file pointer later is additive.
- **Conditions are a dedicated sub-record, not a reusable checklist.** The concept asks which; the project answers it. `checklists` is a named future domain with no code behind it, and building a generic checklist inside `offers` would pre-empt it. `OfferCondition` is owned by this app and belongs to exactly one offer. When `checklists` ships, the question of whether offer conditions should migrate onto it is worth reopening — it is recorded in the concept file as still open.
- **No history table**, for the same reason as `leads`, `applicants`, `applicant_journeys`, and `institutions`: `audit` already provides an immutable append-only log and §4 forbids duplicating another app's storage.
- **No `superseded_by` link.** The concept says an offer "may be superseded by a later offer for the same journey". A stored link would add a column and a write path for a fact a client can already read: a journey's offers are returned newest-first, and the one accepted offer is queryable directly. Recorded in `docs/INTEGRATION.md` §9 `Gaps`.
- **Seven statuses, not the concept's eight.** `awaiting_response` is collapsed into `issued` — once an institution has issued an offer, the consultancy is by definition awaiting a response, and two statuses for one state drift apart as staff forget to advance the second. Settled with the user, 2026-07-24.
- **No separate expiry date or expiry action.** The concept asks whether one is needed; `response_deadline` alone is enough for V1. `expired` is a status a person sets, never the system: nothing in this deployment runs on a schedule (the `notifications` domain does not exist), so an automatic expiry would be a promise the deployment cannot keep. `is_response_overdue` is computed on read so a lapsed offer is still visible without one.
- **A decision is final; there is no reopen action.** `applicant_journeys` has `reopen_journey`, and this app deliberately does not mirror it. A journey is an ongoing plan that can resume; an offer is a record of what an institution decided at a point in time. An institution that changes its position has issued a *new* offer, and recording it as one is what keeps the journey's decision trail readable rather than a single mutable row.
- **Recording an offer never changes the journey's stage.** The concept notes that "journey stage can indicate that offers are being awaited or reviewed, but the offer module is the source of truth for the actual decision records". This app therefore reads `applicant_journeys` and never writes to it — no signal, no cross-app mutation. `concepts/project_overview.txt` — "Explicit lifecycle states": one status must not be used as a shortcut for another.

---

## 1. Offer

**Purpose:** One institution's admission decision, recorded against one applicant journey. A journey may hold several — a second offer never replaces a first, because comparing competing institutional responses is the reason the records are separate.
**Table:** `offers_offer`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| journey | FK → `applicant_journeys.ApplicantJourney` | Yes | No | No | The study plan this decision belongs to; `PROTECT` |
| institution | FK → `institutions.Institution` | No | Yes | No | The live catalogue reference point; `PROTECT` |
| campus | FK → `institutions.Campus` | No | Yes | No | Optional; `PROTECT` |
| program | FK → `institutions.Program` | No | Yes | No | The live catalogue reference point; `PROTECT` |
| reference_source | CharField(20) | Yes | No | Yes | How the reference was entered; derived at creation |
| institution_name_en | CharField(255) | Yes | No | No | **Snapshot.** The provider as named when the decision was made |
| institution_name_np | CharField(255) | No | No | No | **Snapshot.** Optional Devanagari name |
| campus_name | CharField(255) | No | No | No | **Snapshot** |
| program_title | CharField(255) | Yes | No | No | **Snapshot.** The program as named when the decision was made |
| country_name | CharField(150) | No | No | No | **Snapshot** |
| qualification_level | CharField(30) | No | No | No | **Snapshot.** `core.constants.StudyLevel` |
| intake_label | CharField(100) | No | No | No | **Snapshot.** Free text until intakes are catalogued, e.g. `Feb 2027` |
| offer_type | CharField(20) | No | No | No | Defaults to `conditional` |
| offer_reference | CharField(100) | No | No | No | The institution's own offer or letter number |
| issue_date | Date | No | Yes | No | When the institution issued the offer |
| response_deadline | Date | No | Yes | No | When the applicant must respond by; indexed |
| tuition_amount | Decimal(12,2) | No | Yes | No | As quoted in **this offer**, not the catalogue's figure |
| tuition_currency | CharField(3) | No | No | No | ISO 4217 |
| tuition_fee_period | CharField(20) | No | No | No | `core.constants.FeePeriod` |
| scholarship_amount | Decimal(12,2) | No | Yes | No | |
| scholarship_currency | CharField(3) | No | No | No | ISO 4217 |
| scholarship_notes | Text | No | No | No | |
| deposit_amount | Decimal(12,2) | No | Yes | No | Recorded, never collected |
| deposit_currency | CharField(3) | No | No | No | ISO 4217 |
| deposit_due_date | Date | No | Yes | No | |
| deposit_notes | Text | No | No | No | |
| status | CharField(20) | No | No | No | Defaults to `draft`; indexed |
| notes | Text | No | No | No | |
| created_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| decided_at | DateTime | No | Yes | Yes | Set by the decision action |
| decision_reason | Text | No | No | No | Set by the decision action |
| decided_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL` |
| deferred_to_intake | CharField(100) | No | No | Yes | Set only when the decision was `deferred` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`status`** — `draft` | `issued` | `accepted` | `rejected` | `withdrawn` | `deferred` | `expired`. Defined in `offers/constants.py` `OfferStatus`.
- **`offer_type`** — `conditional` | `unconditional`. `OfferType`.
- **`reference_source`** — `catalogue` | `manual`. `OfferSource`.
- **`qualification_level`** — `core.constants.StudyLevel`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other`, or `""`.
- **`tuition_fee_period`** — `core.constants.FeePeriod`: `per_year` | `per_semester` | `total_program`, or `""`.

**Validation Rules:**

- An offer must name **both** an institution and a program, either by catalogue reference or as snapshot text. Neither → `OFFERS_PROGRAM_REFERENCE_REQUIRED`.
- A supplied `campus` or `program` must belong to the supplied `institution` → `OFFERS_CATALOGUE_REFERENCE_INVALID`.
- A `program` implies its own institution and campus; supplying the program alone is sufficient.
- Every money amount requires its currency: tuition, scholarship, and deposit each → `OFFERS_AMOUNT_INCOMPLETE`. A bare number is not a fee.
- Currency codes match `^[A-Z]{3}$` (`core.validators.validate_currency_code`) and are upper-cased on write.
- **The reference block and `status` are immutable after creation.** A `PATCH` carrying `journey`, any catalogue FK, any snapshot field, or `status` is rejected with `OFFERS_REFERENCE_IMMUTABLE` — rejected loudly rather than dropped silently, so a client cannot believe it corrected a record it did not. This is the inverse of the `institutions` convention, and deliberately so: there, ignoring an immutable field lets a round-trip edit form work; here, the whole point of the record is that history cannot be rewritten, and a silent no-op would defeat it.
- Only a `draft` may be issued → `OFFERS_OFFER_NOT_ISSUABLE` (409).
- Only a `draft` or `issued` offer may be decided → `OFFERS_OFFER_NOT_DECIDABLE` (409).
- `rejected` and `withdrawn` require a reason → `OFFERS_DECISION_REASON_REQUIRED`.
- `deferred` requires the target intake → `OFFERS_DEFER_INTAKE_REQUIRED`.
- **At most one `accepted` offer per journey** → `OFFERS_ACCEPTED_OFFER_EXISTS` (409). The single multiplicity rule: a journey may collect any number of competing offers, but only one of them can be the one taken. Enforced in the service rather than by a database constraint, because the rule is "at most one at a time" across a mutable status rather than a uniqueness of stored values.
- All user-entered text is Unicode-normalized on write (§39.2).

**Derived, read-only:**

- `is_terminal` — the status is one of `accepted`, `rejected`, `withdrawn`, `deferred`, `expired`.
- `is_decided` — `decided_at` is set.
- `is_response_overdue` — the status is `issued` and `response_deadline` is before today **in Nepal time** (`core.nepal.calendar.nepal_today`, §39.5). A deadline is a calendar day where the staff work, not in UTC.
- `has_open_conditions` — any condition is not `satisfied`, `waived`, or `not_applicable`. Callers listing many offers must prefetch `conditions`; `selectors.get_offers` does.

**Indexes:**

- `(journey, -created_at)` — `offer_journey_recent_idx`. Supports the Journey Detail offers panel: one journey's offers, newest first.
- `(status, -created_at)` — `offer_status_recent_idx`. Supports the Offer List worklist filtered by status.
- `response_deadline` (`db_index=True`) — supports deadline reporting and the `deadline_before` filter.

**Soft Delete:** `N/A — no deletion at all.` No offer is ever deleted and there is no delete endpoint or delete service. `concepts/offers.txt` — "No deletion of offer history. Replaced or outdated offers should remain visible as part of the journey record." An offer that no longer applies is given a terminal status. `journey`, `institution`, `campus`, `program`, and `created_by` are all `PROTECT`, so nothing an offer references can be removed out from under it either.

**Cross-App Dependencies:**

- `applicant_journeys.ApplicantJourney` — FK, `PROTECT`. Every offer belongs to exactly one journey. Read only: this app never writes to a journey, and recording an offer does not move its stage.
- `institutions.Institution` / `Campus` / `Program` — nullable FKs, `PROTECT`. The live catalogue reference point. The snapshot fields, not these, are what the offer *means* once the catalogue changes.
- `authenticate.User` — FKs for `created_by` (`PROTECT`) and `decided_by` (`SET_NULL`).
- `audit` — service call. Every mutation appends one event. No storage here.

**Example:**

```json
{
  "id": "9a1f4c2e-7b3d-4e58-9a01-2c3d4e5f6071",
  "journey": "5e6f7081-9a2b-4c3d-8e4f-5061728394a5",
  "applicant_id": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819",
  "applicant_name": "राम बहादुर",
  "journey_stage": "offer_stage",
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
  "deposit_notes": "Non-refundable after the response deadline.",
  "status": "issued",
  "is_terminal": false,
  "has_open_conditions": true,
  "notes": "",
  "decided_at": null,
  "decision_reason": "",
  "decided_by_username": null,
  "deferred_to_intake": "",
  "created_by_username": "leadmgr",
  "conditions": [],
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T09:18:47Z"
}
```

---

## 2. OfferCondition

**Purpose:** One requirement that must be satisfied for an offer to become fully usable or unconditional. Staff read the set of them to answer "what is still outstanding on this offer".
**Table:** `offers_offercondition`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| offer | FK → `Offer` | Yes | No | No | `CASCADE` — see Soft Delete |
| condition_type | CharField(30) | Yes | No | No | The kind of requirement |
| description | Text | Yes | No | No | The requirement in the institution's own words |
| due_date | Date | No | Yes | No | |
| display_order | PositiveInteger | No | No | No | Ordering within the offer; defaults to 0 |
| status | CharField(20) | No | No | No | Defaults to `pending`; indexed |
| resolution_note | Text | No | No | No | Required when waiving or retiring |
| resolved_at | DateTime | No | Yes | Yes | Stamped by the status action |
| resolved_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL`; stamped by the status action |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`condition_type`** — `academic_result` | `english_test` | `document_submission` | `deposit_payment` | `interview` | `identity_confirmation` | `other`. `ConditionType`.
- **`status`** — `pending` | `satisfied` | `waived` | `not_applicable`. `ConditionStatus`.

**Validation Rules:**

- `description` is required regardless of type, so nothing is lost by falling back to `other`.
- `waived` and `not_applicable` require a non-empty note → `OFFERS_CONDITION_NOTE_REQUIRED`. Both are judgement calls someone will have to defend later; `satisfied` is a fact and needs none.
- Moving back to `pending` is permitted — a document rejected on review is a real event. It clears `resolved_at` and `resolved_by` while both transitions stay in the audit log.
- `status` is not editable through the update endpoint; it moves only through the status action, which stamps the resolver.
- A condition may be added **after** the offer has been decided. Institutions routinely do this, and refusing it would push the record back into the spreadsheet this app replaces.
- All user-entered text is Unicode-normalized on write (§39.2).

**Derived, read-only:** `is_resolved` — the status is `satisfied`, `waived`, or `not_applicable`.

**Indexes:** `(offer, status)` — `condition_offer_status_idx`. Supports the Offer Detail conditions panel and "what is still pending".

**Soft Delete:** `N/A — no deletion at all.` There is no delete endpoint. A condition that turns out not to apply is set to `not_applicable` with a note, so the offer's history still shows that the institution asked for it (`concepts/offers.txt` — "If a condition is added or changed later, the previous state should remain traceable in history"). The FK is `CASCADE` rather than `PROTECT` only because the parent offer is itself never deleted, so the cascade can never fire; `PROTECT` here would express a constraint in the wrong direction — a condition does not exist independently of its offer.

**Cross-App Dependencies:**

- `authenticate.User` — FK for `resolved_by` (`SET_NULL`).
- `audit` — service call. **Condition events are recorded against the parent offer's `entity_id`**, not the condition's, so `GET /offers/<id>/history/` returns one continuous trail. A condition has no history screen of its own, and splitting the log would leave the offer history silently missing most of what happens to a conditional offer.

**Example:**

```json
{
  "id": "7c8d9e0f-1a2b-4c3d-9e4f-506172839405",
  "condition_type": "english_test",
  "description": "IELTS overall 6.5 with no band below 6.0.",
  "status": "satisfied",
  "is_resolved": true,
  "due_date": "2026-08-15",
  "due_date_bs": {
    "year": 2083, "month": 4, "day": 30,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 30", "display_np": "२०८३ श्रावण ३०"
  },
  "display_order": 0,
  "resolution_note": "",
  "resolved_at": "2026-08-02T04:11:23Z",
  "resolved_by_username": "leadmgr",
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-08-02T04:11:23Z"
}
```
