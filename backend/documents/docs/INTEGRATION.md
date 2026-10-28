# Integration — Documents

**Owner app:** `documents`
**Version:** 1.5.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial integration contract — 9 endpoints, one resource |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint change. `document_history` moved from "missing" to a documented consumer; print/recover gaps closed |
| 1.0.2 | 2026-07-24 | AI (Claude) | No endpoint change. `document_templates` moved from "missing" to a documented consumer. Restated the signatory and template-registry gaps precisely — both libraries now exist and **this module still validates neither** — and corrected the slug count to 53 |
| 1.0.3 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. Moved `uploaded_files` from the missing-apps table to the now-exists list and named the calls a client makes instead |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | History entries gained `actor_id` (`documents.document.list_history` → 1.1.0). The shape is now owned by the `audit` module and shared by all six modules that expose a history endpoint; three of them, this one included, had been omitting `actor_id`. Additive, so no consumer breaks — and the body is still never present. §2 `Requires` corrected: the `audit` coupling is a read dependency as well as a write one |
| 1.2.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Archived documents are hidden from the list by default** (`include_archived=true` / `status=archived` to see them) — an approved in-place behaviour change. Restore returns the status held before archiving and accepts an optional `reason`. New `template_version` on the detail shape (create/PATCH). Workspaces gain `archived_count` and keep applicants whose documents are all archived. `student-certificate` content is now validated (lenient; `error.details.fields` names failing keys); `photo_media_id` must be the applicant's own photograph — new `uploaded_files` dependency in §2 |
| 1.3.0 | 2026-10-29 | AI (Claude Opus 5.5) | New **`GET /documents/prefill/<applicant_id>/`** (`documents.prefill.read`): the applicant's names, identity numbers, addresses, parents and grandparents, educations, language tests, and current photo, shaped for document forms. Admin only, read-only. §2 couplings to `applicants` and `uploaded_files` gain a read for it |
| 1.4.0 | 2026-10-29 | AI (Claude Opus 5.5) | No request or response change. **New side effect:** `POST /documents/<id>/status/` moving to `ready` raises a `document_ready` notification to the other Admins (`notifications` module); `documents.document.change_status` → 1.1.0. §2 records that this module depends on `notifications` for nothing |
| 1.5.0 | 2026-10-29 | AI (Claude Opus 5.5) | No endpoint change in this app. §9 Frontend contract reconciliation: the frontend's `/documents/clipboard/` (applicant / shared / personal scopes) maps to `authenticate`'s personal clipboard at `/api/v1/auth/me/clipboard/` — personal per account only |

---

## 1. Module

