# Data Contract — Search

**Owner app:** `search`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-08-02
**Purpose:** This app owns **no persisted data at all** — no models, no tables, no migrations. What it owns is the *catalogue of searchable record types* and the *response objects* built at read time from other apps' selectors. It does not own any of the records it returns: applicants, leads, clients, documents, files, institutions, programs, templates, and signatories each remain owned, validated, and scoped by their own app. This document therefore contracts three transient objects and one declarative catalogue, not database tables.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-02 | AI (Claude Opus 5) | Initial contract — searchable-type catalogue and three response objects |

---

## Deliberate Deviations

This app deviates from the shape this template assumes, in two named ways:

- **No models, no tables, no migrations.** `dashboards` established the precedent; the rationale is the same and stronger here. Every result is derived at read time from the app that owns the row, so there is nothing to migrate and nothing that could go stale against the records it finds. A search index would be a copy of nine tables that must be kept in step with them — `concepts/search.txt` rules that out explicitly, and `concepts/project_overview.txt` lists a search *store* as out of scope for V1.
- **Sections 1–4 contract transient objects rather than persisted models.** The field tables below describe what an API response carries, not what a column holds. `Required`/`Nullable`/`Generated` are read as: is the key always present, can it be null or empty, and is it derived rather than caller-supplied. `Soft Delete` is `N/A` on all four for the same underlying reason — there is nothing stored to delete.

---

## 1. SearchableType

**Purpose:** One record type the global box can find. This is the app's single source of truth: the query endpoint iterates it, the catalogue endpoint serves it, and `search/registry.py` derives its policy dependencies from it, so a type cannot be searchable without the policy engine knowing which permission opens its results.
**Table:** none — declared in `search/constants.py` as a frozen dataclass tuple.
**`key` choices:** `applicant`, `lead`, `client`, `document`, `uploaded_file`, `institution`, `program`, `document_template`, `signatory`
**`group` choices:** `people`, `work`, `reference`
**`list_search_param` choices:** `search`, `q`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| key | string (choice) | Yes | No | No | Stable `entity_type` value returned on every hit of this type. API vocabulary — changing one is a breaking change (§22/§29). |
| label | string | Yes | No | No | Human section heading, e.g. "Applicants". |
| group | string (choice) | Yes | No | No | Which band of the results panel this section sits in. Fixes the render order. |
| app_label | string | Yes | No | No | The Django app that owns the rows. Informational for a consumer. |
| detail_permission_key | string | Yes | No | No | Permission needed to open one result — the owning app's retrieve endpoint. |
| list_permission_key | string | Yes | No | No | Permission needed to follow "see all" — the owning app's list endpoint. |
| list_path | string | Yes | No | No | Base path of the owning app's list endpoint. |
| list_search_param | string (choice) | Yes | No | No | The query parameter that list endpoint reads. Seven types use `search`; `institution` and `program` use `q`. |
| detail_path | string | Yes | No | No | API path template for one record, containing a literal `{id}` placeholder. |
| matched_fields | list[string] | Yes | No | No | The fields a query is matched against, restated for a consumer. The owning selector remains the authority. |

**Validation Rules:**
- `key` is unique across the catalogue, and is exactly the set of values `?types=` accepts.
- `detail_path` must contain `{id}`; without it every hit of that type would link to the list.
- Both permission keys follow `app.model.action`, lowercase, three dot-separated segments (§35 item 4).
- `list_search_param` must be one of the two parameter names the project actually uses. Storing the wrong one produces a "see all" link that silently returns the unfiltered list.
- All five invariants above are asserted in `search/tests/test_selectors.py`, because nothing in Python enforces them.

**Indexes:** none — an in-memory tuple of nine entries.

**Soft Delete:** N/A — nothing is persisted. A type is removed from search by deleting its catalogue row and its resolver, which is a code change reviewed as such.

**Example:**
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

---

## 2. SearchHit

