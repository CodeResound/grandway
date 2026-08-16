# Integration — Grandway Backend

**Owner app:** `core`
**Version:** 1.13.0
**Status:** Active
**Created:** 2026-07-21
**Purpose:** The entry point for anyone — human or AI — integrating a client against this backend from outside the repository. Read this file first, then the per-app `INTEGRATION.md` for each app you consume.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-21 | AI (Claude Opus 4.8) | Initial project-level integration entry point |
| 1.1.0 | 2026-07-22 | AI (Claude Opus 4.8) | `authenticate` app shipped: real token-issuance (login/refresh) now exists — removed the stale "not callable" warning; added `authenticate` to the inventory and dependency graph |
| 1.2.0 | 2026-07-24 | AI (Claude) | Backfilled the rows missing for `audit`, `leads`, `applicants`, and `applicant_journeys`, which had entered the inventory and dependency graph without a change-history entry. Added `institutions` (`/api/v1/catalogue/`) to both, noted it as the first app whose read and write populations differ, completed the global error-code list, and warned that an app may replace a global code with its own |
| 1.3.0 | 2026-07-24 | AI (Claude) | Added `offers` (`/api/v1/offers/`) to the inventory and dependency graph. **Retracted the "`institutions` is deliberately an island" claim in §7** — `offers` is the first app to reference both the catalogue and a journey, so the statement is no longer true. Noted in §10 that immutable-field handling now differs per app (`institutions` ignores, `offers` rejects) |
| 1.4.0 | 2026-07-24 | AI (Claude) | Added `clients` (`/api/v1/clients/`) to the inventory and dependency graph — the only app with no business-app edge in either direction. Recorded that it is the second app with the read-shared/write-Admin split, and that its concept's attribution flow has no endpoints behind it |
| 1.5.0 | 2026-07-24 | AI (Claude) | Added `documents` (`/api/v1/documents/`) to the inventory and dependency graph. **A third distinct access model now exists** — Admin-only, reads included — so §10's access warning is rewritten around three shapes rather than two. Recorded that three named document domains remain unbuilt, and that `documents` is the first app to store a client-owned opaque body |
| 1.6.0 | 2026-07-24 | AI (Claude) | Added `document_history` (`/api/v1/document-history/`) to the inventory and dependency graph — the second Admin-only app and the holder of one of only two cross-app writes in the project. **Added a `Superadmin` column to §10's access table**: no business app grants a superadmin anything, which the table had never stated and a §19.5 comprehension test found a reader would get wrong. Narrowed the unbuilt-document-domains note from three apps to two |
| 1.6.1 | 2026-07-24 | AI (Claude) | No inventory change. Stated the global `page_size` clamping rule in §3, which was previously only documented per-app and left a reader to assume an over-maximum value is rejected |
| 1.7.0 | 2026-07-24 | AI (Claude) | Added `document_templates` (`/api/v1/document-templates/`) to the inventory and dependency graph — the third Admin-only app, and the only one in the document stack holding no applicant data. Recorded that the document stack's three modules are coupled far more weakly than they look, and that **two cross-module references travel as bare strings inside JSON with nothing validating either**. Narrowed the unbuilt-document-domains note from two apps to one (`uploaded_files`). **A §19.5 review caught that v1.6.1 had added an entire app to §6/§7 without a change-history entry** — the exact defect v1.2.0 was written to fix; this row closes it |
| 1.8.0 | 2026-07-24 | AI (Claude) | Added `uploaded_files` (`/api/v1/files/`) to the inventory (§6) and dependency graph (§7) — **the project's first and only byte storage**, and the app with the most dependencies of any module (five business apps by FK plus the local filesystem). Recorded a **fourth access shape** (§10): shared read/write with three Admin-only actions, plus a per-record visibility rule that makes `document`- and `snapshot`-owned files Admin-only. **A §19.5 review of that app caught a real authorization leak** — the file ledger was a side door around the document stack's Admin-only rule — which was fixed in code before this row was written. Closed the "one named document domain is still unbuilt" gap |
| 1.9.0 | 2026-07-24 | AI (Claude Opus 4.8) | Added `checklists` (`/api/v1/checklists/`) to the inventory (§6), dependency graph (§7), and the fourth access shape (§10). **The graph's first signal edge** — setting a journey's country creates a checklist with no endpoint call, and the journeys app never learns checklists exist — so §7 now warns that the trigger is invisible from the app that fires it and asynchronous relative to its response. **Retracted the "no module points at a file" gap in §9**: a checklist item's `evidence_file` is the first inbound reference to `uploaded_files`, and it is `PROTECT`. Recorded that `checklists` splits authority on a different axis from `uploaded_files` — policy authoring versus judgement actions |
| 1.10.0 | 2026-07-24 | AI (Claude Opus 4.8) | Added `dashboards` (`/api/v1/dashboard/`) to the inventory (§6) and dependency graph (§7) — **the first app that owns no table, writes nothing, and is depended on by nobody**, and the only one reading nine other modules. §7 now records that its edges invert the graph's usual shape: every other dependency exists so an app can own something, while this one exists purely to read. Also recorded the consequence a §19.5 reader would otherwise get wrong — **its figures inherit each owning app's scoping and are therefore not uniformly scoped**, so an Admin and a Lead Manager calling the same URL legitimately see different numbers. Separately, `applicants` and `leads` bumped their list endpoints to 1.1.0 (widened search, relevance ordering, destination filters) |
| 1.11.0 | 2026-07-24 | AI (Claude Opus 4.8) | Added `notifications` (`/api/v1/notifications/`) to the inventory (§6) and dependency graph (§7) — **the first app whose reads are scoped to the calling user**, which made it a fifth access shape in §10 rather than a variant of an existing one. Three §10 statements were falsified by it and are corrected here, all caught by the §19.5 consumer review reading the contract cold: the universal claim that **"every other app's 404 means genuinely absent"** (three apps now return 404 for out-of-scope records, not one); `uploaded_files` being **"the only app that scopes per record"** (now narrowed — it scopes by owning *record*, `notifications` by calling *user*, and they are different mechanisms); and the app's absence from the §10 access table entirely, which left "what can a Lead Manager see in notifications" unanswerable from the entry point. The same review found this file had shipped `dashboards` into §6/§7 with no change-history row — the third recurrence of that omission, and the reason this row exists |
| 1.12.0 | 2026-08-02 | AI (Claude Opus 5) | Added `search` (`/api/v1/search/`) to the inventory (§6) and dependency graph (§7) — **the second app that owns no table and writes nothing**, which falsified the standing claim that `dashboards` was the only one; that row is corrected here rather than left to be discovered. §7's "`dashboards` inverts the shape of every other edge" note now covers both apps, and its scoping consequence records that `search` inherits per-app scoping the same way — its `lead` bucket is owner-scoped and its `uploaded_file` bucket applies that app's visibility rule, while its other seven buckets are not narrowed, **and unlike `dashboards` nothing in the response marks which is which**. Also fixes a stale header: this file read `**Version:** 1.10.0` while its change history already recorded 1.11.0 |
| 1.13.0 | 2026-08-17 | AI (Claude) | Added `reminders` (`/api/v1/reminders/`) to the inventory (§6) and dependency graph (§7) — staff-set, date-only follow-up notes against an applicant or client, surfaced as Admin-only alerts by the notifications nightly sweep. The `notifications` edge in §7 gains its fourth sweep-read (`reminders` — the first whose rows exist *only* to be swept), and `clients` **is no longer the graph's only island**: a reminder may hold a `PROTECT` FK to a client, the first business-app edge `clients` has ever had — that §7 note is corrected here rather than left to be discovered. A §19.5 consumer review of the new contract then caught this file repeating a documented past defect — `reminders` absent from §10's access table (the same omission v1.11.0 logged for `notifications`) and from §10's immutable-field bullet; both fixed in this same version |

