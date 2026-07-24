# API — Document Templates

**Owner app:** `document_templates`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24
**Base prefix:** `/api/v1/document-templates/`
**Auth:** Bearer access JWT (`authenticate.SessionBoundJWTAuthentication`) on every endpoint
**Throttle:** project defaults only — `UserRateThrottle` at 1000/hour. No endpoint here is public. Both resources are small and bounded (one row per signer, 53 template slugs), and no response carries a large payload, so there is no per-endpoint cost worth calling out.
**Access level:** protected. **Admin only, on every route including reads.** Lead Manager and Superadmin both denied.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial API documentation — 10 endpoints across two resources |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint change. Renamed the `PATCH` status guard's code to `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` and recorded that `..._STATUS_INVALID_TRANSITION` is unreachable over HTTP; documented that a rename re-derives `name_romanized` |

---

## Access model (§9 interim inline pattern)

This app uses the interim inline access check in `document_templates/access.py`. There is no `permissions.py`.

| Check | Applies to | Allows | Denies |
|-------|-----------|--------|--------|
| `require_template_actor` | **every endpoint**, read and write alike | `admin` | `lead_manager`, `superadmin` → 403 `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` |

Applied by the `TemplateActorView` base class that every view inherits, so a new endpoint cannot be added without it.

**The access rule does not follow the risk rating, and that is worth understanding before changing either.** Every endpoint here is registered at `low` or `medium` risk — this is the only module in the document stack holding **no applicant data at all**. A signatory is a staff member's name and a link to their signature image; a template is a slug and a label. The Admin-only rule is inherited from the *consumer*, not the content: `concepts/document_templates.txt` — *"No Lead Manager maintenance access in V1 if the rest of the document stack is Admin-only, which is the current direction."* It is, and a Lead Manager who cannot open a document workspace has no way to use a signatory picker.

If Lead Managers are ever given document access, this app should follow in the same change rather than being re-argued from scratch. **No endpoint in this app is public.**

**No `DELETE` method is exposed on any resource.** Withdrawal from use is `POST .../status/` with `inactive` — see `DATA_CONTRACT.md` "Soft Delete" on both models.

---

## Error codes

All codes live in `document_templates/constants.py` `ErrorCode`.

| Code | HTTP | Meaning |
|------|------|---------|
| `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` | 403 | The caller is not an Admin |
| `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` | 404 | No signatory with the id in the URL path |
| `DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND` | 404 | No template with the id in the URL path |
| `DOCUMENT_TEMPLATES_KEY_ALREADY_EXISTS` | 400 | A template with that key is already registered |
| `DOCUMENT_TEMPLATES_KEY_IMMUTABLE` | 400 | A `PATCH` carried `key` |
| `DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID` | 400 | The slug does not agree with the family |
| `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` | 400 | A `PATCH` carried `status` or `status_note` |
| `DOCUMENT_TEMPLATES_STATUS_INVALID_TRANSITION` | 400 | **Unreachable over HTTP** — see below |

Serializer-level failures return the project-wide `VALIDATION_ERROR` (400) with the offending fields in `error.details`.

**`DOCUMENT_TEMPLATES_STATUS_INVALID_TRANSITION` has no reachable HTTP path.** Both status serializers declare `status` as a `ChoiceField`, so a value outside the enum fails there with the project-wide `VALIDATION_ERROR` and never reaches `services.assert_status_selectable`. The code is registered so the envelope is defined if a non-serializer caller is ever added. It was originally used for the `PATCH`-carrying-`status` guard as well; that was renamed to `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` — matching `documents`' equivalent — because **no transition in this app is ever invalid**: `LifecycleStatus` allows every state from every state, so a code named for an invalid transition described a rule that does not exist.

**`DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID` is re-coded from `documents`.** The key/family agreement rule is imported wholesale from `documents.services`, so it raises that app's `TemplateKeyInvalidError`. It is translated at this app's view boundary, because a consumer calling a `/document-templates/` route should never receive a `DOCUMENTS_*` code naming a route it did not call.

---

## 1. Signatories

The signature library. This is the record `documents`' `content.instructorId` and `content.directorId` point at, and the one `document_history` freezes into `render_context.signatories`.

### 1.1 List signatories

