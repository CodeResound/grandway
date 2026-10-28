# API Documentation — Leads

**App:** `leads`
**Version:** 1.5.0
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
| 1.2.1 | 2026-08-17 | AI (Claude Fable 5) | List filters (§3.1) validated before the selector: malformed `source` UUID, unknown `stage`, or unconvertible `fiscal_year` now returns `400 VALIDATION_ERROR` with field details instead of an unhandled `500` (security audit S6) |
| 1.3.0 | 2026-10-29 | AI (Claude Opus 5.5) | §3.4a/§3.4b lead soft delete and restore (Admin only); §4 notes become categorised, backdatable, correctable (§4.3, §4.4 new); every lead write returns 409 on a deleted lead; conversion copies notes to the applicant |
| 1.4.0 | 2026-10-29 | AI (Claude Opus 5.5) | §3.1 three new filters; §3.2/§3.4 study-interest qualification/score/year fields and `language_certificates`; §6.1 conversion creates an applicant education record and language tests |
| 1.5.0 | 2026-10-29 | AI (Claude Opus 5.5) | No request or response change. §3.2, §3.4a, §3.4b, §4.2, §6.1 now emit `core.events` domain events (`lead.created`, `lead.deleted`, `lead.restored`, `lead.note_added`, `lead.converted`) that `notifications` turns into alerts; §6.1 passes the lead's owner to `applicants.services.create_applicant` as `assigned_to`. Registry: `leads.lead.create` 1.2.0, `leads.lead.convert` 1.2.0, `leads.lead.delete` 1.1.0, `leads.lead.restore` 1.1.0, `leads.note.create` 1.2.0 |

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
- **Every write on a soft-deleted lead returns 409 `LEADS_LEAD_DELETED`** (`services._assert_not_deleted`, first check in update, stage, follow-up, lost, reopen, convert, and every note write). A deleted lead is invisible to Lead Managers (404) and to every list unless an Admin passes `?deleted=true` (Lead Manager → 403).

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
- `highest_qualification_level`, `language_test_status` — exact match on the study interest
- `language_test_type` — leads holding at least one certificate of that type (an `Exists` subquery, so a lead with two IELTS results appears once and relevance ranking still composes)
- `page`, `page_size` (max 100)

**Response:** paginated array of the lead **list** shape — `DATA_CONTRACT.md` §3, minus `study_interest` and the lifecycle-state fields. Ordered newest first, **except** when `search` is supplied, in which case results are ordered by relevance and only tie-broken by recency.
**Business rules:**
- An Admin sees every lead; a Lead Manager sees only leads they created. The scope is applied in the queryset, not after fetching.
- **Relevance ordering (only when `search` is present):** `3` a name field equals the query, `2` a name field starts with it, `1` a name field contains it, `0` matched only on email or contact number. Ties fall back to `-created_at`, then `-id`. Lexical, not fuzzy.
- Ranking composes **on top of** owner scoping and never widens it: a Lead Manager's search reorders their own leads and can never surface another manager's.

