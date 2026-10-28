# Session 20261029_0021 — frontend updates.md phases 2–6 (branch `feature/updates_md_phases_2_to_6_20261029_0021`)

## Applicants

## 1. Module
- Name: Applicants
- Base path: `/api/v1/applicants/`
- Auth: unchanged (Bearer access token; `admin` and `lead_manager`; `superadmin` 403 everywhere). New this session: restore is Admin only; assign is Admin and Lead Manager (Lead Manager limited to take/release)

## 2. Conventions
- Response: no changes this session
- Error:
  - per-entry errors on `educations` and `language_tests` use `error.details.fields` — a flat map from `<collection>[<index>].<field>` (index from 0 in the list sent) to **one message string**, not a list; every failing field is reported at once and nothing is written
  - `APPLICANTS_ASSIGNEE_INVALID` carries `error.details` = `{ "assigned_to": ["…"] }`; `APPLICANTS_ASSIGNMENT_FORBIDDEN` carries `details: {}`
- Auth failures: no changes this session
- Pagination: no changes this session; the new notes list is paginated the same way and adds `meta.counts` = `{ general, visit }`
- IDs: no changes this session
- Times: `ApplicantNote.noted_at` is ISO 8601 with a `noted_at_bs` sibling; a `noted_at` sent without a UTC offset is read as Nepal time (Asia/Kathmandu, +05:45). `LanguageTest.test_date` / `expiry_date` carry `_bs` siblings
- List/search/filter/order params:
  - `GET /api/v1/applicants/` adds `assigned_to` — `me` (the caller), `none` (unassigned), or a user UUID; anything else → 400 `VALIDATION_ERROR`. Composes with every other filter; filters, never scopes
  - notes list: `category` (`general` | `visit`), `ordering` (`-noted_at` default | `noted_at` | `-created_at`), `page`, `page_size`
- Scores (education `score` and every language-test score) may be sent as a JSON number or a decimal string; always returned as decimal strings

## 3. Models
- **Applicant (list shape)** `{ id, full_name, date_of_birth?, date_of_birth_bs?:BsDate, gender:[enum], nationality, email, status:[enum], creation_source:[enum], created_by:UserBrief, assigned_to?:UserBrief, contact_numbers:[ContactNumber], destinations:[Destination], created_at, updated_at }`
  - `assigned_to` is new: the staff member notified about this applicant, or `null`. Never an access control
- **Applicant (detail shape)** — the list shape plus `{ citizenship_no, citizenship_issue_district, national_id_no, addresses:[Address], passport?:Passport, family_members:[FamilyMember], emergency_contacts:[EmergencyContact], educations:[Education], language_tests:[LanguageTest], originating_lead_id? }`
  - new: `citizenship_no`, `citizenship_issue_district`, `national_id_no` (detail only), `educations`, `language_tests`
  - returned by retrieve, create, update, and the status, restore, and assign actions
- **FamilyMember** `{ id, relationship:[enum], full_name, occupation, contact_number, citizenship_no }` — `citizenship_no` is new
- **Education** `{ id, level:[enum], qualification, institution, country, completion_status:[enum], score?:decimal-string, score_type:[enum], grading_system, start_year?:int, completion_year?:int, year_calendar:[enum], source_lead_id? }`
  - years are bare years in `year_calendar`; `source_lead_id` is set on a record carried over from a converted lead
- **LanguageTest** `{ id, test_type:[enum], overall_score?, listening_score?, reading_score?, writing_score?, speaking_score?, test_date?, test_date_bs?:BsDate, certificate_number, expiry_date?, expiry_date_bs?:BsDate, source_lead_id? }`
  - scores are decimal strings with one place
- **ApplicantNote** `{ id, category:[enum], body, noted_at, noted_at_bs:BsDate, is_backdated:bool, source_lead_id?, author:UserBrief, updated_by?:UserBrief, created_at, updated_at }`
  - `is_backdated` is `true` when `created_at` is more than 15 minutes after `noted_at`; a note carried over from a lead keeps its original `created_at`
- **HistoryEntry** — shape unchanged; on `applicant_assigned` / `applicant_unassigned`, `changes.assigned_to` is `{ from, to }` with user ids or `null`

## 4. Enums
- FamilyMember.relationship: adds `grandfather` | `grandmother` (full set: `father` | `mother` | `spouse` | `sibling` | `child` | `guardian` | `grandfather` | `grandmother` | `other`)
- Education.level: `see` | `plus_two` | `diploma` | `bachelor` | `master` | `phd` | `other`
- Education.completion_status: `completed` | `ongoing`
- Education.score_type: `gpa` | `percentage` | `""`
- Education.year_calendar: `bs` | `ad` | `""`
- LanguageTest.test_type: `ielts` | `pte` | `toefl` | `duolingo` | `other`
- ApplicantNote.category: `general` | `visit` (may gain values such as `call`)
- HistoryEntry.action: adds `applicant_restored` | `applicant_note_added` | `applicant_note_updated` | `applicant_note_deleted` | `applicant_notes_imported` | `applicant_education_changed` | `applicant_language_tests_changed` | `applicant_assigned` | `applicant_unassigned`
- `?assigned_to=` filter literals: `me` | `none` (or a user UUID)

## 5. Dependency order
- `ApplicantNote` needs an `Applicant` that is not archived (reads work on any applicant).
- `Education` and `LanguageTest` need `Applicant` — sent nested in the applicant payload, never created on their own.
- An assignment needs an `Applicant` that is not archived and an active Admin or Lead Manager account `(external module: authenticate)`.
- **Start here:** unchanged — `POST /api/v1/applicants/` as an Admin, or convert a lead.

## 6. Endpoints

### Applicant — `/api/v1/applicants/`
**Use it when:** the applicant list, the applicant file, and its edit form — now including education, language tests, identity numbers, and an assignee filter.
**Methods:**
- GET `/api/v1/applicants/`
- POST `/api/v1/applicants/`
- GET `/api/v1/applicants/<applicant_id>/`
- PATCH `/api/v1/applicants/<applicant_id>/`
**Send (create/update):**
- create adds: `citizenship_no` (≤50), `citizenship_issue_district` (≤100), `national_id_no` (≤50) — free text, not format-checked; `family_members[].citizenship_no`; `educations`; `language_tests`
- `educations[]`: `level` (required), `qualification`, `institution`, `country`, `completion_status` (default `completed`), `score` + `score_type` (together; gpa 0–4, percentage 0–100), `grading_system`, `start_year`, `completion_year`, `year_calendar` (required when a year is given; BS 2000…current BS year + 1, AD 1950…current year + 1; start ≤ completion; an `ongoing` record has no `completion_year`)
- `language_tests[]`: `test_type` (required), `overall_score`, `listening_score`, `reading_score`, `writing_score`, `speaking_score` (IELTS 0–9 in 0.5 steps, PTE 10–90, TOEFL 0–120, Duolingo 10–160, other ≥0), `test_date` (not in the future), `certificate_number`, `expiry_date` (after `test_date`)
- `source_lead_id` is not writable on either collection
- update: any subset of the same fields
**Returns:** Applicant (detail shape) | list[Applicant (list shape)]
**Notes:**
- `educations` and `language_tests` replace wholesale like every other collection; `[]` clears, omitting leaves untouched. Resending a record carried over from a lead drops its `source_lead_id`
- `educations` are returned most recent `completion_year` first (`ongoing` first), then oldest-entered; `language_tests` most recent `test_date` first (undated first), then oldest-entered
- `assigned_to` is not writable through create or update (ignored, not rejected); a directly created applicant is always unassigned
- `citizenship_no` and `national_id_no` changes appear in history only as `<changed>`
- an applicant converted from a lead arrives assigned to the lead's owner (or unassigned if that person is no longer an active Admin or Lead Manager), with the lead's notes, one education record (when the lead had a qualification level), and one language test per lead certificate, each carrying `source_lead_id`
**Errors:**
- `APPLICANTS_EDUCATION_INVALID` (400) — an education entry breaks a rule; `error.details.fields`
- `APPLICANTS_LANGUAGE_TEST_INVALID` (400) — a language test breaks a rule; `error.details.fields`
- `VALIDATION_ERROR` (400) — includes a malformed `assigned_to` list filter

