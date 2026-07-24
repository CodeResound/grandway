# Iteration — 20260724_1734

## Document Templates

## 1. Module

- **Name:** Document Templates
- **Base path:** `/api/v1/document-templates/`
- **Auth:** Bearer access JWT on every endpoint. Admin authority only — `lead_manager` and `superadmin` receive 403 on every route including reads.

## 2. Conventions

- **Response:** standard envelope — `success`, `message`, `data`, `meta`.
- **Error:** `success` is `false`; `error` carries `code`, `message`, and a `details` object that is always present (`{}` when there are no field-level errors). Query-string failures use the same shape, keyed by the parameter name.
- **Auth failures:** 401 with no token or an expired one. 403 `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` when the token is valid but the caller is not an Admin — on every route.
- **HTTP status codes:** both `POST` collection endpoints return **201**. All four `GET`s, both `PATCH`es, and both `POST .../status/` actions return **200**. **No 409 anywhere** — no operation here can conflict with another's state.
- **Pagination:** page-number based. `page` and `page_size`, default 20, max 100 (clamped, not rejected). `data` is the bare array of rows, not nested under `results`. `meta` carries `count` (total across all pages), `page`, `page_size`, `next`, `previous`. Both list endpoints. The 53-row catalogue is three requests at the default size.
- **IDs:** UUID strings. A template's `key` is unique and human-readable but is **not an address** — every route takes the UUID `id`.
- **Times:** `created_at` and `updated_at`, ISO 8601 UTC. **No Bikram Sambat siblings and no `?fiscal_year=` filter**, unlike `documents` and `document_history` — both timestamps are system bookkeeping on a reference library, and neither resource has a business date.
- **Query parameters:** a recognised parameter with an invalid value is rejected with 400; an unrecognised parameter is silently ignored; no multi-value syntax. **Omitting `status` returns everything** — draft, active, and inactive. There is no implicit `active` default.
- **Ordering** is fixed and not client-controllable. Signatories by `name_np`; templates by `family`, then `display_order`, then `label`.
- **Empty text fields are `""`, never `null`.** No field on either resource is nullable.

## 3. Models

**Signatory** — `{ id, name_np, name_en, name_romanized, title_np, title_en, role, signature_image_url, status:[enum], is_active, status_note, created_by_username, created_at, updated_at }`

- One shape for list and detail — there is no large column to withhold.
- `name_np` and `name_en` are two independent identities, not translations (§39.1). `name_romanized` is a search aid, never displayed.
- **A `PATCH` that changes `name_np` re-derives `name_romanized`** unless one is supplied in the same request; a supplied value is kept on create and update alike. The transliteration scheme is not part of the contract.
- `is_active` is `status == "active"` — a `draft` signatory is not active.
- `signature_image_url` may be `""`, and is a link, never an upload.

**DocumentTemplate** — `{ id, key, family:[enum], label, description, display_order, status:[enum], is_active, status_note, created_by_username, created_at, updated_at }`

- `key` is the string `documents` stores, and is unique and immutable.
- `label` is what you render; `key` is a machine slug.
- `display_order` is per-family, not global.

## 4. Enums

- `Signatory.status` / `DocumentTemplate.status`: `draft` | `active` | `inactive` — every record starts `draft`; any transition to any state is allowed, in any order.
- `DocumentTemplate.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate` — **open, not closed.** Imported from `documents` rather than redeclared; a family added there appears here with no version bump. Do not generate a closed union type. There is no endpoint that enumerates it.
- `Signatory.role`: **not an enum.** Free text up to 100 characters. `director` and `instructor` are observed, not constrained.
- `DocumentTemplate.key`: **not an enum** — a lowercase ASCII slug matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`, which must agree with `family` by prefix and, for the two bank families, by suffix.

## 5. Dependency order

- A `Signatory` needs **nothing** — the only resource in the whole document stack with no prerequisite record.
- A `DocumentTemplate` needs **nothing**, though its `family` must be one of the six values `documents` defines.
- A `Document` **(external module: `documents`)** needs neither — it accepts any well-formed `template_key` and any string in `content.instructorId`, registered here or not.

**Start here:** `POST /signatories/`, then activate it. The signatory picker is the one screen in the document stack that is empty without this module.

## 6. Endpoints

### Signatory — `/api/v1/document-templates/signatories/`

**Use it when:** the Signatory Library management screen, and — the one call the frontend makes into this module — populating the instructor/director selects in the certificate document editor.

**Methods:**

- `GET /signatories/` — `document_templates.signatory.list`
- `POST /signatories/` — `document_templates.signatory.create`
- `GET /signatories/<signatory_id>/` — `document_templates.signatory.read`
- `PATCH /signatories/<signatory_id>/` — `document_templates.signatory.update`

**Send (create):**

- `name_np` — string, **required**, max 255
- `name_en`, `title_np`, `title_en` — string, optional, max 255
- `name_romanized` — string, optional; derived from `name_np` when omitted
- `role` — string, optional, max 100
- `signature_image_url` — URL, optional, max 500

**Send (update):** any subset of the same fields; `name_np` is optional here.

**Returns:** `Signatory` from create (201), retrieve and update (200); `list[Signatory]` from the library (200).

**Notes:**

- A new signatory is always `draft` — there is no `status` field on create, and a picker filtered to `?status=active` will not show one you just created.
- `status` and `status_note` are **rejected** on `PATCH`, not ignored.
- Query parameters: `status`, `role` (exact, case-insensitive), `search`, `page`, `page_size`. `search` matches all three name forms; not `title` or `role`.
- **Renaming a signatory retroactively changes what every live document appears to say**, because only the id is stored. A print snapshot froze the name and keeps showing the old one.

**Errors:**

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403) — applies to every method including `GET`
- `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404)
- `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` (400) — a `PATCH` carried `status` or `status_note`
- `VALIDATION_ERROR` (400) — missing `name_np`, a malformed `signature_image_url`, an over-long field, or an unrecognised `status` in the query string

