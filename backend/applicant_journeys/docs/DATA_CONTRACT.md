# Data Contract — Applicant Journeys

**Owner app:** `applicant_journeys`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-23
**Purpose:** Owns one overseas-study objective pursued by one applicant — destination, level, field, intake, financial preferences, stage, deferment, closure, and outcome. It does **not** own the person (`applicants`), the enquiry that preceded them (`leads`), offers, documents, or institution data. It owns no history table — a journey's history is the central `audit` log filtered to that journey.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial contract — one model, nine-stage lifecycle |

---

## Deliberate Deviations

- **Institution and program are free text, not nullable FKs.** `concepts/applicant.txt` said the FKs "can remain nullable until the institutions module exists," but a nullable FK still requires a target table and there is nothing to point at. `target_institution_name` and `target_program_name` are `CharField`s. Swapping in real references later is an additive migration plus a data backfill — see Known limitations below.
- **No history table**, for the same reason as `leads` and `applicants`: `audit` already provides an immutable append-only log and §4 forbids duplicating it.
- **`StudyLevel` is imported from `core.constants`**, not defined here. It is shared with `leads` (and later `education`), and §3 forbids duplicating an enum across apps. Defining it in `leads` and importing it here would invert the dependency — journeys must not depend on leads.

---

## 1. ApplicantJourney

**Purpose:** One study objective. A person is not the same thing as a plan; someone may pursue Australia, have it fall through, and try Canada two years later — two journeys, one applicant.
**Table:** `applicant_journeys_applicantjourney`
**`stage` choices:** `planning`, `profile_building`, `shortlisting`, `applying`, `offer_stage`, `visa_stage`, `completed`, `closed`, `deferred`
**`outcome` choices:** `successful`, `withdrawn`, `rejected`, `not_qualified`, `cancelled`, `other` (blank until closed)
**`creation_source` choices:** `lead_conversion`, `manual`
**`study_level` choices:** `school`, `certificate`, `diploma`, `bachelors`, `postgraduate_diploma`, `masters`, `phd`, `other`
**`stage_before_terminal` choices:** same set as `stage` (blank unless currently terminal)

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → applicants.Applicant | Yes | No | No | The person pursuing this objective (`PROTECT`). Immutable — never transferred |
| target_country | CharField(100) | No | No | No | One country per journey |
| target_institution_name | CharField(255) | No | No | No | Free text until the institutions module exists |
| target_program_name | CharField(255) | No | No | No | Free text, same reason |
| study_level | CharField(30) | No | No | No | Blank when unknown |
| field_of_study | CharField(150) | No | No | No | |
| preferred_intake | CharField(50) | No | No | No | Free text, e.g. "Fall 2026" |
| budget_amount | Decimal(12,2) | No | Yes | No | `DecimalField`, never a float |
| budget_currency | CharField(3) | No | No | No | ISO 4217, upper-cased on write |
| scholarship_interest | Boolean | No | No | No | |
| notes | TextField | No | No | No | Also carries interest data that had no column at conversion |
| stage | CharField(30) | No | No | No | Defaults to `planning`; indexed |
| creation_source | CharField(20) | Yes | No | Yes | Set by the service. Immutable |
| created_by | FK → authenticate.User | Yes | No | Yes | Who created it (`PROTECT`). Immutable |
| deferred_at | DateTime | No | Yes | No | When the journey was paused |
| deferred_to_intake | CharField(50) | Conditional | No | No | Mandatory while `stage = deferred` |
| deferment_reason | TextField | No | No | No | Unicode-normalized |
| deferred_by | FK → authenticate.User | No | Yes | No | Who deferred it (`SET_NULL`) |
| outcome | CharField(20) | Conditional | No | No | Mandatory while `stage` is `completed` or `closed` |
| closure_reason | TextField | Conditional | No | No | Required when `outcome = other`; Unicode-normalized |
| closed_at | DateTime | No | Yes | No | When it ended |
| closed_by | FK → authenticate.User | No | Yes | No | Who closed it (`SET_NULL`) |
| stage_before_terminal | CharField(30) | No | No | Yes | Stage held immediately before closure or deferment |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- `applicant` is required at creation and is **immutable** — the update serializer drops the field, because a journey belongs to exactly one applicant and is never transferred.
- Nothing else is required. A journey often begins as little more than "Australia, sometime next year."
- Every user-entered text field is Unicode-normalized on write (§39.2); `budget_currency` is upper-cased.
- `budget_amount` must be ≥ 0.
- `stage` is **not** writable through the update endpoint. It moves only via the stage, defer, close, and reopen actions.
- `stage` may reach `deferred` only through the defer action (which requires `deferred_to_intake`), and `completed`/`closed` only through the close action (which requires an `outcome`). Selecting any of the three from the stage dropdown raises `JOURNEYS_STAGE_INVALID_TRANSITION`.
- Closing with `outcome = successful` sets `stage = completed`; every other outcome sets `stage = closed`. This keeps "how did it end" one recorded fact rather than something inferred from where the journey stopped.
- Closing with `outcome = other` requires a `closure_reason` — otherwise `JOURNEYS_OUTCOME_DETAIL_REQUIRED`.
- While `stage` is terminal or deferred, no stage movement, deferment, or closure is permitted until the journey is reopened — otherwise `JOURNEYS_STAGE_NOT_EDITABLE`.
- Reopening clears **all** deferment and closure fields but never erases the audit events recording them.
- A journey's stage never changes the applicant's status, and archiving an applicant never closes their journeys.

