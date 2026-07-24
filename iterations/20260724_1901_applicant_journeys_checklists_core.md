# Session 20260724_1901 — applicant_journeys, checklists, core

## Checklists

## 1. Module

- **Name:** Checklists
- **Base path:** `/api/v1/checklists/`
- **Auth:** JWT bearer on every route. Admin and Lead Manager reach everything except the four template-authoring routes, which are Admin-only. Superadmin is refused everywhere.

## 2. Conventions

- **Response:** `{ success, message, data, meta }`; the resource is always under `data`.
- **Error:** `{ success: false, error: { code, message, details }, meta }`. `details` is not always field-to-strings — `CHECKLISTS_REQUIRED_ITEMS_PENDING` puts an array of `{ id, label, status }` under `details.items`, and `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS` puts an id string under `details.existing_template_id`.
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401); `CHECKLISTS_ACTOR_FORBIDDEN` (403). Both apply to all 18 endpoints.
- **Success statuses:** `201` on every create; `200` on every read, `PATCH`, and lifecycle action. No `204`.
- **Pagination:** every list endpoint. `?page=`, `?page_size=` (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous`. `data` is a bare array.
- **IDs:** UUID strings.
- **Times:** ISO 8601 UTC, `Z`-suffixed. `due_at` and `completed_at` each carry a `_bs` sibling object with the Bikram Sambat rendering, or `null`.
- **List/search/filter/order params:**
  - `GET /templates/`: `country`, `status`, `is_default`, `search` (matches `label` or `key`)
  - `GET /`: `applicant` (traverses the journey), `journey`, `status`, `origin`, `assigned_to`, `country`, `template`, `overdue`, `journey_missing_checklist`
  - no ordering param on either. Templates sort by `display_order` then `label`; checklists newest first
  - an invalid filter value returns 400, never an empty page

## 3. Models

**ChecklistTemplate** — `{ id, key, label, description, country?:CountryBrief, is_default, is_inheritable, status:[enum], status_note, display_order, notes, items:[ChecklistTemplateItem], created_by:UserBrief, created_at, updated_at }`
- `is_inheritable` is derived — `true` when active, default, and country-scoped. The single field answering "will an applicant reaching this country get this list".
- `items` includes retired definitions, active ones first.

**ChecklistTemplateItem** — `{ id, label, description, item_type:[enum], is_required, display_order, default_due_offset_days?:int, is_active, created_at, updated_at }`

**Checklist** — `{ id, journey, applicant:ApplicantBrief, source_template?, country?:CountryBrief, title, description, origin:[enum], status:[enum], assigned_to?:UserBrief, due_at?, due_at_bs?:json, progress:ChecklistProgress, created_at, updated_at }`
- Retrieve-only extras: `notes`, `items:[ChecklistItem]`, `activated_at?`, `completed_at?`, `completed_at_bs?`, `completed_by?:UserBrief`, `archive_reason`, `archived_at?`, `archived_by?:UserBrief`, `status_before_archive:[enum]`.
- `journey` and `source_template` are bare UUIDs; `applicant` and `country` are nested.
- `created_by` is not in the response shape — an inherited checklist has no author.

**ChecklistProgress** — `{ total, resolved, required_total, required_resolved, blocked, document_total, document_resolved }`
- `resolved` counts `completed`, `waived`, `not_applicable`. `blocked` is not resolved.
- `required_resolved == required_total` is the exact precondition for completion.

**ChecklistItem** — `{ id, checklist, source_template_item?, label, description, item_type:[enum], is_required, display_order, status:[enum], status_note, is_resolved, assigned_to?:UserBrief, due_at?, due_at_bs?:json, evidence_file?, evidence_note, completed_at?, completed_at_bs?:json, completed_by?:UserBrief, created_at, updated_at }`
- `evidence_file` is a bare UUID with no filename or type; resolve it against `/api/v1/files/<id>/`.

**JourneyAwaitingChecklist** — `{ id, applicant:ApplicantBrief, target_country_ref?:CountryBrief, stage, created_at }`
- Returned only under `?journey_missing_checklist=true`. `id` is a **journey** id.

**CountryBrief** — `{ id, code, name_en, name_np }`
**ApplicantBrief** — `{ id, full_name_np, full_name_en, status }`
**UserBrief** — `{ id, username, display_name }`

## 4. Enums

- `ChecklistTemplate.status`: `draft` | `active` | `inactive`
- `ChecklistTemplateItem.item_type`, `ChecklistItem.item_type`: `document` | `stage` | `task`
- `Checklist.status`, `Checklist.status_before_archive`: `draft` | `active` | `completed` | `archived`
- `Checklist.origin`: `auto` | `manual`
- `ChecklistItem.status`: `pending` | `completed` | `waived` | `blocked` | `not_applicable`

## 5. Dependency order

- `ChecklistTemplate` needs a `Country` (external module — `institutions`) whenever it is a default
- `ChecklistTemplateItem` needs a `ChecklistTemplate`
- `Checklist` needs an `ApplicantJourney` (external module — `applicant_journeys`), and a `ChecklistTemplate` unless blank
- `Checklist` is created automatically when a journey's `target_country_ref` is set to a country whose default template is active
- `ChecklistItem` needs a `Checklist`
- `ChecklistItem.evidence_file` needs an `UploadedFile` (external module — `uploaded_files`) owned by the same journey or applicant

**Start here:** `ChecklistTemplate`

## 6. Endpoints

### Checklist Templates — `/api/v1/checklists/templates/`

**Use it when:** an Admin records what a destination country requires, or staff read a country's list before applying it.
**Methods:**
- `GET /api/v1/checklists/templates/` — list
- `POST /api/v1/checklists/templates/` — author, **Admin only**
- `GET /api/v1/checklists/templates/<template_id>/` — one template with its requirements
- `PATCH /api/v1/checklists/templates/<template_id>/` — correct one, **Admin only**

**Send (create/update):**
- create: `key` (required, unique, ASCII), `label` (required), `description`, `country`, `is_default`, `status`, `status_note`, `display_order`, `notes`
- update: any create field except `key`, which is immutable

**Returns:** `ChecklistTemplate` | list[`ChecklistTemplate`]

**Notes:**
- omitting `status` on create yields a `draft`, which is not inheritable
- at most one `active` + `is_default` template per country, enforced by a database constraint
- editing a template never touches checklists already inherited from it
- retiring the default (`status: inactive`) frees the country's slot

**Errors:**
- `CHECKLISTS_ACTOR_FORBIDDEN` (403)
- `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS` (409)
- `CHECKLISTS_DEFAULT_REQUIRES_COUNTRY` (400)
- `CHECKLISTS_COUNTRY_NOT_FOUND` (400)
- `CHECKLISTS_TEMPLATE_NOT_FOUND` (404)

### Template Requirements — `/api/v1/checklists/templates/<template_id>/items/`

**Use it when:** an Admin adds or retires one requirement on a country's list.
**Methods:**
- `POST /api/v1/checklists/templates/<template_id>/items/` — add, **Admin only**
- `PATCH /api/v1/checklists/templates/<template_id>/items/<item_id>/` — edit or retire, **Admin only**

**Send (create/update):**
- create: `label` (required), `description`, `item_type`, `is_required`, `display_order`, `default_due_offset_days`
- update: any create field, plus `is_active`

**Returns:** `ChecklistTemplateItem`

**Notes:**
- there is no delete — retirement is `is_active: false`
- affects who inherits the requirement next, never anyone already holding a copy

**Errors:**
- `CHECKLISTS_ACTOR_FORBIDDEN` (403)
- `CHECKLISTS_TEMPLATE_NOT_FOUND` (404)
- `CHECKLISTS_TEMPLATE_ITEM_NOT_FOUND` (404)

### Checklists — `/api/v1/checklists/`

**Use it when:** rendering an applicant's outstanding work, running the worklist, or applying a list by hand.
**Methods:**
- `GET /api/v1/checklists/` — list with progress
- `POST /api/v1/checklists/` — apply a template by hand, or start a blank list
- `GET /api/v1/checklists/<checklist_id>/` — one checklist with its items
- `PATCH /api/v1/checklists/<checklist_id>/` — correct title, owner, due date, notes

**Send (create/update):**
- create with a template: `journey` (required), `template` (required); everything else is ignored
- create blank: `journey` (required), `title` (required in this shape), `description`, `assigned_to`, `due_at`, `notes`
- update: `title`, `description`, `assigned_to`, `due_at`, `notes`

**Returns:** `Checklist` | list[`Checklist`]
- `GET /` returns the list shape (no `items`, no lifecycle stamps)
- `POST /`, `GET /<id>/`, `PATCH /<id>/` return the full retrieve shape

**Notes:**
- **the usual way a checklist appears is not this endpoint** — setting a journey's `target_country_ref` inherits the country's default list automatically, with `origin: "auto"`
- inheritance is idempotent and re-fires on every journey save, so re-`PATCH`ing an unchanged country is a supported retry
- a template-applied checklist is created `active`; a blank one `draft`
- `status` is not accepted by `PATCH`
- archived checklists are included by default; filter with `?status=active`
- `?applicant=` traverses the journey, so a client never needs the journey id

**Errors:**
- `CHECKLISTS_JOURNEY_NOT_FOUND` (400)
- `CHECKLISTS_TEMPLATE_NOT_FOUND` (400)
- `CHECKLISTS_TEMPLATE_NOT_ACTIVE` (400)
- `CHECKLISTS_TEMPLATE_HAS_NO_ITEMS` (400)
- `CHECKLISTS_TEMPLATE_ALREADY_APPLIED` (409)
- `CHECKLISTS_CHECKLIST_NOT_FOUND` (404)
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409)

### Checklist lifecycle — `/api/v1/checklists/<checklist_id>/{activate,complete,reopen,archive,restore}/`

**Use it when:** moving a checklist through its states.
**Methods:**
- `POST /api/v1/checklists/<checklist_id>/activate/` — `draft` → `active`
- `POST /api/v1/checklists/<checklist_id>/complete/` — `active` → `completed`
- `POST /api/v1/checklists/<checklist_id>/reopen/` — `completed` → `active`
- `POST /api/v1/checklists/<checklist_id>/archive/` — any live state → `archived`
- `POST /api/v1/checklists/<checklist_id>/restore/` — `archived` → `status_before_archive`

**Send:**
- `archive`: `reason` (required, non-blank)
- `reopen`: `reason` (optional)
- `activate`, `complete`, `restore`: empty body

**Returns:** `Checklist` (retrieve shape, with fresh `progress`)

**Notes:**
- completion is derived — refused unless every required item is `completed`, `waived`, or `not_applicable`; a `blocked` required item refuses
- `reopen` clears `completed_at` and `completed_by`; the completion survives in the audit log
- `restore` returns the checklist to exactly the status it was archived in — **restore is not a reopen**
- archiving frees the journey to inherit or be applied a fresh copy of the same template

**Errors:**
- `CHECKLISTS_REQUIRED_ITEMS_PENDING` (409) — `details.items` names every outstanding required item
- `CHECKLISTS_INVALID_TRANSITION` (409)
- `CHECKLISTS_ARCHIVE_REASON_REQUIRED` (400)
- `CHECKLISTS_CHECKLIST_NOT_ARCHIVED` (409)
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409)
- `CHECKLISTS_CHECKLIST_NOT_FOUND` (404)

### Checklist Items — `/api/v1/checklists/<checklist_id>/items/`

**Use it when:** adding a requirement this one applicant needs, or correcting an item's descriptive fields.
**Methods:**
- `POST /api/v1/checklists/<checklist_id>/items/` — add
- `PATCH /api/v1/checklists/<checklist_id>/items/<item_id>/` — edit

**Send (create/update):**
- create: `label` (required), `description`, `item_type`, `is_required`, `display_order`, `assigned_to`, `due_at`
- update: the same fields plus `evidence_note`, minus `label` being required

**Returns:** `ChecklistItem`

**Notes:**
- an item added here never travels back to the template
- `status` is not accepted here
- item routes are scoped to their checklist — a stray item id returns 404
- permitted only while the checklist is `draft` or `active`

**Errors:**
- `CHECKLISTS_CHECKLIST_NOT_FOUND` (404)
- `CHECKLISTS_ITEM_NOT_FOUND` (404)
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409)
- `CHECKLISTS_INVALID_TRANSITION` (409)

### Item status — `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/`

**Use it when:** recording that a requirement was met, waived, blocked, or does not apply. The daily act.
**Methods:**
- `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/`

**Send:**
- `status` (required)
- `status_note` (required when `waived` or `blocked`)
- `evidence_file` (UUID of a file owned by this journey or applicant)
- `evidence_note`
- `clear_evidence` (bool)

**Returns:** `ChecklistItem`

**Notes:**
- setting `completed` stamps `completed_at` and `completed_by`; any other status clears both
- send `{"status": "pending", "evidence_file": "<id>"}` to file a scan without declaring the item done
- the response carries no `progress` — re-read the checklist to refresh a progress bar
- a `document`- or snapshot-owned file can never be cited, because such a file is owned by neither a journey nor an applicant

**Errors:**
- `CHECKLISTS_STATUS_NOTE_REQUIRED` (400)
- `CHECKLISTS_EVIDENCE_NOT_ALLOWED` (400) — another applicant's file, or no such file. One code for both, so a caller cannot probe which ids exist
- `CHECKLISTS_ITEM_NOT_FOUND` (404)
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409)
- `CHECKLISTS_INVALID_TRANSITION` (409)

### Journeys awaiting a checklist — `GET /api/v1/checklists/?journey_missing_checklist=true`

**Use it when:** finding applicants whose destination has no authored requirement list.
**Methods:**
- `GET /api/v1/checklists/?journey_missing_checklist=true`

**Send (create/update):** none

**Returns:** list[`JourneyAwaitingChecklist`] — journeys, not checklists

**Notes:**
- every other filter is ignored when the flag is set; `page` and `page_size` still apply
- automatic inheritance is silent when a country has no default template, and this is what makes that silence visible
- the remedy is to author the template, then run the backend command `apply_country_checklists` — no endpoint exposes it

**Errors:** none

## 7. Flows

**Author a country's list and let an applicant inherit it**
1. `GET /api/v1/catalogue/countries/` → capture `country_id`
2. `POST /api/v1/checklists/templates/` with `{ key, label, country: country_id, is_default: true, status: "active" }` → capture `template_id`
   - `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS` (409) → read `details.existing_template_id` and edit that template instead
   - `CHECKLISTS_ACTOR_FORBIDDEN` (403) → the caller is a Lead Manager; only an Admin may author
3. `POST /api/v1/checklists/templates/<template_id>/items/` once per requirement
4. `PATCH /api/v1/journeys/<journey_id>/` with `{ "target_country_ref": country_id }`
5. `GET /api/v1/checklists/?applicant=<applicant_id>` → the checklist is already there, `origin: "auto"`
   - empty → either the journey has no `target_country_ref`, or the template is not active and default. Confirm with `?journey_missing_checklist=true`

**Work a list to completion**
1. `GET /api/v1/checklists/?applicant=<applicant_id>` → capture `checklist_id`
2. `GET /api/v1/checklists/<checklist_id>/` → read `items[]` and `progress`
3. `POST /api/v1/files/` with `applicant` as the owner → capture `file_id`
4. `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` with `{ "status": "completed", "evidence_file": file_id }`
   - `CHECKLISTS_EVIDENCE_NOT_ALLOWED` (400) → the file belongs to a different applicant; re-upload against this one
5. repeat until `progress.required_resolved == progress.required_total`
6. `POST /api/v1/checklists/<checklist_id>/complete/`
   - `CHECKLISTS_REQUIRED_ITEMS_PENDING` (409) → `details.items` names what is left; a `blocked` item counts as outstanding

**A requirement that cannot be met**
1. `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` with `{ "status": "blocked", "status_note": "..." }`
   - `CHECKLISTS_STATUS_NOTE_REQUIRED` (400) → the note is mandatory for `blocked` and `waived`
2. later, `{ "status": "completed" }` or `{ "status": "waived", "status_note": "..." }`
3. `POST /api/v1/checklists/<checklist_id>/complete/` now succeeds

**Start an applicant's list over**
1. `POST /api/v1/checklists/<checklist_id>/archive/` with `{ "reason": "..." }`
2. `POST /api/v1/checklists/` with `{ journey, template }` → a fresh copy reflecting the template as it stands now
   - `CHECKLISTS_TEMPLATE_ALREADY_APPLIED` (409) → step 1 was skipped
   - alternatively re-save the journey; the archived checklist no longer blocks inheritance

**Find destinations nobody has set up**
1. `GET /api/v1/checklists/?journey_missing_checklist=true` → journeys whose country has no template
2. for each distinct country, run the authoring flow
3. re-`PATCH` each journey with its existing `target_country_ref` to cover applicants already waiting

## 8. Gaps

- The caller's authority type is not exposed by any payload in this module, so a client cannot decide whether to render the Admin-only template screens without asking `authenticate` first.
- `evidence_file` is a bare id with no filename, size, or type; showing it takes one extra call per item to `/api/v1/files/<id>/`, and there is no bulk file fetch.
- No endpoint runs the backfill. After authoring a template, journeys that already name that country are covered only by re-`PATCH`ing each one, or by an operator running `apply_country_checklists`.
- Inheritance is asynchronous with no completion signal and no documented latency bound. "Not yet" and "that country has no template" are distinguishable only by also querying `?journey_missing_checklist=true`.
- One operation returns two resource types: `checklists.checklist.list` returns `JourneyAwaitingChecklist` under the flag, where `id` is a journey id.
- `CHECKLISTS_TEMPLATE_NOT_FOUND` is 404 when the template is the addressed resource and 400 when it is a body field. Branch on status and code together.
- A `ChecklistItem` cannot be removed or retired. `not_applicable` is the nearest escape, and it counts as resolved.
- No bulk item-status endpoint; a twelve-item checklist is twelve requests.
- No concurrency control — no `ETag`, no `If-Match`, no `updated_at` precondition on any write.
- No ordering parameter on either list.
- `Checklist.title`, `ChecklistTemplate.label`, and every `description`/`status_note`/`notes` are single strings, unlike the `_np`/`_en` pairs on the nested country and applicant briefs.
- `assigned_to` accepts any active user id including a Superadmin, who is then refused on every route in this module. No user-list endpoint exists here to source a correct picker.
- `due_at` write format is unpinned beyond ISO 8601 — date-only and omitted-timezone behaviour is untested by the contract. The `_bs` objects are read-only.

---

## Applicant Journeys

## 1. Module

- **Name:** Applicant Journeys
- **Base path:** `/api/v1/journeys/`
- **Auth:** JWT bearer. Admin and Lead Manager have identical rights; Superadmin is denied.

## 2. Conventions

Unchanged this session. `{ success, message, data, meta }` envelope; UUID ids; ISO 8601 UTC times; pagination on the list endpoint with `?page=`/`?page_size=`.

## 3. Models

**Journey** — one field added, everything else unchanged:
- `target_country_ref?:CountryBrief` — the catalogue destination. Written as a bare UUID, read back as an object, the same asymmetry `applicant` already had. `null` on any journey whose destination was never resolved to a catalogue country.
- The free-text `target_country` is **unchanged and still present**. It remains the display fallback when the reference is null.

**CountryBrief** — `{ id, code, name_en, name_np }` (new to this module's response set)

## 4. Enums

No enum added or changed. `target_country_ref` is a reference, not a choice field.

## 5. Dependency order

- `Journey` needs an `Applicant` (external module — `applicants`)
- `Journey.target_country_ref` needs a `Country` (external module — `institutions`) — new this session

**Start here:** unchanged — an applicant must exist before a journey.

## 6. Endpoints

No endpoint was added, changed, or retired this session. One existing block gained a field and a side effect.

### Journeys — `/api/v1/journeys/`

**Use it when:** the operational worklist, the journeys panel on an applicant's file, the new-journey form, and the journey detail page.
**Methods:**
- `GET /api/v1/journeys/` — list
- `POST /api/v1/journeys/` — record a new objective
- `GET /api/v1/journeys/<journey_id>/` — retrieve one
- `PATCH /api/v1/journeys/<journey_id>/` — correct one

**Send (create/update):**
- create: unchanged, plus `target_country_ref` (catalogue country id, optional, nullable)
- update: the same, minus `applicant`

**Returns:** `Journey`

**Notes:**
- `target_country_ref` is additive — every existing field keeps its shape, so this is non-breaking
- **setting it creates the applicant's checklist** in the `checklists` module, after this request commits and with nothing about it in this response
- a read issued immediately afterwards may not see the checklist yet; retry
- nothing happens if the country has no authored checklist template, which is not an error
- re-saving never produces a second checklist
- new list filter `target_country_ref` (exact id), beside the existing partial-match `target_country`

**Errors:**
- `JOURNEYS_COUNTRY_NOT_FOUND` (400) — `target_country_ref` names no catalogue country. Identical on create and update

## 7. Flows

**Give an applicant their destination and their checklist**
1. `GET /api/v1/catalogue/countries/` → capture `country_id`
2. `PATCH /api/v1/journeys/<journey_id>/` with `{ "target_country_ref": country_id }`
   - `JOURNEYS_COUNTRY_NOT_FOUND` (400) → the id is not in the catalogue
3. `GET /api/v1/checklists/?applicant=<applicant_id>` → the inherited checklist, if that country has a template

## 8. Gaps

- Institution and program on a journey are **still** free text with no catalogue reference. Only the country was migrated.
- Nothing reconciles `target_country` and `target_country_ref`. A journey may carry a typed name that disagrees with its reference, and no endpoint reports the mismatch.
- The checklist side effect is invisible from this module: no response field, no audit event here, and no way to ask this app whether inheritance succeeded.

---

## Core

## 1. Module

- **Name:** Core — project settings, root URL configuration, and the project-level integration contract
- **Base path:** n/a
- **Auth:** n/a

## 2. Conventions

One global clarification added: **`error.details` must not be typed as a map of field name to an array of strings.** That is the common case, not a guarantee; an app may put a richer value under a key when a list of strings could not carry what a client needs to act on.

## 3. Models

No model added or changed. `core/models.py` holds abstract base models only.

## 4. Enums

No enum added or changed.

## 5. Dependency order

`checklists` added to `INSTALLED_APPS` and mounted at `/api/v1/checklists/`.

## 6. Endpoints

No endpoint added, changed, or retired in `core` this session.

## 7. Flows

No flow owned by `core`.

## 8. Gaps

- The project-level `INTEGRATION.md` §7 previously stated that `applicant_journeys` "has no FK into the catalogue". That is no longer true and has been corrected in place with an explicit retraction. A consumer holding an older copy will build a journey editor that writes only the free-text country and silently receives no checklist.
- `DISABLE_SIGNALS` is now a real settings flag (default `False`). It switches off every app's signal side effects for a process; today only `checklists` reads it.
