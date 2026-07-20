# Integration — Grandway Backend

**Owner app:** `core`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-21
**Purpose:** The entry point for anyone — human or AI — integrating a client against this backend from outside the repository. Read this file first, then the per-app `INTEGRATION.md` for each app you consume.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-21 | AI (Claude Opus 4.8) | Initial project-level integration entry point |

---

> ## ⚠ Read first: this API is not callable end-to-end yet
>
> There is **no token-issuance endpoint**. JWT is the only accepted credential, and no login or
> token route is wired into `/api/v1/` — the app that will own authentication does not exist yet.
>
> **An external client cannot authenticate, and therefore cannot reach any `/api/v1/` endpoint
> today.** The contracts below are real, stable, and CI-verified, but you cannot exercise them from
> outside this server yet. The only way to mint a token requires shell access to the backend host
> (§4) — which the intended reader of this document does not have. If you are planning an
> integration, this is the blocker to resolve first, and it is not resolvable from the client side.
>
> Everything else in this document is accurate and safe to build against in advance.

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

**Error codes.** `APP_RESOURCE_REASON` in upper snake case (e.g. `LISTINGS_LISTING_NOT_FOUND`). Codes are stable — treat them as part of the contract. Global codes: `AUTHENTICATION_REQUIRED` (401), `PERMISSION_DENIED` (403), `NOT_FOUND` (404), `VALIDATION_ERROR` (400), `INTERNAL_SERVER_ERROR` (500).

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

**No token-issuance endpoint exists** (see the warning at the top of this file). The token *lifetimes*
below are the configured SimpleJWT settings and describe how a token will behave once issued — they
do **not** imply a refresh flow you can call today, because no endpoint issues or refreshes tokens.

- Access token lifetime: 60 minutes (24 hours in development).
- Refresh token lifetime: 7 days, rotated on use. *(Configured, but unreachable — no refresh route exists.)*
- In production the refresh token will be an HttpOnly cookie; in development, returned in the body. *(Planned behaviour of the future auth app, not current behaviour.)*

**Getting a token today — backend-host access required.** This is not something the intended reader of
this document can do; it is recorded so a backend operator can hand you a token out of band:

```
python backend/manage.py shell -c "from rest_framework_simplejwt.tokens import RefreshToken; from django.contrib.auth import get_user_model; print(RefreshToken.for_user(get_user_model().objects.get(is_staff=True)).access_token)"
```

When the authentication app ships it will publish its own `INTEGRATION.md` with real token endpoints,
and this section will be replaced by a pointer to it.

**Authorization today.** Endpoints are protected by an interim check: authenticated **and** `is_staff`. There is no role- or permission-key-based enforcement in the request path yet — the Core Policy Engine *describes* the permission surface but does not yet gate requests with it (`CLAUDE.md` §9). A consumer should therefore expect `PERMISSION_DENIED` for any non-staff user on any protected endpoint, regardless of the endpoint's declared `permission_key`.

Every endpoint denies by default. Any public endpoint is explicitly marked as such in its app's `INTEGRATION.md`.

**Health checks** are the exception — `GET /health/` (liveness) and `GET /ready/` (readiness, includes DB connectivity) require no auth and are excluded from rate limiting.

## 5. Rate limiting

Project defaults: 100 requests/hour for anonymous callers, 1000/hour for authenticated ones. Exceeding them returns 429. Limits are not currently surfaced in response headers — treat 429 as the signal and back off.

## 6. App inventory

| App | Base path | Purpose | Contract |
|-----|-----------|---------|----------|
| `core.policy_engine` | `/api/v1/policy/` | Read-only registry of every endpoint in this backend: permission keys, risk levels, dependency edges, version history, change log | `core/policy_engine/docs/INTEGRATION.md` |

**Routes outside `/api/v1/`.** `core` exposes three, and they are deliberately outside the registry-completeness guarantee in §9 (which covers `/api/v1/` only). They have no permission key and are not client API surface:

| Route | Auth | For consumers |
|-------|------|---------------|
| `GET /health/` | none | Liveness probe. Returns 200 while the process is up. Safe to poll; excluded from rate limiting. |
| `GET /ready/` | none | Readiness probe, includes DB connectivity. Returns 200 only when able to serve. Safe to poll; excluded from rate limiting. |
| `/admin/` | session login | Django's built-in admin UI for internal staff. **Not an API** — no JSON contract, no stable surface. Never integrate against it. |

## 7. Cross-app dependency graph

Assembled from each app's `INTEGRATION.md` §2 `Requires`. Use it to determine integration order: an app's dependencies must be usable before it is.

- `core.policy_engine` → `core` (framework), Django `auth.User` (FK), `rest_framework_simplejwt` (framework)

No app-to-app runtime coupling exists yet. When it does, each edge appears in **both** apps' §2 sections — the depended-on app records what would break, the depending app records why it needs it.

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
- Permission-key-based authorization is not yet enforced in the request path (see §4); only `is_staff` is.
- **No token-issuance endpoint exists yet** (§4) — the single biggest blocker to an end-to-end integration today.
- **No host is published here.** Every path in this documentation set is relative to a base URL you must obtain from the deploying team (locally, `http://localhost:8000`). There is no public sandbox environment.
- Rate-limit state is not exposed in response headers — 429 is the only signal (§5).