- **URI:** `GET /api/v1/document-templates/signatories/`
- **Permission key:** `document_templates.signatory.list`
- **Auth:** required. Admin only.
- **Query parameters:** `status` (`draft` | `active` | `inactive`), `role`, `search`, `page`, `page_size`.
- **Response:** paginated list of `Signatory` — `DATA_CONTRACT.md` §1. Alphabetical by `name_np`.
- **Business rules:** omitting `status` returns draft and inactive signatories too. **The frontend's picker calls this with `?status=active`** — a draft signatory is excluded alongside a retired one, because being unfinished and being retired are different reasons for the same answer.
- **Query access pattern:** `selectors.filter_signatories` over `get_signatories()` — one query, `select_related("created_by")`, served by `signatory_status_name_idx`. `?search=` runs `icontains` across all three name forms with OR semantics, each carried by its own GIN trigram index (§39.6). `title` is deliberately **not** searched: it has no romanized sibling, so a title search would work in one script and silently fail in the other.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400) on an unrecognised `status`.
- **AI debugging notes:** if the picker is empty after seeding signatories, check `status` — they are created `draft` and must be activated explicitly.

### 1.2 Create a signatory

- **URI:** `POST /api/v1/document-templates/signatories/`
- **Permission key:** `document_templates.signatory.create`
- **Auth:** required. Admin only.
- **Request:**

```json
{
  "name_np": "सुनिता श्रेष्ठ",
  "name_en": "Sunita Shrestha",
  "title_np": "निर्देशक",
  "title_en": "Director",
  "role": "director",
  "signature_image_url": "https://files.example/signatures/sunita.png"
}
```

  Only `name_np` is required. **There is no `status` field** — a new signatory is always `draft`.
- **Response:** `201` with the full `Signatory`, including the derived `name_romanized`.
- **Validation rules:** `name_np` required, max 255; `role` max 100; `signature_image_url` must be a well-formed URL; every text field Unicode-normalized (§39.2). `name_romanized` is accepted but not required — the service derives it from `name_np` when absent and keeps a hand-corrected value when present (§39.3).
- **Business rules:** created as `draft`. A signatory with no signature image yet is not one a certificate should be able to name, so activation is a separate, recorded decision.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400).

### 1.3 Retrieve a signatory

- **URI:** `GET /api/v1/document-templates/signatories/<signatory_id>/`
- **Permission key:** `document_templates.signatory.read`
- **Response:** the full `Signatory` — `DATA_CONTRACT.md` §1.
- **Business rules:** a deactivated signatory is still retrievable by id, and always will be — snapshots that froze this id must keep resolving.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404).

### 1.4 Edit a signatory

- **URI:** `PATCH /api/v1/document-templates/signatories/<signatory_id>/`
- **Permission key:** `document_templates.signatory.update`
- **Request:** any subset of `name_np`, `name_en`, `name_romanized`, `title_np`, `title_en`, `role`, `signature_image_url`.
- **Response:** the updated `Signatory`.
- **Business rules:** changing `name_np` **re-derives** `name_romanized` unless one is supplied in the same request — without that, a rename would leave a stale romanization and silently break Roman-script search for that record. Covered by `tests/test_services.py::SignatoryLocalizationTests`. A no-op PATCH writes no audit event.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404), `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` (400) if the body carries `status` or `status_note`, `VALIDATION_ERROR` (400).
- **AI debugging notes:** `status` is rejected here rather than dropped, matching `documents`/`offers`/`clients` — a client that sent it and got 200 back would believe the signatory had been activated.

### 1.5 Change a signatory's status

- **URI:** `POST /api/v1/document-templates/signatories/<signatory_id>/status/`
- **Permission key:** `document_templates.signatory.change_status`
- **Request:** `{ "status": "active", "note": "Signature received." }` — `note` optional, max 2000.
- **Response:** the updated `Signatory`.
- **Business rules:** any of the three statuses may be set, in any order. **The note is optional on every transition** — unlike archiving a document, which demands a reason because the record leaves circulation forever, deactivating here is reversible and loses nothing. Deactivating removes the signatory from the picker and **does not** affect documents or snapshots that already name them.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404), `VALIDATION_ERROR` (400) — including a status outside the enum.

---

## 2. Templates

The catalogue of slugs the document picker offers. **Advisory** — `documents` does not consult it.

