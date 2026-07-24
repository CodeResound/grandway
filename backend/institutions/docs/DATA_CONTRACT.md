# Data Contract — Institutions

**Owner app:** `institutions`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns Grandway's study-opportunity catalogue — the countries, institutions, campuses, and programs the consultancy can offer, together with each record's tuition, entry expectations, and current availability. It is **reference data, not a plan**: it does not own an applicant's intent, progress, or choice history (`applicant_journeys`), the person (`applicants`), the enquiry (`leads`), or offers. It owns no history table — a catalogue record's history is the central `audit` log filtered to that record.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial contract — Phase 1 catalogue spine: Field, Country, Institution, Campus, Program |
| 1.1.0 | 2026-07-24 | AI (Claude) | Documentation only — no schema change. Recorded the first inbound dependency (`offers`, three nullable `PROTECT` FKs) and why catalogue edits stay safe under it: offers snapshot the names rather than reading through. Noted the `FeePeriod` promotion to `core.constants` |

---

## Deliberate Deviations

`concepts/institutions.txt` describes ten entities and leaves five questions open. Phase 1 implements the catalogue spine and settles four of those questions; each departure from the concept file or from `CLAUDE.md` is recorded here rather than left to be inferred.

- **§39.1 bilingual identity is inverted for this app: `name_en` is required, `name_np` is optional, and `name_romanized` does not exist.** §39.1 requires `name_np` (required) + `name_en` + `name_romanized` on every model with a user-visible name, and `leads.ReferenceEntry` follows that shape. Catalogue records are *foreign* proper nouns — "University of Melbourne" and "Bachelor of Nursing" have no authoritative Devanagari identity, so a required `name_np` would force staff to invent transliterations and fill the search index with noise. §39.1's premise is that the two names are "two equally canonical, legally authoritative identities"; for a foreign university that premise does not hold. `name_romanized` is dropped because the English name is already ASCII, making the field a duplicate rather than a search aid. `Country` and `Institution` still accept an optional `name_np` for the destinations staff genuinely do write in Nepali, and both are trigram-indexed. **Unicode normalization (§39.2) still applies in full** to every user-entered text field.
- **No `QualificationLevel` table.** The concept asks whether qualification levels should be a seeded fixed list or an admin-managed table. `core.constants.StudyLevel` already exists and is used by `leads.LeadStudyInterest.study_level` and `applicant_journeys.ApplicantJourney.study_level`; a second vocabulary for the same concept would violate §3 and would make "programs matching this journey's level" a mapping problem instead of an equality check. `Program.qualification_level` reuses the enum. Cost, accepted deliberately: adding a level is a migration, not an admin screen.
- **`Field` *is* an admin-managed table.** The same open question, answered the other way, because `field_of_study` is free text in `leads` and `applicant_journeys` — there is no existing enum to preserve, and study areas are genuinely consultancy-specific.
- **Availability is one status field, not a separate entity.** The concept lists "Availability note" as a core entity. It is modelled as `availability_status` + `availability_note` on each catalogue record. A separate table would answer "what is the current availability" with a query instead of a field read, for no gain — the concept's actual requirement is to *distinguish "exists" from "currently usable"*, which a status enum does directly. This mirrors the denormalized current-state pattern already used by `leads`, `applicant_journeys`, and `core.policy_engine` (§35 item 15).
- **`Field` keeps a plain `is_active` boolean** rather than `availability_status`. It is a pure reference table shaped like `leads.ReferenceEntry`, not a catalogue record that can be seasonal or paused. The two shapes are intentional, not drift.
- **Tuition, entry expectations, and scholarship availability are inline fields on `Program`, not related tables.** Phase 1 scope. The concept's open questions — whether tuition varies by campus/intake/year, and whether scholarships attach above the program — must be answered before those become tables. Inline fields promote to related tables additively.
- **Intake is free text (`intake_pattern`), not a table.** Same reason. This matches the free-text `preferred_intake` already in `leads` and `applicant_journeys`, so nothing regresses.
- **No history table**, for the same reason as `leads`, `applicants`, and `applicant_journeys`: `audit` already provides an immutable append-only log and §4 forbids duplicating it.
- **`FeePeriod` and `validate_currency_code` now live in `core`, not here.** Both were declared in this app and were promoted to `core.constants` / `core.validators` when `offers` began recording the tuition an institution actually quoted — a second app needing them makes them shared vocabulary (§2), and copying either would have duplicated an enum and a validator across apps (§3). Both are re-exported from `institutions.constants` and `institutions.validators`, so every import site in this app is unchanged, and the promotion produced **no migration**: Django deconstructs both to inline literals, verified with `makemigrations --check`.
- **No link to `applicant_journeys` in this phase.** Journeys keep their free-text `target_country` / `target_institution_name` / `target_program_name`. Introducing references changes a shipped app's public response shape (§28 item 8) and needs a backfill decision for existing values; it is its own session.

