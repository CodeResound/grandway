# FLOWS — Applicants

**Owner app:** `applicants`
**Updated:** 2026-07-23
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/applicants.txt` to the callable endpoints in `backend/applicants/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

Screen names below are quoted from `concepts/applicants.txt` → `UI screens & wireframe notes`.

---

## Flow: Create an applicant directly

- **Actor:** Admin only
- **Goal:** Record a person who is already committed, with no preceding enquiry.
- **Entry point:** Applicant List → "New applicant"

**Steps**

1. **Applicant List** — the Admin opens the create form →
   no call; the "New applicant" action is visible to Admins only.
   - **Requires state:** an authenticated Admin.
   - **Side effects:** none.
   - *Failure — `APPLICANTS_ACTOR_FORBIDDEN`:* a Lead Manager reached this screen. Hide the action entirely for non-Admins rather than showing a disabled button.

2. **New Applicant Form** — the Admin submits name, at least one contact number, and whatever else is known →
   `POST /api/v1/applicants/` (`applicants.applicant.create`)
   - **Requires state:** an authenticated Admin. No other resource needs to exist.
   - **Side effects:** the applicant is created at status `active` with `creation_source: direct_admin`; one history entry appears. Refresh the Applicant List.
   - *Failure — `APPLICANTS_CONTACT_REQUIRED` or 400 on `contact_numbers`:* inline error on the contact-number repeater; at least one row is mandatory.
   - *Failure — `APPLICANTS_PASSPORT_EXPIRY_INVALID`:* inline error on the passport expiry field — the two dates were likely transposed.
   - *Failure — 400 on `addresses`:* two addresses of the same type were sent; the form must offer at most one permanent and one current.

3. **Applicant Detail** — redirect to the new file using the returned `id`.

4. **Applicant Detail → Journeys panel** — prompt the user to record what the person is actually trying to do →
   `POST /api/v1/journeys/` (`applicant_journeys.journey.create`) **(cross-app: `applicant_journeys`)**
   - **Requires state:** the applicant must exist.
   - **Side effects:** a journey is created at stage `planning`. Refresh the journeys panel.
   - *Note:* an applicant with no journey has no objective. This step is optional in the API but should be strongly prompted in the UI.

---

## Flow: Complete a file that arrived from conversion

- **Actor:** Admin or Lead Manager
- **Goal:** Fill in the identity detail a lead never carried.
- **Entry point:** Applicant Detail, reached from the converted lead

**Steps**

1. **Applicant Detail** — the page loads →
   `GET /api/v1/applicants/<applicant_id>/` (`applicants.applicant.read`)
   - **Requires state:** the applicant must exist.
   - **Side effects:** none.
   - *Note:* `creation_source` reads `lead_conversion` and `originating_lead_id` is populated. Render a link back to the lead — the header is the natural place for it.

2. **Edit Applicant Form** — the user adds date of birth, passport, addresses, family, and emergency contacts →
   `PATCH /api/v1/applicants/<applicant_id>/` (`applicants.applicant.update`)
   - **Requires state:** the applicant must exist.
   - **Side effects:** one history entry per section actually changed. Refresh the detail panels.
   - *Failure — `APPLICANTS_PASSPORT_EXPIRY_INVALID`:* inline error on the expiry field.
   - *Note:* conversion copies only name, email, contact numbers, and address. Everything else is blank by design and the form should make that visible rather than looking complete.

3. **Applicant Detail → Journeys panel** — review the seeded journey →
   `GET /api/v1/journeys/?applicant=<applicant_id>` (`applicant_journeys.journey.list`) **(cross-app: `applicant_journeys`)**
   - **Requires state:** the applicant must exist.
   - **Side effects:** none.
   - *Note:* if the originating lead named more than one country, the seeded journey has a **blank** `target_country`. Surface that as an incomplete-journey prompt rather than letting it sit empty.

---

## Flow: Maintain a file over time

- **Actor:** Admin or Lead Manager
- **Goal:** Keep contact details, addresses, and passport current.
- **Entry point:** Applicant List → search

**Steps**

