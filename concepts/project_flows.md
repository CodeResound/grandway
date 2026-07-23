# FLOWS — Project (end-to-end, multi-app)

**Owner:** project-level — no single app
**Updated:** 2026-07-23
**Purpose:** End-to-end journeys that cross more than one app. Each step here **delegates to a named
per-app flow** rather than re-listing its endpoint calls (CLAUDE.md §36.1). If you are looking for the
detail of any single step, follow the reference to that app's flow file.

> **This file exists because no single app owns these journeys.** A flow lives in its owning app's
> file whenever one app's primary resource is being advanced. The journeys below advance a person
> *through* apps — enquiry to client to objective — so they have no natural owner and would be
> misleading if filed under any one of them.

---

## Journey: Enquiry to study objective

The spine of the whole system: a stranger contacts the consultancy and ends up with a tracked,
authoritative study plan.

**Actors:** Lead Manager for stages 1–2, Admin for stage 3, either afterwards.

1. **Record and work the enquiry** → `concepts/leads_flows.md` → *"Record a new enquiry"*, then *"Work a lead through follow-up"*
   - Ends with the lead at `ready_for_conversion` (or any active stage — readiness is a signal, not a gate).
   - The Lead Manager who created the lead owns it exclusively; no colleague can see it.

2. **Decide whether to admit them** — a judgement call with no endpoint. An Admin reviews the lead and its history.

3. **Convert** → `concepts/leads_flows.md` → *"Convert a lead into a client"*
   - The single hinge of this journey. One Admin-only call creates the applicant and the initial journey together, atomically, and can never run twice for the same lead.
   - **Visibility changes here.** Before conversion the record was one Lead Manager's private lead; after it, the applicant and journey are visible to every Admin and Lead Manager. This is the intended transition from "someone's prospect" to "the consultancy's client" — but it will surprise a Lead Manager who expected their work to stay private, and the UI should make the change legible.

4. **Complete the person's file** → `concepts/applicants_flows.md` → *"Complete a file that arrived from conversion"*
   - Conversion carries only name, email, contact numbers, and address. Date of birth, passport, family, and emergency contacts are all still blank.

5. **Complete the objective** → `concepts/applicant_journeys_flows.md` → *"Work an objective forward"*
   - The seeded journey is a starting point, not a plan. If the lead named more than one country it has **no** target country at all.

6. **Run the objective to an outcome** → `concepts/applicant_journeys_flows.md` → *"End an objective"*
   - The journey closes with a recorded outcome. The applicant's status is untouched.

**What survives the whole journey:** the lead record, its notes, and its full history; the originating Lead Manager's attribution via `Lead.created_by`; and the link in both directions between lead, applicant, and journey.

---

## Journey: Direct client, no enquiry

Some people arrive already committed — a walk-in who has done their research, or a partner referral.
Grandway does not require inventing a lead for them after the fact.

**Actors:** Admin for stage 1, either afterwards.

1. **Create the applicant** → `concepts/applicants_flows.md` → *"Create an applicant directly"*
   - Recorded as `creation_source: direct_admin`, with `originating_lead_id` permanently `null`.

2. **Record their objective** → `concepts/applicant_journeys_flows.md` → *"Record a new study objective"*
   - Recorded as `creation_source: manual`.

3. **Run the objective to an outcome** → `concepts/applicant_journeys_flows.md` → *"Work an objective forward"*, then *"End an objective"*

**Difference from the main journey:** no lead exists, so there is no enquiry history, no source attribution, and no originating Lead Manager. Reporting that asks "where do our clients come from" will show these as a separate, sourceless population — which is accurate, not a gap.

---

## Journey: A second objective for an existing client

One person may pursue several countries or intakes over time. The applicant record is created once;
journeys accumulate.

**Actors:** Admin or Lead Manager throughout.

1. **Find the person** → `concepts/applicants_flows.md` → *"Maintain a file over time"* (steps 1–2)

2. **Record the new objective** → `concepts/applicant_journeys_flows.md` → *"Record a new study objective"*
   - No new applicant is created, and the earlier journey is untouched — including a completed or closed one.

3. **Run it forward independently** → `concepts/applicant_journeys_flows.md` → *"Work an objective forward"*

**The point of this journey:** it is why journeys are a separate app rather than fields on the applicant. Someone whose Australia plan failed and who is now trying Canada has two histories, each with its own outcome, and neither overwrites the other.

---

## Journey: A closed enquiry comes back

**Actors:** Lead Manager or Admin, then Admin to convert.

1. **Revive the lead** → `concepts/leads_flows.md` → *"Revive a closed enquiry"*

2. **Resume follow-up** → `concepts/leads_flows.md` → *"Work a lead through follow-up"*

3. **Convert** → `concepts/leads_flows.md` → *"Convert a lead into a client"*
   - A previously lost lead converts normally once reopened. The loss is still in its history.

**Related but distinct:** reopening a lead that was already **converted** does not undo the conversion and cannot produce a second applicant. That is a correction to the lead's own stage, not a re-entry into this journey.

---

## Cross-app dependency summary

Assembled from each app's flow file. Read it as integration order — an app's dependencies must work before it does.

- `leads` → `applicants` (conversion creates one), `applicant_journeys` (conversion creates one), `audit`, `authenticate`
- `applicants` → `authenticate`, `audit`. **Not** `leads` — an applicant works with no lead in the system.
- `applicant_journeys` → `applicants` (every journey needs one), `authenticate`, `audit`. **Not** `leads`.

The one-directional arrangement is deliberate: `leads` owns both links to the applicant cycle, so the applicant cycle never needs to know leads exist.

## Open questions

- **No reporting or dashboard journey.** `project_overview.txt` names a `dashboards` domain covering lead funnels, conversion rates, and journey stages. Nothing is built, and the filters that exist today (lead stage, applicant status, journey stage) are the raw material rather than the feature.
- **No notification journey.** Passport and test expiry, follow-up prompts, and deadline alerts are all anticipated in `project_overview.txt`; the `notifications` domain does not exist. Passport `expiry_date` is stored and indexed in anticipation.
- **No document, file, offer, or checklist journeys.** Four named domains, none built. An applicant file today holds identity and objectives only.
- **The education and test-score gap is visible mid-journey.** At conversion, `highest_qualification` and `language_test_status` are carried into journey notes as prose because their modules do not exist. When `education` and `test_scores` ship, this journey's step 4 gains a real destination for them and the conversion mapping should be revisited.
- **Whether a converted lead should remain visible to its originating Lead Manager in the lead list** is undecided. Today it does, at `stage: converted`, which means a Lead Manager's list accumulates terminal records they can no longer act on.
