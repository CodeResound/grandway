# API — Institutions

**Owner app:** `institutions`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24
**Base prefix:** `/api/v1/catalogue/`
**Auth:** Bearer access JWT (`authenticate.SessionBoundJWTAuthentication`) on every endpoint
**Throttle:** project defaults only — `UserRateThrottle` at 1000/hour. No endpoint here is public or expensive enough to warrant a scoped throttle; the search is index-backed and paginated at 100 rows max.
**Access level:** protected. Reads: Admin + Lead Manager. Writes: **Admin only**. Superadmin denied on every route including reads.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial API documentation — 20 endpoints across five resources |

---

## Access model (§9 interim inline pattern)

This app uses the interim inline access checks in `institutions/access.py`. There is no `permissions.py`.

| Check | Applies to | Allows | Denies |
|-------|-----------|--------|--------|
| `require_catalogue_reader` | every `GET` | `admin`, `lead_manager` | `superadmin` → 403 `INSTITUTIONS_ACTOR_FORBIDDEN` |
| `require_admin` | every `POST` and `PATCH` | `admin` | `lead_manager`, `superadmin` → 403 `INSTITUTIONS_ACTOR_FORBIDDEN` |

The split is documented in full in `docs/SECURITY.md` §1. **No endpoint in this app is public.**

**No `DELETE` method is exposed on any resource.** Withdrawal from use is a `PATCH` setting `availability_status` to `inactive` — see `DATA_CONTRACT.md` "Soft Delete".

---

## Error codes

All codes live in `institutions/constants.py` `ErrorCode`.

| Code | HTTP | Meaning |
|------|------|---------|
| `INSTITUTIONS_ACTOR_FORBIDDEN` | 403 | The caller's authority may not perform this action |
| `INSTITUTIONS_FIELD_NOT_FOUND` | 404 | No study field with that id |
| `INSTITUTIONS_COUNTRY_NOT_FOUND` | 404 | No country with that id |
| `INSTITUTIONS_INSTITUTION_NOT_FOUND` | 404 | No institution with that id |
| `INSTITUTIONS_CAMPUS_NOT_FOUND` | 404 | No campus with that id |
| `INSTITUTIONS_PROGRAM_NOT_FOUND` | 404 | No program with that id |
| `INSTITUTIONS_CODE_DUPLICATE` | 409 | A field or country already uses that `code` |
| `INSTITUTIONS_CAMPUS_DUPLICATE` | 409 | The institution already has a campus with that name |
| `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` | 400 | A non-active `availability_status` was set with no `availability_note` |
| `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH` | 400 | The chosen campus belongs to a different institution |
| `INSTITUTIONS_TUITION_INCOMPLETE` | 400 | A `tuition_amount` was recorded without a currency or fee period |

Field-level serializer failures use the project-wide `VALIDATION_ERROR` (400) with the offending fields in `error.details`. This includes a referenced UUID that does not exist (`country`, `institution`, `field`, `campus` in a request **body**) and a malformed `code`. A 404 is only ever about the record named in the URL **path**.

`INSTITUTIONS_ACTOR_FORBIDDEN` (403) is returned by **every** endpoint and is omitted from the per-endpoint error lists below only where noted. Its `message` is `"Admin authority is required to maintain the catalogue."` for a Lead Manager write and `"This authority may not access catalogue records."` for a Superadmin read. Clients branch on `code`, never `message`.

Unrouted methods — `DELETE` or `PUT` anywhere, `POST` on `/campuses/<id>/` — return 405 with DRF's `METHOD_NOT_ALLOWED`, not a module code.

**Module-wide response rules**, applying to all five resources:

- `POST` → 201; `GET` and `PATCH` → 200.
- **Immutable fields are silently ignored on update, never rejected** (`Field.code`, `Country.code`, `Campus.institution`, `Program.institution`) — so a read-modify-write client needs no field-stripping.
- **A `PATCH` that changes nothing writes no audit event** and still returns 200 with the unchanged record.
- Ordering is fixed and not client-controllable: `Field`/`Country` by `display_order` then `name_en`; `Institution`/`Campus` by `name_en`; `Program` by `title`.

