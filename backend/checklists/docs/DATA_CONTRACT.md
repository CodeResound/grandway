# Data Contract — Checklists

**Owner app:** `checklists`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the country requirement lists an Admin authors, and each applicant's own copy of one. It does **not** own the records those requirements refer to: `uploaded_files` owns files, `documents`/`document_history`/`document_templates` own document records, `offers` owns offer conditions, `institutions` owns the country catalogue, and `applicant_journeys` owns the destination. This app records what is still outstanding and what proves it was done.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial contract — four models, automatic country-driven inheritance, snapshot instantiation |
| 1.0.1 | 2026-07-24 | AI (Claude Opus 4.8) | Added `Checklist.status_before_archive` (folded into `0001_initial`, which had not shipped). Restore now returns a checklist to the exact status it was archived in rather than inferring one — a completed checklist that was archived came back `active` while still carrying `completed_at`. Caught by the §19.5 review |

---

## Deliberate Deviations

The concept file (`concepts/checklists.txt`) was rewritten in the same session as this build, so it and this contract agree. Three decisions still depart from a project-wide default and are recorded here:

- **`ChecklistTemplate.label` and `ChecklistItem.label` are single fields, not the §39.1 `_np`/`_en` pair.** A template label is operational shorthand read off a picker, the deviation `documents.label` first recorded and `document_templates.label` followed. The names in this module that genuinely carry two canonical identities are the country's, and those live in the `institutions` catalogue where §39.1 already applies.
- **`Checklist.created_by` is nullable — the only nullable `created_by` in the project.** A checklist inherited automatically has no human author. Recording the staff member who happened to be editing the journey would be a lie about who decided the applicant needed this list, so the column is null and `origin` says why.
- **`ChecklistItem.evidence_file` is the project's first inbound foreign key to `uploaded_files`.** Until now that app depended on five others and none depended on it. The reference is one-way and optional; nothing in `uploaded_files` knows this app exists.

---

## 1. ChecklistTemplate

**Purpose:** One destination country's requirement list, authored by an Admin. The model that makes the module dynamic — adding a country's requirements is data entry, never a migration.
**Table:** `checklists_checklisttemplate`
**`status` choices:** `draft`, `active`, `inactive`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| key | CharField(50) | Yes | No | No | Stable ASCII identifier, unique. Immutable after creation |
| label | CharField(200) | Yes | No | No | What staff see, e.g. `Australia — Student Visa` |
| description | TextField | No | No | No | Blank when unused |
| country | FK → `institutions.Country` | No | Yes | No | The destination. `PROTECT`. Null means a general list, applied only by hand |
| is_default | BooleanField | No | No | No | The list this country's applicants inherit. Defaults to `False` |
| status | CharField(20) | No | No | No | Defaults to `draft` |
| status_note | TextField | No | No | No | Why the template is in its current state. Never required |
| display_order | PositiveIntegerField | No | No | No | Defaults to `0` |
| notes | TextField | No | No | No | Blank when unused |
| created_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| created_at | DateTimeField | — | No | Yes | `auto_now_add` |
| updated_at | DateTimeField | — | No | Yes | `auto_now` |

**Validation Rules:**
- `key` matches `^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$` — ASCII only (§39.7). Unique; a duplicate is a serializer validation error, not a database error.
- **At most one `active` `is_default` template per country.** Enforced by the partial unique constraint `checklist_one_active_default_per_country`, and re-checked in `services._assert_default_is_coherent` so the caller is told which template already holds the slot instead of reading a constraint name.
- **A default must name a country.** Enforced by `checklist_default_requires_country` and re-checked in the service. A default with no country could never be inherited by anyone.
- Every user-entered text field is Unicode-normalized on write (§39.2).

**Indexes:** `(country, status)` — `cl_template_country_status_idx`, backing the per-country picker and the single query automatic inheritance depends on.

**Soft Delete:** N/A — templates are never deleted. A template a checklist points back at must stay resolvable forever, so retirement is `status = inactive`. Retiring the active default frees the slot for a replacement.

**Example:**
```json
{
  "id": "9b1f3c22-8d4a-4e1b-9c77-2f0a6b5d1e33",
  "key": "australia-student",
  "label": "Australia — Student Visa",
  "description": "Documents and stages required for an Australian student visa application.",
  "country": { "id": "3a7c...", "code": "au", "name_en": "Australia", "name_np": "अष्ट्रेलिया" },
  "is_default": true,
  "is_inheritable": true,
  "status": "active",
  "status_note": "",
  "display_order": 0,
  "notes": "",
  "items": [],
  "created_by": { "id": "1f2e...", "username": "adminuser", "display_name": "Adminuser" },
  "created_at": "2026-07-24T09:12:44.183Z",
  "updated_at": "2026-07-24T09:12:44.183Z"
}
```

