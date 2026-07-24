# Data Contract — Document Templates

**Owner app:** `document_templates`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the signatory library that certificate documents point at, and the catalogue of template slugs the document picker offers. It does **not** own the editable document record (`documents`), the immutable print snapshot (`document_history`), file storage (`uploaded_files`, which now exists but which this app does not call), or the template *rendering* — which lives in the frontend as code, not here.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial contract — two models, `Signatory` and `DocumentTemplate` |
| 1.0.1 | 2026-07-24 | AI (Claude) | No schema change. Renamed the `PATCH` status guard's error code and documented the `name` re-derivation rule |
| 1.0.2 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. Same, for `signature_image_url` |
| 1.1.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (Signatory `name`/`title`). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |

---

## The rule that governs this app

**This app stores what is *offered*, not what is *rendered*.**

The frontend owns the templates. Its `DocumentType` union is a hardcoded list of slugs, and each per-family content shape is a compiled-in TypeScript type — `CertificateContent`, `CvContent`, `BankStatementContent`, and so on. A template's sections, field order, and layout are frontend code and cannot be moved here without rewriting the renderer to draw from server metadata.

What this app adds is the two things the frontend could not answer for itself:

1. **Who may sign a certificate** — the record `documents`' `content.instructorId` and `content.directorId` have pointed at since that app shipped, and the one `document_history` freezes into `render_context.signatories`. Both stored those ids as opaque strings against a table that did not exist.
2. **Which slugs are currently offered** — so a bank partner can be retired from the picker without a frontend deploy.

A second rule follows: **nothing here is ever deleted.** Documents reference a template by plain string and snapshots freeze signatory ids, neither protected by a foreign key. A row removed here would silently orphan history with nothing in the database to notice. Retirement is a status change.

---

## Deliberate Deviations

`concepts/document_templates.txt` describes a considerably larger module than this. Each departure is recorded here, and the concept file carries matching correction notes.

- **No template version chain, no section metadata, no field hints, no signature slots, and no preview.** The concept names all five, and the frontend consumes none of them — it has no endpoint for any, and its templates are code. Building them would mean inventing a schema against zero consumers, which §32 forbids and which would guarantee drift from the templates that actually exist. **`concepts/document_templates.txt`'s Template Editor, Template Detail / Version History, and Template Preview screens therefore have no backing endpoints.** Recorded in `docs/INTEGRATION.md` §9 rather than silently omitted, so a frontend author reading the concept knows they are absent by decision.
- **Historical reproduction does not need a version chain here, and already works.** The concept's requirement — "Once a version has been used by a document or history snapshot, it should remain available for historical reproduction" — is already satisfied by `document_history`, which freezes the template key, the template version string, and the resolved signatories into each snapshot's `render_context`. A snapshot is self-sufficient for reproduction; it does not read back through this app. Adding an immutable version chain would duplicate a guarantee that already holds.
- **The catalogue is advisory, not enforcing.** `documents` does **not** consult this table. Creating a document with a `template_key` absent from the catalogue still succeeds. Enforcing it would narrow a shipped endpoint's accepted input (§29 breaking change) and add a runtime dependency from `documents` to this app; that is its own decision with its own approval gate. The consequence is that `documents`' documented gap — *"a typo that happens to match the family prefix is accepted"* — stays open.
- **The signature image is a URL, not an upload.** §14 requires a full file contract — allowed types, max size, storage location, filename rule, MIME validation, access control — and `concepts/project_overview.txt` names a dedicated `uploaded_files` domain that does not exist. `signature_image_url` is a plain link to an image hosted elsewhere, mirroring `clients.logo_url` field-for-field. **Fourth deferral of this kind**, after the applicant photograph, offer attachments, and the client logo. The concept explicitly permits it: *"In V1 this can be a stored path or URL-like value."*
- **`role` is free text, not an enum.** The frontend picks signatories into `instructorId` and `directorId` slots and `document_history`'s worked example carries `"role": "director"` — but the signature-slot metadata that would fix the vocabulary is not built, so an enum would be a guess that starts rejecting real roles the moment a template needs a fourth one.
- **`Signatory.name` and `DocumentTemplate.label` are both single English fields (§39.1).** A signatory is a named person; a template label is operational shorthand from a picker ("Vyas Statement"). Both are one field, Unicode-normalized on write (§39.2).
- **`title` is a single optional field.** Search is over the name only — nobody looks up a signatory by job title.
- **No history table**, for the same reason as every other app: `audit` provides an immutable append-only log and §4 forbids duplicating it.
- **Nothing in the audit log is redacted**, unlike `documents` (which replaces its body with a marker) and `document_history` (which drops two whole JSON columns). There is no applicant data in this app to protect, so full before/after values are recorded — which is the point of the log.

