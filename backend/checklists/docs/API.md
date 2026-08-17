# API Documentation — Checklists

**App:** `checklists`
**Version:** 1.0.0
**Base prefix:** `/api/v1/checklists/`
**Auth:** JWT bearer, required on every route. Authority rules follow the §9 interim inline pattern — see "Access levels" below.
**Throttle:** project DRF defaults. No route here is public and none performs an expensive unauthenticated operation, so no per-view scope is set.
**Access level:** Staff-only, mixed — Admin-only for template authoring, Admin + Lead Manager for everything else. Superadmin is denied outright.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial API documentation — 18 endpoints across templates, checklists, and items |
| 1.0.1 | 2026-07-24 | AI (Claude Opus 4.8) | No endpoint change. Corrected the documented restore behaviour alongside the code fix: restore returns a checklist to `status_before_archive` rather than inferring `active`. Caught by the §19.5 consumer-contract review |

---

## Generic envelopes (referenced throughout)

**Success:**
```json
{ "success": true, "message": "...", "data": { ... }, "meta": {} }
```

**Error:**
```json
{ "success": false, "error": { "code": "...", "message": "...", "details": {} }, "meta": {} }
```

**Access levels**

| Population | May do |
|------------|--------|
| Admin | everything |
| Lead Manager | every read; all checklist and item work. **Refused on all four template-authoring routes** (403 `CHECKLISTS_ACTOR_FORBIDDEN`) |
| Superadmin | nothing (403 on every route) |

Template authoring is Admin-only because a template propagates automatically to every future applicant for that country — editing one silently changes what dozens of files will be measured against. Item work is shared because collecting a document and ticking it off is the Lead Manager's daily job.

**AI debugging notes (app-wide):**

- **A checklist response with all-zero `progress` almost always means the object was not read through `selectors.get_checklists`.** The counts are queryset annotations, not model properties; a freshly created instance has no annotations and serializes them as `0`. Every view re-reads through `get_checklist_by_id` before responding, for exactly this reason.
- **Query-parameter booleans need care.** DRF treats a query string as HTML input, where a *missing* `BooleanField` resolves to `False` rather than being skipped. `views._search_params` intersects validated data with the raw query params to undo that; without it a plain `GET /templates/` would silently exclude every default template.
- **Automatic inheritance has no endpoint.** If a checklist is "missing", the cause is upstream: the journey has no `target_country_ref`, or that country has no active default template. `GET /?journey_missing_checklist=true` lists the second case.
- Every write appends one audit event (`app_label = "checklists"`). Inherited checklists are recorded with `actor_type = system`.

---

## 1. Checklist Templates

The country requirement lists. Authored once per destination; inherited automatically by applicants.

### 1.1 List templates — `GET /api/v1/checklists/templates/`

**Policy key(s):** `checklists.template.list` (risk: low)
**Access:** Admin, Lead Manager
**Query params:** `country` (UUID), `status` (`draft`|`active`|`inactive`), `is_default` (bool), `search` (matches `label` or `key`, case-insensitive)
**Response:** paginated list of `DATA_CONTRACT.md §1`, each with its `items` (`§2`) embedded.
**Query access pattern:** `select_related("country", "created_by")` + `prefetch_related("items")`. Items are sorted in Python from the prefetch, so a page of templates stays two queries regardless of how many requirements each defines.
**Error codes:** validation errors on a malformed filter value (400) — a mistyped `status` is a 400 naming the field, never an empty page.

### 1.2 Create a template — `POST /api/v1/checklists/templates/`

