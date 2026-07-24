# Session — 20260724_2344

Branch: `add_audit_read_surface_20260724_2314`

## Audit

## 1. Module

- **Name:** audit
- **Base path:** `/api/v1/audit/`
- **Auth:** Bearer access token AND Admin/Superadmin (`is_staff`). Lead Managers denied on every endpoint.

## 2. Conventions

- **Response:** project envelope — `{ success, message, data, meta }`. Single objects in `data`; lists paginated with `data` as the array.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401), `PERMISSION_DENIED` (403).
- **Pagination:** `?page=` / `?page_size=` (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous`. The filter-values endpoint is not paginated.
- **IDs:** UUID strings.
- **Times:** `created_at` is ISO 8601 UTC; every event also carries `created_at_bs` — **new this session**.
- **List/search/filter/order params** — `app`, `action`, `actor_type`, `actor_id`, `entity_type`, `entity_id`, `success`, `fiscal_year` existed before. **New this session:** `search` (substring of `summary`, min 2 chars), `date_from` / `date_to` (`YYYY-MM-DD`, both inclusive, NPT calendar days), `order` (`desc` default / `asc`). All optional and AND-combined.

## 3. Models

- **AuditEvent** — `{ id, actor_type[enum], actor_id?, actor_label, app_label, action, entity_type, entity_id?, reason, source, ip_address?, success, summary, changes:json, metadata:json, created_at, created_at_bs:json }`
  - `created_at_bs` added this session: `{ year, month, day, month_name_en, month_name_np, display_en, display_np }`.
  - `changes` entries are `{ "from": …, "to": … }`. Unchanged in code; the docs previously said `old`/`new` and were corrected.
- **AuditEventHistoryEntry** — `{ id, action, actor_type[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`
  - New this session. The shape returned by other apps' `/history/` endpoints, now defined once here instead of six times.
  - Not returned by any endpoint under `/api/v1/audit/`.
- **AuditFacets** — `{ apps, actions, entity_types, actor_types }`, each a string array. New this session.

## 4. Enums

- `AuditEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `AuditEvent.action`, `AuditEvent.app_label`, `AuditEvent.entity_type`: open app-owned strings, no closed set. `GET /api/v1/audit/events/facets/` returns the values actually present.

## 5. Dependency order

- Nothing to create — audit is read-only and populated by other apps' actions.
- `audit.event.read` needs `audit.event.list`.
- `audit.event.facets` needs `audit.event.list`.
- **Start here:** `GET /api/v1/audit/events/facets/`, then `GET /api/v1/audit/events/`.

## 6. Endpoints

### Audit events — `/api/v1/audit/events/`

**Use it when:** an administrator reviews system activity, reconstructs one record's timeline, or searches the log by what an event says.

**Methods:**
- `GET /api/v1/audit/events/` (`audit.event.list`) — changed this session
- `GET /api/v1/audit/events/<id>/` (`audit.event.read`) — changed this session

**Send (create/update):** none — read-only.

**Returns:** `list[AuditEvent]` paginated; `read` → one `AuditEvent`.

**Notes:**
- Default order is newest-first; `?order=asc` gives oldest-first for the record-timeline flow.
- Reversing a page client-side is wrong across pagination — page 1 of a descending list is the newest page.
- `?search=` matches `summary` only, so events with a blank `summary` can never match.
- `date_from`/`date_to` name NPT calendar days, not UTC days.

**Errors:**
- `VALIDATION_ERROR` (400) — bad UUID, non-boolean `success`, bad `fiscal_year`, unparseable date, `date_from` after `date_to`, `search` under 2 characters, unknown `order`
- `AUDIT_EVENT_NOT_FOUND` (404) — detail only

### Audit filter values — `/api/v1/audit/events/facets/`

**Use it when:** rendering the audit-log screen's filter dropdowns, before the operator has filtered anything.

**Methods:**
- `GET /api/v1/audit/events/facets/` (`audit.event.facets`) — new this session

**Send (create/update):** none.

**Returns:** one `AuditFacets` object, not paginated.

**Notes:**
- `apps`, `actions`, `entity_types` are read from the data and grow as new events are recorded.
- `actor_types` is the full closed enum, including values never observed.
- Empty lists are a valid response for an empty log.
- One call per screen load, not per keystroke.

**Errors:** none beyond the global auth failures.

## 7. Flows

**Review system activity**
1. `GET /api/v1/audit/events/facets/` → filter values.
2. `GET /api/v1/audit/events/?app=<app>&action=<action>&date_from=<day>&date_to=<day>` → paginated, newest-first.
3. `GET /api/v1/audit/events/<id>/` → full detail with `changes` and `created_at_bs`.
   - `PERMISSION_DENIED` → caller is not an administrator; hide the audit UI.

**Reconstruct a record's timeline**
1. `GET /api/v1/audit/events/?entity_type=<type>&entity_id=<uuid>&order=asc` → oldest-first, paginated in chronological order.
2. `GET /api/v1/audit/events/<id>/` on any entry.
   - Inside that record's own screen, its owning app's `/history/` endpoint returns the same rows in the narrower shape.

**Search the log**
1. `GET /api/v1/audit/events/?search=<term>` → events whose `summary` contains the term.
   - `VALIDATION_ERROR` on `search` → term under 2 characters.
   - Empty result is not proof of absence — blank-`summary` events cannot match.

## 8. Gaps

- `?search=` covers `summary` only; `reason`, `action`, and actor are not searchable, and nothing reports how many events have a blank `summary`.
- `source` is populated by `authenticate` alone; every other emitter leaves it an empty string.
- `entity_type` has no canonical registry — `authenticate` emits `authenticate.user`, every other app emits a bare `lead` / `applicant` / `offer`.
- One `entity_id` per event; an action touching two records records only one, with any second reference improvised inside `metadata`.
- Date filters take Gregorian input only; no BS-native date filter (use `?fiscal_year=` for BS-aligned ranges).
- No retention policy; the table grows without bound, which also bounds how long the filter-values endpoint stays cheap.
- Lead Manager audit access remains deferred (Admin/Superadmin only).

---

## Applicants

## 1. Module

- **Name:** applicants
- **Base path:** `/api/v1/applicants/`
- **Auth:** Bearer access token.

## 2. Conventions

No change this session.

## 3. Models

- **HistoryEntry** — no field change. Now documented as owned by the `audit` module, where the identical shape is called `AuditEventHistoryEntry`.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session.

## 6. Endpoints

No endpoint added, changed, or retired. `applicants.applicant.list_history` returns the same fields it always did; only its implementation moved to audit's shared serializer.

## 7. Flows

No change this session.

## 8. Gaps

- Nothing new. The history shape's gaps are now audit's, listed above.

---

## Applicant Journeys

## 1. Module

- **Name:** applicant_journeys
- **Base path:** `/api/v1/journeys/`
- **Auth:** Bearer access token.

## 2. Conventions

No change this session.

## 3. Models

- **HistoryEntry** — no field change. Now documented as owned by the `audit` module.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session.

## 6. Endpoints

No endpoint added, changed, or retired. `applicant_journeys.journey.list_history` returns the same fields it always did.

## 7. Flows

No change this session.

## 8. Gaps

- Nothing new.

---

## Leads

## 1. Module

- **Name:** leads
- **Base path:** `/api/v1/leads/`
- **Auth:** Bearer access token.

## 2. Conventions

No change this session.

## 3. Models

- **HistoryEntry** — no field change. Now documented as owned by the `audit` module.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session.

## 6. Endpoints

No endpoint added, changed, or retired. `leads.lead.list_history` returns the same fields it always did.

## 7. Flows

No change this session.

## 8. Gaps

- Nothing new.

---

## Clients

## 1. Module

- **Name:** clients
- **Base path:** `/api/v1/clients/`
- **Auth:** Bearer access token. History is readable by a Lead Manager.

## 2. Conventions

No change this session.

## 3. Models

- **HistoryEvent** — `{ id, action, actor_type[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`
  - `actor_id` added this session. Owned by the `audit` module as `AuditEventHistoryEntry`.
  - `actor_id` is the acting user's UUID, `null` for system/AI actors. Prefer it over `actor_label` when linking to an account — the label is a snapshot of the username at the time and is never re-resolved.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session.

## 6. Endpoints

### Client history — `/api/v1/clients/<client_id>/history/`

**Use it when:** showing the history panel on Client Detail, including a past retirement after a restore.

**Methods:**
- `GET /api/v1/clients/<client_id>/history/` (`clients.client.list_history`) — response widened this session

**Send (create/update):** none.

**Returns:** `list[HistoryEvent]`, newest first, paginated.

**Notes:**
- Gained `actor_id`. Additive — no field was removed or renamed.
- Readable by a Lead Manager, unlike every write in this module.

**Errors:**
- `CLIENTS_CLIENT_NOT_FOUND` (404)
- `CLIENTS_ACTOR_FORBIDDEN` (403)

## 7. Flows

**Review a partner's history**
1. `GET /api/v1/clients/<client_id>/` → the client.
2. `GET /api/v1/clients/<client_id>/history/` → the trail, now with `actor_id` on each entry.
   - `CLIENTS_CLIENT_NOT_FOUND` → the id is unknown.

## 8. Gaps

- Nothing new. The history shape's gaps are audit's, listed above.

---

## Offers

## 1. Module

- **Name:** offers
- **Base path:** `/api/v1/offers/`
- **Auth:** Bearer access token. Admin and Lead Manager; Superadmin denied.

## 2. Conventions

No change this session.

## 3. Models

- **HistoryEvent** — `{ id, action, actor_type[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`
  - `actor_id` added this session. Owned by the `audit` module as `AuditEventHistoryEntry`.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session.

## 6. Endpoints

### Offer history — `/api/v1/offers/<offer_id>/history/`

**Use it when:** showing an offer's full trail, including its condition events.

**Methods:**
- `GET /api/v1/offers/<offer_id>/history/` (`offers.offer.list_history`) — response widened this session

**Send (create/update):** none.

**Returns:** `list[HistoryEvent]`, newest first, paginated.

**Notes:**
- Gained `actor_id`. Additive — no field was removed or renamed.
- Condition events appear here too, carrying `metadata.condition_id`; there is no separate condition history.

**Errors:**
- `OFFERS_OFFER_NOT_FOUND` (404)
- `OFFERS_ACTOR_FORBIDDEN` (403)

## 7. Flows

**Review an offer's trail**
1. `GET /api/v1/offers/<offer_id>/` → the offer.
2. `GET /api/v1/offers/<offer_id>/history/` → offer and condition events in one list, now with `actor_id`.
   - `OFFERS_OFFER_NOT_FOUND` → the id is unknown.

## 8. Gaps

- Nothing new.

---

## Documents

## 1. Module

- **Name:** documents
- **Base path:** `/api/v1/documents/`
- **Auth:** Bearer access token. Admin only on every route, reads included.

## 2. Conventions

No change this session.

## 3. Models

- **HistoryEvent** — `{ id, action, actor_type[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`
  - `actor_id` added this session. Owned by the `audit` module as `AuditEventHistoryEntry`.
  - The document body is still never present: a body change appears as `changes.content = { "from": "<changed>", "to": "<changed>" }`.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session.

## 6. Endpoints

### Document history — `/api/v1/documents/<document_id>/history/`

**Use it when:** showing who changed a document and when, on the document workspace.

**Methods:**
- `GET /api/v1/documents/<document_id>/history/` (`documents.document.list_history`) — response widened this session

**Send (create/update):** none.

**Returns:** `list[HistoryEvent]`, newest first, paginated.

**Notes:**
- Gained `actor_id`. Additive — no field was removed or renamed, and the shared shape adds no field that could carry a body.
- A body change is a marker only; a previous body cannot be recovered here.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)
- `DOCUMENTS_ACTOR_FORBIDDEN` (403)

## 7. Flows

**Review who changed a document**
1. `GET /api/v1/documents/<document_id>/` → the document.
2. `GET /api/v1/documents/<document_id>/history/` → the trail, now with `actor_id`.
   - `DOCUMENTS_DOCUMENT_NOT_FOUND` → the id is unknown.

## 8. Gaps

- Nothing new. Recovering a previous body still requires a `document_history` print snapshot, which is captured only by an explicit print.
