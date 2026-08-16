# Integration — Search

**Owner app:** `search`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-08-02

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-02 | AI (Claude Opus 5) | Initial integration contract — 2 read-only endpoints, 9 searchable record types |

---

## 1. Module

- **Name:** Search — the one global search box. A single query answered across every searchable record type, grouped by type, with each group linking to the owning module's own list endpoint for the full set. It owns no data and writes nothing.
- **Base path:** `/api/v1/search/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. Two authority types may use this module: `admin` and `lead_manager`. A `superadmin` token is rejected with 403 everywhere.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which decides whether the caller may search at all and how lead and file results are scoped. | Every endpoint returns 401. Without a recognised `authority_type` the caller gets 403 `SEARCH_ACTOR_FORBIDDEN`. |
| `applicants` | service call | The `applicant` bucket, matched on name, email, contact number, and passport number, and relevance-ranked. | The `applicant` bucket is always empty. |
| `leads` | service call | The `lead` bucket, matched on name, email, and contact number, relevance-ranked, **including that module's owner scoping**. | The `lead` bucket is always empty. |
| `clients` | service call | The `client` bucket, matched on organization name and spokesperson name. | The `client` bucket is always empty. |
| `documents` | service call | The `document` bucket, matched on label only. | The `document` bucket is always empty. |
| `uploaded_files` | service call | The `uploaded_file` bucket, matched on original filename, **including that module's own per-record visibility rule**. | The `uploaded_file` bucket is always empty. |
| `institutions` | service call | The `institution` and `program` buckets, matched on institution name, common name, and program title. | Both catalogue buckets are always empty. |
| `document_templates` | service call | The `document_template` and `signatory` buckets, matched on template label/key and signatory name. | Both library buckets are always empty. |

**This module has no inbound dependencies.** Nothing reads it, nothing points at it, and removing it would break no other module. It is a leaf.

## 3. Conventions

- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. `meta` is always an empty object on this module; neither endpoint paginates.

```json
{
  "success": true,
  "message": "Search results retrieved.",
  "data": {
    "query": "sita",
    "types": ["applicant", "lead", "client", "document", "uploaded_file", "institution", "program", "document_template", "signatory"],
    "total_hits": 3,
    "results": [
      {
        "entity_type": "applicant",
        "label": "Applicants",
        "group": "people",
        "total": 2,
        "has_more": false,
        "hits": [
          {
            "entity_type": "applicant",
            "id": "0f1c9c1e-6c7a-4a1f-9f0e-2b7d5a3c8e11",
            "title": "Sita Rai",
            "subtitle": "sita.rai@example.com · active",
            "matched_on": ["full_name"],
            "detail_path": "/api/v1/applicants/0f1c9c1e-6c7a-4a1f-9f0e-2b7d5a3c8e11/",
            "detail_permission_key": "applicants.applicant.read"
          }
        ],
        "list_url": "/api/v1/applicants/?search=sita",
        "list_permission_key": "applicants.applicant.list"
      }
    ]
  },
  "meta": {}
}
```

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object holding field-level problems.

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { "q": ["Must be at least 2 characters."] }
  },
  "meta": {}
}
```

- **Auth failures:** 401 `AUTHENTICATION_REQUIRED` with no or invalid bearer token. 403 `SEARCH_ACTOR_FORBIDDEN` for a `superadmin` token. 429 `RATE_LIMIT_EXCEEDED` with a `Retry-After` header when the search rate is exceeded.
- **Pagination:** not paginated, deliberately. The query returns a fixed set of buckets, each capped at `limit_per_type`. Depth is reached by following a bucket's `list_url` into the owning module's list endpoint, which is paginated.
- **IDs:** UUID strings.
- **Times:** no timestamp is returned by either endpoint.
- **List/search/filter/order params:** `q` (required), `types` (optional, comma-separated), `limit_per_type` (optional, 1–20, default 5). Bucket order is fixed by the server and is not caller-controllable.

## 4. Models

**SearchResult** — `{ query, types:[string], total_hits, results:[SearchBucket] }`

**SearchBucket** — `{ entity_type:[enum], label, group:[enum], total, has_more, hits:[SearchHit], list_url, list_permission_key }`

- `total` is the true number of matches for that type, not the number of `hits` returned. `has_more` is `total > len(hits)`.
- Every requested bucket is returned, **including empty ones** — an empty bucket carries `total: 0` and `hits: []`.

**SearchHit** — `{ entity_type:[enum], id, title, subtitle, matched_on:[string], detail_path, detail_permission_key }`

