# API Documentation — Core Policy Engine

**App:** `core.policy_engine`
**Version:** 1.10.0
**Base prefix:** `/api/v1/policy/`
**Auth:** All endpoints require `IsAuthenticated` + `is_staff` (interim pattern per CLAUDE.md §9)
**Throttle:** Default DRF throttle classes apply (anon: 100/hour, user: 1000/hour)
**Access level:** Internal/staff only — not public

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-06-19 | AI (Claude) | Initial API documentation |
| 1.1.0 | 2026-06-29 | AI (Claude) | Reformats to the project-wide documentation format standard: regroups the previous 7 flat-numbered endpoints into 3 resource groups (`Policy Applications`, `Permission Tree`, `Policy Endpoints`) with `H2`/`H3` hierarchy — no content/contract changes |
| 1.2.0 | 2026-06-30 | AI (Claude) | Adds `is_dependency_root` to the §3.1 endpoint detail response (non-breaking optional field, see `DATA_CONTRACT.md` §3) |
| 1.3.0 | 2026-07-06 | AI (Claude Sonnet 4.6) | P1: §2.1 — add `?include_inactive=true` query param to include inactive/deprecated endpoints in tree; add `is_active` and `is_deprecated` fields to each permission node in the response |
| 1.4.0 | 2026-07-13 | AI (Claude Fable 5) | §3.3 — `is_current` in the versions response is now derived from `PolicyEndpoint.current_version` instead of stored (response shape unchanged, non-breaking; see `DATA_CONTRACT.md` §6). Management-command behavior: `validate_policy_engine` gains rules 11 (registry ↔ DB drift) and 12 (registered routes ↔ actual URL patterns); `sync_policy_registry` schema-validates all declarations before any write and rejects implicit `permission_key`/endpoint-key renames with `PolicyIdentityConflictError` (see `DATA_CONTRACT.md` §3 Identity rule) |
| 1.5.0 | 2026-07-13 | AI (Claude Fable 5) | Gap-closure session, no HTTP contract change. Management-command behavior: `validate_policy_engine` gains rule 13 (current_version ↔ version-record content consistency, see `DATA_CONTRACT.md` §6) and rewords rule 5's message to nudge toward the new `disable_endpoint()` service instead of just flagging deprecated-but-active as a bare warning. Three new lifecycle service functions (`disable_endpoint`, `restore_endpoint`, `remove_dependency`) are not exposed over HTTP — internal/registry-sync use only, see `DATA_CONTRACT.md` §3 and §7 |
| 1.6.0 | 2026-07-13 | AI (Claude Fable 5) | No HTTP contract change. `validate_policy_engine` gains rule 14 — the reverse of rule 12: every routed `/api/v1/` URL must be covered by a registered endpoint, closing the exact gap behind `.claude/FAILURE.md`'s 2026-07-12 entry (a view wired into `urls.py` with no `POLICY_ENDPOINTS` entry previously passed every check). Also fixes two pre-existing rule-13 findings via version bumps in `authenticate`/`organization`'s registries (see those apps' `DEBUG_HISTORY.md`) — `validate_policy_engine --strict` now passes cleanly against the dev database. New `.claude/hooks/check_integration_freshness.sh` (unrelated to this app's own HTTP surface, project-wide governance hook) |
| 1.7.0 | 2026-07-13 | AI (Claude Fable 5) | No HTTP contract change. Rules 12 and 14 become method-aware instead of path-only: `_collect_actual_route_methods()` now inspects each resolved URL entry's view (via `.actions` for DRF `ViewSet`s routed through a `Router`, or `hasattr(cls, verb)` reflection for `.as_view()` class-based views) to determine which HTTP verbs it actually implements, deliberately excluding `options` (DRF's `APIView.options()` is inherited by every subclass and would otherwise always false-positive). Rule 12 now also flags a registered `http_method` that the view doesn't actually implement; rule 14 now flags each individually-uncovered `(path, method)` pair rather than treating "the path exists somewhere in the registry" as full coverage. Confirmed via `validate_policy_engine --strict` against the real dev database: 0 findings — every one of the 106 registered endpoints' declared `http_method` already matches its view's real verb |
| 1.8.0 | 2026-07-13 | AI (Claude Fable 5) | No HTTP contract change. `register_category()`, `map_endpoint_to_category()`, and `add_dependency()` now fully reconcile metadata on resync instead of freezing it at first-creation values (see `DATA_CONTRACT.md` §4, §5, §7); `register_endpoint()`'s update path now also reconciles `operation_type`, `policy_model` re-parenting, and `is_internal` (§3), which were previously accepted as parameters but silently never applied. Running `sync_policy_registry` against the real dev database with this fix surfaced and corrected genuine pre-existing drift: 2 endpoint-category mappings and 3 dependency `reason` fields had silently diverged from their `registry.py` declarations (no `enforcement_mode` drift found — see `DEBUG_HISTORY.md`) |
| 1.9.0 | 2026-07-14 | AI (Claude Fable 5) | §3.4 — the changelog response gains `branch_name` and `based_on_commit_sha`, non-breaking additive fields (see `DATA_CONTRACT.md` §8 Provenance rule). Both are auto-captured by `log_change()`, not caller-supplied. `migration_reference` (pre-existing field, previously always blank) is now actually populated when a caller of `register_model()`/`register_endpoint()`/`run_endpoint_lifecycle()` provides one |
| 1.10.0 | 2026-07-14 | AI (Claude Opus 4.8) | §3.1 and §2.1 — the endpoint-detail response and each permission-tree node gain six retirement-lifecycle fields: `deprecated_at`, `disabled_at`, `sunset_at`, `replaced_by_permission_key`, `removal_ticket`, `removal_reason` (see `DATA_CONTRACT.md` §3). Non-breaking additive fields, `null`/empty for active endpoints. No route/method/permission_key change, so no endpoint version bump. Adds `validate_policy_engine` rule 15 (lifecycle boolean ↔ timestamp consistency) |

