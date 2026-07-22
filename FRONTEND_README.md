# FRONTEND_README — Building UI Against This Backend

**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-22
**Audience:** A frontend engineer — or a Claude on another machine — building UI (wireframes, then
implementation) against this backend, with **no access to the backend source code**.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Fable 5) | Initial frontend consumer guide |

---

This file is **static**. It teaches a *method* — it deliberately contains no endpoint names, no field
lists, and no per-app content. Everything specific lives in the living, CI-checked docs mapped below, so
this guide never drifts as the API grows. Read it once; then work from the app docs.

## 1. What this backend is, and your obligation to it

A Django + DRF JSON API. This repository is **backend-only** — it contains no frontend code and never
will. Its entire contract to you is a documentation set. Your job is to turn that set into UI that
covers **all** of the intended user flows and functionality — the common failure is missing some, and
Section 4 is the mechanism that prevents it.

You cannot read the backend source. Do not guess at behavior the docs don't state — Section 5 covers
what to do with unknowns.

> **Read this before you plan any live integration.** Depending on how far the backend has been built,
> the API may not be callable end-to-end yet — there may be **no token-issuance endpoint** (so you
> cannot authenticate) and **no published host** (so there is no server to point at). Both facts, and
> their current status, are stated in `backend/core/docs/INTEGRATION.md` §4 and §10 — check there
> first. This does not block **wireframing**, which is a documentation exercise and the primary
> deliverable this guide is for; it does block running a real client. Know which one you are being
> asked for, and if the API is not yet callable, say so up front rather than after building.

## 2. Reading order

Read in this order. Do not skip ahead — later docs assume the conventions in earlier ones.

1. **This file** — the method.
2. **`backend/core/docs/INTEGRATION.md`** — global conventions that apply to *every* endpoint:
   the success/error response envelope, error codes, pagination shape, authentication, rate limits,
   the app inventory, and the cross-app dependency graph. This is the single source for "how every
   response is shaped." Read it before any app.
3. **Per app you consume, the matched triple** — all three, in this order:
   1. **`concepts/<app_name>.txt`** — the product intent: why the app exists, its actors, its core
      entities, its intended user flows, and its UI screen notes. This is the *what and why*.
   2. **`concepts/<app_name>_flows.md`** — the **flow binding layer**: each user flow written as an
      ordered sequence of `screen → action → endpoint → preconditions → side effects`, with failure
      branches and an endpoint-coverage table. This is the bridge that connects screens to the API,
      authored by the backend team that built the endpoints. This is the *how the screens use the API*.
   3. **`backend/<app_name>/docs/INTEGRATION.md`** — the endpoint contract: models (§4), enum value
      sets (§5), the endpoint list with preconditions and side effects (§7), API-level flows (§8), and
      known gaps (§9). This is the *how to call it*.
4. **`backend/core/policy_engine/docs/registry_export.json`** (and `openapi.json`) — the machine-readable,
   CI-enforced-complete inventory of every endpoint. Use it in Section 4 to confirm you have not missed
   an endpoint. Note its documented limitation: response *body* schemas there are generic — field-level
   shapes come from each app's `INTEGRATION.md` §4, never from the OpenAPI bodies.

**A business app is frontend-ready only when all three of its matched-triple files exist.** If the
concept file or the flow file or the `INTEGRATION.md` is missing, **stop and report the app as not
ready** — do not wireframe from a partial set. Building from one half is exactly what produces
incomplete UI.

**Exception — core-infrastructure apps.** A core-infrastructure app (a staff/admin registry or tooling
surface, not a product domain) may legitimately have **no concept file** — it has no product-intent
story to tell, and its flow file defines screen names inline instead. `core.policy_engine` is the
worked example: its `concepts/policy_engine_flows.md` exists and its `INTEGRATION.md` exists, but there
is no `concepts/policy_engine.txt`, and that is correct, not a defect. For such an app the readiness
test is **the flow file plus the `INTEGRATION.md`**; the flow file's own header will state that screens
are defined inline. Do not apply this exception to a business domain listed in
`concepts/project_overview.txt` — those must have all three.

**Never read these** (they will mislead or waste you):

- **Backend source** — you have no access, and the docs are the contract.
- **`backend/<app>/docs/API.md` and `DATA_CONTRACT.md`** — maintainer-facing, they describe database
  tables and internal rationale, not the consumer surface.
