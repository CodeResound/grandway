# Data Contract — Documents

**Owner app:** `documents`
**Version:** 1.2.0
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the editable document working record — identity, ownership, template association, status, and the entered source data. It does **not** own the immutable print snapshot (`document_history`), the template catalogue or its signatories (`document_templates`), supporting files (`uploaded_files`), or the person (`applicants`). `document_history`, `document_templates`, and `uploaded_files` all now exist. **This model still holds no reference to a file** — attaching one is a call to `/api/v1/files/` with `document=<id>`, and nothing here knows it happened. It owns no history table — a document's history is the central `audit` log filtered to that document.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial contract — one model, `Document` |
| 1.0.1 | 2026-07-24 | AI (Claude) | No schema change. Recorded `document_history` as an inbound dependency and restated why `printed` stays absent |
| 1.0.2 | 2026-07-24 | AI (Claude) | No schema change. `document_templates` shipped: recorded it as an inbound dependency that imports this app's family enum, slug validator, and key/family rule but holds no database relation. **Corrected the slug count from 42 to 53** and stated why the signature-FK omission is now deliberate rather than forced |
| 1.0.3 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. Recorded that a document still holds no file reference: attachments are reached from `/api/v1/files/?document=<id>` |
| 1.1.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Schema change** (migration `0002_template_version_status_before_archive`): `template_version` (default `"1"`) and `status_before_archive` (restore returns to it). `student-certificate` `content` is now validated on write — the first and only template the backend looks inside; §2 documents the rules in snake_case. New runtime dependency on `uploaded_files` for the certificate photo check |
| 1.2.0 | 2026-10-29 | AI (Claude Opus 5.5) | §3 DocumentPrefill read model (no table) |

---

## The rule that governs this app

**The backend is not the rendering engine.** `content` is stored exactly as received and returned exactly as stored. Every display value — per-row running balances, debit and credit totals, closing balance, the automatic interest and tax rows, amount-in-words — is computed by the frontend at render time and is **never** persisted, injected, or recalculated here (`concepts/documents.txt` — "Document input data"; `frontend_data-contract.md` — "Bank documents").

Nothing in this app *alters* `content`. Every template's body is checked to be a JSON object under the size cap; a `student-certificate` body is additionally checked against the keys its frontend specified (§2, `validators.validate_template_content`) and then stored exactly as sent. No other template's body is read.

---

## Deliberate Deviations

`concepts/documents.txt` leaves eight questions open. Three were settled with the project owner, one was settled by the project's own state, and the rest are recorded as still open in the concept file. Each departure from the concept or from `CLAUDE.md` is recorded here.

- **Access is Admin-only, reads included — a deliberate override of the concept file.** Flow 1 of `concepts/documents.txt` says "An Admin or Lead Manager opens an applicant record". The project owner has since ruled that Lead Managers get no visibility into document content whatsoever. That instruction supersedes the concept (§36 — concept files are a living draft, not a rulebook), and the concept file carries a correction note. This makes `documents` the **first app in the project where a Lead Manager is denied outright**. See `docs/SECURITY.md` §1.
- **The frontend slugs are not a backend enum.** The concept's final open question asks whether they are canonical types or template keys; they are template keys. The backend owns a stable six-value `family` enum and stores `template_key` as a format-validated string. Onboarding a new bank partner is a row, not a migration — and that call has since paid off: `document_templates` shipped, took over the slug registry, and cost this app no migration, no enum change, and no code change at all. The two fields must agree (`bank-vyas-statement` requires family `bank_statement`), checked by prefix and, for the two bank families, suffix. `document_templates` **imports** that rule and the `family` enum rather than redeclaring either (§4), so the catalogue can never accept a pairing this app would reject.

  **A count correction.** Earlier versions of this document said "42 slugs" and "a shipped 42-value enum", inherited from `frontend_data-contract.md`, whose heading reads "DocumentType (42 slugs)". **That file's own list contains 53** — 4 student, 11 woda, 11 lor, 5 moi, and 22 bank (11 institutions × statement and certificate). The number 42 appears to be stale in the source. `document_templates/seed_data.py` transcribes all 53 and records the discrepancy; it is worth confirming against the real template set, because if 42 is right then eleven of those slugs name templates the frontend cannot render.
