# Integration — Checklists

**Owner app:** `checklists`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial integration contract for the 18 endpoints |
| 1.0.1 | 2026-07-24 | AI (Claude Opus 4.8) | Corrections from the §19.5 consumer-contract review, which read only this file and the project-level one. Added: success status codes, the `error.details` deviation, filter semantics, how to fetch a cited evidence file, the create response shape, inheritance idempotency, `status_before_archive`, pagination on the safety-net view, and how to attach evidence without completing an item. Replaced the abridged list example, which showed two fields and read as the whole row. §9 rewritten and ranked — the review could not determine the caller's authority, the backfill path, or an item's removability from this file alone |

---

## 1. Module

- **Name:** Checklists — the destination-country requirement lists an Admin authors, and each applicant's own copy of one. An applicant whose journey names a catalogue country **automatically receives that country's list**; staff then track it item by item.
- **Base path:** `/api/v1/checklists/`
- **Auth:** Every endpoint requires a JWT bearer token. Admin and Lead Manager may reach every endpoint **except** the four template-authoring routes (`POST /templates/`, `PATCH /templates/<id>/`, `POST /templates/<id>/items/`, `PATCH /templates/<id>/items/<id>/`), which are Admin-only. Superadmin is refused on every route.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `applicant_journeys` | FK + service call + **signal** | A checklist attaches to a journey, and the journey's `target_country_ref` is what triggers inheritance. This module listens on journey saves | No checklist can be created (every create returns `CHECKLISTS_JOURNEY_NOT_FOUND`), and **automatic inheritance never fires** — the module's headline behaviour disappears |
| `institutions` | FK + service call | A template is scoped to a catalogue country, and the checklist copies that country | Templates cannot be scoped, so no template can be a default, so nothing is ever inherited. `POST /templates/` returns `CHECKLISTS_COUNTRY_NOT_FOUND` |
| `uploaded_files` | FK + service call | An item may cite a stored file as evidence that a requirement was met | `evidence_file` cannot be set; every attempt returns `CHECKLISTS_EVIDENCE_NOT_ALLOWED`. Items can still be completed with a note alone |
| `authenticate` | framework + FK | Issues the bearer token; supplies the assignee, the completer, and the archiver | Every endpoint returns 401; `assigned_to` cannot be set |
| `audit` | service call | Every write appends one immutable event | Writes still succeed, but nothing records who changed what |
| `core` | framework | Supplies the response envelope, pagination, and the exception handler | Responses lose the `{ success, message, data, meta }` envelope; errors return raw DRF bodies |

**Note for consumers:** the dependency on `applicant_journeys` runs **one way and is invisible from that side**. Nothing in the journeys app knows checklists exist. A client that sets a journey's country will not see a checklist mentioned in the journey response — it must ask this module.

## 3. Conventions