**Cross-App Dependencies:** `institutions.Country` (FK, `PROTECT`) — a template is scoped to a catalogue country. `authenticate.User` (FK, `PROTECT`) — the author.

---

## 2. ChecklistTemplateItem

**Purpose:** One requirement definition inside a template. Copied onto each applicant's checklist at instantiation; never read through afterwards.
**Table:** `checklists_checklisttemplateitem`
**`item_type` choices:** `document`, `stage`, `task`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| template | FK → `ChecklistTemplate` | Yes | No | No | `CASCADE` — an item has no meaning apart from its template |
| label | CharField(255) | Yes | No | No | The requirement, e.g. `Passport bio page scan` |
| description | TextField | No | No | No | Blank when unused |
| item_type | CharField(20) | No | No | No | Defaults to `document` |
| is_required | BooleanField | No | No | No | Defaults to `True`. Required items gate completion |
| display_order | PositiveIntegerField | No | No | No | Defaults to `0`. The order items are copied in |
| default_due_offset_days | PositiveIntegerField | No | Yes | No | Days after instantiation this item is due. Becomes a real `due_at` on each copy |
| is_active | BooleanField | No | No | No | Defaults to `True`. Retirement, not deletion |
| created_at | DateTimeField | — | No | Yes | `auto_now_add` |
| updated_at | DateTimeField | — | No | Yes | `auto_now` |

**Validation Rules:**
- `label` and `description` are Unicode-normalized on write (§39.2).
- Only `is_active` definitions are copied at instantiation. Retiring one has no effect on any checklist that already copied it.

**Indexes:** `(template, display_order)` — `cl_tmpl_item_order_idx`.

**Soft Delete:** N/A in the usual sense, but `is_active = False` is the retirement mechanism and there is no delete endpoint. A live `ChecklistItem` holds a `PROTECT` foreign key to the definition it was copied from, so a hard delete would be refused by the database anyway.

**Cross-App Dependencies:** none.

---

## 3. Checklist

**Purpose:** One applicant's own copy of a country's requirement list. Two applicants headed for the same country hold two of these, with identical items and entirely independent progress.
**Table:** `checklists_checklist`
**`status` choices:** `draft`, `active`, `completed`, `archived`
**`origin` choices:** `auto`, `manual`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| journey | FK → `applicant_journeys.ApplicantJourney` | Yes | No | No | `PROTECT`. The subject. The applicant is reached through it |
| source_template | FK → `ChecklistTemplate` | No | Yes | No | `PROTECT`. Null for a blank checklist staff built by hand |
| country | FK → `institutions.Country` | No | Yes | No | `PROTECT`. **Copied from the template at instantiation**, not re-read |
| title | CharField(200) | Yes | No | No | Copied from the template's label. The label snapshot |
| description | TextField | No | No | No | Copied from the template's description |
| origin | CharField(20) | No | No | No | Defaults to `manual`. `auto` when the signal created it |
| status | CharField(20) | No | No | No | Defaults to `draft`; instantiation creates it `active` |
| assigned_to | FK → `authenticate.User` | No | Yes | No | `SET_NULL` |
| due_at | DateTimeField | No | Yes | No | Checklist-level deadline |
| notes | TextField | No | No | No | Blank when unused |
| activated_at | DateTimeField | No | Yes | Yes | Set on activation, and at instantiation |
| completed_at | DateTimeField | No | Yes | Yes | Set on completion, **cleared on reopen** |
| completed_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL`. Cleared on reopen |
| archive_reason | TextField | No | No | Yes | Set on archive, cleared on restore |
| archived_at | DateTimeField | No | Yes | Yes | Cleared on restore |
| archived_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL`. Cleared on restore |
| status_before_archive | CharField(20) | No | No | Yes | The status held at archive time, restored verbatim. Blank unless archived |
| created_by | FK → `authenticate.User` | No | **Yes** | No | `PROTECT`. **Null for an inherited checklist** — nobody authored it |
| created_at | DateTimeField | — | No | Yes | `auto_now_add` |
| updated_at | DateTimeField | — | No | Yes | `auto_now` |