---

> ## ⚠ Read first: how to authenticate
>
> Token issuance is live in the **`authenticate`** app. `POST /api/v1/auth/login/` (username +
> password + `device_id`) returns a Bearer access token; `POST /api/v1/auth/refresh/` rotates it.
> Full contract: `authenticate/docs/INTEGRATION.md`.
>
> Two things still require out-of-band setup, and neither is resolvable from the client side:
> 1. **Base URL** — no host is published in this doc; obtain it from whoever runs the backend.
> 2. **The first account** — there is no self-service signup. A backend operator creates the initial
>    superadmin with `python manage.py bootstrap_superadmin` (shell access required); every other
>    account is then provisioned in-app by a higher authority.

---

## 1. What this backend is

A Django + Django REST Framework JSON API. There is no server-rendered HTML surface other than Django admin at `/admin/`, and no GraphQL. Every client integration goes through the versioned REST API described here.

This repository is **backend-only**. It does not contain, and will not contain, frontend code. Its obligation to a consuming project is this documentation set.

## 2. Reading order for a consumer

1. **This file** — global conventions, auth, the app inventory, and the cross-app dependency graph.
2. **`<app>/docs/INTEGRATION.md`** for each app you consume — the endpoint-by-endpoint contract, including what each endpoint requires to function and what it changes.
3. **`core/policy_engine/docs/openapi.json`** — machine-readable paths, methods, permission keys, and risk levels, if you are generating a client.

Do **not** read app source, `API.md`, or `DATA_CONTRACT.md` to integrate. `API.md` and `DATA_CONTRACT.md` are maintainer-facing (they document database tables and internal rationale). The `INTEGRATION.md` files are the consumer contract.

## 3. Global conventions

Every app follows these unless its own `INTEGRATION.md` §3 explicitly states a deviation.

**Base path.** All endpoints are under `/api/v1/`. Breaking changes ship under a new prefix (`/api/v2/`); additive changes do not. A deprecated endpoint returns a `Deprecation: <date>` response header before removal.

**Success envelope.** The resource is always under `data`, never at the top level. `message` may be an empty string. `meta` is always present, `{}` when there is nothing to report.

```json
{
  "success": true,
  "message": "Policy applications retrieved.",
  "data": { "id": "550e8400-e29b-41d4-a716-446655440000", "key": "policy_engine" },
  "meta": {}
}
```

**Error envelope.** `error.details` is **always present** — an empty object `{}` when there are no field-level errors, and a map of field name to an array of messages when there are. Stack traces are never returned.

