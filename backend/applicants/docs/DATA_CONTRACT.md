# Data Contract — Applicants

**Owner app:** `applicants`
**Version:** 1.7.0
**Status:** Active
**Created:** 2026-07-23
**Purpose:** Owns the permanent, authoritative identity of a person the consultancy works with — name, date of birth, contact numbers, addresses, passport, family, emergency contacts, and standing. It does **not** own study objectives (`applicant_journeys`), academic history (`education`, not built), test attempts (`test_scores`, not built), or any file. It owns no history table either — an applicant's history is the central `audit` log filtered to that applicant. It carries **no reference to the originating lead**: `leads.Lead` owns that link, so this app has no dependency on `leads`.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial contract — six models, shared (non-owner-scoped) access |
| 1.1.0 | 2026-07-24 | AI (Claude) | Documentation only — no schema change. Recorded the inbound nullable `documents.Document.applicant` FK and the access asymmetry it introduces: applicants are readable by any Admin or Lead Manager, their documents are Admin-only |
| 1.1.1 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. A photograph now has a home in `uploaded_files`; this model still holds no reference, and nothing marks a primary photograph |
| 1.2.0 | 2026-07-24 | AI (Claude Opus 4.8) | Three search indexes added (no column change): GIN trigram on `Applicant.email`, B-tree on `ApplicantContactNumber.number` and `PassportDetail.passport_number`. **Recorded the first outbound read of `applicant_journeys` from this app** — the list response projects a `destinations` array and three list filters resolve through the reverse `journeys` accessor. It is a reverse-accessor read, not an import, so the FK still runs one direction only; §8 documents the derived read model |
| 1.3.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (`full_name` on Applicant, FamilyMember, EmergencyContact). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |
| 1.4.0 | 2026-08-02 | AI (Claude Opus 5) | Two search indexes added (no column change): GIN trigram on `ApplicantContactNumber.number` and `PassportDetail.passport_number`. Corrects `1.2.0` — the B-trees it added cannot serve the leading-wildcard `icontains` that `search_applicants` issues. Added for the `search` app's applicant bucket |
| 1.5.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Schema change** (migration `0006_notes_and_status_before_archive`): `Applicant.status_before_archive`; new `ApplicantNote` table (§9). Restore is Admin-only; archived applicants' notes are read-only |
| 1.6.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Schema change** (migration `0007_education_language_tests_and_woda_fields`): `Applicant.citizenship_no`, `citizenship_issue_district`, `national_id_no`; `FamilyMember.citizenship_no` and the `grandfather`/`grandmother` relationships; new `ApplicantEducation` (§10) and `ApplicantLanguageTest` (§11) sub-records, folded in instead of separate `education`/`test_scores` apps; `applicant_updated` withholds the two identity numbers |
| 1.7.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Schema change** (migration `0008_applicant_assigned_to`): `Applicant.assigned_to`, a nullable `PROTECT` FK to `authenticate.User` — optional assignment that routes notifications only and never limits access. Additive, reversible, no backfill (existing applicants read as unassigned). New audit actions `applicant_assigned` / `applicant_unassigned`; `applicant_created` metadata gains `assigned_to`. New outbound call to `authenticate.selectors.get_active_user_by_id`; domain events via `core.events` |

---

## Deliberate Deviations

`concepts/applicants.txt` is the grounding document; three provisions are implemented differently than a literal reading suggests.

- **No history table.** The concept asks for a chronological history of applicant actions. The central `audit` app already provides an immutable append-only event log, and §4 forbids duplicating another app's storage. History is `audit.AuditEvent` filtered to `app_label="applicants"`, `entity_type="applicant"`, `entity_id=<id>`. Same decision as `leads`.
- **No photograph *field*.** The concept lists one, and this model still has no image column. **`uploaded_files` now exists** and holds a `PROTECT` foreign key to `Applicant`, so a photograph has a home — `POST /api/v1/files/` with `applicant=<id>`, `category=photograph`. Two things are still deliberately absent and both matter: this model has no pointer back, and **nothing marks one file as *the* photograph**. A caller filtering by category may get several and must pick one itself.
- **No `origin_lead` field.** The concept says the record notes "when applicable, the originating lead." Storing it here would make `applicants` depend on `leads`, which is wrong — an applicant may be created directly with no lead at all. `leads.Lead.converted_applicant` is a `OneToOneField` pointing this way, so the same fact is available through the reverse accessor `applicant.originating_lead` with no second column and no inverted dependency. The `OneToOne` additionally makes "two leads converting to one applicant" impossible at the database level.

