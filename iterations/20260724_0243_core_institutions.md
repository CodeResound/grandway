# Session 20260724_0243 — core, institutions

Branch: `add_institutions_catalogue_20260724_0243`

## Institutions

### 1. Module

- **Name:** Institutions — the study-opportunity catalogue (Phase 1: catalogue spine).
- **Base path:** `/api/v1/catalogue/` — differs from the app name deliberately; the module owns five resources.
- **Auth:** Bearer access JWT on every endpoint. Reads: `admin` and `lead_manager`. Writes: `admin` only. `superadmin` denied everywhere, reads included.

### 2. Conventions

- **Response:** standard project envelope — `success`, `message`, `data`, `meta`.
- **Error:** `success: false` with `error.code`, `error.message`, `error.details`. Field-level failures use `VALIDATION_ERROR` with the offending fields in `details`.
- **Auth failures:** 401 for missing, expired, or revoked token. 403 `INSTITUTIONS_ACTOR_FORBIDDEN` for a valid token whose authority may not act — this module's code replaces the project-wide `PERMISSION_DENIED` and never coexists with it.
- **Status codes:** `POST` 201, `GET`/`PATCH` 200, domain violations 400, duplicates 409, missing records 404, authority failures 403, unrouted methods 405 with `METHOD_NOT_ALLOWED` inside the envelope.
- **Pagination:** page-number based, `page` and `page_size`, default 20, max 100 (clamped, not rejected). `meta` carries `count`, `page`, `page_size`, `next`, `previous`. Applied to every list endpoint.
- **IDs:** UUID strings. `Field.code` and `Country.code` are separate human-readable ASCII identifiers, unique and immutable, never the primary key.
- **Times:** ISO 8601 UTC. **No field in this module carries a `_bs` Bikram Sambat sibling** — the only dates are `created_at`/`updated_at`, which are system timestamps and exempt.
- **List/search/filter/order params:** documented per endpoint in §6. No client-controllable ordering anywhere — no `sort` or `ordering` parameter exists. Invalid query parameters are rejected with 400, never ignored.

### 3. Models

**Field** — `{ id, code, name_en, name_np, is_active, display_order, created_at, updated_at }`

- Uses `is_active`, not `availability_status` — a pure reference table cannot be seasonal.

**Country** — `{ id, code, name_en, name_np, availability_status:[enum], availability_note, is_usable, notes, display_order, created_at, updated_at }`

- `is_usable` is read-only and derived from **that record's own** status only.

**CountryBrief** — `{ id, code, name_en, availability_status:[enum] }`

**Institution** — `{ id, country:CountryBrief, name_en, name_np, common_name, institution_type:[enum], availability_status:[enum], availability_note, is_usable, notes, created_at, updated_at }`

- `country` is a nested object on read, a bare UUID on write.

**InstitutionBrief** — `{ id, name_en, common_name, availability_status:[enum] }`

**Campus** — `{ id, institution:InstitutionBrief, name_en, city, availability_status:[enum], availability_note, is_usable, notes, created_at, updated_at }`

- No `name_np` — campus names are localities in the destination country.

**CampusBrief** — `{ id, name_en, city, availability_status:[enum] }`

**FieldBrief** — `{ id, code, name_en }`

**Program (list shape)** — `{ id, title, institution:InstitutionBrief, campus?:CampusBrief, country:CountryBrief, qualification_level:[enum], field:FieldBrief, duration_months?, intake_pattern, tuition_amount?, tuition_currency, tuition_fee_period:[enum], tuition_is_indicative, scholarship_available, availability_status:[enum], availability_note, is_usable, created_at, updated_at }`

- `country` is derived from the institution and read-only. `tuition_amount` is a decimal string or `null`. Empty text fields are `""`, never `null`.

**Program (detail shape)** — the list shape plus `{ tuition_notes, academic_requirement, english_requirement, backlog_tolerance, document_expectation, selection_notes, scholarship_notes, notes }`

- Returned by retrieve, create, and update. Only the list returns the shorter shape.

### 4. Enums