- `detail_path` is an **API** path, not a frontend route. The client maps `entity_type` to its own routing.
- `matched_on` names the fields that contain the query. It may be **empty**: a `program` matched through its institution's name has no matching field of its own.
- `subtitle` may be an empty string. It is context to tell two similar rows apart, never a complete record.

**SearchableType** — `{ key:[enum], label, group:[enum], app_label, matched_fields:[string], detail_path, detail_permission_key, list_path, list_search_param:[enum], list_permission_key }`

- `detail_path` here is a **template** containing a literal `{id}` placeholder; on a `SearchHit` it is already filled in.

### Worked examples

```json
{
  "key": "institution",
  "label": "Institutions",
  "group": "reference",
  "app_label": "institutions",
  "matched_fields": ["name", "common_name"],
  "detail_path": "/api/v1/catalogue/institutions/{id}/",
  "detail_permission_key": "institutions.institution.read",
  "list_path": "/api/v1/catalogue/institutions/",
  "list_search_param": "q",
  "list_permission_key": "institutions.institution.list"
}
```

## 5. Enums

- `SearchHit.entity_type` / `SearchBucket.entity_type` / `SearchableType.key`: `applicant` | `lead` | `client` | `document` | `uploaded_file` | `institution` | `program` | `document_template` | `signatory`
- `SearchBucket.group` / `SearchableType.group`: `people` | `work` | `reference`
- `SearchableType.list_search_param`: `search` | `q`
- `SearchHit.matched_on` values, by `entity_type`: `applicant` → `full_name` | `email` | `contact_number` | `passport_number`; `lead` → `full_name` | `email` | `contact_number`; `client` → `name` | `spokesperson_name`; `document` → `label`; `uploaded_file` → `original_filename`; `institution` → `name` | `common_name`; `program` → `title`; `document_template` → `label` | `key`; `signatory` → `name`

## 6. Dependency order

- `search` needs a session from `authenticate` (external module) — no other precondition.
- Every bucket needs records to exist in its owning module (external modules) — searching an empty system returns nine empty buckets and `total_hits: 0`, not an error.

**Start here:** read-only module — call `GET /api/v1/search/types/` once at startup, then `GET /api/v1/search/`.

## 7. Endpoints

### Global search — `/api/v1/search/`

**Use it when:** a user types into the application-wide search box — finding a person at the counter by name, phone number, email, or passport number; finding a file by its filename; finding an institution or program while advising.
**Methods:**
- `GET /api/v1/search/` — run one query across every searchable type (permission: `search.query.read`, risk: medium)

**Send (create/update):** `none` — read-only. Query parameters only:
- `q` (required) — the search text. Minimum 2 characters after trimming, maximum 150. Unicode-normalised server-side.
- `types` (optional) — comma-separated `entity_type` keys to restrict the search to. Omit for all nine.
- `limit_per_type` (optional) — hits per bucket, 1–20, default 5.

**Returns:** `SearchResult`
**Requires state:** an authenticated session held by an `admin` or `lead_manager`. No records need to exist; an empty system returns empty buckets.
**Side effects:** `none`. Nothing is written, in this module or any other. Searches are not recorded in the audit log.
**Notes:**
- **Results are narrowed by each owning module's own rules, so two authorities legitimately see different totals for the same query.** A `lead_manager` sees only leads they own, and no file belonging to a `document` or a print snapshot. This is the scoping working, not a bug — do not report differing counts as a defect.
- Buckets are returned in a fixed server-side order: `people` (applicant, lead, client), then `work` (document, uploaded_file), then `reference` (institution, program, document_template, signatory). The order of keys in `types` is ignored.
- Results are **grouped, never interleaved**. There is no cross-type relevance ranking; scores from different modules are not comparable.
- Within the `applicant` and `lead` buckets, hits are relevance-ranked: an exact name match outranks a prefix match, which outranks a substring match. Other buckets use their owning module's default ordering.
- Availability is **not** filtered on the `institution` and `program` buckets — a paused or withdrawn record is findable, and its `subtitle` carries its `availability_status`. This differs from the catalogue's own list endpoints, which default to usable records only.
- Document `content`, file bytes, and operator free-text notes are never searched.
- Rate limited to 60 requests per minute per user, separately from the project-wide budget. Debounce a search-as-you-type box.

**Errors:**
- `VALIDATION_ERROR` (400) — `q` missing, shorter than 2 characters after trimming, or longer than 150; `types` naming an unknown key; `limit_per_type` outside 1–20. The offending field is named in `error.details`.
- `SEARCH_ACTOR_FORBIDDEN` (403) — the caller's authority may not use global search (a `superadmin` token).
- `RATE_LIMIT_EXCEEDED` (429) — more than 60 searches in a minute. Honour `Retry-After`.

