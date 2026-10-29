# Data Contract — Leads

**Owner app:** `leads`
**Version:** 1.5.0
**Status:** Active
**Created:** 2026-07-23
**Purpose:** Owns the enquiry record and everything that happens to it before conversion — identity, contact numbers, source attribution, preliminary study interest, stage, manual follow-up, notes, and loss/reopen state. It does **not** own the applicant, the applicant journey, or any post-conversion data; those belong to the `applicants` and `applicant_journeys` apps. It owns no history table either — a lead's chronological history is the central `audit` log filtered to that lead.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial contract — six models, lead lifecycle without conversion |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | Two search indexes added (no column change): GIN trigram on `Lead.email` and B-tree on `LeadContactNumber.number`, both supporting the widened `search_leads` |
| 1.2.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (`full_name`, source/loss-reason `name`). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |
| 1.3.0 | 2026-08-02 | AI (Claude Opus 5) | One search index added (no column change): GIN trigram on `LeadContactNumber.number`. Corrects `1.1.0` — the B-tree it added cannot serve the leading-wildcard `icontains` that `search_leads` issues, so phone search was scanning. Added for the `search` app's lead bucket |
| 1.4.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Schema change** (migration `0007_notes_categories_and_lead_soft_delete`): `Lead` soft delete (`deleted_at` indexed, `deleted_by`, `delete_reason`); `LeadNote` gains `category`, `noted_at` (backfilled from `created_at`), `updated_by`, `deleted_at`, `deleted_by`, and the `(lead, -noted_at)` index. Notes are no longer append-only; soft delete documented for both models |
| 1.5.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Schema change** (migration `0008_qualification_and_language_certificates`): study interest gains `highest_qualification_level`, `academic_score`/`_type`, `pass_year`/`_calendar`; new `LeadLanguageCertificate` (§5a). Additive — `highest_qualification` unchanged |

---

## Deliberate Deviations

`concepts/leads.txt` is the grounding document; two of its provisions are implemented differently than a literal reading suggests, and one is deferred.

- **A separate "lead history" entity was not created**, even though the concept asks for a chronological history of lead actions. The central `audit` app already provides an immutable, append-only event log with actor/action/time/changes, and §4 forbids duplicating another app's storage. `Lead` history is `audit.AuditEvent` filtered to `app_label="leads"`, `entity_type="lead"`, `entity_id=<lead id>`. This satisfies "history entries should not be silently rewritten or removed" more strongly than an app-local table would, since `AuditEvent` blocks deletion at the model layer.
- **Loss and conversion state are denormalized onto `Lead`** rather than stored as separate event rows. This mirrors the `core.policy_engine` lifecycle pattern (§35 item 15): current-state fields make "which leads are lost and why" a plain field read, while the audit log remains the authoritative event history. Reopening clears the loss fields exactly as `restore_endpoint()` clears its lifecycle fields.
- **Conversion shipped in Phase 4** (migration `0003`), once `applicants` and `applicant_journeys` existed. As planned, the FK links were a purely additive migration — `LeadStage.CONVERTED` had been in the enum since `0001`, so no destructive change was ever needed.

---

## 1. LeadSource

**Purpose:** How a lead found the consultancy. Admin-configurable rather than hardcoded, so the consultancy can add channels without a deployment.
**Table:** `leads_leadsource`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| code | CharField(50) | Yes | No | No | ASCII system identifier, unique, lowercased on write |
| name | CharField(150) | No | No | No | English name — an independent identity, not a translation |
| requires_detail | Boolean | No | No | No | When true, a lead choosing this source must supply `source_detail` |
| is_active | Boolean | No | No | No | Deactivated entries are hidden from pickers but never deleted |
| display_order | PositiveInteger | No | No | No | Sort position in the picker |
| created_at | DateTime | — | No | Yes | Set on insert |
| updated_at | DateTime | — | No | Yes | Set on every save |

**Validation Rules:**
- `code` matches `^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$` — ASCII only, never Devanagari (§39.7).
- `code` is unique across all sources; a duplicate raises `LEADS_SOURCE_CODE_TAKEN`.
- `code` is immutable after creation — the update serializer drops the field.
- `name` and `name` are Unicode-normalized (NFC) on write (§39.2).
- `name` is Unicode-normalized on write (§39.2), in the service layer as well as the serializer.