- **Three statuses, not the concept's five.** `active` is dropped as a synonym for `draft`. **`printed` is deliberately absent**, and remains so now that `document_history` is built. When this app shipped the reason was that nothing could set it; the reason now is that nothing *should*. Capturing a snapshot does not touch this field: "has been printed" is derivable from the version chain, and storing a second denormalized answer here would create something that can drift from the first. The frontend's `submitted` maps to `ready` — nothing in Grandway submits a document anywhere.
- **`content` is an unvalidated JSON object — except for `student-certificate`.** §5 requires a contract for every data object, and 52 of the 53 template shapes cannot have a *server-enforced* one: every one is open (`Record<string, unknown> &`) and required to preserve unknown keys. Their shapes are documented below for reference and enforced by the frontend that renders them. A serializer that named fields would silently drop the keys a template it has never heard of depends on. **`student-certificate` became the exception on 2026-10-29**: its form now covers every printed field and the frontend specified those keys and asked for them to be checked (`updates.md` §7.1). The rules are lenient so older bodies keep saving — nothing required, unknown keys kept — and live in the service layer, so they still never drop or rewrite a key (§2).
- **Derived values are neither computed nor stripped.** If a client posts `statement_debit_total`, it is stored and returned. Stripping would violate "preserve any extra keys" and would require the backend to know all 53 shapes. Recorded as a real gap in `docs/INTEGRATION.md` §9 — such a value must not be trusted as truth.
- **`label` is a single English field (§39.1)**, like every name in the project. It is operational shorthand chosen from a template picker ("Vyas Statement", "Certificate"). **Unicode normalization (§39.2) applies in full**, and `label` is trigram-indexed for search.
- **No history table**, for the same reason as every other app: `audit` already provides an immutable append-only log and §4 forbids duplicating it.
- **No supporting-file link, no signature FK, and no snapshot field.** The first belongs to an app that does not exist. The second is now a deliberate omission rather than a forced one: `document_templates` ships a real `Signatory` table, and `content.instructorId` / `content.directorId` name rows in it — but they stay opaque strings inside the JSON, unvalidated, because validating them would mean parsing `content` per template shape, which is precisely what this app refuses to do. The third is different: `document_history` **does** exist, and the absence of a field here is the design. The FK points the other way — snapshots reference documents, not the reverse — so this table carries no snapshot count, no `last_printed_at`, and no `printed` status. Everything about a document's print history is answered by asking that app.
- **No delete.** The frontend's `DELETE /documents/:id` has no counterpart — `concepts/documents.txt`: "No document deletion that erases history. Retire, archive, or restore instead."

---

## 1. Document

**Purpose:** The editable working record staff prepare in the document workspace. Answers "what is being written, for whom, from which template, and where has it got to".
**Table:** `documents_document`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → `applicants.Applicant` | No | Yes | No | `PROTECT`. Null for a standalone document |
| standalone_purpose | Text | No | No | No | Why a document with no applicant exists. Required exactly when `applicant` is null |
| family | CharField(20) | Yes | No | No | The stable document class; indexed |
| template_key | CharField(100) | Yes | No | No | The frontend's template slug; indexed |
| label | CharField(255) | Yes | No | No | What staff call it |
| content | JSONField | No | No | No | The entered source data, **stored verbatim**; defaults to `{}`. `student-certificate` bodies are validated (§2) |
| template_version | CharField(20) | No | No | No | Layout version the document was authored for; default `"1"`; ASCII `^[A-Za-z0-9._-]{1,20}$`, not checked against a list. Editable while not archived |
| status | CharField(20) | No | No | No | Defaults to `draft`; indexed |
| notes | Text | No | No | No | |
| created_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| archive_reason | Text | No | No | No | Required to archive; cleared on restore |
| status_before_archive | CharField(20) | No | No | Yes | Status held when archived (`draft`/`ready`); set by archive, read and cleared by restore; `""` otherwise. Not settable through update. Not in any response |
| archived_at | DateTime | No | Yes | Yes | Stamped by the archive action |
| archived_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`family`** — `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate`. Defined in `documents/constants.py` `DocumentFamily`. Bank documents split into two families because a statement and a certificate have different content shapes, different derived values, and different screens; one family would make `family` useless for the one thing it exists for, which is knowing what shape `content` is in.
- **`status`** — `draft` | `ready` | `archived`. `DocumentStatus`. See "Deliberate Deviations" for why there is no `printed`.
- **`status_before_archive`** — `draft` | `ready` | `""`. Never `archived`.

**Validation Rules:**

