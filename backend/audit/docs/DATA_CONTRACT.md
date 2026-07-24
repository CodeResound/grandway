# Data Contract — Audit

**Owner app:** `audit`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-22
**Purpose:** Owns the central, immutable, cross-app activity/change history for Grandway (`AuditEvent`). Other apps emit their important actions here through a service call; the audit app owns the write path and the append-only guarantee. It does NOT own the records it describes (it stores references by type + UUID, never copies of identity/document/file content) and it is not a source of truth for any business data — PostgreSQL remains that.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial contract — `AuditEvent` (Phase 4, federated central audit) |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | Corrected the `changes` key names to `from`/`to` (the docs had said `old`/`new`, which no emitter has ever written); added the `summary` trigram index; refreshed the emitter inventory from 1 app to 12 |

---

## Deliberate Deviations

Realized from `concepts/audit.txt` with these resolved decisions:
- **Federated, not central-only:** per-app logs (e.g. `authenticate.AuthEvent`) remain authoritative for their own review; apps *also* emit each important event here. The central audit is the cross-app aggregate.
- **No FK to the actor/subject:** actor and affected entity are stored as type + UUID (+ a preserved label), not foreign keys, so attribution survives even a hard delete and audit stays decoupled from every other app's models.

---

## 1. AuditEvent

**Purpose:** One immutable record of a single important action anywhere in Grandway, carrying the full traceability model (actor / authority / action / scope / time / reason / source / change).
**Table:** `audit_auditevent`
**`actor_type` choices:** `superadmin`, `admin`, `lead_manager`, `system`, `ai`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| actor_type | CharField(20) | Yes | No | No | The authority the actor held (choices above); `system`/`ai` for non-human actions |
| actor_id | UUID | No | Yes | No | UUID of the acting user; null for system/unknown |
| actor_label | CharField(150) | No | No | No | Human label for the actor (e.g. username), preserved even if the user later changes |
| app_label | CharField(100) | Yes | No | No | Source app that emitted the event (e.g. `authenticate`) |
| action | CharField(100) | Yes | No | No | Stable action/event type, app-defined (e.g. `login_success`, `account_blocked`) |
| entity_type | CharField(100) | No | No | No | Type of the affected record (e.g. `authenticate.user`); blank if not entity-scoped |
| entity_id | UUID | No | Yes | No | UUID of the affected record |
| reason | CharField(255) | No | No | No | Why, when an explanation applies (blank otherwise) |
| source | CharField(100) | No | No | No | Where the action originated (module/request context) |
| ip_address | GenericIPAddress | No | Yes | No | Source IP when applicable |
| success | Boolean | — | No | No | Outcome marker |
| summary | CharField(255) | No | No | No | Human-readable one-line description |
| changes | JSONField | — | No | No | Compact before/after: `{ "<field>": { "from": …, "to": … } }` (default `{}`) |
| metadata | JSONField | — | No | No | Extra non-secret context; AI provenance (model id, prompt/template version) when `actor_type=ai` (default `{}`) |
| created_at | DateTime | — | No | Yes | Event time (UTC) |

**Validation Rules:**
- Append-only: `AuditEvent.objects.delete()` and instance `delete()` raise `ImmutabilityError`; rows are never updated.
- `changes`, `metadata`, `reason`, `summary` must never contain secrets or full document/file contents (§17) — only references and minimal before/after values needed for accountability.
- `changes` uses the keys `from` and `to`, not `old`/`new`. Every emitter writes this shape; a doc that said otherwise is what versions before 1.1.0 got wrong.
- Timestamps stored UTC; BS/NPT representation is derived at the API boundary (§39.4).

**Indexes:**

| Index | Fields | Query it supports |
|-------|--------|-------------------|
| composite | `(entity_type, entity_id)` | A record's timeline — `get_events_for_entity`, behind every app's `/history/` endpoint |
| `audit_summary_trgm_idx` (GIN trigram) | `summary` | The audit log's `?search=` filter, a leading-wildcard `summary__icontains` that no B-tree can serve (§39.6) |
| field indexes | `actor_id`, `app_label`, `action`, `actor_type`, `created_at` | The exact-match list filters, the `date_from`/`date_to`/`fiscal_year` ranges, the default `-created_at` ordering, and the `DISTINCT` behind the filter-values endpoint |

**Soft Delete:** N/A — append-only and immutable; rows are never deleted or soft-deleted. `reset_dev_data` detects the blocked bulk `delete()` and preserves the table.

**Example:**
```json
{
  "id": "e1a2…",
  "actor_type": "admin",
  "actor_id": "6f1c…",
  "actor_label": "ramesh.admin",
  "app_label": "authenticate",
  "action": "account_blocked",
  "entity_type": "authenticate.user",
  "entity_id": "9b7e…",
  "reason": "policy violation",
  "source": "authenticate.services.block_account",
  "ip_address": "203.0.113.7",
  "success": true,
  "summary": "Admin blocked lead manager sita.lead",
  "changes": { "is_active": { "from": true, "to": false } },
  "metadata": {},
  "created_at": "2026-07-22T10:15:00Z"
}
```

`source` is shown populated here because `authenticate` sets it; it is the only app that does. Every other emitter leaves it an empty string — see `INTEGRATION.md` §9.

**Security Notes:** No secrets, hashes, tokens, or full document/file content are ever stored. Actor/entity are UUID references (+ preserved label), never copies of the underlying record. Read access is Admin/Superadmin only (`is_staff`).

---

## Cross-App Dependencies

- **Written to by twelve apps** (service call): `applicant_journeys`, `applicants`, `authenticate`, `checklists`, `clients`, `document_history`, `document_templates`, `documents`, `institutions`, `leads`, `notifications`, and `offers` all call `audit.services.record_event` after an important action. Each of those apps depends on `audit`; `audit` imports none of them (actor and entity are passed in as values, never as foreign keys). `authenticate`'s emit is additionally wrapped best-effort, because its own `AuthEvent` log stays authoritative for authentication review — a central-audit failure there is logged, not raised.
- **Read by six apps** (selector + serializer import): `applicant_journeys`, `applicants`, `clients`, `documents`, `leads`, and `offers` render a per-record `/history/` endpoint by calling `audit.selectors.get_events_for_entity` and serializing with `audit.serializers.AuditEventHistorySerializer`. They consume audit's read shape rather than each redefining one; none of them queries the table directly or imports the model at runtime.
- **Depends on `core`** (framework): `BaseModel` (UUID+timestamps via a UUID PK), response envelope, pagination, exception handler, and `core.nepal.calendar` for the BS projection and fiscal-year ranges.

## Soft Delete

`AuditEvent`: N/A — append-only, immutable, never deleted.
