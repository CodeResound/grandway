# Integration — Grandway Backend

**Owner app:** `core`
**Version:** 1.5.0
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

**Pagination.** Page-number based. `?page=` and `?page_size=` (default 20, max 100).

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
| `offers` | `/api/v1/offers/` | Institutions' formal admission decisions against applicant journeys: offer type, dates, money terms, conditions, and the accept/reject/withdraw/defer/expire outcome. Each offer carries an immutable **snapshot** of the institution and program as they stood when the decision was made, so later catalogue edits never rewrite history. Shared, like journeys. A decision is final — there is no reopen, and nothing is ever deleted | `offers/docs/INTEGRATION.md` |

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

Each edge appears in **both** apps' §2 sections — the depended-on app records what would break, the depending app records why it needs it.

**Direction matters at the lead↔applicant boundary.** `leads` owns *both* links into the applicant cycle — the FK and the service call — so `applicants` and `applicant_journeys` reference `leads` for nothing and function with no lead in the system at all. That is required, not incidental: an Admin may create an applicant directly, with no enquiry preceding it. The reverse lookup is available through the `OneToOneField`'s reverse accessor (`applicant.originating_lead`), which also makes two leads converting to one applicant impossible at the database level.

**`offers` is where the catalogue and the applicant cycle finally meet — but only partly.** Until `offers` shipped, `institutions` was an island: no edge to another business app in either direction. An offer now references both a journey and a catalogue program, so the graph is connected. What that does **not** mean:

- **`applicant_journeys` still stores its destination as free text** (`target_country`, `target_institution_name`, `target_program_name`) and has no FK into the catalogue. A client shortlisting a program onto a journey still copies the strings across itself.
- **Nothing reconciles the two.** A journey saying "Melbourne Uni" and an offer on it pointing at the catalogue's "University of Melbourne" are still two unconnected facts; no endpoint compares them or reports a mismatch.
- **The arrows point one way.** `offers` depends on `institutions` and `applicant_journeys`; neither depends on `offers`. Recording, issuing, or deciding an offer changes nothing in either — in particular it does **not** move the journey's stage to `offer_stage`. A client that wants that must call `applicant_journeys.journey.change_stage` itself.

**`clients` is now the graph's only island, and deliberately so — for now.** It has no edge to any business app in either direction, the position `institutions` held until `offers` shipped. That is not the end state: `concepts/clients.txt` describes the directory supplying the reference record for "which organizations are sending work", which means a future `leads.Lead.client` foreign key. **That link does not exist.** Nothing records which partner referred a lead or an applicant, and no endpoint reports it. A consumer can build a complete partner directory today; a consumer expecting to attribute a lead to a partner cannot, and should not ship UI that implies it can.

**An offer does not read through to the catalogue at display time.** It carries a snapshot of the institution and program names taken at creation, and renders from that. This is the point of the module: a program renamed or an institution marked inactive leaves every already-recorded offer untouched. Integrate against the snapshot fields, not a freshly-fetched catalogue record.

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
- **Access models differ per app and cannot be assumed. There are now three distinct shapes:**

  | Shape | Apps | Lead Manager reads | Lead Manager writes |
  |---|---|---|---|
  | Shared | `applicants`, `applicant_journeys`, `offers` | yes | yes |
  | Read-shared, write-Admin | `institutions`, `clients` | yes | no |
  | **Admin-only** | **`documents`** | **no** | **no** |

  `leads` sits outside the table: it is owner-scoped, and reports out-of-scope records as 404. Every other app's 404 means genuinely absent. Creation authority varies within the shared group too — only an Admin may create an applicant, while any lead actor may create a journey or an offer.

  **`documents` is the case most likely to break a client**, because it is the only app where a Lead Manager cannot even list. A documents panel must be *hidden* for them, not rendered read-only or shown empty — an empty panel asserts "this applicant has no documents", which is false. Each app's `INTEGRATION.md` §3 states its own rule; that is the consumer-facing source. The app's `SECURITY.md` §1 carries the same rule plus the reasoning, and is maintainer-facing — useful, but not part of the contract set in §6.
- **Three named document domains are unbuilt, and `documents` depends on all three for its full feature set.** `document_history` (print snapshots), `document_templates` (template definitions and signatory records), and `uploaded_files` (supporting files) have no code and, for the first two, no concept file. A client integrating `documents` can create, edit, archive, and restore — but cannot print, cannot resolve a signatory reference, and cannot attach a file. See `documents/docs/INTEGRATION.md` §2 and §9.
- **Immutable-field handling on `PATCH` differs per app — this one will break a shared edit form.** `institutions` **silently ignores** an immutable field, so reading an object and PATCHing the whole thing back succeeds. `offers` (`OFFERS_REFERENCE_IMMUTABLE`) and `clients` (`CLIENTS_STATUS_IMMUTABLE`) **reject** one with 400, listing every offending field in `details` — in both cases because the field carries accountability, and a silent no-op would let a client believe it had rewritten history or retired a partner when it had not. A generic read-modify-write-the-whole-object form carried from `institutions` to either of the others will fail on every save. Send only the fields the user actually changed.
- **No host is published here.** Every path in this documentation set is relative to a base URL you must obtain from the deploying team (locally, `http://localhost:8000`). There is no public sandbox environment.
- **The first account requires shell access.** Token issuance exists (`authenticate`), but the initial superadmin is created by the `bootstrap_superadmin` management command, and there is no self-service signup — so the very first credential must be provisioned server-side (§4).
- Rate-limit state is not exposed in response headers — 429 is the only signal (§5).