- **Name:** Documents — the editable document working record. Identity, ownership, template association, status, and the entered source data staff type into the document workspace. **The backend is not the rendering engine**: it stores the source data verbatim and the frontend renders it and computes every display value.
- **Base path:** `/api/v1/documents/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. **Admin authority only.** A `lead_manager` and a `superadmin` are both rejected with 403 on every route, reads included.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which is the whole access check here. | Every endpoint returns 401; any non-Admin gets 403 `DOCUMENTS_ACTOR_FORBIDDEN` everywhere. |
| `authenticate` | FK | `created_by` (`PROTECT`) and `archived_by` (`SET_NULL`) reference user accounts. | Documents could not record who created or archived them. |
| `applicants` | FK + service call | An applicant-owned document points at one, resolved through `applicants.selectors.get_applicant_by_id` on create. The prefill reads the whole applicant file through the same selector. | Only standalone documents could be created; `POST` returns 400 `DOCUMENTS_APPLICANT_NOT_FOUND` for any applicant id that does not resolve; prefill returns nothing. |
| `audit` | service call + read shape | Every mutation appends one immutable event. This module stores no history of its own: the history endpoint reads audit's selector and renders audit's shared entry shape. | Hard dependency in both directions of use — without it this module does not start. If only the write path failed, documents would still save but leave no trace of who changed what, and `GET /documents/<id>/history/` would return an empty list rather than an error. |
| `uploaded_files` | service call | A `student-certificate`'s `content.photo_media_id` is checked through `uploaded_files.selectors.get_file_by_id`: it must be a non-archived `photograph` owned by the document's own applicant. The prefill picks the applicant's current photo through `filter_files`. | Saving a certificate that names a photo fails with 500, and prefill's `photo_media_id` cannot be computed; every other template and every certificate without a photo is unaffected. |

**This module writes to nothing outside itself.** Creating, editing, or archiving a document does not touch the applicant's status or any other record. **It depends on `notifications` for nothing:** marking a document `ready` announces a domain event after commit, and `notifications` decides who is told; if it is absent or fails, the status change still succeeds and the response is identical.

**Three apps this module deliberately does not contain, and which now exist:**

- **`uploaded_files`** (`/api/v1/files/`) owns file storage, verification, and versioning. Since
  1.2.0 this module **reads** it in one place — the certificate photo check (§2). **A
  document still has no attachment field here** — attach a supporting file or a generated PDF by
  calling `POST /api/v1/files/` with `document=<document_id>`, and list them with
  `GET /api/v1/files/?document=<document_id>`. This module is not involved in either call and
  returns no file references.

- **`document_history`** (`/api/v1/document-history/`) owns immutable print snapshots and print
  events. It **consumes** this module — it holds `PROTECT` foreign keys to `Document` and performs a
  recovery through this module's own update service rather than writing directly — and this module
  depends on it for nothing. Printing, print history, reprinting, and recovering a previous body all
  live there; none of it is reachable from a `/api/v1/documents/` route.
- **`document_templates`** (`/api/v1/document-templates/`) owns the signatory library and the
  template-slug catalogue. The relationship runs the **opposite** way to `document_history` and is
  weaker in both directions: that module imports this one's `family` enum, slug validator, and
  key/family rule at the Python level, and holds **no foreign key to `Document`** at all. This module
  imports nothing from it and does not consult it.

**Consequences for a client of *this* module:**

- **A document may be referenced by snapshots you cannot see from here.** No field on the `Document`
  resource reports whether it has ever been printed, or how many times. Ask `document_history`.
- **`POST /api/v1/document-history/snapshots/<id>/recover/` can change a document underneath you**,
  writing its `label` and `content`. It appears in this module's history endpoint as an ordinary
  `document_updated` event, indistinguishable from a manual edit except by its timing next to the
  recovery. Refetch after a recovery rather than trusting a cached copy.
- **`PROTECT` now runs both ways with `document_history`.** A document with print history cannot be
  deleted — which changes nothing today, since this module has no delete at all.
- **The template catalogue is advisory and this module does not enforce it.** A `template_key` absent
  from `document_templates`, or present but retired, is still accepted by `POST /documents/`. Nothing
  changed about this module's validation when that one shipped. **Populate your picker from the
  catalogue and treat it as the only guard** — see §9.
- **A signatory picker now exists**, at
  `GET /api/v1/document-templates/signatories/?status=active`. Put the chosen record's `id` into
  `content.instructorId` / `content.directorId`. **This module still does not validate those ids** —
  see §9.

## 3. Conventions

- **Access — Admin only, and this is unlike every other module.** `admin` may do everything; `lead_manager` and `superadmin` are refused on **every route including `GET`**. Two other modules (`institutions`, `clients`) let a Lead Manager read but not write — **this one does not let them read.** A documents panel must be **hidden** for a Lead Manager, not rendered read-only or shown empty: an empty panel implies "this applicant has no documents", which is false.
- **The backend never alters the document body.** `content` is returned exactly as it was sent. It *checks* one template's body on write — `student-certificate` (§7) — and never another's. It computes no running balances, no debit/credit totals, no closing balance, no interest or tax rows, and no amount-in-words. It also does not **strip** them if you send them — see §9.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint**. A document that is no longer current is archived with a mandatory reason and kept forever.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is **abridged to three fields to show the envelope**; a real create returns the full `Document` shape defined in §4.

```json
{
  "success": true,
  "message": "Document created.",
  "data": { "id": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071", "label": "Vyas Statement", "status": "draft" },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract. Branch on the HTTP status and, for errors, on `error.code`.

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object that is always present — `{}` when there are no field-level errors.

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENTS_OWNERSHIP_IMMUTABLE",
    "message": "A document's owner, family, and template cannot be changed after creation.",
    "details": { "applicant": ["This field cannot be changed after creation."] }
  },
  "meta": {}
}
```

  Field-level serializer failures use the project-wide `VALIDATION_ERROR` with the offending fields in `details`:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { "template_key": ["Template key must be a lowercase ASCII slug: letters and digits in hyphen-separated segments, e.g. 'bank-vyas-statement'."] }
  },
  "meta": {}
}
```

  A `student-certificate` body that breaks its rules returns `DOCUMENTS_CONTENT_INVALID` with every failing key in `details.fields`, keyed by its path inside `content`:

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENTS_CONTENT_INVALID",
    "message": "Document content does not satisfy the 'student-certificate' template.",
    "details": {
      "content": ["Document content does not satisfy the 'student-certificate' template."],
      "fields": {
        "marking[2].present": "Present and absent hours together cannot exceed class hours.",
        "date_of_completion": "Must be on or after date_of_admission."
      }
    }
  },
  "meta": {}
}
```

- **HTTP status codes:** `POST /documents/` returns **201**. Every other success — `GET`, `PATCH`, status, archive, restore — returns **200**. Domain-rule violations are **400**, except state conflicts (editing an archived document, archiving twice, restoring an active one), which are **409**. Missing records named in the URL path are **404**. Authority failures are **403**. An unrouted method is **405** with the project-wide `METHOD_NOT_ALLOWED` code, still inside the standard envelope.
- **Auth failures:** 401 with no token, an expired token, or a revoked session. 403 `DOCUMENTS_ACTOR_FORBIDDEN` when the token is valid but the caller is not an Admin. Its body:

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENTS_ACTOR_FORBIDDEN",
    "message": "Admin authority is required to access documents.",
    "details": {}
  },
  "meta": {}
}
```

  **This code replaces the project-wide `PERMISSION_DENIED`, it does not coexist with it.** You will not see `PERMISSION_DENIED` from `/api/v1/documents/`. It is omitted from the per-endpoint `Errors` lists in §7, since it applies identically to all ten.

