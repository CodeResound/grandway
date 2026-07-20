# API Documentation — Core

**App:** `core`
**Version:** 1.1.0
**Base prefix:** N/A — registered directly in `core/urls.py`, not under `/api/v1/` (per CLAUDE.md §23)
**Auth:** Public — both endpoints, no auth required (§23)
**Throttle:** None — excluded from rate limiting (§23)
**Access level:** Public

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-06-18 | Claude Code | Initial scaffold — health check endpoints and standard response envelope |
| 1.1.0 | 2026-06-29 | AI (Claude) | Reformats to the project-wide documentation format standard: adds metadata header, converts Change History to the standard `Version\|Date\|Author\|Summary` shape, numbers endpoints hierarchically — no content/contract changes |

## Generic envelopes (referenced throughout)

All API endpoints (under `/api/v1/`) use these shapes. The two endpoints in this file are the exception — they're public infrastructure checks, not under `/api/v1/`, and use minimal `{"status": "..."}` bodies instead (see §1).

**Success:**
```json
{
  "success": true,
  "message": "...",
  "data": {},
  "meta": {}
}
```

**Error:**
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "...",
    "details": {}
  },
  "meta": {}
}
```

**Paginated List:**
```json
{
  "success": true,
  "message": "",
  "data": [],
  "meta": {
    "count": 100,
    "page": 1,
    "page_size": 20,
    "next": "https://api.example.com/api/v1/resource/?page=2",
    "previous": null
  }
}
```

**Global Error Codes:**

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `INTERNAL_SERVER_ERROR` | 500 | Unhandled exception |
| `VALIDATION_ERROR` | 400 | Request body validation failed |
| `AUTHENTICATION_REQUIRED` | 401 | No credentials provided |
| `AUTHENTICATION_FAILED` | 401 | Invalid or expired credentials |
| `PERMISSION_DENIED` | 403 | Authenticated but not authorized |
| `NOT_FOUND` | 404 | Resource not found |
| `METHOD_NOT_ALLOWED` | 405 | HTTP method not supported |
| `RATE_LIMIT_EXCEEDED` | 429 | Throttle limit hit |

## 1. Health Checks

### 1.1 Liveness — `GET /health/`

**Auth required:** No (public)
**Throttle class:** None
**Purpose:** Liveness check — confirms the process is running.

**Response (200 OK):**
```json
{ "status": "ok" }
```

**Business rules:** Always returns 200 while the process is alive. No DB check performed.

### 1.2 Readiness — `GET /ready/`

**Auth required:** No (public)
**Throttle class:** None
**Purpose:** Readiness check — confirms the service is ready to handle traffic (DB connected).

**Response (200 OK):**
```json
{ "status": "ready" }
```

**Response (503 Service Unavailable):**
```json
{ "status": "not ready" }
```

**Business rules:** Returns 503 if the database connection cannot be established.