**Indexes:** `code` (unique), `is_active`

**Soft Delete:** N/A — sources are deactivated via `is_active`, not deleted. `Lead.source` is `PROTECT`, so a source referenced by any lead cannot be removed even at the database level. There is no delete endpoint.

**Example:**
```json
{
  "id": "0f1c2b3a-4d5e-6f70-8192-a3b4c5d6e7f8",
  "code": "walk_in",
  "name": "Walk-in",
  "requires_detail": false,
  "is_active": true,
  "display_order": 1,
  "created_at": "2026-07-23T09:15:00Z",
  "updated_at": "2026-07-23T09:15:00Z"
}
```

---

## 2. LossReason

**Purpose:** Why a lead did not proceed. Recorded whenever a lead is marked lost; a reason is always mandatory.
**Table:** `leads_lossreason`

Field table, validation rules, indexes, and soft-delete contract are **identical to §1** — both models inherit the same abstract `ReferenceEntry` shape, so they cannot drift apart. The differences are semantic only:

- `requires_detail` is typically set on the `other` entry, forcing an explanation when it is chosen (`LEADS_LOSS_DETAIL_REQUIRED`).
- `Lead.lost_reason` is `PROTECT` and nullable — a reason referenced by any lost lead cannot be removed.
- A duplicate `code` raises `LEADS_LOSS_REASON_CODE_TAKEN`.

**Soft Delete:** N/A — same contract as §1.

**Example:**
```json
{
  "id": "1a2b3c4d-5e6f-7081-92a3-b4c5d6e7f809",
  "code": "no_response",
  "name": "No response",
  "requires_detail": false,
  "is_active": true,
  "display_order": 1,
  "created_at": "2026-07-23T09:15:00Z",
  "updated_at": "2026-07-23T09:15:00Z"
}
```

---

## 3. Lead

**Purpose:** A person who has shown interest in the consultancy but has not yet entered the applicant lifecycle. Owned permanently by the Lead Manager who created it — Grandway has no lead pools, assignment, transfer, or reassignment.
**Table:** `leads_lead`
**`stage` choices:** `new`, `contact_attempted`, `contacted`, `counselling`, `follow_up`, `ready_for_conversion`, `converted`, `lost`
**`stage_before_loss` choices:** same set as `stage` (blank when the lead has never been lost)

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| full_name | CharField(255) | No | No | No | Roman name — an independent identity, not a translation |
| email | EmailField | No | No | No | Single address; multiple emails are deliberately not supported |
| address | TextField | No | No | No | Free text, Unicode-normalized |
| source | FK → LeadSource | Yes | No | No | How the lead reached the consultancy (`PROTECT`) |
| source_detail | CharField(255) | Conditional | No | No | Required when `source.requires_detail` is true |
| stage | CharField(30) | No | No | No | Current lead stage; defaults to `new` |
| created_by | FK → authenticate.User | Yes | No | No | The owning Lead Manager (`PROTECT`). Immutable — ownership never moves |
| last_followed_up_at | DateTime | No | Yes | No | When manual follow-up last occurred |
| last_followed_up_by | FK → authenticate.User | No | Yes | No | Who recorded that follow-up (`SET_NULL`) |
| lost_reason | FK → LossReason | Conditional | Yes | No | Mandatory while `stage = lost` (`PROTECT`) |
| lost_detail | TextField | Conditional | No | No | Required when `lost_reason.requires_detail` is true |
| lost_at | DateTime | No | Yes | No | When the lead was closed |
| lost_by | FK → authenticate.User | No | Yes | No | Who closed it (`SET_NULL`) |
| stage_before_loss | CharField(30) | No | No | Yes | Stage the lead held immediately before closure |
| converted_applicant | OneToOne → applicants.Applicant | No | Yes | Yes | The applicant this lead became (`PROTECT`). Set only by conversion |
| converted_journey | FK → applicant_journeys.ApplicantJourney | No | Yes | Yes | The initial journey created at conversion (`PROTECT`) |
| converted_at | DateTime | No | Yes | Yes | When conversion occurred |
| converted_by | FK → authenticate.User | No | Yes | Yes | The Admin who converted (`SET_NULL`) |
| deleted_at | DateTime | No | Yes | Yes | Set by soft delete, cleared by restore; indexed — every lead list filters on it |
| deleted_by | FK → authenticate.User | No | Yes | Yes | The Admin who deleted it (`SET_NULL`) |
| delete_reason | CharField(500) | Conditional | No | No | Required to delete; cleared on restore |
| created_at | DateTime | — | No | Yes | Set on insert |
| updated_at | DateTime | — | No | Yes | Set on every save |