### Applicant status — `/api/v1/applicants/<applicant_id>/status/`
**Use it when:** setting an applicant dormant or archiving ("deleting") them.
**Methods:**
- POST `/api/v1/applicants/<applicant_id>/status/`
**Send (create/update):** none — request unchanged (`status`)
**Returns:** Applicant (detail shape)
**Notes:**
- can no longer move an applicant **out of** `archived` — that is the restore action
- raises an `applicant_status_changed` notification to the assignee and every Admin, or every Admin and Lead Manager when unassigned, never the caller; a no-op raises nothing
**Errors:**
- `APPLICANTS_APPLICANT_ARCHIVED` (409) — the applicant is archived and a different status was requested

### Applicant restore — `/api/v1/applicants/<applicant_id>/restore/`
**Use it when:** an Admin brings back an archived ("deleted") applicant.
**Methods:**
- POST `/api/v1/applicants/<applicant_id>/restore/`
**Send (create/update):**
- `reason` (optional, ≤2000)
**Returns:** Applicant (detail shape), `status` back to its pre-archive value (`active` or `dormant`; `active` for applicants archived before 2026-10-29)
**Notes:**
- Admin only
- journeys, notes, and sub-records are untouched
- raises an `applicant_restored` notification, routed as a status change
**Errors:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — the caller is not an Admin
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id
- `APPLICANTS_APPLICANT_NOT_ARCHIVED` (409) — the applicant is not archived
- `VALIDATION_ERROR` (400) — `reason` too long

### Applicant assignment — `/api/v1/applicants/<applicant_id>/assign/`
**Use it when:** the "Assigned to" control — an Admin picks a person or clears it; a Lead Manager sees "Take" on an unassigned file and "Release" on their own.
**Methods:**
- POST `/api/v1/applicants/<applicant_id>/assign/`
**Send (create/update):**
- `assigned_to` (required key) — a user UUID, or `null` to clear; no `me` shorthand
**Returns:** Applicant (detail shape), message `Applicant assignment updated.`
**Notes:**
- routing only — never grants or removes access
- Admin: assign any active Admin or Lead Manager, reassign, or clear. Lead Manager: take an unassigned applicant for themselves, or release one they hold
- sending the current value is a no-op (200, nothing written or raised)
- raises `applicant_assigned` to the new assignee and `applicant_unassigned` to the previous one, never to the caller
- check order: 401 → 403 `APPLICANTS_ACTOR_FORBIDDEN` → 404 → 400 `VALIDATION_ERROR` → 400 `APPLICANTS_ASSIGNEE_INVALID` → 409 `APPLICANTS_APPLICANT_ARCHIVED` → 403 `APPLICANTS_ASSIGNMENT_FORBIDDEN`
**Errors:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `APPLICANTS_ASSIGNMENT_FORBIDDEN` (403) — a Lead Manager named someone else, took an applicant someone else holds, or cleared someone else's
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id
- `APPLICANTS_ASSIGNEE_INVALID` (400) — not an active Admin or Lead Manager (unknown, deactivated, or a Superadmin)
- `APPLICANTS_APPLICANT_ARCHIVED` (409) — the applicant is archived
- `VALIDATION_ERROR` (400) — `assigned_to` missing or not a UUID/`null`

### Applicant Note — `/api/v1/applicants/<applicant_id>/notes/`
**Use it when:** the notes panel on the applicant file — a "General" tab and a "Visit" tab.
**Methods:**
- GET `/api/v1/applicants/<applicant_id>/notes/`
- POST `/api/v1/applicants/<applicant_id>/notes/`
- PATCH `/api/v1/applicants/<applicant_id>/notes/<note_id>/`
- DELETE `/api/v1/applicants/<applicant_id>/notes/<note_id>/`
**Send (create/update):**
- create: `body` (required, ≤10 000, not blank), `category` (`general` default, or `visit`), `noted_at` (optional, default now; never more than 5 minutes in the future)
- update: any subset of `category`, `body`, `noted_at`
**Returns:** ApplicantNote | list[ApplicantNote] (with `meta.counts`); `data: null` for delete
**Notes:**
- writes need a non-archived applicant; edit and delete need the author or an Admin
- delete is soft — the note leaves the list and 404s; its history stays
- a `visit` note raises `visit_note_added` to the assignee only, or every Admin and Lead Manager when unassigned, never the author; general notes, edits, and deletes raise nothing
- `meta.counts` counts live notes regardless of the `category` filter
**Errors:**
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id
- `APPLICANTS_NOTE_NOT_FOUND` (404) — no such note, or it was deleted
- `APPLICANTS_NOTE_FORBIDDEN` (403) — not the author and not an Admin
- `APPLICANTS_NOTE_FUTURE_DATE` (400) — `noted_at` later than now + 5 min
- `APPLICANTS_APPLICANT_ARCHIVED` (409) — any note write on an archived applicant
- `VALIDATION_ERROR` (400) — blank or over-long `body`, unknown `category` or `ordering`

## 7. Flows
**Assign, take, or release an applicant**
1. `GET /api/v1/applicants/<applicant_id>/` → read `assigned_to` to pick the control.
2. Admin: `POST /api/v1/applicants/<applicant_id>/assign/` with `{ assigned_to: <user id> }` or `{ assigned_to: null }`.
   - `APPLICANTS_ASSIGNEE_INVALID` (400) → refresh the picker.
3. Lead Manager: same call with their own id (take, when `assigned_to` is `null`) or `null` (release, when it is them).
   - `APPLICANTS_ASSIGNMENT_FORBIDDEN` (403) → someone else holds it; ask an Admin.
   - `APPLICANTS_APPLICANT_ARCHIVED` (409) → an Admin restores it first.

**Work my caseload**
1. `GET /api/v1/applicants/?assigned_to=me&status=active` → the caller's active applicants.
2. `GET /api/v1/applicants/?assigned_to=none` → the unassigned pool.
   - 400 `VALIDATION_ERROR` → value was not `me`, `none`, or a UUID.

**Wind a file down, and bring it back**
1. `POST /api/v1/applicants/<applicant_id>/status/` with `{ status: "archived" }`.
2. An Admin calls `POST /api/v1/applicants/<applicant_id>/restore/` with optional `{ reason }` → back to the status it left.
   - `APPLICANTS_ACTOR_FORBIDDEN` → the caller is a Lead Manager; hide restore for them.
   - Sending `{ status: "active" }` to `status/` instead → `APPLICANTS_APPLICANT_ARCHIVED` (409).

**Keep notes on a file**
1. `GET /api/v1/applicants/<applicant_id>/notes/` → notes plus `meta.counts` for the tab badges; a converted lead's notes are already here with `source_lead_id`.
2. `POST /api/v1/applicants/<applicant_id>/notes/` with `{ category: "visit", body, noted_at }`.
   - `APPLICANTS_APPLICANT_ARCHIVED` → notes are read-only until an Admin restores the applicant.
3. `PATCH` / `DELETE /api/v1/applicants/<applicant_id>/notes/<note_id>/` → author or Admin only (`APPLICANTS_NOTE_FORBIDDEN` otherwise).

## 8. Gaps
- Education is a core record only: gaps, training, backlogs, and medium of instruction are not modelled; divisions and letter grades exist only as a `grading_system` label.
- Language tests only — SAT, GRE, and other standardized tests are out of scope; test types are a fixed enum.
- Editing one education or test requires resending the whole list.
- Citizenship and national ID numbers are not format-checked and not searchable.
- No assignee picker in this module; `GET /api/v1/auth/users/` covers Lead Managers for an Admin but not fellow Admins.
- A deactivated assignee stays on the record until an Admin reassigns or clears it; for notification routing it counts as nobody.
- No bulk reassign.
- `HistoryEntry.metadata` keys remain not exhaustively specified (observed: `creation_source`, `count`, `assigned_to`, `note_id`, `category`, `noted_at`, `is_backdated`, `lead_id`).

## Authenticate

## 1. Module
- Name: Authenticate
- Base path: `/api/v1/auth/`
- Auth: unchanged for existing endpoints. New personal clipboard `me/clipboard/*` is authenticated self-service for **every** authority, Superadmin included — owner-only