**Policy key(s):** `checklists.template.create` (risk: high)
**Access:** **Admin only**
**Request:**
```json
{ "key": "australia-student", "label": "Australia — Student Visa", "country": "<country uuid>", "is_default": true, "status": "active" }
```
**Response:** `DATA_CONTRACT.md §1`, HTTP 201.
**Validation rules:** `key` must be ASCII (`^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$`) and unique. Omitting `status` creates a `draft` — a template with no requirements yet must not be inheritable the moment it is saved.
**Business rules:** at most one `active` `is_default` template per country; a default must name a country. Both are database constraints *and* service checks, so the caller is told which template holds the slot rather than reading a constraint name.
**Error codes:**
- `CHECKLISTS_ACTOR_FORBIDDEN` (403) — Lead Manager or Superadmin
- `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS` (409) — this country already has an active default. `details.existing_template_id` names it
- `CHECKLISTS_DEFAULT_REQUIRES_COUNTRY` (400) — `is_default` with no `country`
- `CHECKLISTS_COUNTRY_NOT_FOUND` (400) — `country` names no catalogue row
- `VALIDATION_ERROR` (400) — duplicate or malformed `key`

### 1.3 Read a template — `GET /api/v1/checklists/templates/<template_id>/`

**Policy key(s):** `checklists.template.read` (risk: low)
**Access:** Admin, Lead Manager
**Response:** `DATA_CONTRACT.md §1` with every requirement, **retired ones included** — an Admin editing a template needs to see what was retired, and `is_active` tells them apart. Active definitions sort first.
**Error codes:** `CHECKLISTS_TEMPLATE_NOT_FOUND` (404)

### 1.4 Edit a template — `PATCH /api/v1/checklists/templates/<template_id>/`

**Policy key(s):** `checklists.template.update` (risk: high)
**Access:** **Admin only**
**Request:** any of `label`, `description`, `country`, `is_default`, `status`, `status_note`, `display_order`, `notes`.
**Validation rules:** `key` is not accepted — it is what seed data, logs, and any external reference point at, and letting it move would break all three while returning 200.
**Business rules:** **Editing a template never touches checklists already inherited from it.** Instantiation is a snapshot. The single-default rule is re-checked against the merged state, so moving the default flag between two templates in either order behaves the same. Retiring the current default (`status: inactive`) frees the slot.
**Error codes:** as §1.2, plus `CHECKLISTS_TEMPLATE_NOT_FOUND` (404)

### 1.5 Add a requirement — `POST /api/v1/checklists/templates/<template_id>/items/`

**Policy key(s):** `checklists.template_item.create` (risk: high)
**Access:** **Admin only**
**Request:**
```json
{ "label": "Passport bio page scan", "item_type": "document", "is_required": true, "display_order": 1, "default_due_offset_days": 14 }
```
**Response:** `DATA_CONTRACT.md §2`, HTTP 201.
**Business rules:** affects who inherits it **next**. Applicants already holding a copy are untouched.
**Error codes:** `CHECKLISTS_ACTOR_FORBIDDEN` (403), `CHECKLISTS_TEMPLATE_NOT_FOUND` (404)

### 1.6 Edit or retire a requirement — `PATCH /api/v1/checklists/templates/<template_id>/items/<item_id>/`

**Policy key(s):** `checklists.template_item.update` (risk: high)
**Access:** **Admin only**
**Request:** any of the create fields, plus `is_active`.
**Business rules:** **there is no delete.** Retirement is `is_active: false`, because a live checklist item holds a `PROTECT` foreign key to the definition it was copied from. A retired definition stops being copied and changes nothing about existing checklists.
**Error codes:** `CHECKLISTS_ACTOR_FORBIDDEN` (403), `CHECKLISTS_TEMPLATE_NOT_FOUND` (404), `CHECKLISTS_TEMPLATE_ITEM_NOT_FOUND` (404)

---

## 2. Checklists

One applicant's copy. **The common path has no endpoint at all** — setting a journey's `target_country_ref` (via `PATCH /api/v1/journeys/<id>/`) inherits that country's list automatically.

### 2.1 List checklists — `GET /api/v1/checklists/`