**Validation Rules:**
- `full_name` is required and Unicode-normalized on write (§39.2).
- Every user-entered text field (`full_name`, `full_name`, `address`, `source_detail`) is Unicode-normalized on write (§39.2).
- The chosen `source` must be active — an inactive source raises `LEADS_SOURCE_INACTIVE`.
- `source_detail` is mandatory when the chosen source has `requires_detail` — otherwise `LEADS_SOURCE_DETAIL_REQUIRED`.
- A lead must always have at least one `LeadContactNumber` — otherwise `LEADS_CONTACT_REQUIRED`.
- `stage` is **not** writable through the update endpoint. It moves only via the stage-change, mark-lost, reopen, and (Phase 4) convert actions.
- `stage` may be set to `lost` only through mark-lost, and to `converted` only through conversion. Selecting either from the stage dropdown raises `LEADS_STAGE_INVALID_TRANSITION`.
- While `stage` is `lost` or `converted`, no stage movement or follow-up is permitted until the lead is reopened — otherwise `LEADS_STAGE_NOT_EDITABLE`.
- Reopening clears all six loss fields but never touches any `converted_*` field, so a reopened converted lead stays permanently linked to its applicant.
- `converted_applicant` is a **`OneToOneField`**, which puts "never create a second applicant from one lead" in the database rather than in service logic — the strongest available form of the idempotency §15 requires. Two leads cannot point at one applicant, and one lead cannot point at two.
- Conversion requires **Admin** authority and an **active** stage. A lost or already-converted lead must be reopened first (`LEADS_CONVERSION_NOT_READY`). Conversion also copies the lead's live notes to the applicant (`applicants.services.import_lead_notes`).
- No write is accepted on a soft-deleted lead (`LEADS_LEAD_DELETED`); a converted lead cannot be deleted (`LEADS_LEAD_ALREADY_CONVERTED`); `delete_reason` must be non-blank after normalization.
- `leads` owns both conversion links, so `applicants` and `applicant_journeys` carry no dependency on this app. The reverse direction is available as `applicant.originating_lead`.

**Indexes:**
- `lead_owner_recent_idx` — `(created_by, -created_at)`. Supports the default list view, a Lead Manager's own leads newest first.
- `lead_stage_recent_idx` — `(stage, -created_at)`. Supports stage filters and funnel views.
- `lead_name_trgm_idx` — GIN trigram indexes (`gin_trgm_ops`) on the three name fields. `search_leads` runs a leading-wildcard `icontains` across all three, which a B-tree index cannot serve. Created in migration `0002`, which also enables the `pg_trgm` extension.
- `lead_email_trgm_idx` — GIN trigram on `email`, supporting the same leading-wildcard `icontains` now that `search_leads` matches the email as well (migration `0004_search_indexes`).
- `stage` additionally carries `db_index=True` for single-column stage lookups.

**Soft Delete:** Yes, since 2026-10-29 (frontend `updates.md` §3.1). `deleted_at` / `deleted_by` / `delete_reason`, set by `DELETE /api/v1/leads/<id>/` (Admin, reason required) and cleared by `POST /restore/` (Admin). A deleted lead is excluded from every lead queryset by `get_leads_for_actor` — lists, global search, dashboard figures — is visible to an Admin only (by id or `?deleted=true`), and rejects every write with `LEADS_LEAD_DELETED`. Nothing is erased: the row, its notes, contact numbers, interest, and history stay, and the Django admin cannot hard-delete a lead. A **converted** lead cannot be deleted — it is an applicant's origin record. Deletion is distinct from `lost`: lost is an outcome that stays reportable; deleted means the lead should never have counted.