---

## 1. Field

**Purpose:** The study-area classification used to group and search programs — IT, business, engineering, health, hospitality. Admin-managed, because the useful grouping is specific to the consultancy's market.
**Table:** `institutions_field`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| code | CharField(50) | Yes | No | No | Unique ASCII system identifier (§39.7), e.g. `information_technology` |
| name_en | CharField(150) | Yes | No | No | Display name |
| name_np | CharField(150) | No | No | No | Optional Devanagari name |
| is_active | Boolean | No | No | No | Deactivated, never deleted; indexed |
| display_order | PositiveInteger | No | No | No | Ordering within admin pickers; defaults to 0 |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- `code` matches `^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$` — lowercase ASCII letters, digits, `_`, `-`, starting and ending alphanumeric. Never Devanagari (§39.7).
- `code` is unique and **immutable after creation** — it is a stable identifier that programs and external references depend on.
- `name_en` is required and Unicode-normalized on write; `name_np` is normalized when present.
- Ordering is `display_order`, then `name_en`.

**Indexes:** `is_active` (`db_index=True`) — every picker filters to active entries.

**Soft Delete:** `N/A — no deletion at all.` `Field` rows are never deleted and there is no delete endpoint. `is_active = False` removes an entry from pickers while programs that reference it keep resolving. `Program.field` uses `PROTECT`, so a referenced field cannot be removed even from the Django admin.

**Example:**
```json
{
  "id": "8f1d9e2a-4c3b-4a71-9f0e-2b6c5d8e1a34",
  "code": "information_technology",
  "name_en": "Information Technology",
  "name_np": "सूचना प्रविधि",
  "is_active": true,
  "display_order": 10,
  "created_at": "2026-07-24T09:12:44.318Z",
  "updated_at": "2026-07-24T09:12:44.318Z"
}
```

---

## 2. Country

**Purpose:** The top-level geographic container for catalogue records, and the first filter in every shortlisting search.
**Table:** `institutions_country`
**`availability_status` choices:** `active`, `paused`, `seasonal`, `inactive`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| code | CharField(10) | Yes | No | No | Unique ASCII identifier, ISO 3166-1 alpha-2 by convention (e.g. `au`) but not enforced as such |
| name_en | CharField(150) | Yes | No | No | Display name, e.g. "Australia" |
| name_np | CharField(150) | No | No | No | Optional Devanagari name — destinations staff do write in Nepali |
| availability_status | CharField(20) | No | No | No | Defaults to `active`; indexed |
| availability_note | TextField | No | No | No | Why the record is paused, seasonal, or inactive |
| notes | TextField | No | No | No | Intake-planning or counselling notes |
| display_order | PositiveInteger | No | No | No | Defaults to 0 |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- `code` follows the same ASCII pattern as `Field.code`, is unique, and is **immutable after creation**.
- `name_en` required; all user-entered text Unicode-normalized on write (§39.2).
- Setting `availability_status` to anything other than `active` **requires a non-empty `availability_note`** — otherwise `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED`. A record withdrawn from use without a stated reason is exactly the drift the catalogue exists to prevent.
- Marking a country non-usable does **not** cascade to its institutions or programs. Search applies the country's status at query time; cascading would destroy each child's own recorded availability and could not be undone.
- Ordering is `display_order`, then `name_en`.

**Indexes:** `availability_status` (`db_index=True`) — the default search filter.

**Soft Delete:** `N/A — availability_status replaces deletion.` No delete endpoint exists. `inactive` hides the country from active search while preserving every record that references it. `Institution.country` uses `PROTECT`.

**Example:**
```json
{
  "id": "1c2b3a49-5d6e-4f70-8a91-b2c3d4e5f607",
  "code": "au",
  "name_en": "Australia",
  "name_np": "अस्ट्रेलिया",
  "availability_status": "active",
  "availability_note": "",
  "notes": "Genuine Student requirement applies from 2024 intakes onward.",
  "display_order": 1,
  "created_at": "2026-07-24T09:14:02.771Z",
  "updated_at": "2026-07-24T09:14:02.771Z"
}
```

---

## 3. Institution

