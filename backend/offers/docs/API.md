# API — Offers

**Owner app:** `offers`
**Version:** 1.2.1
**Status:** Active
**Created:** 2026-07-24
**Base prefix:** `/api/v1/offers/`
**Auth:** Bearer access JWT (`authenticate.SessionBoundJWTAuthentication`) on every endpoint
**Throttle:** project defaults only — `UserRateThrottle` at 1000/hour. No endpoint here is public, and none is expensive: every list is index-backed and paginated at 100 rows max, and the detail read prefetches its conditions in one query.
**Access level:** protected. Admin **and** Lead Manager on every endpoint, read and write alike. Superadmin denied on every route including reads.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial API documentation — 11 endpoints across two resources |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | §1.7 history entries gained `actor_id` and are now serialized by audit's shared `AuditEventHistorySerializer` (`offers.offer.list_history` → 1.1.0). Additive; no other endpoint changed |
| 1.2.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (`institution_name`). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |
| 1.2.1 | 2026-08-17 | AI (Claude Fable 5) | `fiscal_year` filter (§1.1) now round-trips the BS conversion at validation, so a format-valid but unconvertible label (`9999/99`) is a `400` instead of an unhandled `500` (security audit S6) |

---

## Access model (§9 interim inline pattern)

This app uses the interim inline access check in `offers/access.py`. There is no `permissions.py`.

| Check | Applies to | Allows | Denies |
|-------|-----------|--------|--------|
| `require_offer_actor` | every endpoint, `GET` and write alike | `admin`, `lead_manager` | `superadmin` → 403 `OFFERS_ACTOR_FORBIDDEN` |

One rule, no read/write split — the reasoning is in `docs/SECURITY.md` §1. **No endpoint in this app is public.**

**No `DELETE` method is exposed on any resource.** An offer that no longer applies is given a terminal status through the decision endpoint; a condition that does not apply becomes `not_applicable`. See `DATA_CONTRACT.md` "Soft Delete".

---

## Error codes

All codes live in `offers/constants.py` `ErrorCode`.

| Code | HTTP | Meaning |
|------|------|---------|
| `OFFERS_ACTOR_FORBIDDEN` | 403 | The caller's authority may not act in this module (in practice, Superadmin) |
| `OFFERS_OFFER_NOT_FOUND` | 404 | No offer with the id in the URL path |
| `OFFERS_CONDITION_NOT_FOUND` | 404 | No condition with the id in the URL path |
| `OFFERS_JOURNEY_NOT_FOUND` | 400 | The `journey` in the create body does not resolve |
| `OFFERS_PROGRAM_REFERENCE_REQUIRED` | 400 | Neither a catalogue program nor the institution and program names were supplied |
| `OFFERS_CATALOGUE_REFERENCE_INVALID` | 400 | A catalogue id does not exist, or the campus/program does not belong to the institution |
| `OFFERS_REFERENCE_IMMUTABLE` | 400 | A `PATCH` carried the journey, a catalogue reference, a snapshot field, `status`, or `conditions` |
| `OFFERS_AMOUNT_INCOMPLETE` | 400 | A tuition, scholarship, or deposit amount was sent without its currency |
| `OFFERS_OFFER_NOT_ISSUABLE` | 409 | Issue was called on an offer that is not a draft |
| `OFFERS_OFFER_NOT_DECIDABLE` | 409 | A decision was recorded against an already-terminal offer |
| `OFFERS_DECISION_REASON_REQUIRED` | 400 | `rejected` or `withdrawn` with no reason |
| `OFFERS_DEFER_INTAKE_REQUIRED` | 400 | `deferred` with no target intake |
| `OFFERS_ACCEPTED_OFFER_EXISTS` | 409 | The journey already has an accepted offer |
| `OFFERS_CONDITION_NOTE_REQUIRED` | 400 | `waived` or `not_applicable` with no note |

Serializer-level failures return the project-wide `VALIDATION_ERROR` (400) with the offending fields in `error.details`.