---

## 1. Applicant

**Purpose:** The permanent record of a person. Answers "who is this person" and nothing else.
**Table:** `applicants_applicant`
**`status` choices:** `active`, `dormant`, `archived`
**`creation_source` choices:** `lead_conversion`, `direct_admin`
**`gender` choices:** `male`, `female`, `other`, `undisclosed`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| full_name | CharField(255) | No | No | No | Roman name — an independent identity, not a translation |
| date_of_birth | DateField | No | Yes | No | User-facing; exposed with a BS companion |
| gender | CharField(20) | No | No | No | Blank when undisclosed or unknown |
| nationality | CharField(100) | No | No | No | Free text |
| email | EmailField | No | No | No | Single address; multiple emails are deliberately unsupported |
| citizenship_no | CharField(50) | No | No | No | Nepali citizenship certificate number, as entered (normalized). Not format-checked — formats vary by district and era. Detail shape only |
| citizenship_issue_district | CharField(100) | No | No | No | District that issued the citizenship certificate |
| national_id_no | CharField(50) | No | No | No | National identity card number |
| status | CharField(20) | No | No | No | Standing with the consultancy; defaults to `active` |
| status_before_archive | CharField(20) | No | No | Yes | `active`/`dormant` held when archived, `""` otherwise; read and cleared by the Admin-only restore. Not in any response |
| creation_source | CharField(20) | Yes | No | Yes | Set by the service, never by a client. Immutable |
| created_by | FK → authenticate.User | Yes | No | Yes | The Admin who created it (`PROTECT`). Immutable |
| assigned_to | FK → authenticate.User | No | Yes | No | The staff member notified about this applicant (`PROTECT`, `related_name="assigned_applicants"`). `null` = unassigned. **Routing only — never limits who may read or edit.** Written only by `POST /assign/` and by lead conversion (the lead's owner). Exposed on both read shapes as UserBrief or `null` |
| created_at | DateTime | — | No | Yes | Set on insert |
| updated_at | DateTime | — | No | Yes | Set on every save |

**Validation Rules:**
- `full_name` is required and Unicode-normalized on write (§39.2).
- Every user-entered text field is Unicode-normalized on write (§39.2).
- An applicant must always have at least one `ApplicantContactNumber` — otherwise `APPLICANTS_CONTACT_REQUIRED`.
- `status` is **not** writable through the update endpoint; it moves only via the status action. It is never changed as a side effect of a journey opening, closing, or reaching an outcome — the two lifecycles are independent.
- `creation_source` and `created_by` are set once and are absent from both write serializers.
- Only an **Admin** may create an applicant, by either path.
- `assigned_to`, when set, must be an **active** user whose `authority_type` is `admin` or `lead_manager` — otherwise `APPLICANTS_ASSIGNEE_INVALID`. Conversion is lenient: an ineligible lead owner is dropped silently and the applicant is created unassigned. Not writable through create or update; only `POST /assign/`.
- **Assignment authority:** an Admin may set any eligible assignee or clear it. A Lead Manager may only set themselves on an unassigned applicant, or clear it when they are the assignee — otherwise `APPLICANTS_ASSIGNMENT_FORBIDDEN`. An archived applicant cannot be (re)assigned (`APPLICANTS_APPLICANT_ARCHIVED`).

**Indexes:**
- `applicant_status_recent_idx` — `(status, -created_at)`. Supports the default list view and status filters.
- `appl_name_trgm_idx` — GIN trigram indexes (`gin_trgm_ops`) on the three name fields, supporting `search_applicants`'s leading-wildcard `icontains` across all three (§39.6). The `pg_trgm` extension is declared by this app's own initial migration — see the comment there for why it does not rely on the `leads` migration that also creates it.
- `appl_email_trgm_idx` — GIN trigram on `email`, supporting the same leading-wildcard `icontains` now that `search_applicants` matches the email as well (migration `0002_search_indexes`).
- `status` additionally carries `db_index=True`.
- `assigned_to` — the ForeignKey's own index serves `?assigned_to=<id>` and `?assigned_to=none` (`IS NULL`). No composite index added.

**Soft Delete:** N/A — applicants are never deleted. A closed file is archived via `status = "archived"` (the UI may call it "Delete"), which hides nothing from search and is reversible **by an Admin only** through `POST /restore/` (since 2026-10-29), back to `status_before_archive` or `active`. While archived, the applicant's notes are read-only. The record carries identity, history, and the attribution for where the person came from; deleting it would destroy the consultancy's ability to explain its own past work. There is no delete endpoint.

**Example:**
```json
{
  "id": "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5",
  "full_name": "Ram Shrestha",
  "date_of_birth": "2002-05-14",
  "date_of_birth_bs": {
    "year": 2059, "month": 2, "day": 1,
    "month_name": "Jestha",
    "display": "2059 Jestha 1"
  },
  "gender": "male",
  "nationality": "Nepali",
  "email": "ram@example.com",
  "status": "active",
  "creation_source": "lead_conversion",
  "created_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "adminuser", "display_name": "Adminuser" },
  "assigned_to": { "id": "bbbb2222-3333-4444-5555-666677778888", "username": "leadmgr", "display_name": "Leadmgr" },
  "originating_lead_id": "9d8c7b6a-5e4f-3021-a1b2-c3d4e5f60718",
  "created_at": "2026-07-23T05:00:00Z",
  "updated_at": "2026-07-23T05:00:00Z"
}
```

**Cross-App Dependencies:**
- `authenticate.User` — two FKs (`created_by`, `assigned_to`). Plus one runtime call (2026-10-29): the assign view resolves the requested assignee with `authenticate.selectors.get_active_user_by_id`. Recorded in `INTEGRATION.md` §2 `Requires`.
- `core.events` — `change_status`, `restore`, `assign_applicant`, and `add_note` call `core.events.emit` (post-commit). This app imports nothing from `notifications`; the listener depends on this app, never the reverse.
- **Outbound reader:** `notifications` reads `Applicant.assigned_to` (via `get_expiring_passports`, `get_expiring_language_tests`, and its own re-reads) to route alerts to the assignee.
- `audit` — runtime service/selector dependency. Every mutation calls `audit.services.record_event`; the history endpoint reads `audit.selectors.get_events_for_entity` and renders `audit.serializers.AuditEventHistorySerializer`.
- **Inbound:** `leads.Lead.converted_applicant` is a `OneToOneField` pointing here, and `leads` calls `applicants.services.create_applicant` at conversion. This app does **not** reference `leads` — the dependency runs one direction only.
- **Inbound:** `applicant_journeys.ApplicantJourney.applicant` is a `PROTECT` FK pointing here.
- **Outbound (read-only, reverse accessor):** the list and detail responses project a `destinations` array (§8), and the `country`, `country_code`, and `journey_stage` list filters resolve through `applicant.journeys`. **No import of `applicant_journeys` exists** — `applicant_journeys` owns the ForeignKey and this app reads back through the reverse accessor, the same technique already used for `originating_lead`. The coupling is nonetheless real: renaming `ApplicantJourney.target_country_ref` or `stage` would break this app's list endpoint. See `INTEGRATION.md` §2 `Requires`.
- **Inbound:** `documents.Document.applicant` is a **nullable** `PROTECT` FK pointing here (`related_name="documents"`), and `documents` calls `applicants.selectors.get_applicant_by_id` when a document is created against a person. Nullable because a document may be standalone — belonging to no applicant at all. This app does **not** reference `documents`, and creating or archiving a document never touches the applicant's status. **Note the access asymmetry:** applicants are readable by any Admin or Lead Manager, but their documents are **Admin-only**, so a Lead Manager's view of an applicant file is legitimately incomplete (see `documents/docs/SECURITY.md` §1).

**Security Notes:** Applicants are **shared, not owner-scoped** — any Admin or Lead Manager may read and edit any applicant, whoever `assigned_to` names. This is a deliberate departure from `leads`; see `SECURITY.md` §1 and §9. Superadmin is denied entirely. Creation is Admin-only.

---

## 2. ApplicantContactNumber

**Purpose:** One reachable number. Same shape and reasoning as `leads.LeadContactNumber` — a person may give several usable numbers but one working email address.
**Table:** `applicants_applicantcontactnumber`
**`label` choices:** `mobile`, `home`, `work`, `whatsapp`, `viber`, `other`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → Applicant | Yes | No | No | Owning applicant (`CASCADE`) |
| number | CharField(32) | Yes | No | No | The number as entered, trimmed |
| label | CharField(20) | No | No | No | Defaults to `mobile` |
| is_primary | Boolean | No | No | No | Preferred number; sorts first |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- `number` matches `^\+?[0-9][0-9 ()\-]{4,31}$` via `core.validators.validate_contact_number` — the same validator `leads` uses, shared in `core` per §3.
- `(applicant, number)` is unique.
- Managed **nested inside the applicant payload**; supplying `contact_numbers` replaces the whole set.

**Indexes:**
- `uniq_applicant_contact_number` — unique constraint on `(applicant, number)`
- `appl_contact_number_idx` — B-tree on `number` alone. The unique constraint's leading column is the applicant, so it cannot serve `search_applicants`, which knows the number and not the person (migration `0002_search_indexes`).
- `appl_contact_num_trgm_idx` — GIN `gin_trgm_ops` on `number`. The B-tree above cannot serve the leading-wildcard `number__icontains` that `search_applicants` issues, so a phone lookup was scanning this table end to end. The mirror of `leads.LeadContactNumber`'s trigram index, for the same reason (migration `0005_trigram_search_indexes`).

**Soft Delete:** N/A — replaced wholesale on update and cascade-deleted with the applicant, which is itself never deleted. Removal is a correction, not a lifecycle event.

---

## 3. ApplicantAddress

**Purpose:** A permanent or current address, structured for the Nepal context but entirely optional.
**Table:** `applicants_applicantaddress`
**`address_type` choices:** `permanent`, `current`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → Applicant | Yes | No | No | Owning applicant (`CASCADE`) |
| address_type | CharField(20) | Yes | No | No | Permanent or current |
| country | CharField(100) | No | No | No | |
| province | CharField(100) | No | No | No | |
| district | CharField(100) | No | No | No | |
| municipality | CharField(150) | No | No | No | Unicode-normalized |
| ward | CharField(10) | No | No | No | |
| street_address | CharField(255) | No | No | No | Anything the structure does not capture; Unicode-normalized |
| postal_code | CharField(20) | No | No | No | |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- At most one address per type per applicant, enforced by a database constraint and reported cleanly by the serializer.
- Every component is optional — a file is often started before the full address is known.
- Managed nested; supplying `addresses` replaces the whole set.

**Indexes:** `uniq_applicant_address_type` — unique constraint on `(applicant, address_type)`

**Soft Delete:** N/A — replaced wholesale and cascade-deleted with the applicant.

---

## 4. PassportDetail

**Purpose:** The applicant's current passport. `expiry_date` is stored rather than derived because an expiring passport can block a visa application, and the project anticipates notifications driven off this date.
**Table:** `applicants_passportdetail`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | OneToOne → Applicant | Yes | No | No | Owning applicant (`CASCADE`) |
| passport_number | CharField(50) | Yes | No | No | Upper-cased on write |
| issuing_country | CharField(100) | No | No | No | |
| place_of_issue | CharField(150) | No | No | No | |
| issued_date | DateField | No | Yes | No | User-facing; exposed with a BS companion |
| expiry_date | DateField | No | Yes | No | Indexed; user-facing, with a BS companion |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:**
- When both dates are present, `expiry_date` must fall after `issued_date` — otherwise `APPLICANTS_PASSPORT_EXPIRY_INVALID`.
- One record per applicant: a renewal overwrites it, with the change captured in the audit history. Whether old passport numbers need preserving is an open question in the concept file.
- Managed nested; supplying `passport` upserts the row.

**Indexes:**
- `expiry_date` (`db_index=True`) — supports the expiry queries the notification module will need, and the dashboard's expiring-passport blocker.
- `appl_passport_number_idx` — B-tree on `passport_number`. Numbers are upper-cased on write, so it serves equality and prefix matching (migration `0002_search_indexes`).
- `appl_passport_num_trgm_idx` — GIN `gin_trgm_ops` on `passport_number`. This is the index that actually serves `search_applicants`: it matches with `icontains`, and staff routinely type the last few digits of a passport rather than the whole number, which no B-tree can serve (migration `0005_trigram_search_indexes`).

**Soft Delete:** N/A — upserted in place and cascade-deleted with the applicant.

---

## 5. FamilyMember

**Purpose:** One family member. Kept distinct from `EmergencyContact` because a person's emergency contact may be a friend, landlord, or colleague rather than a relative.
**Table:** `applicants_familymember`
**`relationship` choices:** `father`, `mother`, `spouse`, `sibling`, `child`, `guardian`, `grandfather`, `grandmother`, `other` (the two grandparents added 2026-10-29 for ward-office letters)

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → Applicant | Yes | No | No | Owning applicant (`CASCADE`) |
| relationship | CharField(20) | Yes | No | No | |
| full_name | CharField(255) | No | No | No | |
| occupation | CharField(150) | No | No | No | Unicode-normalized |
| contact_number | CharField(32) | No | No | No | Same validator as §2 |
| citizenship_no | CharField(50) | No | No | No | The relative's citizenship number, as entered (normalized) |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:** Managed nested; supplying `family_members` replaces the whole set.

**Soft Delete:** N/A — replaced wholesale and cascade-deleted with the applicant.

---

## 6. EmergencyContact

**Purpose:** Who to reach if something goes wrong. Not necessarily a relative.
**Table:** `applicants_emergencycontact`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → Applicant | Yes | No | No | Owning applicant (`CASCADE`) |
| full_name | CharField(255) | No | No | No | |
| relationship | CharField(100) | No | No | No | Free text — not the `FamilyMember` enum |
| contact_number | CharField(32) | Yes | No | No | Same validator as §2 |
| email | EmailField | No | No | No | |
| address | TextField | No | No | No | Unicode-normalized |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules:** `contact_number` is required — an emergency contact with no number serves no purpose. Managed nested; supplying `emergency_contacts` replaces the whole set.

**Soft Delete:** N/A — replaced wholesale and cascade-deleted with the applicant.

---

## 7. Applicant history (no table — read model)

**Purpose:** The chronological record of everything important that happened to an applicant.

This app owns **no history table**. History is `audit.AuditEvent` filtered to `app_label="applicants"`, `entity_type="applicant"`, `entity_id=<id>`, newest first. `AuditEvent` is append-only and blocks deletion at the model layer.

| `action` | Written when | Notable payload |
|---|---|---|
| `applicant_created` | An applicant is created, by either path | `metadata.creation_source`, `metadata.assigned_to` (user id or `null`) |
| `applicant_updated` | Identity fields are corrected | `changes` per field; `citizenship_no` and `national_id_no` appear only as `<changed>` |
| `applicant_contact_changed` | Contact numbers were replaced | `metadata.count` |
| `applicant_address_changed` | Addresses were replaced | `metadata.count` |
| `applicant_passport_changed` | Passport was upserted | — |
| `applicant_family_changed` | Family members were replaced | `metadata.count` |
| `applicant_emergency_contact_changed` | Emergency contacts were replaced | `metadata.count` |
| `applicant_status_changed` | Standing changed | `changes.status = {from, to}` |
| `applicant_restored` | An Admin un-archived the applicant | `reason`; `changes.status = {from: "archived", to}` |
| `applicant_note_added` / `_updated` / `_deleted` | A note was written, corrected, or removed | `metadata { note_id, category, noted_at, is_backdated }`; `_updated` adds per-field `changes` with `body` as `<changed>` |
| `applicant_notes_imported` | Lead conversion copied the lead's notes here | `metadata { lead_id, count }` |
| `applicant_assigned` | An assignee was set or changed | `changes.assigned_to = {from, to}` — user-id strings or `null` |
| `applicant_unassigned` | The assignee was cleared | `changes.assigned_to = {from: <user id>, to: null}` |

**Cross-App Dependencies:** `audit` — write via `record_event`, read via `get_events`.

**Security Notes:** No secrets or full record dumps enter an audit payload (§17). `changes` carries only fields that moved; free text the user wrote (addresses, notes) is not copied into events.

---

## 8. Applicant destinations (no table — read model)

**Purpose:** Where a person is trying to go, projected onto the applicant list and detail responses as a `destinations` array.

This app owns **no destination column and never will**. A person is not a study plan: someone may try for a master's in Australia, have it fall through, and try again for a diploma in Canada two years later. That is two journeys and one applicant, and `applicant_journeys.ApplicantJourney` is where the destination correctly lives.

The projection exists because a list that cannot show where anyone is headed forces a second round trip per row just to render a country column. It is derived at read time from `applicant.journeys` and is never stored, so it cannot disagree with the journeys it summarizes.

| Field | Type | Nullable | Description |
|-------|------|----------|--------------|
| journey_id | UUID string | No | The `ApplicantJourney` this destination belongs to |
| stage | string | No | That journey's `JourneyStage` value |
| country_id | UUID string | Yes | The `institutions.Country` id, or `null` for a journey with no catalogue link |
| country_code | string | No | The country's ASCII code, `""` when there is no catalogue link |
| country_name | string | No | The catalogue name, `""` when there is no catalogue link |
| target_country | string | No | The free text the destination was typed as. The **only** destination a pre-catalogue journey has |

**Validation Rules:** none — read-only, never accepted from a client on any endpoint.

**Indexes:** none of its own. The projection is served by `prefetch_related("journeys__target_country_ref")`, and the `country`/`country_code`/`journey_stage` filters that traverse the same relation are served by `applicant_journeys`' own `target_country_ref` and `stage` indexes.

**Soft Delete:** N/A — a read model over another app's rows; it owns nothing to delete.

**Example:**
```json
"destinations": [
  {
    "journey_id": "1f2e3d4c-5b6a-7089-9a8b-7c6d5e4f3021",
    "stage": "offer_stage",
    "country_id": "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9",
    "country_code": "au",
    "country_name": "Australia",
    "target_country": ""
  }
]
```

**Cross-App Dependencies:** `applicant_journeys` — read-only, through the reverse `journeys` accessor. No import exists; see §1 `Cross-App Dependencies` and `INTEGRATION.md` §2 `Requires` for why the coupling is still real.

**Security Notes:** Journeys are shared across the consultancy exactly as applicants are, so projecting them here widens nobody's visibility. An empty array means the person has no journey yet — never that one was hidden.

---

## 9. ApplicantNote

**Purpose:** A note on an applicant — general, or a record of an office visit — attributed to its author and dated to when it happened. Includes notes carried over from the lead the applicant was converted from.
**Table:** `applicants_applicantnote`
**`category` choices:** `general`, `visit` — `core.constants.NoteCategory`, shared with `leads.LeadNote`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → Applicant | Yes | No | No | Owning applicant (`PROTECT`) |
| category | CharField(20) | No | No | No | Defaults to `general` |
| body | TextField | Yes | No | No | Unicode-normalized; ≤10 000 characters (API) |
| noted_at | DateTime | No | No | No | When it happened, user-set and backdatable; defaults to now; indexed |
| author | FK → authenticate.User | Yes | No | No | Who wrote it (`PROTECT`) — for a carried-over note, the lead's note author |
| updated_by | FK → authenticate.User | No | Yes | Yes | Last editor (`SET_NULL`) |
| deleted_at | DateTime | No | Yes | Yes | Soft delete |
| deleted_by | FK → authenticate.User | No | Yes | Yes | Who deleted it (`SET_NULL`) |
| source_lead_id | UUID | No | Yes | Yes | The converted lead a carried-over note came from; indexed. A bare UUID, not a foreign key — `leads` depends on this app, never the reverse |
| created_at | DateTime | — | No | Yes | When it was saved; for a carried-over note, the **original** save time on the lead |
| updated_at | DateTime | — | No | Yes | Last save |

**Derived, read-only:** `noted_at_bs` (§39.4); `is_backdated` — `created_at − noted_at > 15 min`.

**Validation Rules:**
- `body` required, normalized, non-blank after normalization.
- `noted_at` not later than now + 5 minutes → `APPLICANTS_NOTE_FUTURE_DATE`; no lower bound; an offset-less value is read as Asia/Kathmandu.
- Edit and delete: author or Admin → otherwise `APPLICANTS_NOTE_FORBIDDEN`.
- No write while the applicant is archived → `APPLICANTS_APPLICANT_ARCHIVED`.
- Ordered by `-noted_at`, then `-created_at`.

**Indexes:** `applnote_applicant_noted_idx` — `(applicant, -noted_at)`, the notes panel's default order; `noted_at` and `source_lead_id` also carry `db_index=True`.

**Soft Delete:** Yes. `DELETE …/notes/<id>/` sets `deleted_at`/`deleted_by`; the note leaves every list and 404s, the row and body remain, and the deletion is in the applicant's history. No restore endpoint for a note. The Django admin is read-only for notes (no add, no delete).

**Example:**
```json
{
  "id": "9a8b7c6d-1111-2222-3333-444455556666",
  "category": "visit",
  "body": "Visited with her father; wants Australia, needs IELTS.",
  "noted_at": "2026-07-22T09:30:00Z",
  "noted_at_bs": { "year": 2083, "month": 4, "day": 6, "month_name": "Shrawan", "display": "2083 Shrawan 6" },
  "is_backdated": true,
  "source_lead_id": "1a2b3c4d-5e6f-4708-9a1b-2c3d4e5f6071",
  "author": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "leadmgr", "display_name": "Leadmgr" },
  "updated_by": null,
  "created_at": "2026-07-23T04:05:00Z",
  "updated_at": "2026-07-23T04:05:00Z"
}
```

**Cross-App Dependencies:**
- `authenticate.User` via `author`, `updated_by`, `deleted_by` (FK references only).
- `core` — `NoteCategory` and the note checks, shared with `leads`.
- **Written by `leads`** at conversion through `services.import_lead_notes` (a service call, plain values). `leads/docs/DATA_CONTRACT.md` §6 records the other side; `leads/docs/INTEGRATION.md` §2 lists the runtime coupling.

---

## 10. ApplicantEducation

**Purpose:** One qualification the applicant holds or is studying for. Folded into this app on 2026-10-29 instead of a separate `education` module (`concepts/education.txt`); a core record — gaps, training, backlogs, and medium of instruction are deferred.
**Table:** `applicants_applicanteducation`
**`level` choices:** `see`, `plus_two`, `diploma`, `bachelor`, `master`, `phd`, `other` — `core.constants.HighestQualification`, shared with `leads` (the lead's `highest_qualification_level` maps 1:1 at conversion)
**`completion_status` choices:** `completed`, `ongoing`
**`score_type` choices:** `gpa`, `percentage` — `core.constants.AcademicScoreType`
**`year_calendar` choices:** `bs`, `ad` — `core.constants.CalendarSystem`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → Applicant | Yes | No | No | Owning applicant (`CASCADE`, like every sub-record) |
| level | CharField(20) | Yes | No | No | Where the qualification sits on the Nepali ladder |
| qualification | CharField(200) | No | No | No | Programme or stream, e.g. "BBS", "Science" |
| institution | CharField(255) | No | No | No | |
| country | CharField(100) | No | No | No | Free text |
| completion_status | CharField(20) | No | No | No | Default `completed` |
| score | Decimal(5,2) | Conditional | Yes | No | Required with `score_type` |
| score_type | CharField(20) | Conditional | No | No | Required with `score` |
| grading_system | CharField(50) | No | No | No | How the score reads ("GPA (4.0)", "First Division") — divisions and letter grades live only here |
| start_year / completion_year | PositiveSmallInteger | No | Yes | No | Bare years in `year_calendar` |
| year_calendar | CharField(2) | Conditional | No | No | Required when either year is set |
| source_lead_id | UUID | No | Yes | Yes | The converted lead this record came from |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Validation Rules** (`services._assert_educations_valid`, every failure reported as `educations[i].field` → `APPLICANTS_EDUCATION_INVALID`):
- `score` and `score_type` together; gpa 0–4, percentage 0–100 (`core.validators.academic_score_error`).
- A year needs `year_calendar`; BS 2000…current BS year+1, AD 1950…current year+1 (`core.validators.year_error`, today taken in Nepal time); `start_year ≤ completion_year`.
- An `ongoing` record has no `completion_year`.
- Text fields Unicode-normalized (§39.2). Managed nested: supplying `educations` replaces the whole set.

**Indexes:** none beyond the FK. Ordered `-completion_year`, then `created_at`.

**Soft Delete:** N/A — replaced wholesale and cascade-deleted with the applicant (which is never deleted). A wrongly entered qualification has no historical value (`concepts/education.txt`); the audit event records that the set changed and its size.

**Example:**
```json
{
  "id": "0a1b2c3d-4e5f-4607-8192-a3b4c5d6e7f8",
  "level": "bachelor", "qualification": "BBS", "institution": "Shanker Dev Campus", "country": "Nepal",
  "completion_status": "completed", "score": "3.45", "score_type": "gpa", "grading_system": "GPA (4.0)",
  "start_year": 2076, "completion_year": 2080, "year_calendar": "bs", "source_lead_id": null
}
```

**Cross-App Dependencies:** `core` (shared enums and validators, with `leads`). Written by `leads` at conversion through `services.import_lead_qualification` (plain values).

---

## 11. ApplicantLanguageTest

**Purpose:** One sitting of a language test — IELTS, PTE, TOEFL, Duolingo — with its scores and expiry. Folded into this app on 2026-10-29 instead of a separate `test_scores` module (`concepts/test_scores.txt`). Language tests only; SAT/GRE are out of scope.
**Table:** `applicants_applicantlanguagetest`
**`test_type` choices:** `ielts`, `pte`, `toefl`, `duolingo`, `other` — `core.constants.LanguageTestType`, shared with `leads.LeadLanguageCertificate`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → Applicant | Yes | No | No | Owning applicant (`CASCADE`) |
| test_type | CharField(20) | Yes | No | No | |
| overall_score / listening_score / reading_score / writing_score / speaking_score | Decimal(5,1) | No | Yes | No | Per-type ranges below |
| test_date | Date | No | Yes | No | Not in the future |
| certificate_number | CharField(100) | No | No | No | Test report / TRF number |
| expiry_date | Date | No | Yes | No | After `test_date`; **indexed** for expiry alerts (notifications, planned) |
| source_lead_id | UUID | No | Yes | Yes | The converted lead's certificate this came from |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Derived, read-only:** `test_date_bs`, `expiry_date_bs` (§39.4).

**Validation Rules** (`core.validators.language_test_errors`, shared with lead certificates; failures as `language_tests[i].field` → `APPLICANTS_LANGUAGE_TEST_INVALID`):
- Every score: IELTS 0–9 in 0.5 steps; PTE 10–90; TOEFL 0–120; Duolingo 10–160; `other` ≥ 0. Section scores use the same range as the overall score (the frontend's rule).
- `test_date` not after today (Nepal time); `expiry_date` after `test_date` when both are set.
- Managed nested: supplying `language_tests` replaces the whole set.

**Indexes:** `expiry_date` (`db_index`). Ordered `-test_date`, then `created_at`.

**Soft Delete:** N/A — replaced wholesale and cascade-deleted with the applicant. Scores never enter the audit log; the event records only the count.

**Example:**
```json
{
  "id": "1b2c3d4e-5f60-4718-92a3-b4c5d6e7f809",
  "test_type": "ielts", "overall_score": "7.0", "listening_score": "7.5", "reading_score": "6.5",
  "writing_score": "6.5", "speaking_score": "7.0", "test_date": "2025-03-01",
  "test_date_bs": { "year": 2081, "month": 11, "day": 17, "month_name": "Falgun", "display": "2081 Falgun 17" },
  "certificate_number": "25NP000123", "expiry_date": "2027-03-01",
  "expiry_date_bs": { "year": 2083, "month": 11, "day": 17, "month_name": "Falgun", "display": "2083 Falgun 17" },
  "source_lead_id": null
}
```

**Cross-App Dependencies:** `core` (shared enum and validator, with `leads`). Written by `leads` at conversion through `services.import_lead_certificates` (plain values).