**Policy key(s):** `checklists.checklist.list` (risk: medium)
**Access:** Admin, Lead Manager
**Query params:** `applicant` (UUID — traverses the journey; this is how a client renders the applicant panel), `journey`, `status`, `origin` (`auto`|`manual`), `assigned_to`, `country`, `template`, `overdue` (bool), and `journey_missing_checklist` (bool — see §2.9).
**Response:** paginated list of `DATA_CONTRACT.md §3` **without** `items`, each carrying a `progress` object.
**Query access pattern:** `select_related("journey", "journey__applicant", "country", "assigned_to", "source_template")` plus seven `Count` annotations computed in one aggregate pass. A page of twenty checklists is a fixed query count regardless of how many items each holds — asserted by `tests/test_views.py::QueryBudgetTests`.
**Business rules:** `overdue` means the *work* is late, so it matches only `draft` and `active` checklists past their `due_at`; a completed one is never overdue however long ago its date passed. Archived checklists are **included** by default — filter with `?status=active` to exclude them.
**Error codes:** validation errors on a malformed filter value (400)

### 2.2 Create a checklist — `POST /api/v1/checklists/`

**Policy key(s):** `checklists.checklist.create` (risk: medium)
**Access:** Admin, Lead Manager
**Request — two shapes, distinguished by `template`:**
```json
{ "journey": "<journey uuid>", "template": "<template uuid>" }
```
applies that template by hand — the override beside the automation, for a non-default template or a fresh copy after archiving. Everything else in the body is ignored: the template supplies the title, description, country, and items.
```json
{ "journey": "<journey uuid>", "title": "Internal review", "assigned_to": "<user uuid>", "due_at": "2026-08-01T00:00:00Z" }
```
starts an empty checklist as a `draft`.
**Response:** `DATA_CONTRACT.md §3` with `items` and `progress`, HTTP 201.
**Validation rules:** `title` is required when no `template` is given.
**Business rules:** an applied template must be `active` and hold at least one active requirement. A journey may hold at most one non-archived checklist per template.
**Error codes:**
- `CHECKLISTS_JOURNEY_NOT_FOUND` (400)
- `CHECKLISTS_TEMPLATE_NOT_FOUND` (400)
- `CHECKLISTS_TEMPLATE_NOT_ACTIVE` (400) — a draft or retired template
- `CHECKLISTS_TEMPLATE_HAS_NO_ITEMS` (400) — an empty list would read as "nothing is required"
- `CHECKLISTS_TEMPLATE_ALREADY_APPLIED` (409) — archive the existing one first
- `VALIDATION_ERROR` (400) — no `template` and no `title`

### 2.3 Read a checklist — `GET /api/v1/checklists/<checklist_id>/`

**Policy key(s):** `checklists.checklist.read` (risk: medium)
**Access:** Admin, Lead Manager
**Response:** `DATA_CONTRACT.md §3` with every item (`§4`), the `progress` counts, and the lifecycle stamps.
**Query access pattern:** the list joins plus `prefetch_related("items__assigned_to", "items__completed_by")` — the nested item briefs previously cost up to two FK queries per item (2026-08-17 audit, P1). Fixed query count asserted by `tests/test_views.py::ChecklistDetailQueryCountTests`.
**Error codes:** `CHECKLISTS_CHECKLIST_NOT_FOUND` (404)

### 2.4 Edit a checklist — `PATCH /api/v1/checklists/<checklist_id>/`

**Policy key(s):** `checklists.checklist.update` (risk: low)
**Access:** Admin, Lead Manager
**Request:** any of `title`, `description`, `assigned_to`, `due_at`, `notes`.
**Business rules:** **`status` is not accepted here.** It moves only through §2.5–§2.8, so a client cannot declare a checklist complete with a `PATCH` and bypass the required-items check that gives the word its meaning. An unknown field is ignored by the serializer rather than rejected.
**Error codes:** `CHECKLISTS_CHECKLIST_NOT_FOUND` (404), `CHECKLISTS_CHECKLIST_ARCHIVED` (409)

### 2.5 Activate — `POST /api/v1/checklists/<checklist_id>/activate/`