## 2. Conventions
- Response: clipboard success messages — `Clipboard entry saved.`, `Clipboard entry updated.`, `Clipboard entry deleted.`, `Clipboard entry used.`, `Clipboard categories retrieved.`, `Clipboard category created.`, `Clipboard category renamed.`, `Clipboard category deleted.`; paginated list `message` is `""`
- Error:
  - `AUTH_CLIPBOARD_CATEGORY_INVALID` → `error.details` = `{ "category": [...] }`
  - `AUTH_CLIPBOARD_CATEGORY_NAME_TAKEN` → `error.details` = `{ "name": [...] }`
  - another account's entry or category id returns the same 404 as a made-up id, never 403
- Auth failures: no changes this session; `must_change_password` and MFA enrollment do not gate the clipboard
- Pagination:
  - `GET /me/clipboard/` is paginated (`page`, `page_size`, default 20, max 100)
  - `GET /me/clipboard/categories/` is a bare, unpaginated array (at most 50), `meta: {}`
- IDs: no changes this session
- Times: no changes this session
- List/search/filter/order params:
  - `GET /me/clipboard/`: `field_key` (comma list, exact match, each key lowercase dotted words, whole param ≤500), `category` (`<uuid>` or `none`), `search` (≤100, substring of label, text, or category name); filters combine with AND
  - entries ordered most-used first, then most-recently used (never-used last), then newest; categories by name ignoring case; no ordering parameter
- HTTP status: `POST /me/clipboard/` and `POST /me/clipboard/categories/` return 201; clipboard deletes return 200 with a body, never 204
- Throttling: clipboard endpoints use the project default per-user rate (1000/hour)

## 3. Models
- **ClipboardEntry** `{ id, label, text, field_key, category?:{ id, name }, usage_count:int, last_used_at?, created_at, updated_at }`
  - `field_key` is `""` when unset; otherwise an opaque lowercase dotted key (`^[a-z0-9_]+(\.[a-z0-9_]+)*$`, ≤100)
  - `category` is read as `{ id, name }` but written as a UUID string or `null`
  - `usage_count` / `last_used_at` change only through `use`; `use` also moves `updated_at`
- **ClipboardCategory** `{ id, name, entry_count:int, created_at, updated_at }`
  - names unique per account ignoring case
- **Clipboard delete result** `{ deleted:bool, entries_uncategorized?:int }`
  - entry delete returns `{ deleted: true }`; category delete adds `entries_uncategorized`

## 4. Enums
- No enum changes to existing resources.
- Central audit `action` values written by clipboard writes (visible through the `audit` module): `clipboard_entry_created` | `clipboard_entry_updated` | `clipboard_entry_deleted` | `clipboard_category_created` | `clipboard_category_updated` | `clipboard_category_deleted`; `entity_type`: `authenticate.clipboard_entry` | `authenticate.clipboard_category`

## 5. Dependency order
- Every `me/clipboard/*` endpoint needs a session (`POST /login/` first).
- Entry `update` / `delete` / `use` need an entry id from the list or a save response.
- Category `update` / `delete` need a category id from the category list.
- Filing an entry in a category needs a category id — optional; an entry may have none.
- **Start here:** `POST /api/v1/auth/me/clipboard/` with `{ label, text }`.

## 6. Endpoints

### Clipboard entries — `/api/v1/auth/me/clipboard/`
**Use it when:** the personal clipboard panel — list, search, save, edit, and remove saved snippets, and fetch suggestions for a document form field.
**Methods:**
- GET `/api/v1/auth/me/clipboard/`
- POST `/api/v1/auth/me/clipboard/`
- PATCH `/api/v1/auth/me/clipboard/<entry_id>/`
- DELETE `/api/v1/auth/me/clipboard/<entry_id>/`
**Send (create/update):**
- create: `label` (required, ≤120), `text` (required, ≤2000), `field_key` (optional, ≤100, lowercase dotted words), `category` (optional UUID or `null`, one of your own)
- update: any subset of `label`, `text`, `field_key`, `category`; `field_key: ""` clears it; `category: null` uncategorizes
**Returns:** ClipboardEntry | list[ClipboardEntry]; delete → Clipboard delete result
**Notes:**
- owner-only for every authority; no sharing, no applicant-linked entries
- there is no single-entry `GET`
- create checks run: `VALIDATION_ERROR` → `AUTH_CLIPBOARD_CATEGORY_INVALID` → `AUTH_CLIPBOARD_LIMIT_REACHED`
- `PATCH` checks the entry exists before validating the body
- label and text are trimmed; whitespace-only values are rejected; duplicates are allowed
- delete is permanent; the audit log records the entry id and `field_key`, never label or text
**Errors:**
- `AUTH_CLIPBOARD_ENTRY_NOT_FOUND` (404) — the id is not one of yours
- `AUTH_CLIPBOARD_LIMIT_REACHED` (400) — 200 entries already
- `AUTH_CLIPBOARD_CATEGORY_INVALID` (400) — `category` is not one of yours
- `VALIDATION_ERROR` (400) — field rules, malformed `field_key`, or a bad list filter

### Clipboard entry use — `/api/v1/auth/me/clipboard/<entry_id>/use/`
**Use it when:** the user copies or inserts an entry, so it ranks higher next time.
**Methods:**
- POST `/api/v1/auth/me/clipboard/<entry_id>/use/`
**Send (create/update):** none
**Returns:** ClipboardEntry with `usage_count` + 1 and `last_used_at` set to now
**Notes:**
- not audited; concurrent calls are counted correctly
**Errors:**
- `AUTH_CLIPBOARD_ENTRY_NOT_FOUND` (404) — the id is not one of yours

### Clipboard categories — `/api/v1/auth/me/clipboard/categories/`
**Use it when:** grouping snippets ("Ward office", "Bank") and filtering the clipboard by group.
**Methods:**
- GET `/api/v1/auth/me/clipboard/categories/`
- POST `/api/v1/auth/me/clipboard/categories/`
- PATCH `/api/v1/auth/me/clipboard/categories/<category_id>/`
- DELETE `/api/v1/auth/me/clipboard/categories/<category_id>/`
**Send (create/update):**
- create / rename: `name` (required, ≤60) — rename is not partial
**Returns:** ClipboardCategory | list[ClipboardCategory] (bare, unpaginated); delete → Clipboard delete result with `entries_uncategorized`
**Notes:**
- deleting a category keeps its entries, now `category: null`
- a case-only rename of a category's own name is allowed; renaming to the identical name records nothing
- on create, a name clash is reported before the limit
**Errors:**
- `AUTH_CLIPBOARD_CATEGORY_NOT_FOUND` (404) — the id is not one of yours
- `AUTH_CLIPBOARD_CATEGORY_NAME_TAKEN` (400) — you already have that name (any case)
- `AUTH_CLIPBOARD_CATEGORY_LIMIT_REACHED` (400) — 50 categories already
- `VALIDATION_ERROR` (400) — missing, blank, or too-long `name`

## 7. Flows
**Save and reuse a snippet**
1. `POST /api/v1/auth/me/clipboard/` with `{ label, text }` → 201 ClipboardEntry.
   - `AUTH_CLIPBOARD_LIMIT_REACHED` → offer to delete old entries.
2. `GET /api/v1/auth/me/clipboard/?search=<text>` → most-used first.
3. User copies an entry → `POST /api/v1/auth/me/clipboard/<entry_id>/use/`.
   - `AUTH_CLIPBOARD_ENTRY_NOT_FOUND` → deleted elsewhere; refetch the list.

**Fill a document form field from the clipboard**
1. A field with a client-defined key gains focus → `GET /api/v1/auth/me/clipboard/?field_key=father.name`.
   - Empty page → offer "save this value" (`POST /api/v1/auth/me/clipboard/` with that `field_key`).
2. User picks a suggestion → insert its `text`, then `POST /api/v1/auth/me/clipboard/<entry_id>/use/`.

**Organise snippets into categories**
1. `POST /api/v1/auth/me/clipboard/categories/` with `{ name }` → 201 ClipboardCategory.
   - `AUTH_CLIPBOARD_CATEGORY_NAME_TAKEN` / `AUTH_CLIPBOARD_CATEGORY_LIMIT_REACHED` → pick another name / delete one.
