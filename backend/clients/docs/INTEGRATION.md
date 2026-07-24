# Integration — Clients

**Owner app:** `clients`
**Version:** 1.2.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial integration contract — 7 endpoints, one resource |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | History entries gained `actor_id` (`clients.client.list_history` → 1.1.0). The shape is now owned by the `audit` module and shared by all six modules that expose a history endpoint; three of them, this one included, had been omitting `actor_id`. Additive, so no consumer breaks. §2 `Requires` corrected: the `audit` coupling is a read dependency as well as a write one |
| 1.2.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (`name`, `spokesperson_name`). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |

---

## 1. Module

- **Name:** Clients — the consultancy's B2B partner directory. The agencies, schools, and companies that refer or send applicants, with the contact details staff need to reach them. It is **a reference directory, not a CRM**: no pipelines, deals, commissions, tasks, or communication history.
- **Base path:** `/api/v1/clients/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. Two authority types may use this module — `admin` and `lead_manager` — with **different** rights: see §3. A `superadmin` token is rejected with 403 everywhere, including on reads.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which decides both whether the caller may act and whether they may write. | Every endpoint returns 401; a `superadmin` gets 403 `CLIENTS_ACTOR_FORBIDDEN` on every route including reads. |
| `authenticate` | FK | `created_by` (`PROTECT`) and `retired_by` (`SET_NULL`) reference user accounts. | Clients could not record who added or retired them. |
| `audit` | service call + read shape | Every create, update, retire, and restore appends one immutable event carrying the changed fields' previous and new values. This module stores no history of its own: the history endpoint reads audit's selector and renders audit's shared entry shape. | Hard dependency in both directions of use — without it this module does not start. If only the write path failed, client edits would still succeed but leave no trace, and `GET /clients/<id>/history/` would return an empty list rather than an error. |

**This module depends on no business app, and no business app depends on it.** It is the only app in the project with no edge in either direction — the position `institutions` held until `offers` shipped. In practice that means a client directory can be built, browsed, and maintained entirely on its own.

**The consequence you need to know about: attribution is not built.** `concepts/clients.txt` describes clients as supplying "the reference record used by other workflows" for recording where a referred lead came from. **Nothing consumes it yet.** There is no `client` field on a lead, no `?client=` filter on the lead list, and no endpoint anywhere that records or reports which partner sent an applicant. The directory exists; the link does not. Do not build a UI that implies otherwise — see §9.

## 3. Conventions

- **Access split — the single most important thing about this module.** Reads are shared, writes are Admin-only:
  - `GET` on any route (list, detail, history): `admin` and `lead_manager`.
  - `POST` / `PATCH` on any route (create, update, retire, restore): `admin` **only**. A `lead_manager` receives 403 `CLIENTS_ACTOR_FORBIDDEN`.
  - `superadmin`: 403 on everything, reads included.

  **Only `institutions` shares this shape.** `applicants`, `applicant_journeys`, and `offers` grant reads and writes to the same population, so do not carry an assumption in either direction between modules — check each one's §3. A directory screen should hide or disable its write controls for a Lead Manager rather than let them fail.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint in this module**, and no way to remove a client or a contact number outright. A partner the consultancy has stopped working with is *retired* — `status: "inactive"` with a mandatory reason. Do not build a delete button; build a "retire" control.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is **abridged to three fields to show the envelope**; a real create returns the full `Client` shape defined in §4.

```json
{
  "success": true,
  "message": "Client added.",
  "data": { "id": "6d7e8f90-1a2b-4c3d-9e4f-5061728394a5", "status": "active" },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract, and may change without a version bump. Branch on the HTTP status and, for errors, on `error.code`.

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object that is always present — `{}` when there are no field-level errors.

```json
{
  "success": false,
  "error": {
    "code": "CLIENTS_CLIENT_ALREADY_RETIRED",
    "message": "This client is already retired.",
    "details": {}
  },
  "meta": {}
}
```

Field-level validation failures come from the serializer layer and put the offending fields inside `details`:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { }
  },
  "meta": {}
}
```

- **HTTP status codes:** `POST /clients/` returns **201**. Every other success — `GET`, `PATCH`, retire, restore — returns **200**. Domain-rule violations are **400**, except standing conflicts (retiring a retired client, restoring an active one), which are **409**. Missing records named in the URL path are **404**. Authority failures are **403**. An unrouted method is **405** with the project-wide `METHOD_NOT_ALLOWED` code, still inside the standard envelope.
- **Auth failures:** 401 with no token, an expired token, or a revoked session — produced by the authentication framework. 403 `CLIENTS_ACTOR_FORBIDDEN` when the token is valid but the authority may not perform that action. Its body:

```json
{
  "success": false,
  "error": {
    "code": "CLIENTS_ACTOR_FORBIDDEN",
    "message": "Admin authority is required to maintain the client directory.",
    "details": {}
  },
  "meta": {}
}
```

  The `message` is `"Admin authority is required to maintain the client directory."` for a write refused to a Lead Manager, and `"This authority may not access client records."` for a Superadmin refused a read. **Branch on `code`, never on `message`** — the two refusals share one code.

  **This module's 403 code replaces the project-wide `PERMISSION_DENIED`, it does not coexist with it.** You will not see `PERMISSION_DENIED` from `/api/v1/clients/`. It is omitted from the per-endpoint `Errors` lists in §7, since it applies identically to all seven.

- **`status` and the retirement fields are REJECTED on `PATCH`, not ignored.** Sending `status`, `status_note`, `retired_at`, or `retired_by` to the update endpoint returns 400 `CLIENTS_STATUS_IMMUTABLE` with every offending field listed in `details`. Standing moves only through the retire and restore actions. **This differs from `institutions`**, which silently drops immutable fields so a read-modify-write-the-whole-object edit form works. Here such a form will fail on every save: send only the fields the user actually changed.
- **A `PATCH` that changes nothing writes no audit event.** The response is still 200 with the unchanged record. A UI reporting "saved, history updated" after an unchanged submit will be claiming something that did not happen. **Exception:** sending `contact_numbers` always counts as a change, even when the resulting set is identical.
- **Contact numbers are a replacement set, and `null` ≠ `[]`.** Sending `contact_numbers` replaces every number the client has — the payload is the complete set it should hold afterwards, not an addition. **Omitting the key** leaves the existing numbers alone; **sending `[]`** clears them. There are no per-number endpoints; a number has an `id` on read, but you never address it.
- **Query parameter encoding.** Invalid query parameters are **rejected with 400, not ignored** — `?status=retired` (not a valid value; use `inactive`) returns a validation error rather than an unfiltered result set. `page_size` above the 100 maximum is clamped, not rejected.
- **Request encoding:** `application/json`.
- **Pagination:** page-number based. Params `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `next`/`previous` are absolute URLs including scheme and host, or `null`. Applied to both list endpoints (the directory and the history).
- **IDs:** UUID strings. There is **no human-readable code** on a client, unlike `institutions.Country` or `leads.LeadSource` — always address a client by `id`.
- **Ordering** is fixed and **not client-controllable** — there is no `sort` or `ordering` parameter. The directory is ordered by `name` **alphabetically**, not newest-first. This is the opposite of every other list in the project; nobody looks up a partner by when it was added. History is newest-first.
- **Times.** System timestamps — `created_at`, `updated_at` — are ISO 8601 UTC with **no** `_bs` sibling. `retired_at` **does** carry one, `retired_at_bs` (§39.4), because it is a date staff act on. It is an object or `null`, never a string: `{ year, month, day, month_name, display }`. There is no BS input anywhere.
- **Empty text fields are `""`, never `null`.** The nullable fields are `retired_at`, `retired_by_username`, and `primary_contact_number` on the list shape.

