# FLOWS — Leads

**Owner app:** `leads`
**Updated:** 2026-07-23
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/leads.txt` to the callable endpoints in `backend/leads/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **Screen names are proposed, not sourced.** `concepts/leads.txt` has no
> `UI screens & wireframe notes` section, so the screen names below were derived from its
> feature descriptions rather than quoted from it. Treat them as a starting vocabulary and
> reconcile them into `concepts/leads.txt` when that section is written — see Open questions.

---

## Flow: Record a new enquiry

- **Actor:** Lead Manager (an Admin may also do this)
- **Goal:** Capture a person who has just contacted the consultancy, so follow-up can begin.
- **Entry point:** Lead List → "New lead"

**Steps**

1. **New Lead Form** — the form loads and populates the source picker →
   `GET /api/v1/leads/sources/` (`leads.source.list`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Failure — empty array:* no sources are configured. A Lead Manager cannot resolve this — block submission and show "Ask an Admin to configure lead sources."
   - *Failure — `LEADS_ACTOR_FORBIDDEN`:* the signed-in account is a Superadmin. This module is not available to it at all; hide Leads from the navigation for that authority.

2. **New Lead Form** — the user picks a source flagged `requires_detail` →
   no call; the form reveals a required "Please specify" field bound to `source_detail`.
   - **Requires state:** the source list from step 1.
   - **Side effects:** none.

3. **New Lead Form** — the user submits name, at least one contact number, and optionally a study interest →
   `POST /api/v1/leads/` (`leads.lead.create`)
   - **Requires state:** at least one active lead source must exist. The caller becomes the lead's permanent owner.
   - **Side effects:** the lead is created at stage `new`; one history entry (`lead_created`) appears. Refresh the Lead List.
   - *Failure — `LEADS_SOURCE_DETAIL_REQUIRED`:* inline field error under "Please specify."
   - *Failure — `LEADS_CONTACT_REQUIRED` or 400 on `contact_numbers`:* inline error on the contact-number repeater; at least one row is mandatory.
   - *Failure — `LEADS_SOURCE_INACTIVE`:* the source was retired while the form was open. Re-fetch the source list and ask the user to re-pick.

4. **Lead Detail** — redirect to the newly created lead using the returned `id`.

---

## Flow: Work a lead through follow-up

- **Actor:** Lead Manager (an Admin may also do this)
- **Goal:** Move a lead along as contact is attempted, made, and counselling happens.
- **Entry point:** Lead List → Lead Detail

**Steps**

1. **Lead List** — the user filters to their active work →
   `GET /api/v1/leads/?stage=new` (`leads.lead.list`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* a Lead Manager sees only leads they created; an Admin sees all. The same call serves both — no separate "all leads" endpoint.
   - *Note:* the same endpoint's `?search=` matches the name in either script, the email, and **any** of the lead's contact numbers. Label the box "Search name, phone, or email" — a lead is very often a number in a call log before anyone has agreed how to spell the name.
   - *Note:* a searched list is **relevance-ordered** (exact name match first), not newest-first. Every other list here is newest-first. Do not re-sort a searched list client-side.
   - *Note:* ranking never widens scope. A Lead Manager's search reorders their own leads and can never surface another manager's, so the result count is still owner-scoped.

2. **Lead Detail** — the page loads →
   `GET /api/v1/leads/<lead_id>/` (`leads.lead.read`)
   - **Requires state:** the lead must be in the caller's scope.
   - **Side effects:** none.
   - *Failure — `LEADS_LEAD_NOT_FOUND`:* full-page not-found state. Do **not** word it as "you don't have access" — the API deliberately does not distinguish missing from not-yours, and the UI must not imply otherwise.

3. **Lead Detail** — the user picks a new stage from the dropdown →
   `POST /api/v1/leads/<lead_id>/stage/` (`leads.lead.change_stage`)
   - **Requires state:** the lead must not be `lost` or `converted`.
   - **Side effects:** stage changes; a `lead_stage_changed` entry appears in the History panel. Refresh both.
   - *Failure — `LEADS_STAGE_NOT_EDITABLE`:* the lead is terminal. Replace the dropdown with a "Reopen" button.
   - *Note:* the dropdown must offer only the six active stages. `Lost` and `Converted` are separate deliberate actions, not dropdown options.

4. **Lead Detail → Record Follow-up dialog** — the user logs a call they just made, optionally with a note and a stage change →
   `POST /api/v1/leads/<lead_id>/follow-up/` (`leads.lead.record_followup`)
   - **Requires state:** the lead must not be `lost` or `converted`.
   - **Side effects:** `last_followed_up_at`/`_by` update; a `lead_followup_recorded` entry appears, plus `lead_note_added` and `lead_stage_changed` when those fields were sent. Refresh the lead header, Notes panel, and History panel.
   - *Failure — `LEADS_STAGE_NOT_EDITABLE`:* as step 3.
   - *Note:* Grandway does not schedule follow-ups or send reminders — this dialog records that contact already happened. Do not build a "schedule next follow-up" control.

5. **Lead Detail → Notes panel** — the user adds a standalone note →
   `POST /api/v1/leads/<lead_id>/notes/` (`leads.note.create`)
   - **Requires state:** the lead must be in the caller's scope.
   - **Side effects:** the note appears; a `lead_note_added` entry appears in History.
   - *Note:* notes are append-only. Render no edit or delete affordance — those verbs return 405.

---

## Flow: Convert a lead into a client

- **Actor:** Admin only
- **Goal:** Admit the person to the applicant lifecycle, creating their permanent record and first study objective.
- **Entry point:** Lead Detail → "Convert"

**Steps**

1. **Lead Detail** — the Admin reviews the lead, typically once it reaches `Ready for Conversion` →
   `GET /api/v1/leads/<lead_id>/` (`leads.lead.read`)
   - **Requires state:** the lead must be in the caller's scope.
   - **Side effects:** none.
   - *Note:* the "Convert" action is visible to Admins only — hide it for Lead Managers rather than showing a disabled button. `Ready for Conversion` is a signal, not a gate: conversion works from **any** active stage.

2. **Lead Detail** — the Admin confirms →
   `POST /api/v1/leads/<lead_id>/convert/` (`leads.lead.convert`)
   - **Requires state:** Admin authority, and the lead in an active stage.
   - **Side effects:** creates an applicant *(cross-app: `applicants`)* **and** an initial journey *(cross-app: `applicant_journeys`)*, links both to the lead permanently, and moves the lead to its terminal `converted` stage. Two entries appear in the lead's history. Refresh the lead and the Lead List.
   - *Failure — `LEADS_ACTOR_FORBIDDEN`:* the caller is a Lead Manager or Superadmin.
   - *Failure — `LEADS_CONVERSION_NOT_READY`:* the lead is lost. Offer Reopen, then retry.
   - *Failure — `LEADS_LEAD_ALREADY_CONVERTED`:* someone converted it already. Read `converted_applicant_id` off the lead and navigate there — **do not retry**, and do not present this as the user's mistake.

3. **Applicant Detail** — redirect using the returned `applicant_id` →
   `GET /api/v1/applicants/<applicant_id>/` (`applicants.applicant.read`) **(cross-app: `applicants`)**
   - **Requires state:** conversion must have succeeded.
   - **Side effects:** none.
   - *Note:* only name, email, contact numbers, and address were copied. Date of birth, passport, family, and emergency contacts are blank — prompt the user to complete them.

4. **Journey Detail** — review the seeded objective →
   `GET /api/v1/journeys/<journey_id>/` (`applicant_journeys.journey.read`) **(cross-app: `applicant_journeys`)**
   - **Requires state:** conversion must have succeeded.
   - **Side effects:** none.
   - *Note:* if the lead named **more than one** interested country, `target_country` is blank and the full list sits in the journey's `notes`. Surface that as an incomplete-journey prompt. `highest_qualification` and `language_test_status` are also in `notes`, because the `education` and `test_scores` modules do not exist yet.

5. **Lead Detail** — the lead stays readable at `stage: converted`, with `converted_applicant_id` and `converted_journey_id` for navigation.
   - *Note:* conversion deletes nothing. Notes, contact numbers, and the full history all survive.

---

## Flow: Close an enquiry that will not proceed

- **Actor:** Lead Manager (an Admin may close any lead)
- **Goal:** Record that the person is not proceeding, and why.
- **Entry point:** Lead Detail → "Mark as lost"

**Steps**

1. **Mark Lost dialog** — the dialog opens and populates the reason picker →
   `GET /api/v1/leads/loss-reasons/` (`leads.loss_reason.list`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Failure — empty array:* no reasons are configured, and a reason is mandatory. Block the dialog and show "Ask an Admin to configure loss reasons."

2. **Mark Lost dialog** — the user picks a reason flagged `requires_detail` →
   no call; the dialog reveals a required explanation field bound to `detail`.

3. **Mark Lost dialog** — the user confirms →
   `POST /api/v1/leads/<lead_id>/lost/` (`leads.lead.mark_lost`)
   - **Requires state:** at least one active loss reason; the lead must not already be `lost` or `converted`.
   - **Side effects:** stage becomes `lost`; `lost_reason`, `lost_at`, `lost_by`, and `stage_before_loss` populate; a `lead_marked_lost` entry appears. The lead stays in the list — it is not removed or archived.
   - *Failure — `LEADS_LOSS_DETAIL_REQUIRED`:* inline field error on the explanation field.
   - *Failure — `LEADS_LOSS_REASON_INACTIVE`:* the reason was retired mid-dialog. Re-fetch and ask the user to re-pick.
   - *Failure — `LEADS_STAGE_NOT_EDITABLE`:* someone else already closed it. Refresh the lead and show its current state.

4. **Lead Detail** — the page now renders the closed state: reason, explanation, who closed it, when, and the stage it held beforehand. The primary action becomes "Reopen."

---

## Flow: Revive a closed enquiry

- **Actor:** Lead Manager (own leads) or Admin (any lead)
- **Goal:** Bring a lost — or already converted — lead back into active follow-up without erasing what happened.
- **Entry point:** Lead Detail → "Reopen"

**Steps**

1. **Reopen dialog** — the user optionally chooses which active stage to land on (default `follow_up`) →
   `POST /api/v1/leads/<lead_id>/reopen/` (`leads.lead.reopen`)
   - **Requires state:** the lead must currently be `lost` or `converted`.
   - **Side effects:** stage returns to an active value; all five loss fields clear; a `lead_reopened` entry appears. `converted_at`/`converted_by` are **not** cleared.
   - *Failure — `LEADS_LEAD_NOT_LOST`:* the lead is already active — someone reopened it first. Refresh and hide the button.

2. **Lead Detail** — the History panel still shows the original `lead_marked_lost` entry alongside the new `lead_reopened` one.
   - *Note:* reopening never erases history, and reopening a **converted** lead never undoes the conversion. If the lead was converted, keep showing its applicant link after reopening — a second applicant must never be created from it.

---

## Flow: Configure the pickers

- **Actor:** Admin only
- **Goal:** Maintain the lead-source and loss-reason lists the whole team picks from.
- **Entry point:** Settings → Lead Configuration

**Steps**

1. **Lead Configuration** — the page lists both reference sets, including retired entries →
   `GET /api/v1/leads/sources/?include_inactive=true` (`leads.source.list`) and
   `GET /api/v1/leads/loss-reasons/?include_inactive=true` (`leads.loss_reason.list`)
   - **Requires state:** an authenticated Admin or Lead Manager (reads are open to both).
   - **Side effects:** none.
   - *Note:* only this settings screen passes `include_inactive=true`. Every picker elsewhere must omit it so retired entries stay hidden.

2. **Lead Configuration** — the Admin adds an entry →
   `POST /api/v1/leads/sources/` (`leads.source.create`) or
   `POST /api/v1/leads/loss-reasons/` (`leads.loss_reason.create`)
   - **Requires state:** Admin authority.
   - **Side effects:** the entry becomes available in every picker immediately. An audit event is written, but it does **not** appear in any lead's history.
   - *Failure — `LEADS_ACTOR_FORBIDDEN`:* the caller is a Lead Manager or Superadmin. Hide this screen from non-Admins entirely rather than showing a disabled form.
   - *Failure — `LEADS_SOURCE_CODE_TAKEN` / `LEADS_LOSS_REASON_CODE_TAKEN`:* inline error on the code field. The clash may be with a *retired* entry, so suggest checking the retired list.

3. **Lead Configuration** — the Admin retires an entry →
   `PATCH /api/v1/leads/sources/<source_id>/` (`leads.source.update`) or
   `PATCH /api/v1/leads/loss-reasons/<reason_id>/` (`leads.loss_reason.update`) with `is_active: false`
   - **Requires state:** Admin authority; the entry must exist.
   - **Side effects:** the entry disappears from pickers but stays attached to existing leads.
   - *Failure — `LEADS_SOURCE_NOT_FOUND` / `LEADS_LOSS_REASON_NOT_FOUND`:* row-level error; refresh the list.
   - *Note:* there is no delete. The UI must offer "Retire," never "Delete."

---

## Flow: Review a lead's full story

- **Actor:** Lead Manager (own leads) or Admin (any lead)
- **Goal:** Understand how a lead reached its current state.
- **Entry point:** Lead Detail → History panel

**Steps**

1. **Lead Detail → History panel** — the panel loads →
   `GET /api/v1/leads/<lead_id>/history/` (`leads.lead.list_history`) **(cross-app: `audit`)**
   - **Requires state:** the lead must be in the caller's scope.
   - **Side effects:** none.
   - *Note:* entries originate in the central `audit` log; this endpoint is a scoped view of it. Render `summary` as the primary label and `changes` (when present) as a from→to detail line.

2. **Lead Detail → Notes panel** — loaded alongside →
   `GET /api/v1/leads/<lead_id>/notes/` (`leads.note.list`)
   - **Requires state:** the lead must be in the caller's scope.
   - **Side effects:** none.
   - *Note:* note **text** lives only here — history entries record that a note was added, never its contents. A complete activity view needs both panels.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `leads.source.list` | `GET /api/v1/leads/sources/` | Record a new enquiry; Configure the pickers | |
| `leads.source.create` | `POST /api/v1/leads/sources/` | Configure the pickers | Admin only |
| `leads.source.update` | `PATCH /api/v1/leads/sources/<source_id>/` | Configure the pickers | Admin only; retire, never delete |
| `leads.loss_reason.list` | `GET /api/v1/leads/loss-reasons/` | Close an enquiry; Configure the pickers | |
| `leads.loss_reason.create` | `POST /api/v1/leads/loss-reasons/` | Configure the pickers | Admin only |
| `leads.loss_reason.update` | `PATCH /api/v1/leads/loss-reasons/<reason_id>/` | Configure the pickers | Admin only |
| `leads.lead.list` | `GET /api/v1/leads/` | Work a lead through follow-up | Owner-scoped; also the funnel/search surface. Search spans name, email, and phone and returns relevance-ordered results |
| `leads.lead.create` | `POST /api/v1/leads/` | Record a new enquiry | |
| `leads.lead.read` | `GET /api/v1/leads/<lead_id>/` | Work a lead; Close; Revive; Review | |
| `leads.lead.update` | `PATCH /api/v1/leads/<lead_id>/` | — | `unused by flow — correction path (Edit Lead form), not a journey. Same form as create; replaces contact numbers wholesale.` |
| `leads.lead.change_stage` | `POST /api/v1/leads/<lead_id>/stage/` | Work a lead through follow-up | Active stages only |
| `leads.lead.record_followup` | `POST /api/v1/leads/<lead_id>/follow-up/` | Work a lead through follow-up | |
| `leads.lead.mark_lost` | `POST /api/v1/leads/<lead_id>/lost/` | Close an enquiry that will not proceed | |
| `leads.lead.reopen` | `POST /api/v1/leads/<lead_id>/reopen/` | Revive a closed enquiry | |
| `leads.note.list` | `GET /api/v1/leads/<lead_id>/notes/` | Review a lead's full story | |
| `leads.note.create` | `POST /api/v1/leads/<lead_id>/notes/` | Work a lead through follow-up | Also reachable via the follow-up dialog's `note` field |
| `leads.lead.list_history` | `GET /api/v1/leads/<lead_id>/history/` | Review a lead's full story | Backed by `audit` |
| `leads.lead.convert` | `POST /api/v1/leads/<lead_id>/convert/` | Convert a lead into a client | Admin only; idempotent; creates records in two other apps |

## Cross-app dependencies

- **This app references (outbound):** `applicants.applicant.read` and `applicant_journeys.journey.read` in the conversion flow, which creates records in both apps; `leads.lead.list_history` is served from the `audit` module's event log, which every mutating endpoint above writes to. All flows additionally require a session from `authenticate.session.login`.
- **Referenced by other apps (inbound):** `concepts/applicants_flows.md` — the "Complete a file that arrived from conversion" flow begins where this app's conversion flow ends. `concepts/project_flows.md` — the end-to-end enquiry-to-objective journey delegates its lead-side steps to the flows above.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.

## Open questions

- **`concepts/leads.txt` has no `UI screens & wireframe notes` section.** Every screen name in this file (Lead List, Lead Detail, New Lead Form, Mark Lost dialog, Record Follow-up dialog, Reopen dialog, Lead Configuration) is proposed by the backend author. They need to be reconciled into the concept file so the frontend and backend share one vocabulary.
- **Two study-interest fields survive conversion only as prose.** `highest_qualification` and `language_test_status` land in the journey's `notes` because the `education` and `test_scores` modules do not exist. When they ship, conversion should map those fields properly and this flow needs revisiting.
- **A multi-country lead produces an incomplete journey** — `target_country` blank, the list in `notes`. The UI needs an explicit prompt for this; the backend deliberately will not guess.
- **Direct applicant creation is out of scope for this app.** `concepts/leads.txt` mentions an Admin creating an applicant without a lead; that lives in `concepts/applicants_flows.md`.
- **No funnel or dashboard flow is defined.** The lead list supports `stage`, `source`, `search`, and `fiscal_year` filters, which is enough to build a funnel view, but reporting belongs to the `dashboards` app and no flow claims it yet.
- **Whether an Admin should see a Lead Manager filter on the lead list is undecided.** An Admin sees all leads, but there is no `created_by`/owner query parameter, so an Admin cannot currently narrow the list to one Lead Manager's work. If that is wanted, it needs a new filter on `leads.lead.list`.
- **A lead cannot be filtered by country of interest.** `study_interest.interested_countries` is shown on Lead Detail but is not a filter, so "every lead interested in Australia" is not answerable — the values live in a JSON array whose containment lookup is PostgreSQL-only and could not be covered by the test suite. The equivalent filter exists one stage later, on `applicants.applicant.list` **(cross-app: `applicants`)**. A UI that offers a destination filter on the lead funnel would be promising something the API does not do.
