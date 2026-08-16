# API Documentation — Search

**App:** `search`
**Version:** 1.0.0
**Base prefix:** `/api/v1/search/`
**Auth:** Bearer access JWT. Interim inline access checks per CLAUDE.md §9 — Admin and Lead Manager only; Superadmin is denied. See `search/access.py`.
**Throttle:** `SearchThrottle` (scope `search_query`, 60/minute per user) on the query endpoint; project-default `UserRateThrottle` (1000/hour) on the catalogue endpoint.
**Access level:** Staff-only — both endpoints require an authenticated Admin or Lead Manager. Neither is public.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-02 | AI (Claude Opus 5) | Initial API documentation — 2 read-only endpoints |

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

**AI debugging notes (app-wide):**

- **This app owns no tables.** If a bucket is empty, the bug is almost never here — check the owning app's search selector first. `search/selectors.py` imports no model by design, so it cannot be the source of a wrong row.
- **An Admin and a Lead Manager calling the same URL with the same query will legitimately see different totals.** Lead results are narrowed by `leads.selectors.get_leads_for_actor` and file results by `uploaded_files.selectors.get_visible_files`. This is the scoping working. Do not "fix" it by widening the queryset — that is precisely the leak `dashboards` had to close in its activity feed, and `search/tests/test_views.py::TestSearchScoping` will fail if it is reintroduced.
- **Bucket order is fixed server-side** (people → work → reference) and ignores the order of `?types=`. A client that renders sections in response order is correct; one that re-sorts them is diverging from every other client.
- **Query counts are pinned by tests.** A full nine-type search is exactly 20 queries. If `search/tests/test_performance.py` fails, read the captured SQL in the failure output before changing the expected number — an N+1 introduced by a new hit field is the likely cause.
- Neither endpoint writes anything, emits any signal, or records an audit event.

---

## 1. Search

### 1.1 Run global search — `GET /api/v1/search/`

**Policy key(s):** `search.query.read` (risk: medium)

**Request:** query parameters only.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `q` | Yes | — | Search text. 2–150 characters after trimming. Unicode-normalised server-side (§39.2). |
| `types` | No | all nine | Comma-separated `entity_type` keys to restrict the search to. |
| `limit_per_type` | No | `5` | Hits per bucket, 1–20. |

```
GET /api/v1/search/?q=sita&types=applicant,lead&limit_per_type=10
```

**Response:** `DATA_CONTRACT.md §4` (`SearchResult`), composed of `§3` (`SearchBucket`) and `§2` (`SearchHit`). A full worked envelope is in `INTEGRATION.md` §3.

**Validation rules:**
- `q` is required. Unlike a list endpoint, an unqueried global search has no meaningful answer — returning "everything" would be nine unfiltered scans to answer a question nobody asked.
- `q` shorter than 2 characters **after trimming** is refused with 400. A one-character `icontains` matches a large fraction of every table, so it costs nine scans and returns nothing usable; a 400 that says so is more honest than a slow 200.
- An unknown `types` key is rejected, not ignored. Silently dropping it returns a narrower result set that looks exactly like "nothing matched", and the client author debugs their query instead of their typo. The error names the valid keys.
- `limit_per_type` above 20 is refused. This cap is what stops search being an export surface: without it a caller could walk the database through a box that applies no filters.

**Business rules:**
- Results are **grouped by type, never interleaved.** There is no cross-type relevance ordering — an applicant's name score and an institution's name score are produced by different selectors on different scales, so ranking them against each other would produce a confident-looking sequence with nothing behind it.
- Every requested bucket is returned, **including empty ones.** The client decides what to render.
- `total` is the true match count for the type, not the number of hits returned; `has_more` is derived from both.
- **Both `total` and `hits` are narrowed by the owning app's scoping.** A count is a disclosure and is scoped exactly as the rows are.
- Availability is **not** filtered on the `institution` and `program` buckets, unlike the catalogue's own list endpoints, which default to usable records only. Someone searching a paused institution by name is usually checking precisely whether it is paused; the hit's `subtitle` carries `availability_status`.
- Document `content`, file bytes, and operator free-text `notes` are never searched — those hold personal financial and identity detail, and making them reachable by guessing is a decision that needs its own concept.