**Policy key(s):** `checklists.checklist.activate` (risk: low)
**Access:** Admin, Lead Manager
**Request:** empty body.
**Business rules:** `draft` → `active`, stamping `activated_at`. Inherited and template-applied checklists arrive `active` already, so this only ever applies to a blank checklist.
**Error codes:** `CHECKLISTS_CHECKLIST_NOT_FOUND` (404), `CHECKLISTS_INVALID_TRANSITION` (409), `CHECKLISTS_CHECKLIST_ARCHIVED` (409)

### 2.6 Complete — `POST /api/v1/checklists/<checklist_id>/complete/`

**Policy key(s):** `checklists.checklist.complete` (risk: high)
**Access:** Admin, Lead Manager
**Request:** empty body.
**Business rules:** **completion is derived from the items, never asserted.** Refused unless every `is_required` item is `completed`, `waived`, or `not_applicable`. A `blocked` required item still refuses. Optional items never block. On success, stamps `completed_at` and `completed_by`.
**Error codes:**
- `CHECKLISTS_REQUIRED_ITEMS_PENDING` (409) — `details.items` lists **every** offending item with its `id`, `label`, and `status`. "Something is still pending" on a forty-item list is not an answer anyone can act on
- `CHECKLISTS_INVALID_TRANSITION` (409) — not `active`
- `CHECKLISTS_CHECKLIST_NOT_FOUND` (404), `CHECKLISTS_CHECKLIST_ARCHIVED` (409)

### 2.7 Reopen — `POST /api/v1/checklists/<checklist_id>/reopen/`

**Policy key(s):** `checklists.checklist.reopen` (risk: medium)
**Access:** Admin, Lead Manager
**Request:** `{ "reason": "..." }` — optional.
**Business rules:** `completed` → `active`, **clearing `completed_at` and `completed_by`**. Leaving them would make a reopened checklist look finished to every query reading `completed_at`; the completion itself survives in the audit log, which is where "completed on the 3rd, reopened on the 7th" is answered.
**Error codes:** `CHECKLISTS_CHECKLIST_NOT_FOUND` (404), `CHECKLISTS_INVALID_TRANSITION` (409), `CHECKLISTS_CHECKLIST_ARCHIVED` (409)

### 2.8 Archive / Restore — `POST /api/v1/checklists/<checklist_id>/archive/` · `.../restore/`

**Policy key(s):** `checklists.checklist.archive` (risk: medium), `checklists.checklist.restore` (risk: low)
**Access:** Admin, Lead Manager
**Request:** archive takes `{ "reason": "..." }` — **required**. Restore takes an empty body.
**Business rules:** archiving takes a checklist out of active work and refuses every subsequent edit. It is also **how staff ask for a fresh copy of a country's list**: an archived checklist no longer blocks re-applying its template, and no longer blocks automatic inheritance. Restore returns it to **`status_before_archive`** — the exact state it held when archived, which may be `draft`, `active`, or `completed` — and clears the archive columns. **Restore is not a reopen:** a checklist archived while complete comes back complete, with its stamps intact.
**Error codes:** `CHECKLISTS_ARCHIVE_REASON_REQUIRED` (400), `CHECKLISTS_INVALID_TRANSITION` (409 — already archived), `CHECKLISTS_CHECKLIST_NOT_ARCHIVED` (409 — restore on a live checklist), `CHECKLISTS_CHECKLIST_NOT_FOUND` (404)

### 2.9 Journeys awaiting a checklist — `GET /api/v1/checklists/?journey_missing_checklist=true`

**Policy key(s):** `checklists.checklist.list` (risk: medium)
**Access:** Admin, Lead Manager
**Response:** a paginated list of **journeys**, not checklists — `{ id, applicant, target_country_ref, stage, created_at }`.
**Business rules:** the safety net for automatic inheritance. A country with no authored default template produces no checklist and no error, correctly so; this query is what keeps that silence from reading as success. Every row is an applicant whose destination nobody has authored requirements for yet.
**Query access pattern:** `ApplicantJourney` filtered to a non-null `target_country_ref` and excluding any with a `draft`, `active`, or `completed` checklist. Archived checklists do not count as coverage — a journey whose only checklist was archived is legitimately awaiting a new one.
**Business follow-up:** author the template, then run `python manage.py apply_country_checklists --country=<id>`.