### Searchable types — `/api/v1/search/types/`

**Use it when:** building the search UI at startup — rendering the type filter chips, and building the map from `entity_type` to the client's own detail route.
**Methods:**
- `GET /api/v1/search/types/` — list every searchable record type (permission: `search.type.list`, risk: low)

**Send (create/update):** `none` — read-only, takes no parameters.
**Returns:** `list[SearchableType]`
**Requires state:** an authenticated session held by an `admin` or `lead_manager`.
**Side effects:** `none`.
**Notes:**
- Static per deployment. Fetch once and cache for the session; it does not change between calls.
- The `key` values returned here are exactly the values `GET /api/v1/search/` accepts in `types`. Build filter chips from this response rather than hardcoding the list, so a new searchable type reaches the client without a release.
- The response is **not** narrowed by authority: every caller sees all nine types. A type whose records the caller cannot see still appears, and simply returns an empty bucket.

**Errors:**
- `SEARCH_ACTOR_FORBIDDEN` (403) — the caller's authority may not use global search.

## 8. Flows

**Find a person at the counter and open their record**
1. `GET /api/v1/search/types/` once at startup → cache the nine `key`/`label`/`group` rows for the filter chips.
2. User types "sita rai" → `GET /api/v1/search/?q=sita%20rai` → capture `results`.
3. Render each bucket with `total > 0` as a section, in the order returned; show `title`, `subtitle`, and a badge from `matched_on`.
4. User clicks the applicant hit → route on `entity_type` = `applicant` and the `id`; the record is at `detail_path` (cross-app: `applicants`).
   - Bucket has `has_more: true`: render "see all {total}" linking to `list_url`, which is the applicants list already filtered by the same query (cross-app: `applicants`).
   - `total_hits` is `0` across every bucket: show one "nothing found" message, not nine empty sections.
   - 400 with `q` in `error.details`: the query was under 2 characters — do not send it; require two characters client-side.

**Find a file whose owner nobody remembers**
1. `GET /api/v1/search/?q=passport-scan&types=uploaded_file` → the `uploaded_file` bucket.
2. Open the hit's `detail_path` to read the file record and reach its owner (cross-app: `uploaded_files`).
   - The bucket is empty for a `lead_manager` but non-empty for an `admin`: the file belongs to a `document` or a print snapshot and is outside a Lead Manager's visibility. This is correct; do not retry or escalate.

**Look up an institution while advising, then shortlist**
1. `GET /api/v1/search/?q=melbourne&types=institution,program` → both catalogue buckets.
2. Read `subtitle` on each hit for the country and `availability_status` — a paused institution is returned here and must be shown as paused.
3. To shortlist properly, follow the `program` bucket's `list_url` into the catalogue's own list, which carries the real filters — country, level, field, tuition, scholarship (cross-app: `institutions`).

**Narrow a noisy search**
1. `GET /api/v1/search/?q=ram` → the people buckets are large.
2. User selects the "Applicants" chip → `GET /api/v1/search/?q=ram&types=applicant&limit_per_type=20`.
3. Only the `applicant` bucket is returned, with up to 20 hits — and the request costs proportionally less server-side.
   - `limit_per_type=50`: 400. The cap is 20; page through `list_url` instead.

## 9. Gaps

- **No token-issuance endpoint is owned by this module.** Authentication is entirely `authenticate`'s; this contract assumes a valid bearer access JWT already exists.
- **`subtitle` composition is not contractually pinned.** It is a human-readable line assembled from different fields per `entity_type` and joined with ` · `. Treat it as opaque display text; never parse it.
- **`matched_on` for the `program` type can be empty** when the match came through the institution's name rather than the program title. There is currently no way for a client to distinguish "matched via institution" from "matched, field unknown".
- **The `client` bucket's `spokesperson_name` is searched but not indexed**, so that half of the client query does not scale the way the others do. This is a deliberate decision recorded in `clients/selectors.py` (the directory is a bounded table); revisit if the directory reaches a few thousand rows.
- **`document_template` label and key are searched without a trigram index** — deliberate, as the catalogue is a fixed ~53 rows.
- **Journeys, offers, and checklists are not searchable** and are not planned to be. None has a name of its own; all are reached by navigating from the applicant.
- **Searches are not audited.** Whether "who looked up whom" should be recorded is an open question in `concepts/search.txt` and is not currently answered either way.
- **Whether a Lead Manager should see all applicants, documents, and catalogue records** is unresolved project-wide (`concepts/project_overview.txt` — Open questions). Today they do, because those modules do not narrow their own lists. If that answer changes, these buckets narrow with it and totals will drop.
