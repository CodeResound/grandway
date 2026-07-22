# FLOWS — Audit

**Owner app:** `audit`
**Updated:** 2026-07-22
**Purpose:** The user-flow binding layer for the audit app — connects the product intent in
`concepts/audit.txt` to the callable endpoints in `backend/audit/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

---

## Flow: Review system activity

- **Actor:** Admin / Superadmin
- **Goal:** See what has been happening across Grandway and drill into any event.
- **Entry point:** Audit log

**Steps:**

1. **Audit log** — open the log, optionally apply filters →
   `GET /api/v1/audit/events/` (`audit.event.list`)
   - **Requires state:** a valid access token for an Admin/Superadmin.
   - **Side effects:** none (read-only).
   - *Failure — `PERMISSION_DENIED`:* the caller is not an administrator — hide the audit UI.
2. **Event detail** — open one row →
   `GET /api/v1/audit/events/<id>/` (`audit.event.read`)
   - **Requires state:** a valid administrator token.
   - **Side effects:** none.
   - *Failure — `AUDIT_EVENT_NOT_FOUND`:* the event id is unknown — show not-found.

## Flow: Reconstruct a record's history

- **Actor:** Admin / Superadmin
- **Goal:** See the full timeline of everything that happened to one record.
- **Entry point:** Record timeline (reached from that record's screen in its own app)

**Steps:**

1. **Record timeline** — request every event for one entity →
   `GET /api/v1/audit/events/?entity_type=<type>&entity_id=<uuid>` (`audit.event.list`)
   - **Requires state:** a valid administrator token.
   - **Side effects:** none. Results are newest-first; reverse client-side for a chronological timeline.
2. **Event detail** — open any item → `GET /api/v1/audit/events/<id>/` (`audit.event.read`).

## Flow: Review an account's authentication activity

- **Actor:** Superadmin (for admins) / Admin (for lead managers)
- **Goal:** Investigate the auth history of one account across the central log.
- **Entry point:** Authentication activity

**Steps:**

1. **Authentication activity** — filter to one account's auth events →
   `GET /api/v1/audit/events/?app=authenticate&actor_id=<uuid>` (`audit.event.list`), or by `entity_type=authenticate.user&entity_id=<uuid>` for events *about* the account.
   - **Requires state:** a valid administrator token.
   - **Side effects:** none.
   - Note: this central view complements `authenticate`'s own per-account review at `GET /api/v1/auth/users/<id>/events/` (`authenticate.user.list_events`) **(cross-app: authenticate)** — the authenticate endpoint reads that app's authoritative `AuthEvent` log; audit shows the federated central copy plus (eventually) events from other apps.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `audit.event.list` | `GET /api/v1/audit/events/` | Review system activity; Reconstruct a record's history; Review an account's authentication activity | Paginated; filters in INTEGRATION §3 |
| `audit.event.read` | `GET /api/v1/audit/events/<id>/` | Review system activity; Reconstruct a record's history | |

## Cross-app dependencies

- **This app references (outbound):** none — audit is read-only and imports no other app's models.
- **Populated by (inbound writes):** `authenticate` emits every auth event to the central log via the audit `record_event` service (federated, best-effort). This is a write-path coupling, not a flow-endpoint reference; future operational apps will emit here the same way.
- **Referenced by other apps' flows (inbound):** none yet.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule).

## Open questions

- Whether operational apps (leads, applicants, journeys, documents…) emit to audit as they are built (federated), and how each maps its actions to `action` values.
- Own-scope Lead Manager read access (deferred) and arbitrary date-range filtering.
