# FLOWS — Institutions

**Owner app:** `institutions`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/institutions.txt` to the callable endpoints in `backend/institutions/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **Two things govern every flow below.**
>
> 1. **Writes are Admin-only; reads are shared.** A Lead Manager loads any screen here but receives
>    403 `INSTITUTIONS_ACTOR_FORBIDDEN` on every create and edit. The UI must hide or disable write
>    controls for a Lead Manager rather than let them fail — this is the only app in the project with
>    that split.
> 2. **There is no delete, anywhere.** No screen gets a delete button. Withdrawal from use is an
>    availability change, which is an ordinary `PATCH`.

---

## Flow: Build the catalogue from empty

- **Actor:** Admin
- **Goal:** Get from a blank catalogue to a program a counsellor can shortlist.
- **Entry point:** Catalogue Dashboard

**Steps:**

1. **Reference Maintenance** — create a study field →
   `POST /api/v1/catalogue/fields/` (`institutions.field.create`)
   - **Requires state:** nothing. This and step 2 are the two roots; either order works.
   - **Side effects:** appends `catalogue_field_created` to the audit log.
   - *Failure — `INSTITUTIONS_CODE_DUPLICATE`:* inline error on the code input, "already in use".
   - *Failure — `VALIDATION_ERROR`:* inline field errors. The code input must reject Devanagari — show the ASCII rule before submit.

2. **Country List** — create a country →
   `POST /api/v1/catalogue/countries/` (`institutions.country.create`)
   - **Requires state:** nothing.
   - **Side effects:** appends `catalogue_country_created` to the audit log.
   - *Failure — `INSTITUTIONS_CODE_DUPLICATE`:* inline error on the code input.

3. **Institution List** — create an institution under that country →
   `POST /api/v1/catalogue/institutions/` (`institutions.institution.create`)
   - **Requires state:** an existing country, chosen from a picker fed by `institutions.country.list`.
   - **Side effects:** appends `catalogue_institution_created` to the audit log.
   - *Failure — `VALIDATION_ERROR` on `country`:* the country picker is stale; refetch it.
   - **Note:** duplicate provider names are **allowed** and produce no error. If the UI wants to warn about a possible duplicate it must do so client-side from the list results — the API will not.

4. **Institution Detail** — *(optional)* add a campus →
   `POST /api/v1/catalogue/institutions/<institution_id>/campuses/` (`institutions.campus.create`)
   - **Requires state:** the institution being viewed. The parent is in the URL — the form has no institution picker.
   - **Side effects:** appends `catalogue_campus_created` to the audit log.
   - *Failure — `INSTITUTIONS_CAMPUS_DUPLICATE`:* inline error on the name input, "this institution already has a campus with that name".
   - **Skip this step** when the institution does not vary by location; `campus` on a program is optional.

5. **Program List** — create a program →
   `POST /api/v1/catalogue/programs/` (`institutions.program.create`)
   - **Requires state:** an existing institution **and** an existing field. A campus is optional, and its picker must be filtered to the chosen institution.
   - **Side effects:** appends `catalogue_program_created` to the audit log. Nothing outside this app changes.
   - *Failure — `INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH`:* the campus picker was not filtered to the selected institution — a UI bug, not user error. Reset the campus field and refilter.
   - *Failure — `INSTITUTIONS_TUITION_INCOMPLETE`:* highlight all three tuition inputs together. Treat amount, currency, and period as one composite control that is filled or empty as a unit.

**Order is enforced by data, not by the API.** Nothing stops a client calling step 5 first; it will simply have no institution or field id to send. Present the dashboard so the roots are the obvious starting point.

## Flow: Shortlist programs for an applicant journey

- **Actor:** Lead Manager or Admin
- **Goal:** Find programs that fit an applicant's stated objective, and record the chosen one.
- **Entry point:** Program Search / Shortlist, opened from an applicant journey.

**Steps:**

1. **Journey Detail** — read the objective the search will be seeded from →
   `GET /api/v1/journeys/<journey_id>/` (`applicant_journeys.journey.read`) **(cross-app: `applicant_journeys`)**
   - **Requires state:** an existing journey.
   - **Side effects:** none.
   - Take `study_level`, `field_of_study`, `target_country`, and `budget_amount`.

2. **Program Search / Shortlist** — resolve the journey's free-text country to a catalogue id →
   `GET /api/v1/catalogue/countries/?q=<target_country>` (`institutions.country.list`)
   - **Requires state:** none.
   - **Side effects:** none.
   - **This step exists only because the two apps are not linked.** A journey stores its country as an unvalidated string, so it must be matched by name before it can be used as a filter.
   - *No match:* do **not** block. Run the search without the country filter and tell the user the journey names a country the catalogue does not hold. The concept is explicit that a journey stays free to pursue an option with no catalogue record.

