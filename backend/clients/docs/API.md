# API — Clients

**Owner app:** `clients`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-24
**Base prefix:** `/api/v1/clients/`
**Auth:** Bearer access JWT (`authenticate.SessionBoundJWTAuthentication`) on every endpoint
**Throttle:** project defaults only — `UserRateThrottle` at 1000/hour. No endpoint here is public, and none is expensive: the directory is a small bounded table, every list is paginated at 100 rows max, and the detail read prefetches its contact numbers in one query.
**Access level:** protected. Reads: Admin + Lead Manager. Writes: **Admin only**. Superadmin denied on every route including reads.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial API documentation — 7 endpoints across one resource |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | §1.7 history entries gained `actor_id` and are now serialized by audit's shared `AuditEventHistorySerializer` (`clients.client.list_history` → 1.1.0). Additive; no other endpoint changed |

---

## Access model (§9 interim inline pattern)

This app uses the interim inline access checks in `clients/access.py`. There is no `permissions.py`.

| Check | Applies to | Allows | Denies |
|-------|-----------|--------|--------|
| `require_client_reader` | every `GET` | `admin`, `lead_manager` | `superadmin` → 403 `CLIENTS_ACTOR_FORBIDDEN` |
| `require_admin` | every `POST` and `PATCH` | `admin` | `lead_manager`, `superadmin` → 403 `CLIENTS_ACTOR_FORBIDDEN` |

Applied per route by `ClientScopedView.resolve(..., check=...)` — the check is an argument rather than a class attribute so a read route and a write route on the same resource cannot accidentally share the wrong one. The split and its reasoning are in `docs/SECURITY.md` §1. **No endpoint in this app is public.**

**No `DELETE` method is exposed on any resource.** Withdrawal from use is `POST .../retire/`, which sets `status` to `inactive` and records why — see `DATA_CONTRACT.md` "Soft Delete".

---

## Error codes

All codes live in `clients/constants.py` `ErrorCode`.

| Code | HTTP | Meaning |
|------|------|---------|
| `CLIENTS_ACTOR_FORBIDDEN` | 403 | The caller's authority may not perform this action — a Lead Manager writing, or a Superadmin doing anything |
| `CLIENTS_CLIENT_NOT_FOUND` | 404 | No client with the id in the URL path |
| `CLIENTS_STATUS_IMMUTABLE` | 400 | A `PATCH` carried `status`, `status_note`, `retired_at`, or `retired_by` |
| `CLIENTS_STATUS_NOTE_REQUIRED` | 400 | Retire was called with a missing or blank reason |
| `CLIENTS_CLIENT_ALREADY_RETIRED` | 409 | Retire was called on an already-inactive client |
| `CLIENTS_CLIENT_NOT_RETIRED` | 409 | Restore was called on an active client |
| `CLIENTS_CONTACT_NUMBER_DUPLICATE` | 400 | The same number appears twice in one payload |

Serializer-level failures return the project-wide `VALIDATION_ERROR` (400) with the offending fields in `error.details`.

---

## Module-wide rules

These hold on every endpoint below and are not repeated per endpoint.

1. **Every mutation appends exactly one `audit.AuditEvent`**, carrying the actor, authority type, changed fields' previous and new values, and client IP.
2. **A `PATCH` that changes nothing writes no audit event** and still returns 200. Replacing `contact_numbers` always counts as a change, even when the resulting set is identical — the write path cannot compare sets without re-reading them, and a spurious event costs less than a missing one.
3. **`status` and the retirement fields are rejected, not ignored, on `PATCH`** — the inverse of the `institutions` convention. See `SECURITY.md` §3 for why this field warrants the louder treatment.
4. **No write in this app touches another app**, and no other app references a client. This module is an island in both directions.
5. **Query strings are validated** by `ClientSearchSerializer`; an unparseable filter is a 400 rather than an ignored parameter.
6. **`retired_at` carries a `_bs` sibling on read** (§39.4); `created_at` and `updated_at` do not. Writes accept no BS input anywhere.
7. **All user-entered text is Unicode-normalized on write** (§39.2) via `_NormalizedTextMixin` in `serializers.py`, and the two romanized fields are derived in the service layer (§39.3), never in a model or signal.