- **Immutable fields are REJECTED on `PATCH`, not ignored.** `applicant`, `family`, and `template_key` return 400 `DOCUMENTS_OWNERSHIP_IMMUTABLE`; `status`, `status_before_archive`, `archive_reason`, `archived_at`, and `archived_by` return 400 `DOCUMENTS_STATUS_IMMUTABLE`. Both list every offending field in `details`. **This differs from `institutions`**, which silently drops them — a read-modify-write-the-whole-object edit form carried across from that module will fail on every save. Send only the fields the user actually changed.
- **An archived document is frozen.** `PATCH` and the status action both return **409** `DOCUMENTS_DOCUMENT_NOT_EDITABLE` until it is restored. Archiving is not a soft-hide; it takes the record out of circulation.
- **A `PATCH` that changes nothing writes no audit event.** The response is still 200 with the unchanged record.
- **Query parameter encoding.** Invalid query parameters are **rejected with 400, not ignored** — `?family=banks` returns a validation error rather than an unfiltered result set. `standalone` and `include_archived` are booleans (`true`/`false`/`1`/`0`); omitting `standalone` returns both kinds, omitting `include_archived` hides archived documents. `page_size` above the 100 maximum is clamped.
- **Request encoding:** `application/json`.
- **Pagination:** page-number based. `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `next`/`previous` are absolute URLs or `null`. Applied to all three list endpoints (documents, workspaces, history).
- **IDs:** UUID strings. `template_key` is a human-readable slug but is **not** an identifier you can address a record by.
- **Ordering** is fixed and **not client-controllable** — there is no `sort` or `ordering` parameter. Documents are ordered by `-updated_at` (most recently touched first). Workspaces by `-last_updated`. History newest-first.
- **Times.** `created_at`, `updated_at`, and `archived_at` are ISO 8601 UTC. **On a Document, only `archived_at` carries a Bikram Sambat sibling**, `archived_at_bs` — an object or `null`, shaped `{ year, month, day, month_name, display }`. The prefill (§4 `DocumentPrefill`) adds `date_of_birth_bs`, `test_date_bs`, and `expiry_date_bs` in the same shape. Dates *inside* `content` are opaque frontend data and are never parsed, converted, or given a BS sibling.
- **Empty text fields are `""`, never `null`.** On a Document the nullable fields are `applicant`, `applicant_name`, `archived_at`, `archived_at_bs`, and `archived_by_username`. On the prefill, a `?` in §4 marks a field that is present but may be `null` — the key is always there, so `father` is `null`, never missing.

## 4. Models

**Document (list shape)** — `{ id, applicant?, applicant_name?, is_standalone, family:[enum], template_key, label, status:[enum], is_archived, created_at, updated_at }`

- **`content` is deliberately absent from the list.** A page of twenty bank statements would otherwise carry a megabyte of transaction rows nothing renders. Fetch the detail to get a body.
- `applicant` and `applicant_name` are both `null` on a standalone document.

**Document (detail shape)** — the list shape plus `{ content:json, template_version, standalone_purpose, notes, is_editable, archive_reason, archived_at?, archived_at_bs?:json, archived_by_username?, created_by_username }`

- Returned by retrieve, create, update, status, archive, **and** restore. Only the list returns the shorter shape.
- **`content` is whatever you stored.** Its shape depends on `family` and `template_key`; the backend never interprets it and validates only `student-certificate` (§7). Per-family shapes are reproduced for reference in `DATA_CONTRACT.md` §2, and the authoritative version is the frontend's own contract.
- **`template_version`** is the layout version the document was authored for — an opaque ASCII label up to 20 characters (`^[A-Za-z0-9._-]{1,20}$`), default `"1"`. Render with it. It is not checked against a list; new Woda letters are created with `"2"`. A print snapshot records what was actually printed in its own `render_context`.
- `archive_reason` is non-empty only when `status` is `archived`; restoring clears it.

**WorkspaceSummary** — `{ applicant_id, applicant_name, document_count, archived_count, last_updated }`

- One row per applicant who has **any** documents. `document_count` counts live ones (`draft`/`ready`) and `archived_count` removed ones, so an applicant whose documents are all archived still has a row with `document_count: 0`. **Standalone documents are excluded** (no applicant to group under). To list standalone documents use `GET /documents/?standalone=true`.
- `applicant_name` is the applicant's name.

**HistoryEvent** — `{ id, action, actor_type:[enum], actor_id:uuid|null, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`

- Owned by the `audit` module, where the same shape is called **AuditEventHistoryEntry** (`audit/docs/INTEGRATION.md` §4). This app renders it; it does not define it. Every module's `/history/` endpoint returns this identical shape.
- `actor_id` is the UUID of the acting user, or `null` for system/AI actors. Prefer it over `actor_label` when linking to an account — the label is a preserved snapshot of the username at the time and is not re-resolved if the account is renamed.
- `changes` maps field name to `{ "from": "...", "to": "..." }`, both stringified. `{}` on creation events.
- **A body change appears as `changes.content = { "from": "<changed>", "to": "<changed>" }`** — the literal marker, never the body. The document body is never written to the audit log (§17); it may hold account numbers and transaction histories, and the audit log is a separate, widely-readable store. **You cannot recover a previous body from the history.**

**DocumentPrefill** — `{ applicant:PrefillApplicant, father?:PrefillRelative, mother?:PrefillRelative, grandfather?:PrefillRelative, grandmother?:PrefillRelative, educations:[Education], language_tests:[LanguageTest], photo_media_id?:uuid }`

- **PrefillApplicant** — `{ first_name, middle_name, last_name, full_name, gender:[enum], date_of_birth?, date_of_birth_bs?:BsDate, nationality, citizenship_no, citizenship_issue_district, national_id_no, passport_no, permanent_address?:PrefillAddress, current_address?:PrefillAddress, primary_email, primary_phone }`
  - **Name parts are derived, not stored.** Grandway keeps one English `full_name` (no native-script name exists — there is no `name_native`). `first_name` is the first word, `last_name` the last, `middle_name` everything between; a one-word name has only `first_name`. Compound surnames split wrongly — keep the form fields editable.
  - Empty text is `""`, never `null`; `date_of_birth` is `YYYY-MM-DD` or `null`. `passport_no` is `""` when the applicant has no passport. `primary_phone` is the primary contact number (or the first one).
- **PrefillAddress** — `{ province, district, municipality, ward_no, tole, formatted }`. `tole` is the address's street line; `formatted` joins the non-empty parts as `tole, municipality-ward, district, province`. The address is `null` when the applicant has none of that type.
- **PrefillRelative** — `{ name, citizenship_no, occupation }`, or `null` when the file has no family member with that relationship. When several do, the most recently added one is used.
- **Education** / **LanguageTest** — the same fields as the applicant's `educations` / `language_tests` (`applicants/docs/INTEGRATION.md` §4), without `id` and `source_lead_id`.
- **`photo_media_id`** — an `uploaded_files` file id: the applicant's newest photograph that is neither archived nor replaced, or `null`. This is a **convention**: nothing designates a "primary" photo.

### Worked examples

**DocumentPrefill**

```json
{
  "applicant": {
    "first_name": "Ram", "middle_name": "Bahadur", "last_name": "Thapa", "full_name": "Ram Bahadur Thapa",
    "gender": "male", "date_of_birth": "2001-04-14",
    "date_of_birth_bs": { "year": 2058, "month": 1, "day": 1, "month_name": "Baisakh", "display": "2058 Baisakh 1" },
    "nationality": "Nepali", "citizenship_no": "27-01-75-12345", "citizenship_issue_district": "Kathmandu",
    "national_id_no": "", "passport_no": "PA1234567",
    "permanent_address": {
      "province": "Bagmati", "district": "Kathmandu", "municipality": "Kathmandu Metropolitan City",
      "ward_no": "10", "tole": "Baneshwor",
      "formatted": "Baneshwor, Kathmandu Metropolitan City-10, Kathmandu, Bagmati"
    },
    "current_address": null,
    "primary_email": "ram@example.com", "primary_phone": "9800000000"
  },
  "father": { "name": "Hari Thapa", "citizenship_no": "27-01-50-00001", "occupation": "Teacher" },
  "mother": null,
  "grandfather": { "name": "Shyam Thapa", "citizenship_no": "", "occupation": "" },
  "grandmother": null,
  "educations": [
    { "level": "bachelor", "qualification": "BBS", "institution": "Shanker Dev Campus", "country": "Nepal",
      "completion_status": "completed", "score": "3.45", "score_type": "gpa", "grading_system": "GPA (4.0)",
      "start_year": 2076, "completion_year": 2080, "year_calendar": "bs" }
  ],
  "language_tests": [
    { "test_type": "ielts", "overall_score": "7.0", "listening_score": "7.5", "reading_score": "6.5",
      "writing_score": "6.5", "speaking_score": "7.0", "test_date": "2025-03-01",
      "test_date_bs": { "year": 2081, "month": 11, "day": 17, "month_name": "Falgun", "display": "2081 Falgun 17" },
      "certificate_number": "25NP000123", "expiry_date": "2027-03-01",
      "expiry_date_bs": { "year": 2083, "month": 11, "day": 17, "month_name": "Falgun", "display": "2083 Falgun 17" } }
  ],
  "photo_media_id": "5e6f7081-9203-4b4c-8d5e-6f708192a3b4"
}
```

**Document (detail shape) — a bank statement**

```json
{
  "id": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071",
  "applicant": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819",
  "applicant_name": "Ram Bahadur Thapa",
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

**Note what is absent and must stay absent:** no per-row `balance`, no `statement_debit_total`, no `statement_credit_total`, no closing balance, no interest or tax rows, no amount-in-words. Compute all of them at render.

**Document (detail shape) — a standalone document, archived**

```json
{
  "id": "b2c3d4e5-6f70-4819-a2b3-c4d5e6f70819",
  "applicant": null,
  "applicant_name": null,
  "is_standalone": true,
  "standalone_purpose": "Office authorisation letter commissioned by the director.",
  "family": "woda",
  "template_key": "woda-address",
  "label": "Address Declaration",
  "template_version": "2",
  "content": { "wodadoc_refno": "WD-2083-014", "applicant_name": "Ram Bahadur", "show_ref_no": true, "show_dispatch_no": false, "dispatch_no": "" },
  "status": "archived",
  "is_archived": true,
  "is_editable": false,
  "notes": "",
  "archive_reason": "Superseded by the 2083 revision.",
  "archived_at": "2026-07-24T10:02:00Z",
  "archived_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name": "Shrawan",
    "display": "2083 Shrawan 8"
  },
  "archived_by_username": "adminuser",
  "created_by_username": "adminuser",
  "created_at": "2026-07-20T04:11:23Z",
  "updated_at": "2026-07-24T10:02:00Z"
}
```

## 5. Enums

- `Document.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate`
  - **This is the backend's type vocabulary — not the 53 slugs.** The slug lives in `template_key` and is a validated string, not an enum, so a new bank partner needs no backend deploy.
  - Bank documents are **two** families, not one: a statement and a certificate have different content shapes and different screens.
- `Document.status`: `draft` | `ready` | `archived`
  - **There is no `printed`, and there will not be one.** Print snapshots exist (`document_history`), but capturing one deliberately does not touch this field — "has been printed" is derivable from the version chain, and a second denormalized answer here could drift from it. Ask `GET /api/v1/document-history/documents/<document_id>/snapshots/` instead.
  - **There is no `submitted`** — the frontend's third value maps to `ready`. Nothing in Grandway submits a document anywhere.
  - `archived` is **not** reachable through the status action; it requires the archive endpoint and a reason.
- `template_key`: **not an enum** — a lowercase ASCII slug matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`, up to 100 characters, which must agree with `family` by prefix (`student-`, `woda-`, `lor-`, `moi-`, `bank-`) and, for the two bank families, by suffix (`-statement`, `-certificate`).
- `HistoryEvent.action`: `document_created` | `document_updated` | `document_status_changed` | `document_archived` | `document_restored`
- `HistoryEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai` — the `audit` module's enum. In practice only `admin` appears here, since only Admins can write.

## 6. Dependency order

- `Document` needs an `Applicant` **(external module: `applicants`)** — *unless* it is standalone, in which case it needs a `standalone_purpose` instead. Exactly one of the two.
- An `Applicant` needs nothing from this module.

- `DocumentPrefill` needs an `Applicant` **(external module: `applicants`)**; its richer parts need the applicant's family, educations, and language tests to have been entered there, and a photograph uploaded in `uploaded_files`.

**Start here:** for an applicant-owned document, obtain the applicant id from `GET /api/v1/applicants/` (or the file you are already viewing), then `POST /api/v1/documents/`. For a standalone document you can post immediately with a `standalone_purpose` — no prerequisite record at all.

## 7. Endpoints

### Document — `/api/v1/documents/`

**Use it when:** the Document List worklist, the Applicant Detail documents panel (`?applicant=`), the standalone documents list (`?standalone=true`), the Document Workspace, and the New Document form.

**Methods:**
- `GET /api/v1/documents/` — list (permission: `documents.document.list`, risk: medium)
- `POST /api/v1/documents/` — create (permission: `documents.document.create`, risk: medium)
- `GET /api/v1/documents/<document_id>/` — retrieve (permission: `documents.document.read`, risk: **high**)
- `PATCH /api/v1/documents/<document_id>/` — update (permission: `documents.document.update`, risk: **high**)

**Send (create/update):**
- create: `family` (**required**), `template_key` (**required**), `label` (**required**); then **either** `applicant` (UUID) **or** `standalone_purpose`; plus optional `content`, `template_version`, `notes`
- update: any subset of `label`, `content`, `template_version`, `standalone_purpose`, `notes` — **and nothing else**

**Returns:** Document (detail shape) for create, retrieve, and update; list[Document (list shape)] for the list, paginated.

**Requires state:** for an applicant-owned document, an existing applicant. Nothing about the applicant's status is checked — a document may be created against a dormant or archived applicant.

**Side effects:** appends `document_created` / `document_updated` to the central audit log. **The body is redacted from the event** — see §4 `HistoryEvent`. Nothing outside this module changes.

**Notes:**
- **List filters:** `applicant` (UUID), `standalone` (bool), `status`, `include_archived` (bool, default `false`), `family` (exact enums), `template_key` (exact string), `search` (partial match on `label` only), `fiscal_year` (`YYYY/YY`, on `created_at`), `page`, `page_size`.
- **`search` does not reach into `content`.** Searching for an account number returns nothing, deliberately — full-text search over personal financial data is a decision this module has not made.
- **Archived documents are hidden unless asked for.** Omitting `status` returns `draft` and `ready` documents only. `status=archived` returns only archived ones (a "removed documents" view); `include_archived=true` returns everything. `include_archived` is ignored when `status` is given. (Before 1.2.0, omitting `status` returned archived documents too.)
- `content` defaults to `{}` — a workspace is opened before anything is typed into it.
- **`content` must be a JSON object** (not an array or scalar) and must serialize under **256 KiB**. A very long bank statement is the realistic way to hit that.
- **`student-certificate` content is validated on create and on every `PATCH` carrying `content`.** Nothing is required, `null` skips a key, and unknown keys (including the older camelCase `studyType`, `studentName`, `program`, `nationality`, `coursehour`) pass untouched. Checked keys (snake_case):
  - `firstname`, `middlename`, `lastname`, `course_name`, `branch_name` — string ≤150; `address` ≤300; `course_level`, `branch_no` ≤50
  - `date_of_birth`, `date_of_admission`, `date_of_completion`, `issue` — `YYYY-MM-DD` or `""`; `date_of_completion` ≥ `date_of_admission`
  - `gender` — `male` | `female` | `other` | `""`
  - `course_books` — list of ≤20 strings, each ≤150
  - `course_total_days` — whole number 0–1000; `course_hours_per_day` — number (or numeric string) 0–24
  - `marking` — list of ≤12 rows `{ month: "YYYY-MM" (unique), total_days: int ≥0, class_hr, present, absent: numbers ≥0, attendance_percentage?: 0–100 }`; `present + absent ≤ class_hr` (all three are **hours**)
  - `grades` — object; `grammar`, `listening`, `conversation`, `reading`, `composition` each `A` | `B` | `C` | `D` | `""`
  - `study_type` — `0` (studying) or `1` (completed)
  - `photo_media_id` — UUID or `null`; must be a non-archived file of category `photograph` uploaded for **this document's applicant** (`GET /api/v1/files/?applicant=<id>&category=photograph`). A standalone document cannot carry one.
  - `instructor_id`, `director_id` — not checked
- Every other template's `content` is still opaque. Woda letters' `show_ref_no`, `show_dispatch_no`, and `dispatch_no` are stored as sent; nothing server-side reads `wodadoc_date`.
- **Immutable on update:** `applicant`, `family`, `template_key` → 400 `DOCUMENTS_OWNERSHIP_IMMUTABLE`; `status` and the archive fields → 400 `DOCUMENTS_STATUS_IMMUTABLE`.
- **An archived document returns 409 on `PATCH`.** Restore it first.
- There is no delete.

**Errors:**
- `DOCUMENTS_APPLICANT_NOT_FOUND` (400) — no applicant with that id, on create. **The same code is 404 on the prefill** (§7 Document prefill): here the id is a field of the body, there it is the resource in the path. Branch on the code, not the status
- `DOCUMENTS_OWNER_REQUIRED` (400) — neither an applicant nor a standalone purpose was given, or a standalone document's purpose was cleared
- `DOCUMENTS_TEMPLATE_KEY_INVALID` (400) — the slug does not agree with the family
- `DOCUMENTS_CONTENT_INVALID` (400) — the body is not a JSON object, or a `student-certificate` body breaks its rules (`details.fields` names each failing key)
- `DOCUMENTS_CONTENT_TOO_LARGE` (400) — the body exceeds 256 KiB
- `VALIDATION_ERROR` (400) — e.g. a malformed `template_version`, or a non-boolean `include_archived`
- `DOCUMENTS_OWNERSHIP_IMMUTABLE` (400) — a `PATCH` carried the applicant, family, or template key
- `DOCUMENTS_STATUS_IMMUTABLE` (400) — a `PATCH` carried a standing field
- `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409) — the document is archived
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document workspaces — `/api/v1/documents/workspaces/`

**Use it when:** the Documents landing table — applicants who have documents, one row each, with live and removed counts.

**Methods:**
- `GET /api/v1/documents/workspaces/` — (permission: `documents.document.list_workspaces`, risk: medium)

**Send:** nothing beyond `page` / `page_size`.

**Returns:** list[WorkspaceSummary], ordered by most recent edit, paginated.

**Requires state:** nothing. Returns an empty array when no applicant has any documents.

**Side effects:** none.

**Notes:**
- **Standalone documents are excluded** — they have no applicant to group under. List them with `GET /documents/?standalone=true`.
- **Archived documents are counted in `archived_count`, not `document_count`.** An applicant whose documents are all archived still appears, with `document_count: 0` — link the row to `GET /documents/?applicant=<id>&status=archived` so they can be restored. (Before 1.2.0 such an applicant was dropped.)
- `last_updated` is the maximum `updated_at` across all of that applicant's documents, archived included.
- Note the **trailing slash**, and that this is a literal path segment — it is not a document id.

**Errors:** none beyond the global authority failure.

### Document: status — `/api/v1/documents/<document_id>/status/`

**Use it when:** the workspace's "mark ready" control, and moving a document back to draft.

**Methods:**
- `POST /api/v1/documents/<document_id>/status/` — (permission: `documents.document.change_status`, risk: medium)

**Send:** `status` — **`draft` or `ready` only**.

**Returns:** Document (detail shape).

**Requires state:** the document must not be archived.

**Side effects:**
- appends `document_status_changed`.
- moving to **`ready`** raises a `document_ready` notification *(cross-app: `notifications`)* to every other active Admin — never a Lead Manager (documents are Admin-only), never the caller. Sent after commit; a notification failure never affects this response. Moving to `draft`, or re-sending the current status, raises nothing.

**Notes:**
- **`archived` is not accepted here** and fails serializer validation with `VALIDATION_ERROR` on the `status` field. Archiving requires its own endpoint and a reason, so a document is never retired without one.
- Re-sending the current status is a no-op: 200, no event.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409) — the document is archived
- `DOCUMENTS_STATUS_INVALID_TRANSITION` (400) — reserved for a status outside the selectable set that passes serializer validation
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document: archive — `/api/v1/documents/<document_id>/archive/`