---

## Module-wide rules

These hold on every endpoint below and are not repeated per endpoint.

1. **Every mutation appends exactly one `audit.AuditEvent`**, carrying the actor, authority type, changed fields' previous and new values, and client IP. Condition events are recorded against the **parent offer's** `entity_id`, so `GET /offers/<id>/history/` is one continuous trail.
2. **A `PATCH` that changes nothing writes no audit event** and still returns 200.
3. **The reference block and `status` are immutable and are rejected, not ignored, on `PATCH`.** This is the inverse of the `institutions` convention. See `DATA_CONTRACT.md` §1 "Validation Rules".
4. **No write in this app touches another app.** Journey stage, applicant status, and catalogue records are all read-only from here.
5. **Query strings are validated** by `OfferSearchSerializer`; an unparseable filter is a 400 rather than an ignored parameter.
6. **User-facing dates carry a `_bs` sibling on read** (§39.4); system timestamps do not. Writes accept Gregorian `YYYY-MM-DD` only.
7. **All user-entered text is Unicode-normalized on write** (§39.2), via `_NormalizedTextMixin` in `serializers.py`.

---

## 1. Offer

### 1.1 List offers

- **URI:** `GET /api/v1/offers/`
- **Permission key:** `offers.offer.list` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Throttle:** project default.

**Query parameters:** `journey`, `applicant`, `institution`, `program` (UUID, exact); `status`, `offer_type` (enum, exact); `intake` (substring of `intake_label`); `deadline_before` (`YYYY-MM-DD`, inclusive, excludes offers with no deadline); `fiscal_year` (`YYYY/YY`, filtered on `created_at` — validated by round-tripping the actual BS conversion, so a format-valid but unconvertible label like `9999/99` is a `400`, not a `500`); `page`, `page_size`.

**Response:** paginated list of the Offer list shape — see `INTEGRATION.md` §4.

**Query access pattern.** `selectors.get_offers` applies `select_related("journey", "journey__applicant", "institution", "campus", "program", "created_by")` and `prefetch_related("conditions")`. The applicant join is required because the first column of the list is the person's name, two relations away; the conditions prefetch is required because every row reports `has_open_conditions`. Without either, the list is N+1. The `journey` and `status` filters are served by `offer_journey_recent_idx` and `offer_status_recent_idx`; `deadline_before` by the `response_deadline` index.

**Business rules:** none beyond access. Offers are shared — no owner scoping.

**Error codes:** `OFFERS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR` (bad filter).

**AI debugging notes:** if a manually recorded offer is "missing" from a result set, check whether the caller filtered on `institution` or `program` — those match the catalogue FK, which is `null` on every manual offer. This is correct behaviour, not a bug.

### 1.2 Record an offer

- **URI:** `POST /api/v1/offers/`
- **Permission key:** `offers.offer.create` (risk: medium)
- **Auth:** required. Admin or Lead Manager.

**Request:** `journey` (required UUID); the reference, either `program` or `institution_name` + `program_title`; optional `institution`, `campus`, the remaining snapshot fields, `offer_type`, `offer_reference`, `issue_date`, `response_deadline`, the nine money fields, `notes`, and a `conditions` array.

```json
{
  "journey": "5e6f7081-9a2b-4c3d-8e4f-5061728394a5",
  "program": "4f506172-8c9d-4e0f-b112-3c4d5e6f7081",
  "intake_label": "Feb 2027",
  "offer_type": "conditional",
  "offer_reference": "UOM-2026-118842",
  "issue_date": "2026-07-18",
  "response_deadline": "2026-09-30",
  "tuition_amount": "49824.00",
  "tuition_currency": "AUD",
  "tuition_fee_period": "total_program",
  "deposit_amount": "5000.00",
  "deposit_currency": "AUD",
  "conditions": [
    { "condition_type": "english_test", "description": "IELTS overall 6.5 with no band below 6.0." }
  ]
}
```