**Purpose:** A university, college, polytechnic, or similar provider. The record staff mean when they say "we work with this university."
**Table:** `institutions_institution`
**`institution_type` choices:** `university`, `college`, `polytechnic`, `language_school`, `other`
**`availability_status` choices:** `active`, `paused`, `seasonal`, `inactive`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| country | FK → institutions.Country | Yes | No | No | Parent country (`PROTECT`) |
| name_en | CharField(255) | Yes | No | No | Official name, e.g. "University of Melbourne" |
| name_np | CharField(255) | No | No | No | Optional Devanagari name |
| common_name | CharField(150) | No | No | No | What staff actually call it, e.g. "Unimelb" |
| institution_type | CharField(20) | No | No | No | Defaults to `university` |
| availability_status | CharField(20) | No | No | No | Defaults to `active`; indexed |
| availability_note | TextField | No | No | No | Required when status is not `active` |
| notes | TextField | No | No | No | Counselling notes |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- `name_en` required and Unicode-normalized; `name_np` and `common_name` normalized when present.
- `country` is required and **may be changed** — an institution is occasionally filed under the wrong country and correcting it is legitimate. The change is audited.
- Non-`active` status requires `availability_note` (see `Country`).
- `(country, name_en)` is **not** unique. Two genuinely distinct providers can share a name, and blocking the second creates a worse problem than the duplicate. Duplicate detection is a Phase 2 concern.
- Ordering is `name_en`.

**Indexes:**
- `availability_status` (`db_index=True`) — default search filter.
- `institution_country_status_idx` — `(country, availability_status)`. Supports the country-detail screen's "institutions in this country, usable ones first".
- `institution_name_en_trgm_idx` — GIN `gin_trgm_ops` on `name_en`. Supports the `?q=` search.
- `institution_name_np_trgm_idx` — GIN `gin_trgm_ops` on `name_np`. Same, for the optional Devanagari name.

**Soft Delete:** `N/A — availability_status replaces deletion.` No delete endpoint. `Campus.institution` and `Program.institution` use `PROTECT`.

**Example:**
```json
{
  "id": "2d3e4f50-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
  "country": "1c2b3a49-5d6e-4f70-8a91-b2c3d4e5f607",
  "name_en": "University of Melbourne",
  "name_np": "",
  "common_name": "Unimelb",
  "institution_type": "university",
  "availability_status": "active",
  "availability_note": "",
  "notes": "Requires certified transcripts at application, not at offer.",
  "created_at": "2026-07-24T09:15:30.102Z",
  "updated_at": "2026-07-24T09:15:30.102Z"
}
```

**Cross-App Dependencies:** `offers.Offer.institution` is a nullable `PROTECT` FK pointing here. An institution referenced by any offer cannot be removed; renaming or deactivating it is safe, because the offer holds its own snapshot of the name.

---

## 4. Campus

**Purpose:** A physical or logical site of an institution. Exists because some institutions price, schedule, or offer programs differently by location.
**Table:** `institutions_campus`
**`availability_status` choices:** `active`, `paused`, `seasonal`, `inactive`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| institution | FK → institutions.Institution | Yes | No | No | Parent institution (`PROTECT`) |
| name_en | CharField(255) | Yes | No | No | Campus name, e.g. "Parkville" |
| city | CharField(150) | No | No | No | City the campus sits in |
| availability_status | CharField(20) | No | No | No | Defaults to `active`; indexed |
| availability_note | TextField | No | No | No | Required when status is not `active` |
| notes | TextField | No | No | No | |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- `name_en` required and Unicode-normalized; `city` normalized when present.
- `institution` is set at creation and is **immutable** — a campus does not move between providers. Correcting a mistake means creating the campus under the right institution and deactivating the wrong one, which keeps the programs attached to each one honest.
- `(institution, name_en)` is unique — one institution genuinely cannot have two campuses of the same name, and here the duplicate is always an error. Violation returns `INSTITUTIONS_CAMPUS_DUPLICATE`.
- Non-`active` status requires `availability_note`.
- No `name_np`: campus names are locality names in the destination country and are not written in Devanagari in practice.
- Ordering is `name_en`.

**Indexes:**
- `availability_status` (`db_index=True`).
- `campus_institution_status_idx` — `(institution, availability_status)`. Supports the institution-detail screen's campus list.
- Unique constraint `campus_institution_name_uniq` — `(institution, name_en)`.

**Soft Delete:** `N/A — availability_status replaces deletion.` No delete endpoint. `Program.campus` uses `PROTECT`.

