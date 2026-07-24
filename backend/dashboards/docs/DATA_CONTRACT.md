# Data Contract — Dashboards

**Owner app:** `dashboards`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Defines the eight response payloads this app returns. It owns **no database table** — there is no `models.py`, no `migrations/` directory, and no row anywhere belongs to it. Every figure is derived at request time from the apps that own the records, so what this contract describes is a set of read models, not a schema.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude Opus 4.8) | Initial contract — eight read models, no tables |

---

## Deliberate Deviations

Three of this document's usual conventions do not apply, and each is a decision rather than an omission.

- **No field table with `Required` / `Nullable` / `Generated` columns.** Those columns describe what a client may *write*. Nothing here is writable — this app has no create or update endpoint of any kind — so every field is generated and read-only, and a table saying so eight times would carry no information. Fields are documented with their type and meaning instead.
- **No `Indexes` sections.** This app has no table to index. Every query it triggers is served by an index belonging to the owning app, and those are documented in that app's own contract. `API.md` §1 names which index backs which section.
- **Soft Delete is `N/A` for every read model**, stated once in §0 rather than repeated eight times. §19.2 rule 5 makes the statement mandatory; making it eight times would be noise.

---

## 0. Ownership and lifecycle (applies to every read model below)

**Soft Delete:** N/A — this app owns no rows, so it has nothing to delete, archive, or restore. Every record it reports on is deleted or archived according to its own app's contract, and this app reflects whatever that app currently says.

**Source of truth:** never this app. Every figure is recomputed on each request from the owning app's selectors. There is no stored counter, no nightly rollup, no cache, and no denormalized copy — which is the point: a stored count can disagree with the rows it summarizes, and a derived one cannot.

**Consistency:** the eight endpoints are eight separate requests against a live database. A record changing between two of them makes the sections disagree, and nothing reconciles them. Cross-section equality is **not** contracted; §1's alert counts are shortcuts into the fuller sections, not assertions about them.

**Scoping:** inherited from each owning app, never re-implemented. Lead figures pass through `leads.selectors.get_leads_for_actor`; file figures pass through `uploaded_files.selectors.get_visible_files`. **The consequence is that a single response is not uniformly scoped**: for a Lead Manager, lead-derived figures are narrowed to their own leads and everything else is not, because those apps are not owner-scoped either. Only `workload.is_scoped_to_caller` marks this.

**Provenance of every figure:**

| Read model | Reads from |
|------------|-----------|
| §1 Summary | `leads`, `applicants`, `applicant_journeys`, `offers`, `checklists`, `uploaded_files` |
| §2 Today's work | `checklists`, `offers`, `uploaded_files`, `documents`, `leads` |
| §3 Pipeline health | `leads`, `applicants`, `applicant_journeys`, `offers`, `checklists`, `documents`, `uploaded_files` |
| §4 Blockers and risk | `checklists`, `applicants`, `offers`, `uploaded_files` |
| §5 Workload by owner | `leads`, `checklists`, `offers` |
| §6 Source and conversion | `leads`, `applicants`, `applicant_journeys`, `offers` |
| §7 Final outcomes | `applicant_journeys`, `offers`, `applicants`, `checklists` |
| §8 Recent activity | `audit` |

---

## 1. Summary (read model)

**Purpose:** The alert strip. Answers *how much* and *where to go*, and nothing else.

| Field | Type | Description |
|-------|------|-------------|
| alerts.overdue_checklist_items | integer | Unresolved items on live checklists past their due date |
| alerts.due_soon_checklist_items | integer | Unresolved items falling due within `due_within_days`. Disjoint from the above |
| alerts.blocked_checklist_items | integer | Items a human explicitly declared stuck |
| alerts.offers_awaiting_response | integer | Issued offers whose deadline has passed or falls within `due_within_days` |
| alerts.files_awaiting_verification | integer | Live files nobody has reviewed |
| alerts.rejected_files | integer | Live files a reviewer rejected and nobody replaced |
| alerts.stale_leads | integer | Live leads with no follow-up in 7 days. **Owner-scoped** |
| alerts.journeys_without_a_checklist | integer | Journeys naming a country whose requirements nobody authored |
| volumes.leads_total | integer | Every lead in the window, all stages. **Owner-scoped** |
| volumes.applicants_active | integer | Applicants with `status = active` |
| volumes.journeys_total | integer | Every journey in the window, all stages |
| due_within_days | integer | The horizon actually applied, echoed so a client need not assume the default |

**Validation Rules:** none — read-only, no field is accepted from a client on any endpoint.

**Soft Delete:** N/A — see §0.

**Example:** `INTEGRATION.md` §4 `Worked examples`.

**Cross-App Dependencies:** six apps, read-only through their own selectors. No FK.

---

## 2. Today's work (read model)

**Purpose:** What needs attention now. The most useful section in the app.