**Response:** 201 with the Offer detail shape — see `DATA_CONTRACT.md` §1 "Example".

**Validation rules:** `DATA_CONTRACT.md` §1 "Validation Rules". The reference resolution itself lives in `services.build_reference_block`: a `program` implies its own institution and campus, caller-supplied snapshot text overrides the catalogue's, and `reference_source` is derived from whether any catalogue record resolved.

**Business rules:** the offer and its conditions are created in one transaction, so a conditional offer never exists — even momentarily — without the conditions that make it conditional. The journey's stage is deliberately untouched.

**Error codes:** `OFFERS_JOURNEY_NOT_FOUND`, `OFFERS_PROGRAM_REFERENCE_REQUIRED`, `OFFERS_CATALOGUE_REFERENCE_INVALID`, `OFFERS_AMOUNT_INCOMPLETE`, `OFFERS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

**AI debugging notes:** `OFFERS_PROGRAM_REFERENCE_REQUIRED` after sending a valid `program` id means the program resolved but its institution chain did not populate `institution_name` — check the catalogue record, not the request.

### 1.3 Retrieve an offer

- **URI:** `GET /api/v1/offers/<offer_id>/`
- **Permission key:** `offers.offer.read` (risk: low)

**Response:** the Offer detail shape, with `conditions` nested.

**Query access pattern.** `selectors.get_offer_by_id` adds `decided_by` to the list relations and prefetches `conditions__resolved_by`, so rendering the full detail screen — including who resolved each condition — is a fixed small number of queries regardless of condition count.

**Error codes:** `OFFERS_OFFER_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`.

### 1.4 Correct an offer

- **URI:** `PATCH /api/v1/offers/<offer_id>/`
- **Permission key:** `offers.offer.update` (risk: medium)

**Request:** any subset of `offer_type`, `offer_reference`, `issue_date`, `response_deadline`, the nine money fields, `notes`.

**Response:** 200 with the Offer detail shape.

**Business rules:** the immutable-field guard runs in the view *before* serializer validation, so a request carrying both a legal and an illegal field is rejected whole — a partial apply would be worse than a refusal. Money completeness is re-checked against the **merged** state, so patching an amount onto an offer with no stored currency fails just as a create would.

**Error codes:** `OFFERS_REFERENCE_IMMUTABLE`, `OFFERS_AMOUNT_INCOMPLETE`, `OFFERS_OFFER_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.5 Issue an offer

- **URI:** `POST /api/v1/offers/<offer_id>/issue/`
- **Permission key:** `offers.offer.issue` (risk: medium)

**Request:** empty body.
**Response:** 200 with the Offer detail shape, `status: "issued"`.

**Business rules:** only `draft` → `issued`. This is the sole transition into `issued`, and there is no transition back out except a decision.

**Error codes:** `OFFERS_OFFER_NOT_ISSUABLE` (409), `OFFERS_OFFER_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`.

### 1.6 Record a decision

- **URI:** `POST /api/v1/offers/<offer_id>/decision/`
- **Permission key:** `offers.offer.record_decision` (risk: high)

**Request:**

```json
{ "outcome": "deferred", "to_intake": "Jul 2027", "reason": "" }
```

**Response:** 200 with the Offer detail shape, `status` set to the outcome and `decided_at` / `decided_by` stamped.

**Business rules:**
- Permitted from `draft` or `issued` only. **A draft may be decided directly** — a historical offer entered from a paper file was resolved long before it was recorded, and forcing an issue step first would fabricate an event that never happened.
- `rejected` / `withdrawn` require a reason; `deferred` requires `to_intake`; `accepted` and `expired` require neither.
- At most one `accepted` offer per journey, checked via `selectors.get_accepted_offer_for_journey` excluding the offer being decided.
- **Final.** No reopen endpoint exists, deliberately — see `SECURITY.md` §2.

