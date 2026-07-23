# FLOWS — Applicant Journeys

**Owner app:** `applicant_journeys`
**Updated:** 2026-07-23
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/applicant_journeys.txt` to the callable endpoints in
`backend/applicant_journeys/docs/INTEGRATION.md`. Authored and updated by the backend author in the
same commit as any endpoint change (CLAUDE.md §36).

Screen names below are quoted from `concepts/applicant_journeys.txt` → `UI screens & wireframe notes`.

---

## Flow: Record a new study objective

- **Actor:** Admin or Lead Manager
- **Goal:** Capture what an existing client is trying to achieve.
- **Entry point:** Applicant Detail → Journeys panel → "New journey"

**Steps**

1. **Applicant Detail → Journeys panel** — the panel lists what the person is already pursuing →
   `GET /api/v1/journeys/?applicant=<applicant_id>` (`applicant_journeys.journey.list`)
   - **Requires state:** the applicant must exist *(cross-app: `applicants`)*.
   - **Side effects:** none.
   - *Note:* this per-person view is the primary entry point. The standalone Journey List is the secondary one.

2. **New Journey Form** — the user submits a destination and whatever else is known →
   `POST /api/v1/journeys/` (`applicant_journeys.journey.create`)
   - **Requires state:** an existing applicant. Nothing else — only `applicant` is a required field.
   - **Side effects:** a journey is created at stage `planning` with `creation_source: manual`. Refresh the journeys panel.
   - *Failure — `JOURNEYS_APPLICANT_NOT_FOUND`:* the applicant id is wrong or the record was never created. Re-select the person.
   - *Note:* the form must not require a country, level, or intake. A journey often begins as little more than "Australia, sometime next year."

3. **Journey Detail** — redirect to the new journey using the returned `id`.

---

## Flow: Work an objective forward

- **Actor:** Admin or Lead Manager
- **Goal:** Advance a journey as counselling, applications, and decisions progress.
- **Entry point:** Journey List, or Applicant Detail → Journeys panel

**Steps**

1. **Journey List** — the user filters to a phase of work →
   `GET /api/v1/journeys/?stage=<stage>` (`applicant_journeys.journey.list`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* this is the operational worklist — "everything at Offer Stage." There is no free-text search here and no client-controlled ordering; results are always newest first.

2. **Journey Detail** — the page loads →
   `GET /api/v1/journeys/<journey_id>/` (`applicant_journeys.journey.read`)
   - **Requires state:** the journey must exist.
   - **Side effects:** none.
   - *Note:* the header shows the applicant's name, which must link to their file. The journey itself holds no contact details — fetch those from `applicants` if the screen needs them.

3. **Journey Detail** — the user picks a new stage from the dropdown →
   `POST /api/v1/journeys/<journey_id>/stage/` (`applicant_journeys.journey.change_stage`)
   - **Requires state:** the journey must not be completed, closed, or deferred.
   - **Side effects:** stage changes; a history entry appears. **Nothing on the applicant changes.**
   - *Failure — `JOURNEYS_STAGE_NOT_EDITABLE`:* someone closed or deferred it. Refresh and replace the dropdown with a Reopen action.
   - *Note:* the dropdown must offer **only** the six active stages. `Completed`, `Closed`, and `Deferred` are separate buttons, because each needs information a stage pick cannot carry.

4. **Journey Detail** — the user corrects the objective as it firms up →
   `PATCH /api/v1/journeys/<journey_id>/` (`applicant_journeys.journey.update`)
   - **Requires state:** the journey must exist.
   - **Side effects:** one history entry when something actually moved.
   - *Note:* the applicant cannot be changed here. A journey belongs to one person and is never transferred; the edit form must not offer a person picker.

---

## Flow: End an objective

- **Actor:** Admin or Lead Manager
- **Goal:** Record that the journey finished, and how.
- **Entry point:** Journey Detail → "Close"

**Steps**

1. **Close Journey dialog** — the user picks an outcome →
   no call; choosing `Other` reveals a required explanation field.
   - **Requires state:** the journey must not already be terminal or deferred.
   - **Side effects:** none.
   - *Note:* the outcome list is a fixed enum, unlike lead loss reasons which are Admin-configurable. Do not fetch it from an endpoint — there is none.

2. **Close Journey dialog** — the user confirms →
   `POST /api/v1/journeys/<journey_id>/close/` (`applicant_journeys.journey.close`)
   - **Requires state:** the journey must be active.
   - **Side effects:** stage becomes `completed` (for `successful`) or `closed` (everything else); outcome and closure fields populate; a history entry appears. **The applicant's status is untouched.**
   - *Failure — `JOURNEYS_OUTCOME_DETAIL_REQUIRED`:* inline error on the explanation field.
   - *Failure — `JOURNEYS_STAGE_NOT_EDITABLE`:* someone already ended it. Refresh and show the current state.
   - *Note:* report how a journey ended by reading `outcome`, never by reading `stage` — `closed` covers five different outcomes.

3. **Journey Detail** — the page now shows the closed state and offers Reopen as the primary action.
   - *Note:* if this was the person's last open journey, the UI may prompt "mark them dormant?" — but that is a client-side suggestion. The server does nothing automatically, and the prompt must call the applicant status endpoint explicitly *(cross-app: `applicants`)*.

---

## Flow: Pause and resume an objective

- **Actor:** Admin or Lead Manager
- **Goal:** Reflect that the applicant intends to continue, but not on the current timeline.
- **Entry point:** Journey Detail → "Defer"

**Steps**

1. **Defer Journey dialog** — the user names the intake being deferred to, with an optional reason →
   `POST /api/v1/journeys/<journey_id>/defer/` (`applicant_journeys.journey.defer`)
   - **Requires state:** the journey must not already be terminal or deferred.
   - **Side effects:** stage becomes `deferred`; the deferment fields populate; `stage_before_terminal` remembers where it was. `outcome` stays **empty**.
   - *Failure — `JOURNEYS_DEFER_INTAKE_REQUIRED`:* inline error on the intake field.
   - *Note:* deferment is **not** an outcome and ends nothing. The UI must not present Defer as a way to close a journey, and reports must not count deferred journeys as finished.

2. **Journey Detail** — later, work restarts →
   `POST /api/v1/journeys/<journey_id>/reopen/` (`applicant_journeys.journey.reopen`)
   - **Requires state:** the journey must currently be completed, closed, or deferred.
   - **Side effects:** stage returns to an active value; all nine closure and deferment fields clear; a history entry appears.
   - *Failure — `JOURNEYS_JOURNEY_NOT_TERMINAL`:* someone resumed it first. Refresh and hide the button.
   - *Note:* one Reopen action serves all three terminal states. Reopening a **completed** journey does not undo that it was completed — the closure stays in the history, and the UI should keep showing it.

---

## Flow: Review a journey's history

- **Actor:** Admin or Lead Manager
- **Goal:** Understand how the objective reached its current state.
- **Entry point:** Journey Detail → History panel

**Steps**

1. **Journey Detail → History panel** — the panel loads →
   `GET /api/v1/journeys/<journey_id>/history/` (`applicant_journeys.journey.list_history`) **(cross-app: `audit`)**
   - **Requires state:** the journey must exist.
   - **Side effects:** none.
   - *Note:* entries originate in the central `audit` log. Render `summary` as the primary label and `changes` as a from→to line where present.
   - *Note:* closure and deferment **reasons** are stored on the journey, not in the history entry. A complete picture reads both the detail record and the timeline.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `applicant_journeys.journey.list` | `GET /api/v1/journeys/` | Record a new objective; Work an objective forward | Serves both the per-person panel and the worklist |
| `applicant_journeys.journey.create` | `POST /api/v1/journeys/` | Record a new study objective | Open to Lead Managers, unlike applicant creation |
| `applicant_journeys.journey.read` | `GET /api/v1/journeys/<journey_id>/` | Work an objective forward | |
| `applicant_journeys.journey.update` | `PATCH /api/v1/journeys/<journey_id>/` | Work an objective forward | Applicant is immutable |
| `applicant_journeys.journey.change_stage` | `POST /api/v1/journeys/<journey_id>/stage/` | Work an objective forward | Active stages only |
| `applicant_journeys.journey.defer` | `POST /api/v1/journeys/<journey_id>/defer/` | Pause and resume an objective | Not an outcome |
| `applicant_journeys.journey.close` | `POST /api/v1/journeys/<journey_id>/close/` | End an objective | Outcome mandatory |
| `applicant_journeys.journey.reopen` | `POST /api/v1/journeys/<journey_id>/reopen/` | Pause and resume an objective | Serves all three terminal states |
| `applicant_journeys.journey.list_history` | `GET /api/v1/journeys/<journey_id>/history/` | Review a journey's history | Backed by `audit` |

## Cross-app dependencies

- **This app references (outbound):** `applicants.applicant.read` and `applicants.applicant.list` to pick and label the person a journey belongs to; `applicants.applicant.change_status` as an optional prompt after closing the last open journey; the history endpoint is served from the `audit` module's event log. All flows require a session from `authenticate.session.login`.
- **Referenced by other apps (inbound):** `concepts/applicants_flows.md` — the Journeys panel on Applicant Detail calls `journey.list` and `journey.create`. `concepts/leads_flows.md` — the conversion flow produces a journey and links to it. `concepts/project_flows.md` — the end-to-end enquiry-to-objective journey.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update **every** referencing flow in the same commit (the CLAUDE.md §36 ripple rule).

## Open questions

- **Is `Visa Stage` right for V1?** Visa case management is explicitly out of scope at the project level, so the stage records only that a visa step is underway. It may be better named as a general post-offer phase.
- **No offer records.** A journey reaching `Offer Stage` says nothing about which offers exist, their conditions, or their deadlines. The `offers` module is not built, so that panel cannot be wireframed yet.
- **No institution picker.** `target_institution_name` and `target_program_name` are free-text inputs with no autocomplete, because there is no institution catalogue. Two staff will spell the same university differently and nothing prevents it.
- **No intake picker** either — `preferred_intake` and `deferred_to_intake` are free text with no date semantics.
- **No priority or target date**, so the worklist can only be ordered newest-first. Sorting by urgency is not possible.
- **No flow prevents two open journeys for the same country and intake.** V1 allows it; whether the UI should warn is undecided.
- **Whether closing the last open journey should prompt a status change on the applicant is undecided.** The server does nothing; any prompt is purely a client-side convention.
