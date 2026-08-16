# Iteration — 2026-08-02 00:52

Session: `add_global_search_20260802_0023`

---

## Search

## 1. Module

- **Name:** Search — the one global search box, answering a single query across every searchable record type.
- **Base path:** `/api/v1/search/`
- **Auth:** Bearer access JWT; Admin and Lead Manager only, Superadmin rejected with 403.

## 2. Conventions

- **Response:** the standard envelope — `{ success, message, data, meta }`. `meta` is always `{}`.
- **Error:** `{ success: false, error: { code, message, details }, meta: {} }`.
- **Auth failures:** 401 `AUTHENTICATION_REQUIRED` (missing/invalid token); 403 `SEARCH_ACTOR_FORBIDDEN` (Superadmin); 429 `RATE_LIMIT_EXCEEDED` with `Retry-After`.
- **Pagination:** not paginated. Each bucket is capped at `limit_per_type` and links to the owning app's paginated list via `list_url`.
- **IDs:** UUID strings.
- **Times:** no timestamp is returned by either endpoint.
- **List/search/filter/order params:** `q` (required, 2–150 chars after trimming), `types` (comma-separated type keys), `limit_per_type` (1–20, default 5). Bucket order is fixed server-side and not caller-controllable.

## 3. Models

**SearchResult** — `{ query, types:[string], total_hits, results:[SearchBucket] }`

**SearchBucket** — `{ entity_type:[enum], label, group:[enum], total, has_more, hits:[SearchHit], list_url, list_permission_key }`

- `total` is the true match count, not the number of hits returned; `has_more` is `total > len(hits)`.
- Empty buckets are returned rather than dropped.

**SearchHit** — `{ entity_type:[enum], id, title, subtitle, matched_on:[string], detail_path, detail_permission_key }`

- `detail_path` is an API path, not a frontend route.
- `matched_on` may be empty — a `program` matched through its institution's name has no matching field of its own.

**SearchableType** — `{ key:[enum], label, group:[enum], app_label, matched_fields:[string], detail_path, detail_permission_key, list_path, list_search_param:[enum], list_permission_key }`

- `detail_path` here is a template containing a literal `{id}`; on a `SearchHit` it is already filled in.

## 4. Enums

- `SearchHit.entity_type` / `SearchBucket.entity_type` / `SearchableType.key`: `applicant` | `lead` | `client` | `document` | `uploaded_file` | `institution` | `program` | `document_template` | `signatory`
- `SearchBucket.group` / `SearchableType.group`: `people` | `work` | `reference`
- `SearchableType.list_search_param`: `search` | `q`

## 5. Dependency order

- `search` needs a session from `authenticate` (external module).
- Each bucket needs records in its owning module (external modules) — an empty system returns empty buckets, not an error.

**Start here:** read-only module — `GET /api/v1/search/types/` once at startup, then `GET /api/v1/search/`.

## 6. Endpoints

### Global search — `/api/v1/search/`

**Use it when:** a user types into the application-wide search box — finding a person by name, phone, email, or passport number; finding a file by filename; checking an institution or program mid-advice.

**Methods:**
- `GET /api/v1/search/` — one query across every searchable type (`search.query.read`, risk medium)

**Send (create/update):** `none` — read-only. Query parameters only: `q`, `types`, `limit_per_type`.

**Returns:** `SearchResult`

**Notes:**
- Results are grouped by type and never interleaved; there is no cross-type relevance ordering.
- Bucket order is fixed: people (applicant, lead, client), work (document, uploaded_file), reference (institution, program, document_template, signatory). The order of keys in `types` is ignored.
- Both `total` and `hits` inherit the owning app's scoping. A Lead Manager sees only their own leads and no Admin-only files, so two authorities legitimately see different totals for the same query.
- Applicant and lead buckets are relevance-ranked (exact name > prefix > substring); other buckets use their owning app's default ordering.
- Availability is not filtered on the `institution` and `program` buckets, unlike the catalogue's own lists.
- Document `content`, file bytes, and operator notes are never searched.
- Throttled at 60/minute per user on its own scope, separate from the project-wide budget.

**Errors:**
- `VALIDATION_ERROR` (400) — `q` missing, under 2 characters after trimming, or over 150; unknown `types` key; `limit_per_type` outside 1–20
- `SEARCH_ACTOR_FORBIDDEN` (403) — the caller's authority may not use global search
- `RATE_LIMIT_EXCEEDED` (429) — more than 60 searches in a minute

### Searchable types — `/api/v1/search/types/`

**Use it when:** building the search UI at startup — the type filter chips and the `entity_type` → route map.

**Methods:**
- `GET /api/v1/search/types/` — list every searchable record type (`search.type.list`, risk low)

**Send (create/update):** `none` — takes no parameters.

**Returns:** `list[SearchableType]`

**Notes:**
- Static per deployment; served from an in-memory catalogue, zero queries.
- The `key` values returned are exactly the values `?types=` accepts.
- Not narrowed by authority — every caller sees all nine types.

**Errors:**
- `SEARCH_ACTOR_FORBIDDEN` (403) — the caller's authority may not use global search

## 7. Flows