---

## 1. Client

### 1.1 List clients

- **URI:** `GET /api/v1/clients/`
- **Permission key:** `clients.client.list` (risk: low)
- **Auth:** required. Admin or Lead Manager.
- **Throttle:** project default.

**Query parameters:** `status` (enum, exact — omitting it returns both active and inactive); `search` (partial match, see the access pattern below); `fiscal_year` (`YYYY/YY`, filtered on `created_at`); `page`, `page_size`.

**Response:** paginated list of the Client list shape — see `INTEGRATION.md` §4.

**Query access pattern.** `selectors.get_clients` applies `select_related("created_by")` and `prefetch_related("contact_numbers")`. The prefetch is required, not an optimisation: every row reports `primary_contact_number`, so without it the list is N+1. `ClientListSerializer.get_primary_contact_number` reads from the prefetched relation and never queries — model ordering is `-is_primary`, `created_at`, so the first row is already the right one.

`selectors.search_clients` matches six fields with OR `icontains` semantics: the organization's `name_np` / `name_en` / `name_romanized` **and** the spokesperson's three. The organization triple is trigram-indexed (`client_name_{np,en,rom}_trgm_idx`); **the spokesperson triple deliberately is not.** The directory is a bounded table of partner organizations — tens to hundreds of rows — unlike `leads`, which grows without limit, and six GIN indexes on a table this size cost more in write overhead and disk than they save. The growth condition that would change this: a few thousand rows. The selector is already written to use the indexes if they are added.

The `status` filter is served by `client_status_name_idx`, which also covers the fixed `name_np` ordering.

**Business rules:** none beyond access. The directory is shared — no owner scoping.

**Error codes:** `CLIENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR` (bad filter).

**AI debugging notes:** if a retired client "will not disappear" from a list, check whether the caller passed `status` at all. Omitting it is not the same as `status=active` — the API returns both by design, because the concept requires retired partners to stay visible historically and leaves the presentation choice to the client.

### 1.2 Add a client

- **URI:** `POST /api/v1/clients/`
- **Permission key:** `clients.client.create` (risk: medium)
- **Auth:** required. **Admin only.**

**Request:** `name_np` (required); optional `name_en`, `name_romanized`, the four spokesperson fields, `email`, `website`, `logo_url`, `address`, `notes`, and `contact_numbers`.

```json
{
  "name_np": "हिमाल एजुकेशन",
  "name_en": "Himal Education",
  "spokesperson_name_np": "सुनिता श्रेष्ठ",
  "spokesperson_designation": "Managing Director",
  "email": "info@himal.example",
  "website": "https://himal.example",
  "contact_numbers": [
    { "number": "9801111111", "label": "mobile", "is_primary": true },
    { "number": "014567890", "label": "work" }
  ]
}
```

**Response:** 201 with the Client detail shape — see `DATA_CONTRACT.md` §1 "Example".

**Validation rules:** `DATA_CONTRACT.md` §1 and §2 "Validation Rules". The romanization itself is in `services._apply_name_fields`, which walks the `_ROMANIZED_PAIRS` table so the organization name and the spokesperson name can never drift into being handled differently.

**Business rules:** the client and its contact numbers are created in one transaction. `status` is always `active` on creation and is not accepted from the request.