**Use it when:** the workspace's "remove"/"delete" action. **This is what a delete button becomes.** Archiving is allowed from `draft` and `ready` alike (the frontend's `finalized`/`submitted` are `ready`).

**Methods:**
- `POST /api/v1/documents/<document_id>/archive/` — (permission: `documents.document.archive`, risk: high)

**Send:** `reason` (**required**, non-empty).

**Returns:** Document (detail shape), with `status: "archived"`, `is_editable: false`, and `archived_at` / `archived_by_username` stamped.

**Requires state:** the document must not already be archived.

**Side effects:** appends `document_archived` with the reason attached, and remembers the current status for restore. **The document drops out of the default list** but is never deleted — it remains reachable with `?status=archived` or `?include_archived=true`, is counted in the workspace's `archived_count`, and keeps its history.

**Notes:**
- **The reason is mandatory.** Archived documents are kept forever, so "why is this one archived" must be answerable from the record.
- **After archiving, the document is frozen** — `PATCH` and the status action both return 409. Label it clearly; a UI that leaves the workspace editable will produce failed saves.

**Errors:**
- `DOCUMENTS_DOCUMENT_ALREADY_ARCHIVED` (409)
- `DOCUMENTS_ARCHIVE_REASON_REQUIRED` (400) — reason missing or whitespace-only
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document: restore — `/api/v1/documents/<document_id>/restore/`

