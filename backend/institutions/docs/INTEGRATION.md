# Integration — Institutions

**Owner app:** `institutions`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial integration contract — 20 endpoints, Phase 1 catalogue spine |
| 1.1.0 | 2026-07-24 | AI (Claude) | Documentation only — no endpoint or behaviour change. Added HTTP status codes, the `INSTITUTIONS_ACTOR_FORBIDDEN` body, query-parameter encoding, write-field defaults, ordering, and module-wide rules for immutability, no-op PATCH, and the availability-note requirement. Defined `is_usable` as per-record rather than chain-aware, and documented the `tuition_max` currency/period limitation, the institution→program country cascade, and `q`'s exact field coverage. Raised from the §19.5 consumer-comprehension test |

---

## 1. Module

- **Name:** Institutions — the study-opportunity catalogue. Owns the countries, providers, campuses, and programs the consultancy can offer, with each program's tuition, entry expectations, and current availability. It is **reference data, not an applicant's plan**: it says what *can* be offered, never what a particular person is pursuing.
- **Base path:** `/api/v1/catalogue/` — note this differs from the app name. The module owns five resources and "institutions" is only one of them.
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. Two authority types may use this module: `admin` and `lead_manager`, with **different** rights — see §3. A `superadmin` token is rejected with 403 everywhere, including on reads.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which decides both whether the caller may act and whether they may write. | Every endpoint returns 401; a `superadmin` gets 403 `INSTITUTIONS_ACTOR_FORBIDDEN` on every route including reads. |
| `audit` | service call | Every create and update appends one immutable event carrying the changed fields' previous and new values. This module stores no history of its own. | Catalogue edits still succeed but leave no trace of what changed — the concept's "previous values should remain visible in history" requirement is silently lost. |

**This module depends on `applicants`, `applicant_journeys`, and `leads` for nothing, and none of them depends on it.** In Phase 1 the catalogue is standalone: `applicant_journeys` still stores its destination as free text (`target_country`, `target_institution_name`, `target_program_name`) and does **not** reference these records. A client building a shortlisting screen must therefore copy the chosen values across itself — see §9.

**No FK to `authenticate`.** Catalogue records have no owner and no `created_by` column; attribution lives entirely in the audit log.

## 3. Conventions

- **Access split — the single most important thing about this module.** Reads are shared, writes are Admin-only:
  - `GET` on any resource: `admin` and `lead_manager`. Search is the point of the catalogue.
  - `POST` / `PATCH` on any resource: `admin` **only**. A `lead_manager` receives 403 `INSTITUTIONS_ACTOR_FORBIDDEN`. Catalogue data is shared infrastructure — one careless edit changes what every Lead Manager sees.
  - `superadmin`: 403 on everything, reads included.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint in this module.** A record that is no longer offered is set to `availability_status: "inactive"`. Records referenced by others are additionally protected at the database level. Do not build a delete button; build a "withdraw from use" control that PATCHes the status.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is **abridged to two fields to show the envelope**; a real create returns the full detail shape defined in §4.