## 4. Models

**Client (list shape)** — `{ id, name, spokesperson_name, email, primary_contact_number?, status:[enum], is_active, logo_url, updated_at }`

- `primary_contact_number` is a **flat string or `null`**, not an object — the number flagged primary, else the first recorded, else `null`. It exists so the directory can show a phone column without fetching every client's detail.
- The list deliberately omits `website`, `address`, `notes`, the spokesperson's designation, and the full number list. Fetch the detail for those.

**Client (detail shape)** — `{ id, name, spokesperson_name, spokesperson_designation, email, website, logo_url, address, contact_numbers:list[ContactNumber], status:[enum], is_active, status_note, retired_at?, retired_at_bs?:json, retired_by_username?, notes, created_by_username, created_at, updated_at }`

- Returned by retrieve, create, update, retire, **and** restore. Only the list returns the shorter shape.
- **`name` is the organization's name and `spokesperson_name` the contact person's** — both plain English fields. Search covers both.
- `status_note` is non-empty only when `status` is `inactive`. Restoring clears it.
- `address` is one free-text field, not a structured object — unlike `applicants`, which has province/district/municipality/ward.

**ContactNumber** — `{ id, number, label:[enum], is_primary }`

- Read-only in this shape. On write, send `{ number, label?, is_primary? }` — the `id` is not accepted and not needed, because numbers are replaced as a set.
- `is_primary` is **not enforced to be unique or present.** A client may have zero primary numbers, or several. Ordering puts primaries first, so `contact_numbers[0]` is the sensible one to show.