**Example:**
```json
{
  "id": "9d8c7b6a-5e4f-3021-a1b2-c3d4e5f60718",
  "full_name": "Ram Shrestha",
  "email": "ram@example.com",
  "address": "Lalitpur",
  "source": { "id": "0f1c2b3a-4d5e-6f70-8192-a3b4c5d6e7f8", "code": "walk_in", "name": "Walk-in" },
  "source_detail": "",
  "stage": "counselling",
  "created_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "leadmgr", "display_name": "Leadmgr" },
  "last_followed_up_at": "2026-07-23T04:00:00Z",
  "last_followed_up_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name": "Shrawan",
    "display": "2083 Shrawan 8"
  },
  "lost_reason": null,
  "lost_detail": "",
  "lost_at": null,
  "stage_before_loss": "",
  "converted_at": null,
  "created_at": "2026-07-20T05:00:00Z",
  "updated_at": "2026-07-23T04:00:00Z"
}
```

**Cross-App Dependencies:**
- `authenticate.User` — five FKs (`created_by`, `last_followed_up_by`, `lost_by`, `converted_by`, and `LeadNote.author`). Model-level reference only, per §4.
- `audit` — runtime service/selector dependency, not a model reference. Every mutation calls `audit.services.record_event`; the history endpoint reads `audit.selectors.get_events_for_entity` and renders `audit.serializers.AuditEventHistorySerializer`. Recorded in `INTEGRATION.md` §2.
- `applicants` — `converted_applicant` is a `OneToOneField` here, and `leads.services.convert_lead` calls `applicants.services.create_applicant`. Both directions of the coupling originate in this app; `applicants` references nothing here.
- `applicant_journeys` — `converted_journey` FK plus a call to `applicant_journeys.services.create_journey` at conversion. Same one-directional arrangement.

**Security Notes:** `Lead` rows are owner-scoped. A Lead Manager may read and write only rows where `created_by` is themselves; an Admin sees all; a Superadmin is denied entirely. Scoping is applied in `selectors.get_leads_for_actor` at the queryset level, never as a post-fetch filter. See `SECURITY.md` §1.

---

## 4. LeadContactNumber

**Purpose:** One reachable number for a lead. A person may give more than one usable number, so this is a collection while `Lead.email` stays a single field.
**Table:** `leads_leadcontactnumber`
**`label` choices:** `mobile`, `home`, `work`, `whatsapp`, `viber`, `other`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| lead | FK → Lead | Yes | No | No | Owning lead (`CASCADE`) |
| number | CharField(32) | Yes | No | No | The number as entered, trimmed |
| label | CharField(20) | No | No | No | What kind of number it is; defaults to `mobile` |
| is_primary | Boolean | No | No | No | Preferred number; sorts first |
| created_at | DateTime | — | No | Yes | Set on insert |
| updated_at | DateTime | — | No | Yes | Set on every save |

**Validation Rules:**
- `number` matches `^\+?[0-9][0-9 ()\-]{4,31}$` — digits, spaces, and `+ - ( )` only. Deliberately permissive so Nepali mobiles, landlines with area codes, and international `+` forms all fit.
- `(lead, number)` is unique — the same number cannot be listed twice on one lead.
- Managed **nested inside the lead payload**; there are no standalone contact-number endpoints. Supplying `contact_numbers` on create or update replaces the whole set, so the payload is always the complete list the lead should end up with.

**Indexes:**
- `uniq_lead_contact_number` — unique constraint on `(lead, number)`
- `lead_contact_number_idx` — B-tree on `number` alone. The unique constraint's leading column is the lead, so it cannot serve `search_leads`, which knows the number and not the lead (migration `0004_search_indexes`).
- `lead_contact_num_trgm_idx` — GIN `gin_trgm_ops` on `number`. The B-tree above serves equality and prefix lookups but **cannot** serve the one `search_leads` actually issues: `number__icontains` has a leading wildcard, and a B-tree has no way in. Until this index existed, every phone search — the most common way a lead is found, since a lead is usually a number in a call log before anyone agrees how to spell the name — was a sequential scan. Both indexes are kept; the B-tree stays cheaper for exact matching (migration `0006_trigram_search_indexes`).

**Soft Delete:** N/A — contact numbers are replaced wholesale on update and cascade-deleted with their lead (which itself is never deleted). Removal of a number is a correction, not a lifecycle event, so no history of removed numbers is kept beyond the `lead_contact_changed` audit event.

