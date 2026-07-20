# Session — 2026-07-21 01:10 — core, policy_engine

Branch: `add_integration_contract_20260721_0032`

Scope: documentation architecture only. No endpoint, model, serializer, migration, or HTTP contract changed this session — the registry's 7 endpoints are byte-identical before and after. What changed is a new consumer-facing doc type, its enforcement gate, and the rulebook wiring.

## Core

## 1. Module

- **Name:** core — global infrastructure. Gains the project-level integration entry point and the `validate_integration_docs` gate.
- **Base path:** no `/api/v1/` surface of its own.
- **Auth:** unchanged.

## 2. Conventions

No change. Envelope, error shape, pagination, IDs, and times are as previously documented — now stated once, canonically, in `core/docs/INTEGRATION.md` §3 with worked examples rather than only in prose.

## 3. Models

No model created or modified this session.

## 4. Enums

No enum created or modified this session.

## 5. Dependency order

Unchanged.

**Start here:** not applicable — no client-facing resources in this app.

## 6. Endpoints

No endpoint changes this session. `core` exposes `/health/`, `/ready/`, `/admin/`, none of which changed.

## 7. Flows

No client-facing flow changes this session.

## 8. Gaps

- No token-issuance endpoint exists anywhere in this backend. JWT is the only accepted credential and no login or refresh route is wired into `/api/v1/`, so an external client cannot authenticate at all. Discovered by this session's comprehension test; now documented at the top of `core/docs/INTEGRATION.md` and in its §10.
- Prose field descriptions are not mechanically verified against serializers. The new gate proves the endpoint *inventory* is complete, not that every field description is accurate.

---

## Policy Engine

## 1. Module

- **Name:** Core Policy Engine — read-only registry of endpoints, permission keys, dependency edges, versions, and change log.
- **Base path:** `/api/v1/policy/`
- **Auth:** JWT bearer + `is_staff`. Unchanged this session.

## 2. Conventions

No change. Now published for consumers in `core/policy_engine/docs/INTEGRATION.md` §3, including which two of the seven endpoints paginate.

## 3. Models

No model created or modified. The existing read shapes are now documented consumer-side with a realistic worked payload each: PolicyApplication, PolicyEndpoint, PermissionTreeNode, PolicyDependencyEdge, PolicyEndpointVersion, PolicyChangeLog.

## 4. Enums

No enum created or modified. Full value sets are now published consumer-side:

- `PolicyEndpoint.operation_type`: `create` | `read` | `list` | `update` | `delete` | `custom`
- `PolicyEndpoint.risk_level`: `low` | `medium` | `high` | `critical`
- `PolicyDependencyEdge.dependency_type`: `requires` | `implies` | `conflicts_with` | `revokes_with` | `suggests`
- `PolicyDependencyEdge.enforcement_mode`: `strict` | `warning` | `manual_review` | `metadata_only`
- `PolicyChangeLog.change_type`: `created` | `updated` | `bug_fix` | `security_fix` | `route_changed` | `method_changed` | `dependency_added` | `dependency_removed` | `category_changed` | `deprecated` | `removed` | `restored` | `breaking_change` | `metadata_update`
- `PolicyChangeLog.created_by_type`: `human` | `ai` | `system`

## 5. Dependency order

- `PolicyEndpoint` needs `PolicyApplication`
- `PolicyEndpointVersion`, `PolicyDependencyEdge`, `PolicyChangeLog` each need `PolicyEndpoint`

**Start here:** `GET /api/v1/policy/apps/`

## 6. Endpoints

No endpoint added, modified, retired, or re-versioned this session. All 7 keep their route, method, permission key, risk level, and version.

One documentation correction affecting what a client should match on: the 401 and 403 error codes in `INTEGRATION_GUIDE.md` §6 were wrong. They read `AUTH_NOT_AUTHENTICATED` / `AUTH_PERMISSION_DENIED`; the values `core/exceptions.py` actually returns are `AUTHENTICATION_REQUIRED` / `PERMISSION_DENIED`. Corrected. No code changed — the doc was wrong, not the behavior.

## 7. Flows

Three consumer flows newly documented (behavior pre-existing, never written down): rendering a role editor with dependency-aware selection; using the `backward` dependency array to determine whether revoking a permission is safe; and reconstructing an endpoint's history across the detail, versions, and changelog endpoints.

## 8. Gaps

- `snapshot` on PolicyEndpointVersion is an opaque JSON object; its internal keys are not contractually pinned.
- `PolicyModel` is not exposed by any endpoint directly — visible only nested inside the application-detail response.
- Rate limits are project defaults and are not surfaced in response headers.
- Request/response body schemas remain absent from `openapi.json`; the registry does not model them. Deferred deliberately — see the session plan.