- Exactly one of `applicant` / `standalone_purpose` must be present → `DOCUMENTS_OWNER_REQUIRED`. Enforced on create **and** on update, so a standalone document cannot have its purpose cleared.
- `template_key` matches `^[a-z0-9]+(?:-[a-z0-9]+)*$` (`documents/validators.py`) — lowercase ASCII slug, no leading, trailing, or doubled hyphen, never Devanagari (§39.7).
- `template_key` must agree with `family`: prefix `student-`, `woda-`, `lor-`, `moi-`, or `bank-`, plus suffix `-statement` / `-certificate` for the two bank families → `DOCUMENTS_TEMPLATE_KEY_INVALID`.
- For `student-certificate`, `content` must satisfy the §2 rules → `DOCUMENTS_CONTENT_INVALID`, with every failing path in `error.details.fields`. Not applied to snapshot recovery (`document_history`), which restores a printed body verbatim.
- `template_version` matches `^[A-Za-z0-9._-]{1,20}$` → `VALIDATION_ERROR`.
- `content` must be a JSON **object** → `DOCUMENTS_CONTENT_INVALID`, and must serialize under **262 144 bytes (256 KiB)** → `DOCUMENTS_CONTENT_TOO_LARGE`. A bank statement carries an unbounded transaction array; this cap is roughly a two-thousand-row statement, far beyond any real document and small enough that a runaway client is caught early.
- **`applicant`, `family`, and `template_key` are immutable after creation** → `DOCUMENTS_OWNERSHIP_IMMUTABLE`. Changing any of them would turn one record into a different document while keeping its id, its history, and any future snapshot that referenced it.
- **`status` (and `status_before_archive`) is not settable through update** → `DOCUMENTS_STATUS_IMMUTABLE`. It moves through the status, archive, and restore actions. Both immutability rules **reject** rather than silently drop, matching `offers` and `clients` rather than `institutions`.
- **An archived document is not editable** → `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409) on update or status change. Restore first, so that "archived, then edited" is always two visible events rather than a silent amendment.
- The status action may set only `draft` or `ready` → `DOCUMENTS_STATUS_INVALID_TRANSITION`; `archived` requires the archive action, which demands a reason.
- Archiving requires a reason → `DOCUMENTS_ARCHIVE_REASON_REQUIRED`, and stores the current status in `status_before_archive`. Restore returns to that status, or to `draft` when it is blank (documents archived before 2026-10-29). Restore takes an optional reason (≤2000), recorded on its audit event.
- `label`, `notes`, `standalone_purpose`, and `archive_reason` are Unicode-normalized on write (§39.2). **`content` is not walked or normalized** — that would be the backend touching the document body.

**Derived, read-only:** `is_standalone` (no applicant), `is_archived`, `is_editable` (not archived).

**Indexes:**

- `(applicant, -updated_at)` — `document_applicant_recent_idx`. The Applicant Detail documents panel.
- `(status, -updated_at)` — `document_status_recent_idx`. The worklist filtered by status.
- `(family, -updated_at)` — `document_family_recent_idx`. "Every bank statement we hold".
- GIN trigram on `label` — `document_label_trgm_idx`. The `?search=` lookup (§39.6). `pg_trgm` already exists from `leads` migration 0002.

Ordering is `-updated_at` — a worklist reads most-recently-touched first, and the frontend's "last updated" column depends on it. This is the opposite of `clients`, which is alphabetical, and of every other app, which is `-created_at`.

**Soft Delete:** `N/A — no deletion at all.` No document is ever deleted and there is no delete endpoint or delete service, enforced by a test that fails if one appears (`tests/test_services.py::NothingIsDeletedTests`). A document that is no longer current is archived with a mandatory reason and kept. `applicant` and `created_by` are both `PROTECT`, so **an applicant who has documents on file cannot be removed** — whatever a client may assume about deleting a person cascading to their documents.

**Cross-App Dependencies:**

- `applicants.Applicant` — nullable `PROTECT` FK, `related_name="documents"`. Read only: this app never writes to an applicant, and creating or archiving a document does not touch their status.
- `authenticate.User` — FKs for `created_by` (`PROTECT`) and `archived_by` (`SET_NULL`).
- `audit` — service call. Every mutation appends one event. **The document body never appears in it** — see below.
- `uploaded_files` — **runtime read (service call), no FK**, since 2026-10-29. `validators._check_photo` resolves a `student-certificate`'s `content.photo_media_id` through `uploaded_files.selectors.get_file_by_id` and requires a non-archived `photograph` owned by the same applicant. Imported inside the function: `uploaded_files` already holds an FK to `Document` (`UploadedFile.document`), so a module-level import both ways would be an import cycle. Recorded in `docs/INTEGRATION.md` §2 and `uploaded_files/docs/DATA_CONTRACT.md`.
- **Referenced by: `document_history`.** Both of its models hold `PROTECT` FKs to `Document` (`related_name="snapshots"` and `related_name="print_events"`), so **a document with print history cannot be deleted** — which changes nothing today, since this app has no delete at all. It also **writes** to this app: `document_history.services.recover_snapshot` calls this app's `update_document` to push a frozen `label` and `content` back into the working record. That write goes through the service rather than the model, so this app's archive lock, size cap, and redacted audit event all still apply, and a recovery appears in this app's history as an ordinary `document_updated` event. The full account is in `document_history/docs/DATA_CONTRACT.md` §3.

**Audit redaction — a contract detail, not an implementation note.** Every mutation appends one `audit.AuditEvent`, and the `changes` map records each changed field's previous and new value **except `content`**, which is replaced by the literal marker `<changed>`. The document body routinely holds bank balances, account numbers, and full transaction histories, and the audit log is readable by every Admin and Superadmin through the `audit` app — a change map carrying the old and new body would leak it there (§17). The history therefore records *that* the body changed and who changed it, never what it said. Covered by `tests/test_services.py::ContentNeverReachesTheAuditLogTests`.

**Example:**

```json
{
  "id": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071",
  "applicant": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819",
  "applicant_name": "राम बहादुर",
  "is_standalone": false,
  "standalone_purpose": "",
  "family": "bank_statement",
  "template_key": "bank-vyas-statement",
  "label": "Vyas Statement",
  "template_version": "1",
  "content": {
    "statement_account_holder": "Ram Bahadur",
    "statement_account_no": "0123456789012",
    "statement_account_type": "Savings",
    "statement_opening_balance": 250000,
    "statement_interest": "5.5",
    "statement_tax": "5",
    "transactions": [
      { "date": "2026-04-01", "description": "Deposit", "credit": 500000 },
      { "date": "2026-05-12", "description": "Withdrawal", "debit": 120000 }
    ],
    "statement_spokesperson": "Sunita Shrestha"
  },
  "status": "draft",
  "is_archived": false,
  "is_editable": true,
  "notes": "",
  "archive_reason": "",
  "archived_at": null,
  "archived_at_bs": null,
  "archived_by_username": null,
  "created_by_username": "adminuser",
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T09:18:47Z"
}
```

Note what is **absent** from `content` and must stay absent: no per-row `balance`, no `statement_debit_total`, no `statement_credit_total`, no closing balance, no interest or tax rows, no amount-in-words. All are derived at render time.

---

## 2. `content` shapes, per family — reference only, except `student-certificate`

**Not enforced by this backend — except `student-certificate`, whose rules follow the list.** Reproduced from `frontend_data-contract.md` so a maintainer can see what the body is expected to hold. Every shape is open: unknown keys are preserved. The authoritative version is the frontend's own contract, where these shapes are compiled-in TypeScript types. `document_templates` now holds the slug **catalogue** — which slugs exist and are offered — but deliberately **not** these shapes: they are frontend code and no endpoint could usefully describe them. See that app's `DATA_CONTRACT.md` "Deliberate Deviations".

- **`student`** — `student-certificate` is **validated** (rules below). The three `student-cv-*` slugs use `CvContent` (identity, passport, IELTS scores, `experiences[]`, `educations[]`, `family_members[]`, `gradings[]`).
- **`woda`** — `WodaContent`: `wodadoc_refno`, `wodadoc_date`, `applicant_name`, plus arbitrary per-slug keys.
- **`lor`** — `LorContent`: reference numbers, institution and recommender blocks, `para_1`…`para_4`, plus template-specific academic fields.
- **`moi`** — `MoiContent`: reference numbers, institution block, student and signatory blocks, plus template-specific academic fields.
- **`bank_statement`** — `BankStatementContent`, **input fields only**: account holder, number, type, reference, date range, `statement_opening_balance`, `statement_interest` (annual rate %), `statement_tax` (rate % on interest), `transactions[]` of `{ date, description, debit?, credit? }`, spokesperson.
- **`bank_certificate`** — `BankCertificateContent`, **input fields only**: account holder, number, type, reference, end date, `statement_interest`, `statement_total_balance` (NPR), `statement_usdrate`, spokesperson.

**`student-certificate` — the one validated shape** (`validators.validate_template_content`, since 2026-10-29). Keys are **snake_case**, as the frontend sends them. An absent key or `null` skips its check, inside `marking` rows too; **nothing is required**; unknown keys pass and are kept — including the older contract's camelCase `studyType`, `instructorId`, `directorId`, `batch`, `studentName`, `program`, `nationality`, and the legacy hours key `coursehour`/`course_hours`, which existing documents still hold.

| Key | Rule |
|---|---|
| `firstname`, `middlename`, `lastname` | string ≤150 |
| `date_of_birth`, `date_of_admission`, `date_of_completion`, `issue` | `YYYY-MM-DD` or `""`; `date_of_completion` ≥ `date_of_admission` |
| `gender` | `male` \| `female` \| `other` \| `""` |
| `address` | string ≤300 |
| `course_name` / `course_level` | string ≤150 / ≤50 |
| `course_books` | list of ≤20 strings, each ≤150 |
| `course_total_days` | whole number 0–1000 |
| `course_hours_per_day` | number or numeric string, 0–24 (replaces `coursehour`) |
| `marking` | list of ≤12 `{ month: "YYYY-MM" (unique), total_days: int ≥0, class_hr, present, absent: number ≥0, attendance_percentage?: 0–100 }`; `present + absent ≤ class_hr` — all three are **hours** |
| `grades` | object; `grammar`, `listening`, `conversation`, `reading`, `composition` each `A` \| `B` \| `C` \| `D` \| `""` |
| `photo_media_id` | UUID or `null`; a non-archived `uploaded_files` file of category `photograph` owned by this document's applicant; not allowed on a standalone document |
| `branch_name` / `branch_no` | string ≤150 / ≤50 |
| `study_type` | `0` (studying) \| `1` (completed) |
| `instructor_id`, `director_id` | not checked (signatory references, see below) |

Print-time derived values (`total_class_hours`, `attendance_percentage`) are not stored here: like bank totals they travel in the snapshot's client-supplied `render_context.computed` (`document_history`).

**Signature references.** `content.instructorId` and `content.directorId` on certificate templates name `document_templates.Signatory` records by id. That table **now exists** — fetch the picker from `GET /api/v1/document-templates/signatories/?status=active`. They are nonetheless still stored and returned as opaque strings inside `content`, and **nothing validates them**: this app does not look inside the body, so a typo, a stale id, or the id of a `draft` signatory are all accepted. A document may still reference a signatory that never existed. Closing that would mean parsing `content` per template shape, which is exactly what this app refuses to do.

---

## 3. DocumentPrefill (no table — read model)

**Purpose:** The applicant's file shaped for document forms (Woda letters, certificates). Computed on every request from `applicants` and `uploaded_files`; nothing is stored, nothing is audited.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| applicant | object | No | `first_name`, `middle_name`, `last_name` (split from `full_name`), `full_name`, `gender`, `date_of_birth` (+`_bs`), `nationality`, `citizenship_no`, `citizenship_issue_district`, `national_id_no`, `passport_no` (`""` when none), `permanent_address`/`current_address` (each `{province, district, municipality, ward_no, tole, formatted}` or null; `tole` ← `street_address`), `primary_email`, `primary_phone` |
| father / mother / grandfather / grandmother | object | Yes | `{name, citizenship_no, occupation}` of the newest `FamilyMember` with that relationship |
| educations | list | No | The applicant's education records (applicants `DATA_CONTRACT.md` §10), without `id`/`source_lead_id` |
| language_tests | list | No | The applicant's language tests (§11), with `test_date_bs`/`expiry_date_bs` |
| photo_media_id | UUID | Yes | Newest `uploaded_files` file of category `photograph` for the applicant that is neither archived nor superseded — a convention, not a stored choice |

**Validation Rules:** none — read-only.
**Soft Delete:** N/A — a read model; it stores nothing.
**Deliberately absent:** `name_native` (§39.1: names are English-only) and `honorific` (needs marital status, which is not stored).
**Cross-App Dependencies:** `applicants` (selector `get_applicant_by_id`), `uploaded_files` (selectors `get_files`, `filter_files`, imported in the function — that app already depends on this one).
