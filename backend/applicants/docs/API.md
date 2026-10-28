# API Documentation — Applicants

**App:** `applicants`
**Version:** 1.5.0
**Base prefix:** `/api/v1/applicants/`
**Auth:** Bearer access JWT on every endpoint (`IsAuthenticated`). Authority rules are enforced inline per `SECURITY.md` §1 — applicants are **shared**, not owner-scoped, which deliberately differs from `leads`.
**Throttle:** Project DRF defaults only. No custom scopes.
**Access level:** Mixed — read and edit for Admin and Lead Manager; create is Admin-only. Superadmin is denied on every endpoint. Nothing here is public.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial API documentation — 6 endpoints |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | List endpoint (§1.1) widened: `search` now matches email, contact number, and passport number and orders by relevance; new `country`, `country_code`, and `journey_stage` filters resolve through the applicant's journeys; the list and detail shapes gained a `destinations` array. Additive only — no filter, field, or ordering that a client already relied on changed |
| 1.2.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (`full_name` on Applicant, FamilyMember, EmergencyContact). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |
| 1.2.1 | 2026-08-17 | AI (Claude Fable 5) | List filters (§1.1) validated before the selector: malformed `country` UUID, unknown enum value, or unconvertible `fiscal_year` now returns `400 VALIDATION_ERROR` with field details instead of an unhandled `500` (security audit S6) |
| 1.3.0 | 2026-10-29 | AI (Claude Opus 5.5) | §1.5 `status/` can no longer leave `archived`; §1.7 Admin-only restore to the pre-archive status; §2 applicant notes (list/add/edit/delete) and the note import used by lead conversion |
| 1.4.0 | 2026-10-29 | AI (Claude Opus 5.5) | §1.2–§1.4: `educations` and `language_tests` collections (wholesale replace), identity numbers, family `citizenship_no`; §2.6 conversion imports `import_lead_qualification` / `import_lead_certificates`; `citizenship_no` / `national_id_no` withheld from `applicant_updated.changes` |
| 1.5.0 | 2026-10-29 | AI (Claude Opus 5.5) | Optional assignment: §1.1 `assigned_to` row field and `?assigned_to=me|none|<uuid>` filter; new §1.8 `POST /assign/` (`applicants.applicant.assign`, errors `APPLICANTS_ASSIGNEE_INVALID`, `APPLICANTS_ASSIGNMENT_FORBIDDEN`); §1.2 conversion passes the lead owner as assignee. §1.5, §1.7, §1.8, §2.2 now emit `core.events` domain events that `notifications` turns into alerts (app-wide note); §3 `get_expiring_language_tests` selector for the sweep |

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
{ "count": 100, "page": 1, "page_size": 20, "next": "https://host/api/v1/applicants/?page=2", "previous": null }
```

**AI debugging notes (app-wide):**
- Every endpoint returns 401 unauthenticated and 403 `APPLICANTS_ACTOR_FORBIDDEN` for a Superadmin. Neither is repeated per endpoint.
- 404 `APPLICANTS_APPLICANT_NOT_FOUND` always means the record does not exist. Unlike `leads`, it never means "not yours" — there is no scoping to hide (`SECURITY.md` §4).
- All five sub-resources (contact numbers, addresses, passport, family members, emergency contacts) are managed **nested inside the applicant payload**. There are no standalone sub-resource endpoints. Collections replace wholesale; the passport upserts.
- User-facing dates (`date_of_birth`, `issued_date`, `expiry_date`) carry a `<field>_bs` companion (§39.4). `created_at`/`updated_at` do not.
- `creation_source` and `created_by` are never accepted from a client on any endpoint. `assigned_to` is accepted only by §1.8.
- **Domain events (2026-10-29).** §1.5 (`applicant.status_changed`), §1.7 (`applicant.restored`), §1.8 (`applicant.assigned`), and §2.2 (`applicant.note_added`) call `core.events.emit` after their audit write. The event fires on commit and carries ids and enum strings only; this app imports nothing from `notifications`, which owns the routing (`notifications/docs/INTEGRATION.md`). A failing listener cannot fail the request. Muted by `DISABLE_SIGNALS`.

---

## 1. Applicants

### 1.1 List — `GET /api/v1/applicants/`

**Policy key(s):** `applicants.applicant.list` (risk: low)
**Request query params:**
- `status` — `active` | `dormant` | `archived`
- `creation_source` — `lead_conversion` | `direct_admin`
- `search` — matches `full_name`, `full_name`, `full_name`, `email`, any contact number, and the passport number. All partial (`icontains`) matches
- `country` — a `institutions.Country` id. Matches applicants with **a** journey targeting it
- `country_code` — the same filter by the country's ASCII code (`AU`), case-insensitive
- `journey_stage` — an `applicant_journeys.JourneyStage` value; matches applicants with a journey at that stage
- `fiscal_year` — `YYYY/YY`, Nepali fiscal year, filtering on `created_at`
- `assigned_to` — `me` (the view substitutes the caller's id), `none` (`assigned_to IS NULL`), or a user UUID. Anything else → `400 VALIDATION_ERROR`
- `page`, `page_size` (max 100)

**Response:** paginated array of the applicant **list** shape (includes `assigned_to`: UserBrief or `null`) — `DATA_CONTRACT.md` §1, minus addresses, passport, family, emergency contacts, and `originating_lead_id`. Newest first, **except** when `search` is supplied, in which case results are ordered by relevance (below) and only tie-broken by recency.
**Business rules:**
- Every Admin and Lead Manager sees every applicant. Archived applicants are **not** hidden — filter on `status` to exclude them.
- **Relevance ordering (only when `search` is present):** `3` a name field equals the query, `2` a name field starts with it, `1` a name field contains it, `0` matched only on email, contact number, or passport. Ties fall back to `-created_at`, then `-id`. The score is lexical, not fuzzy — a misspelling still matches nothing, because the filter underneath is `icontains`.
- **An applicant has no country of its own.** The destination belongs to the journey (`applicant_journeys.ApplicantJourney.target_country_ref`), and a person may pursue several over the years. `country`/`country_code`/`journey_stage` therefore mean "has **a** journey matching this", and an applicant with two journeys to the same country is returned once.
- The three filters compose with `search` and with each other; they narrow the same queryset rather than replacing one another.
- A well-formed but unknown country id or code returns an empty page and `200` — absence is a result, not a mistake.
- `assigned_to` filters, it never scopes: an applicant assigned to someone else is still in the unfiltered list. Served by the FK's own index.

**Validation rules:** all filters are validated by `ApplicantListFilterSerializer` before any query runs. A malformed `country` (not a UUID), an unknown `status`/`creation_source`/`journey_stage` value, or a `fiscal_year` label that is malformed or does not convert (e.g. `9999/99`) returns `400 VALIDATION_ERROR` with the offending field in `error.details` — previously these surfaced as unhandled `500`s (UUID/fiscal-year) or empty pages (enum values).

**Query access pattern:** `selectors.get_applicants` applies `select_related("created_by", "assigned_to")` and `prefetch_related("contact_numbers", "journeys__target_country_ref")`, so a page costs a constant number of queries including the `destinations` projection. `search` runs OR `icontains` across the three name fields (served by the `appl_name_*_trgm_idx` GIN trigram indexes), `email` (`appl_email_trgm_idx`), `contact_numbers.number` (`appl_contact_number_idx`), and `passport.passport_number` (`appl_passport_number_idx`). The contact-number join can multiply rows, so the selector applies `distinct()`; so do all three journey-traversing filters. Relevance is a `Case`/`When` annotation rather than `TrigramSimilarity`, deliberately — the test suite runs on SQLite, where `SIMILARITY` does not exist, and a pg_trgm ranking would leave the ordering rule covered by no test.
**Error codes:** none beyond the app-wide 401/403.

### 1.2 Create — `POST /api/v1/applicants/`

**Policy key(s):** `applicants.applicant.create` (risk: high) — **Admin only**
**Request:**
```json
{
  "full_name": "Ram Shrestha",
  "date_of_birth": "2002-05-14",
  "gender": "male",
  "nationality": "Nepali",
  "email": "ram@example.com",
  "contact_numbers": [{ "number": "9800000000", "label": "mobile", "is_primary": true }],
  "addresses": [{ "address_type": "permanent", "district": "Lalitpur", "ward": "5" }],
  "passport": { "passport_number": "PA1234567", "issued_date": "2022-01-01", "expiry_date": "2032-01-01" },
  "family_members": [{ "relationship": "father" }],
  "emergency_contacts": [{ "contact_number": "9812345678" }]
}
```
**Response:** the created applicant in the **detail** shape, HTTP 201.
**Validation rules:** only `full_name` and at least one `contact_numbers` entry are required. At most one address per `address_type`. `status` is not accepted — a new applicant is always `active`. `citizenship_no`, `citizenship_issue_district`, `national_id_no` (and a family member's `citizenship_no`) are normalized free text, not format-checked. `educations[]` and `language_tests[]` — field rules in `DATA_CONTRACT.md` §10 and §11; the cross-field ones run in `services._assert_educations_valid` / `_assert_language_tests_valid` **before any write**, the score and year ranges via `core.validators` (shared with lead certificates so conversion can never copy a value one side rejects).
**Error codes:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — a Lead Manager attempted creation.
- `APPLICANTS_CONTACT_REQUIRED` (400) — no contact number survived validation.
- `APPLICANTS_PASSPORT_EXPIRY_INVALID` (400) — `expiry_date` is not after `issued_date`.
- `APPLICANTS_EDUCATION_INVALID` / `APPLICANTS_LANGUAGE_TEST_INVALID` (400) — `error.details.fields` maps `educations[i].field` / `language_tests[i].field` to a message.
**Business rules:** this is the **direct** creation path, recorded as `creation_source: "direct_admin"`. The conversion path is `POST /api/v1/leads/<id>/convert/`, which calls the same service with `creation_source: "lead_conversion"`. `full_name` is derived server-side. Writes one `applicant_created` audit event whose `metadata.assigned_to` is the assignee id or `null`. `assigned_to` is **not** accepted on this route (always unassigned; use §1.8). Conversion passes the lead's `created_by` as `assigned_to`; `create_applicant` silently drops it (leaves the applicant unassigned) when that person is not an active Admin or Lead Manager, so a departed lead owner never blocks conversion.

### 1.3 Retrieve — `GET /api/v1/applicants/<applicant_id>/`

**Policy key(s):** `applicants.applicant.read` (risk: low)
**Response:** the applicant **detail** shape — `DATA_CONTRACT.md` §1 plus `addresses`, `passport`, `family_members`, `emergency_contacts`, `educations`, `language_tests`, and `originating_lead_id`. The identity numbers (`citizenship_no`, `citizenship_issue_district`, `national_id_no`) are on the detail shape only, like the passport.
**Query access pattern:** `selectors.get_applicant_by_id` prefetches every collection, `educations` and `language_tests` included — a fixed number of queries regardless of how many records the file holds.
**Business rules:** `originating_lead_id` is read through the reverse accessor `applicant.originating_lead` — `leads.Lead` owns the link, so this app carries no dependency on `leads` (`DATA_CONTRACT.md` Deliberate Deviations). It is `null` for a directly created applicant.
**Error codes:** app-wide 404 only.

### 1.4 Update — `PATCH /api/v1/applicants/<applicant_id>/`

**Policy key(s):** `applicants.applicant.update` (risk: medium)
**Request:** any subset of the create payload. Supplying `contact_numbers`, `addresses`, `family_members`, `emergency_contacts`, `educations`, or `language_tests` **replaces that entire set** — send the complete list, not a delta. Supplying `passport` upserts the single record.
**Response:** the updated applicant, detail shape, re-read so the response carries the freshly replaced collections.
**Error codes:** same as §1.2 minus the 403 — a Lead Manager **may** edit.
**Business rules:** `status`, `creation_source`, `created_by`, and `assigned_to` are **not** writable here (DRF drops unknown keys; `assigned_to` is not on `ApplicantUpdateSerializer`). Sending them is ignored, not rejected. Writes `applicant_updated` plus one event per nested collection actually supplied. `citizenship_no` and `national_id_no` are withheld from `applicant_updated.changes` (`<changed>` on both sides, via `_REDACTED_IDENTITY_FIELDS`).

### 1.5 Change status — `POST /api/v1/applicants/<applicant_id>/status/`

**Policy key(s):** `applicants.applicant.change_status` (risk: medium)
**Request:** `{ "status": "dormant" }`
**Response:** the updated applicant, detail shape.
**Error codes:** app-wide 404; `APPLICANTS_APPLICANT_ARCHIVED` (409) when the applicant is archived and another status is requested. An unknown status value is a 400 with `status` in `error.details`.
**Business rules:** always manual. Status is **never** changed as a side effect of a journey opening, closing, or reaching an outcome — the applicant and journey lifecycles are independent by design. Setting the same status again is a no-op and writes no audit event. Moving **to** `archived` (Admin or Lead Manager) stores the status it left in `status_before_archive`. Moving **out of** `archived` is refused here since 2026-10-29 — it is §1.7, Admin-only (`concepts/applicants.txt`: restore is an Admin power). Writes `applicant_status_changed` with `changes.status = {from, to}`, then emits `applicant.status_changed` (`from_status`, `to_status`) → `notifications` raises `applicant_status_changed` to the assignee + Admins, or every Admin and Lead Manager when unassigned, minus the actor. A no-op emits nothing.

### 1.6 History — `GET /api/v1/applicants/<applicant_id>/history/`

**Policy key(s):** `applicants.applicant.list_history` (risk: low)
**Response:** paginated array of history entries, newest first — same shape as the `leads` history endpoint (`id`, `action`, `actor_type`, `actor_id`, `actor_label`, `summary`, `reason`, `changes`, `metadata`, `created_at`, `created_at_bs`).
**Error codes:** app-wide 404 only.
**Business rules:** this app owns no history table; the response is the central `audit` log filtered to this applicant. `AuditEvent` is append-only and blocks deletion at the model layer. The full action vocabulary is tabulated in `DATA_CONTRACT.md` §7. Sensitive values — passport numbers, address text, family names — are deliberately **not** copied into events (`SECURITY.md` §6).
**Query access pattern:** `selectors.get_history_for_applicant` delegates to `audit.selectors.get_events_for_entity` — a runtime dependency on `audit`, not a duplicated table, served by the audit table's composite `(entity_type, entity_id)` index. Entries are serialized by `audit.serializers.AuditEventHistorySerializer`, the shape shared by every module's history endpoint.

### 1.7 Restore — `POST /api/v1/applicants/<applicant_id>/restore/`

**Policy key(s):** `applicants.applicant.restore` (risk: medium) — **Admin only** (`require_admin` after the actor check; a Lead Manager gets 403).
**Request:** `{ "reason": "Came back for a new intake." }` (optional, ≤2000).
**Response:** the applicant, detail shape, `status` = `status_before_archive`, or `active` (`DEFAULT_RESTORE_STATUS`) when blank — applicants archived before the field existed.
**Error codes:** `APPLICANTS_APPLICANT_NOT_ARCHIVED` (409), `APPLICANTS_ACTOR_FORBIDDEN` (403), app-wide 404.
**Business rules:** `services.restore_applicant`; clears `status_before_archive`; writes `applicant_restored` with the reason and `changes.status = {from: "archived", to}`. Nothing else changes — journeys, notes, sub-records. No "merged duplicate" state exists here, so no restore is refused for it. Emits `applicant.restored` → `notifications` raises `applicant_restored`, routed as §1.5.

### 1.8 Assign — `POST /api/v1/applicants/<applicant_id>/assign/`

**Policy key(s):** `applicants.applicant.assign` (risk: medium) — Admin and Lead Manager, with the Lead Manager limited to take/release (below).
**Request:** `{ "assigned_to": "<user uuid>" }` or `{ "assigned_to": null }` — the key is required (`AssignSerializer`, `UUIDField(allow_null=True)`).
**Response:** the applicant, detail shape, message `Applicant assignment updated.`
**Validation rules:** missing key or non-UUID → `400 VALIDATION_ERROR`. The view resolves the id with `authenticate.selectors.get_active_user_by_id`; an unknown or deactivated id → `400 APPLICANTS_ASSIGNEE_INVALID` with `details: {"assigned_to": ["…"]}`, raised before the service runs. The service then rejects an archived applicant (409) before checking eligibility (`_is_eligible_assignee`: active and `authority_type` in Admin/Lead Manager — a Superadmin assignee is 400 `APPLICANTS_ASSIGNEE_INVALID`).
**Error codes:**
- `APPLICANTS_ASSIGNMENT_FORBIDDEN` (403) — a Lead Manager naming anyone but themselves, taking an applicant someone else holds, or clearing someone else's.
- `APPLICANTS_ASSIGNEE_INVALID` (400) — assignee not an active Admin or Lead Manager.
- `APPLICANTS_APPLICANT_ARCHIVED` (409) — the applicant is archived.
- `VALIDATION_ERROR` (400), app-wide 403/404.
**Business rules:** `services.assign_applicant`. **Routing only** — assignment changes who `notifications` tells, never who may read or write (`SECURITY.md` §9). Admin: assign any eligible person, reassign, or clear. Lead Manager: take an unassigned applicant for themselves, or release (`null`) one they hold. Sending the current value is a no-op for any caller (nothing written, nothing emitted). Otherwise writes `applicant_assigned` (new assignee) or `applicant_unassigned` (cleared) with `changes.assigned_to = {from, to}` as user-id strings or `null`, then emits `applicant.assigned` (`assignee_id`, `previous_assignee_id`) → `notifications` sends `applicant_assigned` to the new assignee and `applicant_unassigned` to the previous one, never to the actor.
**AI debugging notes:** a Lead Manager "taking" a file gets no notification — they are the actor. A 400 for a real staff member usually means the account is deactivated or a Superadmin.

## 2. Applicant notes

Categorised (`general`/`visit`), backdatable (`noted_at`), correctable by the author or an Admin, soft-deleted. Mirrors `leads` notes; the shared vocabulary and checks are in `core` (`NoteCategory`, `NOTE_BODY_MAX_LENGTH`, `NOTE_ORDERINGS`; `noted_at_is_in_future`, `note_is_backdated`). Shape: `ApplicantNote` — `DATA_CONTRACT.md` §9. Access follows the applicant: Admin and Lead Manager on any applicant. **Write guard:** an archived applicant's notes are read-only — 409 `APPLICANTS_APPLICANT_ARCHIVED` (`services._assert_notes_writable`).

### 2.1 List — `GET /api/v1/applicants/<applicant_id>/notes/`

**Policy key(s):** `applicants.note.list` (risk: low)
**Query parameters:** `category`, `ordering` (`-noted_at` default | `noted_at` | `-created_at`), `page`, `page_size`.
**Response:** paginated `ApplicantNote` rows (soft-deleted excluded) with `meta.counts = { general, visit }`.
**Query access pattern:** `selectors.get_notes_for_applicant` — `deleted_at IS NULL`, `select_related("author", "updated_by")`, served by `applnote_applicant_noted_idx` `(applicant, -noted_at)`; counts are one grouped `COUNT`.
**Error codes:** app-wide 404; `VALIDATION_ERROR` for a bad filter.

### 2.2 Add — `POST /api/v1/applicants/<applicant_id>/notes/`

**Policy key(s):** `applicants.note.create` (risk: low)
**Request:** `{ "category": "visit", "body": "…", "noted_at": "2026-07-22T15:15:00+05:45" }` — `category` defaults to `general`, `noted_at` to now; an offset-less `noted_at` is parsed as Asia/Kathmandu.
**Response:** the created note, HTTP 201.
**Error codes:** `APPLICANTS_NOTE_FUTURE_DATE` (400), `APPLICANTS_APPLICANT_ARCHIVED` (409), `VALIDATION_ERROR`.
**Business rules:** body normalized and non-blank in serializer and service. Writes `applicant_note_added` with `metadata { note_id, category, noted_at, is_backdated }` — never the text. Emits `applicant.note_added` (`note_id`, `category`); for a `visit` note `notifications` raises `visit_note_added` to the assignee only, or every Admin and Lead Manager when unassigned, minus the author. General notes raise nothing.

### 2.3 Edit — `PATCH /api/v1/applicants/<applicant_id>/notes/<note_id>/`

**Policy key(s):** `applicants.note.update` (risk: medium)
**Request:** any subset of `category`, `body`, `noted_at`.
**Error codes:** `APPLICANTS_NOTE_NOT_FOUND` (404), `APPLICANTS_NOTE_FORBIDDEN` (403 — neither author nor Admin), plus the 2.2 codes.
**Business rules:** writes `applicant_note_updated`; `body` appears in `changes` only as `<changed>`. No-op edits write nothing.

### 2.4 Delete — `DELETE /api/v1/applicants/<applicant_id>/notes/<note_id>/`

**Policy key(s):** `applicants.note.delete` (risk: medium)
**Response:** `data: null`.
**Error codes:** as 2.3.
**Business rules:** soft delete (`deleted_at`, `deleted_by`); writes `applicant_note_deleted`.

### 2.5 Import from a converted lead (service only, no route)

`services.import_lead_notes(actor, applicant, lead_id, notes)` — called by `leads.services.convert_lead` inside its transaction with plain values, never a `leads` model. Bulk-creates the copies with `source_lead_id`, then restores each original `created_at` (`auto_now_add` would stamp the conversion time and mark every carried note backdated). One `applicant_notes_imported` event `{ lead_id, count }`; nothing when the lead had no notes.

### 2.6 Import qualification and certificates from a converted lead (services only, no route)

`services.import_lead_qualification(actor, applicant, lead_id, education)` and `services.import_lead_certificates(actor, applicant, lead_id, certificates)` — called by `leads.services.convert_lead` inside its transaction with plain values, never a `leads` model. Both validate with the same rules as a hand-entered record, set `source_lead_id`, and write one audit event each (`applicant_education_changed` / `applicant_language_tests_changed`, `metadata { count, lead_id }`). Nothing is written for a lead with no qualification level or no certificates. They **append** rather than replace — a freshly converted applicant has no records yet.

## 3. Selectors used by other apps

### 3.1 Expiring language tests (selector only, no route)

`selectors.get_expiring_language_tests(*, within_days=90)` — every `ApplicantLanguageTest` with an `expiry_date` on or before today-in-Nepal + `within_days` (already-expired tests included), archived applicants excluded, soonest first, `select_related("applicant__assigned_to")`. Read by the `notifications` sweep to raise `test_score_expiring` (horizon set by `--test-score-horizon-days`). Same shape and rules as `get_expiring_passports`, which now also joins `applicant__assigned_to` so both alerts can reach the assignee.