**Purpose:** One found record, reduced to what a result row needs and nothing more. Deliberately **not** a preview of the record: no status history, no personal detail beyond the identifying line, and no field the owning app would not already show in its own list.
**Table:** none — built per request in `search/selectors.py`.
**`entity_type` choices:** as `SearchableType.key` above.

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| entity_type | string (choice) | Yes | No | Yes | Which type this hit is. What a client routes on. |
| id | UUID string | Yes | No | Yes | The owning record's public id. |
| title | string | Yes | No (may be empty) | Yes | The record's display name — full name, label, filename, or title depending on type. |
| subtitle | string | Yes | No (may be empty) | Yes | One line of context to tell two similar rows apart. Opaque display text; never parse it. |
| matched_on | list[string] | Yes | No (may be empty) | Yes | Which of this row's searchable fields contain the query. Empty is legitimate — a program matched through its institution's name has no matching field of its own. |
| detail_path | string | Yes | No | Yes | API path of this record, with the id filled in. Not a frontend route. |
| detail_permission_key | string | Yes | No | Yes | Permission needed to open it. |

**Validation Rules:**
- `matched_on` is recomputed in Python over the returned rows, case-insensitively, and only over fields already loaded — it never triggers a query. Asserted in `search/tests/test_performance.py`.
- `title` and `subtitle` are whatever the owning record holds; both may be empty strings for a record with a blank name field.
- A hit is only ever built for a row the owning app's selector returned, which is what makes the access rule inherited rather than restated.

**Indexes:** N/A.

**Soft Delete:** N/A — transient. A soft-deleted or archived record appears in search only if the owning app's search selector still returns it; that decision belongs to the owning app.

**Example:**
```json
{
  "entity_type": "applicant",
  "id": "0f1c9c1e-6c7a-4a1f-9f0e-2b7d5a3c8e11",
  "title": "Sita Rai",
  "subtitle": "sita.rai@example.com · active",
  "matched_on": ["full_name", "email"],
  "detail_path": "/api/v1/applicants/0f1c9c1e-6c7a-4a1f-9f0e-2b7d5a3c8e11/",
  "detail_permission_key": "applicants.applicant.read"
}
```

---

## 3. SearchBucket

**Purpose:** One type's section of the results panel — its true total, its first few rows, and where the rest are.
**Table:** none.
**`entity_type` choices:** as `SearchableType.key`. **`group` choices:** `people`, `work`, `reference`.

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| entity_type | string (choice) | Yes | No | Yes | Which type this bucket holds. |
| label | string | Yes | No | Yes | Section heading, from the catalogue. |
| group | string (choice) | Yes | No | Yes | Which band of the panel this section belongs to. |
| total | integer | Yes | No | Yes | The **true** match count for this type, counted against the full queryset — not the number of hits returned. |
| has_more | boolean | Yes | No | Yes | `total > len(hits)`. Saves a client inferring it by comparing two numbers. |
| hits | list[SearchHit] | Yes | No (may be empty) | Yes | Up to `limit_per_type` rows. |
| list_url | string | Yes | No | Yes | The owning app's list endpoint with the same query applied, using that app's own search parameter, URL-encoded. |
| list_permission_key | string | Yes | No | Yes | Permission needed to follow `list_url`. |

**Validation Rules:**
- `total` is counted against the same queryset the rows are sliced from, so the number a user reads is the real backlog rather than the preview length.
- `total` and `hits` are **both** narrowed by the owning app's scoping. A Lead Manager's lead bucket counts only their own leads; their file bucket excludes Admin-only files. A count is a disclosure, so it is scoped exactly as the rows are.
- Empty buckets are returned rather than dropped — "no applicant by that name" is frequently the answer someone needed.
- `list_url` uses `list_search_param` from the catalogue, never a hardcoded parameter name.

**Indexes:** N/A.

**Soft Delete:** N/A — transient.

