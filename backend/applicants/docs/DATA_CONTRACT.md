# Data Contract — Applicants

**Owner app:** `applicants`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-23
**Purpose:** Owns the permanent, authoritative identity of a person the consultancy works with — name, date of birth, contact numbers, addresses, passport, family, emergency contacts, and standing. It does **not** own study objectives (`applicant_journeys`), academic history (`education`, not built), test attempts (`test_scores`, not built), or any file. It owns no history table either — an applicant's history is the central `audit` log filtered to that applicant. It carries **no reference to the originating lead**: `leads.Lead` owns that link, so this app has no dependency on `leads`.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial contract — six models, shared (non-owner-scoped) access |
| 1.1.0 | 2026-07-24 | AI (Claude) | Documentation only — no schema change. Recorded the inbound nullable `documents.Document.applicant` FK and the access asymmetry it introduces: applicants are readable by any Admin or Lead Manager, their documents are Admin-only |

---

## Deliberate Deviations

`concepts/applicants.txt` is the grounding document; three provisions are implemented differently than a literal reading suggests.

- **No history table.** The concept asks for a chronological history of applicant actions. The central `audit` app already provides an immutable append-only event log, and §4 forbids duplicating another app's storage. History is `audit.AuditEvent` filtered to `app_label="applicants"`, `entity_type="applicant"`, `entity_id=<id>`. Same decision as `leads`.
- **No photograph.** The concept lists it, but §14 requires a documented file contract and `project_overview.txt` has a dedicated `uploaded_files` domain. Adding an `ImageField` now would pre-empt that app or ship an undocumented upload path. Recorded as an open question in the concept file.
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
| full_name_np | CharField(255) | Yes | No | No | Devanagari name — the canonical human identity |
| full_name_en | CharField(255) | No | No | No | Roman name — an independent identity, not a translation |
| full_name_romanized | CharField(255) | No | No | Yes | ASCII search form derived from `full_name_np` |
| date_of_birth | DateField | No | Yes | No | User-facing; exposed with a BS companion |
| gender | CharField(20) | No | No | No | Blank when undisclosed or unknown |
| nationality | CharField(100) | No | No | No | Free text |
| email | EmailField | No | No | No | Single address; multiple emails are deliberately unsupported |
| status | CharField(20) | No | No | No | Standing with the consultancy; defaults to `active` |
| creation_source | CharField(20) | Yes | No | Yes | Set by the service, never by a client. Immutable |
| created_by | FK → authenticate.User | Yes | No | Yes | The Admin who created it (`PROTECT`). Immutable |
| created_at | DateTime | — | No | Yes | Set on insert |
| updated_at | DateTime | — | No | Yes | Set on every save |

**Validation Rules:**
- `full_name_np` is required and Unicode-normalized; `full_name_romanized` is derived in the service layer and never accepted from a client (§39.1/§39.3).
- Every user-entered text field is Unicode-normalized on write (§39.2).
- An applicant must always have at least one `ApplicantContactNumber` — otherwise `APPLICANTS_CONTACT_REQUIRED`.
- `status` is **not** writable through the update endpoint; it moves only via the status action. It is never changed as a side effect of a journey opening, closing, or reaching an outcome — the two lifecycles are independent.
- `creation_source` and `created_by` are set once and are absent from both write serializers.
- Only an **Admin** may create an applicant, by either path.

**Indexes:**
- `applicant_status_recent_idx` — `(status, -created_at)`. Supports the default list view and status filters.
- `appl_name_np_trgm_idx`, `appl_name_en_trgm_idx`, `appl_name_rom_trgm_idx` — GIN trigram indexes (`gin_trgm_ops`) on the three name fields, supporting `search_applicants`'s leading-wildcard `icontains` across all three (§39.6). The `pg_trgm` extension is declared by this app's own initial migration — see the comment there for why it does not rely on the `leads` migration that also creates it.
- `status` additionally carries `db_index=True`.

**Soft Delete:** N/A — applicants are never deleted. A closed file is archived via `status = "archived"`, which is fully reversible and hides nothing from search. The record carries identity, history, and the attribution for where the person came from; deleting it would destroy the consultancy's ability to explain its own past work. There is no delete endpoint.