- `availability_status` (Country, Institution, Campus, Program): `active` | `paused` | `seasonal` | `inactive`
- Usable statuses (what `is_usable` is true for, and what the default program search includes): `active` | `seasonal`
- `Institution.institution_type`: `university` | `college` | `polytechnic` | `language_school` | `other`
- `Program.qualification_level`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other` — the same set as `applicant_journeys` `Journey.study_level`, so a journey's level passes straight into the program search
- `Program.tuition_fee_period`: `per_year` | `per_semester` | `total_program` | `""`
- `Field.code`, `Country.code`: not enums — ASCII identifiers matching `^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$`
- `Program.intake_pattern`: not an enum — free text in Phase 1

### 5. Dependency order

- `Institution` needs `Country`.
- `Campus` needs `Institution` — supplied in the URL path, never the body.
- `Program` needs `Institution` and `Field`; `Campus` is optional and must belong to the same institution.
- `Field` and `Country` need nothing.

**Start here:** `Country` and `Field` (independent of each other), then `Institution`, then optionally `Campus`, then `Program`.

### 6. Endpoints

### Study Field — `/api/v1/catalogue/fields/`

**Use it when:** the Reference Maintenance screen, and populating the field filter on the program search.
**Methods:**
- `GET /api/v1/catalogue/fields/` (`institutions.field.list`)
- `POST /api/v1/catalogue/fields/` (`institutions.field.create`)
- `GET /api/v1/catalogue/fields/<field_id>/` (`institutions.field.read`)
- `PATCH /api/v1/catalogue/fields/<field_id>/` (`institutions.field.update`)

**Send (create/update):**
- create: `code` (required), `name_en` (required), `name_np`, `is_active`, `display_order`
- update: any subset of `name_en`, `name_np`, `is_active`, `display_order` — not `code`

**Returns:** Field | list[Field]
**Notes:**
- Query params: `is_active` (omitting it returns both), `q`.
- `code` is immutable; sending it on update is ignored.
- Writes are Admin-only.

**Errors:**
- `INSTITUTIONS_CODE_DUPLICATE` (409) — that code is taken
- `INSTITUTIONS_FIELD_NOT_FOUND` (404) — no field with that id

### Country — `/api/v1/catalogue/countries/`

**Use it when:** the Country List / Detail screens, and resolving a journey's free-text country name to an id.
**Methods:**
- `GET /api/v1/catalogue/countries/` (`institutions.country.list`)
- `POST /api/v1/catalogue/countries/` (`institutions.country.create`)
- `GET /api/v1/catalogue/countries/<country_id>/` (`institutions.country.read`)
- `PATCH /api/v1/catalogue/countries/<country_id>/` (`institutions.country.update`)

**Send (create/update):**
- create: `code` (required), `name_en` (required), `name_np`, `availability_status`, `availability_note`, `notes`, `display_order`
- update: any subset of the same except `code`

**Returns:** Country | list[Country]
**Notes:**
- Query params: `availability_status`, `usable_only` (default false here), `q`.
- Setting a non-`active` status requires a non-empty `availability_note` in the same request; a stored note does not satisfy it.
- Availability does not cascade to institutions or programs.
- `name_np` optional, `name_en` required — the inverse of the convention in `leads` and `applicants`.

**Errors:**
- `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400) — non-active status with no note
- `INSTITUTIONS_CODE_DUPLICATE` (409) — that code is taken
- `INSTITUTIONS_COUNTRY_NOT_FOUND` (404) — no country with that id

### Institution — `/api/v1/catalogue/institutions/`

**Use it when:** the Institution List / Detail screens, and the provider filter on the program search.
**Methods:**
- `GET /api/v1/catalogue/institutions/` (`institutions.institution.list`)
- `POST /api/v1/catalogue/institutions/` (`institutions.institution.create`)
- `GET /api/v1/catalogue/institutions/<institution_id>/` (`institutions.institution.read`)
- `PATCH /api/v1/catalogue/institutions/<institution_id>/` (`institutions.institution.update`)

**Send (create/update):**
- create: `country` (required, UUID), `name_en` (required), `name_np`, `common_name`, `institution_type`, `availability_status`, `availability_note`, `notes`
- update: any subset of the same, including `country`

**Returns:** Institution | list[Institution]
**Notes:**
- Query params: `country`, `institution_type`, `availability_status`, `usable_only` (default false), `q` (matches `name_en`, `name_np`, `common_name`).
- `country` is editable — a provider filed under the wrong country is a correctable mistake.
- Changing `country` rewrites the derived `country` on every program under the institution.
- `(country, name_en)` is not unique; duplicate provider names are allowed.