| Field | Type | Description |
|-------|------|-------------|
| due_within_days | integer | The horizon actually applied |
| overdue_checklist_items | Preview<ChecklistItemRow> | Past due, unresolved, on a live checklist |
| due_soon_checklist_items | Preview<ChecklistItemRow> | Falling due within the horizon. **Disjoint from overdue** |
| offers_awaiting_response | Preview<OfferRow> | Issued offers, deadline passed or approaching |
| files_awaiting_verification | Preview<FileRow> | Oldest upload first — a review queue |
| documents_in_progress | Preview<DocumentRow> | Draft documents, oldest edit first — stalled work |
| stale_leads | Preview<LeadRow> | No follow-up in 7 days. **Owner-scoped** |

**`Preview<T>`:** `{ total, has_more, items }`. `total` is the real backlog; `items` holds at most `WORKLIST_PREVIEW_LIMIT` (10) rows; `has_more` is `total > len(items)`.

**Validation Rules:** none — read-only.

**Soft Delete:** N/A — see §0.

**Business rules worth restating here, because they shape what the numbers mean:**
- An item or offer with **no due date never appears**. This list is therefore not "all outstanding work".
- `blocked` items appear when overdue: a stuck requirement is still not done.
- Only `draft`/`active` checklists contribute. A completed or archived checklist's items are finished.
- `stale_leads` uses a fixed 7-day rule and does **not** respond to `due_within_days` — a lead has no due date, so silence is the only signal.

**Cross-App Dependencies:** `checklists`, `offers`, `uploaded_files`, `documents`, `leads`. No FK.

---

## 3. Pipeline health (read model)

**Purpose:** Where volume sits across the business.

| Field | Type | Description |
|-------|------|-------------|
| leads_by_stage | map[str→int] | All 8 `LeadStage` values, zero-filled. **Owner-scoped** |
| applicants_by_status | map[str→int] | All 3 `ApplicantStatus` values |
| journeys_by_stage | map[str→int] | All 9 `JourneyStage` values |
| offers_by_status | map[str→int] | All 7 `OfferStatus` values |
| checklists_by_status | map[str→int] | All 4 `ChecklistStatus` values |
| documents_by_status | map[str→int] | All 3 `DocumentStatus` values |
| documents_by_status_is_country_filtered | boolean | Always `false` — see below |
| files_by_verification | map[str→int] | All 3 `VerificationStatus` values, live files only |

**Validation Rules:** none — read-only.

**Soft Delete:** N/A — see §0.

**Two properties a consumer must not assume away:**
- **Every map is zero-filled across its full enum.** An absent key means the field does not exist, never that the count is nil. A funnel that dropped its empty stages would read as though those stages did not exist, when the fact worth seeing is that nothing has reached them.
- **`documents_by_status_is_country_filtered` is a permanent `false`, not a feature flag.** A document belongs to an applicant, not to a journey, so it carries no destination and **cannot** be filtered by country. The field exists so a client applying a country filter elsewhere on the screen can label that one panel honestly rather than implying a narrowing that did not happen.

**Cross-App Dependencies:** seven apps. No FK.

---

## 4. Blockers and risk (read model)

**Purpose:** Risk surfaced before it becomes a missed outcome.

| Field | Type | Description |
|-------|------|-------------|
| blocked_checklist_items | Preview<ChecklistItemRow> | Explicitly declared stuck; `status_note` says why |
| journeys_without_a_checklist | Preview<JourneyRow> | Destination named, requirements never authored |
| expiring_passports | Preview<PassportRow> | Expiring within `passport_within_days`, **including already expired** |
| overdue_offers | Preview<OfferRow> | Deadlines already past only |
| rejected_files | Preview<FileRow> | Rejected and not yet replaced |
| passport_within_days | integer | The horizon actually applied |

**Validation Rules:** none — read-only.

**Soft Delete:** N/A — see §0.

**`journeys_without_a_checklist` is the most consequential field in this app.** Automatic checklist inheritance is silent when a country has no default template: no checklist is created and **no error is raised**, correctly so, since an empty list would be worse than none. That silence is indistinguishable from success everywhere except here. Every row is an applicant whose destination nobody has written requirements for.

**Cross-App Dependencies:** `checklists`, `applicants`, `offers`, `uploaded_files`. No FK.

---

## 5. Workload by owner (read model)

**Purpose:** How work is distributed, so a manager can rebalance rather than only count volume.

| Field | Type | Description |
|-------|------|-------------|
| is_scoped_to_caller | boolean | `true` for a Lead Manager, `false` for an Admin |
| leads | list[LeadWorkloadRow] | Open leads per owner. **Owner-scoped** |
| checklist_items | list[ChecklistWorkloadRow] | Open / overdue / blocked items per assignee, including an unassigned bucket |
| offers | list[OfferWorkloadRow] | Offers awaiting a response, per the staff member who **recorded** them |

**Validation Rules:** none — read-only.

**Soft Delete:** N/A — see §0.

