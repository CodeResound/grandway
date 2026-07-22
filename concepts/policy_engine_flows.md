# FLOWS — Core Policy Engine

**Owner app:** `core.policy_engine`
**Updated:** 2026-07-22
**Purpose:** The user-flow binding layer for the Core Policy Engine — connects the read-only registry
endpoints in `backend/core/policy_engine/docs/INTEGRATION.md` to the screens of a permission-administration
UI. This is the **worked reference instance**: copy its shape (not its content) when you write a flow
file for a real business app.

> This file binds screens to endpoints; it never re-documents them. Response shapes, field lists, and
> enum value sets live in `backend/core/policy_engine/docs/INTEGRATION.md` — this file references them by
> name. The policy engine is core infrastructure and has no `concepts/policy_engine.txt`; the screen
> names below are therefore defined inline (see Open questions).
>
> **Auth applies to every step below:** JWT bearer token AND `is_staff` on the user. A non-staff caller
> gets `PERMISSION_DENIED` (403); a missing/invalid token gets `AUTHENTICATION_REQUIRED` (401). These
> global auth failures are not repeated per step — treat them as a gate on every screen.

---

## Flow: Render a role editor from the full permission surface

- **Actor:** Admin (permission administration is a staff-only surface)
- **Goal:** Show the complete assignable permission surface so an operator can compose a role.
- **Entry point:** Permission Tree screen

**Steps:**

1. **Permission Tree screen** — operator opens the role editor →
   `GET /api/v1/policy/permissions/tree/` (`policy_engine.permission.tree`)
   - **Requires state:** caller is `is_staff`. Endpoints only appear if they have a UI-visible category mapping — a registered endpoint with no category is silently absent from the tree.
   - **Side effects:** none (read-only).
   - *Failure — empty `data`:* registry never synced — render an empty-state ("no permissions registered") rather than a blank tree.
2. **Permission Tree screen** — operator selects a permission node → the UI reads that node's `dependencies` array (already embedded in the tree response) and auto-selects those keys.
   - **Requires state:** the tree from step 1 is loaded.
   - **Side effects:** none — selection is client-side until submitted to the permission-granting API, which belongs to a different app and is out of this module's scope.
   - *Failure — a `strict` dependency is unavailable:* block the save and surface the missing key; the server-side permissions authority rejects it otherwise.
3. **Applications sidebar** — operator filters the tree to one app →
   `GET /api/v1/policy/apps/` (`policy_engine.application.list`) to populate the app list, then re-fetch the tree with `?app=<app_key>`.
   - **Requires state:** `is_staff`. No resource needs to exist — an unsynced registry returns an empty list.
   - **Side effects:** none.
4. **Application detail drawer** — operator opens one app to see its models and endpoints →
   `GET /api/v1/policy/apps/<app_key>/` (`policy_engine.application.read`)
   - **Requires state:** `<app_key>` names a registered application.
   - **Side effects:** none.
   - *Failure — `NOT_FOUND` (404):* the app_key is unknown — show a "not registered" state, not a crash.

## Flow: Audit one permission's full history

- **Actor:** Admin
- **Goal:** Inspect a single permission in depth — its route/method/risk, what it depends on, how its contract changed, and who changed it.
- **Entry point:** Endpoint Detail screen (reached by clicking a node in the Permission Tree)

**Steps:**

1. **Endpoint Detail screen** — operator opens one permission →
   `GET /api/v1/policy/endpoints/<permission_key>/` (`policy_engine.endpoint.read`)
   - **Requires state:** `<permission_key>` names a registered endpoint. `permission_key` contains dots and is one URL segment — send `authenticate.user.delete` unescaped.
   - **Side effects:** none.
   - *Failure — `NOT_FOUND` (404):* key was never registered (endpoints are retired via deprecation, never deleted) — show "unknown permission".
   - *Retirement banner:* if `is_deprecated` is true, read `sunset_at` and `replaced_by_permission_key` to render a "deprecated — migrate to X by date" banner.