1. **Applicant List** — the user searches by name in either script →
   `GET /api/v1/applicants/?search=<query>` (`applicants.applicant.list`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* one search box matches Devanagari, Roman, and romanized forms simultaneously. Do not build separate script-specific fields.

2. **Applicant Detail** — the user opens the file →
   `GET /api/v1/applicants/<applicant_id>/` (`applicants.applicant.read`)
   - **Requires state:** the applicant must exist.
   - **Side effects:** none.
   - *Failure — `APPLICANTS_APPLICANT_NOT_FOUND`:* a genuine not-found state. Unlike leads, this never means "not yours" — every lead actor sees every applicant.

3. **Edit Applicant Form** — the user adds a second phone number →
   `PATCH /api/v1/applicants/<applicant_id>/` (`applicants.applicant.update`)
   - **Requires state:** the applicant must exist.
   - **Side effects:** the contact set is replaced; one history entry appears.
   - *Note:* **the form must submit the complete list**, not just the new number. Sending one entry deletes the others. The same applies to addresses, family members, and emergency contacts.

---

## Flow: Wind a file down and revive it

- **Actor:** Admin or Lead Manager
- **Goal:** Reflect that the consultancy is no longer actively working with someone, without losing anything.
- **Entry point:** Applicant Detail → status control in the header

**Steps**

1. **Applicant Detail** — the user marks the person dormant →
   `POST /api/v1/applicants/<applicant_id>/status/` (`applicants.applicant.change_status`)
   - **Requires state:** the applicant must exist. No journey state is consulted.
   - **Side effects:** status changes; one history entry appears. **Nothing else changes** — open journeys stay open.
   - *Note:* status is changed from a dedicated control, never by editing a field on the edit form.

2. **Applicant Detail** — later, the user archives the file →
   `POST /api/v1/applicants/<applicant_id>/status/` (`applicants.applicant.change_status`)
   - **Requires state:** the applicant must exist.
   - **Side effects:** status becomes `archived`. The record is not hidden or deleted.
   - *Note:* archived applicants still appear in unfiltered lists and search results. If the UI wants them out of the default view it must filter on `status` itself.

3. **Applicant Detail** — the person returns and the file is reactivated →
   `POST /api/v1/applicants/<applicant_id>/status/` (`applicants.applicant.change_status`)
   - **Requires state:** the applicant must exist.
   - **Side effects:** status returns to `active`. Nothing was ever destroyed.
   - *Note:* if their journeys should also resume, reopen those separately — archival never closed them.

---

## Flow: Review what changed on a file

- **Actor:** Admin or Lead Manager
- **Goal:** Understand how the record reached its current state.
- **Entry point:** Applicant Detail → History panel

**Steps**

1. **Applicant Detail → History panel** — the panel loads →
   `GET /api/v1/applicants/<applicant_id>/history/` (`applicants.applicant.list_history`) **(cross-app: `audit`)**
   - **Requires state:** the applicant must exist.
   - **Side effects:** none.
   - *Note:* entries originate in the central `audit` log; this endpoint is a scoped view of it. Render `summary` as the primary label, and `changes` as a from→to detail line where present.
   - *Note:* nested-collection events carry only a **count** in `metadata` — no passport numbers, no addresses, no family names. The history answers "what kind of thing changed and when," never "what was it before." Do not build a diff viewer expecting old values.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `applicants.applicant.list` | `GET /api/v1/applicants/` | Maintain a file over time | Also the search surface |
| `applicants.applicant.create` | `POST /api/v1/applicants/` | Create an applicant directly | Admin only |
| `applicants.applicant.read` | `GET /api/v1/applicants/<applicant_id>/` | Complete a file; Maintain a file | |
| `applicants.applicant.update` | `PATCH /api/v1/applicants/<applicant_id>/` | Complete a file; Maintain a file | Collections replace wholesale |
| `applicants.applicant.change_status` | `POST /api/v1/applicants/<applicant_id>/status/` | Wind a file down and revive it | Never triggered by journey activity |
| `applicants.applicant.list_history` | `GET /api/v1/applicants/<applicant_id>/history/` | Review what changed on a file | Backed by `audit` |

## Cross-app dependencies

- **This app references (outbound):** `applicant_journeys.journey.create` and `applicant_journeys.journey.list` from the Journeys panel on Applicant Detail; `applicants.applicant.list_history` is served from the `audit` module's event log, which every mutating endpoint here writes to. All flows require a session from `authenticate.session.login`.
- **Referenced by other apps (inbound):** `concepts/leads_flows.md` — the "Convert a lead into a client" flow calls `applicants.applicant.read` after conversion. `concepts/applicant_journeys_flows.md` — several flows call `applicants.applicant.list` and `.read` to pick the person a journey belongs to. `concepts/project_flows.md` — the end-to-end enquiry-to-objective journey.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update **every** referencing flow in the same commit (the CLAUDE.md §36 ripple rule).

## Open questions

- **No flow covers duplicate applicants.** Nothing prevents two records for the same person, and there is no merge endpoint. A UI could warn on a near-name match at create time, but the backend offers no support for detecting or resolving it.
- **No photograph flow.** `concepts/applicants.txt` lists a photograph; no file handling exists in this module. Do not wireframe an avatar upload.
- **No education or test-score panels.** Both modules are specified in `concepts/education.txt` and `concepts/test_scores.txt` but not built, so the Applicant Detail page has no academic or test sections yet.
- **Whether passport and date of birth should be Admin-only is unresolved.** Today any Lead Manager reads and edits them, so the UI must not imply a restriction that does not exist.
- **No flow for linking a directly created applicant to a lead discovered later.** `concepts/applicants.txt` mentions an "approved correction process" for this; no endpoint supports it.
