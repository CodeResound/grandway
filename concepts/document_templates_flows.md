# FLOWS — Document Templates

**Owner app:** `document_templates`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/document_templates.txt` to the callable endpoints in
`backend/document_templates/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **Five things govern every flow below.**
>
> 1. **Admin only — a Lead Manager cannot open any of these screens.** Not read-only, not empty:
>    **hidden**. Note that this is *not* because the data is sensitive — there is no applicant data
>    in this module at all. It is inherited from the consumer: a Lead Manager cannot open a document
>    workspace, so a signatory picker is a screen they can never reach.
> 2. **This module stores what is *offered*, not what is *rendered*.** The templates are frontend
>    code. Nothing here describes sections, field layout, or how a document draws itself, and no
>    endpoint ever will — see "Not backed" below before designing a Template Editor.
> 3. **Everything is created as `draft`.** A signatory or template you just created will **not**
>    appear in a picker filtered to `?status=active`. Activation is a separate, deliberate call.
> 4. **Nothing is ever deleted.** No `DELETE` on any route. Retirement is a status change, and a
>    retired record stays retrievable by id forever so old documents and snapshots keep resolving.
> 5. **Both of this module's libraries are advisory.** `documents` does not check the template
>    catalogue and does not validate signatory ids. **Your picker is the only guard** — see the
>    warnings in each flow.

---

## Flow: Add a certificate signer

- **Actor:** Admin
- **Goal:** Get a new director or instructor into the signature library so certificates can name them.
- **Entry point:** Signatory Library

**Steps:**

1. **Signatory Library** — load what exists →
   `GET /api/v1/document-templates/signatories/` (`document_templates.signatory.list`)
   - **Requires state:** nothing. This module has no prerequisite record of any kind.
   - **Side effects:** none.
   - **Hide this entire screen for a Lead Manager.** They receive 403
     `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN`.
   - Omit `status` here — the management screen should show draft and retired signers, not just
     active ones. That is the opposite of what the picker wants.

2. **Signatory Library → Add** — host the signature image first, then create the record →
   `POST /api/v1/document-templates/signatories/` (`document_templates.signatory.create`)
   - **Requires state:** nothing.
   - **Side effects:** appends `signatory_created` to the audit log. Nothing outside this module
     changes.
   - **There is still no image upload.** `signature_image_url` is a link to a host this project
     knows nothing about — put the file somewhere yourself first. **Do not ship a file-picker
     control.** `uploaded_files` shipped on 2026-07-24, but a `Signatory` is **not** one of its five
     owner types, so there is nowhere to attach a signature image even by hand; migrating this field
     is a separate, unscheduled decision.
   - **`name_np` is required, `name_en` is not.** They are two independent identities (§39.1), not a
     field and its translation — collect both for a real person.
   - **Never render `name_romanized`.** It is a search aid derived from `name_np`. It is returned so
     you can search on it, not display it.
   - *Failure — `VALIDATION_ERROR` on `name_np`:* the Devanagari name is mandatory. Make it a
     required field on the form.
   - *Failure — `VALIDATION_ERROR` on `signature_image_url`:* it must be a well-formed URL. The API
     never fetches it, so a well-formed link to nothing passes.

3. **Signatory Library** — activate once the signature is in place →
   `POST /api/v1/document-templates/signatories/<signatory_id>/status/`
   (`document_templates.signatory.change_status`)
   - **Requires state:** the signatory. **No status precondition** — any transition from any state.
   - **Side effects:** appends `signatory_status_changed` and sets `status_note`.
   - **This step is not optional.** A signatory created in step 2 is `draft` and will not appear in
     the picker until this runs. A UI that omits it will look broken to the person who just added a
     signer.
   - The note is **optional** here, unlike archiving a document — deactivating is reversible and
     loses nothing.

---

## Flow: Fill the instructor and director selects

- **Actor:** Admin
- **Goal:** Put real signatory ids into a certificate document.
- **Entry point:** Document Workspace → certificate form (from `concepts/documents.txt`)

**Steps:**

1. **Document Workspace** — load the options →
   `GET /api/v1/document-templates/signatories/?status=active`
   (`document_templates.signatory.list`)
   - **Requires state:** nothing.
   - **Side effects:** none.
   - **This is the one call the frontend makes into this module.** It replaces the hardcoded
     signature list.
   - Render `name_en` or `name_np` plus `title_en`; send the row's **`id`**.
   - **Do not filter the dropdown by `role`.** A signatory's `role` is free text describing who they
     are, not which slot they may fill — a director may legitimately sign as the instructor.

2. **Document Workspace** — save the document with the chosen ids →
   `PATCH /api/v1/documents/<document_id>/` (`documents.document.update`)
   **(cross-app: `documents`)**
   - **Requires state:** the document must not be archived.
   - **Side effects:** appends `document_updated` in `documents`, with the body redacted.
   - Put the ids in `content.instructorId` and `content.directorId`, and **send the complete
     `content`** — that app replaces the body wholesale.
   - **Nothing validates these ids.** `documents` stores `content` as an opaque body and does not
     look inside it: a typo, a stale id, or the id of a `draft` signatory are all accepted with a
     200. **Your dropdown is the only guard there is.**

