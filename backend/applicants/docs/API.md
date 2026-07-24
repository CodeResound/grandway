# API Documentation — Applicants

**App:** `applicants`
**Version:** 1.1.0
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
- `creation_source` and `created_by` are never accepted from a client on any endpoint.

---

## 1. Applicants

### 1.1 List — `GET /api/v1/applicants/`

**Policy key(s):** `applicants.applicant.list` (risk: low)
**Request query params:**
- `status` — `active` | `dormant` | `archived`
- `creation_source` — `lead_conversion` | `direct_admin`
- `search` — matches `full_name_np`, `full_name_en`, `full_name_romanized`, `email`, any contact number, and the passport number. All partial (`icontains`) matches
- `country` — a `institutions.Country` id. Matches applicants with **a** journey targeting it
- `country_code` — the same filter by the country's ASCII code (`AU`), case-insensitive
- `journey_stage` — an `applicant_journeys.JourneyStage` value; matches applicants with a journey at that stage
- `fiscal_year` — `YYYY/YY`, Nepali fiscal year, filtering on `created_at`
- `page`, `page_size` (max 100)

**Response:** paginated array of the applicant **list** shape — `DATA_CONTRACT.md` §1, minus addresses, passport, family, emergency contacts, and `originating_lead_id`. Newest first, **except** when `search` is supplied, in which case results are ordered by relevance (below) and only tie-broken by recency.
**Business rules:**
- Every Admin and Lead Manager sees every applicant. Archived applicants are **not** hidden — filter on `status` to exclude them.
- **Relevance ordering (only when `search` is present):** `3` a name field equals the query, `2` a name field starts with it, `1` a name field contains it, `0` matched only on email, contact number, or passport. Ties fall back to `-created_at`, then `-id`. The score is lexical, not fuzzy — a misspelling still matches nothing, because the filter underneath is `icontains`.
- **An applicant has no country of its own.** The destination belongs to the journey (`applicant_journeys.ApplicantJourney.target_country_ref`), and a person may pursue several over the years. `country`/`country_code`/`journey_stage` therefore mean "has **a** journey matching this", and an applicant with two journeys to the same country is returned once.
- The three filters compose with `search` and with each other; they narrow the same queryset rather than replacing one another.
- An unknown country id or code returns an empty page and `200`, never a `400`.

**Query access pattern:** `selectors.get_applicants` applies `select_related("created_by")` and `prefetch_related("contact_numbers", "journeys__target_country_ref")`, so a page costs a constant number of queries including the `destinations` projection. `search` runs OR `icontains` across the three name fields (served by the `appl_name_*_trgm_idx` GIN trigram indexes), `email` (`appl_email_trgm_idx`), `contact_numbers.number` (`appl_contact_number_idx`), and `passport.passport_number` (`appl_passport_number_idx`). The contact-number join can multiply rows, so the selector applies `distinct()`; so do all three journey-traversing filters. Relevance is a `Case`/`When` annotation rather than `TrigramSimilarity`, deliberately — the test suite runs on SQLite, where `SIMILARITY` does not exist, and a pg_trgm ranking would leave the ordering rule covered by no test.
**Error codes:** none beyond the app-wide 401/403.

### 1.2 Create — `POST /api/v1/applicants/`