**HistoryEvent** — `{ id, action, actor_type:[enum], actor_id:uuid|null, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`

- Owned by the `audit` module, where the same shape is called **AuditEventHistoryEntry** (`audit/docs/INTEGRATION.md` §4). This app renders it; it does not define it. Every module's `/history/` endpoint returns this identical shape.
- `actor_id` is the UUID of the acting user, or `null` for system/AI actors. Prefer it over `actor_label` when linking to an account — the label is a preserved snapshot of the username at the time and is not re-resolved if the account is renamed.
- `changes` is a map of field name to `{ "from": "...", "to": "..." }`, both stringified. `{}` on creation events.
- A contact-number replacement appears as `changes.contact_numbers = { "from": "replaced", "to": "N number(s)" }` — a marker, **not** a before/after list of the numbers themselves.
- `metadata` is free-form per action — do not rely on a key being present without checking.

### Worked examples

**Client (detail shape), active**

```json
{
  "id": "6d7e8f90-1a2b-4c3d-9e4f-5061728394a5",
  "name": "Himal Education",
  "spokesperson_name": "Sunita Shrestha",
  "spokesperson_designation": "Managing Director",
  "email": "info@himal.example",
  "website": "https://himal.example",
  "logo_url": "https://himal.example/logo.png",
  "address": "Putalisadak, Kathmandu",
  "contact_numbers": [
    { "id": "7e8f9012-2b3c-4d5e-af60-718293a4b5c6", "number": "9801111111", "label": "mobile", "is_primary": true },
    { "id": "8f901234-3c4d-4e5f-b071-8293a4b5c6d7", "number": "014567890", "label": "work", "is_primary": false }
  ],
  "status": "active",
  "is_active": true,
  "status_note": "",
  "retired_at": null,
  "retired_at_bs": null,
  "retired_by_username": null,
  "notes": "Refers mostly nursing applicants.",
  "created_by_username": "adminuser",
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T09:18:47Z"
}
```

**Client (detail shape), retired**

```json
{
  "id": "9012a3b4-4d5e-4f60-8192-a3b4c5d6e7f8",
  "name": "",
  "spokesperson_name": "",
  "spokesperson_designation": "",
  "email": "",
  "website": "",
  "logo_url": "",
  "address": "",
  "contact_numbers": [],
  "status": "inactive",
  "is_active": false,
  "status_note": "Partnership agreement ended in Shrawan 2083.",
  "retired_at": "2026-07-24T10:02:00Z",
  "retired_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name": "Shrawan",
    "display": "2083 Shrawan 8"
  },
  "retired_by_username": "adminuser",
  "notes": "",
  "created_by_username": "adminuser",
  "created_at": "2026-07-20T04:11:23Z",
  "updated_at": "2026-07-24T10:02:00Z"
}
```

## 5. Enums

- `Client.status`: `active` | `inactive`
  - **There is no `paused` or `archived`.** A partner is either offered as a current contact or not; the *reason* lives in `status_note` as free text. If a UI wants a "paused" badge it must define the rule itself.
  - **`inactive` does not mean hidden.** A retired client is still returned by the unfiltered list — the concept requires that retired partners stay "visible historically but not treated as a preferred current contact", and which of those two the UI does is a presentation decision the API leaves open.
- `ContactNumber.label`: `mobile` | `home` | `work` | `whatsapp` | `viber` | `other`. **The same value set as `leads` and `applicants` contact numbers**, deliberately.
- `HistoryEvent.action`: `client_created` | `client_updated` | `client_retired` | `client_restored`
- `HistoryEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai` — the `audit` module's enum. In practice only `admin` appears here, since only Admins can write.
- `spokesperson_designation`: **not an enum** — free text.

## 6. Dependency order

- `Client` needs nothing. It is a root: no parent record, no external reference, no prerequisite.
- `ContactNumber` needs a `Client`, but is never created independently — it arrives inside the client payload.

**Start here:** `POST /api/v1/clients/` as an Admin. This is the only module in the project you can populate from a completely empty database without touching anything else.

## 7. Endpoints

### Client — `/api/v1/clients/`

**Use it when:** the Client List directory, the Client Detail screen, and the New / Edit Client form.

**Methods:**
- `GET /api/v1/clients/` — list (permission: `clients.client.list`, risk: low)
- `POST /api/v1/clients/` — create (permission: `clients.client.create`, risk: medium)
- `GET /api/v1/clients/<client_id>/` — retrieve (permission: `clients.client.read`, risk: low)
- `PATCH /api/v1/clients/<client_id>/` — update (permission: `clients.client.update`, risk: medium)