**Use it when:** undoing a removal — bringing an archived document back.

**Methods:**
- `POST /api/v1/documents/<document_id>/restore/` — (permission: `documents.document.restore`, risk: high)

**Send:** optional `reason` (string ≤2000) — recorded on the `document_restored` history event. An empty body is fine.

**Returns:** Document (detail shape), with `status` set back to what it was before archiving (`draft` or `ready`) and the three archive fields cleared.

**Requires state:** the document must be archived.

**Side effects:** appends `document_restored`. **Clearing the archive fields does not erase the archiving from history** — `document_archived` and its reason stay in the history endpoint.

**Notes:**
- **Restore returns the status the document held when it was archived.** A `ready` document comes back `ready`. Documents archived before 1.2.0 (when that status was first recorded) come back `draft`. (Before 1.2.0, restore always returned `draft`.)
- There is no `unarchive/` route; this is it. There is no `record_version` or other optimistic-concurrency token.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_ARCHIVED` (409)
- `VALIDATION_ERROR` (400) — `reason` longer than 2000 characters
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document: history — `/api/v1/documents/<document_id>/history/`

**Use it when:** the history panel on the Document Workspace.

**Methods:**
- `GET /api/v1/documents/<document_id>/history/` — (permission: `documents.document.list_history`, risk: medium)

**Send:** nothing.

**Returns:** list[HistoryEvent], newest first, paginated.

**Requires state:** the document must exist.

**Side effects:** none.

**Notes:**
- Never empty for an existing document — creation always writes one event.
- **A body change is recorded as a marker, not as content.** This endpoint tells you *that* the document changed and who changed it, never what it said. **You cannot reconstruct a previous body from it** — that is what `document_history` print snapshots are for, and only for edits somebody captured a snapshot of.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document prefill — `/api/v1/documents/prefill/<applicant_id>/`

**Use it when:** opening a new Woda letter, student certificate, or any applicant-owned document form — fill the fields from the applicant's file instead of retyping them; also the clipboard's "From applicant" group.

**Methods:**
- `GET /api/v1/documents/prefill/<applicant_id>/` — (permission: `documents.prefill.read`, risk: **high**)

**Send:** nothing.

**Returns:** DocumentPrefill (§4).

**Requires state:** the applicant exists. Nothing else — every part degrades to `""`, `null`, or `[]` when not entered.

**Side effects:** none. Writes nothing and records no audit event.

**Notes:**
- **Admin only**, like every documents route — it carries citizenship, passport, and family details.
- Read it when the form opens, not on every keystroke: it reflects the applicant file at that moment, and nothing here pushes later changes.
- It does **not** fill `content` for you or know any template's keys — mapping prefill fields onto a template's content keys is the form's job.
- `name_native` and `honorific` are **not provided** (§9).

**Errors:**
- `DOCUMENTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id (the same code is 400 on document create, where the id travels in the body)