**Example:**
```json
{ "id": "c1c2c3c4-0000-1111-2222-333344445555", "number": "9800000000", "label": "mobile", "is_primary": true }
```

---

## 5. LeadStudyInterest

**Purpose:** What the person is considering, as far as it is known during follow-up. Preliminary and possibly incomplete — explicitly **not** an applicant journey. The authoritative journey is created only at conversion.
**Table:** `leads_leadstudyinterest`
**`study_level` choices:** `school`, `certificate`, `diploma`, `bachelors`, `postgraduate_diploma`, `masters`, `phd`, `other`
**`language_test_status` choices:** `not_taken`, `preparing`, `booked`, `taken`, `not_required`
**`highest_qualification_level` choices:** `see`, `plus_two`, `diploma`, `bachelor`, `master`, `phd`, `other` — `core.constants.HighestQualification`, shared with `applicants.ApplicantEducation.level`
**`academic_score_type` choices:** `gpa`, `percentage` · **`pass_year_calendar` choices:** `bs`, `ad`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| lead | OneToOne → Lead | Yes | No | No | Owning lead (`CASCADE`) |
| interested_countries | JSONField | No | No | No | List of country names under consideration; defaults to `[]` |
| study_level | CharField(30) | No | No | No | Intended level; blank when unknown |
| field_of_study | CharField(150) | No | No | No | Preferred field or program |
| preferred_intake | CharField(50) | No | No | No | Free text at this stage, e.g. "Fall 2026" |
| budget_amount | Decimal(12,2) | No | Yes | No | Approximate budget. `DecimalField`, never a float |
| budget_currency | CharField(3) | No | No | No | ISO 4217 code, uppercased on write |
| scholarship_interest | Boolean | No | No | No | Whether scholarships are of interest |
| highest_qualification | CharField(150) | No | No | No | Free text: the programme or stream, e.g. "BBS", "Science" |
| highest_qualification_level | CharField(20) | No | No | No | Its level on the Nepali ladder (2026-10-29) |
| academic_score | Decimal(5,2) | Conditional | Yes | No | With `academic_score_type`; gpa 0–4, percentage 0–100 |
| academic_score_type | CharField(20) | Conditional | No | No | With `academic_score` |
| pass_year | PositiveSmallInteger | Conditional | Yes | No | With `pass_year_calendar`; BS 2000…this BS year+1, AD 1950…this year+1 |
| pass_year_calendar | CharField(2) | Conditional | No | No | With `pass_year` |
| language_test_status | CharField(20) | No | No | No | Where they stand on a language test |
| interest_notes | TextField | No | No | No | Anything else relevant |
| created_at | DateTime | — | No | Yes | Set on insert |
| updated_at | DateTime | — | No | Yes | Set on every save |

**Validation Rules:**
- Every field is optional — this record exists precisely to hold incomplete information.
- The whole record is optional too: a lead may have no `study_interest` row at all.
- Text fields (`field_of_study`, `highest_qualification`, `interest_notes`) are Unicode-normalized on write.
- `budget_amount` must be ≥ 0.
- `academic_score` ⇔ `academic_score_type`, `pass_year` ⇔ `pass_year_calendar`, judged on the record **after** a partial update (`services._assert_study_interest_valid`) → `LEADS_STUDY_INTEREST_INVALID` with `details.fields`.
- Managed nested inside the lead payload; supplying `study_interest` upserts the row (`update_or_create`), so a lead never accumulates more than one.

**Soft Delete:** N/A — the row is upserted in place and cascade-deleted with its lead. Superseded interest values are not versioned; the `lead_interest_changed` audit event records that a change occurred.

**Example:**
```json
{
  "interested_countries": ["Australia", "Canada"],
  "study_level": "masters",
  "field_of_study": "Computer Science",
  "preferred_intake": "Fall 2026",
  "budget_amount": "2500000.00",
  "budget_currency": "NPR",
  "scholarship_interest": true,
  "highest_qualification": "BSc CSIT",
  "highest_qualification_level": "bachelor",
  "academic_score": "3.45",
  "academic_score_type": "gpa",
  "pass_year": 2080,
  "pass_year_calendar": "bs",
  "language_test_status": "preparing",
  "interest_notes": "Prefers Melbourne."
}
```

