# Session — 20260725_0037

Branch: `add_audit_read_surface_20260724_2314`

**Change:** The project moved from bilingual (`_np`/`_en`/`_romanized`) names to **English-only** names. Every user-facing name/title/label is now one field; the `_np` and `_romanized` columns were dropped, `_en` fields renamed to bare (`name_en` → `name`), the romanization helper and the `indic-transliteration` dependency removed, and the BsDate API payload reduced to its English rendering (`month_name`/`display`; the `_np` keys are gone). CLAUDE.md §39 was rewritten to match. This is a **breaking API change**, taken in place on `/api/v1/` (no v2) because no frontend has shipped against these shapes and the database is effectively empty; see each app's Change History.

Migrations: `<app>/migrations/*_english_only_names.py` for the seven apps below. Each drops the dead columns and renames `_en` → bare via `RenameField` (data-preserving), after a `RunPython` salvage that copies a `_np` value into the surviving column wherever it is blank, so no record loses its only name. Reverse re-creates the dropped columns empty.

---

## Applicants

## 1. Module
- Name: applicants — Base path: `/api/v1/applicants/` — Auth: Bearer access token (Admin/Lead Manager read; Admin write).

## 2. Conventions
- BS date fields now render `{ year, month, day, month_name, display }` — the `_np`/`_en` key suffixes are gone.

## 3. Models
- **Applicant** — `full_name_np`, `full_name_en`, `full_name_romanized` removed; single required **`full_name`**. `date_of_birth_bs` and every BS companion use the new shape.
- **FamilyMember**, **EmergencyContact** — `full_name_np`/`full_name_en` removed; single **`full_name`**.
- Read shapes drop the three name variants; a client reads one `full_name`.

## 4. Enums
- No change.

## 5. Dependency order
- No change.

## 6. Endpoints
- No endpoint added, changed, or retired. Request/response **shape** changed: create/list/detail now carry `full_name` (create requires it; update keeps it optional). `?search=` matches the single name plus email, contact number, and passport number.

## 7. Flows
- No flow re-ordered. The applicant search box matches one name field, not three scripts.

## 8. Gaps
- `full_name` is the only identity string. There is no Devanagari or romanized form to fall back on for a record whose name was salvaged from a dropped `_np` column.

---

## Authenticate

## 1. Module
- Name: authenticate — Base path: `/api/v1/auth/` — Auth: as before.

## 2. Conventions
- No change beyond the BS shape.

## 3. Models
- **User** — `full_name_np`, `full_name_en`, `full_name_romanized` removed; single optional **`full_name`**. `display_name` (required) unchanged.

## 4. Enums
- No change.

## 5. Dependency order
- No change.

## 6. Endpoints
- Account create/update: request drops `full_name_np`/`full_name_romanized`; accepts `full_name`. The **User** read shape carries `full_name` instead of the triple.

## 7. Flows
- No change.

## 8. Gaps
- None new.

---

## Clients

## 1. Module
- Name: clients — Base path: `/api/v1/clients/` — Auth: reads Admin/Lead Manager, writes Admin.

## 3. Models
- **Client** — `name_np`/`name_en`/`name_romanized` and `spokesperson_name_np`/`_en`/`_romanized` removed; single required **`name`** and single optional **`spokesperson_name`**. Directory ordering and the `client_status_name_idx` / `client_name_trgm_idx` indexes rebuilt on `name`.

## 6. Endpoints
- Create now requires `name` (was `name_np`); update keeps it optional. List/detail carry `name` + `spokesperson_name`, no romanized fields. `?search=` covers both names.

## 8. Gaps
- Only the organization name is trigram-indexed; the spokesperson name is not (bounded directory).

---

## Document Templates

## 3. Models
- **Signatory** — `name_np`/`name_en`/`name_romanized` and `title_np`/`title_en` removed; single required **`name`**, single optional **`title`**. Indexes rebuilt on `name`.

## 6. Endpoints
- Signatory create requires `name`. The picker read shape carries `name`/`title`, no romanized field. `?search=` runs on `name`.

## 8. Gaps
- None new.

---

## Institutions

## 3. Models
- **Field**, **Country**, **Institution** — `name_np` removed, `name_en` → **`name`** (required). **Campus** — `name_en` → **`name`**. `institution_name_trgm_idx` rebuilt on `name`.

## 6. Endpoints
- Catalogue create/list/detail carry a single `name`. `?q=` searches `Program.title`, `Institution.name`, `Institution.common_name`.

## 8. Gaps
- Catalogue names are English proper nouns with no second form — the clearest case for English-only.

---

## Leads

## 3. Models
- **Lead** — `full_name_np`/`_en`/`_romanized` → single required **`full_name`**; `lead_name_trgm_idx` rebuilt on it. **LeadSource**, **LossReason** (via `ReferenceEntry`) — `name_np`/`_en`/`_romanized` → single required **`name`**.

## 6. Endpoints
- Lead create requires `full_name` (update optional). Source/loss-reason create requires `name`. `?search=` matches `full_name`, email, and any contact number; relevance ranking unchanged (now over the one name field).

## 8. Gaps
- None new.

---

## Offers

## 3. Models
- **Offer** — snapshot `institution_name_np` removed, `institution_name_en` → **`institution_name`** (required; copied from the catalogue).

## 6. Endpoints
- Offer create/detail carry `institution_name` in the manual-entry branch. No endpoint added or removed.

## 8. Gaps
- None new.

---

## Core

## 1. Module
- `core.nepal` — infrastructure, no HTTP surface.

## 3. Models
- None.

## 6. Endpoints
- None. `core.nepal.text.romanize_devanagari`, `contains_devanagari`, `contains_latin`, and the whole `core.nepal.language` module were removed. `normalize_unicode` stays. `core.nepal.calendar.BsDate` now exposes `month_name`/`display` only (no `_np`/`_en`). `BS_MONTH_NAMES_NP` and `DEVANAGARI_DIGITS` constants removed. `indic-transliteration` dropped from `requirements/base.txt`.

## 8. Gaps
- The BS calendar and NPT timezone remain; only their Devanagari rendering is gone.