**Example:**
```json
{
  "entity_type": "lead",
  "label": "Leads",
  "group": "people",
  "total": 14,
  "has_more": true,
  "hits": [
    {
      "entity_type": "lead",
      "id": "b41a7c02-9f3e-4d55-8a10-6c2f1e9d4b73",
      "title": "Sita Gurung",
      "subtitle": "sita.g@example.com · new · Walk-in",
      "matched_on": ["full_name"],
      "detail_path": "/api/v1/leads/b41a7c02-9f3e-4d55-8a10-6c2f1e9d4b73/",
      "detail_permission_key": "leads.lead.read"
    }
  ],
  "list_url": "/api/v1/leads/?search=sita",
  "list_permission_key": "leads.lead.list"
}
```

---

## 4. SearchResult

**Purpose:** The whole results panel for one query — the top-level `data` object of `GET /api/v1/search/`.
**Table:** none.

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| query | string | Yes | No | No | The normalised, trimmed query that was actually run. Echoed so a client can discard a stale response from an earlier keystroke. |
| types | list[string] | Yes | No | Yes | The type keys actually searched, in catalogue order. |
| total_hits | integer | Yes | No | Yes | Sum of every bucket's `total`. Lets a client say "nothing found" once without summing nine numbers. |
| results | list[SearchBucket] | Yes | No (may be empty) | Yes | One bucket per searched type, in fixed catalogue order. Empty only if `types` selected nothing. |

**Validation Rules:**
- `query` is Unicode-normalised (§39.2) and trimmed before use; the echoed value is the normalised one, which may differ byte-wise from what the client sent.
- `results` is ordered by the catalogue, never by the order the caller listed `types` — honouring the caller's order would let two clients render the same results differently.
- `total_hits` equals the sum of bucket totals by construction, and is asserted as such.

**Indexes:** N/A.

**Soft Delete:** N/A — transient.

**Example:** see `INTEGRATION.md` §3 for a full worked envelope.

---

## 5. Cross-App Dependencies

This app reads from seven others and is read by none. Every dependency is a **selector call**, never a model import, and never a direct query — `search/selectors.py` imports no model, deliberately, so that another app's matching rules and access rules cannot be re-implemented here where they would not be tested.

| App | Selectors used | What this app inherits from it |
|-----|----------------|-------------------------------|
| `applicants` | `get_applicants`, `search_applicants`, `rank_applicants` | Match fields and relevance ranking. Unscoped. |
| `leads` | `get_leads_for_actor`, `search_leads`, `rank_leads` | Match fields, relevance ranking, **and owner scoping**. |
| `clients` | `get_clients`, `search_clients` | Match fields. Unscoped. |
| `documents` | `get_documents`, `search_documents` | Match fields, including its refusal to search `content`. Unscoped. |
| `uploaded_files` | `get_visible_files`, `search_files` | Match field **and that app's visibility rule** (Admin-only owner types excluded). |
| `institutions` | `get_institutions`, `filter_institutions`, `get_programs`, `filter_programs` | Match fields via the `q` filter key. Unscoped; availability deliberately not narrowed. |
| `document_templates` | `get_templates`, `search_templates`, `get_signatories`, `search_signatories` | Match fields. Unscoped. |

**Loading strategy is narrowed, filtering never is.** Several resolvers call `select_related(None)` / `prefetch_related(None)` on the owning app's queryset to drop joins a search hit does not render — the file queryset alone sheds nine joins. Joins and prefetches are not filters, so this cannot change which rows come back; it only changes how much is loaded per row. Query counts are pinned in `search/tests/test_performance.py`.

**Indexes added to other apps for this feature** are recorded in those apps' own contracts, not here — `leads` (`lead_contact_num_trgm_idx`), `applicants` (`appl_contact_num_trgm_idx`, `appl_passport_num_trgm_idx`), and `institutions` (`institution_common_trgm_idx`).
