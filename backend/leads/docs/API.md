# API Documentation — Leads

**App:** `leads`
**Version:** 1.2.0
**Base prefix:** `/api/v1/leads/`
**Auth:** Bearer access JWT on every endpoint (`IsAuthenticated`). Authority and ownership rules are enforced inline per `SECURITY.md` §1 — this app does not use the §9 `is_staff` snippet, because leads are owner-scoped rows.
**Throttle:** Project DRF defaults only. No custom scopes — every endpoint is authenticated and none is expensive enough to warrant one today (`SECURITY.md` §7).
**Access level:** Mixed — Admin and Lead Manager. Superadmin is denied on every endpoint. Nothing here is public.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial API documentation — 17 endpoints; conversion deferred to Phase 4 |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | Lead list (§3.1) widened: `search` now matches email and any contact number, and results are relevance-ordered rather than newest-first. Owner scoping is unchanged — ranking reorders inside the caller's existing scope. Additive only |
| 1.2.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (`full_name`, source/loss-reason `name`). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |

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
{ "count": 100, "page": 1, "page_size": 20, "next": "https://host/api/v1/leads/?page=2", "previous": null }
```

**AI debugging notes (app-wide):**
- Every endpoint returns 401 when unauthenticated and 403 `LEADS_ACTOR_FORBIDDEN` when the caller is a Superadmin. Neither is repeated per endpoint below.
- Every endpoint addressing a single lead returns 404 `LEADS_LEAD_NOT_FOUND` when the lead does not exist **or** belongs to another Lead Manager. This is deliberate; see `SECURITY.md` §3. Do not "fix" it to a 403.
- Field-level validation failures return 400 with the offending fields under `error.details`, produced by DRF. Codes listed per endpoint are the app's own domain errors, raised after validation passes.
- Every user-facing datetime has a `<field>_bs` companion carrying the Bikram Sambat projection (§39.4). System timestamps (`created_at`, `updated_at`) do not.
- Both list endpoints for reference data are unpaginated (small, bounded sets). Lead, note, and history lists are paginated.

---

## 1. Lead Sources

Admin-configurable reference data. Every lead actor may read the list — a Lead Manager needs it to attribute a lead — but only an Admin may change it.

### 1.1 List — `GET /api/v1/leads/sources/`

**Policy key(s):** `leads.source.list` (risk: low)
**Request:** optional `?include_inactive=true` to include deactivated entries (default hides them).
**Response:** array of the `LeadSource` shape — `DATA_CONTRACT.md` §1. Unpaginated; ordered by `display_order`, then `name`.
**Error codes:** none beyond the app-wide 401/403.

### 1.2 Create — `POST /api/v1/leads/sources/`

**Policy key(s):** `leads.source.create` (risk: medium) — **Admin only**
**Request:**
```json
{ "code": "referral", "name": "Referral", "requires_detail": false, "display_order": 3 }
```
**Response:** the created `LeadSource` (`DATA_CONTRACT.md` §1), HTTP 201.
**Validation rules:** `code` is lowercased and must be ASCII `[a-z0-9_-]`; `name` is derived server-side and rejected as input.
**Error codes:**
- `LEADS_SOURCE_CODE_TAKEN` (409) — a source with that code already exists.
**Business rules:** set `requires_detail: true` on catch-all entries such as `other`; leads choosing them must then supply `source_detail`.

### 1.3 Edit or deactivate — `PATCH /api/v1/leads/sources/<source_id>/`

**Policy key(s):** `leads.source.update` (risk: medium) — **Admin only**
**Request:** any of `name`, `name`, `requires_detail`, `is_active`, `display_order`. `code` is immutable and silently absent from the update serializer.
**Response:** the updated `LeadSource`.
**Error codes:**
- `LEADS_SOURCE_NOT_FOUND` (404) — no source with that id.
**Business rules:** there is no delete. Retire a source with `{"is_active": false}` — it disappears from pickers while existing leads keep pointing at it. `Lead.source` is `PROTECT`, so deletion is impossible at the database level too.

---

## 2. Loss Reasons

Same shape and same access split as §1. A reason is mandatory whenever a lead is closed, so every lead actor must be able to read this list.

### 2.1 List — `GET /api/v1/leads/loss-reasons/`

**Policy key(s):** `leads.loss_reason.list` (risk: low)
**Request:** optional `?include_inactive=true`.
**Response:** array of the `LossReason` shape — `DATA_CONTRACT.md` §2. Unpaginated.
**Error codes:** none beyond the app-wide 401/403.

### 2.2 Create — `POST /api/v1/leads/loss-reasons/`

**Policy key(s):** `leads.loss_reason.create` (risk: medium) — **Admin only**
**Request:** identical to §1.2.
**Response:** the created `LossReason`, HTTP 201.
**Error codes:**
- `LEADS_LOSS_REASON_CODE_TAKEN` (409) — a reason with that code already exists.

### 2.3 Edit or deactivate — `PATCH /api/v1/leads/loss-reasons/<reason_id>/`

**Policy key(s):** `leads.loss_reason.update` (risk: medium) — **Admin only**
**Request:** identical to §1.3.
**Response:** the updated `LossReason`.
**Error codes:**
- `LEADS_LOSS_REASON_NOT_FOUND` (404) — no reason with that id.

---

## 3. Leads

### 3.1 List — `GET /api/v1/leads/`

**Policy key(s):** `leads.lead.list` (risk: low)
**Request query params:**
- `stage` — one of the eight `LeadStage` values
- `source` — a `LeadSource` id
- `search` — matches across `full_name`, `full_name`, `full_name`, `email`, and any contact number. All partial (`icontains`) matches
- `fiscal_year` — Nepali fiscal year as `YYYY/YY`, e.g. `2081/82`, filtering on `created_at`
- `page`, `page_size` (max 100)

**Response:** paginated array of the lead **list** shape — `DATA_CONTRACT.md` §3, minus `study_interest` and the lifecycle-state fields. Ordered newest first, **except** when `search` is supplied, in which case results are ordered by relevance and only tie-broken by recency.
**Business rules:**
- An Admin sees every lead; a Lead Manager sees only leads they created. The scope is applied in the queryset, not after fetching.
- **Relevance ordering (only when `search` is present):** `3` a name field equals the query, `2` a name field starts with it, `1` a name field contains it, `0` matched only on email or contact number. Ties fall back to `-created_at`, then `-id`. Lexical, not fuzzy.
- Ranking composes **on top of** owner scoping and never widens it: a Lead Manager's search reorders their own leads and can never surface another manager's.

**Query access pattern:** `selectors.get_leads_for_actor` applies `select_related("source", "created_by")` and `prefetch_related("contact_numbers")`, so rendering a page issues a constant number of queries regardless of page size. `search` runs OR `icontains` across the three name fields (served by the `lead_name_*_trgm_idx` GIN trigram indexes), `email` (`lead_email_trgm_idx`), and `contact_numbers.number` (`lead_contact_number_idx`); the contact-number join can multiply rows, so the selector applies `distinct()`. Ordering and stage/owner filters are served by `lead_owner_recent_idx` and `lead_stage_recent_idx` (`DATA_CONTRACT.md` §3). Relevance is a `Case`/`When` annotation rather than `TrigramSimilarity`, deliberately — the test suite runs on SQLite, where `SIMILARITY` does not exist.
**Error codes:** none beyond the app-wide 401/403.

### 3.2 Create — `POST /api/v1/leads/`

**Policy key(s):** `leads.lead.create` (risk: medium)
**Request:**
```json
{
  "full_name": "Ram Shrestha",
  "email": "ram@example.com",
  "address": "Lalitpur",
  "source": "0f1c2b3a-4d5e-6f70-8192-a3b4c5d6e7f8",
  "source_detail": "",
  "contact_numbers": [{ "number": "9800000000", "label": "mobile", "is_primary": true }],
  "study_interest": { "interested_countries": ["Australia"], "study_level": "masters" }
}
```
**Response:** the created lead in the **detail** shape (`DATA_CONTRACT.md` §3), HTTP 201.
**Validation rules:** `contact_numbers` must contain at least one entry. `study_interest` is optional and every field inside it is optional. `stage` and `created_by` are not accepted — a new lead always starts at `new`, owned by the caller.
**Error codes:**
- `LEADS_SOURCE_INACTIVE` (400) — the chosen source has been deactivated.
- `LEADS_SOURCE_DETAIL_REQUIRED` (400) — the chosen source has `requires_detail` but `source_detail` was blank.
- `LEADS_CONTACT_REQUIRED` (400) — no contact number survived validation.
**Business rules:** `full_name` is Unicode-normalized server-side (§39.2). Writes one `lead_created` audit event.

### 3.3 Retrieve — `GET /api/v1/leads/<lead_id>/`

**Policy key(s):** `leads.lead.read` (risk: low)
**Response:** the lead **detail** shape — `DATA_CONTRACT.md` §3, including `study_interest`, `lost_*`, `converted_*`, and the `_bs` companions.
**Error codes:** app-wide 404 only.

### 3.4 Update — `PATCH /api/v1/leads/<lead_id>/`

**Policy key(s):** `leads.lead.update` (risk: medium)
**Request:** any subset of the create payload. Supplying `contact_numbers` **replaces the entire set** — send the complete list the lead should end up with, not a delta. Supplying `study_interest` upserts the single interest row.
**Response:** the updated lead, detail shape.
**Error codes:** same three as §3.2.
**Business rules:** `stage` is **not** writable here. Sending it is ignored, not rejected — stage moves only through §3.5, §3.7, §3.8, or (Phase 4) conversion. Writes `lead_updated` (or `lead_source_changed` when the source moved), plus `lead_contact_changed` and `lead_interest_changed` when those were supplied.

### 3.5 Change stage — `POST /api/v1/leads/<lead_id>/stage/`

**Policy key(s):** `leads.lead.change_stage` (risk: medium)
**Request:** `{ "stage": "counselling" }`
**Response:** the updated lead, detail shape.
**Validation rules:** `stage` must be one of the six **active** stages — `new`, `contact_attempted`, `contacted`, `counselling`, `follow_up`, `ready_for_conversion`. Sending `lost` or `converted` fails DRF choice validation with 400 and the field under `error.details`.
**Error codes:**
- `LEADS_STAGE_NOT_EDITABLE` (409) — the lead is lost or converted; reopen it first.
- `LEADS_STAGE_INVALID_TRANSITION` (400) — a terminal stage reached the service layer directly.
**Business rules:** moving to the stage the lead already holds is a no-op and writes no audit event. `ready_for_conversion` does **not** create an applicant — it only signals readiness.

### 3.6 Record follow-up — `POST /api/v1/leads/<lead_id>/follow-up/`

**Policy key(s):** `leads.lead.record_followup` (risk: low)
**Request:**
```json
{ "note": "Called, will decide next week.", "stage": "counselling", "followed_up_at": "2026-07-23T04:00:00Z" }
```
All three fields are optional; an empty body records a follow-up at the current time.
**Response:** the updated lead, detail shape, with `last_followed_up_at` / `last_followed_up_at_bs` / `last_followed_up_by` set.
**Error codes:**
- `LEADS_STAGE_NOT_EDITABLE` (409) — the lead is lost or converted.
- `LEADS_STAGE_INVALID_TRANSITION` (400) — as §3.5.
**Business rules:** Grandway does not schedule follow-ups, send reminders, or integrate with phone, email, messaging, or calendar. This endpoint only records that manual contact happened, by whom, and optionally what came of it. When `note` is non-blank it creates a `LeadNote`; when `stage` is supplied it applies the same rules as §3.5. Writes `lead_followup_recorded`, plus `lead_note_added` and `lead_stage_changed` where applicable.

### 3.7 Mark lost — `POST /api/v1/leads/<lead_id>/lost/`

**Policy key(s):** `leads.lead.mark_lost` (risk: high)
**Request:** `{ "loss_reason": "<loss_reason_id>", "detail": "Chose another consultancy." }`
**Response:** the updated lead with `stage = "lost"`, `lost_reason`, `lost_at`, `lost_at_bs`, `lost_by`, and `stage_before_loss` populated.
**Validation rules:** `loss_reason` is required — omitting it is a 400 with `loss_reason` in `error.details`.
**Error codes:**
- `LEADS_STAGE_NOT_EDITABLE` (409) — already lost or converted.
- `LEADS_LOSS_REASON_REQUIRED` (400) — no reason reached the service.
- `LEADS_LOSS_REASON_INACTIVE` (400) — the chosen reason has been deactivated.
- `LEADS_LOSS_DETAIL_REQUIRED` (400) — the reason has `requires_detail` but `detail` was blank.
**Business rules:** nothing is deleted. The lead, its notes, its contact numbers, and its full history all survive, and the lead can be reopened later (§3.8). `stage_before_loss` remembers where it was so the closure is interpretable afterwards. Writes `lead_marked_lost` with the reason code in the event's `reason` field.

### 3.8 Reopen — `POST /api/v1/leads/<lead_id>/reopen/`

**Policy key(s):** `leads.lead.reopen` (risk: high)
**Request:** `{ "stage": "contacted" }` — optional; defaults to `follow_up`.
**Response:** the updated lead with the loss fields cleared.
**Error codes:**
- `LEADS_LEAD_NOT_LOST` (409) — the lead is already active.
- `LEADS_STAGE_INVALID_TRANSITION` (400) — the requested stage is terminal.
**Business rules:** this is the **only** way back from a terminal stage. It clears all six loss fields (`lost_reason`, `lost_detail`, `lost_at`, `lost_by`, `stage_before_loss`) but **never touches `converted_at`/`converted_by`** — reopening a converted lead does not undo the conversion, does not delete the applicant, and leaves the lead permanently linked so a second applicant can never be created from it. All previous history is preserved; the reopen is itself appended as `lead_reopened` with `metadata.reopened_from_converted`.

---

## 4. Lead Notes

### 4.1 List — `GET /api/v1/leads/<lead_id>/notes/`

**Policy key(s):** `leads.note.list` (risk: low)
**Response:** paginated array of the `LeadNote` shape — `DATA_CONTRACT.md` §6. Newest first.
**Query access pattern:** `selectors.get_notes_for_lead` applies `select_related("author")` so author attribution costs no extra query per row.
**Error codes:** app-wide 404 only.

### 4.2 Add — `POST /api/v1/leads/<lead_id>/notes/`

**Policy key(s):** `leads.note.create` (risk: low)
**Request:** `{ "body": "Wants Australia, needs IELTS." }`
**Response:** the created `LeadNote`, HTTP 201.
**Error codes:** app-wide 404 only.
**Business rules:** notes are **append-only**. There is no update or delete endpoint and none will be added — a Lead Manager may not delete lead history. `PUT`/`PATCH`/`DELETE` on this path return 405. Writes `lead_note_added`; the note's text is deliberately **not** copied into the audit payload (`SECURITY.md` §5).

---

## 5. Lead History

### 5.1 List — `GET /api/v1/leads/<lead_id>/history/`

**Policy key(s):** `leads.lead.list_history` (risk: low)
**Response:** paginated array of history entries, newest first:
```json
{
  "id": "…",
  "action": "lead_stage_changed",
  "actor_type": "lead_manager",
  "actor_id": "…",
  "actor_label": "leadmgr",
  "summary": "Stage changed from new to contacted.",
  "reason": "",
  "changes": { "stage": { "from": "new", "to": "contacted" } },
  "metadata": {},
  "created_at": "2026-07-23T04:05:00Z",
  "created_at_bs": { "year": 2083, "month": 4, "day": 8, "month_name": "Shrawan", "display": "2083 Shrawan 8" }
}
```
**Error codes:** app-wide 404 only.
**Business rules:** this app owns no history table. The response is the central `audit` log filtered to this lead. `AuditEvent` is append-only and blocks deletion at the model layer, so entries can never be rewritten or removed. The full action vocabulary is tabulated in `DATA_CONTRACT.md` §7.
**Query access pattern:** `selectors.get_history_for_lead` delegates to `audit.selectors.get_events_for_entity` — a runtime dependency on the `audit` app, not a duplicated table, served by the audit table's composite `(entity_type, entity_id)` index. Entries are serialized by `audit.serializers.AuditEventHistorySerializer`, the shape shared by every module's history endpoint. The lead is resolved through the owner-scoped selector first, so a Lead Manager cannot read the history of a lead they do not own even though `audit` itself is global.

---

## 6. Conversion

### 6.1 Convert — `POST /api/v1/leads/<lead_id>/convert/`

**Policy key(s):** `leads.lead.convert` (risk: **critical**) — **Admin only**
**Request:** empty body. Everything is taken from the lead.
**Response:** HTTP 201 with three keys:
```json
{ "lead": { "...": "Lead detail shape, stage now converted" }, "applicant_id": "…", "journey_id": "…" }
```
**Error codes:**
- `LEADS_ACTOR_FORBIDDEN` (403) — a Lead Manager or Superadmin attempted conversion.
- `LEADS_LEAD_ALREADY_CONVERTED` (409) — this lead already produced an applicant.
- `LEADS_CONVERSION_NOT_READY` (409) — the lead is lost or converted; reopen it first.

**Business rules:**

*Preconditions.* Admin authority, and a lead in one of the six **active** stages. Any active stage qualifies — `ready_for_conversion` signals readiness but is deliberately not a precondition, because the concept describes it as a signal rather than a gate.

*What it creates.* One `applicants.Applicant` and one `applicant_journeys.ApplicantJourney`, both with `creation_source: "lead_conversion"`, by calling those apps' services — never their models (§4). Then sets `converted_applicant`, `converted_journey`, `converted_at`, `converted_by`, and `stage = "converted"` on the lead.

*Idempotency (§15).* Guaranteed at two levels. `services.convert_lead` refuses when `converted_applicant_id` is already set, and `Lead.converted_applicant` is a `OneToOneField`, so a second applicant for one lead is impossible at the database level even if the service guard were bypassed. The test asserts object **counts**, not just the 409, because a status code alone would not prove the second call created nothing.

*Atomicity.* The whole conversion runs in one `atomic()` block. A failure while creating the journey rolls back the applicant too — there is no state in which a lead has an applicant but no journey.

*Identity mapping to the applicant.* `full_name`, `full_name`, `full_name`, `email`, all contact numbers, and `address` (as a `permanent` `ApplicantAddress`). Nothing else — a lead holds no date of birth, passport, or family.

*Study-interest mapping to the journey.* `LeadStudyInterest` has ten fields; six map directly (`study_level`, `field_of_study`, `preferred_intake`, `budget_amount`, `budget_currency`, `scholarship_interest`). The remaining four are handled explicitly rather than dropped:

| Lead field | Destination | Why |
|---|---|---|
| `interested_countries` | `target_country` **only if exactly one** | A journey targets one country. Two or more is a genuine ambiguity only a human can resolve, so the field is left blank and the full list is written to the journey's `notes`. |
| `highest_qualification` | journey `notes` | Belongs to the `education` module, which does not exist. |
| `language_test_status` | journey `notes` | Belongs to `test_scores`, which does not exist. |
| `interest_notes` | journey `notes` | Direct. |

*Audit.* Writes `lead_converted` and `lead_applicant_created` to this lead's history, plus `applicant_created` and `journey_created` to the new records' own histories.

*What it does not do.* It does not delete or alter the lead beyond the conversion fields — notes, contact numbers, and history all survive. A converted lead can be reopened (§3.8), but reopening never clears `converted_applicant`/`converted_journey`, so a second applicant can never come from the same lead.

**AI debugging notes:** if conversion appears to have produced nothing, check the lead's `converted_applicant_id` first — a 409 on a retry means the first call succeeded, not that it failed.