**Find a person at the counter**
1. `GET /api/v1/search/types/` at shell startup → cache the nine rows for the filter chips.
2. `GET /api/v1/search/?q=sita` → capture `results`.
3. Render each bucket with `total > 0`, in the order returned.
4. Open a hit at its `detail_path` → `GET /api/v1/applicants/<id>/`.
   - `total_hits` is 0: one "nothing found" message, not nine empty sections.
   - Bucket has `has_more`: follow `list_url` for the full paginated set.
   - 400 naming `q`: the query was under two characters — enforce the minimum client-side.

**Find a file whose owner nobody remembers**
1. `GET /api/v1/search/?q=passport-scan&types=uploaded_file` → the `uploaded_file` bucket.
2. Open the hit at its `detail_path` → `GET /api/v1/files/<id>/`.
   - Empty for a Lead Manager but non-empty for an Admin: the file belongs to a document or snapshot and is outside that authority's visibility. Not a failure; show the ordinary empty state.

**Look up an institution, then shortlist**
1. `GET /api/v1/search/?q=melbourne&types=institution,program`.
2. Read `availability_status` from each hit's `subtitle` — paused records are returned here deliberately.
3. Follow the program bucket's `list_url` → `GET /api/v1/catalogue/programs/?q=melbourne`, where the real shortlisting filters live.

**Narrow a noisy search**
1. `GET /api/v1/search/?q=ram` → the people buckets are large.
2. User selects a chip → `GET /api/v1/search/?q=ram&types=applicant&limit_per_type=20`.
   - `limit_per_type=50`: 400. The cap is 20; page through `list_url` instead.

## 8. Gaps

- `subtitle` composition is not contractually pinned — it is assembled from different fields per type and joined with ` · `. Treat it as opaque display text.
- `matched_on` for `program` can be empty when the match came through the institution's name; a client cannot distinguish "matched via institution" from "matched, field unknown".
- `clients.spokesperson_name` is searched but not trigram-indexed (deliberate — bounded table).
- `document_template` label and key are searched without a trigram index (deliberate — fixed ~53 rows).
- Journeys, offers, and checklists are not searchable and are not planned to be.
- Searches are not recorded in the audit log; whether they should be is unresolved.
- Whether a Lead Manager should see all applicants, documents, and catalogue records is unresolved project-wide. Today they do, because those apps do not narrow their own lists.

---

## Applicants

## 1. Module

- **Name:** Applicants
- **Base path:** `/api/v1/applicants/`
- **Auth:** unchanged this session.

## 2. Conventions

No changes this session.

## 3. Models

No field, shape, or contract changes this session. Two indexes were added; indexes are not client-visible.

## 4. Enums

No changes this session.

## 5. Dependency order

No changes this session. `search` now reads this app's selectors, which adds no constraint for a client.

## 6. Endpoints

**No endpoint changes this session.** No route, method, parameter, response shape, or error code was added, changed, or retired.

## 7. Flows

No flow changes this session.

## 8. Gaps

- Phone and passport search were previously unindexed for substring matching; both are now trigram-indexed. No client-visible behaviour changed — the same queries return the same rows, faster.

---

## Institutions

## 1. Module

- **Name:** Institutions (catalogue)
- **Base path:** `/api/v1/catalogue/`
- **Auth:** unchanged this session.

## 2. Conventions

No changes this session.

## 3. Models

No field, shape, or contract changes this session. One index was added.

## 4. Enums

No changes this session.

## 5. Dependency order

No changes this session.

## 6. Endpoints

**No endpoint changes this session.**

## 7. Flows

No flow changes this session.

## 8. Gaps

- `?q=` matched `name` or `common_name` with only `name` indexed, so the disjunction behaved as if neither were. `common_name` is now trigram-indexed. No client-visible behaviour changed.

---

## Leads

## 1. Module

- **Name:** Leads
- **Base path:** `/api/v1/leads/`
- **Auth:** unchanged this session.

## 2. Conventions

No changes this session.

## 3. Models

No field, shape, or contract changes this session. One index was added.

## 4. Enums

No changes this session.

## 5. Dependency order

No changes this session.

## 6. Endpoints

**No endpoint changes this session.**

## 7. Flows

No flow changes this session.

## 8. Gaps

- `?search=` by phone number was a sequential scan; `LeadContactNumber.number` is now trigram-indexed. No client-visible behaviour changed.

---

## Core

## 1. Module

- **Name:** Core — settings, routing, envelopes, and the project-level integration entry point.
- **Base path:** n/a
- **Auth:** unchanged this session.

## 2. Conventions

- A new throttle scope `search_query` (60/minute) exists in `DEFAULT_THROTTLE_RATES`. It applies only to `GET /api/v1/search/`; no other endpoint's rate changed.

## 3. Models

No changes this session — `core` owns no business tables.

## 4. Enums

No changes this session.

## 5. Dependency order

No changes this session.

## 6. Endpoints

**No endpoint changes this session.** `/api/v1/search/` was added to the root URL tree, but the endpoints belong to the `search` app and are documented in its block above.

## 7. Flows

No flow changes this session.

## 8. Gaps

- The project-level `core/docs/INTEGRATION.md` previously stated `dashboards` was the only app owning no table, and its §10 access table omitted both read-only aggregators. Both are corrected; a sixth access shape ("read-only, composed") now covers `dashboards` and `search`.