## 8. Flows

**Create and work on an applicant's document** *(Admin)*

1. `GET /api/v1/documents/?applicant=<applicant_id>` — the Applicant Detail documents panel (live documents; add `include_archived=true` for a "show removed" toggle).
2. `POST /api/v1/documents/` with `applicant`, `family`, `template_key`, `label`, and the layout `template_version` the form renders (e.g. `"2"` for a new Woda letter). → document id, `status: "draft"`, `content: {}`.
   - A `family` and `template_key` from different pickers → 400 `DOCUMENTS_TEMPLATE_KEY_INVALID`.
   - No applicant and no purpose → 400 `DOCUMENTS_OWNER_REQUIRED`.
3. `GET /api/v1/documents/<id>/` — the workspace loads the body.
4. `PATCH /api/v1/documents/<id>/` with `content` on each save. **Send the complete body**; it is replaced wholesale, not merged.
   - Send only the input fields. Do not send computed balances, totals, or amounts-in-words — the backend stores whatever it is given, and a stored derived value will be stale the moment the inputs change.
   - A `student-certificate` save with a bad value → 400 `DOCUMENTS_CONTENT_INVALID`; mark each key in `error.details.fields` on the form.
5. `POST /api/v1/documents/<id>/status/` with `ready` when the document is finished. The other Admins receive a `document_ready` notification *(cross-app: `notifications`)*.
6. **Print** — save first, then `POST /api/v1/document-history/documents/<document_id>/snapshots/` (module: `document_history`). Capture reads the *committed* row, so an unsaved workspace is not what gets frozen.

