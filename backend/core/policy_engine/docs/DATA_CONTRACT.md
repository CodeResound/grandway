# Data Contract — Core Policy Engine

**Owner app:** `core.policy_engine`
**Version:** 2.4.0
**Status:** Active
**Created:** 2026-06-19
**Purpose:** Authoritative metadata registry for access-control definitions, endpoint versioning, dependency management, and AI/human lifecycle audit trail.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-06-19 | AI (Claude) | Initial contract for all 8 policy engine models |
| 1.1.0 | 2026-06-29 | AI (Claude) | Reformats to the project-wide documentation format standard: renames choice-callout lines to the `` `field` choices: `` convention and adds the matching `, choices` Type-column marker for `operation_type`/`risk_level` (§3), `direction`/`dependency_type`/`enforcement_mode` (§7), `change_type`/`created_by_type`/`object_type` (§8) — no content/contract changes |
| 1.2.0 | 2026-06-30 | AI (Claude) | Adds `is_dependency_root` field to `PolicyEndpoint` (§3) — exempts a high/critical-risk endpoint that legitimately has no prerequisite (e.g. `authenticate.user.login`) from the "must declare a dependency" validation rule |
| 2.0.0 | 2026-07-13 | AI (Claude) | Drops `PolicyEndpointVersion.is_current` (§6) — the stored flag conflicted with the model's append-only guards and could never be flipped; version currency is now derived from `PolicyEndpoint.current_version` (API response shape unchanged: `is_current` is still serialized, computed). Adds the endpoint identity rule (§3): a `permission_key` or endpoint `key` rename in a registry declaration is rejected with `PolicyIdentityConflictError` — renames require an explicit new-endpoint + deprecation step |
| 2.1.0 | 2026-07-13 | AI (Claude Fable 5) | Gap-closure session. Adds the staged-deletion lifecycle rule (§3): `disable_endpoint()`/`restore_endpoint()` alongside existing `deprecate_endpoint()`. Adds the version-conflict integrity rule (§6): reusing an `(endpoint, version)` pair with different content now raises `PolicyVersionConflictError`; `create_version()`'s `snapshot` param is now honored. Adds the dependency removal rule (§7): `remove_dependency()` soft-removes (`is_active=False`), never hard-deletes, plus documents `enforcement_mode` as the field the `permissions` app's grant-time dependency enforcement reads. Adds real versioning to `PolicyApplication`/`PolicyModel` (§1, §2): `current_version` now updates in place with a logged changelog entry on re-registration with a differing version, instead of being write-once decorative |
| 2.2.0 | 2026-07-13 | AI (Claude Fable 5) | Adds reconciliation rules to §3 `PolicyEndpoint` (`operation_type`/`policy_model`/`is_internal` now actually reconciled — previously accepted as parameters but silently never applied on resync), §4 `PermissionCategory` (`description`/`icon_key`/`sort_order`/`application`/`policy_model`/`parent`, not just `display_name`), §5 `EndpointCategoryMap` (`display_label`/`help_text`/`sort_order`/`is_visible_in_ui`/`is_sensitive` — previously nothing at all reconciled), and §7 `PolicyDependency` (`enforcement_mode`/`reason` — previously frozen at first-creation values, a live security gap given `enforcement_mode`'s consumption by `permissions`' grant-time enforcement) |
| 2.3.0 | 2026-07-13 | AI (Claude Fable 5) | Adds `branch_name`/`based_on_commit_sha` fields to §8 `PolicyChangeLog`, auto-captured by `log_change()` via a best-effort git subprocess call (see new Provenance rule, §8) — non-breaking additive schema change, migration `0005_add_changelog_git_provenance`. Wires the pre-existing but previously-dead `migration_reference` field through `register_model()`/`register_endpoint()` and `run_endpoint_lifecycle`'s config surface. Documents `issue_reference` as deliberately reserved/unpopulated pending a future ticket-tracker integration, not a bug |
| 2.4.0 | 2026-07-14 | AI (Claude Opus 4.8) | Adds six denormalized retirement-lifecycle fields to §3 `PolicyEndpoint` — `deprecated_at`, `disabled_at`, `sunset_at`, `replaced_by_permission_key`, `removal_ticket`, `removal_reason` — set/cleared by `deprecate_endpoint()`/`disable_endpoint()`/`restore_endpoint()` (see updated Lifecycle rule, §3). Non-breaking additive schema change, migration `0006_add_endpoint_lifecycle_metadata` (best-effort backfill of `deprecated_at`/`disabled_at` from `PolicyChangeLog`). The append-only changelog remains the authoritative event history; these fields hold only current state for cheap audit queries. Exposed read-only via `PolicyEndpointSerializer` and the UI permission-tree nodes. Adds `validate_policy_engine` rule 15 (lifecycle boolean ↔ timestamp consistency) |