**Why duplicates are 409 rather than DRF's default 400.** `Field.code` and `Country.code` are declared explicitly on their create serializers so DRF's automatic `UniqueValidator` does not apply, letting the database's `IntegrityError` surface as a 409. This is deliberate: the campus duplicate is a composite `UniqueConstraint` that DRF **cannot** validate automatically (the parent institution comes from the URL, not the body), so it must be a 409 either way. Reporting the two the same way means a consumer handles "already exists" once.

---

## 1. Study Field

The admin-managed study-area reference table. Read by every program filter.

### 1.1 List study fields

- **URI:** `GET /api/v1/catalogue/fields/`
- **Permission key:** `institutions.field.list` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Query params:** `is_active` (bool — **omitting it returns both** active and inactive), `q` (partial match on `name_en` or `name_np`), `page`, `page_size`
- **Response:** paginated `list[Field]` — see `DATA_CONTRACT.md` §1
- **Business rules:** ordered by `display_order`, then `name_en`. Not client-orderable.
- **Errors:** `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

**AI debugging notes:** `is_active` uses `OptionalBooleanField`, not DRF's `BooleanField`. DRF's implements HTML-checkbox semantics — a key absent from a QueryDict yields `False`, which would silently filter this list to *inactive* fields only. The custom field yields `None` when absent, which `filter_fields` reads as "do not filter." Any new boolean filter parameter in this app must use `OptionalBooleanField` unless a `False` default is genuinely intended.

### 1.2 Create study field

- **URI:** `POST /api/v1/catalogue/fields/`
- **Permission key:** `institutions.field.create` (risk: medium)
- **Auth:** required. **Admin only.**
- **Request:** `code` (required), `name_en` (required), `name_np`, `is_active`, `display_order`

```json
{ "code": "information_technology", "name_en": "Information Technology", "name_np": "सूचना प्रविधि", "display_order": 10 }
```

- **Response:** `201` with `Field`
- **Validation rules:** `code` must match `^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$` (ASCII only, §39.7). `name_en` required. All text Unicode-normalized (§39.2).
- **Errors:** `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_CODE_DUPLICATE` (409), `VALIDATION_ERROR` (400)

### 1.3 Retrieve study field

- **URI:** `GET /api/v1/catalogue/fields/<field_id>/`
- **Permission key:** `institutions.field.read` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Response:** `Field`
- **Errors:** `INSTITUTIONS_FIELD_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

### 1.4 Update study field

- **URI:** `PATCH /api/v1/catalogue/fields/<field_id>/`
- **Permission key:** `institutions.field.update` (risk: medium)
- **Auth:** required. **Admin only.**
- **Request:** any subset of `name_en`, `name_np`, `is_active`, `display_order`
- **Response:** `Field`
- **Business rules:** `code` is **immutable** — it is absent from the update serializer, so sending it is ignored rather than rejected. A `PATCH` that changes nothing writes no audit event.
- **Errors:** `INSTITUTIONS_FIELD_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400)

---

## 2. Country

### 2.1 List countries

- **URI:** `GET /api/v1/catalogue/countries/`
- **Permission key:** `institutions.country.list` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Query params:** `availability_status` (exact enum), `usable_only` (bool, **default false**), `q`, `page`, `page_size`
- **Response:** paginated `list[Country]` — see `DATA_CONTRACT.md` §2
- **Business rules:** `usable_only` defaults to false here because this backs a maintenance screen, which must show withdrawn records. Only the program search defaults it to true.
- **Errors:** `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

### 2.2 Create country

- **URI:** `POST /api/v1/catalogue/countries/`
- **Permission key:** `institutions.country.create` (risk: medium)
- **Auth:** required. **Admin only.**
- **Request:** `code` (required), `name_en` (required), `name_np`, `availability_status`, `availability_note`, `notes`, `display_order`