### Signatory status — `POST /signatories/<signatory_id>/status/`

**Use it when:** activating a new signer once their signature image is in place, or retiring one who has left.

**Methods:**

- `POST /signatories/<signatory_id>/status/` — `document_templates.signatory.change_status`

**Send:**

- `status` — **required**, one of `draft` | `active` | `inactive`
- `note` — string, optional, max 2000

**Returns:** `Signatory` (200).

**Notes:**

- No status precondition — any transition from any state, including reactivating a retired signer.
- The note is optional on every transition, unlike archiving a document.
- Setting the current status with no note is a no-op and writes no event.
- **Documents and snapshots naming this signatory are completely unaffected.**

**Errors:**

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403)
- `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404)
- `VALIDATION_ERROR` (400) — missing `status`, a status outside the enum, or a `note` over 2000 characters

### DocumentTemplate — `/api/v1/document-templates/templates/`

**Use it when:** the Template Catalog management screen, and backing the document type picker in the New Document form.

**Methods:**

- `GET /templates/` — `document_templates.template.list`
- `POST /templates/` — `document_templates.template.create`
- `GET /templates/<template_id>/` — `document_templates.template.read`
- `PATCH /templates/<template_id>/` — `document_templates.template.update`

**Send (create):**

- `key` — string, **required**, max 100; must agree with `family`
- `family` — **required**, one of the six values
- `label` — string, **required**, max 255
- `description` — string, optional, max 5000
- `display_order` — integer ≥ 0, optional, defaults to 0

**Send (update):** any subset of `family`, `label`, `description`, `display_order`. **`key` is not accepted.**

**Returns:** `DocumentTemplate` from create (201), retrieve and update (200); `list[DocumentTemplate]` from the catalogue (200).

**Notes:**

- **`key` is immutable and rejected on `PATCH`, not dropped.**
- Send `key` and `family` together from one control — they are cross-validated by the rule `documents` owns.
- Changing `family` re-runs the agreement check against the existing `key`.
- A new template is always `draft`.
- Query parameters: `family`, `status`, `search`, `page`, `page_size`.

**Errors** — when a payload trips more than one, they fire serializer-first, then uniqueness, then family agreement:

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403)
- `DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND` (404)
- `DOCUMENT_TEMPLATES_KEY_ALREADY_EXISTS` (400)
- `DOCUMENT_TEMPLATES_KEY_IMMUTABLE` (400)
- `DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID` (400)
- `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` (400)
- `VALIDATION_ERROR` (400)

### DocumentTemplate status — `POST /templates/<template_id>/status/`

**Use it when:** publishing a newly registered slug to the picker, or retiring a bank partner.

**Methods:**

- `POST /templates/<template_id>/status/` — `document_templates.template.change_status`

**Send:**

- `status` — **required**, one of `draft` | `active` | `inactive`
- `note` — string, optional, max 2000

**Returns:** `DocumentTemplate` (200).

**Notes:**

- **No existing document changes and none can break** — `documents` does not consult this table. Retiring changes exactly one thing: whether your picker offers it.
- A retired template stays retrievable by id forever.

**Errors:**

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403)
- `DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND` (404)
- `VALIDATION_ERROR` (400)

## 7. Flows

**Add a certificate signer**

1. `GET /api/v1/document-templates/signatories/` → the library, unfiltered.
2. Host the signature image yourself, then `POST /api/v1/document-templates/signatories/` → `Signatory`, `status: "draft"`.
   - *Failure — `VALIDATION_ERROR` on `name_np`:* the Devanagari name is required.
   - *Failure — `VALIDATION_ERROR` on `signature_image_url`:* must be a well-formed URL. There is no upload endpoint.
3. `POST /api/v1/document-templates/signatories/<id>/status/` with `active` → now in the picker. **Not optional** — without it the signer is invisible to `?status=active`.

**Fill the instructor and director selects**

1. `GET /api/v1/document-templates/signatories/?status=active` → the options.
2. Put the chosen row's `id` into `content.instructorId` / `content.directorId` and `PATCH /api/v1/documents/<document_id>/` (module: `documents`) with the complete `content`.
   - **Nothing validates those ids.** A typo, a stale id, or the id of a `draft` signatory are all accepted with a 200.
3. On print, freeze the signatory's name and role alongside the id into `render_context.signatories` (module: `document_history`), so the snapshot survives a later rename.

**Retire a bank partner from the picker**

1. `GET /api/v1/document-templates/templates/?family=bank_statement` → find the row.
2. `POST /api/v1/document-templates/templates/<id>/status/` with `inactive`.
3. The row leaves `?status=active` and stays retrievable by id. **Every existing document using that slug is untouched and still fully editable.**

**Build the New Document type picker**

1. `GET /api/v1/document-templates/templates/?status=active&page_size=100` → the catalogue, grouped by `family` and ordered by `display_order`.
2. Send the row's `key` and `family` together when creating the document.
   - **A slug absent from this catalogue is still accepted by `documents`.** The catalogue constrains your picker, not the API.

## 8. Gaps

- **`family` is an open enum and no endpoint enumerates it.** A hardcoded list that lags cannot register a new family; one that leads breaks the catalogue filter, because an unrecognised `family` in a query string is a 400.
- **`role` is unconstrained free text.** Do not build a closed dropdown from observed values, and do not filter the picker by it.
- **No concurrency control anywhere** — no ETag, no `If-Match`, no `updated_at` precondition. Last-write-wins, silently.
- **`created_by_username` is a username string with no user id** — no join, no avatar, breaks on a username change.
- **No bulk reorder.** `display_order` is one `PATCH` at a time with no transaction across them.
- **No lookup-by-key endpoint.** Holding a `template_key` and wanting its label means listing the catalogue and matching client-side.
- **No template definition of any kind** — no sections, field hints, signature slots, layout, preview, or version chain. The Template Editor, Template Detail / Version History, and Template Preview screens in the concept file have no backing endpoints, deliberately.
- **No signature image storage.** A link to a host this API knows nothing about; no upload, no validation, no reachability check.
- **The catalogue is advisory.** `documents` accepts any well-formed `template_key`, registered or not, active or not.
- **No Bikram Sambat dates and no `?fiscal_year=` filter**, unlike the other two document modules.
- **401 bodies are not enumerated here**; distinguishing "refresh silently" from "redirect to login" needs `authenticate`'s contract.
- **The permission keys are not enforced in the request path** — access is decided solely by the `admin` authority check.
- **The seeded catalogue may not match the real template set.** 53 slugs transcribed from a frontend contract whose heading says 42.

---

## Documents

## 1. Module

- **Name:** Documents
- **Base path:** `/api/v1/documents/`
- **Auth:** Bearer access JWT. Admin authority only.

## 2. Conventions

No change this session.

## 3. Models

No change this session. No field was added, removed, or renamed on `Document`.

## 4. Enums

No change this session. `Document.family` is now **imported by** `document_templates` rather than redeclared there (§4 — no duplicated enums), so this app remains its single definition. The six values are unchanged.

## 5. Dependency order

Unchanged outbound. One inbound edge is new and is weaker than the `document_history` one: `document_templates` imports this app's `family` enum, slug validator, and key/family rule at the Python level and holds **no database relation to `Document` at all**. This app imports nothing from it and does not consult it.

## 6. Endpoints

**No endpoint was added, changed, or retired in this module this session.** All nine remain exactly as registered, with the same paths, methods, permission keys, request shapes, response shapes, and error codes. No migration, no validator change, no behaviour change of any kind.

Two notes for a client, arising from the new module rather than from any change here:

- **The template catalogue is advisory and this module does not enforce it.** A `template_key` absent from `document_templates`, or present but retired, is still accepted by `POST /documents/`. Verified empirically against a running server this session.
- **A signatory picker now exists**, at `GET /api/v1/document-templates/signatories/?status=active`. Put the chosen record's `id` into `content.instructorId` / `content.directorId`. **This module still does not validate those ids** — it stores `content` as an opaque body and does not look inside it.

## 7. Flows

**Prepare a document with a real signatory** — the previously unbacked dropdown now resolves.

1. `GET /api/v1/document-templates/templates/?status=active` (module: `document_templates`) → populate the type picker.
2. `POST /api/v1/documents/` with `family` and `template_key` from one catalogue row.
3. `GET /api/v1/document-templates/signatories/?status=active` (module: `document_templates`) → populate the instructor and director dropdowns.
4. `PATCH /api/v1/documents/<document_id>/` with the chosen ids inside the complete `content`.
5. Print via `document_history`, freezing the resolved signatory name and role.

## 8. Gaps

- **Narrowed, not closed:** the signatory reference gap. A picker now exists, but `content.instructorId` / `content.directorId` remain unvalidated on write — a typo, a stale id, or a `draft` signatory are all accepted silently.
- **Restated, not closed:** "no template registry" is no longer accurate as written — a registry exists and this module does not consult it. A typo matching the family prefix is still accepted.
- **Corrected:** every reference to "42 template shapes" or "42 slugs" is now **53**. The number was inherited from `frontend_data-contract.md`, whose heading says 42 while its own list contains 53 (4 student + 11 woda + 11 lor + 5 moi + 22 bank). Worth confirming against the real template set.
- **Unchanged:** no supporting files; a client-supplied derived value is stored rather than stripped; `content` is replaced wholesale on `PATCH`; `?search=` matches `label` only; no bulk operations.

---

## Document History

## 1. Module

- **Name:** Document History
- **Base path:** `/api/v1/document-history/`
- **Auth:** Bearer access JWT. Admin authority only.

## 2. Conventions

No change this session.

## 3. Models

No change this session.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session. `document_templates` shipped, and this module gained **no dependency on it in either direction** — no foreign key, no import, no call.

## 6. Endpoints

**No endpoint was added, changed, or retired in this module this session.** All six remain exactly as registered.

One note for a client: the signatory ids frozen into `render_context.signatories` now **resolve** against `GET /api/v1/document-templates/signatories/<id>/`, and a retired signatory stays retrievable forever precisely so old snapshots keep working. This module's behaviour did not change — it still validates nothing inside `render_context`.

## 7. Flows

No flow changed. The capture flow's guidance is sharpened: **keep freezing the signatory's name and role alongside the id**, because an id alone leaves a snapshot dependent on a lookup that may return a since-renamed record — which is what freezing exists to prevent.

## 8. Gaps

- **Narrowed:** "signatory ids inside `render_context` reference nothing" is no longer accurate — they reference a real table. They remain **unvalidated at write time**, because this module stores `render_context` verbatim.
- **Unchanged:** no generated-file storage; no compare endpoint; no cross-document view; `render_context` completely unvalidated; `family` open; actor exposed only as a username string.

---

## Core

## 1. Module

- **Name:** Core — project infrastructure and the API root.
- **Base path:** `/api/v1/` plus the unversioned `/health/`, `/ready/`, `/admin/`.
- **Auth:** unchanged.

## 2. Conventions

No change this session.

## 3. Models

No change this session. `core.policy_engine` gained ten endpoint registrations but no schema change.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session.

## 6. Endpoints

**No `core` endpoint was added, changed, or retired this session.** `core.api_urls` gained one route include mounting `document_templates` at `/api/v1/document-templates/`; the ten endpoints behind it belong to that module.

Ten new registrations were synced into the Core Policy Engine (126 total), and the committed registry and OpenAPI artifacts were regenerated:

- `document_templates.signatory.{list,create,read,update,change_status}` — `low`/`medium`
- `document_templates.template.{list,create,read,update,change_status}` — `low`/`medium`

All ten sit under the existing `document_management` permission category, shared with `documents` and `document_history`. **Every rating is lower than its equivalent in the other two document modules** — this is the only app in the stack holding no applicant data.

## 7. Flows

No `core` flow changed. The project-level dependency graph gained one node and one edge; the app inventory gained one row; §10's access table gained `document_templates` to its Admin-only row.

## 8. Gaps

- **Narrowed:** the unbuilt-document-domains note drops from two apps to one. Only `uploaded_files` remains, and the consequence is sharper now that everything around it works — **no file can be stored anywhere in this system.**
- **New:** two cross-module references travel as bare strings inside JSON with nothing validating either — a document's `template_key` and its `content.instructorId`.
- **Fixed:** a §19.5 review caught that v1.6.1 had added an entire app to the inventory and dependency graph without a change-history entry — the exact defect v1.2.0 was written to prevent. v1.7.0 closes it.
