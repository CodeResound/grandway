# Data Contract — Uploaded Files

**Owner app:** `uploaded_files`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the platform's file ledger — the stored bytes plus their category, ownership, verification state, replacement chain, and archival history. It does **not** own the editable document record (`documents`), the immutable print snapshot (`document_history`), the template catalogue or its signatories (`document_templates`), or the person (`applicants`). It renders nothing and computes nothing about a file's contents.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial contract — one model, `UploadedFile` |
| 1.0.1 | 2026-07-24 | AI (Claude) | No schema change. Recorded the owner-visibility access rule (`document`- and `snapshot`-owned files are Admin-only, closing a leak found by the §19.5 review), the `UPLOADED_FILES_FILE_EMPTY` split, the `superseded_by_username` response field, and the deliberate absence of upload idempotency |

---

## The rule that governs this app

**This is the first and only place in Grandway where bytes are stored.**

Before this app, four shipped modules deferred file handling to it by name: the applicant photograph, offer supporting files, `clients.logo_url`, and `document_templates.signature_image_url`. Each recorded the same reason — §14 requires a full file contract and no storage layer existed. This app is that contract.

Three rules follow from it, and each one is load-bearing:

1. **The bytes are private and leave only through one endpoint.** **No URL maps to `MEDIA_ROOT`** — the root URL configuration routes four prefixes and none of them is a static file handler — so the only path from the disk to a client is `GET /files/<id>/download/`, which applies the same authority check as every other route. A file with a guessable URL would defeat "privacy by default" (`concepts/project_overview.txt`) for passport scans and bank statements.
2. **Nothing is ever deleted, and nothing is ever overwritten.** There is no delete endpoint, no delete service, and no path that replaces the bytes of an existing row. A replacement is a *new row* pointing back at its predecessor. `concepts/uploaded_files.txt`: *"Deletion should be exceptional. The system should preserve traceability over time."*
3. **A file belongs to exactly one business record.** Enforced in the database, not only in a serializer. `concepts/uploaded_files.txt` lifecycle step 2: *"Attach it to one supported record."*

---

## Deliberate Deviations

`concepts/uploaded_files.txt` leaves five questions explicitly open. Each is answered here, and each answer is a decision that can be revisited additively.

- **A file belongs to exactly one record, not many.** The concept asks *"Whether a file can belong to more than one business record."* v1 says one, enforced by the `uploaded_file_single_owner` check constraint. The same passport scan attached to an applicant and to a journey is two rows sharing a `checksum_sha256`, which is queryable and honest, rather than one row with ambiguous ownership and an ambiguous archive rule. Moving to many-owners later means adding a link table, which is additive; moving *back* from many to one would not be.
- **Ownership is five nullable foreign keys, not a `content_type`/`object_id` pair.** The loose-pair form would let a file point at a record that never existed or has since gone, with nothing in the database to notice — the opposite of what an accountability system wants. `PROTECT` on all five matches every existing cross-app FK in the project.
- **`education` and `test_scores` are named in the concept but have no columns here, because those apps do not exist.** The concept lists education records among the owner types. When that app ships, adding a sixth nullable FK and extending the constraint is one additive migration in this app and none anywhere else. Until then, a transcript attaches to the applicant.
- **Generated PDFs have a category but no producer.** The concept asks *"Whether generated PDFs live here immediately or only later."* The `generated_document` category and the `system_generated` upload source both exist and both work — but `document_history` has no field pointing at a file and does not call this app. A client that generates a PDF may upload it against a snapshot today; nothing in `document_history` will know it did.
- **Verification gates nothing.** The concept asks *"Which categories require verification before use."* Every file starts `pending` and every file may be marked `verified` or `rejected`, but **no endpoint anywhere in Grandway refuses to proceed because a file is unverified.** The state is recorded for human review, not enforced. A rule that says "an offer cannot be accepted until the passport is verified" would live in `offers`, not here, and does not exist.
- **No §39.1 bilingual identity triple.** Every other named entity in the project carries `_np`/`_en`/`_romanized`. A filename does not: it is a byte-level artefact chosen by whatever produced the file, not a canonical identity a Nepali institution recognises. §39.2 still applies in full — `notes`, `rejection_reason`, and `archive_reason` are Unicode-normalized on write. §39.6 search runs over `original_filename` alone, with a trigram index, and that is documented as a real limitation: a Devanagari-named file will not be found by a Roman-script query.
- **`content_type` is the validated type, not the client's claim.** The browser's `Content-Type` on a multipart part is advisory and trivially forged. What is stored is the type this app derived from the extension after confirming the leading bytes agree with it.
- **Duplicates are recorded, not blocked.** Two identical files may exist under two owners, or twice under one. `checksum_sha256` is indexed and filterable so an operator can find them; nothing rejects them. The same scan legitimately supports two different records.
- **No upload idempotency key, and this is a deliberate departure from §15.** That section names file upload among the operations requiring idempotency. Here the requirement conflicts with the rule above: if duplicates are legitimate — and they are, because one scan may support two records — then a request-level de-duplication key would have to distinguish "the same file again on purpose" from "the same request retried", which the client is the only party able to know. The consequence is real and is recorded rather than hidden: **an upload that times out after the server stored it produces a second row on retry**, discoverable only by a `?checksum=` lookup afterwards. An idempotency key supplied by the client would close it and is the recommended future improvement.
- **`upload_source` is caller-asserted and unverified.** Any client may label its own upload `system_generated`; nothing checks it, because nothing on the backend generates a file. It is a hint, not provenance — `uploaded_by` is the field that carries accountability.
- **No `logo_url` or `signature_image_url` migration.** `clients` and `document_templates` still hold plain URL fields. Repointing them at file records changes two shipped response shapes (§22/§29 breaking change) and needs its own session and its own deprecation path.
- **No history table**, for the same reason as every other app: `audit` provides an immutable append-only log and §4 forbids duplicating it.