---

## 1. Signatory

**Purpose:** One stored person-and-signature record a certificate template may name. Answers "who is allowed to appear as the signer on an issued document, and what does their signature look like".
**Table:** `document_templates_signatory`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key. **This is the value `documents` stores in `content.instructorId` / `content.directorId`** |
| name | CharField(255) | No | No | No | Roman name — an independent identity, not a translation |
| title | CharField(255) | No | No | No | |
| role | CharField(100) | No | No | No | Free text, e.g. `director`, `instructor`. **Not an enum** |
| signature_image_url | URLField(500) | No | No | No | A link to an image hosted elsewhere — **not an upload** |
| status | CharField(20) | No | No | No | Defaults to `draft`; indexed |
| status_note | Text | No | No | No | Optional on every transition |
| created_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`status`** — `draft` | `active` | `inactive`. Defined in `document_templates/constants.py` `LifecycleStatus`, shared with `DocumentTemplate` via `LifecycleMixin`. One enum for both models rather than two identical ones (§4): both answer the same question — "may this be offered for new work?" — with the same three answers.

**A signatory is not a system user.** `concepts/document_templates.txt`: *"A signatory is not a system actor."* There is no account, no login, and no foreign key to `authenticate.User` — the person whose name appears at the bottom of a certificate is usually not someone who uses Grandway at all. `created_by` records the Admin who added the record, not the signer.

**Validation Rules:**

- `name` is required; every other text field is optional.
- All user-entered text is Unicode-normalized on write (§39.2), in the service layer as well as the serializer.
- `signature_image_url` must be a well-formed URL when present → `VALIDATION_ERROR`.
- **`status` and `status_note` are not settable through update** → `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE`. Both move through the status action, so a change of standing is always a recorded transition rather than a field diff. The code is named for immutability rather than for a transition because **no transition here is ever invalid** — `LifecycleStatus` allows every state from every state.
- A new signatory is created as **`draft`**, never `active`. A signatory with no signature image yet is not one a certificate should be able to name, so activation is a decision rather than a default.

**Indexes:**

- `(status, name)` — `signatory_status_name_idx`. The frontend's only call into this app: the active-signatory picker, alphabetical.
- GIN trigram on `name` — `signatory_name_trgm_idx`. Serves the `?search=` lookup (§39.6). `pg_trgm` comes from `leads` migration 0002, declared as an explicit migration dependency.

Ordering is `name` — a reference library read as a picker, not a worklist, so recency means nothing. Same call `clients` made.

**Soft Delete:** `N/A — no deletion at all.` There is no delete endpoint and no delete service, enforced by a test that fails if one appears (`tests/test_services.py::NothingIsDeletedTests`). A signatory whose id is frozen into a snapshot's `render_context` must keep resolving forever; deactivating removes them from the picker and nothing else. `created_by` is `PROTECT`.

**Cross-App Dependencies:**

- `authenticate.User` — `PROTECT` FK for `created_by`.
- `audit` — service call. Every mutation appends one event, unredacted.
- **Referenced by, without a foreign key:** `documents.Document.content.instructorId` / `.directorId` and `document_history.DocumentSnapshot.render_context.signatories[].id`. Both store this model's `id` as an opaque string inside a JSON body. **Neither validates it, before or after this app shipped** — see §3.

---

## 2. DocumentTemplate

**Purpose:** One row of the template picker — a slug, a family, a label, and whether it may still be chosen. Answers "what may staff create a document from today".
**Table:** `document_templates_documenttemplate`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| key | CharField(100) | Yes | No | No | **Unique.** The slug the frontend renders with, e.g. `bank-vyas-statement` |
| family | CharField(20) | Yes | No | No | The stable document class; indexed |
| label | CharField(255) | Yes | No | No | What staff call it in the picker |
| description | Text | No | No | No | |
| display_order | PositiveInteger | No | No | No | Defaults to 0. Picker position within the family |
| status | CharField(20) | No | No | No | Defaults to `draft`; indexed |
| status_note | Text | No | No | No | |
| created_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`family`** — `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate`. **Imported from `documents.constants.DocumentFamily`, not redeclared** — see §3.
- **`status`** — `draft` | `active` | `inactive`. As `Signatory` above.