```json
{
  "success": true,
  "message": "Program created.",
  "data": { "id": "4f506172-8c9d-4e0f-b112-3c4d5e6f7081", "title": "Master of Information Technology" },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract, and may change without a version bump. Branch on the HTTP status and, for errors, on `error.code`.

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object.

```json
{
  "success": false,
  "error": {
    "code": "INSTITUTIONS_TUITION_INCOMPLETE",
    "message": "Recording a tuition amount requires both a currency and a fee period.",
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
    "details": { "name_en": ["This field is required."] }
  },
  "meta": {}
}
```

- **HTTP status codes:** `POST` returns **201** on success. `GET` and `PATCH` return **200**. Domain-rule violations are **400**, except duplicates, which are **409**. Missing records are **404**. Authority failures are **403**. Calling an unrouted method — `DELETE` or `PUT` on any resource, or `POST` on the un-nested `/campuses/<id>/` route — returns **405** with DRF's `METHOD_NOT_ALLOWED` code, not a module code.
- **Auth failures:** 401 with no token, an expired token, or a revoked session — produced by the authentication framework. 403 `INSTITUTIONS_ACTOR_FORBIDDEN` when the token is valid but the authority may not perform that action (a `lead_manager` writing, or a `superadmin` doing anything). It is **the most common error in this module** — every Lead Manager write returns it — and is therefore omitted from the per-endpoint `Errors` lists in §7, which would otherwise repeat it twenty times. Its body:

```json
{
  "success": false,
  "error": {
    "code": "INSTITUTIONS_ACTOR_FORBIDDEN",
    "message": "Admin authority is required to maintain the catalogue.",
    "details": {}
  },
  "meta": {}
}
```

  The `message` is `"Admin authority is required to maintain the catalogue."` for a write refused to a Lead Manager, and `"This authority may not access catalogue records."` for a Superadmin refused a read. Branch on `code`, never on `message`.

  **This module's 403 code replaces the project-wide `PERMISSION_DENIED`, it does not coexist with it.** Every authority refusal in `/api/v1/catalogue/` is `INSTITUTIONS_ACTOR_FORBIDDEN`; you will not see `PERMISSION_DENIED` from these endpoints.
- **Unknown referenced UUIDs are 400, not 404.** Sending a `country`, `institution`, `field`, or `campus` id that does not exist fails serializer validation and returns `VALIDATION_ERROR` with the offending field in `details` — a 404 is only ever about the record named in the **URL path**. The one exception is the campus routes' `<institution_id>`, which is in the path and so returns 404 `INSTITUTIONS_INSTITUTION_NOT_FOUND`.
- **A malformed `code`** (non-ASCII, bad characters, wrong length) returns `VALIDATION_ERROR` with `details.code`, not `INSTITUTIONS_CODE_DUPLICATE`. The duplicate code is only ever returned for a *taken* code, and only on create — `code` is immutable, so it can never fire on `PATCH`.
- **Immutable fields are silently ignored on update, never rejected** — module-wide, with no exceptions: `Field.code`, `Country.code`, `Campus.institution`, and `Program.institution`. A client that reads an object and PATCHes the whole thing back will succeed, with those fields unchanged. This is deliberate, so a round-trip edit form needs no field-stripping logic.
- **A `PATCH` that changes nothing writes no audit event** — module-wide, all five resources. The response is still 200 with the unchanged record. A UI that reports "saved, history updated" after an unchanged submit will be claiming something that did not happen.
- **`usable_only` is chain-aware on `/programs/` only.** On `/countries/`, `/institutions/`, and `.../campuses/` it filters on **that record's own** `availability_status` and ignores ancestors — so `usable_only=true` on `/institutions/` still returns an `active` institution sitting under a `paused` country. On all three it defaults to `false`; only `/programs/` defaults it to `true` and evaluates the whole chain. On every endpoint, passing `availability_status` explicitly **overrides** `usable_only` entirely.
- **A non-`active` `availability_status` requires a non-empty `availability_note`** — module-wide, on all four availability-bearing resources (`Country`, `Institution`, `Campus`, `Program`), on create **and** update. `seasonal` is included: "seasonal" without saying which season explains nothing. The rule is checked against the **resulting** record, so a `PATCH` sending only `availability_status` fails even when a note is already stored — the reason must be re-affirmed by whoever makes the change, not inherited. Returns 400 `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED`.
- **Query parameter encoding.** Booleans (`is_active`, `usable_only`, `scholarship_available`) accept, case-insensitively: `true`/`false`, `1`/`0`, `t`/`f`, `y`/`n`, `yes`/`no`, `on`/`off`. Anything else is a 400. **Omitting a boolean is not the same as sending `false`**: omitted means "do not filter on this at all" for `is_active` and `scholarship_available`, whereas `usable_only` falls back to its documented per-endpoint default. Decimals (`tuition_max`) accept a plain literal — `50000` or `50000.00`; a non-numeric value is a 400. `page_size` above the 100 maximum is **clamped, not rejected**.
- **Every error in this module carries the standard envelope, including 405.** An unrouted method returns 405 with `error.code` of `METHOD_NOT_ALLOWED` — the project-wide code, not a module one — inside the usual `success`/`error`/`meta` structure. There is no raw-DRF error shape anywhere here, so an interceptor reading `body.error.code` is safe on every status. A path that does not exist at all — `GET /api/v1/catalogue/campuses/`, which is not a route; campuses are listed under their institution — returns a plain **404** from URL resolution, before any view or handler runs, and so carries **no envelope**. Status-first branching handles both.
- **Defaults for omitted write fields:** `availability_status` → `"active"`, `is_active` (Field) → `true`, `institution_type` → `"university"`, `tuition_is_indicative` → `false`, `scholarship_available` → `false`, `display_order` → `0`. Every unset text field is `""`; `campus`, `duration_months`, and `tuition_amount` are `null`.
- **Ordering** is fixed per resource and **not client-controllable** — there is no `sort` or `ordering` parameter anywhere. `Field` and `Country`: `display_order`, then `name_en`. `Institution` and `Campus`: `name_en`. `Program`: `title`.
- **Request encoding:** `application/json`.
- **Pagination:** page-number based. Params `page` and `page_size` (default 20, max 100). `meta` carries `count`, `page`, `page_size`, `next`, `previous` — `next`/`previous` are absolute URLs or `null`. Applied to **every** list endpoint here.
- **IDs:** UUID strings. `code` on `Field` and `Country` is a separate human-readable ASCII identifier, unique and immutable, but **not** the primary key — always address records by `id`.
- **Times:** ISO 8601 UTC. **No field in this module carries a `_bs` Bikram Sambat sibling** — the only dates here are `created_at`/`updated_at`, which are system timestamps and are exempt (§39.4). This differs from `applicant_journeys`, where `closed_at` and `deferred_at` do carry one.
- **Invalid query parameters are rejected with 400, not ignored.** `?tuition_max=cheap` or `?qualification_level=wizardry` returns a validation error rather than an unfiltered result set.
- **Money:** decimal **strings**, never numbers — `"49824.00"`. Never parse into a float.

## 4. Models

**Field** — `{ id, code, name_en, name_np, is_active, display_order, created_at, updated_at }`

- The study-area classification. `is_active` rather than `availability_status`: it is a pure reference table, not something that can be seasonal.

**Country** — `{ id, code, name_en, name_np, availability_status:[enum], availability_note, is_usable, notes, display_order, created_at, updated_at }`

- `is_usable` is a **read-only derived boolean**, true when **that record's own** `availability_status` is `active` or `seasonal`.

> **`is_usable` is per-record, not per-chain — read this before using it.** It reflects only the record it appears on. A `Program` whose own status is `active` but whose country is `paused` returns **`is_usable: true`** while being excluded from the default search, because the search evaluates the whole chain (program → campus → institution → country) and `is_usable` does not.
>
> The two therefore disagree exactly when an ancestor is unavailable. Use `is_usable` to render **this record's own** availability badge on a detail or maintenance screen. Do **not** use it to decide whether a program can be offered.
>
> To decide that client-side, rely on the default search (which already filters correctly), or evaluate the chain yourself:
>
> - the program's own `is_usable`, **and**
> - `availability_status ∈ {"active", "seasonal"}` on each of the nested `campus` (when not `null`), `institution`, and `country`.
>
> **The nested brief shapes carry `availability_status`, not `is_usable`** — `CountryBrief`, `InstitutionBrief`, and `CampusBrief` are exactly the field lists given below, and none of them includes a derived boolean. `availability_status` is present on all three precisely so this check is possible without four extra requests.

**CountryBrief** — `{ id, code, name_en, availability_status:[enum] }`

**Institution** — `{ id, country:CountryBrief, name_en, name_np, common_name, institution_type:[enum], availability_status:[enum], availability_note, is_usable, notes, created_at, updated_at }`

- `country` is a nested object on read, but a **bare UUID string** on write.

**InstitutionBrief** — `{ id, name_en, common_name, availability_status:[enum] }`

**Campus** — `{ id, institution:InstitutionBrief, name_en, city, availability_status:[enum], availability_note, is_usable, notes, created_at, updated_at }`

- No `name_np`: campus names are localities in the destination country.

**CampusBrief** — `{ id, name_en, city, availability_status:[enum] }`

**FieldBrief** — `{ id, code, name_en }`

**Program (list shape)** — `{ id, title, institution:InstitutionBrief, campus?:CampusBrief, country:CountryBrief, qualification_level:[enum], field:FieldBrief, duration_months?, intake_pattern, tuition_amount?, tuition_currency, tuition_fee_period:[enum], tuition_is_indicative, scholarship_available, availability_status:[enum], availability_note, is_usable, created_at, updated_at }`

- `country` is **derived from the institution** and is read-only — there is no country field on a program write.
- `campus` and `duration_months` are `null` when unset. `tuition_amount` is a decimal string or `null`.
- Empty text fields are `""`, never `null`.

**Program (detail shape)** — the list shape plus `{ tuition_notes, academic_requirement, english_requirement, backlog_tolerance, document_expectation, selection_notes, scholarship_notes, notes }`

- The detail shape is returned by retrieve, create, **and** update. Only the list returns the shorter shape. The five entry-expectation fields are long free text and are deliberately absent from list rows.

### Worked examples

**Program (detail shape)**

```json
{
  "id": "4f506172-8c9d-4e0f-b112-3c4d5e6f7081",
  "title": "Master of Information Technology",
  "institution": {
    "id": "2d3e4f50-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
    "name_en": "University of Melbourne",
    "common_name": "Unimelb",
    "availability_status": "active"
  },
  "campus": {
    "id": "3e4f5061-7b8c-4d9e-af01-2b3c4d5e6f70",
    "name_en": "Parkville",
    "city": "Melbourne",
    "availability_status": "active"
  },
  "country": {
    "id": "1c2b3a49-5d6e-4f70-8a91-b2c3d4e5f607",
    "code": "au",
    "name_en": "Australia",
    "availability_status": "active"
  },
  "qualification_level": "masters",
  "field": {
    "id": "8f1d9e2a-4c3b-4a71-9f0e-2b6c5d8e1a34",
    "code": "information_technology",
    "name_en": "Information Technology"
  },
  "duration_months": 24,
  "intake_pattern": "Feb / Jul",
  "tuition_amount": "49824.00",
  "tuition_currency": "AUD",
  "tuition_fee_period": "total_program",
  "tuition_is_indicative": true,
  "tuition_notes": "2026 rate; the university has not published 2027 fees.",
  "academic_requirement": "Bachelor's in any discipline, 65% or GPA 2.8+.",
  "english_requirement": "IELTS 6.5 overall, no band below 6.0.",
  "backlog_tolerance": "Up to 5 backlogs considered case by case.",
  "document_expectation": "Certified transcripts and provisional certificate at application.",
  "selection_notes": "Prefers applicants with a computing or quantitative background.",
  "scholarship_available": true,
  "scholarship_notes": "Graduate Access Scholarship — 25% tuition, merit-based.",
  "availability_status": "active",
  "availability_note": "",
  "is_usable": true,
  "notes": "",
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T09:18:47Z"
}
```

**Country, withdrawn from use**

```json
{
  "id": "1c2b3a49-5d6e-4f70-8a91-b2c3d4e5f607",
  "code": "au",
  "name_en": "Australia",
  "name_np": "अस्ट्रेलिया",
  "availability_status": "paused",
  "availability_note": "Partner agreement under review until October.",
  "is_usable": false,
  "notes": "Genuine Student requirement applies from 2024 intakes onward.",
  "display_order": 1,
  "created_at": "2026-07-24T09:14:02Z",
  "updated_at": "2026-07-24T11:02:19Z"
}
```

## 5. Enums

- `availability_status` (on `Country`, `Institution`, `Campus`, `Program`): `active` | `paused` | `seasonal` | `inactive`
- **Usable statuses** (what `is_usable` returns true for, and what the default program search includes): `active` | `seasonal`. `seasonal` counts as usable — it is offered, just not year-round.
- `Institution.institution_type`: `university` | `college` | `polytechnic` | `language_school` | `other`
- `Program.qualification_level`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other`. **This is the same value set as `applicant_journeys` `Journey.study_level`**, deliberately, so a journey's level can be passed straight into the program search as `?qualification_level=`.
- `Program.tuition_fee_period`: `per_year` | `per_semester` | `total_program` | `""` (empty when no tuition is recorded)
- `Field.code`, `Country.code`: **not enums** — admin-assigned ASCII identifiers matching `^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$`. Country codes are ISO 3166-1 alpha-2 by convention but this is not enforced.
- `Program.intake_pattern`: **not an enum** — free text in Phase 1 (see §9).

