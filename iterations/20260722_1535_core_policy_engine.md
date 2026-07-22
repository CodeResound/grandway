## Core Policy Engine

## 1. Module

- **Name:** Core Policy Engine
- **Base path:** `/api/v1/policy/`
- **Auth:** JWT bearer token AND `is_staff`. No changes this session.

## 2. Conventions

No changes this session. See `backend/core/policy_engine/docs/INTEGRATION.md` §3 for the current conventions.

## 3. Models

No model, field, or shape changes this session.

## 4. Enums

No enum changes this session.

## 5. Dependency order

No changes this session.

## 6. Endpoints

No endpoints were created, modified, or retired this session. This was a documentation-layer session: it added the frontend flow-binding layer (`concepts/policy_engine_flows.md`) that references the existing 7 read-only endpoints, and the repo-level consumer entry point (`FRONTEND_README.md`) and flow-file template (`concepts/_FLOWS_TEMPLATE.md`). No endpoint contract, route, method, permission key, or registry entry changed.

## 7. Flows

No API contract change. For reference, the newly documented frontend flows binding the existing endpoints to screens are in `concepts/policy_engine_flows.md`: "Render a role editor from the full permission surface", "Audit one permission's full history", and "Warn before revoking a permission". These describe UI journeys over unchanged endpoints, not new API behavior.

## 8. Gaps

- Pre-existing (unchanged this session, flagged for a future policy-engine doc session): `backend/core/policy_engine/docs/INTEGRATION.md` §4 does not define the field set of the nested `policy_models[]` elements returned by `GET /api/v1/policy/apps/<app_key>/`, and does not state whether nested `endpoints[]` elements are full `PolicyEndpoint` shapes; `is_internal` and `is_dependency_root` on `PolicyEndpoint` are returned but not described. Surfaced by the §19.5 blind-consumer verification run during this session.