---

## 3. Checklist Items

### 3.1 Add an item — `POST /api/v1/checklists/<checklist_id>/items/`

**Policy key(s):** `checklists.item.create` (risk: low)
**Access:** Admin, Lead Manager
**Request:** `{ "label": "Extra reference letter", "item_type": "document", "is_required": false, "assigned_to": "<uuid>", "due_at": "..." }`
**Response:** `DATA_CONTRACT.md §4`, HTTP 201.
**Business rules:** for the case the template did not anticipate — one institution asking this applicant for one extra thing. **It never travels back to the template**, so the next applicant bound for the same country is unaffected. Permitted only while the checklist is `draft` or `active`.
**Error codes:** `CHECKLISTS_CHECKLIST_NOT_FOUND` (404), `CHECKLISTS_CHECKLIST_ARCHIVED` (409), `CHECKLISTS_INVALID_TRANSITION` (409 — checklist is completed; reopen it first)

### 3.2 Edit an item — `PATCH /api/v1/checklists/<checklist_id>/items/<item_id>/`

**Policy key(s):** `checklists.item.update` (risk: low)
**Access:** Admin, Lead Manager
**Request:** any of `label`, `description`, `item_type`, `is_required`, `display_order`, `assigned_to`, `due_at`, `evidence_note`.
**Business rules:** **`status` is not accepted here** — it moves only through §3.3, where the note and evidence rules live. A client editing a label should not have to satisfy them.
**Error codes:** `CHECKLISTS_ITEM_NOT_FOUND` (404), plus §3.1's

### 3.3 Set item status — `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/`

**Policy key(s):** `checklists.item.status` (risk: medium)
**Access:** Admin, Lead Manager — **the daily act**
**Request:**
```json
{ "status": "completed", "status_note": "", "evidence_file": "<file uuid>", "evidence_note": "Scan received 2026-07-24", "clear_evidence": false }
```
**Validation rules:**
- `status_note` is **required** for `waived` and `blocked`. Both are judgements someone will be asked about months later
- `evidence_file` must belong to this checklist's journey or that journey's applicant
- `clear_evidence: true` detaches the current evidence. It is explicit rather than inferred from a null `evidence_file`, because on a partial update the two are indistinguishable

**Business rules:** the completion stamps follow the status rather than accumulating — moving an item back to `pending` clears `completed_at` and `completed_by`, because an item that kept a "completed by" would report work nobody is now claiming.

**Security note:** the evidence rule has a second consequence worth stating. A file owned by a `document` or a print snapshot is never owned by a journey or an applicant, so it can never be cited here — which is what keeps this module from becoming a route by which a Lead Manager reaches material the `documents` stack holds Admin-only.

**Error codes:**
- `CHECKLISTS_STATUS_NOTE_REQUIRED` (400) — `waived` or `blocked` with no note
- `CHECKLISTS_EVIDENCE_NOT_ALLOWED` (400) — the file belongs to another applicant, or does not exist. **One code for both**, deliberately: distinguishing them would let a caller probe which file ids exist
- `CHECKLISTS_ITEM_NOT_FOUND` (404) — including an item id belonging to a different checklist; item routes are scoped to their checklist so a stray id reaches nobody
- `CHECKLISTS_CHECKLIST_ARCHIVED` (409), `CHECKLISTS_INVALID_TRANSITION` (409)

---

## 4. Endpoints this app deliberately does not have

- **No "inherit checklist" endpoint.** The trigger is `PATCH /api/v1/journeys/<id>/` with `target_country_ref`. Adding a second, explicit way to do the same thing would let the two disagree.
- **No delete anywhere.** Templates retire (`status: inactive`), requirements retire (`is_active: false`), checklists archive, items become `not_applicable`.
- **No checklist history endpoint.** The audit log carries every event; `GET /api/v1/audit/?app=checklists&entity_id=<id>` is the query.
