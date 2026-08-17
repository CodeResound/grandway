# Session 20260817_1411 — security-audit remediation (branch `fix_security_audit_20260817_1323`)

## Applicants

## 1. Module
- Name: Applicants
- Base path: `/api/v1/applicants/`
- Auth: unchanged this session (JWT bearer, Admin + Lead Manager)

## 2. Conventions
- Response: no changes this session
- Error: list-filter mistakes now return the standard 400 envelope with the offending field in `error.details`; previously a malformed `country` UUID or `fiscal_year` label was an unhandled 500, and an unknown enum value returned an empty page
- Auth failures: no changes
- Pagination: no changes
- IDs: no changes
- Times: no changes
- List/search/filter/order params: same param set; all now validated before any query runs

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints

### Applicant list — `/api/v1/applicants/`
**Use it when:** the applicant directory screen applies filters.
**Methods:**
- GET `/api/v1/applicants/` (only the error behavior changed)
**Send (create/update):** none (filters via query params, unchanged set)
**Returns:** list[Applicant] — unchanged
**Notes:**
- Malformed `country` (non-UUID), unknown `status`/`creation_source`/`journey_stage`, or an unconvertible `fiscal_year` (e.g. `9999/99`) is now a 400 with field details
- A well-formed but unknown id still returns an empty page and 200
**Errors:**
- `VALIDATION_ERROR` (400) — malformed filter param

## 7. Flows
- No new flows; existing list screens should surface the new 400 field details on filter widgets instead of a generic failure toast.

## 8. Gaps
- none

## Leads

## 1. Module
- Name: Leads
- Base path: `/api/v1/leads/`
- Auth: unchanged this session

## 2. Conventions
- Error: same change as Applicants — malformed `source` UUID / unknown `stage` / unconvertible `fiscal_year` on the list is now a 400 with field details, previously a 500
- All other conventions: no changes this session

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints

### Lead list — `/api/v1/leads/`
**Use it when:** the lead worklist applies stage/source/fiscal-year filters.
**Methods:**
- GET `/api/v1/leads/` (only the error behavior changed)
**Send (create/update):** none
**Returns:** list[Lead] — unchanged
**Notes:**
- Owner scoping unchanged; validation runs before any query
**Errors:**
- `VALIDATION_ERROR` (400) — malformed filter param

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Applicant Journeys

## 1. Module
- Name: Applicant Journeys
- Base path: `/api/v1/journeys/`
- Auth: unchanged this session

## 2. Conventions
- Error: malformed `applicant`/`target_country_ref` UUID, unknown `stage`, or unconvertible `fiscal_year` on the list is now a 400 with field details, previously a 500
- All other conventions: no changes this session

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints

### Journey list — `/api/v1/journeys/`
**Use it when:** the per-applicant view or stage worklist applies filters.
**Methods:**
- GET `/api/v1/journeys/` (only the error behavior changed)
**Send (create/update):** none
**Returns:** list[Journey] — unchanged
**Errors:**
- `VALIDATION_ERROR` (400) — malformed filter param

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Clients

## 1. Module
- Name: Clients
- Base path: `/api/v1/clients/`
- Auth: unchanged this session

## 2. Conventions
- Error: a format-valid but unconvertible `fiscal_year` (e.g. `9999/99`) on the list is now a 400 with field details, previously a 500. No other change this session.

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint added, changed, or retired beyond the `fiscal_year` error behavior above.

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Offers

## 1. Module
- Name: Offers
- Base path: `/api/v1/offers/`
- Auth: unchanged this session

## 2. Conventions
- Error: same `fiscal_year` change as Clients — `9999/99`-style labels are now a 400, previously a 500. No other change this session.

## 3. Models
- No changes this session (a database index on `decided_at` was added — invisible over HTTP).

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint added, changed, or retired beyond the `fiscal_year` error behavior above.

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Authenticate

## 1. Module
- Name: Authenticate
- Base path: `/api/v1/auth/`
- Auth: unchanged this session

## 2. Conventions
- No changes this session.

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No API endpoint added, changed, or retired. The account list (`GET /api/v1/auth/users/`) responds identically but no longer costs per-row device queries.
- Outside `/api/v1/`: the Django admin at `/admin/` now requires a verified TOTP device at login (OTPAdminSite). Staff without a confirmed device cannot enter the admin; enrol through the API's MFA endpoints first.

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Checklists

## 1. Module
- Name: Checklists
- Base path: `/api/v1/checklists/`
- Auth: unchanged this session

## 2. Conventions
- No changes this session.

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint added, changed, or retired. Checklist detail responds identically but no longer costs two queries per item.

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Uploaded Files

## 1. Module
- Name: Uploaded Files
- Base path: `/api/v1/files/`
- Auth: unchanged this session

## 2. Conventions
- No changes this session. The `?checksum=` filter remains case-insensitive; it now uses the column's index internally.

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint added, changed, or retired.

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Dashboards

## 1. Module
- Name: Dashboards
- Base path: `/api/v1/dashboard/`
- Auth: unchanged this session

## 2. Conventions
- No changes this session (the fiscal-year validator now lives in a shared core rule; behavior identical).

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint added, changed, or retired.

## 7. Flows
- No new flows.

## 8. Gaps
- none

## Core

## 1. Module
- Name: Core (infrastructure)
- Base path: `/api/v1/` (envelope, pagination), `/health/`, `/ready/`
- Auth: unchanged this session

## 2. Conventions
- No changes visible over HTTP. Server-side this session: Django 5.2.17 / DRF 3.16.1 / simplejwt 5.5.1 / gunicorn 23.0.0; environment selection fails closed when `ENVIRONMENT` is unset or unknown; production requires an explicit throttle-cache backend; audited client IPs resolve through `NUM_PROXIES`.

## 3. Models
- No changes this session.

## 4. Enums
- No changes this session.

## 5. Dependency order
- No changes this session.

## 6. Endpoints
- No endpoint added, changed, or retired.

## 7. Flows
- No new flows.

## 8. Gaps
- none