**Create a standalone document** *(Admin)*

1. `POST /api/v1/documents/` with `standalone_purpose` and **no** `applicant`. → `is_standalone: true`.
2. Work it exactly as above.
3. Find it again with `GET /api/v1/documents/?standalone=true` — it will **not** appear in `GET /documents/workspaces/`, which groups by applicant.

**Remove a document and bring it back** *(Admin)*

1. `POST /api/v1/documents/<id>/archive/` with a reason. → `status: "archived"`, `is_editable: false`.
   - No reason → 400 `DOCUMENTS_ARCHIVE_REASON_REQUIRED`. Make the reason input mandatory before submit.
2. **The workspace must go read-only now.** Any `PATCH` returns 409 `DOCUMENTS_DOCUMENT_NOT_EDITABLE`.
3. The document **disappears** from `GET /api/v1/documents/?applicant=<id>`. It is listed by `?status=archived` (or `?include_archived=true`), and the workspace row's `archived_count` goes up by one.
4. `POST /api/v1/documents/<id>/restore/` (optionally with `{ "reason": "..." }`) → back to the status it had (`draft` or `ready`) and editable.
5. `GET /api/v1/documents/<id>/history/` still shows `document_archived` with the original reason, then `document_restored`.

**Fill a new letter from the applicant's file** *(Admin)*

1. `GET /api/v1/documents/prefill/<applicant_id>/` → names, citizenship, addresses, parents, grandparents, education, language tests, photo.
   - `DOCUMENTS_APPLICANT_NOT_FOUND`: the applicant id is wrong.
   - A `null` parent or address: that part of the file is empty — prompt the user to type it, or to complete the applicant file (`PATCH /api/v1/applicants/<id>/`, module `applicants`).
2. Map the values onto the template's content keys in the form, let the user adjust, then `POST /api/v1/documents/` with that `content` (and `template_version`).

**Build the documents landing table** *(Admin)*

1. `GET /api/v1/documents/workspaces/` → one row per applicant with documents: id, name, live count, archived count, last edit.
2. Clicking a row → `GET /api/v1/documents/?applicant=<applicant_id>` for that applicant's documents.
3. Standalone documents need their own tab — they are absent from step 1 by design.

## 9. Gaps

### Blocking — features the concept describes that have no endpoints

- **Reading the prefill leaves no trace.** It returns citizenship, passport, and family identity numbers, yet — like every read in this module — it records no audit event, so there is no record of who looked up whose identity data. Whether high-risk reads should be audited is an open decision, not a planned change.

- **Signature references are still unvalidated, even though the signatory table now exists.** `content.instructorId` / `content.directorId` on certificate templates name records in `document_templates`, and you can now fetch the real list from `GET /api/v1/document-templates/signatories/?status=active`. But this module stores `content` as an opaque JSON body and does not look inside it: a typo, a stale id, or the id of a `draft` signatory are all accepted silently. **A document may still name a signatory that never existed** — what changed is that a correct client has a list to pick from, not that an incorrect one is caught.
- **The template catalogue is advisory; `template_key` is still not checked against it.** `document_templates` holds a catalogue of registered slugs, and this module does not consult it. A well-formed slug matching its family prefix is accepted whether or not it is registered, and whether or not it is retired. See the next item — the two gaps compound.
- **No supporting files *on this resource*.** `uploaded_files` now exists, but **a document payload carries no file references at all** — no count, no list, no ids. Files that belong to a document are reachable only from that module, via `GET /api/v1/files/?document=<document_id>`. A screen showing a document and its attachments must make two calls and join them itself.
- **A template registry exists, and this module does not use it.** `template_key` is format-checked and family-checked but **not** checked against `document_templates`' catalogue. A typo that happens to match the family prefix — `bank-vyass-statement` — is still accepted. Enforcing the catalogue would narrow this endpoint's accepted input, which is a breaking change and a separate decision; until it is made, your picker is the only thing standing between a typo and a document nobody can render.