3. **Print Preview** — freeze the resolved signer into the snapshot →
   `POST /api/v1/document-history/documents/<document_id>/snapshots/`
   (`document_history.snapshot.capture`) **(cross-app: `document_history`)**
   - **Requires state:** the document, and its body already saved.
   - **Side effects:** creates a snapshot and its capture event in that module.
   - **Freeze the signatory's `name` and `role` alongside the `id`** in
     `render_context.signatories`. An id alone leaves the snapshot dependent on a later lookup that
     may return a since-renamed record — which is exactly what freezing exists to prevent.

---

## Flow: Retire a signer who has left

- **Actor:** Admin
- **Goal:** Stop offering a signatory without breaking documents that already name them.
- **Entry point:** Signatory Library

**Steps:**

1. **Signatory Library** →
   `POST /api/v1/document-templates/signatories/<signatory_id>/status/` with `inactive`
   (`document_templates.signatory.change_status`)
   - **Requires state:** the signatory.
   - **Side effects:** appends `signatory_status_changed`. **No document or snapshot changes.**
   - **Label the button "Retire", not "Delete".** Say in the confirmation that the record is kept —
     it must be, because snapshots reference it.
   - Reversible: the same endpoint with `active` brings them back.

2. **Consequences to surface in the UI, because the API will not:**
   - The signer disappears from `?status=active` immediately.
   - **Every existing document naming them still renders their name**, because `documents` stores
     only the id and resolves it at render time.
   - **A retired signer is still retrievable by id** —
     `GET /api/v1/document-templates/signatories/<id>/` works forever. That is deliberate.

---

## Flow: Retire a bank partner from the document picker

- **Actor:** Admin
- **Goal:** Stop offering a template for new documents without touching existing ones.
- **Entry point:** Template Catalog

**Steps:**

1. **Template Catalog** — find the row →
   `GET /api/v1/document-templates/templates/?family=bank_statement`
   (`document_templates.template.list`)
   - **Requires state:** nothing.
   - **Side effects:** none.
   - Rows arrive grouped by `family` and ordered by `display_order` — render in that order rather
     than re-sorting alphabetically, which is what the ordering exists to avoid.

2. **Template Catalog** — retire it →
   `POST /api/v1/document-templates/templates/<template_id>/status/` with `inactive`
   (`document_templates.template.change_status`)
   - **Requires state:** the template.
   - **Side effects:** appends `template_status_changed`. **No document changes and none can break.**
   - `concepts/document_templates.txt` flow 4 requires that retirement not break records pointing at
     the key. It cannot: `documents` never reads this table.
   - *No failure branch worth handling* — there is no state this can conflict with. This module has
     no 409 anywhere.

3. **New Document Form** — the picker, fed by `?status=active`, stops offering it.
   - **Existing documents using that slug remain fully editable.** If you need them blocked, that is
     a client decision; this API will not make it.

---

## Flow: Register a new template slug

- **Actor:** Admin
- **Goal:** Add a slug the frontend has started supporting to the catalogue.
- **Entry point:** Template Catalog → Add

**Steps:**

1. **Template Catalog → Add** →
   `POST /api/v1/document-templates/templates/` (`document_templates.template.create`)
   - **Requires state:** nothing.
   - **Side effects:** appends `template_created`.
   - **This does not make the template renderable.** The frontend must already support the slug —
     registering it here only makes it *offerable*. Registering a slug the frontend cannot draw
     produces documents nobody can print.
   - **Send `key` and `family` from one control.** They are cross-validated by the same rule
     `documents` applies, so a `bank-` slug under family `lor` is refused.
   - *Failure — `DOCUMENT_TEMPLATES_KEY_ALREADY_EXISTS`:* the slug is registered. Offer to edit the
     existing row instead.
   - *Failure — `DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID`:* the slug and family disagree. A UI bug,
     not user error, if they came from one control.
   - *Failure — `VALIDATION_ERROR` on `key`:* malformed slug — uppercase, spaces, or underscores.

2. **Template Catalog** — publish it →
   `POST /api/v1/document-templates/templates/<template_id>/status/` with `active`
   - As with signatories, a newly registered template is `draft` and will not appear in the picker
     until this runs.

3. **The 53 slugs already in use are seeded**, not created through this flow — see
   `requirements/README.md`. This flow is for the 54th.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `document_templates.signatory.list` | `GET /api/v1/document-templates/signatories/` | Add a signer; Fill the selects; Retire a signer | **The frontend's only call into this module**, with `?status=active` |