## 6. Dependency order

- `Institution` needs `Country` — a provider is always filed under a country.
- `Campus` needs `Institution` — supplied in the URL path, not the body.
- `Program` needs `Institution` **and** `Field`; `Campus` is optional but, when given, must belong to the same institution.
- `Field` and `Country` need nothing — they are the roots.

**Start here:** create a `Country` and a `Field` (independent of each other), then an `Institution` under the country, then optionally a `Campus` under the institution, then a `Program`. A client with an empty catalogue cannot create a program first.

## 7. Endpoints

### Study Field — `/api/v1/catalogue/fields/`

**Use it when:** the Reference Maintenance screen, and populating the field filter on the program search.
**Methods:**
- `GET /api/v1/catalogue/fields/` — list (permission: `institutions.field.list`, risk: low)
- `POST /api/v1/catalogue/fields/` — create (permission: `institutions.field.create`, risk: medium)
- `GET /api/v1/catalogue/fields/<field_id>/` — retrieve (permission: `institutions.field.read`, risk: low)
- `PATCH /api/v1/catalogue/fields/<field_id>/` — update (permission: `institutions.field.update`, risk: medium)

**Send (create/update):**
- create: `code` (required), `name_en` (required), `name_np`, `is_active`, `display_order`
- update: any subset of `name_en`, `name_np`, `is_active`, `display_order` — **not `code`**