**Example:**
```json
{
  "id": "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5",
  "full_name_np": "राम श्रेष्ठ",
  "full_name_en": "Ram Shrestha",
  "full_name_romanized": "raam shrestha",
  "date_of_birth": "2002-05-14",
  "date_of_birth_bs": {
    "year": 2059, "month": 2, "day": 1,
    "month_name_en": "Jestha", "month_name_np": "जेठ",
    "display_en": "2059 Jestha 1", "display_np": "२०५९ जेठ १"
  },
  "gender": "male",
  "nationality": "Nepali",
  "email": "ram@example.com",
  "status": "active",
  "creation_source": "lead_conversion",
  "created_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "adminuser", "display_name": "Adminuser" },
  "originating_lead_id": "9d8c7b6a-5e4f-3021-a1b2-c3d4e5f60718",
  "created_at": "2026-07-23T05:00:00Z",
  "updated_at": "2026-07-23T05:00:00Z"
}
```

**Cross-App Dependencies:**
- `authenticate.User` — one FK (`created_by`). Model-level reference only, per §4.
- `audit` — runtime service/selector dependency. Every mutation calls `audit.services.record_event`; the history endpoint reads `audit.selectors.get_events`.
- **Inbound:** `leads.Lead.converted_applicant` is a `OneToOneField` pointing here, and `leads` calls `applicants.services.create_applicant` at conversion. This app does **not** reference `leads` — the dependency runs one direction only.
- **Inbound:** `applicant_journeys.ApplicantJourney.applicant` is a `PROTECT` FK pointing here.
- **Inbound:** `documents.Document.applicant` is a **nullable** `PROTECT` FK pointing here (`related_name="documents"`), and `documents` calls `applicants.selectors.get_applicant_by_id` when a document is created against a person. Nullable because a document may be standalone — belonging to no applicant at all. This app does **not** reference `documents`, and creating or archiving a document never touches the applicant's status. **Note the access asymmetry:** applicants are readable by any Admin or Lead Manager, but their documents are **Admin-only**, so a Lead Manager's view of an applicant file is legitimately incomplete (see `documents/docs/SECURITY.md` §1).

**Security Notes:** Applicants are **shared, not owner-scoped** — any Admin or Lead Manager may read and edit any applicant. This is a deliberate departure from `leads`; see `SECURITY.md` §1. Superadmin is denied entirely. Creation is Admin-only.

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

**Indexes:** `uniq_applicant_contact_number` — unique constraint on `(applicant, number)`

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

**Indexes:** `expiry_date` (`db_index=True`) — supports the expiry queries the notification module will need.

**Soft Delete:** N/A — upserted in place and cascade-deleted with the applicant.

---

## 5. FamilyMember

**Purpose:** One family member. Kept distinct from `EmergencyContact` because a person's emergency contact may be a friend, landlord, or colleague rather than a relative.
**Table:** `applicants_familymember`
**`relationship` choices:** `father`, `mother`, `spouse`, `sibling`, `child`, `guardian`, `other`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| applicant | FK → Applicant | Yes | No | No | Owning applicant (`CASCADE`) |
| relationship | CharField(20) | Yes | No | No | |
| full_name_np | CharField(255) | Yes | No | No | Unicode-normalized |
| full_name_en | CharField(255) | No | No | No | |
| occupation | CharField(150) | No | No | No | Unicode-normalized |
| contact_number | CharField(32) | No | No | No | Same validator as §2 |
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
| full_name_np | CharField(255) | Yes | No | No | Unicode-normalized |
| full_name_en | CharField(255) | No | No | No | |
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
| `applicant_created` | An applicant is created, by either path | `metadata.creation_source` |
| `applicant_updated` | Identity fields are corrected | `changes` per field |
| `applicant_contact_changed` | Contact numbers were replaced | `metadata.count` |
| `applicant_address_changed` | Addresses were replaced | `metadata.count` |
| `applicant_passport_changed` | Passport was upserted | — |
| `applicant_family_changed` | Family members were replaced | `metadata.count` |
| `applicant_emergency_contact_changed` | Emergency contacts were replaced | `metadata.count` |
| `applicant_status_changed` | Standing changed | `changes.status = {from, to}` |

**Cross-App Dependencies:** `audit` — write via `record_event`, read via `get_events`.

**Security Notes:** No secrets or full record dumps enter an audit payload (§17). `changes` carries only fields that moved; free text the user wrote (addresses, notes) is not copied into events.