```json
{ "code": "au", "name_en": "Australia", "name_np": "अस्ट्रेलिया", "notes": "Genuine Student requirement applies from 2024 intakes." }
```

- **Response:** `201` with `Country`
- **Validation rules:** as `DATA_CONTRACT.md` §2. A non-`active` `availability_status` requires a non-empty `availability_note`.
- **Errors:** `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_CODE_DUPLICATE` (409), `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400), `VALIDATION_ERROR` (400)

### 2.3 Retrieve country

- **URI:** `GET /api/v1/catalogue/countries/<country_id>/`
- **Permission key:** `institutions.country.read` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Response:** `Country`
- **Errors:** `INSTITUTIONS_COUNTRY_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

### 2.4 Update country

- **URI:** `PATCH /api/v1/catalogue/countries/<country_id>/`
- **Permission key:** `institutions.country.update` (risk: **high**)
- **Auth:** required. **Admin only.**
- **Request:** any subset of `name_en`, `name_np`, `availability_status`, `availability_note`, `notes`, `display_order`

```json
{ "availability_status": "paused", "availability_note": "Partner agreement under review until October." }
```

- **Response:** `Country`
- **Business rules:**
  - `code` is immutable.
  - The availability rule is checked against the **resulting** state, not the incoming patch: sending `availability_status` alone fails even when a note is already stored, because the pairing must be re-affirmed by whoever makes the change.
  - **Availability does not cascade.** Pausing a country leaves every institution and program beneath it with its own status untouched. They drop out of the default program search while the country is unusable, and reappear unchanged when it is restored. Cascading would overwrite each child's recorded state irreversibly.
  - Risk is `high` because one edit silently changes what every Lead Manager can offer.
- **Errors:** `INSTITUTIONS_COUNTRY_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400), `VALIDATION_ERROR` (400)

---

## 3. Institution

### 3.1 List institutions

- **URI:** `GET /api/v1/catalogue/institutions/`
- **Permission key:** `institutions.institution.list` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Query params:** `country` (exact id), `institution_type` (exact enum), `availability_status` (exact enum), `usable_only` (bool, default false), `q`, `page`, `page_size`
- **Response:** paginated `list[Institution]` — see `DATA_CONTRACT.md` §3
- **Query access pattern:** `get_institutions()` applies `select_related("country")`; every row renders its country without an extra query. `q` searches `name_en`, `name_np`, and `common_name` with `icontains`, served by the `institution_name_en_trgm_idx` / `institution_name_np_trgm_idx` GIN trigram indexes (§39.6). `?country=&availability_status=` is served by `institution_country_status_idx`.
- **Errors:** `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

### 3.2 Create institution

- **URI:** `POST /api/v1/catalogue/institutions/`
- **Permission key:** `institutions.institution.create` (risk: medium)
- **Auth:** required. **Admin only.**
- **Request:** `country` (required, UUID), `name_en` (required), `name_np`, `common_name`, `institution_type`, `availability_status`, `availability_note`, `notes`

```json
{ "country": "1c2b3a49-5d6e-4f70-8a91-b2c3d4e5f607", "name_en": "University of Melbourne", "common_name": "Unimelb", "institution_type": "university" }
```

- **Response:** `201` with `Institution` (`country` nested as a brief object)
- **Business rules:** `(country, name_en)` is deliberately **not** unique — two distinct providers may legitimately share a name, and blocking the second creates a worse problem than the duplicate.
- **Errors:** `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400), `VALIDATION_ERROR` (400 — includes an unknown `country` id)

### 3.3 Retrieve institution

- **URI:** `GET /api/v1/catalogue/institutions/<institution_id>/`
- **Permission key:** `institutions.institution.read` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Response:** `Institution`
- **Errors:** `INSTITUTIONS_INSTITUTION_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

### 3.4 Update institution

