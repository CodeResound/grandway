# FLOWS — Project (end-to-end, multi-app)

**Owner:** project-level — no single app
**Updated:** 2026-07-24
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

6. **Record the institutional responses** → `concepts/offers_flows.md` → *"Record an offer against a journey"*, then *"Manage an offer's conditions"*
   - One offer per institutional response. A journey may collect several and keeps all of them.
   - **Nothing here advances the journey.** A journey can sit at `planning` with three issued offers on it — offer status and journey stage are separate lifecycles, and no API surface reconciles them. If the UI should move the journey to `offer_stage`, it makes that call itself.

7. **Decide** → `concepts/offers_flows.md` → *"Record the applicant's decision"*, and where there are competing responses, *"Compare competing offers on one journey"*
   - At most one offer per journey may be `accepted`; the rest are resolved as rejected or withdrawn and stay visible.
   - **An offer decision is final** — unlike a journey, an offer cannot be reopened. A changed institutional position is a new offer.

8. **Run the objective to an outcome** → `concepts/applicant_journeys_flows.md` → *"End an objective"*
   - The journey closes with a recorded outcome. The applicant's status is untouched, and so is every offer on it — closing a journey does not resolve its outstanding offers, and an offer can still be recorded against a closed journey.

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
- `applicant_journeys` → `applicants` (every journey needs one), `authenticate`, `audit`. **Not** `leads`, and **not** `offers`.
- `institutions` → `authenticate`, `audit`. Depends on no business app; the catalogue is reference data.
- `offers` → `applicant_journeys` (every offer needs one), `institutions` (optional — the catalogue entry it was based on), `authenticate`, `audit`.
- `clients` → `authenticate`, `audit`. **No business-app edge in either direction** — the only app in the project with none.
- `documents` → `applicants` (optional — an applicant-owned document points at one; a standalone document points at nothing), `authenticate`, `audit`. **Not** `applicant_journeys`: a document belongs to a person, not to one of their study plans.

The one-directional arrangement is deliberate: `leads` owns both links to the applicant cycle, so the applicant cycle never needs to know leads exist. `offers` does the same at the other end — it reaches into both the journey and the catalogue, and neither reaches back.

**`offers` is where the catalogue finally connects to the applicant cycle, but the join is partial.** A journey still stores its destination as free text and has no reference into `institutions`; an offer references the catalogue properly. Nothing compares the two, so "the journey names Melbourne Uni" and "the offer points at the catalogue's University of Melbourne" remain unconnected facts. And an offer never reads through to the catalogue at display time — it renders from a snapshot taken when the decision was recorded, which is what lets the catalogue be edited freely without rewriting history.

## Open questions

- **No reporting or dashboard journey.** `project_overview.txt` names a `dashboards` domain covering lead funnels, conversion rates, and journey stages. Nothing is built, and the filters that exist today (lead stage, applicant status, journey stage) are the raw material rather than the feature.
- **No notification journey.** Passport and test expiry, follow-up prompts, and deadline alerts are all anticipated in `project_overview.txt`; the `notifications` domain does not exist. Passport `expiry_date` is stored and indexed in anticipation.
- **No file or checklist journeys.** Two named domains, neither built. `offers` and `documents` both shipped 2026-07-24; uploaded files and checklists have not.
- **`documents` shipped, but no end-to-end journey passes through it — and it is the first module a Lead Manager cannot see.** The document workspace is complete for creating, editing, archiving, and restoring (`concepts/documents_flows.md`), but it sits outside every journey above for two reasons. First, **access**: documents are Admin-only, reads included, so the Lead Manager who runs the applicant's file cannot open them at all. Second, **the print step does not exist**: `document_history` has no concept file and no code, so a document can be prepared but never formally issued. The journey "prepare and issue an applicant's documents" cannot be written until both are resolved.
- **Three document-adjacent domains remain unbuilt and block each other.** `document_history` (print snapshots), `document_templates` (template definitions and signatory records), and `uploaded_files` (supporting files). `document_history` and `document_templates` have no concept file yet, which is what stopped them being built alongside `documents`. Until they exist, a certificate cannot resolve its signatory, a document cannot carry an attachment, and no document can be printed to history.
- **`clients` shipped, but no journey passes through it.** The B2B partner directory exists (`concepts/clients_flows.md`) and is complete on its own terms, yet **no end-to-end journey touches it**, because nothing records which partner referred a lead. `concepts/clients.txt` flow 3 anticipates exactly that; the `leads.Lead.client` reference it needs is not built. Until it is, "Enquiry to study objective" begins with a lead whose origin is a free-text `LeadSource`, and a partner organization cannot be connected to a single person it sent. Building the link would add a step to that journey's stage 1 and give `clients` its first cross-app flow.
- **An offer has nowhere to put the letter it came from.** `uploaded_files` does not exist, so the PDF that prompted the offer record lives outside the system. This is the most visible gap in the offer flow today.
- **Offer conditions and `checklists` overlap and nothing reconciles them.** `offers` owns its own condition sub-records because `checklists` is unbuilt. Whether the two should merge when it ships is an open question in `concepts/offers.txt`.
- **No deadline or expiry alerting.** An offer's `response_deadline` is stored and an `is_response_overdue` flag is computed on read, but nothing polls or notifies — `notifications` does not exist. A lapsed offer is only noticed by someone looking at the list.
- **The education and test-score gap is visible mid-journey.** At conversion, `highest_qualification` and `language_test_status` are carried into journey notes as prose because their modules do not exist. When `education` and `test_scores` ship, this journey's step 4 gains a real destination for them and the conversion mapping should be revisited.
- **Whether a converted lead should remain visible to its originating Lead Manager in the lead list** is undecided. Today it does, at `stage: converted`, which means a Lead Manager's list accumulates terminal records they can no longer act on.