**Example:**
```json
{
  "id": "3e4f5061-7b8c-4d9e-af01-2b3c4d5e6f70",
  "institution": "2d3e4f50-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
  "name_en": "Parkville",
  "city": "Melbourne",
  "availability_status": "active",
  "availability_note": "",
  "notes": "",
  "created_at": "2026-07-24T09:16:11.554Z",
  "updated_at": "2026-07-24T09:16:11.554Z"
}
```

---

## 5. Program

**Purpose:** A specific study offering — the record staff actually shortlist against. Carries where it is taught, what level and field it sits in, when it runs, what it costs, what it takes to get in, and whether it can be offered right now.
**Table:** `institutions_program`
**`qualification_level` choices:** `school`, `certificate`, `diploma`, `bachelors`, `postgraduate_diploma`, `masters`, `phd`, `other` — imported from `core.constants.StudyLevel`, the same set `applicant_journeys.ApplicantJourney.study_level` uses
**`tuition_fee_period` choices:** `per_year`, `per_semester`, `total_program` (blank when no tuition is recorded)
**`availability_status` choices:** `active`, `paused`, `seasonal`, `inactive`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| institution | FK → institutions.Institution | Yes | No | No | Provider (`PROTECT`) |
| campus | FK → institutions.Campus | No | Yes | No | Site, when the institution splits by campus (`PROTECT`) |
| title | CharField(255) | Yes | No | No | e.g. "Master of Information Technology" |
| qualification_level | CharField(30) | Yes | No | No | `core.constants.StudyLevel`; indexed |
| field | FK → institutions.Field | Yes | No | No | Study area (`PROTECT`) |
| duration_months | PositiveSmallInteger | No | Yes | No | Null when not yet recorded |
| intake_pattern | CharField(100) | No | No | No | Free text in Phase 1, e.g. "Feb / Jul" |
| tuition_amount | Decimal(12,2) | No | Yes | No | `DecimalField`, never a float (§8) |
| tuition_currency | CharField(3) | No | No | No | ISO 4217, upper-cased on write |
| tuition_fee_period | CharField(20) | No | No | No | What the amount covers |
| tuition_is_indicative | Boolean | No | No | No | True when the figure is an estimate rather than a quoted fee |
| tuition_notes | TextField | No | No | No | Caveats — the "context" the concept asks to preserve alongside the value |
| academic_requirement | TextField | No | No | No | Entry expectation |
| english_requirement | TextField | No | No | No | Entry expectation |
| backlog_tolerance | TextField | No | No | No | Entry expectation |
| document_expectation | TextField | No | No | No | Entry expectation |
| selection_notes | TextField | No | No | No | Entry expectation |
| scholarship_available | Boolean | No | No | No | Defaults to false |
| scholarship_notes | TextField | No | No | No | Free text in Phase 1 |
| availability_status | CharField(20) | No | No | No | Defaults to `active`; indexed |
| availability_note | TextField | No | No | No | Required when status is not `active` |
| notes | TextField | No | No | No | |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- `institution`, `title`, `qualification_level`, and `field` are required. Everything else may be filled in later — the concept explicitly allows saving an incomplete record as inactive until it is ready.
- **`campus`, when given, must belong to `institution`** — otherwise `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH`. This is the one cross-field rule that silently corrupts the catalogue if unchecked, because both FKs resolve individually.
- `institution` is **immutable after creation**; `campus` may be changed but only to a campus of the same institution. A program that moves provider is a different program.
- `tuition_amount` must be ≥ 0. When `tuition_amount` is set, `tuition_currency` and `tuition_fee_period` are both required — an amount with no currency or period is unusable in counselling and is the single most likely catalogue error. Returns `INSTITUTIONS_TUITION_INCOMPLETE`.
- `tuition_currency` is upper-cased on write and must be exactly three ASCII letters when present.
- `duration_months`, when given, must be between 1 and 120.
- Non-`active` status requires `availability_note`.
- Every user-entered text field is Unicode-normalized on write (§39.2).
- A program's availability is its own. It is not derived from its institution's or country's status, and changing theirs does not change it — search evaluates all three at query time.

**Indexes:**
- `qualification_level` (`db_index=True`), `availability_status` (`db_index=True`).
- `program_institution_status_idx` — `(institution, availability_status)`. Supports the institution-detail program list.
- `program_level_status_idx` — `(qualification_level, availability_status)`. Supports the shortlisting search's primary filter pair.
- `program_field_status_idx` — `(field, availability_status)`. Supports "all IT programs we can currently offer".
- `program_title_trgm_idx` — GIN `gin_trgm_ops` on `title`. Supports the `?q=` search.