- **URI:** `PATCH /api/v1/catalogue/institutions/<institution_id>/`
- **Permission key:** `institutions.institution.update` (risk: **high**)
- **Auth:** required. **Admin only.**
- **Request:** any subset of the create fields, **including `country`**
- **Response:** `Institution`
- **Business rules:** unlike the immutable parents elsewhere in this app, `country` **is** editable — an institution filed under the wrong country is an ordinary correctable mistake, and the change is audited with its previous value.
- **Errors:** `INSTITUTIONS_INSTITUTION_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400), `VALIDATION_ERROR` (400)

---

## 4. Campus

Nested under its institution for list and create; addressed directly for retrieve and update.

### 4.1 List an institution's campuses

- **URI:** `GET /api/v1/catalogue/institutions/<institution_id>/campuses/`
- **Permission key:** `institutions.campus.list` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Query params:** `availability_status`, `usable_only` (bool, default false), `q` (name or city), `page`, `page_size`
- **Response:** paginated `list[Campus]` — see `DATA_CONTRACT.md` §4
- **Business rules:** an unknown `institution_id` returns 404, **not** an empty list — the distinction between "this provider has no campuses" and "this provider does not exist" matters to the caller.
- **Query access pattern:** `get_campuses()` applies `select_related("institution")`; `?availability_status=` under an institution is served by `campus_institution_status_idx`.
- **Errors:** `INSTITUTIONS_INSTITUTION_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

### 4.2 Create campus

- **URI:** `POST /api/v1/catalogue/institutions/<institution_id>/campuses/`
- **Permission key:** `institutions.campus.create` (risk: medium)
- **Auth:** required. **Admin only.**
- **Request:** `name_en` (required), `city`, `availability_status`, `availability_note`, `notes`

```json
{ "name_en": "Parkville", "city": "Melbourne" }
```

- **Response:** `201` with `Campus`
- **Business rules:**
  - **The institution comes from the URL, never the body.** A campus is created under a provider and never moves between providers, so putting the parent in the body would imply a mutability that does not exist.
  - `(institution, name_en)` **is** unique — unlike institutions, a duplicate campus name within one provider is always an error.
  - `Campus` has no `name_np`: campus names are localities in the destination country and are not written in Devanagari in practice.
- **Errors:** `INSTITUTIONS_INSTITUTION_NOT_FOUND` (404), `INSTITUTIONS_CAMPUS_DUPLICATE` (409), `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400), `VALIDATION_ERROR` (400)

### 4.3 Retrieve campus

- **URI:** `GET /api/v1/catalogue/campuses/<campus_id>/`
- **Permission key:** `institutions.campus.read` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Response:** `Campus`
- **Business rules:** not nested under the institution, because the institution is immutable and so the nesting would carry no information the campus id does not already imply.
- **Errors:** `INSTITUTIONS_CAMPUS_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

### 4.4 Update campus

