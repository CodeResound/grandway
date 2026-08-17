# Debug History — Leads

## 2026-08-17 — Malformed list-filter params returned 500 instead of 400

**Endpoint/module:** `GET /api/v1/leads/` — `leads.views.LeadListCreateView.get`, `leads.selectors.filter_leads`
**Problem:** Any authenticated lead actor sending `?source=not-a-uuid` or `?fiscal_year=garbage` received a 500: the view passed raw `request.query_params` into the selector, where `filter(source_id=...)` raised Django's (non-DRF) `ValidationError` and `fiscal_year_gregorian_range()` raised `ValueError`. Neither is translated by the global exception handler. Found by the 2026-08-17 pre-production security audit (finding S6, OWASP A04).
**Root cause:** Same as `applicants` — the endpoint predates the filter-serializer pattern the newer apps use.
**Changed files:** `serializers.py` (`LeadListFilterSerializer`), `views.py`, `docs/API.md`, `tests/test_leads.py` (shared validator added in `core/validators.py`, see the applicants entry of the same date)
**Fix summary:** `LeadListFilterSerializer` validates `stage` (choices), `source` (UUID), `search` (length), and `fiscal_year` (shared `validate_fiscal_year_label`, which round-trips the BS conversion) before the selector runs.
**Contract impact:** `API.md` §3.1 → 1.2.1. Malformed filters now return `400 VALIDATION_ERROR` with field details (previously 500); unknown `stage` values now 400 instead of an empty page. Well-formed but unknown `source` ids still return an empty page and 200. Owner scoping unchanged.
**Tests added/updated:** `TestLeadListFilters` — malformed `source`, malformed `fiscal_year`, unknown `stage` each assert 400 with field details; valid `fiscal_year` asserts 200.
**Notes for future AI:** See the applicants entry of the same date — the rule is project-wide: query params go through a filter serializer, never raw into a selector.