**Returns:** Field for create, retrieve, and update; list[Field] for the list, paginated.
**Requires state:** nothing.
**Side effects:** appends `catalogue_field_created` / `catalogue_field_updated` to the central audit log. A `PATCH` that changes nothing writes no event.

**Notes:**
- Query params: `is_active` (bool — omitting it returns both active and inactive), `q` (partial match on either name).
- `code` is **immutable**. Sending it on update is ignored, not rejected.
- Ordering is `display_order`, then `name_en`. Not client-controllable.
- Writes are Admin-only.

**Errors:**
- `INSTITUTIONS_CODE_DUPLICATE` (409) — that code is already taken
- `INSTITUTIONS_FIELD_NOT_FOUND` (404) — no field with that id

### Country — `/api/v1/catalogue/countries/`

**Use it when:** the Country List / Detail screens, and populating the country filter on the program search.
**Methods:**
- `GET /api/v1/catalogue/countries/` — list (permission: `institutions.country.list`, risk: low)
- `POST /api/v1/catalogue/countries/` — create (permission: `institutions.country.create`, risk: medium)
- `GET /api/v1/catalogue/countries/<country_id>/` — retrieve (permission: `institutions.country.read`, risk: low)
- `PATCH /api/v1/catalogue/countries/<country_id>/` — update (permission: `institutions.country.update`, risk: high)