**Three properties that decide whether a client renders this correctly:**
- **The three lists are not joinable into one row per person and must never be summed.** They measure different things; a combined total would be a number with no meaning.
- **`checklist_items` includes `owner_id: null`, labelled "Unassigned".** Work nobody owns is the most likely to be missed, so it is returned rather than dropped — a workload view that hid it would hide the worst case it exists to surface.
- **`offers` is ownership by authorship, not assignment.** An offer has no assignee; `created_by` is the only ownership the offers app records.

**Cross-App Dependencies:** `leads`, `checklists`, `offers`. No FK.

---

## 6. Source and conversion (read model)

**Purpose:** Whether intake is producing outcomes.

| Field | Type | Description |
|-------|------|-------------|
| by_source | list[SourceConversionRow] | Per channel: `total`, `converted`, `lost`, `in_progress`. **Owner-scoped** |
| rates.lead_to_applicant | Rate | Converted leads over all leads. **Owner-scoped** |
| rates.applicant_to_journey | Rate | Applicants holding a journey, over all applicants |
| rates.journey_to_offer | Rate | Journeys holding an offer, over all journeys |
| rates.offer_acceptance | Rate | Accepted offers over **decided** offers |

**`Rate`:** `{ numerator, denominator, percent }`. `percent` is `null` — never `0` — when `denominator` is `0`.

**Validation Rules:** none — read-only.

**Soft Delete:** N/A — see §0.

**The four rates are four independent measures, not one funnel.** Each is windowed on its own stage's dates, so a lead that arrived in Ashadh and converted in Shrawan counts toward Ashadh's intake and Shrawan's conversions. Multiplying them together, or rendering them as one cohort walking through four gates, reports something the data does not say. For a Lead Manager the inconsistency is sharper still: the first rate is owner-scoped and the other three are not.

`applicant_to_journey` and `journey_to_offer` count **distinct** applicants and journeys respectively — a person pursuing three objectives converted once, and a study plan collecting four competing offers converted once.

**Cross-App Dependencies:** `leads`, `applicants`, `applicant_journeys`, `offers`. No FK.

---

## 7. Final outcomes (read model)

**Purpose:** How work ended, over the window.

| Field | Type | Description |
|-------|------|-------------|
| journey_outcomes | map[str→int] | All 6 `JourneyOutcome` values, windowed on `closed_at` |
| offer_decisions | map[str→int] | The 5 terminal `OfferStatus` values, windowed on `decided_at` |
| journeys_completed | integer | Windowed on **creation** |
| journeys_closed | integer | Windowed on **creation** |
| applicants_archived | integer | |
| applicants_dormant | integer | |
| checklists_completed | integer | |
| checklists_archived | integer | |

**Validation Rules:** none — read-only.

**Soft Delete:** N/A — see §0.

**Two windowing rules coexist in this one payload, deliberately.** `journey_outcomes` and `offer_decisions` are windowed on *when the thing ended*, because "how many journeys ended successfully in Shrawan" is a question about the ending. `journeys_completed`/`journeys_closed` are windowed on *creation*, matching §3. **The same journey can therefore be counted by one and not the other**, and a consumer comparing them will find a discrepancy that is correct.

`offer_decisions` carries keys only for the five terminal statuses; `draft` and `issued` are not decisions and never appear.

**Cross-App Dependencies:** `applicant_journeys`, `offers`, `applicants`, `checklists`. No FK.

---

## 8. Recent activity (read model)

**Purpose:** The change feed, projected from the central audit log.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | The audit event's id |
| app_label | string | Which app recorded it |
| action | string | **Not a fixed enum** — every app contributes its own values |
| entity_type | string | The kind of record acted on; may be blank |
| entity_id | UUID or null | The record acted on |
| actor_type | string | `superadmin` / `admin` / `lead_manager` / `system` / `ai` |
| actor_label | string | Who acted, denormalized onto the event |
| summary | string | The human-readable label. Render this rather than branching on `action` |
| success | boolean | Whether the action succeeded |
| created_at | datetime | UTC |
| created_at_bs | BsDate | The Bikram Sambat companion (§39.4) |

**Validation Rules:** none — read-only.

**Soft Delete:** N/A — see §0. `audit.AuditEvent` blocks deletion at the model layer, so nothing here can disappear.

**This is the one place in the app where a caller may see something the corresponding list endpoint would not show them.** The feed is **not** narrowed by authority, because the audit log is not owner-scoped anywhere in the project. A Lead Manager therefore sees events referring to records outside their scope. Narrowing it here would make this endpoint disagree with `GET /api/v1/audit/events/`, which the same users may already call, so the inconsistency was chosen over the disagreement. Note that an event carries a `summary` and ids, never a record's contents — `audit`'s own contract keeps sensitive values out of every payload.

**Cross-App Dependencies:** `audit`, read through `audit.selectors.get_events`. No FK.
