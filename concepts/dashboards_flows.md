# FLOWS — Dashboards

**Owner app:** `dashboards`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/dashboards.txt` to the callable endpoints in `backend/dashboards/docs/INTEGRATION.md`.

> **Every flow here ends in another app.** That is not incidental — this module owns no data and
> accepts no writes, so a flow that stayed inside it would be a flow where nobody did anything.
> The dashboard's whole job is to get staff to the next action, so each flow below starts on the
> dashboard and finishes with a `(cross-app: …)` step where the work actually happens.

---

## Flow: Morning triage

- **Actor:** Admin or Lead Manager
- **Goal:** See what is late right now and clear it.
- **Entry point:** Dashboard home → Alert strip

**Steps**

1. **Dashboard home → Alert strip** — the page loads →
   `GET /api/v1/dashboard/summary/` (`dashboards.summary.read`)
   - **Requires state:** an authenticated Admin or Lead Manager. Nothing else — every count is `0` on an empty system.
   - **Side effects:** none. This module writes nothing, ever, including no audit event for the read.
   - *Note:* render each alert as a number **plus a destination**. A count with nowhere to go is the one thing `concepts/dashboards.txt` explicitly asks this app not to produce.
   - *Failure — `DASHBOARDS_ACTOR_FORBIDDEN` (403):* the caller is a Superadmin. Do not render an empty dashboard — hide the navigation entry entirely, because no section will ever answer for this authority.

2. **Dashboard home → Today's work** — the panel loads, in parallel with the others →
   `GET /api/v1/dashboard/today/` (`dashboards.today.read`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* **load the eight sections as eight independent requests.** They are separate endpoints precisely so a slow panel cannot block the page; a client that awaits all eight before painting discards the only reason they were split.
   - *Note:* `overdue_checklist_items` and `due_soon_checklist_items` are disjoint, so their totals may be summed. Nothing else on this page may be.
   - *Note:* each worklist returns at most 10 rows with an accurate `total`. Show `total`; use `has_more` to decide whether to show a "see all" link rather than comparing lengths yourself.

3. **Today's work → an overdue row** — the user clicks a checklist item →
   `GET /api/v1/checklists/<checklist_id>/` (`checklists.checklist.read`) **(cross-app: `checklists`)**
   - **Requires state:** the `checklist_id` from the row. Every row carries `checklist_id`, `journey_id`, and `applicant_id`, so no lookup call is needed to navigate.
   - **Side effects:** none.

4. **Checklist detail** — the user resolves or reassigns the requirement →
   `POST /api/v1/checklists/<checklist_id>/items/<item_id>/status/` (`checklists.item.status`) **(cross-app: `checklists`)**
   - **Requires state:** the checklist must be `draft` or `active`. A completed one must be reopened first.
   - **Side effects:** the item's status changes and one audit event is appended — which also makes it appear in the dashboard's own activity feed.
   - *Failure — `CHECKLISTS_STATUS_NOTE_REQUIRED`:* waiving or blocking needs an explanation. Inline field error on the note.

5. **Dashboard home** — the user returns →
   `GET /api/v1/dashboard/summary/` (`dashboards.summary.read`)
   - **Requires state:** none beyond the session.
   - **Side effects:** none.
   - *Note:* the count has already dropped. Nothing here caches, so a refetch always reflects the change — but there is also no push, no polling contract, and no ETag, so **the client decides when to refetch**.

---

## Flow: Unblock a stalled file

- **Actor:** Admin
- **Goal:** Find work that is stuck for a reason nobody has noticed, and remove the cause.
- **Entry point:** Dashboard home → Blockers and risk

**Steps**

1. **Blockers and risk** — the panel loads →
   `GET /api/v1/dashboard/blockers/` (`dashboards.blockers.read`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* render the five groups **separately, by cause**. They call for five different people to act, and a single list sorted by urgency would obscure which is which.

2. **Blockers → "journeys without a checklist"** — the user reads a row →
   no call; the row carries `country_id`, `country_name`, `applicant_id`, and `journey_id`.
   - **Requires state:** none.
   - **Side effects:** none.
   - *Note:* this group is the safety net behind automatic checklist inheritance. The journey named a destination, nobody had authored that country's requirements, so **no checklist was created and no error was raised**. This panel is the only place that silence is visible. An empty group is the healthy state, not a missing feature.

3. **Checklist templates** — the user checks whether a template exists →
   `GET /api/v1/checklists/templates/?country=<country_id>` (`checklists.template.list`) **(cross-app: `checklists`)**
   - **Requires state:** the `country_id` from step 2.
   - **Side effects:** none.

4. **Template editor** — the Admin authors and activates the country's list →
   `POST /api/v1/checklists/templates/` (`checklists.template.create`) **(cross-app: `checklists`)**
   - **Requires state:** Admin authority. Template authoring is Admin-only even though checklists themselves are shared.
   - **Side effects:** **future** journeys to that country inherit the list automatically, with no endpoint call. The journeys already in step 2's list do **not** retroactively gain one.
   - *Failure — `CHECKLISTS_DEFAULT_TEMPLATE_EXISTS`:* a default already exists for this country, so the blocker has another cause. Send the user back to step 3.

5. **Checklist workspace** — the Admin applies the new list to each already-affected applicant →
   `POST /api/v1/checklists/` (`checklists.checklist.create`) **(cross-app: `checklists`)**
   - **Requires state:** the `journey_id` from step 2 and the template from step 4.
   - **Side effects:** the applicant gains a checklist; the blocker row disappears on the next dashboard load.
   - *Note:* this step is easy to skip and is the whole point of the flow. Authoring the template fixes the future; only this fixes the people already waiting.

---

## Flow: Rebalance the team

- **Actor:** Admin (a Lead Manager may open the screen, but has nothing to rebalance)
- **Goal:** Find who is carrying too much and move work.
- **Entry point:** Dashboard home → Workload by owner

**Steps**

1. **Workload by owner** — the panel loads →
   `GET /api/v1/dashboard/workload/` (`dashboards.workload.read`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* **branch on `is_scoped_to_caller` before rendering.** `true` means the caller is a Lead Manager and the `leads` list holds only their own row — label the panel "My workload" and drop the rebalancing affordances, which would be dead controls. Do not infer team size from the row count.
   - *Note:* the three lists are **not joinable into one row per person and must not be summed**. Render three tables, not one.
   - *Note:* the `checklist_items` list includes a row with `owner_id: null`, labelled "Unassigned". **Do not filter it out** — it is the most likely work to be missed and the most useful row on the panel.

2. **Workload row → that person's items** — the user clicks a row →
   `GET /api/v1/checklists/?assigned_to=<owner_id>` (`checklists.checklist.list`) **(cross-app: `checklists`)**
   - **Requires state:** the `owner_id` from the row. For the unassigned row there is none, so this link must be disabled or point at an unassigned-work view the API does not currently provide (see Open questions).
   - **Side effects:** none.

3. **Checklist item** — the Admin reassigns it →
   `PATCH /api/v1/checklists/<checklist_id>/items/<item_id>/` (`checklists.item.update`) **(cross-app: `checklists`)**
   - **Requires state:** the checklist must be editable.
   - **Side effects:** the item's assignee changes; both people's workload rows move on the next dashboard load.

---

## Flow: Chase a decision

- **Actor:** Admin or Lead Manager
- **Goal:** Get an answer on an offer whose deadline has passed.
- **Entry point:** Dashboard home → Today's work, or Blockers and risk

**Steps**

1. **Today's work → offers awaiting response** — the panel loads →
   `GET /api/v1/dashboard/today/` (`dashboards.today.read`)
   - **Requires state:** an authenticated Admin or Lead Manager. An offer appears only if it is `issued` **and** carries a `response_deadline`.
   - **Side effects:** none.
   - *Note:* this list holds both already-passed and approaching deadlines. Read `is_response_overdue` on each row to style them differently; do not re-derive it from `response_deadline` in the browser's timezone, because the backend computes it against today in **Nepal**.
   - *Note:* an offer with no deadline set never appears here at all. The list is "offers with a deadline", not "offers awaiting a response".

2. **Offer detail** — the user opens it →
   `GET /api/v1/offers/<offer_id>/` (`offers.offer.read`) **(cross-app: `offers`)**
   - **Requires state:** the `id` from the row.
   - **Side effects:** none.

3. **Decision dialog** — the user records the applicant's answer →
   `POST /api/v1/offers/<offer_id>/decision/` (`offers.offer.record_decision`) **(cross-app: `offers`)**
   - **Requires state:** the offer must be `issued`. A decision is final — there is no reopen.
   - **Side effects:** the offer becomes terminal and leaves this worklist; it enters `dashboards.outcomes.read`'s `offer_decisions` for the period the decision was recorded, **not** the period the offer was created.
   - *Failure — `OFFERS_ACCEPTED_OFFER_EXISTS`:* the journey already has an accepted offer. Blocking dialog naming the existing one.

---

## Flow: Review intake health for a period

- **Actor:** Admin
- **Goal:** Judge whether a channel, or a destination, is producing outcomes.
- **Entry point:** Dashboard home → Filter bar

**Steps**

1. **Filter bar → country picker** — the control populates →
   `GET /api/v1/catalogue/countries/` (`institutions.country.list`) **(cross-app: `institutions`)**
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* never hardcode country codes — the catalogue is data, added by staff without a deployment.

2. **Filter bar** — the user sets a fiscal year and a destination, and every panel refetches →
   `GET /api/v1/dashboard/conversion/?fiscal_year=2081/82&country=<id>` (`dashboards.conversion.read`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* **the four rates are four independent measures, not one funnel.** Each is windowed on its own stage's dates, so a lead that arrived in Ashadh and converted in Shrawan counts toward Ashadh's intake and Shrawan's conversions. Render four figures; **do not draw a funnel chart and do not multiply them together.**
   - *Note:* a `percent` of `null` means the denominator was zero. Render "—", never "0%" — "nobody arrived" and "people arrived and none converted" are different facts and the API distinguishes them deliberately.
   - *Failure — `VALIDATION_ERROR` on `fiscal_year`:* the label was malformed. Inline error on the fiscal-year control; the format is `YYYY/YY`.
   - *Failure — `VALIDATION_ERROR` on `date_to`:* the range runs backwards. Inline error on the end-date control.

3. **Final outcomes** — the user reads what became of that cohort →
   `GET /api/v1/dashboard/outcomes/?fiscal_year=2081/82&country=<id>` (`dashboards.outcomes.read`)
   - **Requires state:** an authenticated Admin or Lead Manager.
   - **Side effects:** none.
   - *Note:* `journey_outcomes` is windowed on **when each journey ended**, while `journeys_completed` on the same payload is windowed on **when it was created**. The two can disagree about the same journey and both be right. Do not present them as parts of one total.

4. **Applicant list** — the user opens the people behind the numbers →
   `GET /api/v1/applicants/?country=<id>` (`applicants.applicant.list`) **(cross-app: `applicants`)**
   - **Requires state:** the country id.
   - **Side effects:** none.
   - *Note:* the dashboard does **not** tell you which query parameters reproduce its filtering on the target list. Its `fiscal_year` maps to the applicant list's `fiscal_year`, and its `country` to `country` — but `due_within_days` and the worklist predicates have no equivalent there, so a drill-down is an approximation, not a guarantee of the same rows.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `dashboards.summary.read` | `GET /api/v1/dashboard/summary/` | Morning triage | The alert strip. Every figure is duplicated in a fuller section |
| `dashboards.today.read` | `GET /api/v1/dashboard/today/` | Morning triage; Chase a decision | Six worklists, 10 rows each |
| `dashboards.pipeline.read` | `GET /api/v1/dashboard/pipeline/` | **No dedicated flow** — it is a read-only panel on Dashboard home with no action behind it. Every count links into another app's list view | Zero-filled maps |
| `dashboards.blockers.read` | `GET /api/v1/dashboard/blockers/` | Unblock a stalled file | Grouped by cause, never merged |
| `dashboards.workload.read` | `GET /api/v1/dashboard/workload/` | Rebalance the team | Branch on `is_scoped_to_caller` |
| `dashboards.conversion.read` | `GET /api/v1/dashboard/conversion/` | Review intake health | Four independent rates, not a funnel |
| `dashboards.outcomes.read` | `GET /api/v1/dashboard/outcomes/` | Review intake health | Two windowing rules in one payload |
| `dashboards.activity.list` | `GET /api/v1/dashboard/activity/` | **No dedicated flow** — a passive change feed at the foot of Dashboard home. The only paginated section, and the only one ignoring every filter but `fiscal_year` | **Admin only** — hide the panel for a Lead Manager, who is refused (403) here exactly as at `audit.event.list`. Not narrowed among those who may read it |

## Cross-app dependencies

- **This app references (outbound):** every flow above ends in another app. `checklists.checklist.read`, `checklists.item.status`, `checklists.item.update`, `checklists.template.list`, `checklists.template.create`, `checklists.checklist.create`, and `checklists.checklist.list` (the largest destination by far); `offers.offer.read` and `offers.offer.record_decision`; `institutions.country.list` for the destination filter; `applicants.applicant.list` for the drill-down. All flows require a session from `authenticate.session.login`.
- **Reads seven apps with no endpoint call.** Every figure on every panel comes from `leads`, `applicants`, `applicant_journeys`, `offers`, `checklists`, `documents`, `uploaded_files`, and `audit` — but a client never calls those modules to render the dashboard. One request per section is all a panel costs.
- **Referenced by other apps (inbound): none.** No other app's flow calls a dashboard endpoint, and none ever should — this module summarises the others and is never a step in their work.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update **every** referencing flow in the same commit (the CLAUDE.md §36 ripple rule).

## Open questions

- **No flow covers appointments or notifications**, because neither module exists. `concepts/dashboards.txt` asks for upcoming appointments, missed appointments, and a pending-alert summary; all three are absent from every response rather than returned as zero. A wireframe must not include those panels.
- **No branch filter exists, and no branch concept exists anywhere in the backend.** The concept file lists it among the useful filters. Building the control would promise a narrowing the API cannot perform.
- **Four filters are accepted but change nothing.** `journey_stage`, `offer_status`, `document_status`, and `checklist_status` are validated and ignored by every section. **Do not render them as active controls** — a user who sets one and sees no change will reasonably conclude the dashboard is broken.
- **The activity feed ignores the filter bar** except for `fiscal_year`. If one filter bar sits above the whole page, that panel must say it is unfiltered or the user will misread it.
- **There is no drill-down contract.** Each row carries the ids needed to navigate, but nothing states which query parameters would reproduce a section's filtering on the target list endpoint. A "see all 47" link is a best-effort approximation, and the count on the destination screen may legitimately differ.
- **Nothing marks which figures were owner-scoped**, except `workload.is_scoped_to_caller`. For a Lead Manager, lead-derived numbers are narrowed and the rest are not, so **an Admin and a Lead Manager see different dashboards at the same URL**. Whether the UI should say so per panel is undecided.
- **No refresh contract.** There is no polling interval, push channel, cache header, or staleness indicator. How often a client refetches is entirely its own decision.
- **Whether different roles need different default layouts is unresolved** — an open question in `concepts/dashboards.txt` that the API does not answer either way. All eight sections are available to both authorities today.