**Soft Delete:** `N/A — availability_status replaces deletion.` No delete endpoint exists, per the concept's "No deletion of historical catalogue records." A program that is no longer offered becomes `inactive` and keeps resolving for any journey or offer that referenced it.

**Example:**
```json
{
  "id": "4f506172-8c9d-4e0f-b112-3c4d5e6f7081",
  "institution": "2d3e4f50-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
  "campus": "3e4f5061-7b8c-4d9e-af01-2b3c4d5e6f70",
  "title": "Master of Information Technology",
  "qualification_level": "masters",
  "field": "8f1d9e2a-4c3b-4a71-9f0e-2b6c5d8e1a34",
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
  "notes": "",
  "created_at": "2026-07-24T09:18:47.900Z",
  "updated_at": "2026-07-24T09:18:47.900Z"
}
```

**Security Notes:** No sensitive data. Catalogue records contain no applicant information and are readable by every Admin and Lead Manager.

---

## Cross-App Dependencies

**This app references:**

| App | What | Why |
|-----|------|-----|
| `core` | `core.models.BaseModel` (abstract), `core.constants.StudyLevel`, `core.nepal.text.normalize_unicode`, `core.pagination.StandardPagination`, `core.responses` | Framework and shared vocabulary. `StudyLevel` is imported rather than redefined (§3). |
| `authenticate` | `authenticate.constants.AuthorityType` | The interim access checks in `access.py` (§9). No FK — catalogue records record no owner. |
| `audit` | `audit.services.record_event` | Every create and update appends one immutable event. Service call only; this app never writes the audit table directly. |

**Referenced by:**

| App | What | Why |
|-----|------|-----|
| `offers` | `offers.Offer.institution`, `.campus`, `.program` — three nullable `PROTECT` FKs; plus `institutions.selectors.get_institution_by_id` / `get_campus_by_id` / `get_program_by_id` | An offer records which catalogue entry it was based on. The FKs are nullable because a manually recorded historical offer has no catalogue record behind it. |
| `applicant_journeys` | `applicant_journeys.ApplicantJourney.target_country_ref` — one nullable `PROTECT` FK (`related_name="journeys"`); plus `institutions.selectors.get_country_by_id` on create and update | A journey's destination, as a real reference rather than the typed string it also keeps. **This is the field that decides which document checklist an applicant inherits**, which is why an exact reference was worth adding. |
| `checklists` | `checklists.ChecklistTemplate.country` and `checklists.Checklist.country` — two nullable `PROTECT` FKs (`related_name="checklist_templates"`, `"checklists"`); plus `institutions.selectors.get_country_by_id` | A checklist template is a country's requirement list; each applicant's checklist copies that country at instantiation. |

**A referenced catalogue record can still be edited freely, and that is safe.** `offers` copies the institution, campus, program, country, level, and intake into an immutable **snapshot** on the offer at creation, and renders from that — so renaming a program or marking an institution `inactive` changes nothing on offers already recorded against it. The FK survives as the original reference point; it is not read through at display time. This is what makes the catalogue's "edit freely, never delete" posture compatible with the offer module's "never rewrite history" requirement. See `offers/docs/DATA_CONTRACT.md` §1.

**`applicant_journeys` now references this app — partly.** It gained `target_country_ref`, a nullable FK to `Country`, alongside the free-text `target_country` it keeps for journeys created before this catalogue existed. Institution and program on a journey are **still** free text with no reference; migrating those is a separate session (see Deliberate Deviations).

**A country referenced by a checklist template cannot be removed, and it is the only catalogue record read through at display time.** Unlike `offers`, which snapshots the catalogue names it needs and never reads the FK back, `checklists` returns the live country object on every template and checklist response. Renaming a country therefore *does* change what a checklist screen displays — correctly, since a checklist names an ongoing destination rather than a historical decision. Marking a country `inactive` changes nothing about checklists already inherited: this app's availability status is never consulted by that module.

**No app imports this app's `models.py`** except for the FK references above, which §4 permits. Consumers otherwise use `institutions.selectors` and `institutions.services`.

---

## Soft Delete

`N/A — no model in this app supports deletion.` The concept's "No deletion of historical catalogue records" is implemented as an app-wide rule rather than a per-model flag: there is no delete endpoint on any resource, every child FK is `PROTECT`, and withdrawal from use is expressed as `availability_status = inactive` (or `is_active = False` on `Field`). Records that are no longer offered stay resolvable forever, so a journey or offer that referenced them can still be read.