**Error codes:** `OFFERS_OFFER_NOT_DECIDABLE` (409), `OFFERS_ACCEPTED_OFFER_EXISTS` (409), `OFFERS_DECISION_REASON_REQUIRED`, `OFFERS_DEFER_INTAKE_REQUIRED`, `OFFERS_OFFER_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

**AI debugging notes:** `outcome` accepts only the five terminal values (`DecisionOutcome`), not the full `OfferStatus` set — sending `issued` is a serializer `VALIDATION_ERROR`, not a domain error.

### 1.7 Offer history

- **URI:** `GET /api/v1/offers/<offer_id>/history/`
- **Permission key:** `offers.offer.list_history` (risk: low)

**Response:** paginated list of HistoryEvent, newest first — serialized by `audit.serializers.AuditEventHistorySerializer`, the shape shared by every module's history endpoint. Includes `actor_id` as of version 1.1.0.

**Query access pattern.** `selectors.get_history_for_offer` delegates to `audit.selectors.get_events_for_entity` with `entity_type="offer"`, `entity_id=<offer id>`, `app_label="offers"` — served by the audit table's composite `(entity_type, entity_id)` index. Condition events are included because they are written against the offer's entity id.

**Error codes:** `OFFERS_OFFER_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`.

---

## 2. Offer Condition

### 2.1 List an offer's conditions

- **URI:** `GET /api/v1/offers/<offer_id>/conditions/`
- **Permission key:** `offers.condition.list` (risk: low)

**Response:** paginated list of Condition, ordered by `display_order` then `created_at`.

**Query access pattern.** `selectors.get_conditions_for_offer` uses `select_related("resolved_by")` and is served by `condition_offer_status_idx`. Rendering the Offer Detail screen does **not** require this call — the conditions are already nested in the detail response.

**Error codes:** `OFFERS_OFFER_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`.

### 2.2 Add a condition

- **URI:** `POST /api/v1/offers/<offer_id>/conditions/`
- **Permission key:** `offers.condition.create` (risk: medium)

**Request:**

```json
{ "condition_type": "deposit_payment", "description": "AUD 5,000 deposit by 29 August.", "due_date": "2026-08-29" }
```

**Response:** 201 with the Condition shape.

**Business rules:** allowed regardless of the offer's status, **including after a decision** — institutions routinely attach a condition after acceptance, and refusing it would push the record back into the spreadsheet this app replaces.

**Error codes:** `OFFERS_OFFER_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 2.3 Correct a condition

- **URI:** `PATCH /api/v1/offers/conditions/<condition_id>/`
- **Permission key:** `offers.condition.update` (risk: medium)

**Request:** any subset of `condition_type`, `description`, `due_date`, `display_order`.
**Response:** 200 with the Condition shape.

**Business rules:** `status` is absent from the serializer — it moves only through 2.4, which stamps the resolver. Note the route is **not** nested under the offer: a condition never moves between offers, so the offer id carries no information once the condition id is known.

**Error codes:** `OFFERS_CONDITION_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 2.4 Change a condition's status

- **URI:** `POST /api/v1/offers/conditions/<condition_id>/status/`
- **Permission key:** `offers.condition.change_status` (risk: medium)

**Request:**

```json
{ "status": "waived", "note": "Institution confirmed by email that this is not required." }
```

**Response:** 200 with the Condition shape, `resolved_at` / `resolved_by` stamped for a resolved status and cleared for `pending`.

**Business rules:**
- `waived` and `not_applicable` require a note. `satisfied` does not — it is a fact, whereas waiving an institution's requirement is a judgement someone may have to defend later.
- Moving back to `pending` is permitted and clears the resolution stamp; both transitions remain in the audit log.
- Re-sending the current status with no note is a no-op: 200, no event.

**Error codes:** `OFFERS_CONDITION_NOTE_REQUIRED`, `OFFERS_CONDITION_NOT_FOUND`, `OFFERS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

**AI debugging notes:** this endpoint changes the parent offer's derived `has_open_conditions`, which is **not** returned here — the response is the condition alone. A UI showing that flag must refetch the offer or recompute locally.