**Send (create/update):**
- create: `code` (required), `name_en` (required), `name_np`, `availability_status`, `availability_note`, `notes`, `display_order`
- update: any subset of `name_en`, `name_np`, `availability_status`, `availability_note`, `notes`, `display_order` — **not `code`**

**Returns:** Country for create, retrieve, and update; list[Country] for the list, paginated.
**Requires state:** nothing.
**Side effects:** appends `catalogue_country_created` / `catalogue_country_updated` to the audit log, recording each changed field's previous and new value. **Availability does not cascade** — pausing a country leaves every institution and program under it with its own status untouched, though they will drop out of the default program search while the country is unusable.

**Notes:**
- Query params: `availability_status` (exact), `usable_only` (bool, default **false** here — a maintenance list shows everything), `q` (partial match on either name).
- **Setting `availability_status` to anything other than `active` requires a non-empty `availability_note`** in the same request. Patching the status alone fails even if a note is already stored.
- `name_np` is optional; `name_en` is required. This is the inverse of the convention in `leads` and `applicants`.
- There is no delete. Use `availability_status: "inactive"`.

**Errors:**
- `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400) — non-active status sent without a note
- `INSTITUTIONS_CODE_DUPLICATE` (409) — that code is already taken
- `INSTITUTIONS_COUNTRY_NOT_FOUND` (404) — no country with that id

### Institution — `/api/v1/catalogue/institutions/`

**Use it when:** the Institution List / Detail screens, and the provider filter on the program search.
**Methods:**
- `GET /api/v1/catalogue/institutions/` — list (permission: `institutions.institution.list`, risk: low)
- `POST /api/v1/catalogue/institutions/` — create (permission: `institutions.institution.create`, risk: medium)
- `GET /api/v1/catalogue/institutions/<institution_id>/` — retrieve (permission: `institutions.institution.read`, risk: low)
- `PATCH /api/v1/catalogue/institutions/<institution_id>/` — update (permission: `institutions.institution.update`, risk: high)

**Send (create/update):**
- create: `country` (required, UUID), `name_en` (required), `name_np`, `common_name`, `institution_type`, `availability_status`, `availability_note`, `notes`
- update: any subset of the same fields, **including `country`**

**Returns:** Institution for create, retrieve, and update; list[Institution] for the list, paginated.
**Requires state:** an existing `Country`.
**Side effects:**
- appends `catalogue_institution_created` / `catalogue_institution_updated` to the audit log.
- **Availability does not cascade** to campuses or programs — but **identity does.** `Program.country` is derived from the institution, so changing an institution's `country` silently rewrites the `country` reported by *every* program under it, and changes which `?country=` filter they answer to. On a large provider that is hundreds of records altered by one `PATCH`, with a single audit event recording it. Warn before submitting a country change on an institution that has programs.

**Notes:**
- Query params: `country` (exact id), `institution_type` (exact), `availability_status` (exact), `usable_only` (bool, default false), `q` (partial match on `name_en`, `name_np`, or `common_name` — trigram-indexed).
- `country` **is** editable, unlike the immutable parents elsewhere in this module: an institution filed under the wrong country is an ordinary correctable mistake.
- `(country, name_en)` is **not** unique — two genuinely distinct providers may share a name. No duplicate detection exists in Phase 1.
- Non-active status requires an `availability_note`.

**Errors:**
- `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400) — non-active status sent without a note
- `INSTITUTIONS_INSTITUTION_NOT_FOUND` (404) — no institution with that id

### Campus — `/api/v1/catalogue/institutions/<institution_id>/campuses/` and `/api/v1/catalogue/campuses/<campus_id>/`

**Use it when:** the campus section of the Institution Detail screen, and the campus picker on a program form.
**Methods:**
- `GET /api/v1/catalogue/institutions/<institution_id>/campuses/` — list one institution's campuses (permission: `institutions.campus.list`, risk: low)
- `POST /api/v1/catalogue/institutions/<institution_id>/campuses/` — create (permission: `institutions.campus.create`, risk: medium)
- `GET /api/v1/catalogue/campuses/<campus_id>/` — retrieve (permission: `institutions.campus.read`, risk: low)
- `PATCH /api/v1/catalogue/campuses/<campus_id>/` — update (permission: `institutions.campus.update`, risk: medium)

**Send (create/update):**
- create: `name_en` (required), `city`, `availability_status`, `availability_note`, `notes`
- update: any subset of the same fields