## 1. Policy Applications

### 1.1 List — `GET /api/v1/policy/apps/`

**Auth:** IsAuthenticated + is_staff
**Throttle:** Default user rate
**Access:** Staff only

**Response (200):**
```json
{
  "success": true,
  "message": "Policy applications retrieved.",
  "data": [
    {
      "id": "uuid",
      "key": "authenticate",
      "display_name": "Authentication",
      "description": "...",
      "current_version": "1.0.0",
      "is_active": true,
      "is_deprecated": false,
      "created_at": "2026-06-19T00:00:00Z",
      "updated_at": "2026-06-19T00:00:00Z"
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

**Error codes:**
- `AUTHENTICATION_REQUIRED` (401) — no JWT
- `PERMISSION_DENIED` (403) — non-staff user

### 1.2 Detail — `GET /api/v1/policy/apps/<app_key>/`

**Auth:** IsAuthenticated + is_staff
**Path params:** `app_key` — the app's slug key (e.g. `authenticate`)

**Response (200):**
```json
{
  "success": true,
  "message": "Policy application retrieved.",
  "data": {
    "id": "uuid",
    "key": "authenticate",
    "display_name": "Authentication",
    "current_version": "1.0.0",
    "is_active": true,
    "is_deprecated": false,
    "policy_models": [
      { "key": "user", "display_name": "User Account", ... }
    ],
    "endpoints": [
      { "permission_key": "authenticate.user.create", ... }
    ]
  },
  "meta": {}
}
```

**Error codes:**
- `NOT_FOUND` (404) — app_key not found

## 2. Permission Tree

### 2.1 Get UI Permission Tree — `GET /api/v1/policy/permissions/tree/`

**Auth:** IsAuthenticated + is_staff
**Query params:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `app` | string | No | None (all apps) | Filter by `PolicyApplication.key` |
| `include_inactive` | boolean (`true`) | No | `false` | When `true`, includes endpoints where `is_active=False` and categories where `is_active=False` — used by permission management UI to show deprecated permissions |

**Note on `is_active`/`is_deprecated` fields:** Both are always returned on each permission node. When `include_inactive=false` (default), only active nodes are returned, so `is_active` will always be `true` in the normal response. With `include_inactive=true`, `is_active=false` and `is_deprecated=true` nodes are included so the UI can display them distinctly.

**Response (200):**
```json
{
  "success": true,
  "message": "Permission tree retrieved.",
  "data": [
    {
      "app": "authenticate",
      "groups": [
        {
          "key": "user_management",
          "label": "User Management",
          "permissions": [
            {
              "key": "authenticate.user.create",
              "label": "Create User",
              "operation": "create",
              "description": "...",
              "risk_level": "medium",
              "is_sensitive": false,
              "is_active": true,
              "is_deprecated": false,
              "deprecated_at": null,
              "disabled_at": null,
              "sunset_at": null,
              "replaced_by_permission_key": "",
              "removal_ticket": "",
              "removal_reason": "",
              "dependencies": []
            },
            {
              "key": "authenticate.user.delete",
              "label": "Delete User",
              "operation": "delete",
              "description": "...",
              "risk_level": "high",
              "is_sensitive": true,
              "dependencies": ["authenticate.user.read", "authenticate.user.list"]
            }
          ]
        }
      ]
    }
  ],
  "meta": {}
}
```

**Business rules:**
- Only endpoints with `is_visible_in_ui=True` category maps are included
- Only active categories and active endpoints are included
- `dependencies` lists forward/bidirectional required permission keys

## 3. Policy Endpoints

### 3.1 Detail — `GET /api/v1/policy/endpoints/<permission_key>/`

**Auth:** IsAuthenticated + is_staff
**Path params:** `permission_key` — e.g. `authenticate.user.delete`

**Note:** Dots in the permission_key are part of the URL segment. Django routing handles them as part of the `<str:permission_key>` capture.

**Response (200):**
```json
{
  "success": true,
  "message": "Endpoint retrieved.",
  "data": {
    "id": "uuid",
    "application_key": "authenticate",
    "model_key": "user",
    "key": "user-delete",
    "permission_key": "authenticate.user.delete",
    "http_method": "DELETE",
    "route_pattern": "/api/v1/auth/users/<id>/",
    "operation_type": "delete",
    "display_name": "Delete User",
    "risk_level": "high",
    "current_version": "1.0.0",
    "is_internal": false,
    "is_dependency_root": false,
    "is_active": true,
    "is_deprecated": false,
    "deprecated_at": null,
    "disabled_at": null,
    "sunset_at": null,
    "replaced_by_permission_key": "",
    "removal_ticket": "",
    "removal_reason": ""
  },
  "meta": {}
}
```

**Retirement-lifecycle fields:** `deprecated_at`/`disabled_at`/`sunset_at` (ISO-8601, nullable), `replaced_by_permission_key`, `removal_ticket`, `removal_reason` describe the endpoint's current retirement state. All are `null`/empty for a fully-active endpoint, populated by `deprecate_endpoint()`/`disable_endpoint()`, and cleared by `restore_endpoint()` (see `DATA_CONTRACT.md` §3 Lifecycle rule). Non-breaking additive fields.

**Error codes:**
- `NOT_FOUND` (404) — permission_key not found

### 3.2 Dependencies — `GET /api/v1/policy/endpoints/<permission_key>/dependencies/`

**Auth:** IsAuthenticated + is_staff

**Response (200):**
```json
{
  "success": true,
  "message": "Endpoint dependencies retrieved.",
  "data": {
    "forward": [
      {
        "target_endpoint__permission_key": "authenticate.user.read",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": "User must be readable before delete access is meaningful."
      }
    ],
    "backward": []
  },
  "meta": {}
}
```

**Business rules:**
- `forward`: dependencies where this endpoint is the source (what this endpoint requires)
- `backward`: dependencies where this endpoint is the target (what would break if this is removed)

**Error codes:**
- `NOT_FOUND` (404) — permission_key not found

### 3.3 Version History — `GET /api/v1/policy/endpoints/<permission_key>/versions/`

**Auth:** IsAuthenticated + is_staff

**Response (200):**
```json
{
  "success": true,
  "message": "Endpoint versions retrieved.",
  "data": [
    {
      "id": "uuid",
      "permission_key": "authenticate.user.delete",
      "version": "1.1.0",
      "route_pattern": "/api/v1/auth/users/<id>/",
      "http_method": "DELETE",
      "operation_type": "delete",
      "snapshot": { ... },
      "is_current": true,
      "is_deprecated": false,
      "created_at": "2026-06-19T00:00:00Z"
    }
  ],
  "meta": {}
}
```

**Business rules:**
- Ordered by `created_at` descending (most recent first)
- Historical records are never deleted
- `is_current` is derived per record: `true` iff `version` equals the endpoint's `current_version` (`DATA_CONTRACT.md` §6 Currency rule) — exactly one record is current per endpoint

**Error codes:**
- `NOT_FOUND` (404) — permission_key not found

### 3.4 Changelog — `GET /api/v1/policy/endpoints/<permission_key>/changelog/`

**Auth:** IsAuthenticated + is_staff
**Pagination:** yes (page size 20, max 100)

**Response (200):**
```json
{
  "success": true,
  "message": "Endpoint changelog retrieved.",
  "data": [
    {
      "id": "uuid",
      "application_key": "authenticate",
      "object_type": "endpoint",
      "object_key": "authenticate.user.delete",
      "previous_version": "1.0.0",
      "new_version": "1.1.0",
      "change_type": "route_changed",
      "summary": "Route updated for v2 API.",
      "detail": "...",
      "reason": "API versioning requirement.",
      "issue_reference": "",
      "migration_reference": "0007_add_user_status",
      "branch_name": "add_v2_route_20260619_1000",
      "based_on_commit_sha": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
      "affected_dependencies": ["authenticate.user.read"],
      "backward_compatibility_notes": "Old route /api/v1/... still active until 2026-12-01.",
      "created_by_type": "ai",
      "created_by_identifier": "claude-sonnet",
      "created_at": "2026-06-19T00:00:00Z"
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

**Business rules:**
- Append-only — no update/delete
- AI-generated changes have `created_by_type = "ai"`
- Ordered by `created_at` descending
- `branch_name`/`based_on_commit_sha` are captured automatically for every row (blank if git was unavailable when the row was written); `based_on_commit_sha` is the commit the working tree was based on at write time, **not** the commit that shipped this change (see `DATA_CONTRACT.md` §8 Provenance rule). `issue_reference` is currently always blank — reserved for a future ticket-tracker integration.

**Error codes:**
- `NOT_FOUND` (404) — permission_key not found

## Query Access Patterns

| View | Selector | Access pattern |
|------|----------|---------------|
| App list | `get_registered_apps()` | Filter active, order by key — O(n) |
| App detail | `get_application_by_key()` + nested models/endpoints | FK traversal with select_related |
| Permission tree | `get_ui_permission_tree()` | Grouped join across EndpointCategoryMap + PolicyDependency |
| Endpoint detail | `get_endpoint_by_permission_key()` | Indexed lookup on permission_key |
| Dependencies | `get_endpoint_dependencies()` | Two indexed FK lookups |
| Versions | `get_endpoint_versions()` | FK + ordered by created_at |
| Changelog | `get_endpoint_changelog()` | FK + ordered by created_at, paginated |

**N+1 prevention:** All selectors use `select_related` on FK traversals. The UI permission tree query joins EndpointCategoryMap with endpoints and categories in one query, then fetches forward dependencies per endpoint within the loop. For large datasets, consider a single bulk dependency fetch.

## AI Debugging Notes

- `permission_key` dots in URL paths: Django `<str:...>` capture includes dots, so `auth.user.delete` is captured correctly.
- `PolicyChangeLog` admin: all fields are `readonly_fields` — changes cannot be made via admin.
- `PolicyEndpointVersion` admin: `has_add_permission` and `has_change_permission` both return `False`.
- All API views are read-only (`GET` only) — no write endpoints.
- The `is_staff` check is inline in `_require_staff()` in `views.py`, not in a `permissions.py` file (per CLAUDE.md §9).
