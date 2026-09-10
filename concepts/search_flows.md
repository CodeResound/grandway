# FLOWS — Search

**Owner app:** `search`
**Updated:** 2026-08-02
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/search.txt` to the callable endpoints in `backend/search/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **Note on this app's flows.** Almost every step after the first is `(cross-app:)`, and that is the
> shape of the app rather than an accident: global search exists to *hand off*. Its own two endpoints
> answer "which record did you mean", and everything after that belongs to the module that owns the
> record. A flow here that never left this app would be a flow that never got the user anywhere.

---

## Flow: Find a person at the counter and open their record

- **Actor:** Admin / Lead Manager
- **Goal:** Turn a half-remembered name, phone number, or email into the right record, without first
  guessing which list to open.
- **Entry point:** Global search bar

**Steps**

1. **Global search bar** — the application shell loads and prepares the filter chips →
   `GET /api/v1/search/types/` (`search.type.list`)
   - **Requires state:** an authenticated session held by an Admin or Lead Manager.
   - **Side effects:** none. Cache the response for the session; it is static per deployment.
   - *Failure — `SEARCH_ACTOR_FORBIDDEN`:* hide the search bar entirely. A Superadmin has no
     operational search; showing a box that always 403s is worse than showing nothing.
2. **Global search bar** — user types at least two characters (debounced) →
   `GET /api/v1/search/?q=<text>` (`search.query.read`)
   - **Requires state:** none beyond the session. An empty system returns empty buckets, not an error.
   - **Side effects:** none. Nothing is written and no audit event is recorded.
   - *Failure — `VALIDATION_ERROR`:* do not send a query under two characters at all; enforce the
     minimum client-side and leave the panel showing its idle state.
   - *Failure — `RATE_LIMIT_EXCEEDED`:* the box is not debounced enough. Back off for `Retry-After`
     and show the previous results rather than an error.
3. **Results panel** — render one section per bucket with `total > 0`, in the order returned; show
   `title`, `subtitle`, and a badge derived from `matched_on`.
   - **Requires state:** the response from step 2. Discard it if `data.query` no longer matches what
     is in the box — a slower earlier keystroke may land after a later one.
   - **Side effects:** none.
   - *Failure — `total_hits` is `0`:* one "nothing found" message for the whole panel, never nine
     empty sections.
4. **Results panel** — user clicks an applicant hit → open the record at the hit's `detail_path` →
   `GET /api/v1/applicants/<id>/` (`applicants.applicant.read`) **(cross-app: `applicants`)**
   - **Requires state:** the applicant exists — guaranteed, since search just returned it.
   - **Side effects:** none.
   - *Failure — `APPLICANTS_APPLICANT_NOT_FOUND`:* the record was deleted between the search and the
     click. Refresh the search rather than showing a dead detail screen.
5. **Results panel** — user clicks "see all 43" on a bucket instead → follow the bucket's `list_url` →
   `GET /api/v1/leads/?search=<text>` (`leads.lead.list`) **(cross-app: `leads`)**
   - **Requires state:** none. `list_url` already carries the query in that module's own parameter.
   - **Side effects:** none.
   - *Failure — none specific:* the target list handles its own errors.

## Flow: Find a file whose owner nobody remembers

- **Actor:** Admin / Lead Manager
- **Goal:** Locate an uploaded file by its filename and reach the record it belongs to.
- **Entry point:** Global search bar → Type filter chips

**Steps**

1. **Type filter chips** — user restricts the search to files →
   `GET /api/v1/search/?q=<filename>&types=uploaded_file` (`search.query.read`)
   - **Requires state:** an authenticated session.
   - **Side effects:** none.
   - *Failure — `VALIDATION_ERROR` naming `types`:* the client sent a key not in the catalogue from
     `search.type.list`. Rebuild the chips from that endpoint instead of hardcoding them.