---

## 1. PolicyApplication

**Purpose:** Registers a logical Django app or backend module in the policy registry.

**Table:** `policy_engine_policyapplication`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|-------------|
| id | UUID | — | No | Yes | Primary key, auto-generated |
| key | SlugField(100) | Yes | No | No | Unique stable identifier (e.g. `authenticate`) |
| display_name | CharField(255) | Yes | No | No | Human-readable name |
| description | TextField | No | No | No | Optional longer description |
| current_version | CharField(50) | No | No | No | Semantic version, default `1.0.0` |
| is_active | Boolean | No | No | No | Default `True` |
| is_deprecated | Boolean | No | No | No | Default `False` |
| created_at | DateTimeField | — | No | Yes | Auto set on creation |
| updated_at | DateTimeField | — | No | Yes | Auto set on update |

**Validation rules:**
- `key` must be unique, lowercase slug
- `current_version` must match `MAJOR.MINOR.PATCH`

**Versioning rule:** `register_application()` updates `current_version` in place when called again with a differing valid version, logging a `metadata_update` changelog entry with `previous_version`/`new_version` (§8). No separate per-application version-history model exists — only the current pointer and the changelog trail.

**Example:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "key": "authenticate",
  "display_name": "Authentication",
  "description": "Handles user authentication and JWT tokens.",
  "current_version": "1.0.0",
  "is_active": true,
  "is_deprecated": false
}
```

---

## 2. PolicyModel

**Purpose:** Registers a model/entity within a PolicyApplication.

**Table:** `policy_engine_policymodel`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|-------------|
| id | UUID | — | No | Yes | Primary key |
| application | FK → PolicyApplication | Yes | No | No | Owning app |
| key | SlugField(100) | Yes | No | No | Stable key within app scope (e.g. `user`) |
| import_path | CharField(500) | No | No | No | Optional Python import path |
| display_name | CharField(255) | Yes | No | No | Human-readable name |
| description | TextField | No | No | No | Optional description |
| current_version | CharField(50) | No | No | No | Semantic version, default `1.0.0` |
| is_active | Boolean | No | No | No | Default `True` |
| is_deprecated | Boolean | No | No | No | Default `False` |
| created_at | DateTimeField | — | No | Yes | Auto |
| updated_at | DateTimeField | — | No | Yes | Auto |

**Unique constraint:** `(application, key)`

**Versioning rule:** Same as `PolicyApplication` (§1) — `register_model()` updates `current_version` in place on a differing valid version, logging a `metadata_update` changelog entry with `previous_version`/`new_version`.

**Example:**
```json
{
  "application": "authenticate",
  "key": "user",
  "display_name": "User Account",
  "import_path": "authenticate.models.UserAccount",
  "current_version": "1.0.0"
}
```

---

## 3. PolicyEndpoint

**Purpose:** Registers an API endpoint, view action, or permission-controlled operation.

**Table:** `policy_engine_policyendpoint`

**`operation_type` choices:** `create`, `read`, `list`, `update`, `delete`, `custom`
**`risk_level` choices:** `low`, `medium`, `high`, `critical`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|-------------|
| id | UUID | — | No | Yes | Primary key |
| application | FK → PolicyApplication | Yes | No | No | Owning app |
| policy_model | FK → PolicyModel | No | Yes | No | Owning model (nullable for app-level endpoints) |
| key | SlugField(100) | Yes | No | No | Stable key within app scope |
| permission_key | CharField(255) | Yes | No | No | Global unique key: `app.model.action` |
| http_method | CharField(20) | No | No | No | e.g. `GET`, `POST`, blank for service-only |
| route_pattern | CharField(500) | No | No | No | URL pattern |
| view_import_path | CharField(500) | No | No | No | Python import path of view |
| operation_type | CharField(50), choices | Yes | No | No | One of the 6 operation types |
| display_name | CharField(255) | Yes | No | No | Human-readable name |
| description | TextField | No | No | No | Description |
| current_version | CharField(50) | No | No | No | Semantic version, default `1.0.0` |
| risk_level | CharField(50), choices | No | No | No | Default `low` |
| is_internal | Boolean | No | No | No | System-only, default `False` |
| is_dependency_root | Boolean | No | No | No | Default `False`. `True` exempts a high/critical-risk endpoint with zero outgoing dependencies from the validation rule that otherwise flags it as missing dependency metadata — for endpoints that legitimately have no prerequisite (e.g. `authenticate.user.login`) |
| is_active | Boolean | No | No | No | Default `True` |
| is_deprecated | Boolean | No | No | No | Default `False` |
| deprecated_at | DateTimeField | No | Yes | Yes | Set by `deprecate_endpoint()`; cleared by `restore_endpoint()`. Denormalized current-state timestamp (event history stays in `PolicyChangeLog`) |
| disabled_at | DateTimeField | No | Yes | Yes | Set by `disable_endpoint()`; cleared by `restore_endpoint()` |
| sunset_at | DateTimeField | No | Yes | No | Planned removal date, caller-provided at deprecation time; cleared by `restore_endpoint()`. No default window is computed |
| replaced_by_permission_key | CharField(255) | No | No | No | `permission_key` of the successor endpoint, if any. Loose string pointer (not a FK — the successor may not be registered yet); cleared by `restore_endpoint()` |
| removal_ticket | CharField(255) | No | No | No | External tracker reference for the removal; reserved-but-empty until a ticketing convention exists (mirrors `PolicyChangeLog.issue_reference`); cleared by `restore_endpoint()` |
| removal_reason | TextField | No | No | No | Why the endpoint is being retired; unicode-normalized on write (§39.2); cleared by `restore_endpoint()` |
| created_at | DateTimeField | — | No | Yes | Auto |
| updated_at | DateTimeField | — | No | Yes | Auto |

`deprecated_at`/`disabled_at`/`sunset_at` are system-internal lifecycle timestamps and carry **no Bikram Sambat representation** (consistent with `created_at`/`updated_at`, §39.4).

**Unique constraints:** `permission_key` globally unique; `(application, key)` unique

**Permission key format:** `<app_key>.<model_key>.<operation>` — all lowercase, snake_case

**Identity rule:** An endpoint's identity is the pair `((application, key), permission_key)`. Registration (`register_endpoint` / registry sync) rejects any declaration that changes one half of an already-registered pair with `PolicyIdentityConflictError` — a rename is a breaking change for permission consumers (role bindings reference `permission_key`) and must be performed explicitly: register the new key as a new endpoint, then deprecate the old one.

**Lifecycle rule (staged deletion):** An endpoint is never hard-deleted through the service layer. Lifecycle stages, in order: active → `deprecate_endpoint()` (sets `is_deprecated=True`, stays `is_active=True` — the sunset window; `validate_policy_engine` rule 5 surfaces this as an intentional WARNING nudge, not an error) → `disable_endpoint()` (requires the endpoint already be deprecated; sets `is_active=False`, logs `change_type=removed`) → optionally `restore_endpoint()` at any point to reverse either stage back to fully active. `disable_endpoint()` raises `PolicyLifecycleIncompleteError` if called on a non-deprecated endpoint. Each transition also records denormalized current-state metadata directly on the endpoint so audit queries are plain field reads rather than `PolicyChangeLog` scans: `deprecate_endpoint()` sets `deprecated_at` and the caller-provided `sunset_at` / `replaced_by_permission_key` / `removal_ticket` and stores `reason` in `removal_reason`; `disable_endpoint()` sets `disabled_at`; `restore_endpoint()` clears all six (the full event history is preserved in the append-only `PolicyChangeLog`). `validate_policy_engine` rule 15 asserts these timestamps stay consistent with `is_deprecated`/`is_active`.

**Reconciliation rule:** Re-registering an already-existing endpoint (same identity, §above) via `register_endpoint()` reconciles every mutable field against the incoming declaration, not just a subset — `display_name`, `description`, `operation_type`, `risk_level`, `view_import_path`, `http_method`, `route_pattern`, `is_internal`, `is_dependency_root`, and `policy_model` (re-parenting, only when a `model_key` is actually provided — an omitted `model_key` never nulls out an existing relation) all update in place and log a `metadata_update`/`route_changed`/`method_changed` changelog entry when any changed. String/optional fields (`display_name`, `description`, `view_import_path`, `route_pattern`, `http_method`, `operation_type`) are blank-gated — an empty value in the declaration never overwrites existing content. `operation_type` was historically accepted but silently never reconciled; fixed alongside the category/mapping/dependency reconciliation gaps below (2026-07-13, see `DEBUG_HISTORY.md`).

**Example:**
```json
{
  "application": "authenticate",
  "policy_model": "user",
  "key": "user-delete",
  "permission_key": "authenticate.user.delete",
  "http_method": "DELETE",
  "route_pattern": "/api/v1/auth/users/<id>/",
  "operation_type": "delete",
  "display_name": "Delete User",
  "risk_level": "high",
  "current_version": "1.0.0"
}
```

---

## 4. PermissionCategory

**Purpose:** Groups endpoints into UI-friendly sections (e.g. "User Management").

**Table:** `policy_engine_permissioncategory`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|-------------|
| id | UUID | — | No | Yes | Primary key |
| application | FK → PolicyApplication | No | Yes | No | Scope to app (null = global) |
| policy_model | FK → PolicyModel | No | Yes | No | Optional model scope |
| parent | FK → self | No | Yes | No | Parent category for nesting |
| key | SlugField(100) | Yes | No | No | Globally unique key |
| display_name | CharField(255) | Yes | No | No | Label shown in UI |
| description | TextField | No | No | No | Description |
| icon_key | CharField(100) | No | No | No | Optional UI icon identifier |
| sort_order | PositiveInteger | No | No | No | Default 0 |
| is_active | Boolean | No | No | No | Default `True` |
| is_deprecated | Boolean | No | No | No | Default `False` |
| created_at | DateTimeField | — | No | Yes | Auto |
| updated_at | DateTimeField | — | No | Yes | Auto |

**Reconciliation rule:** Re-registering an already-existing category via `register_category()` reconciles `display_name`, `description`, `icon_key`, `sort_order`, and re-parenting `application`/`policy_model`/`parent` — not just `display_name` as in earlier versions of this contract. Blank/omitted `description`/`icon_key` never overwrite existing content; `application`/`policy_model`/`parent` only update when the call actually resolves one (an omitted `model_key`/`parent_key` never nulls out an existing relation). Logs `metadata_update` when anything changes.

**Example:**
```json
{
  "key": "user_management",
  "display_name": "User Management",
  "description": "Permissions related to user account operations.",
  "sort_order": 10
}
```

---

## 5. EndpointCategoryMap

**Purpose:** Maps an endpoint to one or more permission categories with UI display metadata.

**Table:** `policy_engine_endpointcategorymap`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|-------------|
| id | UUID | — | No | Yes | Primary key |
| endpoint | FK → PolicyEndpoint | Yes | No | No | The endpoint |
| category | FK → PermissionCategory | Yes | No | No | The category |
| display_label | CharField(255) | Yes | No | No | Label shown in UI for this mapping |
| help_text | TextField | No | No | No | Tooltip/help in UI |
| sort_order | PositiveInteger | No | No | No | Default 0 |
| is_visible_in_ui | Boolean | No | No | No | Default `True` |
| is_sensitive | Boolean | No | No | No | Danger flag, default `False` |
| created_at | DateTimeField | — | No | Yes | Auto |
| updated_at | DateTimeField | — | No | Yes | Auto |

**Unique constraint:** `(endpoint, category)`

**Reconciliation rule:** Re-registering an already-existing mapping via `map_endpoint_to_category()` reconciles `display_label`, `help_text`, `sort_order`, `is_visible_in_ui`, and `is_sensitive` — previously this function did nothing at all once the mapping row existed (a `get_or_create()` with no update branch). `is_sensitive` and `is_visible_in_ui` always reconcile (booleans with meaningful defaults); blank/omitted `help_text` never overwrites existing content. Logs `category_changed` when anything changes.

---

## 6. PolicyEndpointVersion

**Purpose:** Immutable version snapshot per endpoint. New record on every behavior change.

**Table:** `policy_engine_policyendpointversion`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|-------------|
| id | UUID | — | No | Yes | Primary key |
| endpoint | FK → PolicyEndpoint | Yes | No | No | The endpoint |
| version | CharField(50) | Yes | No | No | Semantic version string |
| route_pattern | CharField(500) | No | No | No | Route at this version |
| http_method | CharField(20) | No | No | No | HTTP method at this version |
| view_import_path | CharField(500) | No | No | No | View path at this version |
| operation_type | CharField(50) | Yes | No | No | Operation type at this version |
| snapshot | JSONField | No | No | No | Full endpoint metadata snapshot |
| is_deprecated | Boolean | No | No | No | Default `False` |
| created_at | DateTimeField | — | No | Yes | Auto |
| updated_at | DateTimeField | — | No | Yes | Auto |

**Unique constraint:** `(endpoint, version)`
**Integrity rule:** Never delete or overwrite historical version records. Reusing an existing `(endpoint, version)` pair with different `route_pattern`/`http_method`/`operation_type`/`view_import_path` content raises `PolicyVersionConflictError` instead of silently returning the stale existing record — bump the version instead. `create_version()`'s `snapshot` parameter, when explicitly provided, overrides the auto-computed snapshot dict.
**Currency rule:** Currency is derived, never stored — a version record is "current" iff its `version` equals its endpoint's `current_version` (§3). `PolicyEndpoint.current_version` is the single writable pointer; version records stay fully immutable. The API still serializes an `is_current` field, computed from this rule (response shape unchanged).

---

## 7. PolicyDependency

**Purpose:** Defines forward/backward permission dependencies between endpoints.

**Table:** `policy_engine_policydependency`

**`direction` choices:** `forward`, `backward`, `bidirectional`
**`dependency_type` choices:** `requires`, `implies`, `conflicts_with`, `revokes_with`, `suggests`
**`enforcement_mode` choices:** `strict`, `warning`, `manual_review`, `metadata_only`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|-------------|
| id | UUID | — | No | Yes | Primary key |
| source_endpoint | FK → PolicyEndpoint | Yes | No | No | The endpoint that has the dependency |
| target_endpoint | FK → PolicyEndpoint | Yes | No | No | The endpoint being depended on |
| direction | CharField(50), choices | Yes | No | No | forward / backward / bidirectional |
| dependency_type | CharField(50), choices | Yes | No | No | requires / implies / etc. |
| enforcement_mode | CharField(50), choices | No | No | No | Default `strict` |
| reason | TextField | No | No | No | Human explanation |
| is_active | Boolean | No | No | No | Default `True` |
| is_deprecated | Boolean | No | No | No | Default `False` |
| created_at | DateTimeField | — | No | Yes | Auto |
| updated_at | DateTimeField | — | No | Yes | Auto |

**Unique constraint:** `(source_endpoint, target_endpoint, direction, dependency_type)`

**Removal rule:** `remove_dependency()` never hard-deletes a row — it sets `is_active=False` and logs a `dependency_removed` changelog entry (§8). The row remains for audit-trail integrity (prior changelog entries reference it via `affected_dependencies`). Raises `PolicyDependencyNotFoundError` if no matching active-or-inactive row exists for the given `(source, target, direction, dependency_type)`.

**Enforcement consumer:** `enforcement_mode` is read by `permissions` app grant-time checks (`permissions/docs/DATA_CONTRACT.md` "Cross-App Dependencies") via `core.policy_engine.dependency_resolver.resolve_required_permissions()` — `strict` dependencies block role-permission attach / direct-grant creation when unsatisfied; `warning` dependencies are logged, not blocked. `manual_review`/`metadata_only` are not yet consumed by any enforcement path (metadata only, for now).

**Reconciliation rule:** Re-registering an already-existing dependency edge (same `(source, target, direction, dependency_type)`) via `add_dependency()` reconciles `enforcement_mode` (always, direct comparison) and `reason` (blank-gated — an empty reason on resync never wipes a previously-documented one), logging a `metadata_update` changelog entry with the before/after `enforcement_mode` in `detail` when it changes. This was previously a silent no-op — a real correctness/security gap, since `enforcement_mode` gates the `permissions` app's grant-time enforcement above: tightening a dependency from `warning` to `strict` in a registry declaration would appear to ship but never actually take effect until this fix (2026-07-13, see `DEBUG_HISTORY.md`).

**Example:**
```json
{
  "source_endpoint": "authenticate.user.delete",
  "target_endpoint": "authenticate.user.read",
  "direction": "forward",
  "dependency_type": "requires",
  "enforcement_mode": "strict",
  "reason": "User must be readable before delete access is meaningful."
}
```

---

## 8. PolicyChangeLog

**Purpose:** Append-only audit trail of every policy metadata change. Tracks AI vs. human authorship.

**Table:** `policy_engine_policychangelog`

**`change_type` choices:** `created`, `updated`, `bug_fix`, `security_fix`, `route_changed`, `method_changed`, `dependency_added`, `dependency_removed`, `category_changed`, `deprecated`, `removed`, `restored`, `breaking_change`, `metadata_update`
**`created_by_type` choices:** `human`, `ai`, `system`
**`object_type` choices:** `application`, `model`, `endpoint`, `category`, `dependency`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|-------------|
| id | UUID | — | No | Yes | Primary key |
| application | FK → PolicyApplication | No | Yes | No | Related app (nullable if app deleted) |
| policy_model | FK → PolicyModel | No | Yes | No | Related model |
| endpoint | FK → PolicyEndpoint | No | Yes | No | Related endpoint |
| object_type | CharField(50), choices | Yes | No | No | Type of changed object |
| object_key | CharField(255) | No | No | No | Stable key of the changed object |
| previous_version | CharField(50) | No | No | No | Version before change |
| new_version | CharField(50) | No | No | No | Version after change |
| change_type | CharField(100), choices | Yes | No | No | Type of change |
| summary | CharField(500) | Yes | No | No | One-line summary |
| detail | TextField | No | No | No | Full explanation |
| reason | TextField | No | No | No | Why the change was made |
| issue_reference | CharField(255) | No | No | No | Bug/ticket reference — reserved, currently always blank (no ticket-tracker integration exists in this project yet; see Provenance rule) |
| migration_reference | CharField(255) | No | No | No | Django migration filename this change corresponds to, when relevant (e.g. `0007_add_user_status`) — opt-in, passed by the caller |
| branch_name | CharField(255) | No | No | No | Git branch the process was on when this row was written — auto-captured, see Provenance rule |
| based_on_commit_sha | CharField(40) | No | No | No | Git commit SHA the working tree was based on when this row was written (**not** the commit that ships it — see Provenance rule) — auto-captured |
| affected_dependencies | JSONField | No | No | No | List of affected dependency keys |
| affected_categories | JSONField | No | No | No | List of affected category keys |
| backward_compatibility_notes | TextField | No | No | No | BC impact |
| forward_compatibility_notes | TextField | No | No | No | FC impact |
| created_by_type | CharField(50), choices | No | No | No | human / ai / system |
| created_by_identifier | CharField(255) | No | No | No | Name/ID of author |
| created_at | DateTimeField | — | No | Yes | Auto |
| updated_at | DateTimeField | — | No | Yes | Auto |

**Integrity rules:**
- Never UPDATE or DELETE changelog records.
- All new changes must append a new record.
- AI-generated changes must set `created_by_type = "ai"`.

**Provenance rule:** `branch_name`/`based_on_commit_sha` are captured automatically by `log_change()` — no caller passes them, every changelog row gets them for free via a best-effort `git rev-parse` subprocess call, memoized once per process (a single `sync_policy_registry` run can write hundreds of rows without spawning hundreds of git processes). If git isn't available (e.g. a deployed build with no `.git` directory) or the calls fail for any reason, both fields are silently left blank — provenance capture must never block a registry write. `based_on_commit_sha` is deliberately **not** "the commit that shipped this change": that commit doesn't exist yet when the row is written (per `CLAUDE.md` §34, the commit happens after code, tests, and docs are all done), and `PolicyChangeLog` is append-only — a row can never be retroactively stamped with a SHA discovered after the fact. The durable link between "what changed" and "which commit shipped it" is `/iterations/<timestamp>_<apps>.md` (§19.4) plus the commit message itself, not this table. `issue_reference` remains unpopulated by design — no ticket-tracker/requirement-ID convention exists in this project, and inventing one here would violate §32 ("do not invent business rules not provided"); the column is reserved for a future integration, not a bug.

---

## Cross-App Dependencies

This app has no dependencies on other application apps. Future apps (organization, RBAC, department) will import from this app's `selectors.py` only.

---

## Soft Delete

Not used. Deprecated state is tracked via `is_deprecated = True` on each model. Records are never hard-deleted without explicit approval.