---

## 5a. LeadLanguageCertificate

**Purpose:** A language-test result the enquirer reports. Becomes an `applicants.ApplicantLanguageTest` at conversion, field for field.
**Table:** `leads_leadlanguagecertificate`
**`test_type` choices:** `ielts`, `pte`, `toefl`, `duolingo`, `other` — `core.constants.LanguageTestType`, shared with `applicants`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| lead | FK → Lead | Yes | No | No | `CASCADE` (moot — a lead is never hard-deleted) |
| test_type | CharField(20) | Yes | No | No | |
| overall_score / listening_score / reading_score / writing_score / speaking_score | Decimal(5,1) | No | Yes | No | IELTS 0–9 (0.5 steps), PTE 10–90, TOEFL 0–120, Duolingo 10–160, other ≥0 |
| test_date | Date | No | Yes | No | Not in the future |
| certificate_number | CharField(100) | No | No | No | Normalized |
| expiry_date | Date | No | Yes | No | After `test_date` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:** `core.validators.language_test_errors` (shared with `applicants`, so conversion never copies a value one side rejects) → `LEADS_CERTIFICATE_INVALID` with `language_certificates[i].field`; at most 10 per lead → `LEADS_CERTIFICATE_LIMIT`. Managed nested: supplying `language_certificates` replaces the whole set.

**Indexes:** `leadcert_type_lead_idx` — `(test_type, lead)`, serving the `?language_test_type=` `Exists` filter.

**Soft Delete:** N/A — replaced wholesale with the lead's list; the audit event records the count, never scores.

**Example:**
```json
{
  "id": "2c3d4e5f-6071-4829-a3b4-c5d6e7f8091a",
  "test_type": "ielts", "overall_score": "7.0", "listening_score": null, "reading_score": null,
  "writing_score": null, "speaking_score": null, "test_date": "2025-03-01",
  "test_date_bs": { "year": 2081, "month": 11, "day": 17, "month_name": "Falgun", "display": "2081 Falgun 17" },
  "certificate_number": "", "expiry_date": null, "expiry_date_bs": null,
  "created_at": "2026-10-29T04:00:00Z", "updated_at": "2026-10-29T04:00:00Z"
}
```

**Cross-App Dependencies:** `core` (shared enum and validator). Copied to `applicants` at conversion through `applicants.services.import_lead_certificates`.

---

## 6. LeadNote

**Purpose:** A note on where a lead stands — general, or a record of an office visit — attributed to its author and dated to when it happened.
**Table:** `leads_leadnote`
**`category` choices:** `general`, `visit` — `core.constants.NoteCategory`, shared with `applicants.ApplicantNote` (§4: one enum, two apps, because notes cross at conversion)

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| lead | FK → Lead | Yes | No | No | Owning lead (`CASCADE` — moot, a lead is never hard-deleted) |
| category | CharField(20) | No | No | No | Defaults to `general` |
| body | TextField | Yes | No | No | Note content, Unicode-normalized; ≤10 000 characters (API) |
| noted_at | DateTime | No | No | No | When it happened, user-set and backdatable; defaults to now; indexed. Existing notes were backfilled with `created_at` (migration `0007`) |
| author | FK → authenticate.User | Yes | No | No | Who wrote it (`PROTECT`) |
| updated_by | FK → authenticate.User | No | Yes | Yes | Last editor (`SET_NULL`) |
| deleted_at | DateTime | No | Yes | Yes | Soft delete |
| deleted_by | FK → authenticate.User | No | Yes | Yes | Who deleted it (`SET_NULL`) |
| created_at | DateTime | — | No | Yes | When it was saved |
| updated_at | DateTime | — | No | Yes | Last save |

**Derived, read-only:** `noted_at_bs` (§39.4) and `is_backdated` — `created_at − noted_at > 15 min` (`core.validators.note_is_backdated`).

**Validation Rules:**
- `body` is required, Unicode-normalized, and non-blank after normalization.
- `noted_at` may not be later than now + 5 minutes (`core.validators.noted_at_is_in_future`) → `LEADS_NOTE_FUTURE_DATE`. No lower bound. A value without a UTC offset is read as Asia/Kathmandu.
- Only the **author or an Admin** may edit or delete a note → `LEADS_NOTE_FORBIDDEN`.
- No write while the lead is deleted (`LEADS_LEAD_DELETED`) or once it is converted (`LEADS_LEAD_ALREADY_CONVERTED`) — a converted lead's notes are copied to the applicant at conversion.
- Ordered by `-noted_at`, then `-created_at`.