**Validation Rules:**
- **Completion is derived, never asserted.** `complete_checklist` refuses unless every `is_required` item is `completed`, `waived`, or `not_applicable`. A `blocked` required item still refuses — it is precisely the status meaning the work did not happen. The refusal names every offending item.
- Only an `active` checklist can be completed; only a `completed` one can be reopened; only a `draft` one can be activated.
- Archiving requires a non-blank reason. An archived checklist refuses every edit until restored.
- Restore returns the checklist to **`status_before_archive`** — exactly the state it was archived in. Archiving a `completed` checklist and restoring it gives back a `completed` one with its stamps intact; **restore is not a reopen.** The first implementation inferred the state from `activated_at` and produced an `active` checklist still carrying `completed_at`, which read as "completed on the 3rd" above unfinished work. Found by the §19.5 consumer-contract review; regression test in `tests/test_services.py::ArchiveTests`.
- `status` is not writable through the update endpoint — it moves only through the lifecycle actions, so a `PATCH` cannot bypass the required-items check.
- A journey may hold at most one **non-archived** checklist per template. Archiving one frees the journey to receive a fresh copy.

**Indexes:**
- `(journey, -created_at)` — `cl_journey_recent_idx`, the Applicant/Journey Detail panel
- `(status, -created_at)` — `cl_status_recent_idx`, the operational worklist
- `(assigned_to, status)` — `cl_assignee_status_idx`, "what is on my desk"
- `(country, status)` — `cl_country_status_idx`, "every Australia checklist"
- `(due_at)` — `cl_due_idx`, the overdue sweep

**Ordering:** `["-created_at", "-id"]`. The `id` tiebreaker is not cosmetic: `created_at` is not unique — the backfill command writes many rows in one pass — and a non-unique sort key under page-number pagination lets a row appear on two pages or on none.

**Soft Delete:** `status = archived` is the soft delete. There is no delete endpoint and no delete service. Archived checklists remain in the default queryset and are returned by list and detail; a client filters them out with `?status=active`. Archiving is deliberately not hidden, because it is also the mechanism for requesting a fresh copy of a country's list, and a "disappeared" checklist would make that indistinguishable from data loss.

**Progress (derived, never stored):** `selectors.get_checklists` annotates `item_total`, `item_resolved`, `required_total`, `required_resolved`, `item_blocked`, `document_total`, and `document_resolved` in one aggregate pass. No progress figure is persisted, so none can disagree with the items it summarizes. Any code path returning a checklist **must** read it through that selector or the counts serialize as zero.

**Example:**
```json
{
  "id": "7c3e9a11-4b2d-4f0e-8a55-1d9c7b3e2f10",
  "journey": "5e2b...",
  "applicant": { "id": "8a1c...", "full_name_np": "राम बहादुर", "full_name_en": "Ram Bahadur", "status": "active" },
  "source_template": "9b1f3c22-8d4a-4e1b-9c77-2f0a6b5d1e33",
  "country": { "id": "3a7c...", "code": "au", "name_en": "Australia", "name_np": "अष्ट्रेलिया" },
  "title": "Australia — Student Visa",
  "origin": "auto",
  "status": "active",
  "assigned_to": null,
  "due_at": null,
  "progress": { "total": 3, "resolved": 1, "required_total": 2, "required_resolved": 1, "blocked": 0, "document_total": 2, "document_resolved": 1 },
  "created_by": null,
  "created_at": "2026-07-24T09:20:03.771Z"
}
```

**Cross-App Dependencies:** `applicant_journeys.ApplicantJourney` (FK, `PROTECT`) — the subject, and the source of the destination that triggered inheritance. `institutions.Country` (FK, `PROTECT`) — the destination, copied at instantiation. `authenticate.User` (FK — one `PROTECT` author, three `SET_NULL` lifecycle actors).

**Security Notes:** Neither reads nor writes are owner-scoped — any Admin or Lead Manager may read any checklist, inherited from `applicants` for the same reason: once a person enters the applicant lifecycle, several staff legitimately work on their file.

---

## 4. ChecklistItem