3. **Program Search / Shortlist** — resolve the journey's free-text field of study to a catalogue id →
   `GET /api/v1/catalogue/fields/?q=<field_of_study>&is_active=true` (`institutions.field.list`)
   - **Requires state:** none.
   - **Side effects:** none.
   - Same reason and same fallback as step 2: `field_of_study` is free text on the journey and a UUID here. No match means run the search without the field filter, not block.

4. **Program Search / Shortlist** — run the search →
   `GET /api/v1/catalogue/programs/?country=&qualification_level=&field=&q=` (`institutions.program.list`)
   - **Requires state:** none. Every filter is optional.
   - **Side effects:** none.
   - The journey's `study_level` maps **directly** onto `qualification_level` — same enum, no translation table.
   - **Do not wire the journey's `budget_amount` straight into `tuition_max`.** The filter compares raw numbers and normalizes neither currency nor fee period, so an NPR budget against AUD tuition is meaningless and will silently return the wrong set. Either omit it, or convert client-side first and show `tuition_currency` and `tuition_fee_period` on every row.
   - **Results are already restricted to what can be offered.** `usable_only` defaults to true, evaluated across program, campus, institution, and country. Do not add a client-side availability filter — and do not expect a paused country's programs to appear.
   - *Failure — `VALIDATION_ERROR`:* a filter value was malformed. The API rejects rather than ignoring it, so surface it instead of retrying unfiltered.

5. **Program Search / Shortlist** — compare candidates →
   `GET /api/v1/catalogue/programs/<program_id>/` (`institutions.program.read`)
   - **Requires state:** a program id from the results.
   - **Side effects:** none.
   - The list row deliberately omits entry expectations; fetch the detail for the comparison panel.
   - **Render each row's availability from the nested objects, not from `is_usable` alone.** `is_usable` reflects only the record it sits on, so a program under a paused country still reports `is_usable: true` even though the default search excludes it. The nested `campus`, `institution`, and `country` each carry their own `availability_status` for exactly this.

6. **Journey Detail** — record the choice on the journey →
   `PATCH /api/v1/journeys/<journey_id>/` (`applicant_journeys.journey.update`) **(cross-app: `applicant_journeys`)**
   - **Requires state:** the journey, and the chosen program's details from step 4.
   - **Side effects:** appends `journey_updated` to the audit log.
   - **The client copies the strings across.** Write the program's institution and title into the journey's `target_institution_name` and `target_program_name`. There is **no endpoint in either app** that links a journey to a catalogue record, and nothing keeps the copied text in sync if the catalogue is later edited.

## Flow: Withdraw a record from use

- **Actor:** Admin
- **Goal:** Stop a country, institution, campus, or program being offered, without losing it.
- **Entry point:** the detail screen of whichever record is being withdrawn.

**Steps:**

1. **<Resource> Detail** — set the availability status and state the reason →
   `PATCH /api/v1/catalogue/{countries|institutions|campuses|programs}/<id>/`
   (`institutions.country.update` / `institutions.institution.update` / `institutions.campus.update` / `institutions.program.update`)
   - **Requires state:** the record being viewed.
   - **Side effects:** appends the matching `catalogue_*_updated` event with the previous and new values. **Availability does not cascade** — children keep their own status.
   - *Failure — `INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED`:* the note is mandatory for any non-active status. Make status and note **one control**: selecting anything other than "active" reveals a required reason box.

2. **Program Search / Shortlist** — confirm the effect
   - The record disappears from the default search immediately.
   - A record withdrawn *above* a program — a paused country, say — removes that program from search while leaving its own status untouched. The maintenance view (`usable_only=false`) will still show the program as `active`. Surface the reason, or the discrepancy reads as a bug.

3. **<Resource> Detail** — restore, when applicable →
   same `PATCH`, setting `availability_status` back to `active`
   - **Side effects:** the record and everything beneath it return at whatever individual statuses they held.

**There is no delete step, and there never will be.** The record stays retrievable by id permanently so anything that referenced it keeps resolving.

## Flow: Maintain the catalogue as data ages

- **Actor:** Admin
- **Goal:** Keep tuition, intakes, and entry expectations current.
- **Entry point:** Catalogue Dashboard → recently edited / needs review.

**Steps:**

1. **Program List** — find records to review →
   `GET /api/v1/catalogue/programs/?usable_only=false` (`institutions.program.list`)
   - **Requires state:** none.
   - **Side effects:** none.
   - Pass `usable_only=false` — the maintenance view must show paused and inactive records, unlike the shortlisting search.
   - **The dashboard's "needs review" grouping is client-side.** There is no `needs_review` flag and no `?updated_before=` filter; sort on `updated_at` from the list response.