2. `PATCH /api/v1/auth/me/clipboard/<entry_id>/` with `{ category: <category_id> }`.
   - `AUTH_CLIPBOARD_CATEGORY_INVALID` → refetch the category list.
3. `GET /api/v1/auth/me/clipboard/?category=<category_id>` or `?category=none`.
4. `DELETE /api/v1/auth/me/clipboard/categories/<category_id>/` → `{ deleted: true, entries_uncategorized: n }`.

## 8. Gaps
- Not built: sharing between accounts, team or applicant-scoped entries, multi-field "fill a whole form" sets, import/export, list ordering parameter, per-entry encryption at rest.
- The `field_key` vocabulary is not defined or published by the backend — a frontend convention.
- Clipboard audit is not best-effort: if the central audit write fails, the clipboard write returns `INTERNAL_SERVER_ERROR` (500) and nothing is saved (safe to retry).
- The stale gap "central audit app not built" was removed from this contract this session.

## Core

## 1. Module
- Name: Core (project-level conventions)
- Base path: `/api/v1/`
- Auth: unchanged this session

## 2. Conventions
- Error: the worked `VALIDATION_ERROR` envelope's `message` is `"Validation failed."` (previously shown as `"Invalid input."`)
- Auth failures: no changes this session
- Access models: now **seven** shapes — adds **Personal, every account** (`authenticate` clipboard, `/api/v1/auth/me/clipboard/`): Lead Manager own entries only, Superadmin **yes — own entries only**; the only row granting a Superadmin anything in a business-facing feature
- 404 for out-of-scope records: now three resources — `leads`, `notifications`, and the `authenticate` clipboard (plus Admin-only-owner files in `uploaded_files`)
- An applicant's assignee is not an access control: `applicants` stays shared; `assigned_to` only routes notifications and filters the list
- Domain events: `leads`, `applicants`, and `documents` writes now raise alerts in `notifications`; the alert exists before the write's response is returned (visible on the recipients' next poll); a notification failure never fails the write; there is no client-facing event stream, webhook, or endpoint listing events
- Pagination: no changes this session
- IDs: no changes this session
- Times: no changes this session
- List/search/filter/order params: no changes this session
- App inventory wording updated: `leads` (soft delete, General/Visit notes), `applicants` (identity numbers, education, language tests, notes, Admin-only restore, optional assignee), `documents` (prefill read), `notifications` (event alerts, categories, preferences, 90-day purge — no longer "nothing is ever deleted"), `reminders` (applicant reminder alerts also reach the assignee)
- `education` and `test_scores` were folded into `applicants` (`educations`, `language_tests`) rather than built as modules

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes to resource creation order.
- New app-level edges: `documents` → `uploaded_files` (service call — certificate photo check, prefill photo); `applicants` → `authenticate` (service call — assignee lookup); `notifications` → `leads` / `applicants` / `documents` (domain-event receiver).

## 6. Endpoints
- No endpoint changes in this module.

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Document History

## 1. Module
- Name: Document History
- Base path: `/api/v1/document-history/`
- Auth: unchanged this session (Admin only)

## 2. Conventions
- No changes this session.

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints

### Snapshot recovery — `/api/v1/document-history/snapshots/<snapshot_id>/recover/`
**Use it when:** restoring a printed body into the working document.
**Methods:**
- POST `/api/v1/document-history/snapshots/<snapshot_id>/recover/`
**Send (create/update):** none — request unchanged
**Returns:** Document (detail shape, `documents` module) — unchanged
**Notes:**
- the frozen body goes back verbatim, without the `student-certificate` content check `documents` now applies on save, so no `DOCUMENTS_CONTENT_INVALID` can arise here; the next ordinary save of that document is checked again
**Errors:**
- none new

## 7. Flows
- No new flows.

## 8. Gaps
- None new this session.

## Document Templates

## 1. Module
- Name: Document Templates
- Base path: `/api/v1/document-templates/`
- Auth: unchanged this session (Admin only)

## 2. Conventions
- No changes this session.

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint changes this session.

## 7. Flows
- No new flows.

## 8. Gaps
- A document now carries its own `template_version` (the layout it was authored for, `documents` module), separate from the version a print snapshot records as printed; this module still holds no template version chain, and that version is an opaque label, not a reference to anything here.

## Documents

## 1. Module
- Name: Documents
- Base path: `/api/v1/documents/`
- Auth: unchanged this session (Admin only, reads included)

## 2. Conventions
- Response: no changes this session
- Error: a `student-certificate` body that breaks its rules returns `DOCUMENTS_CONTENT_INVALID` with `error.details.content` (list) and `error.details.fields` mapping each failing path inside `content` (e.g. `marking[2].present`) to one message string
- Auth failures: no changes this session; `DOCUMENTS_ACTOR_FORBIDDEN` now applies to all ten endpoints
- Pagination: no changes this session
- IDs: no changes this session
- Times: on a Document only `archived_at` carries a `_bs` sibling (unchanged); the prefill adds `date_of_birth_bs`, `test_date_bs`, `expiry_date_bs`
- Nullability: on the prefill a `?` field is always present but may be `null` (e.g. `father: null`, never missing)
- List/search/filter/order params: document list adds `include_archived` (boolean, default `false`); archived documents are hidden unless `status=archived` or `include_archived=true`; `include_archived` is ignored when `status` is given
- Immutable on `PATCH`: `status_before_archive` joins the `DOCUMENTS_STATUS_IMMUTABLE` set
- `content` is still never altered; only `student-certificate` content is now checked on write

## 3. Models
- **Document (detail shape)** — adds `template_version` (opaque ASCII label `^[A-Za-z0-9._-]{1,20}$`, default `"1"`; new Woda letters use `"2"`)
- **WorkspaceSummary** `{ applicant_id, applicant_name, document_count, archived_count, last_updated }`
  - `archived_count` is new; `document_count` counts live (`draft`/`ready`) documents; an applicant whose documents are all archived now appears with `document_count: 0`; `last_updated` spans archived documents too
- **DocumentPrefill** `{ applicant:PrefillApplicant, father?:PrefillRelative, mother?:PrefillRelative, grandfather?:PrefillRelative, grandmother?:PrefillRelative, educations:[Education], language_tests:[LanguageTest], photo_media_id?:uuid }`
  - **PrefillApplicant** `{ first_name, middle_name, last_name, full_name, gender:[enum], date_of_birth?, date_of_birth_bs?:BsDate, nationality, citizenship_no, citizenship_issue_district, national_id_no, passport_no, permanent_address?:PrefillAddress, current_address?:PrefillAddress, primary_email, primary_phone }` — name parts split from `full_name` (first word, middle words, last word); `passport_no` is `""` with no passport
  - **PrefillAddress** `{ province, district, municipality, ward_no, tole, formatted }`
  - **PrefillRelative** `{ name, citizenship_no, occupation }` — the most recently added family member of that relationship
  - **Education** / **LanguageTest** — the `applicants` shapes without `id` and `source_lead_id`
  - `photo_media_id` — the applicant's newest photograph that is neither archived nor replaced, or `null`

## 4. Enums
- `student-certificate` content (validated keys, snake_case):
  - `gender`: `male` | `female` | `other` | `""`
  - `grades.grammar` / `listening` / `conversation` / `reading` / `composition`: `A` | `B` | `C` | `D` | `""`
  - `study_type`: `0` (studying) | `1` (completed)

## 5. Dependency order
- `DocumentPrefill` needs an `Applicant` `(external module: applicants)`; its richer parts need family, educations, and language tests entered there, and a photograph uploaded `(external module: uploaded_files)`.
- A `student-certificate` `content.photo_media_id` needs a non-archived `photograph` file uploaded for the document's own applicant `(external module: uploaded_files)`.
- **Start here:** unchanged — obtain an applicant id, then `POST /api/v1/documents/`.

## 6. Endpoints