**Returns:** Campus for create, retrieve, and update; list[Campus] for the list, paginated.
**Requires state:** an existing `Institution`, named in the URL path.
**Side effects:** appends `catalogue_campus_created` / `catalogue_campus_updated` to the audit log.

**Notes:**
- **The list and create routes are nested under the institution; retrieve and update are not.** A campus never moves between providers, so the institution is a path segment on create and carries no information once you hold the campus id.
- `institution` is **never sent in the body** on either create or update. Sending it is ignored.
- `(institution, name_en)` **is** unique — unlike institutions, a duplicate campus name within one provider is always an error. Because `name_en` is editable, `INSTITUTIONS_CAMPUS_DUPLICATE` fires on a **rename** as well as a create, unlike `INSTITUTIONS_CODE_DUPLICATE` which is create-only.
- Query params on the list: `availability_status`, `usable_only` (bool, default false), `q` (partial match on name or city).
- Listing under an institution id that does not exist returns 404 `INSTITUTIONS_INSTITUTION_NOT_FOUND`, not an empty list.

**Errors:**
- `INSTITUTIONS_CAMPUS_DUPLICATE` (409) — this institution already has a campus with that name
- `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400) — non-active status sent without a note
- `INSTITUTIONS_INSTITUTION_NOT_FOUND` (404) — no institution with that id in the path
- `INSTITUTIONS_CAMPUS_NOT_FOUND` (404) — no campus with that id

### Program — `/api/v1/catalogue/programs/`

**Use it when:** the Program List / Detail screens, and — most importantly — the **Program Search / Shortlist** screen opened from an applicant journey.
**Methods:**
- `GET /api/v1/catalogue/programs/` — search (permission: `institutions.program.list`, risk: low)
- `POST /api/v1/catalogue/programs/` — create (permission: `institutions.program.create`, risk: medium)
- `GET /api/v1/catalogue/programs/<program_id>/` — retrieve (permission: `institutions.program.read`, risk: low)
- `PATCH /api/v1/catalogue/programs/<program_id>/` — update (permission: `institutions.program.update`, risk: high)

**Send (create/update):**
- create: `institution` (required, UUID), `title` (required), `qualification_level` (required), `field` (required, UUID), `campus`, `duration_months`, `intake_pattern`, `tuition_amount`, `tuition_currency`, `tuition_fee_period`, `tuition_is_indicative`, `tuition_notes`, `academic_requirement`, `english_requirement`, `backlog_tolerance`, `document_expectation`, `selection_notes`, `scholarship_available`, `scholarship_notes`, `availability_status`, `availability_note`, `notes`
- update: any subset of the same fields **except `institution`**, which is immutable

**Returns:** Program (detail shape) for create, retrieve, and update; list[Program (list shape)] for the search, paginated.
**Requires state:** an existing `Institution` and an existing `Field`. A `Campus`, if supplied, must belong to that institution.
**Side effects:** appends `catalogue_program_created` / `catalogue_program_updated` to the audit log, recording each changed field's previous and new value. Nothing outside this module changes — creating a program does not touch any journey.

**Notes:**
- **Search parameters:** `country`, `institution`, `campus`, `field` (all exact UUIDs), `qualification_level` (exact enum), `availability_status` (exact enum), `usable_only` (bool), `scholarship_available` (bool), `tuition_max` (decimal), `q`.
- **`q` on this endpoint searches exactly three fields:** `Program.title`, `Institution.name_en`, and `Institution.common_name`. It does **not** search `Institution.name_np`, and `Program` has no Devanagari name at all — so a Nepali-script program search matches nothing. There is also **no `tuition_min` and no range filter**; `tuition_max` is a ceiling only.
- **`usable_only` defaults to `true` on this endpoint** — the only endpoint in the module where it does. The default search returns only programs that can actually be offered, evaluated across the **whole chain**: the program, its campus (if any), its institution, **and** its country must all be `active` or `seasonal`. Pass `usable_only=false` for the maintenance view. **`Field.is_active` is deliberately *not* part of this chain** — deactivating a study field removes it from pickers but does not withdraw the programs filed under it, because a field is a filing label rather than something being offered. A program under an inactive field still appears in search.
- **`?campus=<id>` returns only programs at that campus.** Programs at the same institution with no campus set are excluded, and there is **no way to query for them** — no `campus=null` or `has_campus=false` parameter exists. Filter client-side on `campus === null`.
- Passing `availability_status` explicitly **overrides** `usable_only` entirely, and returns exactly that status.
- **`tuition_max` compares raw numbers and normalizes nothing. Read this before building a budget filter.** There is no currency parameter, and `tuition_max` accounts for neither `tuition_currency` nor `tuition_fee_period`. `tuition_max=50000` matches a program priced `"50000.00"` `JPY` as readily as one priced `"50000.00"` `AUD`, and matches a `"48000.00"` `AUD` `per_year` program whose `total_program` cost is roughly double the ceiling. It is only trustworthy when your result set is already narrowed to one country — and therefore, in practice, one currency — and even then the fee period still varies per program. Pass `country` alongside it, and render `tuition_currency` and `tuition_fee_period` on every row so the user can see what they are comparing.
- `tuition_max` **excludes programs with no recorded tuition** — an unknown fee is not a cheap one. There is **no way to list unpriced programs**: combining it with `usable_only=false` widens the availability filter but still drops every null-tuition record. Finding unpriced programs means fetching without `tuition_max` and filtering client-side on `tuition_amount === null`.
- `tuition_currency` is accepted in any case and stored upper-cased.
- **A `tuition_amount` requires both `tuition_currency` and `tuition_fee_period`.** This is checked against the *resulting* record, so a `PATCH` that clears the currency on an already-priced program fails too.
- Only `institution`, `title`, `qualification_level`, and `field` are required — an incomplete record is explicitly allowed, and can be saved as `inactive` until ready.
- `institution` is **immutable**; `campus` is editable but must belong to the program's institution. **`PATCH {"campus": null}` genuinely detaches the campus** — `null` is an accepted value here, not an ignored one. (The "immutable fields are ignored" rule in §3 covers only the four named fields; `campus` is not one of them.)
- `tuition_currency` must be exactly three ASCII letters and is stored upper-cased; anything else is a `VALIDATION_ERROR`. It is **not** checked against a real ISO 4217 list, so `"ZZZ"` is accepted. `duration_months` must be an integer between 1 and 120. `tuition_amount` must be ≥ 0.
- A program **can** be created or kept under a `Field` whose `is_active` is `false` — nothing prevents it, and such a program still appears in search.
- Ordering is by `title`. Not client-controllable.

**Errors:**
- `INSTITUTIONS_TUITION_INCOMPLETE` (400) — an amount without a currency or a fee period
- `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH` (400) — the campus belongs to a different institution
- `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400) — non-active status sent without a note
- `INSTITUTIONS_PROGRAM_NOT_FOUND` (404) — no program with that id