**Send (create/update):**
- create: `name` (**required**), plus optional `name`, `name`, `spokesperson_name`, `spokesperson_name`, `spokesperson_name`, `spokesperson_designation`, `email`, `website`, `logo_url`, `address`, `notes`, `contact_numbers`
- update: any subset of the same fields (`name` becomes optional) — **and nothing else**

**Returns:** Client (detail shape) for create, retrieve, and update; list[Client (list shape)] for the list, paginated.

**Requires state:** nothing. A client is a root record with no prerequisite.

**Side effects:** appends `client_created` / `client_updated` to the central audit log, recording each changed field's previous and new value. Nothing outside this module changes — there is nothing outside this module that references a client.

**Notes:**
- **Query params:** `status` (exact enum), `search` (partial match), `fiscal_year` (`YYYY/YY`, Nepali fiscal year, filtered on `created_at`), `page`, `page_size`.
- **`search` covers six fields:** the organization's `name`, `name`, and `name`, **and** the spokesperson's three name fields. One box finds either the company or the person, which is what the directory is for.
- **Omitting `status` returns both active and inactive clients.** Pass `status=active` for a picker; leave it off for the maintenance directory.
- **`name` and `spokesperson_name` are auto-derived** from their `_np` source when you do not send them. Send one only to override a poor transliteration — a supplied value is never overwritten, including on a later edit.
- **Only `name` is required.** Everything else, including the spokesperson and any contact number, is optional: a partner may be an organization you deal with before you know who to ask for.
- **Sending `status` on update is a 400**, not a silent no-op. See §3.
- Defaults for omitted write fields: `status` → `"active"`, every text field → `""`, `contact_numbers` → `[]` on create.
- There is no delete.

**Errors:**
- `CLIENTS_STATUS_IMMUTABLE` (400) — a `PATCH` carried `status`, `status_note`, `retired_at`, or `retired_by`
- `CLIENTS_CONTACT_NUMBER_DUPLICATE` (400) — the same number appears twice in one payload
- `CLIENTS_CLIENT_NOT_FOUND` (404) — no client with that id

### Client: retire — `/api/v1/clients/<client_id>/retire/`

**Use it when:** the Client Detail screen's "retire" action — the relationship has ended or paused.

**Methods:**
- `POST /api/v1/clients/<client_id>/retire/` — (permission: `clients.client.retire`, risk: medium)

**Send:** `reason` (**required**, non-empty).

**Returns:** Client (detail shape), with `status: "inactive"`, `status_note` set to the reason, and `retired_at` / `retired_by_username` stamped.

**Requires state:** the client's `status` must be `active`.

**Side effects:** appends `client_retired` to the audit log with the reason attached. **The client remains in the directory and in unfiltered list results** — retiring is not hiding.

**Notes:**
- **The reason is mandatory and there is no way around it.** Retired clients are kept forever, so "why is this one inactive" has to be answerable from the record rather than from someone's memory.
- Retiring is reversible — see restore. The retirement stays in the history either way.

**Errors:**
- `CLIENTS_CLIENT_ALREADY_RETIRED` (409) — the client is already inactive
- `CLIENTS_STATUS_NOTE_REQUIRED` (400) — reason missing or blank
- `CLIENTS_CLIENT_NOT_FOUND` (404)

### Client: restore — `/api/v1/clients/<client_id>/restore/`

**Use it when:** the Client Detail screen's "restore" action — the consultancy is working with this partner again.

**Methods:**
- `POST /api/v1/clients/<client_id>/restore/` — (permission: `clients.client.restore`, risk: medium)

**Send:** nothing. An empty JSON object is fine.

**Returns:** Client (detail shape), with `status: "active"` and `status_note`, `retired_at`, `retired_by_username` all cleared.

**Requires state:** the client's `status` must be `inactive`.

**Side effects:** appends `client_restored` to the audit log. **Clearing the retirement fields does not erase the retirement from history** — `client_retired`, with its reason, stays in the history endpoint forever. That is where "have we worked with them before, and did it end badly?" is answered.

**Errors:**
- `CLIENTS_CLIENT_NOT_RETIRED` (409) — the client is already active
- `CLIENTS_CLIENT_NOT_FOUND` (404)

### Client: history — `/api/v1/clients/<client_id>/history/`

**Use it when:** the history / audit-trail panel on the Client Detail screen.

**Methods:**
- `GET /api/v1/clients/<client_id>/history/` — (permission: `clients.client.list_history`, risk: low)