### Behavioural — things that will surprise a client

- **Prefill has no `name_native` or `honorific`.** Names are English-only in Grandway (one `full_name`), so a native-script name has no source; an honorific (Mr/Ms/Shri/Sushri) would need marital status, which is not stored. Both are typed on the form.
- **Prefill's name parts are a split of `full_name`,** first/middle/last word — compound surnames come out wrong.
- **Prefill's `photo_media_id` is a convention** (newest current, non-archived photograph), not a chosen primary photo.

- **Global search still returns archived documents.** `GET /api/v1/search/` (module `search`) does not apply this module's list default; its document hits carry `is_archived`. Filter or badge them client-side.
- **The certificate photo is checked at save time only.** A photograph archived *after* the certificate was saved is not detected until the next save of `content`; a snapshot recovery puts back a printed body without re-checking it.

- **A client-supplied derived value is stored, not stripped.** Posting `statement_debit_total` gets it persisted and returned. The backend cannot strip it without knowing all 53 shapes, and stripping would break "preserve any extra keys". **Never read a derived value back from the API as truth** — recompute from the inputs.
- **`content` is replaced wholesale on `PATCH`, not merged.** Sending `{"content": {"a": 1}}` on a document whose body had ten keys leaves it with one. Send the complete body.
- **A previous body is recoverable only if somebody printed it.** This module has no field history, no versioning, and its audit log redacts the body. `document_history` snapshots are the only record of a previous body — so editing a document that was never printed still loses its previous contents irrecoverably. It is a print log, not an autosave.
- **`content` is not sanitized or escaped.** It is returned exactly as stored; escaping on render is the frontend's responsibility.
- **`?search=` matches `label` only** — not the body, not the applicant's name, not `template_key`.
- **No cascade from applicants.** `applicant` is `PROTECT`: an applicant with documents cannot be deleted, and no document is ever removed as a side effect of anything.
- **No bulk operations.** No bulk create, bulk archive, or bulk export.

### Frontend contract reconciliation

The uploaded `frontend_api-used.md` and `frontend_data-contract.md` describe a **different backend** — a different project, different auth, and a different response envelope. Every row below is a real difference the client must adapt to.

| The frontend docs assume | Grandway actually |
|---|---|
| `POST /api/auth/login/` with `{ email, password }` | `POST /api/v1/auth/login/` with `{ username, password, device_id }` |
| `{ data, meta: { total, page, pageSize } }` | `{ success, message, data, meta: { count, page, page_size, next, previous } }` |
| `GET /api/auth/users/me/` | `GET /api/v1/auth/me/` |
| `studentId` on a document | `applicant` (UUID) |
| `GET /students/:studentId/documents` | `GET /api/v1/documents/?applicant=<id>` |
| `GET /students/:studentId/full` | `GET /api/v1/applicants/<id>/` — exists, and now carries education history (`educations`) and language-test scores (`language_tests`), plus the citizenship and national ID numbers; for document forms use `GET /api/v1/documents/prefill/<applicant_id>/`. Still **without** `summary`, `skills`, or `experience` |
| `DELETE /documents/:id` → 204, and cascade-delete of print logs | **No delete exists.** `POST /api/v1/documents/<id>/archive/` with a reason |
| Deleting a student removes their documents | **Never.** `applicant` is `PROTECT` |
| `type: "bank-vyas-statement"` (one field) | `family: "bank_statement"` **and** `template_key: "bank-vyas-statement"` (two fields, cross-validated) |
| `status: draft \| submitted \| archived` | `draft \| ready \| archived` — `submitted` becomes `ready` |
| `GET /documents/workspaces` | `GET /api/v1/documents/workspaces/` — note the trailing slash |
| `DocumentWorkspaceSummary.studentId` / `.studentName` | `applicant_id` / `applicant_name` |
| `GET /documents/:id/print-logs`, `POST` the same | Built, in a **different module and at a different path**: `GET /api/v1/document-history/documents/<document_id>/timeline/` and `POST /api/v1/document-history/documents/<document_id>/snapshots/` |
| `GET /signatures?active=true` | Built, in a **different module and at a different path**: `GET /api/v1/document-templates/signatories/?status=active`. The resource is `Signatory`, with a single `name` field |
| Any authenticated user reaches these screens | **Admin only.** A Lead Manager gets 403 on every route, reads included |
| `/documents/clipboard/` with `scope: applicant \| shared \| personal` | Built in a **different module and at a different path**, and **personal only**: `GET`/`POST /api/v1/auth/me/clipboard/`, `PATCH`/`DELETE /api/v1/auth/me/clipboard/<entry_id>/`, `POST …/<entry_id>/use/`, and categories at `/api/v1/auth/me/clipboard/categories/` (see `authenticate/docs/INTEGRATION.md`). One clipboard per account, owner-only, for **every authority** (Lead Managers and Superadmins included, unlike this module). **No `shared` or `applicant` scope** — an entry is never shared or linked to an applicant. `field_key` is optional; filter suggestions with `?field_key=a,b` |

**What the frontend gets right and must keep:** `content` carries input fields only; derived values are computed at render and never persisted. That is exactly this backend's contract, and the one thing in the uploaded docs that needed no reconciliation at all.
