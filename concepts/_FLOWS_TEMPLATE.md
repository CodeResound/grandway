# FLOWS — <App Name>

**Owner app:** `<app_name>`
**Updated:** <YYYY-MM-DD>
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/<app_name>.txt` to the callable endpoints in `backend/<app_name>/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **What this file is — and is not.** This is a *binding* layer, not a third copy of anything.
> Screens are named (never re-described) from `concepts/<app_name>.txt` → `UI screens & wireframe notes`.
> Endpoints are referenced by `permission_key` + `METHOD /path` (never re-documented) from
> `INTEGRATION.md`. If you find yourself restating a field list or a response shape here, stop — that
> belongs in `INTEGRATION.md`. This file only answers: *which screen calls which endpoint, in what
> order, guarded by what, and what changes after.*
>
> Copy this file to `concepts/<app_name>_flows.md`, fill every section, and delete this intro block
> and every `<...>` placeholder. A frontend Claude on another machine reads it via `FRONTEND_README.md`.

---

## Flow: <flow name — imperative, e.g. "Convert a qualified lead into an applicant">

- **Actor:** <actor type from concepts/<app_name>.txt → Actors, e.g. Lead Manager / Admin>
- **Goal:** <what the actor is trying to accomplish in one line>
- **Entry point:** <screen name, exactly as written in concepts/<app_name>.txt → UI screens>

**Steps** — each step binds a screen action to the endpoint that realizes it:

1. **<Screen name>** — <action the user takes> →
   `<METHOD> /api/v1/<path>` (`<permission_key>`)
   - **Requires state:** <what must already exist / be true before this call — from INTEGRATION.md §7 `Requires state`>
   - **Side effects:** <what changes or must be refreshed after — from INTEGRATION.md §7 `Side effects`; write `none` if none>
   - *Failure — `<ERROR_CODE>`:* <the UI treatment for this failure — inline field error, blocking dialog, empty state, redirect>
2. **<Screen name>** — <action> →
   `<METHOD> /api/v1/<path>` (`<permission_key>`) **(cross-app: `<other_app>`)**
   - **Requires state:** <...>
   - **Side effects:** <...>
   - *Failure — `<ERROR_CODE>`:* <UI treatment>

> **Cross-app marker.** Any step whose endpoint belongs to a different app is tagged
> `(cross-app: <other_app>)`. This is the flow-level mirror of that app's `INTEGRATION.md` §2 `Requires`.
> Every flow still has exactly ONE owner app (this file's app — the one whose primary resource the flow
> advances). A flow is never split across two files; it reaches into other apps' endpoints instead.

## Flow: <second flow name>

<...repeat the structure above...>

---

## Endpoint coverage

Every endpoint this app exposes (per `backend/<app_name>/docs/INTEGRATION.md` §7) maps to the flow(s)
that use it, or is explicitly marked unused. The frontend verifies its wireframes against this table;
an endpoint with no flow and no reason is a gap, not an omission.

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `<app.model.action>` | `<METHOD> /api/v1/<path>` | <flow name> | |
| `<app.model.action>` | `<METHOD> /api/v1/<path>` | — | `unused by flow — <reason, e.g. admin-only maintenance, not a UI journey>` |

## Cross-app dependencies

- **This app references (outbound):** <other apps' endpoints used in the flows above, by `permission_key` — or `none`>
- **Referenced by other apps (inbound):** <other apps' flow files that reference this app's endpoints, by file — or `none` / `none yet`>

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.

## Open questions

- <anything unresolved that blocks or shapes a flow — deferred decisions, unconfirmed enum sets, missing endpoints>