**Query access pattern:** `selectors.get_leads_for_actor` applies `select_related("source", "created_by")` and `prefetch_related("contact_numbers")`, so rendering a page issues a constant number of queries regardless of page size. `search` runs OR `icontains` across the three name fields (served by the `lead_name_*_trgm_idx` GIN trigram indexes), `email` (`lead_email_trgm_idx`), and `contact_numbers.number` (`lead_contact_number_idx`); the contact-number join can multiply rows, so the selector applies `distinct()`. Ordering and stage/owner filters are served by `lead_owner_recent_idx` and `lead_stage_recent_idx` (`DATA_CONTRACT.md` §3). Relevance is a `Case`/`When` annotation rather than `TrigramSimilarity`, deliberately — the test suite runs on SQLite, where `SIMILARITY` does not exist.
**Validation rules:** all filters are validated by `LeadListFilterSerializer` before any query runs. A malformed `source` (not a UUID), an unknown `stage` value, or a `fiscal_year` label that is malformed or does not convert (e.g. `9999/99`) returns `400 VALIDATION_ERROR` with the offending field in `error.details` — previously the UUID/fiscal-year cases surfaced as unhandled `500`s. A well-formed but unknown `source` id still returns an empty page and `200`.
**Error codes:** `VALIDATION_ERROR` (400, malformed filter) — plus the app-wide 401/403.

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
  "study_interest": {
    "interested_countries": ["Australia"], "study_level": "masters",
    "highest_qualification": "BBS", "highest_qualification_level": "bachelor",
    "academic_score": "3.45", "academic_score_type": "gpa", "pass_year": 2080, "pass_year_calendar": "bs"
  },
  "language_certificates": [{ "test_type": "ielts", "overall_score": "7.0", "test_date": "2025-03-01" }]
}
```
**Response:** the created lead in the **detail** shape (`DATA_CONTRACT.md` §3), HTTP 201.
**Validation rules:** `contact_numbers` must contain at least one entry. `study_interest` is optional and every field inside it is optional, but `academic_score` comes with `academic_score_type` and `pass_year` with `pass_year_calendar`, in range (`core.validators`) — checked in `services._assert_study_interest_valid` against the record as it will be after the write. `language_certificates` (≤10) are checked by `core.validators.language_test_errors`, the rule applicant language tests share. `stage` and `created_by` are not accepted — a new lead always starts at `new`, owned by the caller.
**Error codes:**
- `LEADS_SOURCE_INACTIVE` (400) — the chosen source has been deactivated.
- `LEADS_SOURCE_DETAIL_REQUIRED` (400) — the chosen source has `requires_detail` but `source_detail` was blank.
- `LEADS_CONTACT_REQUIRED` (400) — no contact number survived validation.
- `LEADS_STUDY_INTEREST_INVALID` (400) — pairing or range; `error.details.fields`.
- `LEADS_CERTIFICATE_INVALID` (400) — a certificate rule; `error.details.fields`. `LEADS_CERTIFICATE_LIMIT` (400) — more than 10.
**Business rules:** `full_name` is Unicode-normalized server-side (§39.2). Writes one `lead_created` audit event, then emits `lead.created` → `notifications` raises `lead_created` to every active Admin except the actor.

### 3.3 Retrieve — `GET /api/v1/leads/<lead_id>/`

**Policy key(s):** `leads.lead.read` (risk: low)
**Response:** the lead **detail** shape — `DATA_CONTRACT.md` §3, including `study_interest`, `lost_*`, `converted_*`, and the `_bs` companions.
**Error codes:** app-wide 404 only.

### 3.4 Update — `PATCH /api/v1/leads/<lead_id>/`

**Policy key(s):** `leads.lead.update` (risk: medium)
**Request:** any subset of the create payload. Supplying `contact_numbers` or `language_certificates` **replaces the entire set** — send the complete list the lead should end up with, not a delta (writes `lead_contact_changed` / `lead_certificates_changed` with a count, never scores). Supplying `study_interest` upserts the single interest row.
**Response:** the updated lead, detail shape.
**Error codes:** same three as §3.2.
**Business rules:** `stage` is **not** writable here. Sending it is ignored, not rejected — stage moves only through §3.5, §3.7, §3.8, or (Phase 4) conversion. Writes `lead_updated` (or `lead_source_changed` when the source moved), plus `lead_contact_changed` and `lead_interest_changed` when those were supplied.

### 3.4a Soft delete — `DELETE /api/v1/leads/<lead_id>/`

**Policy key(s):** `leads.lead.delete` (risk: high) — **Admin only** (`require_admin` after the scoped resolve, so a Lead Manager gets 403 on their own lead and 404 on another's).
**Request:** `{ "reason": "Duplicate enquiry." }` (required, ≤500; JSON body on `DELETE`).
**Response:** the Lead detail shape with `deleted_at`, `deleted_at_bs`, `deleted_by`, `delete_reason`.
**Error codes:** `LEADS_LEAD_ALREADY_CONVERTED` (409), `LEADS_LEAD_DELETED` (409, already deleted), `VALIDATION_ERROR` (reason missing/blank/long).
**Business rules:** `services.delete_lead`. Converted leads are applicant origin records and cannot be deleted. Writes `lead_deleted` with the reason, then emits `lead.deleted` → `notifications` raises `lead_deleted` to the lead's owner and every active Admin, minus the actor. Nothing is erased; `LeadAdmin.has_delete_permission` is `False`, so there is no hard delete anywhere.
**Query access pattern:** `get_leads_for_actor(actor, deleted=False)` filters `deleted_at IS NULL` (indexed); `search` and `dashboards` read leads through it, so a deleted lead drops out of both with no change in those apps.

### 3.4b Restore — `POST /api/v1/leads/<lead_id>/restore/`

**Policy key(s):** `leads.lead.restore` (risk: high) — Admin only.
**Request:** `{ "reason": "…" }` optional.
**Response:** the Lead detail shape, `deleted_*` cleared.
**Error codes:** `LEADS_LEAD_NOT_DELETED` (409).
**Business rules:** `services.restore_lead`; writes `lead_restored`, then emits `lead.restored` → `lead_restored` alert to the owner and every active Admin, minus the actor. `get_lead_for_actor` keeps deleted leads in scope for an Admin only, which is what makes this route reachable.

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

Categorised (`general`/`visit`), backdatable (`noted_at`), correctable by the author or an Admin, soft-deleted — since 2026-10-29; append-only before. Shape: `LeadNote` — `DATA_CONTRACT.md` §6. Shared rules live in `core`: `NoteCategory`, `NOTE_BODY_MAX_LENGTH`, `NOTE_ORDERINGS` (`core/constants.py`) and `noted_at_is_in_future` / `note_is_backdated` (`core/validators.py`).

**Write guard (every note write):** `services._assert_notes_writable` — 409 `LEADS_LEAD_DELETED` for a deleted lead, 409 `LEADS_LEAD_ALREADY_CONVERTED` once `converted_applicant` is set (even after a reopen): a converted lead's notes were copied to the applicant and continue there.

### 4.1 List — `GET /api/v1/leads/<lead_id>/notes/`

**Policy key(s):** `leads.note.list` (risk: low)
**Query parameters:** `category` (`general`|`visit`), `ordering` (`-noted_at` default | `noted_at` | `-created_at`), `page`, `page_size` — validated by `LeadNoteListFilterSerializer`.
**Response:** paginated array of `LeadNote`, excluding soft-deleted notes; `meta.counts = { general, visit }` (live notes, independent of `category`), added by the view after pagination.
**Query access pattern:** `selectors.get_notes_for_lead` filters `deleted_at IS NULL` and applies `select_related("author", "updated_by")`; ordering is served by `leadnote_lead_noted_idx` `(lead, -noted_at)`. `get_note_category_counts` is one grouped `COUNT`.
**Error codes:** app-wide 404; `VALIDATION_ERROR` for a bad `category`/`ordering`.

### 4.2 Add — `POST /api/v1/leads/<lead_id>/notes/`

**Policy key(s):** `leads.note.create` (risk: low)
**Request:** `{ "category": "visit", "body": "Came in with her father.", "noted_at": "2026-07-22T15:15:00+05:45" }` — `category` defaults to `general`, `noted_at` to now. A `noted_at` without an offset is parsed in Asia/Kathmandu (`DateTimeField(default_timezone=…)`), never UTC.
**Response:** the created `LeadNote`, HTTP 201.
**Error codes:** `LEADS_NOTE_FUTURE_DATE` (400, `noted_at` > now + 5 min), `LEADS_LEAD_ALREADY_CONVERTED` (409), `LEADS_LEAD_DELETED` (409), `VALIDATION_ERROR` (blank/over-long body, bad category).
**Business rules:** the body is normalized and must be non-blank (§39.2) in the serializer **and** the service. Writes `lead_note_added` with `metadata { note_id, category, noted_at, is_backdated }`; the text is never copied into the audit payload (`SECURITY.md` §5). Emits `lead.note_added` (`note_id`, `category`); for a `visit` note `notifications` raises `visit_note_added` to the lead's owner unless the owner is the author. General notes raise nothing.

### 4.3 Edit — `PATCH /api/v1/leads/<lead_id>/notes/<note_id>/`

**Policy key(s):** `leads.note.update` (risk: medium)
**Request:** any subset of `category`, `body`, `noted_at`.
**Response:** the updated `LeadNote`, with `updated_by` set.
**Error codes:** `LEADS_NOTE_NOT_FOUND` (404, missing or deleted), `LEADS_NOTE_FORBIDDEN` (403, neither author nor Admin), plus the 4.2 codes.
**Business rules:** author-or-Admin check in `services._assert_may_change_note`. Writes `lead_note_updated` with a per-field `changes` map — `body` is the `<changed>` marker, never text. A no-op edit writes nothing.

### 4.4 Delete — `DELETE /api/v1/leads/<lead_id>/notes/<note_id>/`

**Policy key(s):** `leads.note.delete` (risk: medium)
**Response:** `data: null`, HTTP 200.
**Error codes:** as 4.3.
**Business rules:** soft — sets `deleted_at`/`deleted_by`; the note then 404s and leaves the list, the row stays. Writes `lead_note_deleted`. `GET`/`POST` on the list path are unaffected; `DELETE` on the list path still returns 405.

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
- `LEADS_LEAD_DELETED` (409) — the lead is soft-deleted.

**Business rules:**

*Preconditions.* Admin authority, and a lead in one of the six **active** stages. Any active stage qualifies — `ready_for_conversion` signals readiness but is deliberately not a precondition, because the concept describes it as a signal rather than a gate.

*What it creates.* One `applicants.Applicant` and one `applicant_journeys.ApplicantJourney`, both with `creation_source: "lead_conversion"`, by calling those apps' services — never their models (§4). Then sets `converted_applicant`, `converted_journey`, `converted_at`, `converted_by`, and `stage = "converted"` on the lead.

*Idempotency (§15).* Guaranteed at two levels. `services.convert_lead` refuses when `converted_applicant_id` is already set, and `Lead.converted_applicant` is a `OneToOneField`, so a second applicant for one lead is impossible at the database level even if the service guard were bypassed. The test asserts object **counts**, not just the 409, because a status code alone would not prove the second call created nothing.

*Notes.* Since 2026-10-29 the lead's live notes are copied to the applicant inside the same transaction: `selectors.get_lead_note_exports` hands plain values (category, body, `noted_at`, author, `created_at`) to `applicants.services.import_lead_notes`, which bulk-creates `ApplicantNote` rows with `source_lead_id` and restores each original `created_at` (otherwise every carried note would read as backdated). Soft-deleted notes are not copied. The lead's own notes stay and become read-only.

*Qualification and certificates.* When `highest_qualification_level` is set, `_build_education` maps the study interest onto one applicant education entry (`applicants.services.import_lead_qualification`); every certificate becomes an applicant language test (`import_lead_certificates`, via `selectors.get_lead_certificate_exports` — plain values). Both carry `source_lead_id`. `language_test_status` and a level-less `highest_qualification` stay in the journey notes.

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

*Assignment (2026-10-29).* `convert_lead` passes `assigned_to=lead.created_by` to `applicants.services.create_applicant`, so the new applicant is assigned to the lead's owner. `create_applicant` drops it silently (applicant unassigned) when the owner is no longer an active Admin or Lead Manager — conversion never fails because the owner left. Routing only; the applicant stays shared (`applicants/docs/SECURITY.md` §9). `applicant_created.metadata.assigned_to` records the outcome.

*Notification.* After the conversion commits, emits `lead.converted` (with `applicant_id`) → `notifications` raises `lead_converted` to the lead's owner and every active Admin, minus the converting Admin. A notification failure cannot roll back the conversion.

*What it does not do.* It does not delete or alter the lead beyond the conversion fields — notes, contact numbers, and history all survive. A converted lead can be reopened (§3.8), but reopening never clears `converted_applicant`/`converted_journey`, so a second applicant can never come from the same lead.

**AI debugging notes:** if conversion appears to have produced nothing, check the lead's `converted_applicant_id` first — a 409 on a retry means the first call succeeded, not that it failed.
