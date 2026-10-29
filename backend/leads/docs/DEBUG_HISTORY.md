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

---

## 2026-10-29 — Conversion stranded a lead's notes on the frozen lead

**Endpoint/module:** `POST /api/v1/leads/<lead_id>/convert/` — `leads.services.convert_lead`
**Problem:** After conversion, staff work on the applicant, but the notes written during the enquiry stayed on the lead, which nobody opens again. The applicant file started with no notes, and the frontend could not show the enquiry → applicant story in one feed (frontend `updates.md` §2.4).
**Root cause:** Notes existed only on leads (`LeadNote`); applicants had no notes at all, so conversion had nowhere to put them and copied nothing.
**Changed files:** `leads/services.py` (`convert_lead`, note write guard), `leads/selectors.py` (`get_lead_note_exports`), `applicants/models.py` (`ApplicantNote`), `applicants/services.py` (`import_lead_notes`), migrations `leads/0007`, `applicants/0006`
**Fix summary:** Applicants gained a notes resource, and conversion now copies the lead's live notes into it in the same transaction — same category, body, author, and `noted_at`, the original `created_at`, and `source_lead_id`. The lead keeps its notes, read-only from then on, so there is one place to keep writing.
**Contract impact:** Additive. `leads.lead.convert` → 1.1.0 with a new dependency on `applicants.note.create`. Note writes on a converted lead now return 409 `LEADS_LEAD_ALREADY_CONVERTED` (previously allowed).
**Tests added/updated:** `leads/tests/test_notes_and_soft_delete.py::TestConvertedLeadNotes`, `applicants/tests/test_notes_and_restore.py::test_import_keeps_original_creation_time`.
**Notes for future AI:** `bulk_create` honours `auto_now_add`, so copied rows get the conversion time as `created_at` unless it is restored afterwards with a queryset `update` — and `is_backdated` is computed from `created_at`, so getting this wrong silently marks every carried note as backdated.

