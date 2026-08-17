# Debug History — Applicant Journeys

## 2026-08-17 — Malformed list-filter params returned 500 instead of 400

**Endpoint/module:** `GET /api/v1/journeys/` — `applicant_journeys.views.JourneyListCreateView.get`, `applicant_journeys.selectors.filter_journeys`
**Problem:** Any authenticated journey actor sending `?applicant=not-a-uuid`, `?target_country_ref=not-a-uuid`, or `?fiscal_year=garbage` received a 500: the view passed raw `request.query_params` into the selector, where the UUID filters raised Django's (non-DRF) `ValidationError` and `fiscal_year_gregorian_range()` raised `ValueError`. Neither is translated by the global exception handler. Found by the 2026-08-17 pre-production security audit (finding S6, OWASP A04).
**Root cause:** Same as `applicants` and `leads` — the endpoint predates the filter-serializer pattern the newer apps use.
**Changed files:** `serializers.py` (`JourneyListFilterSerializer`), `views.py`, `docs/API.md`, `tests/test_journeys.py` (shared validator added in `core/validators.py`, see the applicants entry of the same date)
**Fix summary:** `JourneyListFilterSerializer` validates `applicant` and `target_country_ref` (UUID), `stage` (choices), `target_country` (length), and `fiscal_year` (shared `validate_fiscal_year_label`) before the selector runs.
**Contract impact:** `API.md` §1.1 → 1.1.1. Malformed filters now return `400 VALIDATION_ERROR` with field details (previously 500); unknown `stage` values now 400 instead of an empty page. Well-formed but unknown ids still return an empty page and 200.
**Tests added/updated:** `TestJourneyListFilterValidation` — malformed `applicant`, malformed `target_country_ref`, malformed `fiscal_year` each assert 400 with field details; valid `fiscal_year` asserts 200.
**Notes for future AI:** See the applicants entry of the same date — the rule is project-wide: query params go through a filter serializer, never raw into a selector.