**Indexes:**
- `journey_applicant_recent_idx` — `(applicant, -created_at)`. Supports the per-person journeys panel.
- `journey_stage_recent_idx` — `(stage, -created_at)`. Supports the operational worklist, e.g. "everything at Offer Stage."
- `stage` additionally carries `db_index=True`.

**Soft Delete:** N/A — journeys are never deleted. A journey that should not have existed is closed with the `cancelled` outcome; the record and its history remain. There is no delete endpoint and no archive flag.

**Example:**
```json
{
  "id": "3f4e5d6c-7b8a-9012-3456-789abcdef012",
  "applicant": {
    "id": "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5",
    "full_name_np": "राम श्रेष्ठ",
    "full_name_en": "Ram Shrestha",
    "status": "active"
  },
  "target_country": "Australia",
  "target_institution_name": "University of Melbourne",
  "target_program_name": "MSc Computer Science",
  "study_level": "masters",
  "field_of_study": "Computer Science",
  "preferred_intake": "Fall 2026",
  "budget_amount": "2500000.00",
  "budget_currency": "NPR",
  "scholarship_interest": true,
  "notes": "Prefers Melbourne.",
  "stage": "offer_stage",
  "creation_source": "lead_conversion",
  "created_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "adminuser", "display_name": "Adminuser" },
  "outcome": "",
  "closure_reason": "",
  "closed_at": null,
  "closed_by": null,
  "deferred_at": null,
  "deferred_to_intake": "",
  "deferment_reason": "",
  "deferred_by": null,
  "stage_before_terminal": "",
  "created_at": "2026-07-23T05:00:00Z",
  "updated_at": "2026-07-23T07:00:00Z"
}
```

**Cross-App Dependencies:**
- `applicants.Applicant` — one `PROTECT` FK. Model-level reference only, per §4. An applicant with any journey cannot be removed.
- `authenticate.User` — three FKs (`created_by`, `closed_by`, `deferred_by`).
- `core.constants.StudyLevel` — shared enum, not a duplicate.
- `audit` — runtime service/selector dependency for history.
- **Inbound:** `leads.Lead.converted_journey` points here, and `leads` calls `applicant_journeys.services.create_journey` at conversion. This app does **not** reference `leads`.

**Security Notes:** Journeys are shared, exactly as applicants are — any Admin or Lead Manager may read and write any journey. Superadmin is denied. Unlike `applicants`, **creation is not Admin-restricted**: adding a second objective for an existing client is ordinary operational work, not an entry decision. See `SECURITY.md` §1.

---

## 2. Journey history (no table — read model)

A journey's history is `audit.AuditEvent` filtered to `app_label="applicant_journeys"`, `entity_type="applicant_journey"`, `entity_id=<id>`, newest first.

| `action` | Written when | Notable payload |
|---|---|---|
| `journey_created` | A journey is recorded | `metadata.creation_source`, `metadata.applicant_id` |
| `journey_updated` | Objective fields are corrected | `changes` per field |
| `journey_stage_changed` | Stage moved between active stages | `changes.stage = {from, to}` |
| `journey_deferred` | Paused to a later intake | `metadata.deferred_to_intake`, `changes.stage` |
| `journey_closed` | Ended with an outcome | `reason` = outcome, `metadata.outcome`, `changes.stage` |
| `journey_reopened` | Returned to active work | `changes.stage` |

**Security Notes:** No full record dumps enter an audit payload (§17). Free text — notes, closure and deferment reasons — is stored on the journey but not copied into events.

---

## Known limitations

- **Institution and program are unvalidated free text.** Two staff members will spell the same university differently, and nothing prevents it. When the `institutions` module lands, these become references and existing values need migrating — automatically matched or reviewed by hand is an open question in `concepts/applicant_journeys.txt`.
- **`preferred_intake` and `deferred_to_intake` are free text** for the same reason; there is no intake catalogue yet.
- **Nothing prevents two open journeys for the same country and intake.** V1 allows it deliberately, but it may indicate a data-entry error rather than a real second objective.
