<!-- Copy this file to <app>/docs/INTEGRATION.md and fill in. Delete this comment block.

AUDIENCE: a consumer in ANOTHER project (a frontend Claude, an external client author) who
cannot see this codebase's internals and will integrate purely from this file. Write for a
reader with zero context. This file describes CURRENT state — it is a living contract, updated
in the same commit as any endpoint change (unlike /iterations/ logs, which are frozen
per-session deltas).

HARD RULES (inherited from CLAUDE.md §19.4, adapted):
1. Use the section headings below verbatim, in order. Copy paths, fields, enums, and error
   codes EXACTLY from the code. Drop everything a client can't see over HTTP (DB mechanics,
   indexes, transactions, viewsets, migrations, tests, file/function names, rationale).
2. EXTRACT conventions from the code and docs — never assume them. If something isn't pinned
   down, write "not documented" and add it to §9 Gaps. Never invent anything.
3. Define each resource's response shape ONCE in §4 Models. Endpoints reference it by name.
4. No prose outside the schema. Output the spec only.
5. Inline single-backtick formatting for field names, paths, and codes. Multi-item fields
   (`Methods`, `Send`, `Notes`, `Errors`) are bullet lists. Fenced JSON is permitted in exactly
   two places and nowhere else: §3 Conventions (a worked envelope with real values) and §4 Models
   (one realistic payload per resource, under a `### Worked examples` sub-heading). §7 Endpoints
   stays prose — it references shapes by name, never re-lists them.
   Both allowances came from comprehension-testing a reader with no source access: given only the
   inline shorthand, the reader inferred response shapes rather than reading them, and flagged
   "only one of N shapes has a real example" as the top remaining weakness.
6. `Requires` (§2), `Requires state`, and `Side effects` (§7) are MANDATORY — write the literal
   `none` when genuinely empty. Never omit them: an omitted field is indistinguishable from
   "the author decided it was obvious", and what an author finds obvious is exactly what an
   external reader lacks.
-->

# Integration — <App Display Name>

**Owner app:** `<app_name>`
**Version:** <semver>
**Status:** Active | Draft | Deprecated
**Created:** YYYY-MM-DD

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | YYYY-MM-DD | AI (Claude) | Initial integration contract |

---

## 1. Module

- **Name:** <app display name — one line on what this module is for>
- **Base path:** `/api/v1/<prefix>/`
- **Auth:** <one line, applies to all endpoints; note per-endpoint exceptions in §7>
- **Status:** <active / beta / deprecated>

## 2. Requires

<App-level dependencies: what must exist and function for THIS app to work. One row per
dependency. Kind is one of: `service call` | `FK` | `permission authority` | `signal` |
`framework`. The literal `none` if the app is fully standalone.>

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `<app_or_module>` | <kind> | <one line> | <observable failure a consumer would see> |

## 3. Conventions

- **Response:** <the wrapper actually returned — e.g. the standard envelope `{ success, message, data, meta }` per project-level `INTEGRATION.md`, or the deviation>
- **Error:** <the actual error body shape>
- **Auth failures:** <codes/bodies actually returned for 401 and 403>
- **Pagination:** <params + meta shape, or "not paginated" / "not documented">
- **IDs:** <e.g. UUID strings>
- **Times:** <e.g. ISO 8601 UTC>
- **List/search/filter/order params:** <only what actually exists>

## 4. Models

<One entry per resource: bold name, then the read shape as a single inline-code line.
Mark `?` nullable, `[enum]` choice fields, `json` for object fields. Note retrieve-only extra
fields and cross-field rules as a bullet underneath, only if applicable.>

**<Resource>** — `{ id, field, other?:type, status:[enum], … }`

## 5. Enums

<One bullet per enum: `Resource.field: a | b | c`. If observed values may be incomplete, mark
"(observed — confirm full set)".>

- `<Resource>.<field>`: `a` | `b` | `c`

## 6. Dependency order

<One bullet each: `X` needs `Y` (a Y must exist before creating an X). Mark external deps
`(other app)`. End with the first thing a consumer creates.>

- `<X>` needs `<Y>`

**Start here:** <first resource a client creates, or "read-only module — start with any list endpoint">

## 7. Endpoints

<One block per resource. Break an endpoint into its own block ONLY when non-standard (custom
action, different response, side effect, auto-set fields, nested retrieve).>

### <Resource> — `<base path>`

**Use it when:** <the real consumer use case(s), one line>
**Methods:**
- `<VERB> <path>` — <one-line purpose> (permission: `<app.model.action>`, risk: <level>)
**Send (create/update):** <bullet per action with the writable fields, or `none`>
**Returns:** <Model> | list[<Model>] <note retrieve-only extras>
**Requires state:** <preconditions that must hold before calling — resources that must exist,
statuses that must be set, grants that must be in place — or the literal `none`>
**Side effects:** <what changes beyond the returned resource, including in other apps — records
created/updated elsewhere, events emitted, counters, emails — or the literal `none`>
**Notes:**
- <auto-set fields, search scope, immutability, special behavior — omit the subsection entirely if none>
**Errors:**
- `<CODE>` (<4xx>) — <trigger condition; omit global auth errors; `none` if genuinely none>

## 8. Flows

<2–5 cross-resource journeys a real consumer performs, each a bold name + ordered list with ids
threaded through and failure branches as indented sub-bullets. At least one flow should cross an
app boundary if §2 lists any dependency.>

**<Flow name>**
1. <step — `VERB /path` → capture `id`>
2. <next step using that `id`>
   - <failure branch: what error, what the consumer should do>

## 9. Gaps

<Anything a consumer needs that this file cannot pin down — undocumented shapes, unconfirmed
enum sets, validation bodies not shown, external references. Specific only; never fabricate.
The literal `none` if complete.>

- <gap>