### Document — `/api/v1/documents/`
**Use it when:** the applicant documents panel and the document workspace.
**Methods:**
- GET `/api/v1/documents/`
- POST `/api/v1/documents/`
- GET `/api/v1/documents/<document_id>/`
- PATCH `/api/v1/documents/<document_id>/`
**Send (create/update):**
- create adds: `template_version` (optional; a JSON number is accepted and stored as a string)
- update adds: `template_version`
- `student-certificate` `content` (all optional, `null` skips, unknown keys kept):
  - `firstname`, `middlename`, `lastname`, `course_name`, `branch_name` — string ≤150; `address` ≤300; `course_level`, `branch_no` ≤50
  - `date_of_birth`, `date_of_admission`, `date_of_completion`, `issue` — `YYYY-MM-DD` or `""`; `date_of_completion` ≥ `date_of_admission`
  - `course_books` — list of ≤20 strings, each ≤150
  - `course_total_days` — whole number 0–1000; `course_hours_per_day` — number or numeric string 0–24
  - `marking` — list of ≤12 `{ month: "YYYY-MM" (unique), total_days, class_hr, present, absent, attendance_percentage? }`; `present + absent ≤ class_hr` (all hours)
  - `photo_media_id` — UUID or `null`; not allowed on a standalone document
  - `instructor_id`, `director_id` — not checked
**Returns:** Document (detail shape) | list[Document (list shape)]
**Notes:**
- **Behaviour change:** omitting `status` now returns `draft` and `ready` only; `status=archived` lists only archived; `include_archived=true` lists everything
- every other template's `content` is still opaque (Woda `show_ref_no`, `show_dispatch_no`, `dispatch_no` stored as sent)
- global search (`search` module) still returns archived documents, flagged `is_archived`
**Errors:**
- `DOCUMENTS_CONTENT_INVALID` (400) — now also a `student-certificate` body breaking its rules; `error.details.fields`
- `VALIDATION_ERROR` (400) — e.g. malformed `template_version` or non-boolean `include_archived`

### Document workspaces — `/api/v1/documents/workspaces/`
**Use it when:** the Documents landing table — applicants who have documents, with live and removed counts.
**Methods:**
- GET `/api/v1/documents/workspaces/`
**Send (create/update):** none
**Returns:** list[WorkspaceSummary]
**Notes:**
- link a row with `document_count: 0` to `GET /api/v1/documents/?applicant=<id>&status=archived` so removed documents can be restored
**Errors:**
- none new

### Document status — `/api/v1/documents/<document_id>/status/`
**Use it when:** marking a document ready or back to draft.
**Methods:**
- POST `/api/v1/documents/<document_id>/status/`
**Send (create/update):** none — request unchanged
**Returns:** Document (detail shape)
**Notes:**
- moving to `ready` raises a `document_ready` notification to every other active Admin, never a Lead Manager or the caller; `draft` or a re-send raises nothing
**Errors:**
- none new

### Document archive — `/api/v1/documents/<document_id>/archive/`
**Use it when:** the workspace "remove"/"delete" action.
**Methods:**
- POST `/api/v1/documents/<document_id>/archive/`
**Send (create/update):** none — request unchanged (`reason` required)
**Returns:** Document (detail shape)
**Notes:**
- allowed from `draft` and `ready`; remembers the current status for restore
- the document now drops out of the default list (still reachable with `?status=archived` / `?include_archived=true`, and counted in `archived_count`)
**Errors:**
- none new

### Document restore — `/api/v1/documents/<document_id>/restore/`
**Use it when:** undoing a removal.
**Methods:**
- POST `/api/v1/documents/<document_id>/restore/`
**Send (create/update):**
- `reason` (optional, ≤2000) — recorded on the `document_restored` history event; an empty body is fine
**Returns:** Document (detail shape), `status` back to its pre-archive value (`draft` or `ready`; `draft` for documents archived before 2026-10-29)
**Notes:**
- previously always returned `draft`
**Errors:**
- `VALIDATION_ERROR` (400) — `reason` longer than 2000 characters

