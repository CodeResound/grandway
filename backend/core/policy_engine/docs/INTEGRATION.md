# Integration — Core Policy Engine

**Owner app:** `core.policy_engine`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-21

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-21 | AI (Claude Opus 4.8) | Initial integration contract for the 7 read-only endpoints |

---

## 1. Module

- **Name:** Core Policy Engine — the registry of every endpoint in this backend, its permission key, risk level, dependency edges, version history, and change log. Read-only over HTTP; all writes happen through `sync_policy_registry` at deploy time.
- **Base path:** `/api/v1/policy/`
- **Auth:** Every endpoint requires a JWT bearer token AND `is_staff` on the user. No public endpoints. No per-endpoint exceptions.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `core` | framework | Supplies the response envelope, pagination class, exception handler, and `RequestIDMiddleware` that every response here is shaped by | Responses lose the `{ success, message, data, meta }` envelope; errors return raw DRF bodies |
| Django `auth.User` | FK | The interim access check reads `request.user.is_authenticated` and `request.user.is_staff` (`CLAUDE.md` §9) | Every endpoint returns 403; no caller can be recognised as staff |
| `rest_framework_simplejwt` | framework | Issues and validates the bearer token in the `Authorization` header | Every endpoint returns 401; there is no other accepted credential |

**Note for consumers:** this app has **no dependency on an application-level permission system**. It is the registry that *describes* permissions; it does not *enforce* them beyond the `is_staff` check above. A caller with `is_staff` sees the entire registry.

## 3. Conventions

- **Response:** the project-standard envelope — `{ success: true, message, data, meta }`. See `core/docs/INTEGRATION.md` §3.
- **Error:** `{ success: false, error: { code, message, details }, meta }`.
- **Auth failures:** `AUTHENTICATION_REQUIRED` (401) when no/invalid JWT; `PERMISSION_DENIED` (403) when authenticated but not staff. Both use the error envelope above.
- **Pagination:** applies to `GET /apps/` and the changelog endpoint only. `?page=` and `?page_size=` (default 20, max 100); `meta` carries `count`, `page`, `page_size`, `next`, `previous` as absolute URLs or `null`. The other five endpoints return an unpaginated `data` with `meta: {}`.
- **IDs:** UUID strings. Endpoints are addressed by `permission_key` (e.g. `authenticate.user.delete`), not by UUID — dots are part of the URL segment.
- **Times:** ISO 8601, UTC, `Z`-suffixed.
- **List/search/filter/order params:** only `GET /permissions/tree/` accepts filters — `?app=<app_key>` and `?include_inactive=true`. No search or ordering params exist on any endpoint.

## 4. Models

**PolicyApplication** — `{ id, key, display_name, description, current_version, is_active, is_deprecated, created_at, updated_at }`
- Retrieve-only extras on `GET /apps/<app_key>/`: `policy_models[]` and `endpoints[]`, each a nested list.

**PolicyEndpoint** — `{ id, application_key, model_key, key, permission_key, http_method, route_pattern, operation_type:[enum], display_name, risk_level:[enum], current_version, is_internal, is_dependency_root, is_active, is_deprecated, deprecated_at?, disabled_at?, sunset_at?, replaced_by_permission_key, removal_ticket, removal_reason }`
- The six retirement fields are `null`/empty for a fully active endpoint.

**PermissionTreeNode** — `{ key, label, operation:[enum], description, risk_level:[enum], is_sensitive, is_active, is_deprecated, deprecated_at?, disabled_at?, sunset_at?, replaced_by_permission_key, removal_ticket, removal_reason, dependencies:[string] }`
- Returned nested as `data[].groups[].permissions[]`, grouped by app then by category.

**PolicyDependencyEdge** — `{ target_endpoint__permission_key, dependency_type:[enum], enforcement_mode:[enum], reason }`

**PolicyEndpointVersion** — `{ id, permission_key, version, route_pattern, http_method, operation_type:[enum], snapshot:json, is_current, is_deprecated, created_at }`
- `is_current` is derived, not stored: `true` iff `version` equals the endpoint's `current_version`. Exactly one record is current per endpoint.

**PolicyChangeLog** — `{ id, application_key, permission_key, change_type:[enum], summary, reason, created_by_type:[enum], created_by_identifier, branch_name, based_on_commit_sha, migration_reference, created_at }`

### Worked examples

One realistic `data` payload per shape above, so no field type has to be inferred from the shorthand. Each is the value of `data` in the standard envelope (`core/docs/INTEGRATION.md` §3).

`GET /endpoints/<permission_key>/` → **PolicyEndpoint**:

```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "application_key": "policy_engine",
  "model_key": "application",
  "key": "application-list",
  "permission_key": "policy_engine.application.list",
  "http_method": "GET",
  "route_pattern": "/api/v1/policy/apps/",
  "operation_type": "list",
  "display_name": "List Policy Applications",
  "risk_level": "low",
  "current_version": "1.0.0",
  "is_internal": false,
  "is_dependency_root": true,
  "is_active": true,
  "is_deprecated": false,
  "deprecated_at": null,
  "disabled_at": null,
  "sunset_at": null,
  "replaced_by_permission_key": "",
  "removal_ticket": "",
  "removal_reason": ""
}
```