**Errors:**
- `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400) — non-active status with no note
- `INSTITUTIONS_INSTITUTION_NOT_FOUND` (404) — no institution with that id

### Campus — `/api/v1/catalogue/institutions/<institution_id>/campuses/` and `/api/v1/catalogue/campuses/<campus_id>/`

**Use it when:** the campus panel on Institution Detail, and the campus picker on a program form.
**Methods:**
- `GET /api/v1/catalogue/institutions/<institution_id>/campuses/` (`institutions.campus.list`)
- `POST /api/v1/catalogue/institutions/<institution_id>/campuses/` (`institutions.campus.create`)
- `GET /api/v1/catalogue/campuses/<campus_id>/` (`institutions.campus.read`)
- `PATCH /api/v1/catalogue/campuses/<campus_id>/` (`institutions.campus.update`)

**Send (create/update):**
- create: `name_en` (required), `city`, `availability_status`, `availability_note`, `notes`
- update: any subset of the same

**Returns:** Campus | list[Campus]
**Notes:**
- List and create are nested under the institution; retrieve and update are not.
- `institution` is never sent in the body and is immutable.
- `(institution, name_en)` is unique; the duplicate error fires on rename as well as create.
- An unknown `<institution_id>` returns 404, not an empty list.
- Query params on the list: `availability_status`, `usable_only` (default false), `q`.

**Errors:**
- `INSTITUTIONS_CAMPUS_DUPLICATE` (409) — that name is taken at this institution
- `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400) — non-active status with no note
- `INSTITUTIONS_INSTITUTION_NOT_FOUND` (404) — no institution with that id in the path
- `INSTITUTIONS_CAMPUS_NOT_FOUND` (404) — no campus with that id

### Program — `/api/v1/catalogue/programs/`

**Use it when:** the Program List / Detail screens, and the Program Search / Shortlist screen opened from an applicant journey.
**Methods:**
- `GET /api/v1/catalogue/programs/` (`institutions.program.list`)
- `POST /api/v1/catalogue/programs/` (`institutions.program.create`)
- `GET /api/v1/catalogue/programs/<program_id>/` (`institutions.program.read`)
- `PATCH /api/v1/catalogue/programs/<program_id>/` (`institutions.program.update`)

**Send (create/update):**
- create: `institution` (required), `title` (required), `qualification_level` (required), `field` (required), `campus`, `duration_months`, `intake_pattern`, `tuition_amount`, `tuition_currency`, `tuition_fee_period`, `tuition_is_indicative`, `tuition_notes`, `academic_requirement`, `english_requirement`, `backlog_tolerance`, `document_expectation`, `selection_notes`, `scholarship_available`, `scholarship_notes`, `availability_status`, `availability_note`, `notes`
- update: any subset of the same except `institution`

**Returns:** Program (detail shape) | list[Program (list shape)]
**Notes:**
- Search params: `country`, `institution`, `campus`, `field`, `qualification_level`, `availability_status`, `usable_only`, `scholarship_available`, `tuition_max`, `q`.
- `usable_only` defaults to **true** here and nowhere else, and evaluates the whole chain: program, campus, institution, and country must all be usable.
- Passing `availability_status` explicitly overrides `usable_only`.
- `tuition_max` normalizes neither currency nor fee period, and excludes programs with no recorded tuition.
- `q` searches `Program.title`, `Institution.name_en`, and `Institution.common_name` only.
- `Field.is_active` is not part of the usability chain.
- A tuition amount requires both a currency and a fee period, checked against the resulting record.
- `institution` is immutable; `campus` must belong to it; `PATCH {"campus": null}` detaches.
- Only `institution`, `title`, `qualification_level`, and `field` are required.

