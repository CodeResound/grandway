# FLOWS — Audit

**Owner app:** `audit`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for the audit app — connects the product intent in
`concepts/audit.txt` to the callable endpoints in `backend/audit/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

---

## Flow: Review system activity

- **Actor:** Admin / Superadmin
- **Goal:** See what has been happening across Grandway and drill into any event.
- **Entry point:** Audit log

**Steps:**

1. **Audit log** — populate the filter controls →
   `GET /api/v1/audit/events/facets/` (`audit.event.facets`)
   - **Requires state:** a valid access token for an Admin/Superadmin.
   - **Side effects:** none (read-only).
   - Call once per screen load. `actions`, `apps` and `entity_types` are open, app-owned
     vocabularies with no enum — this endpoint is the only authoritative source for them.
2. **Audit log** — apply filters and read the list →
   `GET /api/v1/audit/events/` (`audit.event.list`)
   - **Requires state:** a valid administrator token.
   - **Side effects:** none.
   - Filters: `app`, `action`, `actor_type`, `actor_id`, `entity_type`, `entity_id`, `success`,
     `search` (over `summary`, min 2 chars), `date_from`/`date_to` (NPT days), `fiscal_year`,
     `order`. All optional and AND-combined; see `INTEGRATION.md` §3.
   - *Failure — `VALIDATION_ERROR`:* a malformed filter value — show the per-field messages from
     `error.details` against the filter controls; the endpoint never 500s on a bad filter.
   - *Failure — `PERMISSION_DENIED`:* the caller is not an administrator — hide the audit UI.
3. **Event detail** — open one row →
   `GET /api/v1/audit/events/<id>/` (`audit.event.read`)
   - **Requires state:** a valid administrator token.
   - **Side effects:** none.
   - Render the time from `created_at_bs` (BS) alongside `created_at` (UTC), and the before/after
     from `changes`, whose entries are `{ "from": …, "to": … }`.
   - *Failure — `AUDIT_EVENT_NOT_FOUND`:* the event id is unknown — show not-found.

## Flow: Reconstruct a record's history

- **Actor:** Admin / Superadmin
- **Goal:** See the full timeline of everything that happened to one record.
- **Entry point:** Record timeline (reached from that record's screen in its own app)

**Steps:**

1. **Record timeline** — request every event for one entity, oldest first →
   `GET /api/v1/audit/events/?entity_type=<type>&entity_id=<uuid>&order=asc` (`audit.event.list`)
   - **Requires state:** a valid administrator token.
   - **Side effects:** none.
   - Ask the server for `order=asc`; do not reverse a page client-side. Page 1 of the default
     descending list is the *newest* page, so reversing it yields the wrong end of the timeline
     whenever the record has more events than one page holds.
2. **Event detail** — open any item → `GET /api/v1/audit/events/<id>/` (`audit.event.read`).
   - Inside a record's own screen, prefer that app's `/history/` endpoint — same rows, narrower
     shape, already scoped to the record. See the owning app's flow file.

## Flow: Review an account's authentication activity

- **Actor:** Superadmin (for admins) / Admin (for lead managers)
- **Goal:** Investigate the auth history of one account across the central log.
- **Entry point:** Authentication activity

**Steps:**

1. **Authentication activity** — filter to one account's auth events →
   `GET /api/v1/audit/events/?app=authenticate&actor_id=<uuid>` (`audit.event.list`), or by
   `entity_type=authenticate.user&entity_id=<uuid>` for events *about* the account. Add
   `date_from`/`date_to` to bound an investigation window.
   - **Requires state:** a valid administrator token.
   - **Side effects:** none.
   - Note: this central view complements `authenticate`'s own per-account review at
     `GET /api/v1/auth/users/<id>/events/` (`authenticate.user.list_events`)
     **(cross-app: authenticate)** — the authenticate endpoint reads that app's authoritative
     `AuthEvent` log; audit shows the federated central copy alongside every other app's events.
     `authenticate`'s central emit is best-effort, so treat a gap here as a gap in the copy, not
     as evidence that nothing happened.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `audit.event.list` | `GET /api/v1/audit/events/` | Review system activity; Reconstruct a record's history; Review an account's authentication activity | Paginated; filters in INTEGRATION §3 |
| `audit.event.read` | `GET /api/v1/audit/events/<id>/` | Review system activity; Reconstruct a record's history | |
| `audit.event.facets` | `GET /api/v1/audit/events/facets/` | Review system activity | Filter dropdown values; not paginated |

## Cross-app dependencies

- **This app references (outbound):** none — audit is read-only and imports no other app's models.
- **Populated by (inbound writes):** twelve apps emit through the audit `record_event` service —
  `applicant_journeys`, `applicants`, `authenticate`, `checklists`, `clients`, `document_history`,
  `document_templates`, `documents`, `institutions`, `leads`, `notifications`, `offers`. This is a
  write-path coupling, not a flow-endpoint reference.
- **Read shape reused by (inbound reads):** `applicant_journeys`, `applicants`, `clients`,
  `documents`, `leads`, `offers` render their `/history/` endpoints from
  `audit.selectors.get_events_for_entity` and audit's shared history serializer. Those history
  flows live in their own flow files; the shape they render is defined in `INTEGRATION.md` §4 as
  **AuditEventHistoryEntry**.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule).

## Open questions

- Own-scope Lead Manager read access — deferred until record ownership lives in the operational apps
  that own those records (the V1 resolved decision in `concepts/audit.txt`).
- Retention: how long events are kept, and whether any are ever archived (never deleted). Nothing
  bounds the table today, which also sets the ceiling on how long the filter-values endpoint stays
  cheap.
- Whether `source` should be populated by every emitter or dropped from the contract — only
  `authenticate` sets it today.
- Whether `entity_type` should have a canonical registry: `authenticate` emits a dotted
  `authenticate.user` while every other app emits a bare `lead`/`applicant`/`offer`.
- Whether an event should be able to reference more than one entity — `concepts/audit.txt` says it
  may, the model holds one pair, and emitters improvise in `metadata`.