`GET /permissions/tree/` → grouped tree (`data` is an array of apps):

```json
[
  {
    "app": "policy_engine",
    "groups": [
      {
        "key": "policy_engine_administration",
        "label": "Policy Engine Administration",
        "permissions": [
          {
            "key": "policy_engine.application.read",
            "label": "Read Policy Application",
            "operation": "read",
            "description": "Retrieve one registered policy application.",
            "risk_level": "low",
            "is_sensitive": false,
            "is_active": true,
            "is_deprecated": false,
            "deprecated_at": null,
            "disabled_at": null,
            "sunset_at": null,
            "replaced_by_permission_key": "",
            "removal_ticket": "",
            "removal_reason": "",
            "dependencies": ["policy_engine.application.list"]
          }
        ]
      }
    ]
  }
]
```

`GET /endpoints/<permission_key>/dependencies/` → **note this one is an object, not an array**:

```json
{
  "forward": [
    {
      "target_endpoint__permission_key": "policy_engine.application.list",
      "dependency_type": "requires",
      "enforcement_mode": "strict",
      "reason": "Applications must be listable before one can be read."
    }
  ],
  "backward": []
}
```

`GET /endpoints/<permission_key>/versions/` → array of **PolicyEndpointVersion**:

```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "permission_key": "policy_engine.application.list",
    "version": "1.0.0",
    "route_pattern": "/api/v1/policy/apps/",
    "http_method": "GET",
    "operation_type": "list",
    "snapshot": {},
    "is_current": true,
    "is_deprecated": false,
    "created_at": "2026-07-21T06:15:00Z"
  }
]
```

`GET /endpoints/<permission_key>/changelog/` → array of **PolicyChangeLog** (paginated):

```json
[
  {
    "id": "9b2fd1e0-1c4a-4f77-9d2e-8a1b3c4d5e6f",
    "application_key": "policy_engine",
    "permission_key": "policy_engine.application.list",
    "change_type": "created",
    "summary": "Registered endpoint.",
    "reason": "Initial registry sync.",
    "created_by_type": "ai",
    "created_by_identifier": "claude-opus-4-8",
    "branch_name": "main",
    "based_on_commit_sha": "646b310",
    "migration_reference": "",
    "created_at": "2026-07-21T06:15:00Z"
  }
]
```

`snapshot` is an opaque JSON object — its internal keys are not contractually pinned (§9).

## 5. Enums

- `PolicyEndpoint.operation_type`: `create` | `read` | `list` | `update` | `delete` | `custom`
- `PolicyEndpoint.risk_level`: `low` | `medium` | `high` | `critical`
- `PolicyDependencyEdge.dependency_type`: `requires` | `implies` | `conflicts_with` | `revokes_with` | `suggests`
- `PolicyDependencyEdge.enforcement_mode`: `strict` | `warning` | `manual_review` | `metadata_only`
- `PolicyChangeLog.change_type`: `created` | `updated` | `bug_fix` | `security_fix` | `route_changed` | `method_changed` | `dependency_added` | `dependency_removed` | `category_changed` | `deprecated` | `removed` | `restored` | `breaking_change` | `metadata_update`
- `PolicyChangeLog.created_by_type`: `human` | `ai` | `system`

## 6. Dependency order

- `PolicyEndpoint` needs `PolicyApplication` (every endpoint belongs to a registered app)
- `PolicyEndpointVersion`, `PolicyDependencyEdge`, `PolicyChangeLog` all need `PolicyEndpoint`
- Nothing here is client-creatable — this module is read-only over HTTP. Records appear only when a backend maintainer runs `sync_policy_registry`.

**Start here:** `GET /api/v1/policy/apps/` to discover which apps exist, then `GET /api/v1/policy/permissions/tree/` for the full permission surface in one call.

## 7. Endpoints

### Policy Applications — `/api/v1/policy/apps/`

**Use it when:** building a permission-administration screen and you need the list of apps that own permissions, or the full detail of one app including its models and endpoints.
**Methods:**
- `GET /api/v1/policy/apps/` — list all registered applications (permission: `policy_engine.application.list`, risk: low)
- `GET /api/v1/policy/apps/<app_key>/` — one application with nested models and endpoints (permission: `policy_engine.application.read`, risk: low)
**Send (create/update):** none — read-only resource.
**Returns:** list[PolicyApplication] on list; PolicyApplication on detail, with retrieve-only `policy_models[]` and `endpoints[]`.
**Requires state:** the caller's user record must have `is_staff = true`. No other resource needs to exist — the list endpoint returns an empty `data` array on a registry that has never been synced.
**Side effects:** none — no writes, no events, no counters.
**Notes:**
- `app_key` is the slug key (e.g. `authenticate`), not a UUID.
- The list endpoint is paginated; the detail endpoint is not.
**Errors:**
- `NOT_FOUND` (404) — `app_key` does not match a registered application.

