# FLOWS — Checklists

**Owner app:** `checklists`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/checklists.txt` to the callable endpoints in `backend/checklists/docs/INTEGRATION.md`.

> **One flow in this file has no endpoint of its own.** Flow 2 is the module's headline behaviour and
> its only step is a call into another app: setting a journey's destination country. The checklist
> appears as a side effect. A frontend that waits for a checklist endpoint to call will wait forever.

---

## Flow: Author a destination country's requirement list

- **Actor:** Admin (Lead Managers are refused on every step)
- **Goal:** Record, once, what a country requires of every applicant sent there
- **Entry point:** Checklist template authoring screen

**Steps**

1. **Checklist template authoring screen** — pick the destination country from the catalogue →
   `GET /api/v1/catalogue/countries/` (`institutions.country.list`) **(cross-app: `institutions`)**
   - **Requires state:** none
   - **Side effects:** none
2. **Checklist template authoring screen** — save the list's identity, scoped to that country →
   `POST /api/v1/checklists/templates/` (`checklists.template.create`)
   - **Requires state:** the country exists; it has no other `active` template with `is_default: true`
   - **Side effects:** none. Existing applicants are unaffected — a template is only ever copied at the moment a checklist is created
   - *Failure — `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS`:* blocking dialog naming the existing list, with a link to it built from `details.existing_template_id`. Offer "edit that one instead", not "try again"
   - *Failure — `CHECKLISTS_DEFAULT_REQUIRES_COUNTRY`:* inline field error on the country picker
   - *Failure — `CHECKLISTS_ACTOR_FORBIDDEN`:* the screen should not have been reachable — hide it for a Lead Manager rather than rendering it read-only
3. **Checklist template authoring screen** — add each requirement, typed as a document, stage, or task →
   `POST /api/v1/checklists/templates/<template_id>/items/` (`checklists.template_item.create`)
   - **Requires state:** the template exists. It need not be active — requirements are normally added while it is still a draft
   - **Side effects:** none for anyone already holding a copy
4. **Checklist template authoring screen** — publish the list →
   `PATCH /api/v1/checklists/templates/<template_id>/` (`checklists.template.update`) with `{"status": "active"}`
   - **Requires state:** the single-default rule still holds for its country
   - **Side effects:** **from this moment, any journey saved with that country inherits this list.** Journeys that already name the country are *not* retroactively covered — see flow 5
   - *Failure — `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS`:* as step 2

## Flow: An applicant receives their checklist

- **Actor:** Admin or Lead Manager
- **Goal:** Give an applicant the requirement list for the country they have settled on
- **Entry point:** Journey detail screen

**Steps**

1. **Journey detail screen** — choose the destination country →
   `PATCH /api/v1/journeys/<journey_id>/` (`applicant_journeys.journey.update`) with `{"target_country_ref": "<country_id>"}` **(cross-app: `applicant_journeys`)**
   - **Requires state:** the journey exists; the country exists in the catalogue
   - **Side effects:** **the applicant's checklist is created** — automatically, once, after this request's transaction commits. **The journey response says nothing about it.** Nothing happens if the country has no active default template, and that is not an error
   - *Failure — `JOURNEYS_COUNTRY_NOT_FOUND`:* inline field error on the country picker
2. **Applicant detail screen → Checklist panel** — show what is now outstanding →
   `GET /api/v1/checklists/?applicant=<applicant_id>` (`checklists.checklist.list`)
   - **Requires state:** none
   - **Side effects:** none
   - *Empty result:* **do not render "this applicant has no requirements"** — it is indistinguishable from a country nobody has set up. Either retry once (inheritance is asynchronous), or show "no requirement list has been authored for this destination yet" and, for an Admin, link to flow 1

> There is no "create checklist" button in this flow, deliberately. A second, explicit way to do the
> same thing would let the two disagree.

## Flow: Work an applicant's list to completion

- **Actor:** Admin or Lead Manager
- **Goal:** Collect what is missing and close the list out
- **Entry point:** Applicant detail screen → Checklist panel

**Steps**

1. **Checklist detail screen** — open the list →
   `GET /api/v1/checklists/<checklist_id>/` (`checklists.checklist.read`)
   - **Requires state:** none
   - **Side effects:** none
2. **Checklist detail screen** — upload the document the applicant handed over →
   `POST /api/v1/files/` (`uploaded_files.file.upload`) with `applicant` or `journey` as the owner **(cross-app: `uploaded_files`)**
   - **Requires state:** the owner record exists
   - **Side effects:** a new file record. It is **not** attached to any checklist item yet
3. **Checklist detail screen** — tick the matching item, citing the file →
   `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` (`checklists.item.status`)
   - **Requires state:** the checklist is `draft` or `active`; the file belongs to this checklist's journey or applicant
   - **Side effects:** the item's completion stamps are set; the checklist's `progress` counts move. **The response is the item and carries no `progress`** — either re-read `GET /api/v1/checklists/<checklist_id>/` or recompute the counts client-side from the items already on screen
   - *Failure — `CHECKLISTS_EVIDENCE_NOT_ALLOWED`:* the file was uploaded against a different applicant. Inline error on the file picker; scope the picker to this applicant's files so it cannot happen
   - *Failure — `CHECKLISTS_INVALID_TRANSITION`:* the checklist is completed. Offer "reopen and edit"
4. **Checklist detail screen** — declare the work finished →
   `POST /api/v1/checklists/<checklist_id>/complete/` (`checklists.checklist.complete`)
   - **Requires state:** every required item is `completed`, `waived`, or `not_applicable`. `progress.required_resolved == progress.required_total` is the exact precondition — **disable the button until then rather than letting the call fail**
   - **Side effects:** the checklist is stamped complete; item edits are refused until it is reopened
   - *Failure — `CHECKLISTS_REQUIRED_ITEMS_PENDING`:* scroll to and highlight each item in `details.items`. Do not show a generic toast — the response names exactly what is left

## Flow: A requirement that cannot be met

- **Actor:** Admin or Lead Manager
- **Goal:** Record honestly that a requirement is stuck or does not apply, without falsely completing it
- **Entry point:** Checklist detail screen

**Steps**

1. **Checklist detail screen** — flag the item as blocked, with the reason →
   `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` (`checklists.item.status`) with `{"status": "blocked", "status_note": "..."}`
   - **Requires state:** the checklist is `draft` or `active`
   - **Side effects:** `progress.blocked` increases. **A blocked item still counts as outstanding** and still prevents completion — surface it as a warning, not a resolution
   - *Failure — `CHECKLISTS_STATUS_NOTE_REQUIRED`:* the note field is mandatory here. Make it a required input on the blocked/waived option, not an optional one the user discovers by failing
2. **Checklist detail screen** — later, resolve it or waive it →
   `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` (`checklists.item.status`) with `completed`, or `waived` plus a note
   - **Requires state:** as above
   - **Side effects:** the item becomes resolved; completion may now be possible

## Flow: Find destinations nobody has set up

- **Actor:** Admin
- **Goal:** Catch applicants whose country has no requirement list — the silent failure mode of automatic inheritance
- **Entry point:** Checklist worklist screen → "Awaiting setup" view

**Steps**

1. **Checklist worklist screen** — list journeys with a country and no checklist →
   `GET /api/v1/checklists/?journey_missing_checklist=true` (`checklists.checklist.list`)
   - **Requires state:** none
   - **Side effects:** none
   - **Note:** the rows are **journeys, not checklists** — each `id` is a journey id, and there is no checklist to link to
2. For each distinct country in that list, run **flow 1**
3. **Journey detail screen** — cover the applicants already waiting: re-save each journey with the same country →
   `PATCH /api/v1/journeys/<journey_id>/` (`applicant_journeys.journey.update`) **(cross-app: `applicant_journeys`)**
   - **Requires state:** the country now has an active default template
   - **Side effects:** inheritance fires as in flow 2
   - **Note:** the backend has a bulk command for this (`apply_country_checklists`), but **no endpoint exposes it**. A frontend must either re-save each journey or ask an operator

## Flow: Start an applicant's list over

- **Actor:** Admin or Lead Manager
- **Goal:** Replace a checklist that no longer reflects the applicant's situation
- **Entry point:** Checklist detail screen

**Steps**

1. **Checklist detail screen** — archive the current list with a reason →
   `POST /api/v1/checklists/<checklist_id>/archive/` (`checklists.checklist.archive`)
   - **Requires state:** the checklist is not already archived
   - **Side effects:** it leaves active work, refuses every edit, **and stops blocking a fresh copy of the same template**
   - *Failure — `CHECKLISTS_ARCHIVE_REASON_REQUIRED`:* the reason is mandatory. Require it in the dialog
2. **Checklist detail screen** — apply the country's current list again →
   `POST /api/v1/checklists/` (`checklists.checklist.create`) with `{journey, template}`
   - **Requires state:** the template is `active` and has at least one active requirement; no non-archived checklist from it exists on this journey
   - **Side effects:** a fresh copy, reflecting the template **as it stands now** — this is how an applicant picks up requirements added since they first inherited theirs
   - *Failure — `CHECKLISTS_TEMPLATE_ALREADY_APPLIED`:* step 1 was skipped or failed
   - **Note:** archived checklists remain in `GET /api/v1/checklists/` results. Filter with `?status=active` or the applicant panel will show both

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `checklists.template.list` | `GET /api/v1/checklists/templates/` | Author a destination country's requirement list | Also the template picker in "Start an applicant's list over" |
| `checklists.template.create` | `POST /api/v1/checklists/templates/` | Author a destination country's requirement list | Admin only |
| `checklists.template.read` | `GET /api/v1/checklists/templates/<id>/` | Author a destination country's requirement list | Returns retired requirements too — show them greyed, not hidden |
| `checklists.template.update` | `PATCH /api/v1/checklists/templates/<id>/` | Author a destination country's requirement list | Admin only. Also how a list is retired (`status: inactive`) |
| `checklists.template_item.create` | `POST /api/v1/checklists/templates/<id>/items/` | Author a destination country's requirement list | Admin only |
| `checklists.template_item.update` | `PATCH /api/v1/checklists/templates/<id>/items/<item_id>/` | Author a destination country's requirement list | Admin only. **There is no delete** — retire with `is_active: false` |
| `checklists.checklist.list` | `GET /api/v1/checklists/` | An applicant receives their checklist; Find destinations nobody has set up | One endpoint, two response shapes — `?journey_missing_checklist=true` returns journeys |
| `checklists.checklist.create` | `POST /api/v1/checklists/` | Start an applicant's list over | The manual override. **The normal path is flow 2, which calls no checklist endpoint at all** |
| `checklists.checklist.read` | `GET /api/v1/checklists/<id>/` | Work an applicant's list to completion | The only shape carrying `items` |
| `checklists.checklist.update` | `PATCH /api/v1/checklists/<id>/` | — | `unused by flow — title, owner, due date, and notes are inline edits on the checklist detail screen, not a journey of their own` |
| `checklists.checklist.activate` | `POST /api/v1/checklists/<id>/activate/` | — | `unused by flow — only a blank hand-built checklist is ever a draft; inherited and template-applied ones arrive active` |
| `checklists.checklist.complete` | `POST /api/v1/checklists/<id>/complete/` | Work an applicant's list to completion | Disable the button until `required_resolved == required_total` |
| `checklists.checklist.reopen` | `POST /api/v1/checklists/<id>/reopen/` | Work an applicant's list to completion | The recovery path from the `CHECKLISTS_INVALID_TRANSITION` failure in step 3 |
| `checklists.checklist.archive` | `POST /api/v1/checklists/<id>/archive/` | Start an applicant's list over | |
| `checklists.checklist.restore` | `POST /api/v1/checklists/<id>/restore/` | — | `unused by flow — undo for an archive done in error; a confirmation-toast action, not a journey.` **Restore is not a reopen** — it returns the checklist to the exact status it was archived in, so a completed one comes back completed |
| `checklists.item.create` | `POST /api/v1/checklists/<id>/items/` | — | `unused by flow — the one-off requirement an institution asks of a single applicant; an inline "add item" on the checklist detail screen` |
| `checklists.item.update` | `PATCH /api/v1/checklists/<id>/items/<item_id>/` | — | `unused by flow — inline edit of an item's label, owner, or due date. Status is NOT editable here` |
| `checklists.item.status` | `POST /api/v1/checklists/<id>/items/<item_id>/status/` | Work an applicant's list to completion; A requirement that cannot be met | The most-called endpoint in the module |

## Cross-app dependencies

- **This app references (outbound):**
  - `institutions.country.list` — the country picker when authoring a template
  - `applicant_journeys.journey.update` — **the trigger for automatic inheritance.** The most important outbound reference in this file, and the only one whose effect is invisible in its own response
  - `uploaded_files.file.upload` — evidence that a requirement was met
  - `uploaded_files.file.list` — scoping the evidence picker to this applicant's files, so `CHECKLISTS_EVIDENCE_NOT_ALLOWED` never reaches a user
- **Referenced by other apps (inbound):** none yet. No other app's flow file calls a `checklists.*` endpoint. The natural future one is an applicant-file overview that shows outstanding requirements alongside documents and offers.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.