**Validation Rules:**

- `key` is unique → `DOCUMENT_TEMPLATES_KEY_ALREADY_EXISTS`. It is the catalogue's identity and the string every document stores; two rows claiming it would make "which template is this document using" unanswerable.
- `key` matches `^[a-z0-9]+(?:-[a-z0-9]+)*$` — the validator **imported from `documents.validators`**, not a second copy.
- `key` must agree with `family` by prefix, plus suffix for the two bank families — the rule **imported from `documents.services`**. Violations raise that app's `TemplateKeyInvalidError`, re-coded at this app's view boundary as `DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID`.
- **`key` is immutable after creation** → `DOCUMENT_TEMPLATES_KEY_IMMUTABLE`, rejected rather than silently dropped. Documents point at it as a plain string with no foreign key behind them, so a rename would orphan every document that used it.
- Changing `family` re-runs the agreement check against the existing `key`.
- **`status` and `status_note` are not settable through update** → `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE`.

**Indexes:**

- `(family, status)` — `template_family_status_idx`. "Every active bank statement template" — the shape of the picker the frontend draws.
- `key` UNIQUE.

Ordering is `family`, `display_order`, `label` — grouped by family, then curated order. Without `display_order` the eleven bank statements sort alphabetically by label, which is not the order anyone wants to read them in.

**Soft Delete:** `N/A — no deletion at all.` `concepts/document_templates.txt`: *"No deletion of published template history. Inactive versions should remain available for old records."* Retirement is `POST .../status/` with `inactive`. `concepts` flow 4 requires that retirement not break old documents — it cannot, because `documents` never consults this table.

**Cross-App Dependencies:** as `Signatory` above, plus the imported enum, validator, and service function described in §3. **No foreign key to `documents` in either direction.**

---

## 3. Cross-App Dependencies — three imports from `documents`

§4 forbids duplicating enums, validators, and service functions across apps. That rule outranks the fact that `constants.py` and `validators.py` are not on §4's list of importable modules: a second copy of any of these three could accept a template key `documents` would reject, letting an Admin publish a catalogue row no document could ever be created from.

| Imported | From | Why not a local copy |
|---|---|---|
| `DocumentFamily` | `documents.constants` | Six values that must stay identical. A divergent copy would split the family vocabulary between the app that defines documents and the app that catalogues them |
| `validate_template_key` | `documents.validators` | The same slug, for the same purpose, under the same rule. `documents` declared its own rather than importing `institutions`' because those rules genuinely differ; here they are the same rule |
| `assert_template_key_matches_family` | `documents.services` | The prefix/suffix cross-check. §4 explicitly permits importing another app's `services.py` |

`document_history` set the opposite precedent for `MAX_RENDER_CONTEXT_BYTES`, declaring it locally to avoid coupling. The distinction holds: a size cap may legitimately diverge between two apps, a shared vocabulary may not.

**What this app does *not* do to `documents`:** it holds no foreign key in either direction, calls no write service, and is not consulted by that app. The relationship is one-way and read-only at the Python level. The consequence is stated plainly in the Deliberate Deviations above and in `docs/INTEGRATION.md` §9 — **the signatory ids in `content` and `render_context` are still unvalidated.** What changed is that a client now has a real list to pick from; what did not change is that nothing stops it sending an id that was never in that list.

---

## 4. Seed data

`document_templates/seed_data.py` carries **53** template slugs transcribed from the frontend's own `frontend_data-contract.md`, loaded by `python manage.py seed_document_templates`.

**The frontend contract heads that list "DocumentType (42 slugs)" and then lists 53.** Counted by family: 4 student + 11 woda + 11 lor + 5 moi + 11 bank statements + 11 bank certificates. The "42" is wrong, and it propagated into this backend's documentation ("42 template shapes") when `documents` shipped. Recorded rather than silently corrected — if 42 is the real number, this list contains eleven slugs the frontend cannot render, which is worth confirming against the real template set.

The transcription is **not** a source of truth: the templates are frontend code, and this list is stale the moment the frontend adds a bank partner. The command is idempotent and never touches an existing row — an Admin's renamed label and a retired template both survive a re-run. `EXPECTED_TEMPLATE_COUNT` is asserted by the test suite so a slug dropped in a future edit fails loudly rather than quietly shrinking the catalogue.
