# Registry Maintainer Guide — Core Policy Engine

**Owner app:** `core.policy_engine`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-14

> **Audience: backend maintainers of *this* repository.** How to register, version, and retire
> endpoints in the policy registry.
>
> **If you are integrating a client against this API, this is the wrong file.** Start at
> `backend/core/docs/INTEGRATION.md`, then read the per-app `docs/INTEGRATION.md` — those are the
> consumer contract (`CLAUDE.md` §19.3). This file documents internal registry mechanics that a
> consumer neither needs nor can act on.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-14 | AI (Claude Opus 4.8) | Initial integration guide: machine-readable artifacts, add/remove-endpoint checklists, lifecycle/method-level/failure examples, frontend & external-client integration, CI-required evidence format |
| 1.1.0 | 2026-07-21 | AI (Claude Opus 4.8) | Retitled and scoped to backend maintainers to disambiguate from the new consumer-facing `INTEGRATION.md` (`CLAUDE.md` §19.3). Corrects the §6 401/403 error codes to the values `core/exceptions.py` actually returns (`AUTHENTICATION_REQUIRED`/`PERMISSION_DENIED`, not `AUTH_*`). Adds the `INTEGRATION.md` update step to the add/remove-endpoint checklists |

---

## 1. Machine-readable artifacts

Three generated/published artifacts make the registry consumable by tools and external clients. All are produced from the **declarative** registry (`registry.py` `POLICY_ENDPOINTS` across all apps), so they are deterministic and diff-stable, and are kept fresh by CI (§8).

| Artifact | Path | What it is |
|----------|------|------------|
| Registry export | `docs/registry_export.json` | Canonical JSON of every registered endpoint: `permission_key`, app/model, route, method, `operation_type`, `risk_level`, `version`, category, `dependencies[]`. Sorted by `permission_key`. |
| OpenAPI 3.1 | `docs/openapi.json` | Paths/methods with `operationId` = `permission_key`, `x-permission-key`/`x-risk-level` extensions, bearer-JWT security, and the standard success/error envelope components (`CLAUDE.md` §7). |
| Registry schema contract | `docs/registry_schema.json` | JSON Schema (draft 2020-12) for one `POLICY_ENDPOINTS` entry (§7). |

Regenerate locally:

```bash
python manage.py export_policy_registry --format registry --output backend/core/policy_engine/docs/registry_export.json
python manage.py export_policy_registry --format openapi  --output backend/core/policy_engine/docs/openapi.json
```

**Limitation (registry-derived OpenAPI):** the OpenAPI doc is authoritative for *paths, methods, permission keys, and risk*, but request/response **body** schemas are generic — the registry does not model field shapes. Read field-level contracts from each app's `docs/DATA_CONTRACT.md` (each OpenAPI operation's `description` cross-references it). This is a deliberate trade-off to avoid a heavyweight schema-generation dependency (`CLAUDE.md` §37).

## 2. How to add an endpoint (checklist)

The authoritative rules are `CLAUDE.md` §35. Operator distillation:

1. Register the endpoint in the owning app's `registry.py` `POLICY_ENDPOINTS` (see the entry shape in §7 / `registry_schema.json`): `app_key`, `endpoint_key`, `permission_key` (`app.model.action`), `operation_type`, `display_name`, `route_pattern`, `http_method`, `risk_level`, `category_key`, and `dependencies[]` (high/critical-risk endpoints must declare a dependency or set `is_dependency_root=True`).
2. Run `python manage.py sync_policy_registry` immediately after editing `registry.py` (`CLAUDE.md` §35 item 14).
3. Regenerate the artifacts (§1) and stage them.
4. Run `python manage.py validate_policy_engine --strict` → must pass (0 findings).
5. Update the owning app's `docs/API.md` + `docs/DATA_CONTRACT.md` (`CLAUDE.md` §19.3).
6. Update the owning app's `docs/INTEGRATION.md` — the consumer contract. Add the endpoint to §7 with its `Use it when`, `Requires state`, and `Side effects`, and to §4/§5 if it introduces a new model or enum. Run `python manage.py validate_integration_docs --strict` → must pass. A registered endpoint with no contract entry fails CI (`scripts/ci.sh docs`).

## 3. How to remove an endpoint (checklist)

Endpoints are **never hard-deleted** — staged retirement only (`CLAUDE.md` §35 item 15, `DATA_CONTRACT.md` §3 Lifecycle rule):

1. `deprecate_endpoint(permission_key, reason, sunset_at=..., replaced_by_permission_key=..., removal_ticket=...)` — starts the sunset window (`is_deprecated=True`, stays `is_active=True`). `validate_policy_engine` rule 5 then WARNs until it is disabled.
2. When the sunset window ends: `disable_endpoint(permission_key, reason)` — sets `is_active=False` (requires the endpoint already be deprecated, else `PolicyLifecycleIncompleteError`).
3. To reverse either stage: `restore_endpoint(permission_key, reason)` — clears all lifecycle metadata back to fully active.
4. Soft-remove any dependency edges via `remove_dependency(...)` (`is_active=False`, never hard delete).
5. Regenerate artifacts (§1), run `validate_policy_engine --strict`, update docs.
6. Update `docs/INTEGRATION.md`: mark the endpoint deprecated and name its successor and sunset date so consumers can migrate. **Do not delete the entry** — a consumer needs to see that a permission they use is going away, and `validate_integration_docs` flags a documented key that no longer exists in the registry, so the removal happens only after the endpoint is actually gone.