**Send:** nothing.

**Returns:** list[HistoryEvent], newest first, paginated.

**Requires state:** the client must exist.

**Side effects:** none.

**Notes:**
- **Readable by a Lead Manager**, unlike every write in this module.
- Never empty for an existing client — creation always writes one event.
- This is the only place a retired-then-restored client's past retirement is visible.

**Errors:**
- `CLIENTS_CLIENT_NOT_FOUND` (404)

## 8. Flows

**Add a partner to the directory** *(Admin)*

1. `POST /api/v1/clients/` with `name`, the spokesperson, and a `contact_numbers` array. → client id, `status: "active"`.
   - Missing `name` → 400 `VALIDATION_ERROR` with `details.name`.
   - The same number listed twice → 400 `CLIENTS_CONTACT_NUMBER_DUPLICATE`.
   - Called by a Lead Manager → 403 `CLIENTS_ACTOR_FORBIDDEN`. Hide the "add client" button for them.
2. Read back `name` from the response and **do not display it** — it is the search index, and it will look wrong to a human.

**Find the right partner** *(Admin or Lead Manager)*

1. `GET /api/v1/clients/?status=active&search=<query>` — one box searches both the company name and the spokesperson's.
2. Render `primary_contact_number` and `email` straight from the list row; no detail fetch needed for a phone-and-email directory.
3. `GET /api/v1/clients/<id>/` for the full record — the other numbers, website, address, and notes.
   - A Lead Manager can do all of this. Only the edit controls are refused.

**Retire and later restore a partner** *(Admin)*

1. `POST /api/v1/clients/<id>/retire/` with a reason. → `status: "inactive"`, `retired_at` stamped.
   - No reason → 400 `CLIENTS_STATUS_NOTE_REQUIRED`. Make the reason input mandatory before submit.
   - Already retired → 409 `CLIENTS_CLIENT_ALREADY_RETIRED`; refetch, someone else did it.
2. The client **still appears** in `GET /api/v1/clients/` with no `status` filter. Grey it out or move it to an "inactive" section — do not expect the API to hide it.
3. `POST /api/v1/clients/<id>/restore/` → `status: "active"`, retirement fields cleared.
4. `GET /api/v1/clients/<id>/history/` still shows `client_retired` with the original reason.

**Correct a partner's contact details** *(Admin)*

1. `GET /api/v1/clients/<id>/` for the current record.
2. `PATCH /api/v1/clients/<id>/` with **only the changed fields**.
   - Sending the whole object back, including `status`, → 400 `CLIENTS_STATUS_IMMUTABLE`. This module rejects immutable fields rather than dropping them, unlike `institutions`.
   - To change the numbers, send the **complete** new `contact_numbers` array — it replaces, it does not append. To clear them, send `[]`. To leave them alone, omit the key.
3. A `PATCH` that changed nothing returns 200 and writes no history event.

## 9. Gaps

- **Attribution is not built — the largest gap, and the reason this module exists.** `concepts/clients.txt` describes clients supplying the reference record for "which organizations are sending work". There is **no `client` field on a lead or an applicant**, no `?client=` filter anywhere, and no referral count, statistic, or report. A client record cannot currently be connected to a single person the partner referred. Building it means changing the `leads` app and is a separate piece of work.
- **No `client_type`.** Agencies, schools, and partner companies are all the same shape here, and cannot be filtered apart.
- **The logo is an unvalidated external URL.** `logo_url` is stored as given, never fetched or checked for reachability, and points at a third-party host. Rendering it in an `<img>` leaks a referrer and displays whatever that host serves. Format validation is not safety validation.
- **`is_primary` on a contact number is neither unique nor required.** A client may have zero primary numbers or three. Sort order puts primaries first, so use `contact_numbers[0]`; do not assume exactly one.
- **Contact-number history is a marker, not a diff.** The audit event records `{ "from": "replaced", "to": "N number(s)" }` — you cannot recover which number was removed or added from the history.
- **The address is unstructured.** One free-text field, unlike `applicants`' province/district/municipality/ward. No geographic filtering or grouping is possible.
- **No duplicate detection.** Two clients may have identical names, emails, and numbers with no warning. If the UI wants to guard against a double entry it must check the list itself before submitting.
- **Only the organization-name fields are trigram-indexed**, though search also covers the spokesperson names. Deliberate — the directory is a small bounded table — but the spokesperson half of a search is a sequential scan. Not a concern at the intended scale; worth revisiting past a few thousand rows.
- **No bulk import.** Partners are added one at a time through the API; there is no CSV path and no management command.