2. **Dependencies panel** — operator expands dependencies →
   `GET /api/v1/policy/endpoints/<permission_key>/dependencies/` (`policy_engine.endpoint.read_dependencies`)
   - **Requires state:** same registered key.
   - **Side effects:** none.
   - *Note:* response is an object `{ forward, backward }`, not an array — `forward` = what this requires, `backward` = what breaks if removed.
3. **Version history tab** — operator views contract changes over time →
   `GET /api/v1/policy/endpoints/<permission_key>/versions/` (`policy_engine.endpoint.read_versions`)
   - **Requires state:** same registered key.
   - **Side effects:** none.
   - *Note:* ordered most-recent-first; exactly one record has `is_current: true`; never paginated.
4. **Change log tab** — operator views who changed what and why →
   `GET /api/v1/policy/endpoints/<permission_key>/changelog/?page=1` (`policy_engine.endpoint.read_changelog`)
   - **Requires state:** same registered key.
   - **Side effects:** none.
   - *Note:* the only paginated sub-resource here — render pagination controls from `meta`; use `created_by_type` (`human`/`ai`/`system`) to badge each entry.

## Flow: Warn before revoking a permission

- **Actor:** Admin
- **Goal:** Prevent an operator from revoking a permission that other permissions still depend on.
- **Entry point:** Endpoint Detail screen → Revoke action

**Steps:**

1. **Endpoint Detail screen** — operator clicks Revoke →
   `GET /api/v1/policy/endpoints/<permission_key>/dependencies/` (`policy_engine.endpoint.read_dependencies`) and capture `backward`.
   - **Requires state:** registered key.
   - **Side effects:** none — this module is read-only; the actual revoke happens in the permissions app (cross-module, out of scope here).
   - *Failure — non-empty `backward`:* list those keys as blockers in a confirmation dialog before allowing the revoke to proceed to the permissions API.

---

## Endpoint coverage

All 7 registered endpoints map to a flow. Verified against `backend/core/policy_engine/docs/INTEGRATION.md` §7.

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `policy_engine.application.list` | `GET /api/v1/policy/apps/` | Render a role editor | Populates the applications sidebar |
| `policy_engine.application.read` | `GET /api/v1/policy/apps/<app_key>/` | Render a role editor | App detail drawer with nested models + endpoints |
| `policy_engine.permission.tree` | `GET /api/v1/policy/permissions/tree/` | Render a role editor | The primary surface; one call returns the whole tree |
| `policy_engine.endpoint.read` | `GET /api/v1/policy/endpoints/<permission_key>/` | Audit one permission | Also drives the retirement banner |
| `policy_engine.endpoint.read_dependencies` | `GET /api/v1/policy/endpoints/<permission_key>/dependencies/` | Audit one permission; Warn before revoking | `forward` for audit, `backward` for revoke-warning |
| `policy_engine.endpoint.read_versions` | `GET /api/v1/policy/endpoints/<permission_key>/versions/` | Audit one permission | Version history tab |
| `policy_engine.endpoint.read_changelog` | `GET /api/v1/policy/endpoints/<permission_key>/changelog/` | Audit one permission | Change log tab (paginated) |

## Cross-app dependencies

- **This app references (outbound):** none — every step above calls a `policy_engine` endpoint. The permission-*granting* and permission-*revoking* actions referenced in the flows belong to a future permissions app and are deliberately out of this read-only module's scope.
- **Referenced by other apps (inbound):** none yet — no business app flow files exist. When a role editor in another app consumes `policy_engine.permission.tree`, that app's flow file marks the step `(cross-app: policy_engine)` and this line records the inbound reference.

## Open questions

- The policy engine has no `concepts/policy_engine.txt` (it is core infrastructure, not a business app), so the screen names here are defined inline rather than sourced from a concept file. A real business-app flow file must name screens from its concept file's `UI screens & wireframe notes` section.
- The permission-granting / role-save API (where the role editor submits its selection) lives outside this module; its endpoints and contract are not yet defined.