## 4. Endpoint lifecycle examples

```python
from django.utils import timezone
from datetime import timedelta
from core.policy_engine.services import deprecate_endpoint, disable_endpoint, restore_endpoint

# Announce retirement with a 90-day sunset and a successor.
deprecate_endpoint(
    "authenticate.user.update",
    reason="Superseded by the unified profile-update endpoint.",
    sunset_at=timezone.now() + timedelta(days=90),
    replaced_by_permission_key="authenticate.user.update_self",
    removal_ticket="OPS-1421",
)
# -> is_deprecated=True, is_active=True, deprecated_at set, sunset_at set,
#    replaced_by_permission_key/removal_ticket/removal_reason populated.

disable_endpoint("authenticate.user.update", reason="Sunset window elapsed.")
# -> is_active=False, disabled_at set.

restore_endpoint("authenticate.user.update", reason="Rollback: clients still depend on it.")
# -> is_active=True, is_deprecated=False, all six lifecycle fields cleared.
```

The append-only `PolicyChangeLog` records every transition as an event; the denormalized fields above hold only the *current* state (see `DATA_CONTRACT.md` §3).

## 5. Method-level permission examples

A single URL path routinely backs multiple permission keys — one per HTTP verb — each with its own `risk_level` and dependencies. Enforcement and audit are therefore **method-level**, not path-level:

| Path | Method | permission_key |
|------|--------|----------------|
| `/api/v1/auth/users/<id>/` | `GET` | `authenticate.user.read` |
| `/api/v1/auth/users/<id>/` | `PATCH` | `authenticate.user.update` |
| `/api/v1/auth/users/` | `GET` | `authenticate.user.list` |
| `/api/v1/auth/users/` | `POST` | `authenticate.user.create` |
| `/api/v1/auth/me/` | `GET` | `authenticate.user.read_self` |
| `/api/v1/auth/me/` | `PATCH` | `authenticate.user.update_self` |

`validate_policy_engine` rules 12 and 14 are method-aware for exactly this reason: "the path exists in the registry" is a weaker claim than "every verb this path answers has its own registered permission."

## 6. Failure examples

All errors use the standard envelope (`CLAUDE.md` §7); field-level validation errors go in `error.details`.

**401 — unauthenticated:**
```json
{ "success": false, "error": { "code": "AUTHENTICATION_REQUIRED", "message": "Authentication required." }, "meta": {} }
```

**403 — authenticated but not permitted (current interim `is_staff` default, `CLAUDE.md` §9):**
```json
{ "success": false, "error": { "code": "PERMISSION_DENIED", "message": "Staff access required." }, "meta": {} }
```

**400 — validation failure:**
```json
{ "success": false, "error": { "code": "POLICY_ENGINE_VALIDATION_FAILED", "message": "Invalid input.",
  "details": { "permission_key": ["Must be lowercase 'app.model.action' with snake_case segments."] } }, "meta": {} }
```

**409-style — grant-time dependency violation** (`permissions` app, attaching a permission whose strict `requires` dependency is unmet):
```json
{ "success": false, "error": { "code": "PERMISSIONS_MISSING_REQUIRED_PERMISSION",
  "message": "Cannot grant 'authenticate.user.delete' without its required 'authenticate.user.read'." }, "meta": {} }
```

## 7. Registry schema contract

`docs/registry_schema.json` is the published JSON Schema for one `POLICY_ENDPOINTS` entry. The authoritative runtime validator is `core.policy_engine.validators.validate_registry_config()`; a test (`tests/test_exporters.py::RegistrySchemaContractTest`) asserts the schema's `required` keys and enums stay in lockstep with the Python constants, so the contract can never silently diverge from what `sync_policy_registry` enforces. External tooling can validate proposed registry entries against this schema before a PR.

## 8. CI-required evidence format

A change touching endpoints/registry must show this evidence (CI enforces the mechanical parts — see `scripts/ci.sh` and `.github/workflows/ci.yml`):

1. `ruff check` / `ruff format --check` — clean.
2. `export_policy_registry --format registry --check` and `--format openapi --check` — pass (the committed artifacts match the registry). CI uploads `registry_export.json` / `openapi.json` / `registry_schema.json` as build artifacts.
3. `python manage.py validate_policy_engine --strict` — 0 findings (all 15 rules).
4. `pytest` — green.

Per `CLAUDE.md` §33, a completion report must paste the actual command output for items 2–4, not assert them.