**Policy key(s):** `applicants.applicant.create` (risk: high) — **Admin only**
**Request:**
```json
{
  "full_name_np": "राम श्रेष्ठ",
  "full_name_en": "Ram Shrestha",
  "date_of_birth": "2002-05-14",
  "gender": "male",
  "nationality": "Nepali",
  "email": "ram@example.com",
  "contact_numbers": [{ "number": "9800000000", "label": "mobile", "is_primary": true }],
  "addresses": [{ "address_type": "permanent", "district": "Lalitpur", "ward": "5" }],
  "passport": { "passport_number": "PA1234567", "issued_date": "2022-01-01", "expiry_date": "2032-01-01" },
  "family_members": [{ "relationship": "father", "full_name_np": "हरि श्रेष्ठ" }],
  "emergency_contacts": [{ "full_name_np": "गीता", "contact_number": "9812345678" }]
}
```
**Response:** the created applicant in the **detail** shape, HTTP 201.
**Validation rules:** only `full_name_np` and at least one `contact_numbers` entry are required. At most one address per `address_type`. `status` is not accepted — a new applicant is always `active`.
**Error codes:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — a Lead Manager attempted creation.
- `APPLICANTS_CONTACT_REQUIRED` (400) — no contact number survived validation.
- `APPLICANTS_PASSPORT_EXPIRY_INVALID` (400) — `expiry_date` is not after `issued_date`.
**Business rules:** this is the **direct** creation path, recorded as `creation_source: "direct_admin"`. The conversion path is `POST /api/v1/leads/<id>/convert/`, which calls the same service with `creation_source: "lead_conversion"`. `full_name_romanized` is derived server-side. Writes one `applicant_created` audit event.

### 1.3 Retrieve — `GET /api/v1/applicants/<applicant_id>/`

**Policy key(s):** `applicants.applicant.read` (risk: low)
**Response:** the applicant **detail** shape — `DATA_CONTRACT.md` §1 plus `addresses`, `passport`, `family_members`, `emergency_contacts`, and `originating_lead_id`.
**Business rules:** `originating_lead_id` is read through the reverse accessor `applicant.originating_lead` — `leads.Lead` owns the link, so this app carries no dependency on `leads` (`DATA_CONTRACT.md` Deliberate Deviations). It is `null` for a directly created applicant.
**Error codes:** app-wide 404 only.

### 1.4 Update — `PATCH /api/v1/applicants/<applicant_id>/`

**Policy key(s):** `applicants.applicant.update` (risk: medium)
**Request:** any subset of the create payload. Supplying `contact_numbers`, `addresses`, `family_members`, or `emergency_contacts` **replaces that entire set** — send the complete list, not a delta. Supplying `passport` upserts the single record.
**Response:** the updated applicant, detail shape, re-read so the response carries the freshly replaced collections.
**Error codes:** same as §1.2 minus the 403 — a Lead Manager **may** edit.
**Business rules:** `status`, `creation_source`, and `created_by` are **not** writable here. Sending them is ignored, not rejected. Writes `applicant_updated` plus one event per nested collection actually supplied.

### 1.5 Change status — `POST /api/v1/applicants/<applicant_id>/status/`

**Policy key(s):** `applicants.applicant.change_status` (risk: medium)
**Request:** `{ "status": "dormant" }`
**Response:** the updated applicant, detail shape.
**Error codes:** app-wide 404 only. An unknown status value is a 400 with `status` in `error.details`.
**Business rules:** always manual. Status is **never** changed as a side effect of a journey opening, closing, or reaching an outcome — the applicant and journey lifecycles are independent by design. Setting the same status again is a no-op and writes no audit event. Archiving deletes nothing and is fully reversible. Writes `applicant_status_changed` with `changes.status = {from, to}`.

### 1.6 History — `GET /api/v1/applicants/<applicant_id>/history/`

**Policy key(s):** `applicants.applicant.list_history` (risk: low)
**Response:** paginated array of history entries, newest first — same shape as the `leads` history endpoint (`id`, `action`, `actor_type`, `actor_id`, `actor_label`, `summary`, `reason`, `changes`, `metadata`, `created_at`, `created_at_bs`).
**Error codes:** app-wide 404 only.
**Business rules:** this app owns no history table; the response is the central `audit` log filtered to this applicant. `AuditEvent` is append-only and blocks deletion at the model layer. The full action vocabulary is tabulated in `DATA_CONTRACT.md` §7. Sensitive values — passport numbers, address text, family names — are deliberately **not** copied into events (`SECURITY.md` §6).
**Query access pattern:** `selectors.get_history_for_applicant` delegates to `audit.selectors.get_events` with `app`/`entity_type`/`entity_id` filters — a runtime dependency on `audit`, not a duplicated table.
