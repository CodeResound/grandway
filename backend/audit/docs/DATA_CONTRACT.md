# Data Contract — Audit

**Owner app:** `audit`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-22
**Purpose:** Owns the central, immutable, cross-app activity/change history for Grandway (`AuditEvent`). Other apps emit their important actions here through a service call; the audit app owns the write path and the append-only guarantee. It does NOT own the records it describes (it stores references by type + UUID, never copies of identity/document/file content) and it is not a source of truth for any business data — PostgreSQL remains that.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial contract — `AuditEvent` (Phase 4, federated central audit) |

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
| changes | JSONField | — | No | No | Compact before/after: `{ "<field>": { "old": …, "new": … } }` (default `{}`) |
| metadata | JSONField | — | No | No | Extra non-secret context; AI provenance (model id, prompt/template version) when `actor_type=ai` (default `{}`) |
| created_at | DateTime | — | No | Yes | Event time (UTC) |

**Validation Rules:**
- Append-only: `AuditEvent.objects.delete()` and instance `delete()` raise `ImmutabilityError`; rows are never updated.
- `changes`, `metadata`, `reason`, `summary` must never contain secrets or full document/file contents (§17) — only references and minimal before/after values needed for accountability.
- Timestamps stored UTC; BS/NPT representation is derived at the API boundary (§39.4).

**Indexes:** composite `(entity_type, entity_id)` (record timeline); `actor_id`; `app_label`; `action`; `actor_type`; `created_at`.

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
  "changes": { "is_active": { "old": true, "new": false } },
  "metadata": {},
  "created_at": "2026-07-22T10:15:00Z"
}
```

**Security Notes:** No secrets, hashes, tokens, or full document/file content are ever stored. Actor/entity are UUID references (+ preserved label), never copies of the underlying record. Read access is Admin/Superadmin only (`is_staff`).

---

## Cross-App Dependencies

- **Referenced by `authenticate`** (service call): `authenticate.services.record_auth_event` also calls `audit.services.record_event` (best-effort, federated) so authentication activity appears in the central audit. `authenticate` depends on `audit`; `audit` does not import `authenticate` (actor/entity are passed in as values).
- **Depends on `core`** (framework): `BaseModel` (UUID+timestamps via a UUID PK), response envelope, pagination, exception handler.
- No other app writes to audit yet; future operational apps will emit here through the same `record_event` service.

## Soft Delete

`AuditEvent`: N/A — append-only, immutable, never deleted.