## 8. Flows

**Build the catalogue from empty**

1. `POST /api/v1/catalogue/countries/` with `{ "code": "au", "name_en": "Australia" }` → keep `country_id`.
2. `POST /api/v1/catalogue/fields/` with `{ "code": "information_technology", "name_en": "Information Technology" }` → keep `field_id`. Independent of step 1; either order works.
3. `POST /api/v1/catalogue/institutions/` with `{ "country": country_id, "name_en": "University of Melbourne" }` → keep `institution_id`.
   - 400 with `details.country` if `country_id` does not exist.
4. *(Optional)* `POST /api/v1/catalogue/institutions/<institution_id>/campuses/` with `{ "name_en": "Parkville" }` → keep `campus_id`.
   - 409 `INSTITUTIONS_CAMPUS_DUPLICATE` if that name is already used at this institution.
5. `POST /api/v1/catalogue/programs/` with `{ "institution": institution_id, "field": field_id, "title": "...", "qualification_level": "masters", "campus": campus_id }`.
   - 400 `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH` if `campus_id` belongs to another institution.
   - 400 `INSTITUTIONS_TUITION_INCOMPLETE` if a `tuition_amount` was sent without currency and period.

**Shortlist against an applicant journey**

1. Read the journey from `applicant_journeys` (`GET /api/v1/journeys/<journey_id>/`) and take its `study_level`, `field_of_study`, `target_country`, `budget_amount`, and `budget_currency`.
2. `GET /api/v1/catalogue/countries/?q=<target_country>` to resolve the free-text country name to a `country_id`. **This step exists because the two modules are not linked** — see §9.
   - If nothing matches, the journey names a country not in the catalogue. Proceed without the country filter rather than blocking.
3. `GET /api/v1/catalogue/fields/?q=<field_of_study>&is_active=true` to resolve the journey's free-text field of study to a `field_id`. Same reason as step 2, and the same fallback: no match means run the search without the field filter.
4. `GET /api/v1/catalogue/programs/?country=<country_id>&qualification_level=<study_level>&field=<field_id>` — the journey's `study_level` is the same enum as `qualification_level` and needs no mapping.
   - **Only add `tuition_max` when the journey's `budget_currency` matches the country's actual tuition currency**, and even then expect mixed fee periods in the results. `tuition_max` normalizes nothing (see §7); a Nepali journey's `budget_amount` in NPR compared against Australian programs priced in AUD is a meaningless filter that will silently return an empty or wrong result set. Filtering client-side after converting is the honest option.