**Errors:**
- `INSTITUTIONS_TUITION_INCOMPLETE` (400) — amount without currency or fee period
- `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH` (400) — campus belongs to another institution
- `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400) — non-active status with no note
- `INSTITUTIONS_PROGRAM_NOT_FOUND` (404) — no program with that id

### 7. Flows

**Build the catalogue from empty**

1. `POST /api/v1/catalogue/countries/` → keep `country_id`.
2. `POST /api/v1/catalogue/fields/` → keep `field_id`. Independent of step 1.
3. `POST /api/v1/catalogue/institutions/` with `country_id` → keep `institution_id`.
   - 400 `VALIDATION_ERROR` with `details.country` if the id does not exist.
4. Optionally `POST /api/v1/catalogue/institutions/<institution_id>/campuses/` → keep `campus_id`.
   - 409 `INSTITUTIONS_CAMPUS_DUPLICATE` if that name is taken at this institution.
5. `POST /api/v1/catalogue/programs/` with `institution_id`, `field_id`, and optionally `campus_id`.
   - 400 `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH` if the campus is another institution's.
   - 400 `INSTITUTIONS_TUITION_INCOMPLETE` if an amount was sent without currency and period.

**Shortlist against an applicant journey**

1. `GET /api/v1/journeys/<journey_id>/` — take `study_level`, `field_of_study`, `target_country`, `budget_amount`, `budget_currency`.
2. `GET /api/v1/catalogue/countries/?q=<target_country>` to resolve the free-text country to an id.
   - No match: proceed without the country filter rather than blocking.
3. `GET /api/v1/catalogue/fields/?q=<field_of_study>&is_active=true` to resolve the field.
   - No match: proceed without the field filter.
4. `GET /api/v1/catalogue/programs/?country=&qualification_level=&field=` — `study_level` maps directly onto `qualification_level`.
   - Only add `tuition_max` when the journey's currency matches the tuition currency; the filter normalizes nothing.
5. `GET /api/v1/catalogue/programs/<program_id>/` for the comparison panel.
6. `PATCH /api/v1/journeys/<journey_id>/` writing the chosen names into `target_institution_name` and `target_program_name`. No endpoint links a journey to a catalogue record.

**Withdraw a record from use**

1. `PATCH` the record with `availability_status: "inactive"` and a non-empty `availability_note`.
   - 400 `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` if the note is omitted.
2. The record leaves the default search but stays retrievable by id permanently.
3. `PATCH` back to `active` to restore. Children keep their own statuses throughout.

**Pause a whole country**

1. `PATCH /api/v1/catalogue/countries/<country_id>/` with `availability_status: "paused"` and a note.
2. Every program in that country drops out of the default program search, while each program's own `availability_status` stays unchanged and its own `is_usable` stays `true`.
3. Un-pausing restores them all at whatever individual statuses they held.

### 8. Gaps

- No link to `applicant_journeys`. A journey's destination remains free text; the client copies catalogue strings across, and nothing keeps them in sync or detects a later rename or withdrawal.
- No Intake resource. `intake_pattern` is unstructured free text — no dates, deadlines, per-intake statuses, or fiscal-year filters, and therefore no Bikram Sambat handling anywhere in this module.
- No Scholarship resource. Only a boolean and a free-text note on the program.
- Tuition is program-level only — no per-campus, per-intake, or per-year rows.
- `tuition_max` normalizes neither currency nor fee period, and there is no currency filter, no `tuition_min`, and no way to list unpriced programs.
- Entry expectations are unstructured free text and cannot be filtered or compared.
- No program code and no uniqueness constraint on `(institution, campus, title)`.
- No duplicate detection on institutions — `(country, name_en)` is deliberately not unique.
- No bulk import, feed, or scraping endpoint.
- No history endpoint. Audit events are written but read only through the `audit` module, using `entity_type` values `catalogue_field`, `catalogue_country`, `catalogue_institution`, `catalogue_campus`, `catalogue_program`.
- `is_usable` is per-record, not chain-aware, so it disagrees with search results whenever an ancestor is unavailable. It also cannot be filtered on.
- `q` is a substring match with no ranking and no cross-script matching — a romanized query never matches a Devanagari `name_np`, and program search does not cover `name_np` at all.
- No `?code=` lookup on `Country` or `Field` despite both codes being unique and immutable.

## Core

### 1. Module

- **Name:** core — global infrastructure. No new endpoints this session.
- **Base path:** n/a.
- **Auth:** unchanged.

### 2. Conventions

Unchanged. The global error-code list in `core/docs/INTEGRATION.md` §3 was completed with `METHOD_NOT_ALLOWED` (405) and `RATE_LIMIT_EXCEEDED` (429), which were already emitted by the global exception handler but undocumented.

### 3. Models

No model changes. `core/models.py` still contains abstract base models only.

### 4. Enums

No changes. `core.constants.StudyLevel` is now consumed by a third app (`institutions.Program.qualification_level`) but its values are unchanged.

### 5. Dependency order

Unchanged.

### 6. Endpoints

**No endpoint changes this session.** `core/api_urls.py` gained one `include` mounting the new app at `/api/v1/catalogue/`; no route owned by `core` was added, changed, or retired.

### 7. Flows

No flow changes owned by `core`.

### 8. Gaps

- The project-level `core/docs/INTEGRATION.md` change history had no rows for `audit`, `leads`, `applicants`, or `applicant_journeys`, all of which had entered its inventory and dependency graph in earlier sessions. Backfilled in one row this session rather than reconstructed per-app.
- `CLAUDE.md` §9 states that a `permissions` app exists with `check_permission()`/`explain_permission()`. No such app exists in `backend/` or `INSTALLED_APPS`. Every app, including this one, uses the interim inline `authority_type` pattern. Flagged, not changed — amending the rulebook was outside this session's scope.