**Error codes:** `CLIENTS_CONTACT_NUMBER_DUPLICATE`, `CLIENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

**AI debugging notes:** a caller reporting that `name_romanized` "looks wrong" is usually reading it as a display field. It is a search index — `"हिमाल एजुकेशन"` correctly becomes `"himala ejukesana"`, which no human would write. Point them at `name_en`.

### 1.3 Retrieve a client

- **URI:** `GET /api/v1/clients/<client_id>/`
- **Permission key:** `clients.client.read` (risk: low)
- **Auth:** required. Admin or Lead Manager.

**Response:** the Client detail shape, with `contact_numbers` nested.

**Query access pattern.** `selectors.get_client_by_id` adds `retired_by` to the list relations and prefetches `contact_numbers`, so rendering the full detail screen — including who retired the client — is a fixed small number of queries regardless of how many numbers it has.

**Error codes:** `CLIENTS_CLIENT_NOT_FOUND`, `CLIENTS_ACTOR_FORBIDDEN`.

### 1.4 Correct a client

- **URI:** `PATCH /api/v1/clients/<client_id>/`
- **Permission key:** `clients.client.update` (risk: medium)
- **Auth:** required. **Admin only.**

**Request:** any subset of the writable fields. `name_np` becomes optional here.

**Response:** 200 with the Client detail shape.

**Business rules:**
- The immutable-field guard runs in the view **before** serializer validation, so a request carrying both a legal and an illegal field is rejected whole — a partial apply would be worse than a refusal.
- **`contact_numbers` distinguishes `null` from `[]`.** The view pops it with a `None` sentinel: absent means "leave them alone", `[]` means "clear them". Collapsing the two would make it impossible to edit a client's notes without either wiping or duplicating its numbers.
- Renaming re-derives the affected romanized field, unless the caller supplies one.

**Error codes:** `CLIENTS_STATUS_IMMUTABLE`, `CLIENTS_CONTACT_NUMBER_DUPLICATE`, `CLIENTS_CLIENT_NOT_FOUND`, `CLIENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.5 Retire a client

- **URI:** `POST /api/v1/clients/<client_id>/retire/`
- **Permission key:** `clients.client.retire` (risk: medium)
- **Auth:** required. **Admin only.**

**Request:** `{ "reason": "Partnership agreement ended." }` — required, non-empty.

**Response:** 200 with the Client detail shape: `status: "inactive"`, `status_note` set, `retired_at` / `retired_by` stamped.

**Business rules:** only an `active` client may be retired. The reason is mandatory because inactive clients are kept forever, so "why is this one inactive" must be answerable from the record rather than from someone's memory of how the relationship ended. Retiring does **not** remove the client from unfiltered list results.

**Error codes:** `CLIENTS_CLIENT_ALREADY_RETIRED` (409), `CLIENTS_STATUS_NOTE_REQUIRED`, `CLIENTS_CLIENT_NOT_FOUND`, `CLIENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

**AI debugging notes:** a blank-string reason fails at the serializer with `VALIDATION_ERROR` (`CharField` rejects `""`), while a whitespace-only reason reaches the service and fails with `CLIENTS_STATUS_NOTE_REQUIRED`. Both are 400; the codes differ because the layers differ.

### 1.6 Restore a client

- **URI:** `POST /api/v1/clients/<client_id>/restore/`
- **Permission key:** `clients.client.restore` (risk: medium)
- **Auth:** required. **Admin only.**

**Request:** empty body.

**Response:** 200 with the Client detail shape: `status: "active"`, `status_note` cleared, `retired_at` and `retired_by` set to `null`.

**Business rules:** only an `inactive` client may be restored. Clearing the denormalized retirement fields does not erase the retirement from history — `client_retired` and its reason stay in the audit log, which is where "have we worked with them before, and how did it end?" is answered.

**Error codes:** `CLIENTS_CLIENT_NOT_RETIRED` (409), `CLIENTS_CLIENT_NOT_FOUND`, `CLIENTS_ACTOR_FORBIDDEN`.

### 1.7 Client history

- **URI:** `GET /api/v1/clients/<client_id>/history/`
- **Permission key:** `clients.client.list_history` (risk: low)
- **Auth:** required. Admin or Lead Manager — **readable by a Lead Manager, unlike every write here.**

**Response:** paginated list of HistoryEvent, newest first — serialized by `audit.serializers.AuditEventHistorySerializer`, the shape shared by every module's history endpoint. Includes `actor_id` as of version 1.1.0.

**Query access pattern.** `selectors.get_history_for_client` delegates to `audit.selectors.get_events_for_entity` with `entity_type="client"`, `entity_id=<client id>`, `app_label="clients"` — served by the audit table's composite `(entity_type, entity_id)` index. Contact-number changes appear here as a marker on the parent client's `client_updated` event (`changes.contact_numbers`), not as separate events, because a number has no identity a reader would recognise on its own.

**Error codes:** `CLIENTS_CLIENT_NOT_FOUND`, `CLIENTS_ACTOR_FORBIDDEN`.