5. Present the results. Every row's own `is_usable` is true unless `usable_only=false` was passed — but see §4 before using that field for anything beyond a badge.
6. `GET /api/v1/catalogue/programs/<program_id>/` for each candidate the counsellor compares — the list row omits the entry expectations.
7. Record the choice **on the journey**, by PATCHing its free-text `target_institution_name` and `target_program_name`. There is no endpoint in this module that attaches a program to a journey, and nothing keeps the copied text in sync afterwards.

**Withdraw a program from use**

1. `PATCH /api/v1/catalogue/programs/<program_id>/` with `{ "availability_status": "inactive", "availability_note": "Not offered from 2027 intake." }`.
   - 400 `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` if the note is omitted.
2. The program disappears from the default search but remains retrievable by id forever, so anything that referenced it still resolves.
3. To restore it, PATCH `availability_status` back to `active`. The note may be left or cleared.

**Pause an entire country**

1. `PATCH /api/v1/catalogue/countries/<country_id>/` with `{ "availability_status": "paused", "availability_note": "..." }`.
2. Every program in that country drops out of the default program search immediately — but **each program's own `availability_status` is unchanged**, and a maintenance view (`usable_only=false`) still shows them as `active`.
3. Un-pausing the country restores them all, with whatever individual statuses they had.

## 9. Gaps

- **No link to `applicant_journeys`.** This is the largest gap and it is deliberate for Phase 1. A journey's `target_country`, `target_institution_name`, and `target_program_name` are free text with no reference to these records. A client that shortlists a program must copy the strings across, and nothing guarantees they match a catalogue entry or stay in sync if the catalogue is later edited. There is **no endpoint anywhere** that associates a program with a journey.
- **No Intake resource.** `Program.intake_pattern` is unstructured free text (`"Feb / Jul"`). There are no intake dates, deadlines, per-intake statuses, or fiscal-year filters, and consequently no Bikram Sambat date handling anywhere in this module. A client cannot ask "which programs have a February 2027 intake still open."
- **No Scholarship resource.** A program carries only `scholarship_available` (bool) and `scholarship_notes` (free text). Scholarships cannot be named, valued, filtered, or attached to a country or institution.
- **Tuition is program-level only.** There is no per-campus, per-intake, or per-year tuition. If a program's fee differs by campus, the catalogue cannot express it — a separate program record is the only workaround.
- **Entry expectations are unstructured free text.** `academic_requirement`, `english_requirement`, and `backlog_tolerance` cannot be filtered or compared. "Programs accepting IELTS 6.0" is not answerable.
- **No program code.** Programs are identified only by UUID; there is no stable human-readable identifier equivalent to `Field.code` or `Country.code`, and no uniqueness constraint on `(institution, campus, title)`. Two identical programs can be created and nothing flags it.
- **No duplicate detection on institutions.** `(country, name_en)` is not unique, by design, so the same university can be entered twice.
- **No bulk import.** Every record is created one at a time; there is no CSV, feed, or scraping endpoint.
- **No history endpoint.** Audit events are written for every change, but this module exposes no route to read them — unlike `applicant_journeys`, which has `GET /api/v1/journeys/<id>/history/`. Reading catalogue history means calling the `audit` module's own list endpoint, filtering to `app_label` `institutions` plus the record's entity type and id. **Take the exact query-parameter names from `audit/docs/INTEGRATION.md`** — this contract is authoritative for the *values* below, not for the parameter names that carry them. The five `entity_type` values are `catalogue_field`, `catalogue_country`, `catalogue_institution`, `catalogue_campus`, and `catalogue_program` — all prefixed, because the audit log is shared across every app and a bare `country` would collide. The `action` values are listed per endpoint in §7.
- **No `?code=` lookup on `Country` or `Field`.** Both have a unique, immutable, human-readable `code`, but neither list endpoint filters on it — `q` searches names only. Resolving `"au"` to a country id means fetching the list and matching client-side.
- **No way to list programs with no recorded tuition**, and **`tuition_max` does not normalize currency or fee period**. See §7. A budget filter is only meaningful within a single country.
- **`is_usable` is per-record, not per-chain**, so it disagrees with search results whenever an ancestor is unavailable. See §4. It also cannot be filtered on — use `usable_only` or `availability_status`.
- **Search is substring-based, not ranked.** `q` performs a case-insensitive partial match with no relevance ordering and no fuzzy tolerance for misspellings, despite being trigram-indexed. It matches the stored strings literally, so a Devanagari `name_np` is **not** found by a romanized query, nor the reverse — searching "Australia" will not match a record whose only Nepali name is "अस्ट्रेलिया". Search each script with a query in that script.
- **No stale-reference handling for the journey copy.** Because shortlisting copies catalogue text into a journey's free-text fields, nothing detects or reconciles the case where the source program is later renamed or withdrawn. The journey keeps whatever string was copied, indefinitely, with no link back to notice the drift.