**Indexes:** `leadnote_lead_noted_idx` — `(lead, -noted_at)`, the notes panel's default order. `noted_at` also carries `db_index=True`.

**Soft Delete:** Yes, since 2026-10-29 (previously append-only). `DELETE …/notes/<id>/` sets `deleted_at`/`deleted_by`; the note leaves every list and 404s, but the row and its body remain and the audit log records the deletion. There is no restore endpoint for a note. The Django admin is read-only for notes and blocks deletion. This is how "a Lead Manager may not delete lead history" (`concepts/leads.txt`) survives notes becoming correctable: nothing a user does erases a note.

**Example:**
```json
{
  "id": "e1e2e3e4-9999-8888-7777-666655554444",
  "category": "visit",
  "body": "Visited the office with her father. Wants Australia, needs IELTS.",
  "noted_at": "2026-07-22T09:30:00Z",
  "noted_at_bs": { "year": 2083, "month": 4, "day": 6, "month_name": "Shrawan", "display": "2083 Shrawan 6" },
  "is_backdated": true,
  "author": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "leadmgr", "display_name": "Leadmgr" },
  "updated_by": null,
  "created_at": "2026-07-23T04:05:00Z",
  "updated_at": "2026-07-23T04:05:00Z"
}
```

**Cross-App Dependencies:** `authenticate.User` via `author`, `updated_by`, `deleted_by` (FK references only). `core.constants.NoteCategory` and the note helpers in `core.validators` (shared with `applicants`). At conversion the live notes are handed to `applicants.services.import_lead_notes` as plain values (`selectors.get_lead_note_exports`) — `applicants` never receives a `LeadNote`.

---

## 7. Lead history (no table — read model)

**Purpose:** The chronological record of everything important that happened to a lead.

This app owns **no history table**. A lead's history is `audit.AuditEvent` filtered to `app_label="leads"`, `entity_type="lead"`, `entity_id=<lead id>`, newest first. `AuditEvent` is append-only and blocks deletion at the model layer, which satisfies "history entries should not be silently rewritten or removed" more strongly than an app-local table would.

Actions this app writes, using `audit.services.record_event`:

| `action` | Written when | Notable payload |
|---|---|---|
| `lead_created` | A lead is recorded | `metadata.source`, `metadata.stage` |
| `lead_updated` | Identity/contact/address fields are corrected | `changes` per field |
| `lead_source_changed` | The update changed the source | `changes.source` |
| `lead_contact_changed` | Contact numbers were replaced | `metadata.count` |
| `lead_interest_changed` | Study interest was upserted | — |
| `lead_stage_changed` | Stage moved between active stages | `changes.stage = {from, to}` |
| `lead_followup_recorded` | Manual follow-up was recorded | `metadata.followed_up_at` |
| `lead_marked_lost` | The lead was closed | `reason` = loss reason code, `changes.stage` |
| `lead_reopened` | A lost/converted lead returned to active work | `changes.stage`, `metadata.reopened_from_converted` |
| `lead_note_added` | A note was appended | `metadata.note_id` |
| `lead_converted` | The lead became an applicant | `changes.stage`, `metadata.applicant_id`, `metadata.journey_id` |
| `lead_applicant_created` | Written alongside the above | `metadata.applicant_id`, `metadata.journey_id` |

Reference-table changes are recorded with `entity_type` of `lead_source` or `loss_reason` and actions `lead_source_created` / `lead_source_updated` / `loss_reason_created` / `loss_reason_updated`. These are audit-only and do not appear in any lead's history pane.

**Cross-App Dependencies:** `audit` — write via `audit.services.record_event`, read via `audit.selectors.get_events_for_entity` and `audit.serializers.AuditEventHistorySerializer`. Runtime coupling; see `INTEGRATION.md` §2.

**Security Notes:** No secrets, passwords, tokens, or full record dumps are ever passed into an audit payload (§17). `changes` carries only the fields that moved, and `metadata` only small scalars.
