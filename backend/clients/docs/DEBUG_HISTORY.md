# Debug History — Clients

## 2026-08-17 — Format-valid but unconvertible `fiscal_year` returned 500

**Endpoint/module:** `GET /api/v1/clients/` — `clients.serializers` list filter, `clients.selectors`
**Problem:** The list filter validated `fiscal_year` with a bare `RegexField(r"^\d{4}/\d{2}$")`, so a format-valid but unconvertible label like `9999/99` passed validation and then raised `ValueError: Date out of range` inside `fiscal_year_gregorian_range()` in the selector — a 500 for a caller mistake. Found by the 2026-08-17 pre-production security audit (finding S6-related, OWASP A04).
**Root cause:** The regex checks shape, not convertibility; only `dashboards` round-tripped the actual conversion at validation time.
**Changed files:** `serializers.py`, `docs/API.md`, `tests/test_views.py` (shared validator added in `core/validators.py`)
**Fix summary:** Replaced the `RegexField` with a `CharField` using the shared `core.validators.validate_fiscal_year_label`, which round-trips `fiscal_year_gregorian_range` and rejects anything the selector would choke on.
**Contract impact:** `API.md` §1.1 → 1.2.1. Out-of-range labels are now `400 VALIDATION_ERROR` (previously 500). Valid labels behave identically.
**Tests added/updated:** `ClientListFilterValidationTests` — `9999/99` asserts 400 with `fiscal_year` in `error.details`; `2081/82` asserts 200.
**Notes for future AI:** Validate convertible values by converting them, not by pattern-matching their shape — `core.validators.validate_fiscal_year_label` is the shared rule for every `?fiscal_year=` filter.
