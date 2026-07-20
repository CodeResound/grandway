<!-- Copy this file to <app>/docs/API.md and fill in. Delete this comment line. -->

# API Documentation — <App Display Name>

**App:** `<app_name>`
**Version:** <semver>
**Base prefix:** `/api/v1/<prefix>/`
**Auth:** <one-line summary — cross-ref CLAUDE.md §9 or this app's SECURITY.md if relevant>
**Throttle:** <default DRF throttle classes, or note custom scopes>
**Access level:** <Public | Staff-only | Mixed — summarize>

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | YYYY-MM-DD | AI (Claude) | Initial API documentation |

---

## Generic envelopes (referenced throughout)

**Success:**
```json
{ "success": true, "message": "...", "data": { ... }, "meta": {} }
```

**Error:**
```json
{ "success": false, "error": { "code": "...", "message": "...", "details": {} }, "meta": {} }
```

**AI debugging notes (app-wide):** anything true of every endpoint worth flagging once, here. Add a per-endpoint note below only when something is genuinely endpoint-specific.

---

## 1. <Resource Name>

### 1.1 <Action> — `<METHOD> <path>`

**Policy key(s):** `<app>.<resource>.<action>` (risk: <low|medium|high|critical>)
**Request:** <only if non-trivial — inline a minimal example, not every field>
**Response:** reference `DATA_CONTRACT.md §N` for the read shape; inline only response shapes that are NOT just "the model"
**Validation rules:** <only if not obvious from DATA_CONTRACT.md>
**Error codes:** `CODE` (HTTP status — one-line trigger condition)
**Business rules:** <only non-obvious ones — algorithm steps, side effects, ordering>
**Query access pattern:** <only for endpoints backed by a non-trivial selector>
**AI debugging notes:** <only if endpoint-specific; omit if the app-wide note above already covers it>

### 1.2 <Next action>
...

---

## 2. <Next Resource>
...

---

## Error code reference

All codes are defined in `<app>/constants.py`. See this app's `SECURITY.md` (if present) for any account-enumeration / generic-failure rationale governing which codes may be specific vs. generic.

| Code | HTTP | Notes |
|---|---|---|
| `<APP_RESOURCE_REASON>` | <status> | <one-line trigger condition> |