---

## 1. UploadedFile

**Purpose:** One stored file and everything Grandway knows about it — what it is, which record it belongs to, whether it has been reviewed, what it replaced, and whether it is still in active use. Answers *"which files do we hold for this applicant, and can we trust them?"*
**Table:** `uploaded_files_uploadedfile`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → `applicants.Applicant` | One-of | Yes | No | `PROTECT`. Exactly one owner FK is set |
| journey | FK → `applicant_journeys.ApplicantJourney` | One-of | Yes | No | `PROTECT` |
| offer | FK → `offers.Offer` | One-of | Yes | No | `PROTECT` |
| document | FK → `documents.Document` | One-of | Yes | No | `PROTECT` |
| snapshot | FK → `document_history.DocumentSnapshot` | One-of | Yes | No | `PROTECT` |
| category | CharField(30) | Yes | No | No | Indexed |
| upload_source | CharField(20) | No | No | No | Defaults to `staff_upload` |
| notes | Text | No | No | No | Free operator note |
| file | FileField(500) | Yes | No | No | The storage reference. **Never returned to a client** — the bytes come from the download endpoint |
| original_filename | CharField(255) | Yes | No | Yes | Taken from the upload, stored verbatim. **Never used as the name on disk** |
| content_type | CharField(100) | Yes | No | Yes | Derived and verified by this app, not accepted from the client |
| size_bytes | PositiveBigInteger | Yes | No | Yes | Measured from the stored file |
| checksum_sha256 | CharField(64) | Yes | No | Yes | Streamed SHA-256 hex digest; indexed |
| version_number | PositiveInteger | No | No | Yes | 1-based position in the replacement chain |
| replaces | OneToOne → `self` | No | Yes | Yes | The file this one replaced. `PROTECT` |
| superseded_at | DateTime | No | Yes | Yes | Set when this file is replaced |
| superseded_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL`. Who performed the replacement |
| verification_status | CharField(20) | No | No | No | Defaults to `pending`; indexed |
| rejection_reason | Text | No | No | No | Required when moving to `rejected`; cleared on `verified` |
| reviewed_at | DateTime | No | Yes | Yes | |
| reviewed_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL` |
| archive_reason | Text | No | No | No | Required to archive; cleared on restore |
| archived_at | DateTime | No | Yes | Yes | |
| archived_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL` |
| uploaded_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`category`** — `passport` | `photograph` | `academic_transcript` | `academic_certificate` | `test_score_report` | `offer_letter` | `financial` | `sponsorship` | `signature_image` | `generated_document` | `other`. Defined in `uploaded_files/constants.py` `FileCategory`. `other` exists deliberately: an enum with no escape hatch turns every unanticipated document into a migration.
- **`upload_source`** — `staff_upload` | `system_generated`. `concepts/uploaded_files.txt` names "upload source" as stored data. `system_generated` marks a file produced by the platform (a rendered PDF) rather than received from a person.
- **`verification_status`** — `pending` | `verified` | `rejected`. Every file starts `pending`.

**Derived, not stored** (computed properties, present in every API response):

- `owner_type` — `applicant` | `journey` | `offer` | `document` | `snapshot`, read off whichever FK is set.
- `owner_id` — the UUID of that record.
- `is_current` — `superseded_at is None`. A file stays current until something replaces it; archiving does not make it non-current, and being non-current does not archive it. Two independent axes, deliberately.
- `is_archived` — `archived_at is not None`.
- `is_verified` — `verification_status == "verified"`.
- `created_at_bs`, `reviewed_at_bs`, `archived_at_bs` — Bikram Sambat siblings (§39.4) for the three timestamps that are *business dates* rather than bookkeeping: when the document was received, when it was reviewed, and when it was taken out of use. `null` while the Gregorian field is. `updated_at` and `superseded_at` get no sibling — the first is bookkeeping, and the second is only ever read alongside the successor's `created_at`, which has one. Same division `documents` drew when it gave `archived_at` a sibling and `updated_at` none.

### Validation Rules

- **Exactly one owner FK must be set** → `UPLOADED_FILES_OWNER_REQUIRED` (400) for zero or for more than one. Enforced twice: in the serializer, for a usable error message, and by the `uploaded_file_single_owner` database constraint, so no code path — admin, shell, or management command — can create a file with ambiguous ownership.
- The referenced owner must exist → `UPLOADED_FILES_OWNER_NOT_FOUND` (400).
- A file part must be present → `UPLOADED_FILES_FILE_MISSING` (400).
- **Size ≤ 10 MB** (`MAX_UPLOAD_BYTES = 10 * 1024 * 1024`, i.e. 10 485 760 bytes) → `UPLOADED_FILES_FILE_TOO_LARGE` (400). **A zero-byte file gets its own code**, `UPLOADED_FILES_FILE_EMPTY` — folding the two together would let a client tell a user their empty file was oversized.
- **Extension in the allowlist**: `pdf`, `jpg`, `jpeg`, `png`, `webp`, `docx`, `xlsx` → `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED` (400).
- **The leading bytes must agree with the extension** → `UPLOADED_FILES_FILE_CONTENT_MISMATCH` (400). A `.pdf` whose bytes start `\x89PNG` is refused. Signatures checked: `%PDF-`, `\xFF\xD8\xFF`, `\x89PNG\r\n\x1a\n`, `RIFF????WEBP`, `PK\x03\x04` (both Office formats).
- **`category` is the only classification field a client may change after upload.** `notes` may also be edited. Every other field — owner, bytes, filename, checksum, size, content type, version, and all three lifecycle groups — is refused on `PATCH` with `UPLOADED_FILES_FIELD_IMMUTABLE` (400), rejected rather than dropped so a client is never told a change succeeded when it did not.
- **Every write action against an archived file is refused** → `UPLOADED_FILES_FILE_ARCHIVED` (400), except restore. An archived file must be restored first, so "archived, then changed" is always two visible events. Same rule `documents` applies to its own archived records.
- **Replace** requires a currently-superseded-by-nothing file → `UPLOADED_FILES_ALREADY_SUPERSEDED` (400). The chain stays linear, so "which file is current" always has exactly one answer. Enforced additionally by the `OneToOne` on `replaces`.
- **Verify** accepts `verified` or `rejected` only → `UPLOADED_FILES_VERIFICATION_STATUS_INVALID` (400); `pending` is a starting state, not a decision, and there is no un-review action. Rejecting requires a reason → `UPLOADED_FILES_REJECTION_REASON_REQUIRED` (400).
- **Archive** requires a reason → `UPLOADED_FILES_ARCHIVE_REASON_REQUIRED` (400). Archiving an archived file → `UPLOADED_FILES_ALREADY_ARCHIVED`; restoring a live file → `UPLOADED_FILES_NOT_ARCHIVED`.
- All user-entered text (`notes`, `rejection_reason`, `archive_reason`) is Unicode-normalized on write (§39.2).

### File Contract (§14)

| Question | Answer |
|---|---|
| Allowed types | `pdf`, `jpg`, `jpeg`, `png`, `webp`, `docx`, `xlsx` — by extension **and** by leading-byte signature |
| Max size | 10 MB per file, one file per request |
| Storage location | `MEDIA_ROOT` (default `backend/mediafiles/`, already git-ignored; overridable per environment via the `MEDIA_ROOT` env var). Local filesystem only (§37). **Not served by any URL** |
| Filename rule | `uploaded_files/<owner_type>/<YYYY>/<MM>/<uuid4>.<ext>`. The stored name is a fresh UUID — the client's filename is never used on disk, so a crafted name cannot traverse a path or collide with another record |
| Original filename | Preserved verbatim in `original_filename`, returned in metadata, and used as the `filename=` on download |
| MIME validation | Extension allowlist plus magic-byte prefix check, in `validators.py`. No third-party library and no reliance on the client's declared `Content-Type` |
| Checksum | SHA-256, streamed in chunks at upload time, stored hex-encoded and indexed. Not recomputed on read |
| Ownership | Exactly one of five business records, enforced by a database constraint |
| Access control | Admin or Lead Manager for list, read, edit, upload, replace, and download; **Admin only** for verify, archive, and restore. **A file owned by a `document` or a `document_snapshot` is Admin-only in every respect**, inheriting those modules' rule. Nothing is public. See `docs/SECURITY.md` |
| Deletion rule | **None.** No delete endpoint, no delete service, no model path that removes bytes. Archive is the terminal state |

### Indexes

Each one names the screen it serves (§20):

- `(applicant, -created_at)` — `file_applicant_recent_idx`. The Applicant Detail files panel.
- `(journey, -created_at)` — `file_journey_recent_idx`. The Journey Detail files panel.
- `(offer, -created_at)` — `file_offer_recent_idx`. The Offer Detail supporting-files section.
- `(document, -created_at)` — `file_document_recent_idx`. The Document workspace attachments panel.
- `(verification_status, -created_at)` — `file_review_queue_idx`. The review queue, `?verification_status=pending`.
- `(category, -created_at)` — `file_category_recent_idx`. The category filter on the file list.
- GIN trigram on `original_filename` — `file_orig_name_trgm_idx`. The `?search=` lookup. `pg_trgm` comes from `leads` migration 0002, declared as an explicit migration dependency.
- `checksum_sha256` — plain B-tree via `db_index`. Duplicate discovery.

The `snapshot` FK gets only its implicit index: a snapshot has at most one generated file, so a composite would serve nothing a single-row lookup does not.

Ordering is `-created_at`, `-id`. The `-id` tiebreaker is not cosmetic — it is copied from `document_history.PrintEvent` for the same reason. `created_at` is not unique (a replace writes two rows in one transaction), and under page-number pagination a non-unique sort key lets a row appear on two pages or on none, which on a file ledger reads as a file that silently vanished.

### Constraints

- `uploaded_file_single_owner` — a five-way disjunction requiring exactly one owner FK non-null and the other four null. Written as an explicit `Q` disjunction rather than an arithmetic null-count so it evaluates identically on PostgreSQL and on the SQLite used by the test suite.
- `replaces` is a `OneToOneField` — the uniqueness that keeps the replacement chain from forking.

**Soft Delete:** `N/A — no deletion at all, and no soft-delete flag either.` Archival is a *lifecycle state* (`archived_at`/`archived_by`/`archive_reason`, all cleared on restore), not a tombstone: an archived file is still readable, still downloadable, and still part of its version chain. It is excluded from the default file list by `?is_archived=false`, never by a manager override — selectors return every row unless a filter narrows them, so nothing is hidden from a caller that did not ask for it to be. `uploaded_by` is `PROTECT`, so a user who has uploaded a file cannot be removed.

### Example

```json
{
  "id": "8f14e45f-ea22-4a7f-9f0a-1c2b3d4e5f60",
  "owner_type": "applicant",
  "owner_id": "3c9a1b77-0d5e-4a2c-9b8f-77e1a4c6d210",
  "category": "passport",
  "upload_source": "staff_upload",
  "original_filename": "sita_passport_scan.pdf",
  "content_type": "application/pdf",
  "size_bytes": 842118,
  "checksum_sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "version_number": 2,
  "replaces": "b21c0f9e-33aa-4c1d-8e77-5510aa9f3c41",
  "is_current": true,
  "verification_status": "verified",
  "is_verified": true,
  "rejection_reason": "",
  "reviewed_at": "2026-07-24T11:20:41Z",
  "reviewed_at_bs": {
    "year": 2083, "month": 4, "day": 9,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 9", "display_np": "२०८३ श्रावण ९"
  },
  "reviewed_by_username": "admin.rita",
  "is_archived": false,
  "archive_reason": "",
  "archived_at": null,
  "archived_at_bs": null,
  "notes": "Re-scanned at 300dpi; the first upload was unreadable on page 2.",
  "uploaded_by_username": "lm.bikash",
  "created_at": "2026-07-24T10:58:03Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 9,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 9", "display_np": "२०८३ श्रावण ९"
  },
  "updated_at": "2026-07-24T11:20:41Z"
}
```

**`file` is absent from every response, by design.** Returning a storage path would leak the layout of `MEDIA_ROOT` and imply a fetchable URL that does not exist. The bytes come from `GET /files/<id>/download/` and nowhere else.

**Cross-App Dependencies:**

- `applicants.Applicant`, `applicant_journeys.ApplicantJourney`, `offers.Offer`, `documents.Document`, `document_history.DocumentSnapshot` — `PROTECT` FKs, one of which is set. **Model references only** (§4): this app imports no service, selector, or business rule from any of them.
- `authenticate.User` — `PROTECT` for `uploaded_by`, `SET_NULL` for the three lifecycle actors.
- `audit` — service call. Every write action appends one event.

**Security Notes:** `original_filename` and `notes` may carry applicant identity ("sita_passport_scan.pdf"), so audit `changes` entries record field names and record ids, never the storage path and never file content. The storage path is never logged and never serialized. See `docs/SECURITY.md`.

---

## 2. Cross-App Dependencies

**What this app references:** five business models by foreign key, `authenticate.User`, and `audit.services.record_event`. Nothing else. It imports no other app's `services.py` or `selectors.py`, and no rule, enum, or validator is shared with another app — unlike `document_templates`, which borrows three things from `documents`, there is nothing here another app already defines.

**What references this app: one thing.** `checklists.ChecklistItem.evidence_file` is a nullable `PROTECT` FK pointing here (`related_name="checklist_items"`), and `checklists.services` resolves it through `uploaded_files.selectors.get_file_by_id`. A file cited as proof that a requirement was met **cannot be removed while that item exists** — the first hard constraint of its kind on this table, though no delete path exists here anyway.

That module additionally enforces a rule this app does not: **an evidence file must belong to the citing checklist's journey or that journey's applicant.** The rule is theirs to keep, not ours, but it has a consequence worth recording here — because a `document`- or `snapshot`-owned file is owned by neither a journey nor an applicant, one can never be cited as checklist evidence, so `checklists` cannot become a route around this app's `ADMIN_ONLY_OWNER_TYPES` visibility rule. That is a property of their validation, and would need re-checking if they ever widened it.

**Nothing else references this app.** `applicants` has no photograph field, `offers` has no attachment field, `documents` has no attachment field, `document_history` has no generated-file field, and `clients.logo_url` / `document_templates.signature_image_url` are still plain URLs. The direction remains one-way for all five owner types: a file knows its owner, an owner does not know its files except through this app's list endpoint filtered by that record's id. Adding a reverse reference in any of those apps is additive and is a separate session each.

The practical consequence for a client: **there is no "attach" call on any other app's endpoint.** To attach a passport to an applicant you `POST /api/v1/files/` with `applicant=<id>`; to show that applicant's files you `GET /api/v1/files/?applicant=<id>`.

---

## Soft Delete

`N/A — no model in this app is ever deleted or soft-deleted.` Archival is a reversible lifecycle state, not a delete flag; it hides nothing from a selector and removes nothing from disk. `concepts/uploaded_files.txt`: *"Deletion should be exceptional. The system should preserve traceability over time."* There is no endpoint through which any actor, of any authority, can remove a file record or its bytes.
