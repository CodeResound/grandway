# Data Contract — Core

**Owner app:** `core`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-06-18
**Purpose:** Shared abstract infrastructure used by every other app — the base model every domain model inherits from, and the standard API response envelope every endpoint returns. Owns no concrete, queryable business data of its own (see §1's `Table: N/A`).

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-06-18 | Claude Code | Initial definition for `BaseModel` and the Standard API Response Envelope |
| 1.1.0 | 2026-06-29 | AI (Claude) | Reformats to the project-wide documentation format standard: consolidates to one file-level metadata header and Change History table, expands the field table to the standard 6 columns, moves the (non-model) Standard API Response Envelope under `Request/Response Payload Contracts`, adds `Cross-App Dependencies`/`Soft Delete` sections — no content/contract changes |

## 1. BaseModel (Abstract)

**Purpose:** Shared abstract base for all domain models. Provides UUID primary key and audit timestamps.

**Table:** N/A — abstract, no database table of its own.

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key, auto-generated via `uuid.uuid4`, never editable |
| created_at | DateTimeField (TZ-aware) | — | No | Yes | Set on creation, never editable |
| updated_at | DateTimeField (TZ-aware) | — | No | Yes | Updated on every save |

**Validation Rules:**
- `id` is non-editable and never exposed as an internal PK
- All timestamps are UTC-aware (`USE_TZ=True`)

**Soft Delete:** N/A — abstract base class, never directly instantiated or deleted.

**Usage:** Extend `core.models.BaseModel` in any domain model that requires UUID PKs and audit timestamps.
```python
from core.models import BaseModel

class MyModel(BaseModel):
    name = models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.name
```

**Cross-App Dependencies:** every app's concrete models inherit from this class (per CLAUDE.md §2) — a one-directional dependency; `core` depends on none of them.

## Request/Response Payload Contracts

### Standard API Response Envelope

**Purpose:** Unified response shape for all API endpoints. Implemented in `core/responses.py`.
**Produced by:** `core.responses`
**Consumed by:** every app's views, across every endpoint.

**Success Shape:**
```json
{
  "success": true,
  "message": "string",
  "data": {},
  "meta": {}
}
```

**Error Shape:**
```json
{
  "success": false,
  "error": {
    "code": "UPPER_SNAKE_CASE",
    "message": "string",
    "details": {}
  },
  "meta": {}
}
```

## Cross-App Dependencies

`core` has no dependencies on other application apps — it is global infrastructure only (per CLAUDE.md §2). Every other app depends on `core.models.BaseModel` and `core.responses`'s envelope shape; `core` depends on none of them.

## Soft Delete

N/A — `core` owns no concrete, deletable models. `BaseModel` is abstract only (see §1).