2. **Program Detail** — correct tuition, intake, or entry expectations →
   `PATCH /api/v1/catalogue/programs/<program_id>/` (`institutions.program.update`)
   - **Requires state:** the program.
   - **Side effects:** appends `catalogue_program_updated` carrying each changed field's previous and new value. **This is where the concept's "previous values remain visible in history" requirement is met** — there is no version history to browse.
   - *Failure — `INSTITUTIONS_TUITION_INCOMPLETE`:* also fires when *clearing* a currency on an already-priced program. The rule is checked against the resulting record, so an edit form that lets the three tuition inputs be emptied independently will hit this.
   - **A no-op save writes no audit event.** A UI that shows "saved, history updated" after an unchanged submit will be lying.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `institutions.field.list` | `GET /api/v1/catalogue/fields/` | Shortlist programs; Build the catalogue | Also feeds every field picker |
| `institutions.field.create` | `POST /api/v1/catalogue/fields/` | Build the catalogue | Admin only |
| `institutions.field.read` | `GET /api/v1/catalogue/fields/<field_id>/` | — | `unused by flow — the list carries every field a picker needs; retrieve exists for deep links and as the dependency root for update` |
| `institutions.field.update` | `PATCH /api/v1/catalogue/fields/<field_id>/` | Withdraw a record from use (via `is_active`) | Admin only. Uses `is_active`, not `availability_status` |
| `institutions.country.list` | `GET /api/v1/catalogue/countries/` | Shortlist programs (step 2); Build the catalogue | Also the country picker |
| `institutions.country.create` | `POST /api/v1/catalogue/countries/` | Build the catalogue | Admin only |
| `institutions.country.read` | `GET /api/v1/catalogue/countries/<country_id>/` | Build the catalogue (Country Detail) | |
| `institutions.country.update` | `PATCH /api/v1/catalogue/countries/<country_id>/` | Withdraw a record from use | Admin only. Highest-blast-radius edit in the app |
| `institutions.institution.list` | `GET /api/v1/catalogue/institutions/` | Build the catalogue; Shortlist programs | Institution List screen and the provider picker |
| `institutions.institution.create` | `POST /api/v1/catalogue/institutions/` | Build the catalogue | Admin only |
| `institutions.institution.read` | `GET /api/v1/catalogue/institutions/<institution_id>/` | Build the catalogue (Institution Detail) | |
| `institutions.institution.update` | `PATCH /api/v1/catalogue/institutions/<institution_id>/` | Withdraw a record from use | Admin only |
| `institutions.campus.list` | `GET /api/v1/catalogue/institutions/<institution_id>/campuses/` | Build the catalogue | Institution Detail campus panel; the campus picker on a program form |
| `institutions.campus.create` | `POST /api/v1/catalogue/institutions/<institution_id>/campuses/` | Build the catalogue | Admin only |
| `institutions.campus.read` | `GET /api/v1/catalogue/campuses/<campus_id>/` | — | `unused by flow — the nested list covers the Institution Detail panel; retrieve exists for deep links and as the dependency root for update` |
| `institutions.campus.update` | `PATCH /api/v1/catalogue/campuses/<campus_id>/` | Withdraw a record from use | Admin only |
| `institutions.program.list` | `GET /api/v1/catalogue/programs/` | Shortlist programs; Maintain the catalogue | **The Program Search / Shortlist screen.** Defaults differ by flow — see each |
| `institutions.program.create` | `POST /api/v1/catalogue/programs/` | Build the catalogue | Admin only |
| `institutions.program.read` | `GET /api/v1/catalogue/programs/<program_id>/` | Shortlist programs (step 4); Maintain the catalogue | The only source of entry expectations |
| `institutions.program.update` | `PATCH /api/v1/catalogue/programs/<program_id>/` | Maintain the catalogue; Withdraw a record from use | Admin only |

**No screen in `concepts/institutions.txt` is unbacked**, with one qualification: the **Catalogue Dashboard**'s "recently edited" and "needs review" groupings have no dedicated endpoint. They are composed client-side from the list endpoints' `updated_at` and `availability_status`.

## Cross-app dependencies

- **This app references (outbound):** `applicant_journeys.journey.read` and `applicant_journeys.journey.update`, both in the shortlisting flow only. Neither is a runtime dependency of this app's code — the *client* calls them; the backend has no coupling to `applicant_journeys` at all.
- **Referenced by other apps (inbound):** none yet. No other app's flow file references an `institutions.*` permission key.

**The shortlisting flow is a client-side join, not a backend integration.** It appears here rather than in `concepts/project_flows.md` because its primary resource is the catalogue — the user is searching programs. When the journey↔catalogue link is eventually built, step 5 changes from "copy the strings across" to a real reference, and that will ripple into `concepts/applicant_journeys_flows.md` as well as this file.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.