**Do not type `details` as `Record<string, string[]>`.** The field-name-to-messages shape is the common case, not a guarantee. An app may put a richer value under a key when a list of strings could not carry what the client needs to act — `checklists` returns `details.items` as an array of `{ id, label, status }` objects naming every requirement blocking a completion, and `details.existing_template_id` as a bare id string. Type it as an open map of `unknown` and narrow per error code; each app's `INTEGRATION.md` §7 documents any code whose `details` is not the common shape.

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input.",
    "details": { "permission_key": ["Must be lowercase 'app.model.action'."] }
  },
  "meta": {}
}
```

**Error codes.** `APP_RESOURCE_REASON` in upper snake case (e.g. `LISTINGS_LISTING_NOT_FOUND`). Codes are stable — treat them as part of the contract. Global codes: `AUTHENTICATION_REQUIRED` (401), `PERMISSION_DENIED` (403), `NOT_FOUND` (404), `VALIDATION_ERROR` (400), `METHOD_NOT_ALLOWED` (405), `RATE_LIMIT_EXCEEDED` (429), `INTERNAL_SERVER_ERROR` (500).

> **An app may replace a global code with its own — do not write a single global handler and assume it fires.** The clearest case is 403: `institutions` returns `INSTITUTIONS_ACTOR_FORBIDDEN` for every authority refusal and never returns `PERMISSION_DENIED`, so a handler keyed only on the global code will miss every one of them. Check each app's `INTEGRATION.md` §3 for the codes it actually emits, and branch on `error.code` per app rather than globally.

**Pagination.** Page-number based. `?page=` and `?page_size=` (default 20, max 100). A `page_size` above the maximum is **clamped, not rejected** — `?page_size=500` returns 100 rows and a 200, never a 400. This is the shared paginator's behaviour and applies to every paginated endpoint in every app. Do not guard against it client-side, and do not infer from a 200 that you received the page size you asked for; read `meta.page_size`.

**`data` is the bare array of results — it is NOT nested under a `results` key.** Page metadata lives in `meta`, never alongside the rows. `next`/`previous` are absolute URLs including scheme and host, or `null`.

A full `GET /api/v1/policy/apps/` response with every field populated:

```json
{
  "success": true,
  "message": "Policy applications retrieved.",
  "data": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "key": "policy_engine",
      "display_name": "Core Policy Engine",
      "description": "Registry of every endpoint, permission key, and dependency edge.",
      "current_version": "1.0.0",
      "is_active": true,
      "is_deprecated": false,
      "created_at": "2026-07-21T06:15:00Z",
      "updated_at": "2026-07-21T06:15:00Z"
    }
  ],
  "meta": {
    "count": 1,
    "page": 1,
    "page_size": 20,
    "next": null,
    "previous": null
  }
}
```

An unpaginated list endpoint returns the same bare array in `data` with `meta: {}`. Not every list endpoint paginates — each app's §3 states which do.

**Worked failure responses.** A 403 from a non-staff caller, and a 404 for an unknown key:

```json
{ "success": false, "error": { "code": "PERMISSION_DENIED", "message": "Staff access required.", "details": {} }, "meta": {} }
```

```json
{ "success": false, "error": { "code": "NOT_FOUND", "message": "Not found.", "details": {} }, "meta": {} }
```

**IDs.** Public identifiers are UUID strings. Auto-increment integer keys are never exposed. Some resources are addressed by a stable slug or key instead of a UUID; the owning app's §7 says which.

**Times.** ISO 8601, UTC. Timestamps are timezone-aware.

**Money.** Decimal, serialized as a string to avoid float precision loss. Never parse as a native float.

## 4. Authentication

JWT via SimpleJWT, sent as `Authorization: Bearer <access_token>`.

**Token issuance lives in the `authenticate` app** (`/api/v1/auth/`). `POST /api/v1/auth/login/`
(username + password + `device_id`) returns an access token; `POST /api/v1/auth/refresh/` rotates it.
See `authenticate/docs/INTEGRATION.md` for the full contract. Access tokens are **session-bound**:
the server re-validates the underlying session on every request, so blocking, logout, and password
change revoke access immediately regardless of token lifetime.

- Access token lifetime: 15 minutes (24 hours in development).
- Refresh credential: opaque, server-stored, rotated on use, with reuse detection (7-day absolute /
  12-hour idle lifetime). In production it is a `Secure; HttpOnly; SameSite` cookie; in development it
  is returned in the login/refresh response body.

**Getting a token today.** Create the initial superadmin with
`python backend/manage.py bootstrap_superadmin --username <name>`, then `POST /api/v1/auth/login/`.

**Authorization today.** `authenticate`'s own protected endpoints (`logout`, `me`, `password/change`)
are authenticated self-service (any signed-in user, acting on their own account). `core.policy_engine`
still uses the interim check: authenticated **and** `is_staff`. There is no role- or permission-key-based
enforcement in the request path yet — the Core Policy Engine *describes* the permission surface but does
not yet gate requests with it (`CLAUDE.md` §9).

Every endpoint denies by default. Any public endpoint is explicitly marked as such in its app's `INTEGRATION.md`.

**Health checks** are the exception — `GET /health/` (liveness) and `GET /ready/` (readiness, includes DB connectivity) require no auth and are excluded from rate limiting.

## 5. Rate limiting

Project defaults: 100 requests/hour for anonymous callers, 1000/hour for authenticated ones. Exceeding them returns 429. Limits are not currently surfaced in response headers — treat 429 as the signal and back off.

## 6. App inventory

| App | Base path | Purpose | Contract |
|-----|-----------|---------|----------|
| `authenticate` | `/api/v1/auth/` | Platform identity: username/password login (+ TOTP MFA), session-bound JWT, revocable device sessions (max 3), forced first-login password change, and admin account + session management (one-tier hierarchy: superadmin manages admins, admin manages lead managers) | `authenticate/docs/INTEGRATION.md` |
| `audit` | `/api/v1/audit/` | Central, immutable, cross-app activity/change history. Read-only over HTTP (Admin/Superadmin); populated by other apps via an internal service call | `audit/docs/INTEGRATION.md` |
| `core.policy_engine` | `/api/v1/policy/` | Read-only registry of every endpoint in this backend: permission keys, risk levels, dependency edges, version history, change log | `core/policy_engine/docs/INTEGRATION.md` |
| `leads` | `/api/v1/leads/` | Enquiry tracking before applicant conversion: lead identity and contact details, configurable source attribution, preliminary study interest, eight-stage lifecycle, manual follow-up, notes, loss/reopen handling, and Admin-only conversion into an applicant plus initial journey. Owner-scoped — a Lead Manager sees only leads they created | `leads/docs/INTEGRATION.md` |
| `applicants` | `/api/v1/applicants/` | The permanent identity record of a person the consultancy works with: name, date of birth, contact numbers, addresses, passport, family, emergency contacts, and standing. Created by Admins only, by direct creation or lead conversion. **Shared** — every Admin and Lead Manager sees every applicant | `applicants/docs/INTEGRATION.md` |
| `applicant_journeys` | `/api/v1/journeys/` | One overseas-study objective pursued by one applicant: destination, level, field, intake, budget, nine-stage lifecycle, deferment, closure, and outcome. One applicant may hold many. Shared, like applicants | `applicant_journeys/docs/INTEGRATION.md` |
| `institutions` | `/api/v1/catalogue/` | The study-opportunity catalogue: countries, providers, campuses, and programs with tuition, entry expectations, and availability, plus an admin-managed study-field reference table. Read-shared, **write Admin-only** — the inverse split from every other app. Nothing is ever deleted; records are marked unavailable. Note the base path differs from the app name | `institutions/docs/INTEGRATION.md` |
| `clients` | `/api/v1/clients/` | The B2B partner directory: the agencies, schools, and companies that refer applicants, with spokesperson, contact numbers, address, website, and logo link. Read-shared, **write Admin-only** — the same split as `institutions`. Retired rather than deleted. **No business-app dependency in either direction**, and note that the attribution it was built to support is not wired up yet | `clients/docs/INTEGRATION.md` |
| `documents` | `/api/v1/documents/` | The editable document working record: ownership (applicant or standalone), template family + slug, status, and the entered source data as an opaque JSON body stored verbatim. **The backend is not the rendering engine** — every derived value is computed by the client at render. **Admin only, reads included** — the one app a Lead Manager cannot see at all. Archived, never deleted | `documents/docs/INTEGRATION.md` |
| `document_history` | `/api/v1/document-history/` | The immutable print snapshots of a document, and the print events (capture / reprint / recovery) that produced them. Freezes the document body plus the client's render-time context, so what was issued is recoverable even after the working record moves on. **Admin only, reads included**, like `documents`. **Nothing here is ever edited or deleted** — no `PUT`, `PATCH`, or `DELETE` exists on any route. Holds the project's only cross-app write outside lead conversion | `document_history/docs/INTEGRATION.md` |
| `document_templates` | `/api/v1/document-templates/` | The signatory library certificate documents name, and the catalogue of template slugs the document picker offers. **Stores what is *offered*, not what is *rendered*** — the templates themselves are frontend code, and no endpoint here describes how a document draws itself. **Admin only, reads included**, like the other two document modules — though this is the only one holding no applicant data. Retired, never deleted. The catalogue is **advisory**: `documents` does not consult it | `document_templates/docs/INTEGRATION.md` |
| `uploaded_files` | `/api/v1/files/` | **The platform's file ledger — the only place in Grandway where bytes are stored.** Upload, category, verification state, replacement chains, and archival, for files belonging to an applicant, journey, offer, document, or print snapshot. **The bytes are private**: `MEDIA_URL` is unset, nothing is web-served, and a file leaves only through an authenticated, audited download endpoint. Nothing is ever deleted. Shared read/write with **Admin-only** verify, archive, and restore — and a file **inherits the visibility of its owner**, so `document`- and `snapshot`-owned files are Admin-only entirely | `uploaded_files/docs/INTEGRATION.md` |
| `offers` | `/api/v1/offers/` | Institutions' formal admission decisions against applicant journeys: offer type, dates, money terms, conditions, and the accept/reject/withdraw/defer/expire outcome. Each offer carries an immutable **snapshot** of the institution and program as they stood when the decision was made, so later catalogue edits never rewrite history. Shared, like journeys. A decision is final — there is no reopen, and nothing is ever deleted | `offers/docs/INTEGRATION.md` |
| `dashboards` | `/api/v1/dashboard/` | **The operational command centre — one of two apps in this backend that own no table and write nothing** (the other is `search`). Eight independent read-only sections (summary, today's work, pipeline, blockers, workload, conversion, outcomes, activity) summarising every other app, sharing one filter set. Every figure is derived live at request time from the owning app's own selectors; there is no stored counter, no rollup, and no cache. **A leaf: nothing depends on it, and it is the only app that reads nine others.** Note the base path is singular while the app is plural | `dashboards/docs/INTEGRATION.md` |
| `checklists` | `/api/v1/checklists/` | **The destination-country requirement lists, and each applicant's own copy of one.** An Admin authors, per catalogue country, the documents to collect and the stages to reach; setting a journey's `target_country_ref` then **inherits that country's list automatically**, with no endpoint call. Two applicants headed for the same country hold identical items and entirely independent progress. Instantiation is a **snapshot** — editing a template never rewrites a live checklist. Completion is derived from item states, never asserted. Shared read/write with **Admin-only** template authoring. Nothing is deleted: templates retire, checklists archive | `checklists/docs/INTEGRATION.md` |
| `notifications` | `/api/v1/notifications/` | **The in-app alert stream — a per-person inbox of what needs attention.** Deadlines (checklist items, offer responses, passport expiry, uncollected documents) are raised by a nightly sweep; lifecycle events (assignment, file rejection, journey stage, offer decision) are raised the moment they happen. Every alert points at the record that caused it and owns none of it. **The only app in the backend whose reads are scoped to the calling user** — no authority, including Admin, can read another person's feed, and another user's notification id returns 404 rather than 403. There is **no create, update, or delete endpoint**: a client may only read, mark read/unread, and dismiss. Nothing is ever deleted — the alert history survives the fix | `notifications/docs/INTEGRATION.md` |
| `reminders` | `/api/v1/reminders/` | **Staff-set follow-up reminders** — a one-off, date-only note against exactly one applicant or client ("chase the payment", "call them back"), due at the start of the chosen day Nepal time. Shared read/write for Admin and Lead Manager; when the date arrives the **nightly notifications sweep raises a `custom_reminder` alert to every active Admin** — only Admins receive it, though anyone who can see the reminder may complete or dismiss it. One-off by design: no recurrence, no snooze, no reopen — "remind me again" is a new reminder. Nothing is ever deleted; a reminder ends `completed` or `dismissed` and its history stays in the central audit log | `reminders/docs/INTEGRATION.md` |
| `search` | `/api/v1/search/` | **The one global search box — the second app that owns no table and writes nothing.** One query answered across nine record types (applicants, leads, clients, documents, files, institutions, programs, templates, signatories), returned **grouped by type, never interleaved**, each group carrying its true total and a link into the owning app's own list for the full set. It adds no capability: every row is one the caller could already have reached through the owning module. **Results inherit each owning app's scoping**, so an Admin and a Lead Manager searching the same word legitimately see different totals. Two endpoints, both read-only; the second is a static catalogue a client fetches once to build its filter chips. Rate-limited separately at 60/min — debounce a search-as-you-type box | `search/docs/INTEGRATION.md` |

**Routes outside `/api/v1/`.** `core` exposes three, and they are deliberately outside the registry-completeness guarantee in §9 (which covers `/api/v1/` only). They have no permission key and are not client API surface:

| Route | Auth | For consumers |
|-------|------|---------------|
| `GET /health/` | none | Liveness probe. Returns 200 while the process is up. Safe to poll; excluded from rate limiting. |
| `GET /ready/` | none | Readiness probe, includes DB connectivity. Returns 200 only when able to serve. Safe to poll; excluded from rate limiting. |
| `/admin/` | session login | Django's built-in admin UI for internal staff. **Not an API** — no JSON contract, no stable surface. Never integrate against it. |

## 7. Cross-app dependency graph

Assembled from each app's `INTEGRATION.md` §2 `Requires`. Use it to determine integration order: an app's dependencies must be usable before it is.

- `authenticate` → `core` (framework), `django-axes` (framework), `rest_framework_simplejwt` (framework), `argon2-cffi` (framework), `django-otp` (framework — TOTP MFA), `audit` (service call — emits auth events to the central audit log, best-effort)
- `audit` → `core` (framework), `authenticate` (framework — supplies the request user for the `is_staff` read gate)
- `core.policy_engine` → `core` (framework), `authenticate.User` (FK — the platform user model, since `AUTH_USER_MODEL = authenticate.User`), `rest_framework_simplejwt` (framework)
- `leads` → `core` (framework), `authenticate` (framework — supplies the access token and the `authority_type` that decides Admin vs Lead Manager scope; FK — lead ownership and every attribution field reference a user account), `audit` (service call — every lead mutation appends one event, and the lead history endpoint reads that log back), `applicants` (service call + FK — conversion creates the applicant and links to it one-to-one), `applicant_journeys` (service call + FK — conversion creates the initial journey and links to it)
- `applicants` → `core` (framework), `authenticate` (framework — access token and authority type; FK — `created_by`), `audit` (service call — history)
- `applicant_journeys` → `core` (framework), `applicants` (FK — every journey belongs to exactly one applicant), `authenticate` (framework; FK — `created_by`, `closed_by`, `deferred_by`), `audit` (service call — history)
- `institutions` → `core` (framework), `authenticate` (framework — supplies the access token and the `authority_type` that decides read-vs-write; **no FK**, since catalogue records have no owner), `audit` (service call — every create and update appends one event carrying the changed fields' previous and new values)
- `offers` → `core` (framework), `applicant_journeys` (FK — every offer belongs to exactly one journey; also the route to the applicant's identity), `institutions` (FK, optional — the catalogue records an offer is built from and snapshots its names out of), `authenticate` (framework; FK — `created_by`, `decided_by`, and each condition's `resolved_by`), `audit` (service call — every mutation, including every condition change, appends one event)
- `clients` → `core` (framework), `authenticate` (framework — access token and the `authority_type` that decides read-vs-write; FK — `created_by`, `retired_by`), `audit` (service call — every mutation appends one event). **No business-app edge at all.**
- `documents` → `core` (framework), `applicants` (FK, optional — an applicant-owned document points at one; a standalone document points at nothing; also a service call to resolve the id on create), `authenticate` (framework; FK — `created_by`, `archived_by`), `audit` (service call — every mutation appends one event, with the document body redacted)
- `document_history` → `core` (framework), `documents` (FK — every snapshot and print event belongs to exactly one document; **service call** — `get_document_by_id` on every document-scoped route, and `update_document` for the recovery **write**), `authenticate` (framework; FK — `captured_by`, `performed_by`), `audit` (service call — every capture, reprint, and recovery appends one event, with both the frozen body and the render context redacted). **No edge to `applicants` at all** — a snapshot reaches the applicant only through its document.
- `document_templates` → `core` (framework), `documents` (**three Python imports, no database relation** — the `DocumentFamily` enum, the template-key slug validator, and the key/family agreement rule, the last being a **service call** made at request time, so the catalogue can never accept a pairing `documents` would reject), `authenticate` (framework; FK — `created_by` on both models), `audit` (service call — every mutation appends one event, **unredacted**, since this module holds no applicant data). **No edge to `applicants` or `document_history` in either direction.**
- `uploaded_files` → `core` (framework), **the local filesystem** (infrastructure — `MEDIA_ROOT` is the byte store, not web-served), `applicants` / `applicant_journeys` / `offers` / `documents` / `document_history` (**FK + service call, all five** — a file belongs to exactly one of them, and each owner id is resolved through that app's own selector on upload), `authenticate` (framework; FK — `uploaded_by`, plus three `SET_NULL` lifecycle actors), `audit` (service call — every write **and every download** appends one event). **The most-connected app in the graph, and the only one depending on infrastructure rather than only on other apps.**

- `checklists` → `core` (framework), `applicant_journeys` (FK — every checklist belongs to exactly one journey; service call — the id is resolved on create; **signal** — a `post_save` receiver on `ApplicantJourney` is what makes inheritance automatic), `institutions` (FK + service call — a template is scoped to a catalogue country, and the checklist copies that country at instantiation), `uploaded_files` (FK + service call, **optional** — an item may cite a stored file as evidence, validated against the checklist's own journey and applicant), `authenticate` (framework; FK — one nullable `PROTECT` author plus four `SET_NULL` actors), `audit` (service call — every write appends one event; inherited checklists are recorded with `actor_type = system`)

- `dashboards` → `core` (framework), `authenticate` (framework — access token and the `authority_type` that decides both admission and how lead figures are scoped), `leads` / `applicants` / `applicant_journeys` / `offers` / `checklists` / `documents` / `uploaded_files` (**service call, all seven** — every figure comes from a summary selector in the app owning the rows; this app queries no table but its own, and it has none), `audit` (service call — the recent-activity feed is a projection of the central log), `institutions` (**indirect FK read** — the `country` filter is a catalogue country id, passed through to the apps holding the foreign key; this app never queries the catalogue). **No FK of any kind, in either direction.**

- `notifications` → `core` (framework), `authenticate` (framework — access token and the `authority_type` that decides admission; **FK** — the recipient, the only foreign key this app holds; service call — `get_active_admins()` is the fan-out for alerts about records nobody owns), `checklists` / `offers` / `applicants` / `reminders` (**service call** — the deadline sweep reads each owning app's own selectors and never re-implements its definition of "overdue"; the `reminders` read is the newest, and the first whose rows exist *only* to be swept), `checklists` / `uploaded_files` / `applicant_journeys` / `offers` (**signal** — five `post_save` receivers across those four apps turn source events into alerts; `checklists` carries two of them, one on the checklist and one on its items, because a checklist and a single requirement can be assigned to different people), `audit` (service call — dismissals and generator failures). **Holds exactly one FK, to `authenticate.User`; every other module is referenced by app name, entity type, and a bare id string.**

- `reminders` → `core` (framework), `authenticate` (framework — access token and the `authority_type` that decides admission; FK — `created_by`, `closed_by`), `applicants` / `clients` (**FK — exactly one per reminder**, `PROTECT`; service call — the owner id is resolved through that app's own selector on create), `audit` (service call — every mutation appends one event, and the reminder history endpoint reads that log back). **The reverse edge is the one that matters:** `notifications` reads this app's due-reminder selector on its nightly sweep — reminders stores the follow-up, notifications surfaces it.

- `search` → `core` (framework), `authenticate` (framework — access token and the `authority_type` that decides both admission and how lead and file results are scoped), `applicants` / `leads` / `clients` / `documents` / `uploaded_files` / `institutions` / `document_templates` (**service call, all seven** — every result comes from the search selector of the app owning the rows; this app queries no table and has none). **No FK of any kind, in either direction.**

Each edge appears in **both** apps' §2 sections — the depended-on app records what would break, the depending app records why it needs it.

**`dashboards` and `search` both invert the shape of every other edge in this graph.** Every dependency above exists so an app can *own* something — a foreign key it holds, a record it creates. These two hold nothing and create nothing; they depend on other modules purely to read them. The three consequences below are written for `dashboards` and apply to `search` word for word, with "figures" read as "results":

- **It is a leaf, and it is optional.** Nothing points at it, so removing it would break no other module and no other app's contract mentions it. A client can integrate the entire backend without ever calling it.
- **It adds no capability, only a view.** Every number it returns is derivable by calling the owning module directly. What it provides is the aggregation and the drill-down ids, not access to anything otherwise unreachable — so it can never show a caller more than the underlying apps would.
- **Its numbers inherit each owning app's scoping, and therefore are not uniformly scoped.** Lead figures are narrowed to a Lead Manager's own leads; applicant, journey, offer, and checklist figures are not, because those apps are shared. **An Admin and a Lead Manager calling the same URL will legitimately see different numbers**, and only `workload.is_scoped_to_caller` marks it. `search` behaves identically — its `lead` bucket is owner-scoped and its `uploaded_file` bucket applies that app's visibility rule, while its other seven buckets are not narrowed — and it marks it nowhere at all. In both apps this is the scoping working, not a defect.

**`checklists` holds the graph's first signal edge, and its first inbound reference to `uploaded_files`.** Two consequences a consumer must plan for:

- **The trigger is invisible from the app that fires it.** Setting a journey's `target_country_ref` creates a checklist, and the journey response says nothing about it — `applicant_journeys` does not know `checklists` exists, deliberately, so the dependency stays one-way. A client that wants to show the newly inherited list must ask `/api/v1/checklists/?applicant=<id>` separately.
- **It is asynchronous relative to the response.** Inheritance runs after the journey's transaction commits, so a read issued in the same instant as the `PATCH` may find nothing. There is no completion signal to poll; retry.

**`uploaded_files` is no longer unreciprocated.** It depended on five business apps with none depending on it until `checklists` shipped a `PROTECT` foreign key to a file as an item's evidence. That reference is optional and one-way — nothing in `uploaded_files` knows about checklists — but it is the first, and it means a file cited as evidence can no longer be removed while the item citing it exists. Every other reverse pointer named in §9 is still absent.

**It is also where a per-app access rule first proved insufficient.** Because this app stores data on behalf of five modules with three different access models, its own flat "shared read/write" rule silently overrode the Admin-only rule of two of them. The fix — a file inherits the visibility of its owner — is described in §10 and in that app's `docs/SECURITY.md` §2.1. **Any app that later stores data on another app's behalf inherits this problem**, and should check its access rule against every owner it accepts rather than against its own domain alone.

**Direction matters at the lead↔applicant boundary.** `leads` owns *both* links into the applicant cycle — the FK and the service call — so `applicants` and `applicant_journeys` reference `leads` for nothing and function with no lead in the system at all. That is required, not incidental: an Admin may create an applicant directly, with no enquiry preceding it. The reverse lookup is available through the `OneToOneField`'s reverse accessor (`applicant.originating_lead`), which also makes two leads converting to one applicant impossible at the database level.

**`offers` is where the catalogue and the applicant cycle finally meet — but only partly.** Until `offers` shipped, `institutions` was an island: no edge to another business app in either direction. An offer now references both a journey and a catalogue program, so the graph is connected. What that does **not** mean:

- **`applicant_journeys` stores its institution and program as free text** (`target_institution_name`, `target_program_name`) with no FK into the catalogue. A client shortlisting a program onto a journey still copies those strings across itself. **The country is no longer among them** — see the correction below.
- **Nothing reconciles the two.** A journey saying "Melbourne Uni" and an offer on it pointing at the catalogue's "University of Melbourne" are still two unconnected facts; no endpoint compares them or reports a mismatch.
- **The arrows point one way.** `offers` depends on `institutions` and `applicant_journeys`; neither depends on `offers`. Recording, issuing, or deciding an offer changes nothing in either — in particular it does **not** move the journey's stage to `offer_stage`. A client that wants that must call `applicant_journeys.journey.change_stage` itself.

**Correction (2026-07-24, v1.9.0): a journey's country IS a catalogue reference.** The three bullets above were written when the whole destination was free text, and one of them is now wrong. `ApplicantJourney` gained `target_country_ref`, a nullable FK to `institutions.Country`, alongside the free-text `target_country` it still keeps for journeys created before the catalogue existed. **Write the reference, not only the string** — `target_country_ref` is what `checklists` watches to inherit a country's document requirements, so a client that sets only `target_country` leaves every applicant without a checklist and receives no error saying so. Institution and program remain free text; only the country was migrated.

**`clients` is no longer an island — but the edge it gained is not the one its concept was waiting for.** Until `reminders` shipped (2026-08-17), `clients` had no edge to any business app in either direction, the position `institutions` held until `offers` shipped. A reminder may now hold a `PROTECT` foreign key to a client, which means **a client with an open reminder against it cannot be removed** (nothing deletes clients anyway) and a partner record can carry follow-up work. What has **not** changed: the attribution link `concepts/clients.txt` describes — a future `leads.Lead.client` foreign key recording "which organizations are sending work" — **still does not exist.** Nothing records which partner referred a lead or an applicant, and no endpoint reports it. A consumer expecting to attribute a lead to a partner cannot, and should not ship UI that implies it can.

**An offer does not read through to the catalogue at display time.** It carries a snapshot of the institution and program names taken at creation, and renders from that. This is the point of the module: a program renamed or an institution marked inactive leaves every already-recorded offer untouched. Integrate against the snapshot fields, not a freshly-fetched catalogue record.

**`document_history` holds the only cross-app *write* in the graph apart from lead conversion, and it is one endpoint.** Every other edge above is a read or an audit append: an app fetches another app's record, or emits an event. `POST /api/v1/document-history/snapshots/<id>/recover/` writes a frozen `label` and `content` back into a `documents.Document`, through `documents.services.update_document` rather than directly — so that module's archive lock, size cap, and redacted audit event all still apply. Two consequences for a consumer:

- **A recovery produces two audit events, one per module** — `documents.document_updated` (body redacted) and `document_history.snapshot_recovered`. Not duplication; they answer different questions and appear in different history panels.
- **The arrow points one way.** `documents` depends on `document_history` for nothing and functions with no snapshot in the system. Capturing a snapshot does **not** change the document's status — there is no `printed` status in `documents`, deliberately (see that module's contract §5).

**Two snapshot mechanisms now exist, and they are unrelated.** `offers` snapshots institution and program *names* into columns on the offer row; `document_history` snapshots a whole document body into its own table. Same word, different mechanism, different module — do not expect a shared shape or a shared endpoint.

**The three document modules form a stack, and every edge between them is weaker than it looks.** `documents` is the centre and depends on neither of the others. `document_history` holds real foreign keys to it and performs one write through its service. `document_templates` holds **no database relation to anything in the stack** — it imports three Python objects from `documents` (the family enum, the slug validator, the key/family rule) so the two cannot disagree about what a valid template key is, and that is the entire coupling. The practical consequence for a consumer:

- **Two references cross module boundaries as bare strings inside JSON, and nothing validates either.** A document's `content.instructorId` names a `document_templates.Signatory`; a document's `template_key` names a `document_templates.DocumentTemplate`. Both are accepted whether or not the target exists, and whether or not it is active. The catalogue and the signatory library constrain *your picker*, not the API.
- **Renaming propagates; snapshots do not.** Rename a signatory and every live document renders the new name, because only the id is stored. A print snapshot froze the name and keeps showing the old one. That divergence is the point of the snapshot, but it will read as a bug if unexpected.

**Not yet built.** `education` and `test_scores` have approved concept files (`concepts/education.txt`, `concepts/test_scores.txt`) but no code. Their absence is visible at conversion: a lead's `highest_qualification` and `language_test_status` are carried into the journey's free-text notes rather than into structured records.

## 8. Machine-readable artifacts

Generated from the endpoint registry, committed, and CI-checked for drift — they cannot silently fall out of sync with the code.

| Artifact | Path | Authoritative for |
|----------|------|-------------------|
| Registry export | `core/policy_engine/docs/registry_export.json` | Every registered endpoint: permission key, app/model, route, method, operation type, risk level, version, category, dependency edges |
| OpenAPI 3.1 | `core/policy_engine/docs/openapi.json` | Paths, methods, `operationId` (= permission key), `x-permission-key`, `x-risk-level`, bearer security, envelope components |
| Registry schema | `core/policy_engine/docs/registry_schema.json` | The JSON Schema for one registry entry |

**Limitation — read this before generating a client.** The OpenAPI document is authoritative for *paths, methods, permission keys, and risk*, but its request/response **body** schemas are generic: every operation returns the envelope with an opaque `data`. Field-level shapes live in each app's `INTEGRATION.md` §4 `Models`. A generated client will therefore have correct routes and auth but untyped payloads; type the payloads from §4.

## 9. Guarantees and non-guarantees

**Guaranteed.** Every routed `/api/v1/` endpoint is registered in the policy registry and appears in the artifacts above — CI rejects an endpoint that is not (`validate_policy_engine` rule 14). Every registered endpoint is documented in its app's `INTEGRATION.md` — CI rejects one that is not (`validate_integration_docs`). So the endpoint *inventory* is provably complete.

**Not guaranteed.** Prose field descriptions inside a documented endpoint are not mechanically verified against the serializer. If a payload field seems wrong, the code is authoritative and the doc is a bug — report it.

## 10. Gaps

- Request/response body schemas are not machine-readable (see §8).
- Permission-key-based authorization is not yet enforced in the request path (see §4); `authenticate`'s own protected endpoints are authenticated self-service, `core.policy_engine` and `audit` use `is_staff`, and `leads`, `applicants`, and `applicant_journeys` each use their own inline authority rules (see each app's `SECURITY.md` §1). Every endpoint has a registered permission key ready for that wiring, but no view consults one yet.
- **Access models differ per app and cannot be assumed. There are now six distinct shapes:**

  | Shape | Apps | Lead Manager reads | Lead Manager writes | Superadmin |
  |---|---|---|---|---|
  | Shared | `applicants`, `applicant_journeys`, `offers`, `reminders` | yes | yes | **no** |
  | Read-shared, write-Admin | `institutions`, `clients` | yes | no | **no** |
  | **Admin-only** | **`documents`**, **`document_history`**, **`document_templates`** | **no** | **no** | **no** |
  | **Shared, with Admin-only actions** | **`uploaded_files`**, **`checklists`** | yes | yes, **except** verify / archive / restore (`uploaded_files`) and **template authoring** (`checklists`) | **no** |
  | **Scoped to the calling user** | **`notifications`** | **own feed only** | **own feed only** | **no** |
  | **Read-only, composed** | **`dashboards`**, **`search`** | yes — **but each figure or result inherits the owning app's own scoping** | n/a — these apps write nothing | **no** |

  **The composed row is the one a client is most likely to misread.** `dashboards` and `search` own no tables; every number and every result is produced by the app that owns the row, and arrives already narrowed by that app's rule. The consequence is that **a single response is not uniformly scoped**: within one search, the `lead` bucket is narrowed to a Lead Manager's own leads and the `uploaded_file` bucket excludes Admin-only files, while the other seven buckets are not narrowed at all, because those apps do not narrow their own lists. **An Admin and a Lead Manager issuing the identical request will legitimately get different totals.** `dashboards` marks this in exactly one place (`workload.is_scoped_to_caller`); `search` marks it nowhere. Neither app can ever show a caller more than the underlying apps would — they add a view, not access — so the correct client behaviour is to render what comes back and never treat a differing count as a bug to report.

  **`checklists` splits on a different axis from `uploaded_files`, and the difference is worth internalising.** `uploaded_files` reserves the *judgement* actions (verify, archive, restore) for an Admin while sharing the clerical ones. `checklists` reserves *authoring the policy* — the four template routes — while sharing every act performed against an applicant, completion included. The reasoning is the blast radius: a checklist template propagates automatically to every future applicant for that country, so editing one silently changes what dozens of files will be measured against, whereas completing one applicant's list affects one applicant. A client must hide the template-authoring screens for a Lead Manager while leaving every checklist panel fully editable.

  **`uploaded_files` additionally scopes by the owning *record*, and it is the only app that does.** (Distinct from `notifications`, which scopes by the calling *user* — see the row below it. The two are different mechanisms: a file's visibility is inherited from what it is attached to, a notification's from who it was addressed to.) A file inherits the visibility of the record it belongs to, so a file owned by a `document` or a print snapshot is Admin-only in every respect — invisible in lists and reported as **404** on every per-file route for a Lead Manager. Without that rule the file ledger would have been a side door around the Admin-only row above; the leak was real, and was found by a §19.5 review rather than by design. **If Lead Managers are ever given document access, that app's `ADMIN_ONLY_OWNER_TYPES` must change in the same session** or its attachment panels will stay dark while the documents themselves become visible.

  **`superadmin` is not a superset of `admin`, and this surprises everyone.** Read the third column carefully: **no business app in this project grants a superadmin anything.** Every access check is an exact authority match against `admin` or `lead_manager`, so a superadmin token is refused with the owning app's 403 code on every business route — reads included, in every shape above, not only the Admin-only one. §4 describes `authenticate` as a "one-tier hierarchy: superadmin manages admins", and that is *all* it means: a superadmin administers accounts and sessions, and reaches `core.policy_engine` and `audit` (which gate on `is_staff` instead). It does not inherit Admin's access to applicants, journeys, offers, the catalogue, clients, documents, or document history. **Do not build navigation that assumes a superadmin can see what an Admin can see** — every one of those panels must be hidden for them exactly as it is for a Lead Manager.

  **`notifications` is the only app whose reads are scoped to the calling user, and it is the one place where Admin is not privileged at all.** Every endpoint returns the caller's own alerts and nothing else — there is no `?recipient=` filter, no "notifications for user X" route, and no authority that can widen it. A notification is one person's work queue rather than a fact about the business, and everything it points at is already reachable through the owning app's own endpoints, so the scoping costs an Admin no access and removes the ability to read somebody's inbox without leaving a trace. Cross-user inspection lives in Django admin. **Do not design a supervisor screen on top of it** — "show me everything sent to this Lead Manager" is not buildable from this API.

  `leads` sits outside the table: it is owner-scoped, and reports out-of-scope records as 404. **Two apps now return 404 for a record that exists but is out of the caller's scope** — `leads` (not your lead) and `notifications` (not your notification) — and in both the ambiguity is deliberate, so an id cannot be probed for existence. `uploaded_files` does the same for a file whose owner is Admin-only. Everywhere else, 404 means genuinely absent. **A global client handler that treats 404 as "this record does not exist" will therefore mislabel three apps.** Creation authority varies within the shared group too — only an Admin may create an applicant, while any lead actor may create a journey or an offer.

  **The three document modules are the cases most likely to break a client**, because they are the only apps where a Lead Manager cannot even list. All three modules' panels must be *hidden* for them, not rendered read-only or shown empty — an empty panel asserts "this applicant has no documents", which is false. Each app's `INTEGRATION.md` §3 states its own rule; that is the consumer-facing source. `documents/docs/SECURITY.md` §1 carries the reasoning for the first two, and is maintainer-facing — useful, but not part of the contract set in §6. Neither `document_history` nor `document_templates` publishes a `SECURITY.md`, because neither adds a security decision of its own.

  **`document_templates` is Admin-only for a different reason than the other two, and that is worth knowing before anyone relaxes it.** It holds **no applicant data at all** — a signatory is a staff member's name and a link to their signature image; a template is a slug and a label. Its risk ratings are `low`/`medium` throughout, against `high` for the endpoints that return a document body. The Admin-only rule is inherited from its *consumer*: a Lead Manager who cannot open a document workspace has no way to use a signatory picker. If document access is ever widened, that module should follow in the same change rather than being re-argued from scratch.
- **Files are stored, and exactly one module points back at one.** `uploaded_files` holds `PROTECT` foreign keys to applicants, journeys, offers, documents, and print snapshots. In the other direction there is now a single reference: a `checklists` item may cite a file as `evidence_file`, proving a requirement was met. **Every other reverse pointer is still absent** — an applicant payload carries no photograph, an offer carries no letter, a document carries no attachment, and a snapshot carries no file, so every files *panel* in the product remains a second call to `/api/v1/files/?<owner>=<id>` that the screen joins itself. Adding a reverse pointer to any of those apps is additive and is a separate session each.
- **A file cited as checklist evidence can no longer be removed.** The `evidence_file` reference is `PROTECT`, so once an item cites a file, deleting that file is refused at the database level. There is no delete endpoint in `uploaded_files` anyway, but this is the first hard constraint of its kind, and it will surface if a future cleanup path is ever built.
- **Two URL fields were deliberately not migrated to file storage.** `clients.logo_url` and `document_templates.signature_image_url` are still links to hosts this API knows nothing about — repointing them changes two shipped response shapes, and neither `Client` nor `Signatory` is one of `uploaded_files`' five owner types, so there is nowhere to attach them even by hand.
- **There is no owner rollup.** "Every file related to this applicant" spans the applicant, each of their journeys, each offer on each journey, and each document and snapshot — one request per owner id, merged client-side. There is no `owner_type` filter and no multi-value filter syntax anywhere in that app.
- **Two cross-module references travel as bare strings inside JSON and are validated by nothing.** A document's `template_key` names a row in `document_templates`' catalogue; its `content.instructorId` / `content.directorId` name signatory records there. `documents` stores `content` as an opaque body and does not consult the catalogue, so a typo, a stale id, or a retired template are all accepted silently. **Both libraries constrain your picker, not the API** — if you need them enforced, that is client-side work today.
- **Immutable-field handling on `PATCH` differs per app — this one will break a shared edit form.** `institutions` **silently ignores** an immutable field, so reading an object and PATCHing the whole thing back succeeds. `offers` (`OFFERS_REFERENCE_IMMUTABLE`), `clients` (`CLIENTS_STATUS_IMMUTABLE`), and `reminders` (`REMINDERS_FIELD_IMMUTABLE` — the owner FKs and the three lifecycle fields) **reject** one with 400, listing every offending field in `details` — in all three cases because the field carries accountability, and a silent no-op would let a client believe it had rewritten history, retired a partner, or re-pointed a reminder when it had not. A generic read-modify-write-the-whole-object form carried from `institutions` to either of the others will fail on every save. Send only the fields the user actually changed.
- **No host is published here.** Every path in this documentation set is relative to a base URL you must obtain from the deploying team (locally, `http://localhost:8000`). There is no public sandbox environment.
- **The first account requires shell access.** Token issuance exists (`authenticate`), but the initial superadmin is created by the `bootstrap_superadmin` management command, and there is no self-service signup — so the very first credential must be provisioned server-side (§4).
- Rate-limit state is not exposed in response headers — 429 is the only signal (§5).