- **URI:** `PATCH /api/v1/catalogue/campuses/<campus_id>/`
- **Permission key:** `institutions.campus.update` (risk: medium)
- **Auth:** required. **Admin only.**
- **Request:** any subset of `name_en`, `city`, `availability_status`, `availability_note`, `notes`
- **Response:** `Campus`
- **Business rules:** `institution` is **immutable** and absent from the update serializer.
- **Errors:** `INSTITUTIONS_CAMPUS_NOT_FOUND` (404), `INSTITUTIONS_CAMPUS_DUPLICATE` (409), `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400), `VALIDATION_ERROR` (400)

---

## 5. Program

The main operational resource. Its list endpoint **is** the concept's "Program Search / Shortlist" screen.

### 5.1 Search programs

- **URI:** `GET /api/v1/catalogue/programs/`
- **Permission key:** `institutions.program.list` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Query params:** `country`, `institution`, `campus`, `field` (exact UUIDs), `qualification_level` (exact enum), `availability_status` (exact enum), `usable_only` (bool, **default true**), `scholarship_available` (bool), `tuition_max` (decimal), `q`, `page`, `page_size`
- **Response:** paginated `list[Program (list shape)]` — see `DATA_CONTRACT.md` §5. Entry-expectation fields are omitted from list rows and available on retrieve.
- **Business rules:**
  - **`usable_only` defaults to `true` here and nowhere else.** The concept requires inactive items be hidden from active selection workflows, and a search that silently offers a withdrawn program is worse than one returning nothing.
  - Usability is evaluated **across the whole chain**: the program, its campus (when set), its institution, **and** its country must all be `active` or `seasonal`. This is why availability never cascades on write — the read path composes it instead, so restoring a paused country restores its programs at whatever status each one actually holds.
  - Passing `availability_status` explicitly **overrides** `usable_only` entirely.
  - `tuition_max` **excludes programs with no recorded tuition.** An unknown fee is not a cheap one; showing unpriced programs under a budget ceiling would misrepresent them. There is consequently no way to *list* unpriced programs through this filter — that requires fetching without it and filtering client-side.
  - **`tuition_max` normalizes neither currency nor fee period** — it compares `tuition_amount` as a raw number. `tuition_max=50000` matches `"50000.00" JPY` as readily as `"50000.00" AUD`, and matches a `per_year` price whose `total_program` cost is far higher. This is a **known limitation, documented in `INTEGRATION.md` §9**, not an oversight: normalizing would require an exchange-rate source and a canonical fee period, both of which are Phase 2 decisions. Constrain by `country` alongside it.
  - **`Field.is_active` is not part of the usability chain.** Deactivating a study field removes it from pickers but does not withdraw the programs filed under it — a field is a filing label, not something being offered.
  - `?campus=<id>` returns only programs at that campus; programs with no campus are excluded and cannot be queried for directly.
  - Invalid parameters are **rejected with 400, not ignored** — silently dropping `?tuition_max=cheap` would return the entire catalogue as though it were a result set.
  - Ordered by `title`. Not client-orderable.
- **Query access pattern:** `get_programs()` applies `select_related("institution", "institution__country", "campus", "field")` — four joins, because each list row renders all four. Verified non-scaling by `tests/test_views.py::TestProgramListQueryCount`, which asserts the query count is identical for 2 and 10 rows. `?qualification_level=&usable_only=` is served by `program_level_status_idx`; `?field=` by `program_field_status_idx`; `?institution=` by `program_institution_status_idx`; `q` by the `program_title_trgm_idx` GIN trigram index plus the institution-name indexes.
- **Errors:** `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400)

**AI debugging notes:** `scholarship_available` uses `OptionalBooleanField` for the reason given in §1.1 — with DRF's stock `BooleanField` an omitted parameter yielded `False` and the default search silently excluded **every** scholarship-bearing program. That defect was caught by `TestProgramSearch`, not by review.

### 5.2 Create program

- **URI:** `POST /api/v1/catalogue/programs/`
- **Permission key:** `institutions.program.create` (risk: medium)
- **Auth:** required. **Admin only.**
- **Request:** `institution` (required, UUID), `title` (required), `qualification_level` (required), `field` (required, UUID), plus optional `campus`, `duration_months`, `intake_pattern`, the five tuition fields, the five entry-expectation fields, `scholarship_available`, `scholarship_notes`, `availability_status`, `availability_note`, `notes`

```json
{
  "institution": "2d3e4f50-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
  "campus": "3e4f5061-7b8c-4d9e-af01-2b3c4d5e6f70",
  "field": "8f1d9e2a-4c3b-4a71-9f0e-2b6c5d8e1a34",
  "title": "Master of Information Technology",
  "qualification_level": "masters",
  "duration_months": 24,
  "intake_pattern": "Feb / Jul",
  "tuition_amount": "49824.00",
  "tuition_currency": "AUD",
  "tuition_fee_period": "total_program",
  "tuition_is_indicative": true,
  "english_requirement": "IELTS 6.5 overall, no band below 6.0."
}
```