### 2.1 List templates

- **URI:** `GET /api/v1/document-templates/templates/`
- **Permission key:** `document_templates.template.list`
- **Query parameters:** `family`, `status`, `search`, `page`, `page_size`.
- **Response:** paginated list of `DocumentTemplate` — `DATA_CONTRACT.md` §2. Grouped by family, then `display_order`, then label.
- **Query access pattern:** `selectors.filter_templates` — one query, `select_related("created_by")`, served by `template_family_status_idx`. `?search=` is a plain `icontains` over `label` and `key` with **no trigram index behind it**: the catalogue is 53 rows and will not meaningfully grow, so an index would cost writes to serve a scan that is already trivial. Both fields are ASCII by construction — a key is a validated slug (§39.7), a label is picker shorthand — so there is no script-mismatch problem to solve.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `VALIDATION_ERROR` (400) on an unrecognised `family` or `status`.

### 2.2 Register a template

- **URI:** `POST /api/v1/document-templates/templates/`
- **Permission key:** `document_templates.template.create`
- **Request:** `{ "key": "bank-vyas-statement", "family": "bank_statement", "label": "Vyas Statement", "description": "", "display_order": 10 }`
- **Response:** `201` with the full `DocumentTemplate`.
- **Validation rules:** `key` unique and matching `^[a-z0-9]+(?:-[a-z0-9]+)*$` (validator imported from `documents`); `key` must agree with `family` by prefix, and by suffix for the two bank families (rule imported from `documents.services`).
- **Business rules:** created as `draft`. **Send `family` and `key` together, from one picker** — they are cross-validated by the same rule `documents` applies when a document is created, so a catalogue row that fails it could never back a real document.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `DOCUMENT_TEMPLATES_KEY_ALREADY_EXISTS` (400), `DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID` (400), `VALIDATION_ERROR` (400).
- **AI debugging notes:** a malformed slug (`"Bank Vyas"`) fails at the **serializer** with `VALIDATION_ERROR` on `key`, while a well-formed slug in the wrong family (`bank-vyas-statement` under `lor`) reaches the **service** and fails with `DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID`. Both are 400; the codes differ because the layers do. Exactly the same split as `documents`.

### 2.3 Retrieve a template

- **URI:** `GET /api/v1/document-templates/templates/<template_id>/`
- **Permission key:** `document_templates.template.read`
- **Response:** the full `DocumentTemplate`.
- **Business rules:** a retired template is still retrievable by id — that is what makes retirement safe for documents that already name it.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND` (404).

### 2.4 Edit a template

- **URI:** `PATCH /api/v1/document-templates/templates/<template_id>/`
- **Permission key:** `document_templates.template.update`
- **Request:** any subset of `family`, `label`, `description`, `display_order`.
- **Response:** the updated `DocumentTemplate`.
- **Business rules:** **`key` is immutable and is rejected, not dropped.** Documents point at it as a plain string with no foreign key behind them, so a rename would orphan every document that used it, silently. Changing `family` re-runs the agreement check against the existing `key`.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND` (404), `DOCUMENT_TEMPLATES_KEY_IMMUTABLE` (400), `DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID` (400), `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` (400), `VALIDATION_ERROR` (400).

### 2.5 Change a template's status

- **URI:** `POST /api/v1/document-templates/templates/<template_id>/status/`
- **Permission key:** `document_templates.template.change_status`
- **Request:** `{ "status": "inactive", "note": "Partner closed." }`
- **Response:** the updated `DocumentTemplate`.
- **Business rules:** `concepts/document_templates.txt` flow 4 — *"Retirement must not break old document records that already point at the template key."* It cannot: `documents` never consults this table, so retiring a row changes exactly one thing, which is whether a client's picker still offers it.
- **Errors:** `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403), `DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND` (404), `VALIDATION_ERROR` (400) — including a status outside the enum.

---

## 3. Management command

`python manage.py seed_document_templates` loads the 53 transcribed slugs from `document_templates/seed_data.py`. Not an endpoint and not reachable over HTTP — documented here because it is how a fresh environment gets a usable catalogue. Flags: `--dry-run`, `--activate`, `--username`. Idempotent; never modifies an existing row. See `DATA_CONTRACT.md` §4 and `requirements/README.md`.