- **`/iterations/*.md`** — write-once session deltas ("what changed that day"), not current state.
  Reconstructing the present from N deltas is exactly what `INTEGRATION.md` exists to spare you.

## 3. The matched triple, and how the flow file drives wireframes

The three files answer three different questions, and you need all three:

| File | Answers | You use it to |
|------|---------|---------------|
| `concepts/<app>.txt` | What & why — actors, entities, screens | Enumerate the screens and understand each actor's goals |
| `concepts/<app>_flows.md` | Which screen calls which endpoint, in what order | Build each flow's screen sequence — the spine of the wireframe |
| `backend/<app>/docs/INTEGRATION.md` | How to call each endpoint, exact shapes | Fill in payloads, states, enum values, error handling |

Work each flow in `concepts/<app>_flows.md` top to bottom:

- Each **step** is already bound: a named screen, the action, the endpoint (`METHOD /path` +
  `permission_key`), its **`Requires state`** (preconditions), and its **`Side effects`** (what changes
  after). Wireframe the screen sequence in that order.
- **`Requires state`** → model it as UI: empty states when a resource doesn't exist yet, disabled
  actions until a precondition holds, guided setup steps. **`Side effects`** → what your UI must refresh
  or re-fetch after the action succeeds (including changes in *other* apps).
- Each step's **failure branches** (with their error codes) → the wireframe's error paths: inline field
  errors, blocking dialogs, empty states, redirects. Every error path in the flow file must appear
  somewhere in your wireframes.
- Every value in the app's `INTEGRATION.md` **§5 Enums** is a distinct visual state (a badge, a status
  color, a filter option). Enumerate them; don't collapse them.
- Steps marked **`(cross-app: <other_app>)`** call an endpoint owned by a different app — read that
  app's `INTEGRATION.md` too, and treat its dependency as a precondition for this flow.
- Respect **actor scoping** from the concept file — what each actor type (e.g. Admin vs a scoped
  operational user) is allowed to see and do changes which screens and actions you render.

## 4. The mandatory deliverable: a coverage matrix

Before you call a set of wireframes complete, produce a traceability table and check it. This is the
single most important step — it is what turns "I wireframed some screens" into "I covered the
functionality."

For each app you consumed, build three mappings:

1. **Every endpoint** in the app's `INTEGRATION.md` §7 (cross-checked against the registry export) →
   the screen(s)/flow(s) that call it, **or** an explicit "unused by design because …" row. The app's
   own `concepts/<app>_flows.md` → `Endpoint coverage` table is your answer key — reconcile against it.
2. **Every screen** named in `concepts/<app>.txt` → its wireframe.
3. **Every flow** in `concepts/<app>_flows.md` → its wireframe screen sequence.

**Any row you cannot map is a named gap you report back — never silently drop it.** An endpoint with no
screen, a screen with no wireframe, or a flow you couldn't realize is a question for the backend team,
not something to omit quietly. Deliver the matrix alongside the wireframes.

## 5. Completeness discipline

- **Never invent** endpoints, fields, enum values, or business rules. If the docs don't state it, you
  don't know it.
- Collect every unknown into an **open-questions list** for the backend team. Seed it from each app's
  `INTEGRATION.md` **§9 Gaps**, the project-level `core/docs/INTEGRATION.md` **§10 Gaps**, and the
  `Open questions` section of each flow file — these are the maintainers telling you what is not pinned
  down. Echo them into your own list rather than resolving them by guessing.

## 6. Staleness and trust

- Every doc carries a **`Change History`** table (or an `Updated` date on flow files). Check it — if a
  flow file's date predates its app's `INTEGRATION.md` last change, the flow file may be stale; flag it.
- The **registry export is authoritative for the endpoint inventory** — CI rejects any routed endpoint
  missing from it (`core/docs/INTEGRATION.md` §9). If an `INTEGRATION.md` describes an endpoint absent
  from the registry, or vice versa, that is a contradiction to report.
- If a doc contradicts the API's observed behavior, **the code is authoritative and the doc is a bug** —
  report it; do not build a workaround around a doc you suspect is wrong.

## 7. The worked example

`concepts/policy_engine_flows.md` is a complete, real flow file for the Core Policy Engine (the one app
currently wired up). Read it alongside `backend/core/policy_engine/docs/INTEGRATION.md` to see the method
end to end: three flows, screen-to-endpoint bindings, failure branches, and a full endpoint-coverage
table for all seven endpoints. Use it as your model for what "done" looks like.