**Purpose:** One requirement on one applicant, and the record of what happened to it.
**Table:** `checklists_checklistitem`
**`status` choices:** `pending`, `completed`, `waived`, `blocked`, `not_applicable`
**`item_type` choices:** `document`, `stage`, `task`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| checklist | FK → `Checklist` | Yes | No | No | `CASCADE` |
| source_template_item | FK → `ChecklistTemplateItem` | No | Yes | No | `PROTECT`. Provenance only. Null for an item staff added by hand |
| label | CharField(255) | Yes | No | No | **Copied** from the definition, not read through it |
| description | TextField | No | No | No | Copied |
| item_type | CharField(20) | No | No | No | Copied. Defaults to `document` |
| is_required | BooleanField | No | No | No | Copied. Defaults to `True` |
| display_order | PositiveIntegerField | No | No | No | Copied |
| status | CharField(20) | No | No | No | Defaults to `pending` |
| status_note | TextField | No | No | No | **Required** when status is `waived` or `blocked` |
| assigned_to | FK → `authenticate.User` | No | Yes | No | `SET_NULL` |
| due_at | DateTimeField | No | Yes | Yes | Derived from `default_due_offset_days` at instantiation; editable afterwards |
| evidence_file | FK → `uploaded_files.UploadedFile` | No | Yes | No | `PROTECT`. Must belong to this checklist's journey or applicant |
| evidence_note | TextField | No | No | No | Blank when unused |
| completed_at | DateTimeField | No | Yes | Yes | Set when status becomes `completed`, **cleared on any other status** |
| completed_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL`. Cleared with `completed_at` |
| created_at | DateTimeField | — | No | Yes | `auto_now_add` |
| updated_at | DateTimeField | — | No | Yes | `auto_now` |

**Validation Rules:**
- `status_note` must be non-blank for `waived` and `blocked` (`NOTE_REQUIRED_STATUSES`). Both are judgements someone will be asked about later.
- **`evidence_file` must belong to this checklist's journey or to that journey's applicant.** Anything else is refused. This also means a file owned by a `document` or a print snapshot can never be cited here — which is what keeps this module from becoming a way for a Lead Manager to reach material `documents` holds Admin-only.
- Detaching evidence requires an explicit `clear_evidence` flag. On a partial update an omitted field and an explicit null are indistinguishable, and silently detaching the proof behind a completed item is not something a client should be able to do by omission.
- The completion stamps follow the status rather than accumulating: moving an item back to `pending` clears both.
- Items may be added, edited, or have their status changed only while the checklist is `draft` or `active`.
- `status` is not writable through the item update endpoint — it moves only through the status endpoint, where the note and evidence rules live.

**Indexes:**
- `(checklist, display_order)` — `cl_item_order_idx`, the detail view in the author's order
- `(status, due_at)` — `cl_item_status_due_idx`, the overdue sweep across every applicant
- `(assigned_to, status)` — `cl_item_assignee_idx`

**Soft Delete:** N/A — items are not deleted. An item that turns out not to apply is set to `not_applicable`, which records the decision instead of erasing the requirement.

**Cross-App Dependencies:** `uploaded_files.UploadedFile` (FK, `PROTECT`) — evidence. **This is the project's first inbound reference to `uploaded_files`.** `authenticate.User` (FK, two `SET_NULL`).

---

## 5. Automatic inheritance (behaviour, not a table)

Not a model, but part of this app's contract and invisible from any schema.

**Trigger:** `post_save` on `applicant_journeys.ApplicantJourney`, registered in `ChecklistsConfig.ready()` (§11). Fires whenever a journey with a non-null `target_country_ref` is saved — creation or update alike.

**Effect:** inside `transaction.on_commit`, resolves the country's `active` `is_default` template and instantiates it with `origin = auto`, `status = active`, `created_by = null`.

**Guarantees:**
- **Idempotent.** A journey already holding a non-archived checklist from that template gets nothing. Re-saving never produces a second copy.
- **Silent when it cannot act.** No country, or no default template for that country, is a no-op — not an error. An empty checklist would read as "nothing is required of this applicant", which is never true.
- **Never rolls back the journey.** It runs after commit and swallows every failure into the log and an unsuccessful `checklist_inherit_failed` audit event. The destination being recorded matters more than the list being generated, and the list can always be generated later.

**Escape hatch:** `settings.DISABLE_SIGNALS = True` switches it off for bulk imports (§11). Rebuild afterwards with `python manage.py apply_country_checklists`.

**Visibility of the silent case:** `selectors.get_journeys_missing_checklist` — active journeys naming a country with no live checklist — surfaced at `GET /api/v1/checklists/?journey_missing_checklist=true`.

---

## 6. Audit events

Every write appends one event through `audit.services.record_event` with `app_label = "checklists"`.

| Action | Entity type | Written by |
|--------|-------------|------------|
| `checklist_template_created` / `_updated` | `checklist_template` | Template create / update |
| `checklist_template_item_created` / `_updated` | `checklist_template` | Requirement create / update |
| `checklist_created` | `checklist` | Manual apply, or a blank checklist |
| `checklist_inherited` | `checklist` | Automatic inheritance. `actor_type` is `system` — nobody decided it |
| `checklist_inherit_failed` | `checklist` | Inheritance raised. `success = false` |
| `checklist_updated` / `_activated` / `_completed` / `_reopened` / `_archived` / `_restored` | `checklist` | The lifecycle actions |
| `checklist_item_created` / `_updated` / `_status_changed` | `checklist_item` | Item work |
