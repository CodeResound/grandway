"""The canonical template slug list, transcribed from the frontend contract.

**Provenance.** Every entry below comes from ``frontend_data-contract.md``
section "DocumentType (42 slugs)", as supplied by the project owner on
2026-07-24. That file is the frontend's own contract and is **not** in this
repository — it lives with the frontend, where the templates themselves are
code. This module is a transcription, not a source of truth: if the frontend
adds a bank partner, this list is stale until someone updates it and re-runs
``seed_document_templates``.

**The heading says 42; the list contains 53.** Counted by family:

* student — 4
* woda — 11
* lor — 11
* moi — 5
* bank_statement — 11, bank_certificate — 11 (11 institutions × two documents)

4 + 11 + 11 + 5 + 22 = **53**. The "42" in that heading is wrong, and the number
propagated into this backend's own documentation ("42 template shapes") when
``documents`` shipped. Recorded here rather than silently corrected so the
discrepancy can be checked against the real template set — if 42 is right, this
list contains eleven slugs the frontend cannot render.

**Labels are inferred from the slug**, since the frontend contract carries none.
They are a starting point an Admin is expected to correct — which is exactly why
the seed command never overwrites a label on re-run.
"""

from __future__ import annotations

from typing import Any

from documents.constants import DocumentFamily

#: The eleven bank partners, each of which has both a statement and a
#: certificate template. Slug order matches the frontend contract's listing.
BANK_INSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("bigyalaxmi", "Bigyalaxmi"),
    ("birendranagar", "Birendranagar"),
    ("himchuli", "Himchuli"),
    ("janautthan", "Janautthan"),
    ("karnali", "Karnali"),
    ("mata-bageshwori", "Mata Bageshwori"),
    ("narayan", "Narayan"),
    ("shahabhagi", "Shahabhagi"),
    ("sumnima", "Sumnima"),
    ("tribeni", "Tribeni"),
    ("vyas", "Vyas"),
)

#: Non-bank templates as ``(key, family, label)``. The bank families are built
#: from ``BANK_INSTITUTIONS`` below rather than written out twice.
_FIXED_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    # --- student (4) ---
    ("student-certificate", DocumentFamily.STUDENT, "Student Certificate"),
    ("student-cv", DocumentFamily.STUDENT, "Student CV"),
    ("student-cv-standard", DocumentFamily.STUDENT, "Student CV — Standard"),
    ("student-cv-extended", DocumentFamily.STUDENT, "Student CV — Extended"),
    # --- woda (11) ---
    ("woda-address", DocumentFamily.WODA, "Address Declaration"),
    ("woda-dob", DocumentFamily.WODA, "Date of Birth Declaration"),
    ("woda-fiscal", DocumentFamily.WODA, "Fiscal Declaration"),
    ("woda-income", DocumentFamily.WODA, "Income Declaration"),
    ("woda-migration", DocumentFamily.WODA, "Migration Declaration"),
    ("woda-occupation", DocumentFamily.WODA, "Occupation Declaration"),
    ("woda-relationship", DocumentFamily.WODA, "Relationship Declaration"),
    ("woda-surname", DocumentFamily.WODA, "Surname Declaration"),
    ("woda-tax-clearance", DocumentFamily.WODA, "Tax Clearance Declaration"),
    ("woda-agriculture-income", DocumentFamily.WODA, "Agriculture Income Declaration"),
    ("woda-affidavit-financial", DocumentFamily.WODA, "Financial Affidavit"),
    # --- lor (11) ---
    ("lor-janajagriti", DocumentFamily.LOR, "Janajagriti"),
    ("lor-bageshwari-chief", DocumentFamily.LOR, "Bageshwari — Chief"),
    ("lor-bageshwari-hod", DocumentFamily.LOR, "Bageshwari — Head of Department"),
    ("lor-shiva", DocumentFamily.LOR, "Shiva"),
    ("lor-kcmit", DocumentFamily.LOR, "KCMIT"),
    ("lor-tri-chandra", DocumentFamily.LOR, "Tri-Chandra"),
    ("lor-monastic", DocumentFamily.LOR, "Monastic"),
    ("lor-om-health", DocumentFamily.LOR, "Om Health"),
    ("lor-atlantic", DocumentFamily.LOR, "Atlantic"),
    ("lor-model-technical", DocumentFamily.LOR, "Model Technical"),
    ("lor-nepalgunj", DocumentFamily.LOR, "Nepalgunj"),
    # --- moi (5) ---
    ("moi-global-college", DocumentFamily.MOI, "Global College"),
    ("moi-janajagriti", DocumentFamily.MOI, "Janajagriti"),
    ("moi-vinayak", DocumentFamily.MOI, "Vinayak"),
    ("moi-reliance", DocumentFamily.MOI, "Reliance"),
    ("moi-bheri-nursing", DocumentFamily.MOI, "Bheri Nursing"),
)


def build_seed_rows() -> list[dict[str, Any]]:
    """Every template slug, in a stable order, with a derived display position.

    ``display_order`` is assigned per family in listing order, so a picker that
    sorts by it reproduces the frontend contract's own grouping rather than an
    alphabetical shuffle. Deterministic — two runs produce identical rows.
    """
    rows: list[dict[str, Any]] = []
    per_family_counter: dict[str, int] = {}

    def _append(key: str, family: str, label: str) -> None:
        position = per_family_counter.get(family, 0)
        per_family_counter[family] = position + 1
        rows.append({"key": key, "family": family, "label": label, "display_order": position})

    for key, family, label in _FIXED_TEMPLATES:
        _append(key, family, label)

    # The bank families share a prefix and are told apart by suffix — the rule
    # ``documents`` enforces and this app borrows. Statements first, then
    # certificates, so each family's display order is self-contained.
    for slug, name in BANK_INSTITUTIONS:
        _append(f"bank-{slug}-statement", DocumentFamily.BANK_STATEMENT, f"{name} Statement")
    for slug, name in BANK_INSTITUTIONS:
        _append(f"bank-{slug}-certificate", DocumentFamily.BANK_CERTIFICATE, f"{name} Certificate")

    return rows


#: Row count this module is expected to produce. Asserted by the test suite, so
#: a slug accidentally dropped or duplicated during a future edit fails loudly
#: rather than silently shrinking the catalogue.
EXPECTED_TEMPLATE_COUNT = 53