### Permission Tree — `/api/v1/policy/permissions/tree/`

**Use it when:** rendering a permission picker or role editor — this returns the entire assignable permission surface, grouped app → category → permission, in a single request.
**Methods:**
- `GET /api/v1/policy/permissions/tree/` — grouped permission tree (permission: `policy_engine.permission.tree`, risk: low)
**Send (create/update):** none — read-only resource.
**Returns:** list of `{ app, groups[] }`, where each group is `{ key, label, permissions: list[PermissionTreeNode] }`.
**Requires state:** caller must be `is_staff`. Endpoints only appear here if they have a category mapping with `is_visible_in_ui = true` and an active category — a registered endpoint with no category mapping is silently absent from this tree, though it still exists in the registry.
**Side effects:** none.
**Notes:**
- `?app=<app_key>` restricts to one application.
- `?include_inactive=true` adds endpoints with `is_active=false` and deprecated categories, so a UI can show retired permissions distinctly. Default is `false`, in which case every returned node has `is_active: true`.
- Each node's `dependencies` array lists forward and bidirectional required permission keys — a role editor should require those to be selected alongside.
- Not paginated; returns the whole tree.
**Errors:** none beyond the global auth failures.

### Policy Endpoints — `/api/v1/policy/endpoints/<permission_key>/`

**Use it when:** inspecting one permission in depth — its route and method, its risk, what it requires, how it has changed, and whether it is being retired.
**Methods:**
- `GET /api/v1/policy/endpoints/<permission_key>/` — endpoint detail (permission: `policy_engine.endpoint.read`, risk: low)
- `GET /api/v1/policy/endpoints/<permission_key>/dependencies/` — forward and backward dependency edges (permission: `policy_engine.endpoint.read_dependencies`, risk: low)
- `GET /api/v1/policy/endpoints/<permission_key>/versions/` — append-only version history (permission: `policy_engine.endpoint.read_versions`, risk: low)
- `GET /api/v1/policy/endpoints/<permission_key>/changelog/` — append-only change log (permission: `policy_engine.endpoint.read_changelog`, risk: low)
**Send (create/update):** none — all four are read-only.
**Returns:**
- detail → PolicyEndpoint
- dependencies → `{ forward: list[PolicyDependencyEdge], backward: list[PolicyDependencyEdge] }`
- versions → list[PolicyEndpointVersion]
- changelog → list[PolicyChangeLog]
**Requires state:** caller must be `is_staff`, and `<permission_key>` must name an endpoint already present in the registry. All four sub-resources 404 on an unknown key rather than returning an empty list.
**Side effects:** none.
**Notes:**
- `permission_key` contains dots and is captured as a single URL segment — send `authenticate.user.delete`, not an escaped form.
- `forward` = what this endpoint requires; `backward` = what would break if this endpoint were removed. A UI revoking a permission should warn using `backward`.
- Only the changelog endpoint is paginated. Versions and dependencies return the full set.
- Versions are ordered most-recent-first and are never deleted; exactly one has `is_current: true`.
**Errors:**
- `NOT_FOUND` (404) — `permission_key` does not match a registered endpoint. Applies to all four methods.

## 8. Flows

**Render a role editor and save a valid selection**
1. `GET /api/v1/policy/permissions/tree/` → the full grouped surface.
2. Render `data[].groups[].permissions[]`, using `risk_level` and `is_sensitive` to style high-risk entries.
3. When the operator selects a permission, also select everything in its `dependencies` array.
   - If a dependency is unavailable, block the save: a `strict` dependency will be rejected server-side by the permissions authority, not by this module.
4. Submit the selection to the permission-granting API (a different app — not part of this module).

**Show why a permission cannot be revoked**
1. `GET /api/v1/policy/endpoints/<permission_key>/dependencies/` → capture `backward`.
2. If `backward` is non-empty, list those permission keys as blockers before allowing the revoke.
   - Empty `backward` means nothing else declares a dependency on it.

**Explain an endpoint's history in an audit view**
1. `GET /api/v1/policy/endpoints/<permission_key>/` → current state, including the six retirement fields.
2. If `is_deprecated` is `true`, read `sunset_at` and `replaced_by_permission_key` to tell the consumer what to migrate to and by when.
3. `GET /api/v1/policy/endpoints/<permission_key>/versions/` → contract changes over time.
4. `GET /api/v1/policy/endpoints/<permission_key>/changelog/?page=1` → who changed what and why, including whether a `human` or an `ai` made the change.
   - 404 at any step means the key was never registered, not that it was deleted — endpoints are retired via deprecation, never removed from the registry.

## 9. Gaps

- The error envelope's `error.details` is always present but is an empty object `{}` on 401/403/404 — only validation failures populate it, and this module accepts no input to validate, so in practice it is always `{}` here.
- `snapshot` on PolicyEndpointVersion is typed only as a JSON object; its internal keys are not contractually pinned.
- No endpoint exposes `PolicyModel` directly — models are visible only nested inside the application-detail response.
- Rate limits are the project defaults (anon 100/hour, user 1000/hour) and are not surfaced in any response header.