- **Response:** the project-standard envelope — `{ success: true, message, data, meta }`. See `core/docs/INTEGRATION.md` §3.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when the JWT is missing or invalid; `CHECKLISTS_ACTOR_FORBIDDEN` (403) when the authority type may not perform the action. **Both apply to all 18 endpoints** and are not repeated in each §7 `Errors` list — a Superadmin gets 403 on every route, and a Lead Manager gets 403 on the four template-authoring routes.
- **Success statuses:** `201` for every create (`POST /templates/`, `POST /templates/<id>/items/`, `POST /`, `POST /<id>/items/`); `200` for every read, `PATCH`, and lifecycle action. No endpoint returns `204` — every response carries a body.
- **`error.details` is not always field-name-to-strings.** Two codes here carry a richer value, deliberately: `CHECKLISTS_REQUIRED_ITEMS_PENDING` puts an array of `{ id, label, status }` objects under `details.items`, and `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS` puts a bare id string under `details.existing_template_id`. Type `details` as an open map and narrow by code.
- **Pagination:** every list endpoint. `?page=` and `?page_size=` (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous` as absolute URLs or `null`. `data` is a **bare array** of resources — it is not nested under `results`.
- **IDs:** UUID strings everywhere, including in URL segments.
- **Times:** ISO 8601, UTC, `Z`-suffixed. Every user-facing date field additionally carries a `_bs` sibling holding its Bikram Sambat rendering (`due_at` → `due_at_bs`, `completed_at` → `completed_at_bs`), or `null`.
- **List/search/filter/order params:** `GET /templates/` accepts `country`, `status`, `is_default`, `search`. `GET /` accepts `applicant`, `journey`, `status`, `origin`, `assigned_to`, `country`, `template`, `overdue`, `journey_missing_checklist`. No ordering param exists on either — templates sort by `display_order` then `label`; checklists sort newest first. A filter value that is not a valid UUID or a valid enum member returns `400` with the global `VALIDATION_ERROR` code and the offending parameter named in `details` — never an empty page.

Filter semantics on `GET /`, since several are not self-evident: `applicant` matches through the checklist's journey (exact id); `journey`, `assigned_to`, `template`, and `country` are exact id matches; `country` matches the **copied** country on the checklist, so a blank hand-built checklist (which has none) never matches any value; `origin` distinguishes inherited from staff-created; `overdue=true` matches only `draft` and `active` checklists past their `due_at`. Filters combine with AND. `journey_missing_checklist=true` **overrides all of them** and changes the returned resource — see the last block of §7.

Worked success envelope, `GET /api/v1/checklists/?applicant=<id>`:

```json
{
  "success": true,
  "message": "Checklists retrieved.",
  "data": [
    {
      "id": "7c3e9a11-4b2d-4f0e-8a55-1d9c7b3e2f10",
      "journey": "5e2b8a71-3c4d-4e5f-8a91-2b3c4d5e6f70",
      "applicant": { "id": "8a1c2d3e-4f50-4617-a283-94a5b6c7d8e9", "full_name": "Ram Bahadur", "status": "active" },
      "source_template": "9b1f3c22-8d4a-4e1b-9c77-2f0a6b5d1e33",
      "country": { "id": "3a7c1d90-5b2e-4f81-9a03-6c4d8e2b7f15", "code": "au", "name": "Australia" },
      "title": "Australia — Student Visa",
      "description": "",
      "origin": "auto",
      "status": "active",
      "assigned_to": null,
      "due_at": null,
      "due_at_bs": null,
      "progress": { "total": 3, "resolved": 1, "required_total": 2, "required_resolved": 1, "blocked": 0, "document_total": 2, "document_resolved": 1 },
      "created_at": "2026-07-24T09:20:03.771Z",
      "updated_at": "2026-07-24T10:02:11.004Z"
    }
  ],
  "meta": { "count": 1, "page": 1, "page_size": 20, "next": null, "previous": null }
}
```

**`progress` is on every list row**, not only the retrieve shape — it is the whole reason a worklist can render progress bars without a request per checklist. What the list row omits is `items`, `notes`, and the lifecycle stamps.

Worked error envelope, `POST /api/v1/checklists/<id>/complete/` with work outstanding:

```json
{
  "success": false,
  "error": {
    "code": "CHECKLISTS_REQUIRED_ITEMS_PENDING",
    "message": "2 required item(s) are still outstanding.",
    "details": {
      "items": [
        { "id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d", "label": "Passport bio page scan", "status": "pending" },
        { "id": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819", "label": "Academic transcripts", "status": "blocked" }
      ]
    }
  },
  "meta": {}
}
```

## 4. Models

**ChecklistTemplate** — `{ id, key, label, description, country?:CountryBrief, is_default, is_inheritable, status:[enum], status_note, display_order, notes, items:[ChecklistTemplateItem], created_by:UserBrief, created_at, updated_at }`
- `is_inheritable` is derived: `true` when the template is `active`, `is_default`, and has a country. It is the single field that answers "will an applicant reaching this country get this list".
- `items` includes **retired** definitions (`is_active: false`), active ones sorted first.

**ChecklistTemplateItem** — `{ id, label, description, item_type:[enum], is_required, display_order, default_due_offset_days?:int, is_active, created_at, updated_at }`

**Checklist** — `{ id, journey, applicant:ApplicantBrief, source_template?, country?:CountryBrief, title, description, origin:[enum], status:[enum], assigned_to?:UserBrief, due_at?, due_at_bs?:json, progress:ChecklistProgress, created_at, updated_at }`
- Retrieve-only extras on `GET /<id>/`: `notes`, `items:[ChecklistItem]`, `activated_at?`, `completed_at?`, `completed_at_bs?`, `completed_by?:UserBrief`, `archive_reason`, `archived_at?`, `archived_by?:UserBrief`, `status_before_archive:[enum]`.
- `status_before_archive` is empty except while `status` is `archived`, where it holds the status the checklist will return to on restore.
- `journey` and `source_template` are bare UUID strings, not nested objects. `applicant` and `country` are nested.
- `created_by` is **absent from the response shape**. An inherited checklist has no author, and the field would be null on the majority of rows.

**ChecklistProgress** — `{ total, resolved, required_total, required_resolved, blocked, document_total, document_resolved }`
- All integers. `resolved` counts items in `completed`, `waived`, or `not_applicable` — **`blocked` is not resolved**. `required_resolved == required_total` is the exact condition under which `POST /<id>/complete/` will succeed.

**ChecklistItem** — `{ id, checklist, source_template_item?, label, description, item_type:[enum], is_required, display_order, status:[enum], status_note, is_resolved, assigned_to?:UserBrief, due_at?, due_at_bs?:json, evidence_file?, evidence_note, completed_at?, completed_at_bs?:json, completed_by?:UserBrief, created_at, updated_at }`
- `checklist`, `source_template_item`, and `evidence_file` are bare UUID strings.
- **`evidence_file` carries no filename, size, or type.** To show or download the cited file, call the `uploaded_files` module with that id: `GET /api/v1/files/<evidence_file>/` for its metadata (original filename, category, size, verification status) and `GET /api/v1/files/<evidence_file>/download/` for the bytes, both with the same bearer token. There is no nested file brief here and no URL — see `uploaded_files/docs/INTEGRATION.md`.
- `ChecklistItem` has **no `is_active` and no delete.** An item that turns out not to apply is set to `not_applicable`, which counts as resolved. There is no way to remove one — see §9.

**JourneyAwaitingChecklist** — `{ id, applicant:ApplicantBrief, target_country_ref?:CountryBrief, stage, created_at }`
- Returned **only** by `GET /?journey_missing_checklist=true`. `id` is the **journey's** id, not a checklist's.

**CountryBrief** — `{ id, code, name }`
**ApplicantBrief** — `{ id, full_name, status }`
**UserBrief** — `{ id, username, display_name }`

### Worked examples

Each payload below is the value of `data` inside the standard envelope from §3 — they are shown unwrapped so the resource shape is unambiguous.

`GET /api/v1/checklists/templates/<id>/` → **ChecklistTemplate**:

```json
{
  "id": "9b1f3c22-8d4a-4e1b-9c77-2f0a6b5d1e33",
  "key": "australia-student",
  "label": "Australia — Student Visa",
  "description": "Documents and stages required for an Australian student visa application.",
  "country": { "id": "3a7c1d90-5b2e-4f81-9a03-6c4d8e2b7f15", "code": "au", "name": "Australia" },
  "is_default": true,
  "is_inheritable": true,
  "status": "active",
  "status_note": "",
  "display_order": 0,
  "notes": "",
  "items": [
    {
      "id": "4d5e6f70-8192-4a3b-9c4d-5e6f70819243",
      "label": "Passport bio page scan",
      "description": "",
      "item_type": "document",
      "is_required": true,
      "display_order": 1,
      "default_due_offset_days": 14,
      "is_active": true,
      "created_at": "2026-07-24T09:12:44.183Z",
      "updated_at": "2026-07-24T09:12:44.183Z"
    }
  ],
  "created_by": { "id": "1f2e3d4c-5b6a-4798-8071-6253445362f1", "username": "adminuser", "display_name": "Adminuser" },
  "created_at": "2026-07-24T09:12:44.183Z",
  "updated_at": "2026-07-24T09:12:44.183Z"
}
```

`GET /api/v1/checklists/<id>/` → **Checklist** (retrieve shape, one item shown):

```json
{
  "id": "7c3e9a11-4b2d-4f0e-8a55-1d9c7b3e2f10",
  "journey": "5e2b8a71-3c4d-4e5f-8a91-2b3c4d5e6f70",
  "applicant": { "id": "8a1c2d3e-4f50-4617-a283-94a5b6c7d8e9", "full_name": "Ram Bahadur", "status": "active" },
  "source_template": "9b1f3c22-8d4a-4e1b-9c77-2f0a6b5d1e33",
  "country": { "id": "3a7c1d90-5b2e-4f81-9a03-6c4d8e2b7f15", "code": "au", "name": "Australia" },
  "title": "Australia — Student Visa",
  "description": "",
  "origin": "auto",
  "status": "active",
  "assigned_to": null,
  "due_at": null,
  "due_at_bs": null,
  "progress": { "total": 3, "resolved": 1, "required_total": 2, "required_resolved": 1, "blocked": 0, "document_total": 2, "document_resolved": 1 },
  "notes": "",
  "items": [
    {
      "id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
      "checklist": "7c3e9a11-4b2d-4f0e-8a55-1d9c7b3e2f10",
      "source_template_item": "4d5e6f70-8192-4a3b-9c4d-5e6f70819243",
      "label": "Passport bio page scan",
      "description": "",
      "item_type": "document",
      "is_required": true,
      "display_order": 1,
      "status": "completed",
      "status_note": "",
      "is_resolved": true,
      "assigned_to": null,
      "due_at": "2026-08-07T09:20:03.771Z",
      "due_at_bs": { "year": 2083, "month": 4, "day": 23, "month_name": "Shrawan", "display": "2083 Shrawan 23" },
      "evidence_file": "6f708192-a3b4-45c6-8d7e-8f9021324354",
      "evidence_note": "Scan received 2026-07-24",
      "completed_at": "2026-07-24T10:02:11.004Z",
      "completed_at_bs": { "year": 2083, "month": 4, "day": 9, "month_name": "Shrawan", "display": "2083 Shrawan 9" },
      "completed_by": { "id": "2e3d4c5b-6a79-4880-9162-53445362f1a2", "username": "leadmgr", "display_name": "Leadmgr" },
      "created_at": "2026-07-24T09:20:03.771Z",
      "updated_at": "2026-07-24T10:02:11.004Z"
    }
  ],
  "activated_at": "2026-07-24T09:20:03.771Z",
  "completed_at": null,
  "completed_at_bs": null,
  "completed_by": null,
  "archive_reason": "",
  "archived_at": null,
  "archived_by": null,
  "created_at": "2026-07-24T09:20:03.771Z",
  "updated_at": "2026-07-24T10:02:11.004Z"
}
```

## 5. Enums

- `ChecklistTemplate.status`: `draft` | `active` | `inactive`
- `ChecklistTemplateItem.item_type`, `ChecklistItem.item_type`: `document` | `stage` | `task`
- `Checklist.status`: `draft` | `active` | `completed` | `archived`
- `Checklist.origin`: `auto` | `manual`
- `ChecklistItem.status`: `pending` | `completed` | `waived` | `blocked` | `not_applicable`

## 6. Dependency order

- `ChecklistTemplate` needs a `Country` **(institutions module — `GET /api/v1/catalogue/countries/`)** whenever it is a default
- `ChecklistTemplateItem` needs a `ChecklistTemplate`
- `Checklist` needs an `ApplicantJourney` **(applicant_journeys module)**, and a `ChecklistTemplate` unless it is blank
- `Checklist` is created **automatically** when a journey's `target_country_ref` is set to a country whose default template is active — see §8, flow 1
- `ChecklistItem` needs a `Checklist`
- `ChecklistItem.evidence_file` needs an `UploadedFile` **(uploaded_files module)** owned by the same journey or applicant

**Start here:** `ChecklistTemplate` — nothing can be inherited until a country's list exists.

## 7. Endpoints

### Checklist Templates — `/api/v1/checklists/templates/`

**Use it when:** an Admin sets up what a destination country requires, or any staff member needs to see what a country's list contains before it is applied.
**Methods:**
- `GET /api/v1/checklists/templates/` — list, paginated (permission: `checklists.template.list`, risk: low)
- `POST /api/v1/checklists/templates/` — author a country's list (permission: `checklists.template.create`, risk: high) — **Admin only**
- `GET /api/v1/checklists/templates/<template_id>/` — one template with its requirements (permission: `checklists.template.read`, risk: low)
- `PATCH /api/v1/checklists/templates/<template_id>/` — correct one (permission: `checklists.template.update`, risk: high) — **Admin only**

**Send (create):**
- `key` (required, unique, ASCII `^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$`), `label` (required), `description`, `country` (UUID), `is_default` (bool), `status`, `status_note`, `display_order`, `notes`

**Send (update):**
- any create field **except `key`**, which is immutable

**Returns:** `ChecklistTemplate` | list[`ChecklistTemplate`]

**Requires state:**
- for a default template, the `country` must already exist in the institutions catalogue
- that country must not already have an `active` template with `is_default: true`

**Side effects:**
- none on create or update — **editing a template never changes any checklist already inherited from it**. Instantiation is a snapshot taken at the moment a checklist is created
- one audit event per write, in the `audit` module

**Notes:**
- omitting `status` on create yields a `draft`, which is **not** inheritable. Send `"status": "active"` to make the template live
- a template retired with `"status": "inactive"` frees its country's default slot for a replacement
- filters: `?country=<uuid>`, `?status=`, `?is_default=true|false`, `?search=` (matches `label` or `key`)

**Errors:**
- `CHECKLISTS_ACTOR_FORBIDDEN` (403) — Lead Manager attempting to author, or any Superadmin
- `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS` (409) — this country already has an active default. `details.existing_template_id` names it
- `CHECKLISTS_DEFAULT_REQUIRES_COUNTRY` (400) — `is_default: true` with no `country`
- `CHECKLISTS_COUNTRY_NOT_FOUND` (400) — `country` names no catalogue row
- `CHECKLISTS_TEMPLATE_NOT_FOUND` (404)
- `VALIDATION_ERROR` (400) — duplicate or malformed `key`

### Template Requirements — `/api/v1/checklists/templates/<template_id>/items/`

**Use it when:** an Admin adds or retires one requirement on a country's list.
**Methods:**
- `POST /api/v1/checklists/templates/<template_id>/items/` — add (permission: `checklists.template_item.create`, risk: high) — **Admin only**
- `PATCH /api/v1/checklists/templates/<template_id>/items/<item_id>/` — edit or retire (permission: `checklists.template_item.update`, risk: high) — **Admin only**

**Send (create):**
- `label` (required), `description`, `item_type`, `is_required` (default `true`), `display_order`, `default_due_offset_days` (int, days after instantiation)

**Send (update):**
- any create field, plus `is_active` (send `false` to retire)

**Returns:** `ChecklistTemplateItem`

**Requires state:**
- the template must exist. It need not be active — requirements are normally added while it is still a draft

**Side effects:**
- affects who inherits the requirement **next**. Applicants already holding a copy of this template are untouched
- one audit event

**Notes:**
- **there is no delete.** Retirement is `is_active: false`, because existing checklist items hold a protected reference to the definition they were copied from
- a retired definition is still returned by `GET /templates/<id>/`, sorted after the active ones

**Errors:**
- `CHECKLISTS_ACTOR_FORBIDDEN` (403)
- `CHECKLISTS_TEMPLATE_NOT_FOUND` (404)
- `CHECKLISTS_TEMPLATE_ITEM_NOT_FOUND` (404)

### Checklists — `/api/v1/checklists/`

**Use it when:** rendering an applicant's outstanding work, running the team worklist, or applying a list by hand.
**Methods:**
- `GET /api/v1/checklists/` — list with progress, paginated (permission: `checklists.checklist.list`, risk: medium)
- `POST /api/v1/checklists/` — apply a template by hand, or start a blank list (permission: `checklists.checklist.create`, risk: medium)
- `GET /api/v1/checklists/<checklist_id>/` — one checklist with its items (permission: `checklists.checklist.read`, risk: medium)
- `PATCH /api/v1/checklists/<checklist_id>/` — correct title, owner, due date, notes (permission: `checklists.checklist.update`, risk: low)

**Send (create) — two shapes:**
- with a template: `journey` (required), `template` (required). Every other field is ignored; the template supplies title, description, country, and items
- blank: `journey` (required), `title` (**required in this shape**), `description`, `assigned_to`, `due_at`, `notes`

**Send (update):**
- `title`, `description`, `assigned_to`, `due_at`, `notes`

**Returns:** `Checklist` | list[`Checklist`] — `GET /` returns the list shape (no `items`, no lifecycle stamps); **`POST /`, `GET /<id>/`, and `PATCH /<id>/` all return the full retrieve shape**, so a create hands back every item it just copied and there is no follow-up read. `POST` is `201`; the rest are `200`

**Requires state:**
- the `journey` must exist
- an applied `template` must be `active` and hold at least one active requirement
- the journey must not already hold a non-archived checklist from that same template

**Side effects:**
- create copies every active requirement into real `ChecklistItem` rows, deriving each `due_at` from the template's `default_due_offset_days`
- one audit event

**Notes:**
- **the usual way a checklist appears is not this endpoint.** Setting a journey's `target_country_ref` (via `PATCH /api/v1/journeys/<journey_id>/`, cross-app: `applicant_journeys`) inherits that country's default list automatically, with `origin: "auto"`. This route is the manual override
- **Automatic inheritance is idempotent, and re-saving the journey is a supported retry.** It fires on **every** save of a journey that has a `target_country_ref` — creation, an update that sets the country, and an update that changes nothing at all — and each time it checks for an existing non-archived checklist from the same template before writing. There is no old-versus-new comparison, so a `PATCH` re-sending the country the journey already has **does** re-attempt inheritance, and produces a second checklist only if the first was archived. This is what makes the backfill in §8 flow 5 work
- a template-applied checklist is created `active`; a blank one is created `draft` and must be activated
- `?applicant=<uuid>` is how a client renders the applicant panel — it traverses the journey, so the caller never needs the journey id
- `?overdue=true` matches only `draft` and `active` checklists past their `due_at`; a completed one is never overdue
- **archived checklists are included by default.** Filter with `?status=active` to exclude them
- `status` is **not** accepted by `PATCH` — it moves only through the lifecycle actions below

**Errors:**
- `CHECKLISTS_JOURNEY_NOT_FOUND` (400)
- `CHECKLISTS_TEMPLATE_NOT_FOUND` (400)
- `CHECKLISTS_TEMPLATE_NOT_ACTIVE` (400) — a draft or retired template
- `CHECKLISTS_TEMPLATE_HAS_NO_ITEMS` (400) — the template defines no active requirements
- `CHECKLISTS_TEMPLATE_ALREADY_APPLIED` (409) — archive the existing one first
- `CHECKLISTS_CHECKLIST_NOT_FOUND` (404)
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409) — on `PATCH`; restore it first
- `VALIDATION_ERROR` (400) — no `template` and no `title`

### Checklist lifecycle — `/api/v1/checklists/<checklist_id>/{activate,complete,reopen,archive,restore}/`

**Use it when:** moving a checklist through its states. All five take `POST`.
**Methods:**
- `POST .../activate/` — `draft` → `active` (permission: `checklists.checklist.activate`, risk: low)
- `POST .../complete/` — `active` → `completed` (permission: `checklists.checklist.complete`, risk: high)
- `POST .../reopen/` — `completed` → `active` (permission: `checklists.checklist.reopen`, risk: medium)
- `POST .../archive/` — any live state → `archived` (permission: `checklists.checklist.archive`, risk: medium)
- `POST .../restore/` — `archived` → `active` or `draft` (permission: `checklists.checklist.restore`, risk: low)

**Send:**
- `archive`: `reason` (**required**, non-blank)
- `reopen`: `reason` (optional)
- `activate`, `complete`, `restore`: empty body

**Returns:** `Checklist` (retrieve shape, with fresh `progress`)

**Requires state:**
- `activate`: status is `draft`
- `complete`: status is `active`, **and every required item is `completed`, `waived`, or `not_applicable`**. A `blocked` required item refuses. `progress.required_resolved == progress.required_total` is the exact precondition
- `reopen`: status is `completed`
- `archive`: status is not already `archived`
- `restore`: status is `archived`. It returns to `status_before_archive`, so restoring may yield a `draft`, an `active`, or a `completed` checklist

**Side effects:**
- `complete` stamps `completed_at` and `completed_by`
- `reopen` **clears** `completed_at` and `completed_by`; the completion survives only in the audit log
- `archive` stamps `archive_reason`, `archived_at`, `archived_by`, and **frees the journey to inherit or be applied a fresh copy of the same template**
- `restore` clears the archive fields and returns the checklist to **exactly the status it held when archived** (`status_before_archive`). Archiving a `completed` checklist and restoring it gives back a `completed` one, with its `completed_at` and `completed_by` intact — restore is not a reopen
- one audit event each

**Notes:**
- an inherited or template-applied checklist arrives `active`, so `activate` only ever applies to a blank one
- an archived checklist refuses every edit until restored

**Errors:**
- `CHECKLISTS_REQUIRED_ITEMS_PENDING` (409) — `details.items` lists **every** outstanding required item with `id`, `label`, and `status`
- `CHECKLISTS_INVALID_TRANSITION` (409) — the action does not apply from the current status
- `CHECKLISTS_ARCHIVE_REASON_REQUIRED` (400) — blank or missing `reason`
- `CHECKLISTS_CHECKLIST_NOT_ARCHIVED` (409) — `restore` on a live checklist
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409) — a live action on an archived checklist
- `CHECKLISTS_CHECKLIST_NOT_FOUND` (404)

### Checklist Items — `/api/v1/checklists/<checklist_id>/items/`

**Use it when:** adding a requirement this one applicant needs, or correcting an item's descriptive fields.
**Methods:**
- `POST /api/v1/checklists/<checklist_id>/items/` — add (permission: `checklists.item.create`, risk: low)
- `PATCH /api/v1/checklists/<checklist_id>/items/<item_id>/` — edit (permission: `checklists.item.update`, risk: low)

**Send (create):**
- `label` (required), `description`, `item_type`, `is_required`, `display_order`, `assigned_to`, `due_at`

**Send (update):**
- `label`, `description`, `item_type`, `is_required`, `display_order`, `assigned_to`, `due_at`, `evidence_note`

**Returns:** `ChecklistItem`

**Requires state:**
- the checklist exists and its status is `draft` or `active`. A `completed` checklist must be reopened first; an `archived` one restored

**Side effects:**
- adding a required item **lowers** `progress.required_resolved / required_total`, so a checklist that was ready to complete may no longer be
- one audit event

**Notes:**
- an item added here **never travels back to the template**. The next applicant bound for the same country is unaffected
- `status` is **not** accepted by `PATCH` — use the status endpoint below
- item routes are scoped to their checklist: an item id belonging to a different checklist returns 404, not the other checklist's item

**Errors:**
- `CHECKLISTS_CHECKLIST_NOT_FOUND` (404)
- `CHECKLISTS_ITEM_NOT_FOUND` (404)
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409)
- `CHECKLISTS_INVALID_TRANSITION` (409) — the checklist is completed

### Item status — `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/`

**Use it when:** recording that a requirement was met, waived, blocked, or does not apply. The daily act.
**Methods:**
- `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` (permission: `checklists.item.status`, risk: medium)

**Send:**
- `status` (required — one of the five `ChecklistItem.status` values)
- `status_note` (**required** when `status` is `waived` or `blocked`)
- `evidence_file` (UUID of an uploaded file)
- `evidence_note`
- `clear_evidence` (bool — detach the current evidence; explicit, because on a partial update an omitted field and an explicit null are indistinguishable)

**Returns:** `ChecklistItem`

**Requires state:**
- the checklist's status is `draft` or `active`
- any `evidence_file` **must already exist and belong to this checklist's journey or to that journey's applicant** (cross-app: `uploaded_files` — upload it there first, with `applicant` or `journey` as its owner)

**Side effects:**
- setting `completed` stamps `completed_at` and `completed_by`; **any other status clears both**
- the checklist's `progress` counts change, which may make `POST .../complete/` newly possible or newly impossible
- one audit event

**Notes:**
- `resolved` in `progress` counts `completed`, `waived`, and `not_applicable`. **`blocked` is not resolved** — it is the status meaning the work did not happen, and it keeps blocking completion
- **To attach evidence without declaring the item done, send `{"status": "pending", "evidence_file": "<id>"}`.** `status` is required on this route, but re-asserting the current one is accepted and is the supported way to file a scan while the decision is still open
- **the response is the item, not the checklist** — it carries no `progress`. A screen showing a progress bar must re-read `GET /<checklist_id>/` after each status change, or recompute the counts client-side from the items it already holds
- a file owned by a `document` or a print snapshot can never be cited here, because such a file is owned by neither a journey nor an applicant

**Errors:**
- `CHECKLISTS_STATUS_NOTE_REQUIRED` (400) — `waived` or `blocked` with no note
- `CHECKLISTS_EVIDENCE_NOT_ALLOWED` (400) — the file belongs to another applicant, **or does not exist**. One code for both, so a caller cannot probe which file ids exist
- `CHECKLISTS_ITEM_NOT_FOUND` (404)
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409), `CHECKLISTS_INVALID_TRANSITION` (409)

### Journeys awaiting a checklist — `GET /api/v1/checklists/?journey_missing_checklist=true`

**Use it when:** finding applicants whose destination has no authored requirement list — the safety net for automatic inheritance.
**Methods:**
- `GET /api/v1/checklists/?journey_missing_checklist=true` (permission: `checklists.checklist.list`, risk: medium)

**Send:** none

**Returns:** list[`JourneyAwaitingChecklist`] — **journeys, not checklists.** The `id` in each row is a journey id.

**Requires state:** none

**Side effects:** none

**Notes:**
- automatic inheritance is silent when a country has no active default template, because an empty checklist would read as "nothing is required of this applicant". This query is what makes that silence visible
- every other **filter** on this route is ignored when this flag is set; `page` and `page_size` still apply, and `meta` carries the usual pagination fields. Rows are newest journey first
- the fix is to author the country's template; existing journeys are then covered by the backend's `apply_country_checklists` management command, not by an endpoint

**Errors:** none beyond the global auth failures

## 8. Flows

**1. Set up a destination and let an applicant inherit it (the primary flow)**
1. `GET /api/v1/catalogue/countries/` *(cross-app: institutions)* → capture `country_id`
2. `POST /api/v1/checklists/templates/` with `{ key, label, country: country_id, is_default: true, status: "active" }` → capture `template_id`
   - `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS` (409) → the country already has a default; read `details.existing_template_id` and edit that one instead
   - `CHECKLISTS_ACTOR_FORBIDDEN` (403) → the caller is a Lead Manager; only an Admin may author
3. `POST /api/v1/checklists/templates/<template_id>/items/` once per requirement
4. `PATCH /api/v1/journeys/<journey_id>/` with `{ "target_country_ref": country_id }` *(cross-app: applicant_journeys)*
   - the journey response says **nothing** about checklists — that app does not know this one exists
5. `GET /api/v1/checklists/?applicant=<applicant_id>` → the checklist is already there, `origin: "auto"`, every item `pending`
   - empty result → either the journey has no `target_country_ref`, or step 2's template is not `active` + `is_default`. Confirm with `GET /?journey_missing_checklist=true`

**2. Work an applicant's list to completion**
1. `GET /api/v1/checklists/?applicant=<applicant_id>` → capture `checklist_id`
2. `GET /api/v1/checklists/<checklist_id>/` → read `items[]` and `progress`
3. `POST /api/v1/files/` *(cross-app: uploaded_files)* with `applicant` as the owner → capture `file_id`
4. `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` with `{ "status": "completed", "evidence_file": file_id }`
   - `CHECKLISTS_EVIDENCE_NOT_ALLOWED` (400) → the file was uploaded against a different applicant; re-upload it against this one
5. repeat until `progress.required_resolved == progress.required_total`
6. `POST /api/v1/checklists/<checklist_id>/complete/`
   - `CHECKLISTS_REQUIRED_ITEMS_PENDING` (409) → `details.items` names what is left. A `blocked` item counts as outstanding; either resolve the blocker or waive the item with `{ "status": "waived", "status_note": "..." }`

**3. A requirement that cannot be met**
1. `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` with `{ "status": "blocked", "status_note": "Awaiting the university's confirmation." }`
   - `CHECKLISTS_STATUS_NOTE_REQUIRED` (400) → the note is not optional for `blocked` or `waived`
2. later, either resolve it (`"status": "completed"`) or waive it (`"status": "waived"` with a note)
3. `POST /api/v1/checklists/<checklist_id>/complete/` now succeeds

**4. Start an applicant's list over**
1. `POST /api/v1/checklists/<checklist_id>/archive/` with `{ "reason": "Applicant restarted their file." }`
2. `POST /api/v1/checklists/` with `{ journey, template }` → a fresh copy, `origin: "manual"`
   - alternatively, re-saving the journey re-triggers automatic inheritance, since the archived checklist no longer blocks it
   - `CHECKLISTS_TEMPLATE_ALREADY_APPLIED` (409) → the old checklist was not archived

**5. Find destinations nobody has set up**
1. `GET /api/v1/checklists/?journey_missing_checklist=true` → journeys whose country has no template
2. for each distinct `target_country_ref`, run flow 1 steps 2–3
3. existing journeys are covered by the backend command `python manage.py apply_country_checklists`; **there is no endpoint for this**, so a purely HTTP client must ask a backend operator, or re-save each journey to re-trigger inheritance

## 9. Gaps

Ordered by how much they cost a real integration.

- **You cannot tell, from this module, what authority the caller holds.** Every route's behaviour depends on Admin versus Lead Manager, and no payload here carries the actor's authority type — `UserBrief` is `{ id, username, display_name }`. A client must obtain it from `authenticate` before it can decide whether to render the template-authoring screens at all. Rendering them and letting the 403 happen is the fallback, and it is a poor one.
- **An item's evidence is one id and nothing else.** Showing "Passport scan.pdf, verified, 1.2 MB" beside a completed item takes a second call per item to `GET /api/v1/files/<id>/`, and there is no bulk file-fetch. A checklist detail screen with twelve cited files is twelve extra requests, or a design that shows only "evidence attached".
- **No endpoint runs the backfill.** After authoring a country's template, journeys that already name that country are not covered automatically. The backend has `apply_country_checklists` as a management command; an HTTP-only consumer must instead re-`PATCH` each journey with its existing `target_country_ref` (which does re-fire inheritance — see §7), one request per journey, sourced from `?journey_missing_checklist=true`.
- **Inheritance is asynchronous with no completion signal.** It runs after the journey's transaction commits, so a read issued in the same instant as the `PATCH` may find nothing. There is no documented latency bound, no polling endpoint, and no way to distinguish "not yet" from "that country has no template" **except** by also querying `?journey_missing_checklist=true`. A client should retry once or twice and then fall back to that query rather than asserting the applicant has no requirements.
- **One operation returns two different resources.** `checklists.checklist.list` returns `Checklist` normally and `JourneyAwaitingChecklist` under `?journey_missing_checklist=true`, where `id` is a **journey** id. A generated client will have one return type for one operation; treat the flag as a separate call site.
- **`CHECKLISTS_TEMPLATE_NOT_FOUND` and `CHECKLISTS_CHECKLIST_ARCHIVED` each appear with two statuses.** `TEMPLATE_NOT_FOUND` is `404` when the template is the addressed resource (`/templates/<id>/`) and `400` when it is a field in a request body (`POST /` with `template`). `CHECKLIST_ARCHIVED` is always `409`. Branch on status *and* code, not code alone.
- **A checklist item cannot be removed.** Template requirements retire with `is_active: false`; a `ChecklistItem` has no equivalent and no `DELETE`. An item added by mistake is permanent, and the nearest escape — `not_applicable` — counts as *resolved*, so it silently satisfies the completion check.
- **There is no bulk item-status endpoint.** Completing a twelve-item checklist is twelve requests, each returning the item without refreshed progress.
- **No concurrency control.** No `ETag`, no `If-Match`, no `updated_at` precondition on any write. Two staff working one checklist is last-write-wins, silently.
- **No ordering parameter** on either list. Templates always sort by `display_order` then `label`; checklists always newest first. Any other order is client-side.
- **Titles, labels, and names are all single English strings.** `Checklist.title`, `ChecklistTemplate.label`, the nested `CountryBrief.name` and `ApplicantBrief.full_name`, and every `description`, `status_note`, and `notes` are one field each.
- **`assigned_to` accepts any active user id**, including a Superadmin — who is then refused on every route in this module. Nothing prevents assigning work to someone who cannot open it, and there is no user-list endpoint here to source a correct picker from.
- **`due_at` write format is not pinned down** beyond ISO 8601. Whether a date-only value is accepted, and whether an omitted timezone is read as UTC, is untested by this contract. The `_bs` sibling objects are read-only; never send one.
- **The `_bs` object's full field set is documented here from an observed payload** (`year`, `month`, `day`, `month_name`, `month_name`, `display`, `display`). Its authoritative shape belongs to the project's Nepali calendar layer, not to this module.
- **`meta` is `{}` on every non-paginated response.** Whether that is guaranteed project-wide is a `core` question.