| `document_templates.signatory.create` | `POST /api/v1/document-templates/signatories/` | Add a signer | Always creates as `draft` |
| `document_templates.signatory.read` | `GET /api/v1/document-templates/signatories/<id>/` | — | `unused by flow — resolving a single id, e.g. rendering a retired signer named by an old document` |
| `document_templates.signatory.update` | `PATCH /api/v1/document-templates/signatories/<id>/` | Add a signer (corrections) | `status` rejected; use the status action |
| `document_templates.signatory.change_status` | `POST /api/v1/document-templates/signatories/<id>/status/` | Add a signer; Retire a signer | **This is the retire button** |
| `document_templates.template.list` | `GET /api/v1/document-templates/templates/` | Retire a partner; New Document picker (cross-app) | `?family=`, `?status=`, `?search=` |
| `document_templates.template.create` | `POST /api/v1/document-templates/templates/` | Register a slug | `key` + `family` cross-validated |
| `document_templates.template.read` | `GET /api/v1/document-templates/templates/<id>/` | — | `unused by flow — single-row inspection from the catalog` |
| `document_templates.template.update` | `PATCH /api/v1/document-templates/templates/<id>/` | Register a slug (corrections) | `key` **immutable**, rejected not dropped |
| `document_templates.template.change_status` | `POST /api/v1/document-templates/templates/<id>/status/` | Retire a partner; Register a slug | **This is the retire button** |

**Screens from `concepts/document_templates.txt`, and whether they are backed:**

- **Signatory Library** — **fully backed.** List, create, edit, and retire.
- **Template Catalog** — **backed.** List with family and status filters, create, edit, retire.
- **Template Detail / Version History** — **partly backed, and the version half never will be.** The
  detail read exists; there is **no version chain**, so there is no history to show. See below.
- **Template Editor** — **not backed** beyond label, description, family, and display order. There
  is no section order, no field hints, and no signature slots.
- **Template Preview** — **not backed.** No endpoint returns anything renderable.

**Not backed, and deliberately so:**

- **Template versions, sections, field hints, and signature slots.** The templates are frontend code
  — the slugs are a hardcoded union and each content shape is a compiled-in type. No endpoint
  describes them and none is planned; inventing a schema here would guarantee drift from the
  templates that actually render. **Do not build a Template Editor that implies the backend controls
  layout**, and do not build a version-history timeline — there is nothing behind either.
- **Historical reproduction through this module.** The concept asks that a version used by a
  document or snapshot stay available. That already holds without a version chain here:
  `document_history` freezes the template key, version string, and resolved signatories into each
  snapshot's `render_context`, so a snapshot reproduces itself without reading this app at all.
- **Signature image upload.** `signature_image_url` is a link. No upload, no size or type check, no
  reachability check. `uploaded_files` now exists but a `Signatory` is not one of its owner types, so
  this field was deliberately left alone — repointing it would also change a shipped response shape.
- **Lookup by key.** Every route takes the UUID `id`. Holding a `documents.template_key` and wanting
  its label means listing the catalogue and matching client-side — cheap at 53 rows, but there is no
  `?key=` filter.

## Cross-app dependencies

- **This app references (outbound):** `none` at the HTTP level — no flow here calls another app's
  endpoint. The backend imports three Python objects from `documents` (the `family` enum, the slug
  validator, and the key/family rule) so the catalogue cannot accept a pairing that app would
  reject; see `backend/document_templates/docs/INTEGRATION.md` §2. There is **no database relation
  to any app but `authenticate`**.
- **Referenced by other apps (inbound):** `concepts/documents_flows.md` — its New Document picker
  calls `document_templates.template.list` and its certificate form calls
  `document_templates.signatory.list`. `concepts/document_history_flows.md` references the signatory
  picker for the ids frozen into `render_context.signatories`. **Both references are advisory:**
  neither app validates what this one publishes.

**Note the asymmetry across the document stack.** `documents` depends on neither of its two
siblings. `document_history` holds real foreign keys to `documents` and writes through its service.
This app holds no database relation to either and is consulted by neither — it publishes two
libraries that clients are trusted to use.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.

## Open questions

- **Should `documents` enforce the catalogue?** Today a `template_key` absent from it, or retired, is
  still accepted. Enforcing would narrow a shipped endpoint's accepted input (a breaking change,
  §29) and add a runtime dependency from `documents` to this app. Deliberately deferred; it needs
  its own decision.
- **Should `documents` validate signatory ids?** Same shape of question, and harder — it would mean
  parsing `content` per template shape, which that app refuses to do by design.
- **Is the real slug count 42 or 53?** `frontend_data-contract.md` heads its list "42 slugs" and
  lists 53. The seed loads all 53. If 42 is right, eleven seeded rows name templates the frontend
  cannot render, and the picker would offer them.
- **Should a template ever be renderable-but-not-offerable, or vice versa?** Today the catalogue and
  the frontend's union are maintained independently, so either can hold a slug the other lacks, in
  both directions, with nothing reporting the mismatch.