- **Response:** `201` with `Program (detail shape)`
- **Validation rules:**
  - Only `institution`, `title`, `qualification_level`, and `field` are required. An incomplete record is explicitly permitted by the concept and may be saved as `inactive` until ready.
  - **`campus`, when given, must belong to `institution`** → `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH`. Both FKs resolve individually, so nothing else catches this; unchecked it would silently place a program at a site that does not host it.
  - **A `tuition_amount` requires both `tuition_currency` and `tuition_fee_period`** → `INSTITUTIONS_TUITION_INCOMPLETE`. An amount alone is unusable in counselling.
  - `tuition_amount` ≥ 0. `tuition_currency` accepted in any case, stored upper-cased.
  - `duration_months` between 1 and 120.
  - `qualification_level` must be a `core.constants.StudyLevel` value — the same set as `applicant_journeys` `Journey.study_level`.
- **Errors:** `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH` (400), `INSTITUTIONS_TUITION_INCOMPLETE` (400), `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400), `VALIDATION_ERROR` (400)

**AI debugging notes:** `tuition_currency` clears its model validators via `CURRENCY_FIELD_KWARGS` in each write serializer's `extra_kwargs`. The model's `validate_currency_code` regex is uppercase-only and, left in place, runs *before* `validate_tuition_currency` and rejects `"aud"` before it can be normalized. Declaring the field on `ProgramWriteMixin` does **not** work — DRF's `SerializerMetaclass` collects declared fields only from bases that are themselves serializers, so a field on a plain mixin is silently dropped. The model keeps the strict validator so a direct ORM write still cannot store a lowercase code.

### 5.3 Retrieve program

- **URI:** `GET /api/v1/catalogue/programs/<program_id>/`
- **Permission key:** `institutions.program.read` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Response:** `Program (detail shape)` — adds `tuition_notes`, the five entry-expectation fields, `scholarship_notes`, and `notes` to the list shape
- **Business rules:** an `inactive` program is still retrievable by id, permanently. Anything that referenced it must keep resolving.
- **Errors:** `INSTITUTIONS_PROGRAM_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403)

### 5.4 Update program

- **URI:** `PATCH /api/v1/catalogue/programs/<program_id>/`
- **Permission key:** `institutions.program.update` (risk: **high**)
- **Auth:** required. **Admin only.**
- **Request:** any subset of the create fields **except `institution`**
- **Response:** `Program (detail shape)`
- **Business rules:**
  - `institution` is **immutable** — a program that changes provider is a different program. It is absent from the update serializer, so sending it is ignored.
  - `campus` is editable but must still belong to the program's institution.
  - **Every cross-field rule is evaluated against the resulting record, not the incoming patch.** A `PATCH` clearing `tuition_currency` on an already-priced program fails with `INSTITUTIONS_TUITION_INCOMPLETE`, exactly as setting an amount with no currency does. Only a resulting-state check catches both.
  - A `PATCH` that changes nothing writes no audit event.
  - Risk is `high`: tuition and entry expectations drive counselling advice.
- **Errors:** `INSTITUTIONS_PROGRAM_NOT_FOUND` (404), `INSTITUTIONS_ACTOR_FORBIDDEN` (403), `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH` (400), `INSTITUTIONS_TUITION_INCOMPLETE` (400), `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED` (400), `VALIDATION_ERROR` (400)

---

## Audit

Every create and update appends one event to the central `audit` log via `audit.services.record_event`, with `app_label = "institutions"`. Update events carry a `changes` map of `{field: {from, to}}`, which is how the concept's "previous values should remain visible in history" requirement is met — there is no versioned row history.

`entity_type` values: `catalogue_field`, `catalogue_country`, `catalogue_institution`, `catalogue_campus`, `catalogue_program`. All five carry the prefix — the audit log is shared across every app, so a bare `country` or `field` would collide the moment another app records an entity of the same name, and a set where only some members are prefixed is worse than either convention applied consistently.

**This app exposes no history endpoint** — unlike `applicant_journeys`. Catalogue history is read through the `audit` app's own endpoints, filtered by `app=institutions` plus `entity_type` and `entity_id`.

**Security notes:** catalogue records contain no applicant data and nothing sensitive. No secrets or full record contents enter an audit payload (§17).