2. **Results panel** — user opens the file hit →
   `GET /api/v1/files/<id>/` (`uploaded_files.file.read`) **(cross-app: `uploaded_files`)**
   - **Requires state:** the file is visible to this caller — guaranteed, since search applied the
     same visibility rule.
   - **Side effects:** none.
   - *Failure — empty bucket for a Lead Manager where an Admin sees a result:* not a failure. The file
     belongs to a document, a print snapshot, or a signatory, and is outside a Lead Manager's
     visibility. Show the ordinary empty state; do not retry, and do not surface an "access denied"
     message for a record the user was never told exists.
   - **Known inconsistency, and it is inside one response body.** The `uploaded_file` bucket is
     narrowed by authority; the `signatory`, `document`, and `document_template` buckets are **not**.
     So a Lead Manager searching a signer's name gets a populated `signatory` hit whose hand-off link
     (`document_templates.signatory.read`) returns 403, while that signatory's signature file is
     correctly hidden. This predates the signature work — `documents` and `document_templates` hits
     have always had it — and is recorded here so it is not filed as a regression against signature
     uploads. Guard the hand-off client-side until the buckets are narrowed.

## Flow: Look up an institution while advising, then shortlist

- **Actor:** Admin / Lead Manager
- **Goal:** Check whether an institution or program exists and is currently usable, mid-conversation,
  then move into real shortlisting.
- **Entry point:** Global search bar

**Steps**

1. **Global search bar** — user types an institution name →
   `GET /api/v1/search/?q=<name>&types=institution,program` (`search.query.read`)
   - **Requires state:** an authenticated session.
   - **Side effects:** none.
2. **Results panel** — read `availability_status` from each hit's `subtitle`.
   - **Requires state:** none.
   - **Side effects:** none.
   - *Note, not a failure:* paused and withdrawn records **are** returned here, unlike the catalogue's
     own lists, which default to usable only. Render the status visibly — someone searching a paused
     institution is usually checking exactly that.
3. **Results panel** — user follows the program bucket's "see all" into real shortlisting →
   `GET /api/v1/catalogue/programs/?q=<name>` (`institutions.program.list`)
   **(cross-app: `institutions`)**
   - **Requires state:** none.
   - **Side effects:** none.
   - *Failure — none specific:* the catalogue list owns the shortlisting filters (country, level,
     field, tuition, scholarship); search deliberately does not duplicate them.

## Flow: Narrow a noisy search

- **Actor:** Admin / Lead Manager
- **Goal:** Cut a common-name search down to the one record type that matters.
- **Entry point:** Results panel → Type filter chips

**Steps**

1. **Type filter chips** — user selects one or more chips; the client re-issues the same query →
   `GET /api/v1/search/?q=<text>&types=applicant&limit_per_type=20` (`search.query.read`)
   - **Requires state:** the chip keys came from `search.type.list`.
   - **Side effects:** none. The request is also proportionally cheaper server-side — `types` is the
     only control a client has over the cost of a search.
   - *Failure — `VALIDATION_ERROR` naming `limit_per_type`:* the cap is 20. Page through the bucket's
     `list_url` rather than raising the limit.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `search.query.read` | `GET /api/v1/search/` | Find a person at the counter; Find a file whose owner nobody remembers; Look up an institution while advising; Narrow a noisy search | The app's only substantive endpoint |
| `search.type.list` | `GET /api/v1/search/types/` | Find a person at the counter (step 1) | Fetched once at shell startup and cached; every other flow relies on that cache |

## Cross-app dependencies

- **This app references (outbound):** `applicants.applicant.read`, `applicants.applicant.list`,
  `leads.lead.read`, `leads.lead.list`, `clients.client.read`, `clients.client.list`,
  `documents.document.read`, `documents.document.list`, `uploaded_files.file.read`,
  `uploaded_files.file.list`, `institutions.institution.read`, `institutions.institution.list`,
  `institutions.program.read`, `institutions.program.list`, `document_templates.template.read`,
  `document_templates.template.list`, `document_templates.signatory.read`,
  `document_templates.signatory.list`. Every one is a hand-off target reached from a hit's
  `detail_path` or a bucket's `list_url`, and every one is declared as a strict forward dependency in
  `search/registry.py`.
- **Referenced by other apps (inbound):** none yet. No other app's flow calls a `search.*` endpoint.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.