### Document prefill — `/api/v1/documents/prefill/<applicant_id>/`
**Use it when:** opening a new Woda letter, student certificate, or other applicant-owned document form, and the clipboard's "From applicant" group.
**Methods:**
- GET `/api/v1/documents/prefill/<applicant_id>/`
**Send (create/update):** none
**Returns:** DocumentPrefill
**Notes:**
- Admin only; read-only; records no audit event
- does not fill `content` — mapping prefill fields to template keys is the form's job
- every part degrades to `""`, `null`, or `[]` when not entered
**Errors:**
- `DOCUMENTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id (the same code is 400 on document create)

## 7. Flows
**Remove a document and bring it back**
1. `POST /api/v1/documents/<document_id>/archive/` with a reason → `status: "archived"`.
2. The document disappears from `GET /api/v1/documents/?applicant=<id>`; it is listed by `?status=archived`, and the workspace row's `archived_count` rises.
3. `POST /api/v1/documents/<document_id>/restore/` (optional `{ reason }`) → back to `draft` or `ready`, editable.

**Fill a new letter from the applicant's file**
1. `GET /api/v1/documents/prefill/<applicant_id>/` → names, identity numbers, addresses, parents, grandparents, education, tests, photo.
   - `DOCUMENTS_APPLICANT_NOT_FOUND` → wrong applicant id.
   - `null` parent or address → prompt the user, or complete the applicant via `PATCH /api/v1/applicants/<id>/` (module `applicants`).
2. Map values onto the template's content keys, then `POST /api/v1/documents/` with `content` and `template_version`.

**Save a student certificate**
1. `PATCH /api/v1/documents/<document_id>/` with the complete `content`.
   - `DOCUMENTS_CONTENT_INVALID` → mark each key in `error.details.fields` on the form.
2. `POST /api/v1/documents/<document_id>/status/` with `ready` → the other Admins receive `document_ready`.

## 8. Gaps
- Reading the prefill leaves no audit trace, although it returns citizenship, passport, and family identity numbers.
- Prefill has no `name_native` or `honorific`; name parts are a word split of `full_name` (compound surnames split wrongly); `photo_media_id` is a convention, not a designated primary photo.
- The certificate photo is checked only at save time; a photograph archived later is not detected until the next save of `content`.
- Global search still returns archived documents.
- The frontend's `/documents/clipboard/` (applicant / shared / personal scopes) maps to `authenticate`'s personal clipboard at `/api/v1/auth/me/clipboard/` — personal only; no shared or applicant scope.

## Leads

## 1. Module
- Name: Leads
- Base path: `/api/v1/leads/`
- Auth: unchanged (Admin all leads; Lead Manager own leads). New this session: delete and restore are Admin only; `?deleted=true` is Admin only

## 2. Conventions
- Response: no changes this session
- Error:
  - every write on a soft-deleted lead returns 409 `LEADS_LEAD_DELETED`
  - `LEADS_STUDY_INTEREST_INVALID` → `error.details.fields` maps `study_interest.<field>`; `LEADS_CERTIFICATE_INVALID` → maps `language_certificates[i].<field>`
- Auth failures: no changes this session
- Pagination: no changes this session; the notes list adds `meta.counts` = `{ general, visit }`
- IDs: no changes this session
- Times: `LeadNote.noted_at` carries `noted_at_bs`; a `noted_at` without an offset is read as Nepal time; the detail shape adds `deleted_at` / `deleted_at_bs`
- List/search/filter/order params:
  - lead list adds `highest_qualification_level`, `language_test_status` (exact, from the study interest), `language_test_type` (leads holding at least one such certificate, each once), `deleted` (`true` → only deleted leads, Admin only)
  - deleted leads are hidden from every list, global search, and dashboard figure
  - notes list: `category`, `ordering` (`-noted_at` default | `noted_at` | `-created_at`), `page`, `page_size`

## 3. Models
- **StudyInterest** — adds `{ highest_qualification_level:[enum], academic_score?, academic_score_type:[enum], pass_year?:int, pass_year_calendar:[enum] }`
  - `highest_qualification` keeps its free-text meaning (programme or stream); `academic_score` comes with `academic_score_type`, `pass_year` with `pass_year_calendar`
- **LanguageCertificate** `{ id, test_type:[enum], overall_score?, listening_score?, reading_score?, writing_score?, speaking_score?, test_date?, test_date_bs?:BsDate, certificate_number, expiry_date?, expiry_date_bs?:BsDate, created_at, updated_at }`
- **Lead (detail shape)** — adds `{ language_certificates:[LanguageCertificate], deleted_at?, deleted_at_bs?:BsDate, deleted_by?:UserBrief, delete_reason }`
  - only an Admin ever receives a lead with `deleted_at` set
- **LeadNote** `{ id, category:[enum], body, noted_at, noted_at_bs:BsDate, is_backdated:bool, author:UserBrief, updated_by?:UserBrief, created_at, updated_at }`
  - `category`, `noted_at`, `noted_at_bs`, `is_backdated`, `updated_by`, `updated_at` are new

## 4. Enums
- StudyInterest.highest_qualification_level: `see` | `plus_two` | `diploma` | `bachelor` | `master` | `phd` | `other` | `""`
- StudyInterest.academic_score_type: `gpa` | `percentage` | `""`
- StudyInterest.pass_year_calendar: `bs` | `ad` | `""`
- LanguageCertificate.test_type: `ielts` | `pte` | `toefl` | `duolingo` | `other`
- LeadNote.category: `general` | `visit` (may gain values, e.g. `call`)
- HistoryEntry.action: adds `lead_note_updated` | `lead_note_deleted` | `lead_deleted` | `lead_restored`

## 5. Dependency order
- `LeadNote` needs a live (not deleted), unconverted `Lead` to be written; it can be read on any lead in scope.
- `LanguageCertificate` needs `Lead` — sent nested in the lead payload.
- Restoring needs a deleted lead (find it with `GET /api/v1/leads/?deleted=true`).
- **Start here:** unchanged.

## 6. Endpoints

### Lead — `/api/v1/leads/`
**Use it when:** the lead list and lead form — now with qualification detail, language certificates, and new filters.
**Methods:**
- GET `/api/v1/leads/`
- POST `/api/v1/leads/`
- GET `/api/v1/leads/<lead_id>/`
- PATCH `/api/v1/leads/<lead_id>/`
**Send (create/update):**
- `study_interest` adds: `highest_qualification_level`, `academic_score` + `academic_score_type` (gpa 0–4, percentage 0–100), `pass_year` + `pass_year_calendar` (BS 2000…this BS year + 1, AD 1950…this year + 1)
- `language_certificates[]` (optional, ≤10): `test_type` (required), `overall_score`, `listening_score`, `reading_score`, `writing_score`, `speaking_score` (IELTS 0–9 in 0.5 steps, PTE 10–90, TOEFL 0–120, Duolingo 10–160, other ≥0), `test_date` (not in the future), `certificate_number`, `expiry_date` (after `test_date`)
- update: any subset; `language_certificates` replaces the whole set, `[]` clears
**Returns:** Lead (detail shape) | list[Lead (list shape)]
**Notes:**
- score/type and year/calendar pairs are checked against the record after a partial update
- create raises a `lead_created` notification to every active Admin except the caller
- retrieving a deleted lead: Admin 200 with `deleted_at` set; Lead Manager 404, even their own
- `?deleted=true` from a Lead Manager → 403 `LEADS_ACTOR_FORBIDDEN`
**Errors:**
- `LEADS_STUDY_INTEREST_INVALID` (400) — unpaired or out-of-range score/year
- `LEADS_CERTIFICATE_INVALID` (400) — a certificate rule
- `LEADS_CERTIFICATE_LIMIT` (400) — more than 10 certificates
- `LEADS_LEAD_DELETED` (409) — `PATCH` on a deleted lead
- `VALIDATION_ERROR` (400) — e.g. `?deleted=maybe`

### Lead delete — `/api/v1/leads/<lead_id>/`
**Use it when:** an Admin removes a duplicate, spam, or test lead.
**Methods:**
- DELETE `/api/v1/leads/<lead_id>/`
**Send (create/update):**
- `reason` (required, ≤500) — JSON body of the `DELETE`
**Returns:** Lead (detail shape) with `deleted_at`, `deleted_at_bs`, `deleted_by`, `delete_reason` set (HTTP 200)
**Notes:**
- soft delete — nothing is erased; the lead leaves lists, search, and dashboards; its owner can no longer see it
- not the same as `lost`
- raises a `lead_deleted` notification to the owner and every active Admin except the caller
**Errors:**
- `LEADS_ACTOR_FORBIDDEN` (403) — not an Admin
- `LEADS_LEAD_NOT_FOUND` (404) — no such lead, or another Lead Manager's
- `LEADS_LEAD_ALREADY_CONVERTED` (409) — converted leads cannot be deleted
- `LEADS_LEAD_DELETED` (409) — already deleted
- `VALIDATION_ERROR` (400) — `reason` missing, blank, or too long

### Lead restore — `/api/v1/leads/<lead_id>/restore/`
**Use it when:** an Admin undoes a lead deletion from the "deleted leads" view.
**Methods:**
- POST `/api/v1/leads/<lead_id>/restore/`
**Send (create/update):**
- `reason` (optional, ≤2000)
**Returns:** Lead (detail shape) with `deleted_*` cleared
**Notes:**
- returns exactly as it was — stage, notes, history untouched
- raises a `lead_restored` notification to the owner and every active Admin except the caller
**Errors:**
- `LEADS_ACTOR_FORBIDDEN` (403) — not an Admin
- `LEADS_LEAD_NOT_FOUND` (404) — no such lead (always, for a Lead Manager on a deleted lead)
- `LEADS_LEAD_NOT_DELETED` (409) — the lead is not deleted

### Lead lifecycle actions — stage / follow-up / lost / reopen
**Use it when:** moving a lead through its lifecycle (unchanged use).
**Methods:**
- POST `/api/v1/leads/<lead_id>/stage/`
- POST `/api/v1/leads/<lead_id>/follow-up/`
- POST `/api/v1/leads/<lead_id>/lost/`
- POST `/api/v1/leads/<lead_id>/reopen/`
**Send (create/update):** none — requests unchanged
**Returns:** Lead (detail shape)
**Notes:**
- a follow-up with a `note` creates a `general` note dated now
**Errors:**
- `LEADS_LEAD_DELETED` (409) — the lead is deleted (all four)
- `LEADS_LEAD_ALREADY_CONVERTED` (409) — follow-up only: a `note` sent for a converted (since reopened) lead

### Lead convert — `/api/v1/leads/<lead_id>/convert/`
**Use it when:** an Admin converts a lead into an applicant plus journey.
**Methods:**
- POST `/api/v1/leads/<lead_id>/convert/`
**Send (create/update):** none
**Returns:** `{ lead, applicant_id, journey_id }` — unchanged
**Notes:**
- copies every live note onto the applicant (same category, text, author, `noted_at`, original `created_at`, plus `source_lead_id`); the lead's notes become read-only
- when `highest_qualification_level` is set, creates one applicant education record; every certificate becomes an applicant language test; each carries `source_lead_id`
- the new applicant is assigned to the lead's owner, or unassigned if that person is no longer an active Admin or Lead Manager
- `language_test_status`, `interest_notes`, multiple countries, and a level-less `highest_qualification` still land in the journey's `notes`
- raises a `lead_converted` notification to the owner and every active Admin except the caller
**Errors:**
- `LEADS_LEAD_DELETED` (409) — the lead is deleted

### Lead Note — `/api/v1/leads/<lead_id>/notes/`
**Use it when:** the notes panel on the lead detail page — "General" and "Visit" tabs.
**Methods:**
- GET `/api/v1/leads/<lead_id>/notes/`
- POST `/api/v1/leads/<lead_id>/notes/`
- PATCH `/api/v1/leads/<lead_id>/notes/<note_id>/`
- DELETE `/api/v1/leads/<lead_id>/notes/<note_id>/`
**Send (create/update):**
- create: `body` (required, ≤10 000, not blank), `category` (`general` default, or `visit`), `noted_at` (optional, default now; never more than 5 minutes in the future)
- update: any subset of `category`, `body`, `noted_at`
**Returns:** LeadNote | list[LeadNote] (with `meta.counts`); `data: null` for delete
**Notes:**
- notes are **no longer append-only**: edit and delete need the author or an Admin; delete is soft
- writes need a lead that is not deleted and not converted
- a `visit` note raises `visit_note_added` to the lead's owner unless the owner wrote it; general notes, edits, and deletes raise nothing
- `DELETE` on the list path still returns 405
**Errors:**
- `LEADS_LEAD_NOT_FOUND` (404) — no such lead in scope (or deleted, for a Lead Manager)
- `LEADS_NOTE_NOT_FOUND` (404) — no such note, or it was deleted
- `LEADS_NOTE_FORBIDDEN` (403) — not the author and not an Admin
- `LEADS_NOTE_FUTURE_DATE` (400) — `noted_at` later than now + 5 min
- `LEADS_LEAD_ALREADY_CONVERTED` (409) — any note write on a converted lead
- `LEADS_LEAD_DELETED` (409) — any note write on a deleted lead
- `VALIDATION_ERROR` (400) — blank or over-long `body`, unknown `category` or `ordering`

### Lead History — `/api/v1/leads/<lead_id>/history/`
**Use it when:** the lead timeline (unchanged use).
**Methods:**
- GET `/api/v1/leads/<lead_id>/history/`
**Send (create/update):** none
**Returns:** list[HistoryEntry]
**Notes:**
- a deleted lead's history is readable by an Admin only
**Errors:**
- none new

## 7. Flows
**Delete and restore a lead** (Admin only)
1. `DELETE /api/v1/leads/<lead_id>/` with `{ reason }` → `deleted_at` set.
   - `LEADS_LEAD_ALREADY_CONVERTED` → converted leads cannot be deleted.
2. The lead vanishes from `GET /api/v1/leads/`, search, and dashboards; its owner gets 404.
3. `GET /api/v1/leads/?deleted=true` → the deleted-leads view.
4. `POST /api/v1/leads/<lead_id>/restore/` with optional `{ reason }` → back as it was.

**Write and correct notes**
1. `POST /api/v1/leads/<lead_id>/notes/` with `{ category: "visit", body, noted_at }` → capture `note.id`.
   - `LEADS_NOTE_FUTURE_DATE` → fix the date picker.
   - `LEADS_LEAD_ALREADY_CONVERTED` → post on the applicant instead.
2. `GET /api/v1/leads/<lead_id>/notes/?category=visit` → the Visit tab; `meta.counts` feeds both badges.
3. `PATCH` / `DELETE /api/v1/leads/<lead_id>/notes/<note_id>/`.
   - `LEADS_NOTE_FORBIDDEN` → show edit/delete only on own notes (Admins: all).

**Convert a lead (changed tail)**
1. `POST /api/v1/leads/<lead_id>/convert/` → `applicant_id`, `journey_id`.
2. `GET /api/v1/applicants/<applicant_id>/` (module `applicants`) → `assigned_to` is the lead's owner (or `null`); `educations` / `language_tests` carry the lead's qualification and certificates.
3. `GET /api/v1/applicants/<applicant_id>/notes/` (module `applicants`) → the copied notes; continue writing notes there.

## 8. Gaps
- `language_test_status`, and a `highest_qualification` with no level, still convert to journey free text.
- No hard delete anywhere; no duplicate detection on create (a deleted lead with the same number does not warn).
- A converted lead that was reopened still counts as converted: it cannot be deleted and its notes stay read-only.

## Notifications

## 1. Module
- Name: Notifications
- Base path: `/api/v1/notifications/`
- Auth: unchanged rule (Admin and Lead Manager; Superadmin 403), now over **nine** endpoints; every endpoint acts on the caller's own notifications **and own preferences** only

## 2. Conventions
- Response: no changes this session; preferences messages `"Preferences retrieved."` / `"Preferences updated."`
- Error:
  - validation `error.details` keys may now be body field names (`category` on `read-all/`, `categories` / `assigned_only` on `PATCH /preferences/`); the message is always `"Validation failed."`
- Auth failures: now documents `AUTHENTICATION_FAILED` (401) for an expired, malformed, or revoked-session token beside `AUTHENTICATION_REQUIRED` (401) for no token
- Success statuses: still `200` everywhere — the first `PATCH /preferences/` creates stored preferences but answers 200
- Pagination: no changes (page-number; cursor pagination was requested and declined)
- IDs: no changes this session
- Times: no changes this session
- List/search/filter/order params:
  - feed adds `category` — one or more category values, comma-separated (the only multi-value parameter); unknown value → 400
  - feed adds `applicant_id` — exact match; rows before 2026-10-29 and non-applicant types carry `null` and never match
  - `/summary/` validates but ignores `category`; read `by_category` instead
- Methods: `/preferences/` accepts only `GET` and `PATCH` (`PUT` → 405)
- Delivery: event alerts are written synchronously after the triggering write commits (not queued), visible on the next poll; no push, websocket, SSE, or long-poll
- Retention: the nightly sweep deletes event alerts (any status) and resolved deadline alerts older than 90 days (default); dismissed and active deadline alerts are kept

## 3. Models
- **Notification** — adds `{ category:[enum], applicant_id?, payload:json }`
  - `category` is derived from `notification_type`, never stored
  - `applicant_id` is the applicant the alert is about, else `null`; `null` on every row raised before 2026-10-29
  - `payload` is an object, never `null`, holding non-sensitive ids and enum strings; keys by type: `journey_stage_changed` / `journey_closed` → `stage`; `test_score_expiring` → `test_type`; `lead_converted` → `applicant_id`; `applicant_status_changed` → `from`, `to`, `originating_lead_id`; `applicant_restored` → `from` (`archived`), `to`, `originating_lead_id`; `visit_note_added` → `note_id`; `document_ready` → `family`; every other type `{}`
  - new source triples: `custom_reminder` → `reminders` / `reminder`; `test_score_expiring` → `applicants` / `language_test` (path is the applicant); `lead_*` → `leads` / `lead`; `applicant_*` → `applicants` / `applicant`; `visit_note_added` → `leads` or `applicants` / `lead` or `applicant` (path is the notes feed); `document_ready` → `documents` / `document`
- **FeedSummary** `{ unread, active, by_priority:json, by_due_bucket:json, by_category:json }`
  - `by_category` is new: keyed by all eleven categories, zero-filled; counts unread in any status; `unread` equals its sum
- **NotificationPreferences** `{ categories:json, assigned_only }`
  - `categories` keyed by every category, each `{ in_app: boolean }`; `assigned_only` boolean
  - defaults: every category `in_app: true`, `assigned_only: false`
  - decides which alerts are **created** from now on; never hides, deletes, or restores existing alerts
  - no `id`, no owner field

## 4. Enums
- Notification.notification_type: adds `lead_created` | `lead_converted` | `lead_deleted` | `lead_restored` | `applicant_status_changed` | `applicant_restored` | `applicant_assigned` | `applicant_unassigned` | `visit_note_added` | `document_ready`
- Notification.category: `lead` | `applicant_status` | `journey` | `assignment` | `notes` | `follow_up` | `documents` | `checklist` | `offer` | `file` | `expiry`
- Category mapping:
  - `lead` — `lead_created`, `lead_converted`, `lead_deleted`, `lead_restored`
  - `applicant_status` — `applicant_status_changed`, `applicant_restored`
  - `journey` — `journey_stage_changed`, `journey_closed`
  - `assignment` — `assignment_received`, `applicant_assigned`, `applicant_unassigned`
  - `notes` — `visit_note_added`
  - `follow_up` — `custom_reminder`, `appointment_reminder`
  - `documents` — `document_ready`
  - `checklist` — `checklist_item_due`, `checklist_item_overdue`, `missing_documents`, `missing_information`
  - `offer` — `offer_response_due`, `offer_expired`, `offer_decided`
  - `file` — `file_rejected`
  - `expiry` — `passport_expiring`, `test_score_expiring`
- `test_score_expiring` is now produced; only `missing_information` and `appointment_reminder` remain unproduced
- Priority additions: `lead_restored`, `applicant_unassigned`, `visit_note_added` → `low`; other new types → `normal`
- Notification.source_app (observed, open): adds `reminders` | `leads` | `documents`
- Notification.source_entity_type (observed, open): adds `reminder` | `language_test` | `lead` | `applicant` | `document`

## 5. Dependency order
- A `Notification` may now also come from a `reminders`, `leads`, or `documents` source `(external modules)`.
- `NotificationPreferences` needs only the calling user `(external module: authenticate)`; it always exists from the client's view (defaults).
- Set preferences before the alerts they should filter are raised — they never apply retroactively.
- **Start here:** unchanged — `GET /api/v1/notifications/summary/`, then `GET /api/v1/notifications/?status=active`; `GET /api/v1/notifications/preferences/` backs a settings screen.

## 6. Endpoints

### Notification — `/api/v1/notifications/`
**Use it when:** the inbox, a per-category tab via `?category=`, and the per-applicant alert history via `?applicant_id=`.
**Methods:**
- GET `/api/v1/notifications/`
- GET `/api/v1/notifications/<id>/`
**Send (create/update):** none
**Returns:** Notification | list[Notification]
**Notes:**
- routing (server-side): applicant-related alerts (`passport_expiring`, `test_score_expiring`, journey alerts, applicant `custom_reminder`) reach every Admin plus the applicant's assignee; `applicant_status_changed` / `applicant_restored` reach the assignee and every Admin, or every Admin and Lead Manager when unassigned; applicant visit notes reach the assignee only, or every Admin and Lead Manager when unassigned; lead visit notes reach the lead's owner; `lead_created` → every Admin; other `lead_*` → owner and every Admin; `applicant_assigned` → new assignee; `applicant_unassigned` → previous assignee; `document_ready` → every Admin; client reminders → every Admin
- the actor of a `leads` / `applicants` / `documents` event (and of `file_rejected`) is never notified; a deactivated assignee counts as no assignee
- a muted category is never written for that user; `assigned_only` drops alerts about applicants not assigned to them (not `applicant_assigned` / `applicant_unassigned`)
- a dismissed event alert is purged after 90 days like any event alert; a dismissed deadline alert is kept
- a new alert arriving between page requests shifts later pages by one row
**Errors:**
- `VALIDATION_ERROR` (400) — now also an unknown category

### Notification summary — `/api/v1/notifications/summary/`
**Use it when:** the bell badge and the per-category tab badges; this is also the "unread count" endpoint.
**Methods:**
- GET `/api/v1/notifications/summary/`
**Send (create/update):** none
**Returns:** FeedSummary (now with `by_category`)
**Notes:**
- every feed parameter is validated, only `due_within_days` changes the result
**Errors:**
- `VALIDATION_ERROR` (400) — `due_within_days` outside 1–365, or any other feed parameter with an invalid value

### Mark all read — `/api/v1/notifications/read-all/`
**Use it when:** "mark all as read", globally or on one category tab.
**Methods:**
- POST `/api/v1/notifications/read-all/`
**Send (create/update):**
- no body, `{}`, or `{ category: "" }` — clears everything unread
- `{ category: "<category>" }` — clears only that category; one category per call (a comma list is an unknown value → 400)
**Returns:** BulkReadResult
**Errors:**
- `VALIDATION_ERROR` (400) — `category` is not one of the eleven values

### Notification preferences — `/api/v1/notifications/preferences/`
**Use it when:** the notification settings screen — per-category switches and an "only my applicants" toggle.
**Methods:**
- GET `/api/v1/notifications/preferences/`
- PATCH `/api/v1/notifications/preferences/`
**Send (create/update):**
- `categories` (optional) — any subset of category keys, each `{ in_app: boolean }`; unsent categories keep their setting
- `assigned_only` (optional boolean)
**Returns:** NotificationPreferences — always the full set
**Notes:**
- GET never creates anything; the first PATCH creates the stored preferences
- not audited; changes nothing already in the feed or in `/summary/` counts until new alerts arrive
**Errors:**
- `VALIDATION_ERROR` (400) — unknown category key (e.g. `details: { categories: ["Unknown categories: case_journey."] }`) or a value not shaped `{ in_app: boolean }`

## 7. Flows
**Per-category inbox tabs**
1. `GET /api/v1/notifications/summary/` → one tab per category badged from `by_category.<category>`; "All" from `unread`.
2. Open a tab → `GET /api/v1/notifications/?category=<category>&status=active` (a combined tab may send `?category=lead,applicant_status,notes`).
   - 400 `VALIDATION_ERROR` naming `category` → client bug.
3. "Mark all read" on that tab → `POST /api/v1/notifications/read-all/` with `{ category }` → `{ marked_read: n }`; one call per category for a combined tab.

**Setting my notification preferences**
1. `GET /api/v1/notifications/preferences/` → render switches from `categories.*.in_app` and the toggle from `assigned_only`.
2. `PATCH /api/v1/notifications/preferences/` with `{ categories: { <category>: { in_app: false } } }` → re-render from the response.
   - 400 under `details.categories` → unknown key; client bug.
3. `PATCH /api/v1/notifications/preferences/` with `{ assigned_only: true }`.
4. Existing alerts stay; skipped alerts do not reappear when a category is turned back on.

**Reviewing everything about one applicant**
1. `GET /api/v1/notifications/?applicant_id=<applicant_id>` → the caller's alerts about that applicant.
   - Misses rows raised before 2026-10-29 and rows older than the retention window.

## 8. Gaps
- History is deleted after 90 days for most alerts; the window is an operator setting not exposed through the API; no archive or undo.
- Muting is lossy and leaves no trace.
- `applicant_id` is `null` and `payload` is `{}` on every alert raised before 2026-10-29.
- `payload` is identical for every recipient (never sensitive); richer detail requires following `source_api_path`.
- Checklist `assignment_received` is the routing exception: it does not exclude the assigner and does not skip deactivated accounts.
- Checklist, offer, and journey alerts carry no actor, so an Admin who moves a journey or decides an offer receives that alert themselves.
- Requested and declined: cursor pagination, a dedicated `unread-count/` endpoint, server-sent events, and a `case_journey` category.
- Event delivery has no queue and no retry; a failed alert write is never surfaced to any client.
- Still no ordering parameter, no search, no snooze or un-dismiss, no email/SMS.

## Reminders

## 1. Module
- Name: Reminders
- Base path: `/api/v1/reminders/`
- Auth: unchanged this session

## 2. Conventions
- Routing of the due alert: a due **applicant** reminder's `custom_reminder` alert now reaches every active Admin **plus that applicant's assignee** (who may be a Lead Manager); client reminders still go to Admins only. This is `notifications` routing and restricts nothing here
- At most one `custom_reminder` per **recipient** per reminder per due date (previously stated per Admin)
- All other conventions: no changes this session

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint or shape changes this session. The create/reschedule side effect now names the applicant's assignee as an additional recipient of the due alert.

## 7. Flows
**Act on a due alert** (cross-app: notifications)
1. A `custom_reminder` notification appears in each Admin's feed, and the applicant's assignee's for an applicant reminder (`GET /api/v1/notifications/`); `source_api_path` is `/api/v1/reminders/<id>/`.
2. `GET /api/v1/reminders/<id>/` → the note and its owning record.
3. `POST /api/v1/reminders/<id>/complete/` (or `/dismiss/`) → terminal; the next sweep resolves the alert.

## 8. Gaps
- A Lead Manager receives a due alert only for an applicant reminder on an applicant assigned to them; their reminders on unassigned applicants, applicants assigned to others, and clients surface nowhere automatically — the reminder's author is not a recipient.

## Uploaded Files

## 1. Module
- Name: Uploaded Files
- Base path: `/api/v1/files/`
- Auth: unchanged this session

## 2. Conventions
- No changes this session.

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- A file of category `photograph` uploaded with `applicant=<id>` is what a `student-certificate` document's `content.photo_media_id` must name `(external module: documents)` — non-archived and owned by the certificate's own applicant.

## 6. Endpoints
- No endpoint changes this session.

## 7. Flows
- No new flows.

## 8. Gaps
- A certificate's `photo_media_id` is an id inside a document body, not a link: archiving or replacing that photograph later does not touch the certificate and is detected only on the certificate's next save.
- The documents prefill picks the applicant's newest current, non-archived photograph by convention; nothing in this module designates a primary photograph.