**Query access pattern:** nine independent bucket queries, each a `COUNT` plus a `LIMIT`ed slice, plus one `contact_numbers` prefetch each for the applicant and lead buckets — **20 queries total** for a full search, invariant in the number of results. Each resolver narrows the owning app's loading strategy to what a hit renders (the file queryset drops nine joins; the applicant queryset drops the `journeys__target_country_ref` prefetch), which changes what is loaded but never which rows match. `?types=` is the one control a caller has over the cost. Pinned by `search/tests/test_performance.py`.

**Throttle:** `SearchThrottle`, 60/minute per user, in a bucket of its own rather than the shared `user` rate. One search is up to nine queries across seven apps and is driven keystroke by keystroke; without its own scope an undebounced search box would spend the project-wide 1000/hour budget in minutes and throttle the user out of the whole API. Clients should debounce.

**Error codes:**

| Code | HTTP | Trigger |
|------|------|---------|
| `VALIDATION_ERROR` | 400 | `q` missing, too short, or too long; unknown `types` key; `limit_per_type` outside 1–20. Field named in `error.details`. |
| `SEARCH_ACTOR_FORBIDDEN` | 403 | The caller's authority may not use global search (Superadmin). |
| `AUTHENTICATION_REQUIRED` | 401 | Missing or invalid bearer token (global). |
| `RATE_LIMIT_EXCEEDED` | 429 | More than 60 searches in a minute. Carries `Retry-After`. |

**AI debugging notes:** validation uses the project-wide `VALIDATION_ERROR` rather than an app-specific code, matching all 92 other views in the project — `error.details` already carries the specificity, and a bespoke `SEARCH_QUERY_INVALID` would force clients to special-case this one endpoint.

---

### 1.2 List searchable types — `GET /api/v1/search/types/`

**Policy key(s):** `search.type.list` (risk: low)

**Request:** no parameters.

**Response:** array of `DATA_CONTRACT.md §1` (`SearchableType`).

**Validation rules:** none — the endpoint takes no input.

**Business rules:**
- Static per deployment; it reads the catalogue in `search/constants.py` and touches no table.
- The `key` values returned are **exactly** the values the query endpoint accepts in `types`. Clients build filter chips from this response rather than hardcoding the list, so a new searchable type reaches every client without a frontend release. Asserted by `search/tests/test_views.py::TestSearchableTypes`.
- The response is **not** narrowed by authority: every caller sees all nine types. A type whose records a caller cannot see still appears and simply returns an empty bucket. Narrowing it would leak, by omission, which record classes a given authority is denied.

**Query access pattern:** zero queries — served from an in-memory tuple.

**Throttle:** project default (`UserRateThrottle`, 1000/hour). No scope of its own; it costs nothing.

**Error codes:**

| Code | HTTP | Trigger |
|------|------|---------|
| `SEARCH_ACTOR_FORBIDDEN` | 403 | The caller's authority may not use global search (Superadmin). |
| `AUTHENTICATION_REQUIRED` | 401 | Missing or invalid bearer token (global). |

**AI debugging notes:** if a filter chip in a client is dead, compare this response against `search/constants.py::SEARCHABLE_TYPES` — the two cannot diverge, since the endpoint serves that tuple directly. A dead chip means the client hardcoded its list.

---

## 2. Access Control

Both endpoints use the interim inline pattern (§9), implemented in `search/access.py`:

- **Superadmin is denied** on both endpoints — a platform authority that manages Admin accounts and does not participate in consultancy operations.
- **Admin and Lead Manager call the same endpoints.** There is no separate "manager search". Narrowing happens in the owning apps' selectors, not in this app.

Neither endpoint is public. There is no anonymous access path.

**The rule this app must never break:** a record appears in results only if the owning app would have shown that row to that caller in its own list. Search is the most tempting place in the project to write a convenient `Model.objects.filter(...)` — shorter and faster than composing nine selectors — and doing so would silently rebuild each app's access rule where it is not tested. `search/selectors.py` imports no model, which makes the mistake unavailable rather than merely discouraged.
