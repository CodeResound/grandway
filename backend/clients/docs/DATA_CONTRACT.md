# Data Contract — Clients

**Owner app:** `clients`
**Version:** 1.1.0
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the consultancy's B2B partner directory — the agencies, schools, and companies that refer or send applicants, with the contact and identity details staff need to work with them. It does **not** own people (`leads`, `applicants`), study plans (`applicant_journeys`), the study catalogue (`institutions`), or offers. It owns no history table — a client's history is the central `audit` log filtered to that client.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial contract — `Client` and `ClientContactNumber` |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. Recorded that `logo_url` was deliberately not migrated, and that a `Client` is not an accepted owner type |
| 1.1.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (`name`, `spokesperson_name`). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |

---

## Deliberate Deviations

`concepts/clients.txt` leaves five questions open. Four were settled with the user; the fifth was settled by the project's own state. Each departure from the concept file or from `CLAUDE.md` is recorded here rather than left to be inferred.

- **The logo is a URL, not an uploaded file.** The concept asks which. `logo_url` is a plain link to a logo hosted elsewhere: no storage decision and no upload path. **`uploaded_files` shipped on 2026-07-24 and this field was deliberately not migrated to it** — repointing it would change a shipped response shape (§22/§29) and needs its own session and deprecation path. Note also that a `Client` is **not** one of that app's five owner types, so a logo cannot be attached there today even by hand; adding a sixth owner column is the change that would make migration possible.
- **`ClientStatus` has two values, not three.** The concept asks whether a separate `paused` or `archived` distinction is needed. It is not: a third status is only worth having if something branches on it, and in V1 nothing does — the only behaviour attached to status is whether the directory presents a partner as a current contact, which is binary. The nuance a `paused` value would have carried is carried better by the **mandatory** `status_note`, which says *why* in words instead of encoding it in an enum nothing reads. This is the opposite call from `institutions.AvailabilityStatus`, which genuinely needs four values because its program search filters on them.
- **One inline spokesperson, not a contact table.** The concept says V1 "may" put a primary spokesperson directly on the client record, and separately rules out "complex multi-contact CRM structure in V1". Both are honoured: the spokesperson is four inline fields. Contact *numbers* are a child table, because an organization realistically has a landline and two mobiles while having exactly one person you ask for.
- **No history table**, for the same reason as `leads`, `applicants`, `applicant_journeys`, `institutions`, and `offers`: `audit` already provides an immutable append-only log and §4 forbids duplicating another app's storage.
- **No `code` field.** `leads.LeadSource` and `institutions.Country` both carry a stable ASCII code because they are picked from dropdowns and referenced by key. A client is looked up by name and addressed by UUID; a code would be a field nobody types and nobody reads.
- **No `client_type` enum.** The concept's prose names "companies, agencies, schools, or partner organizations", but its explicit field list — "company name, spokesperson, contact numbers, email, address, website, logo, notes, and status" — omits a type. §32: code only what the requirement specifies. Recorded as a future improvement.
- **`address` is one free-text field**, not the structured province/district/municipality/ward shape `applicants.ApplicantAddress` uses. The concept asks for a form "kept intentionally small and practical", and a partner's address is written on an envelope, not used for eligibility or reporting.
- **`name` is a single required English field (§39.1)**, as everywhere else in the project. `spokesperson_name` is a single optional field. Both are Unicode-normalized on write (§39.2) and the organization name is trigram-indexed for search.

---

## 1. Client

**Purpose:** A B2B partner organization. Answers "who is this company, and who do we call there" — nothing else. It is not a person record and not a lead.
**Table:** `clients_client`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| name | CharField(255) | No | No | No | Optional English name |
| spokesperson_name | CharField(255) | No | No | No | |
| spokesperson_designation | CharField(150) | No | No | No | Their role, e.g. `Managing Director` |
| email | EmailField | No | No | No | The organization's address, not the spokesperson's |
| website | URLField(500) | No | No | No | |
| logo_url | URLField(500) | No | No | No | A link to a logo hosted elsewhere — not an upload |
| address | Text | No | No | No | One free-text field |
| status | CharField(20) | No | No | No | Defaults to `active`; indexed |
| status_note | Text | No | No | No | Why the relationship ended. Required to retire; cleared on restore |
| retired_at | DateTime | No | Yes | Yes | Stamped by the retire action |
| retired_by | FK → `authenticate.User` | No | Yes | Yes | `SET_NULL`; stamped by the retire action |
| notes | Text | No | No | No | |
| created_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`status`** — `active` | `inactive`. Defined in `clients/constants.py` `ClientStatus`. See "Deliberate Deviations" for why there is no third value.

**Validation Rules:**

- `name` is required and Unicode-normalized on write (§39.2); `name` is normalized when present.
- `name` and `spokesperson_name` are Unicode-normalized in the **service layer** (§39.2) as well as the serializer, so a direct service caller cannot store an un-normalized value.
- **`status` is not settable through the update endpoint.** It moves only through `retire_client` and `restore_client`, which stamp who acted and why. A `PATCH` carrying `status`, `status_note`, `retired_at`, or `retired_by` is **rejected** with `CLIENTS_STATUS_IMMUTABLE`, not silently dropped — a client that sent `status` and got 200 back would believe the record had changed.
- Retiring requires a non-empty reason → `CLIENTS_STATUS_NOTE_REQUIRED`. Retiring an already-inactive client → `CLIENTS_CLIENT_ALREADY_RETIRED` (409).
- Restoring an already-active client → `CLIENTS_CLIENT_NOT_RETIRED` (409).
- `email` and the two URL fields are format-validated by DRF; all three are optional.

**Derived, read-only:** `is_active` — the status is `active`.

**Indexes:**

- `(status, name)` — `client_status_name_idx`. Supports the directory filtered to current partners, in name order.
- GIN trigram on `name`, `name`, `name` — `client_name_{np,en,rom}_trgm_idx`. Support the `?search=` lookup (§39.6). The `pg_trgm` extension already exists from `leads` migration 0002.
- **The three spokesperson name fields are deliberately *not* trigram-indexed**, although `search_clients` does search them. The directory is a bounded table of partner organizations — tens to hundreds of rows — unlike `leads`, which grows without limit. Six GIN indexes on a table this size cost more in write overhead and disk than they save. If the directory ever reaches a few thousand rows, add them; the selector is already written to use them.

**Soft Delete:** `N/A — no deletion at all.` No client is ever deleted and there is no delete endpoint or delete service, enforced by a test that fails if one appears (`tests/test_services.py::NothingIsDeletedTests`). `concepts/clients.txt` — "No deletion of historical records. Inactive clients should be retained." A partner the consultancy has stopped working with becomes `inactive` with a note. `created_by` is `PROTECT`, so the user who added a client cannot be removed either.

**Cross-App Dependencies:**

- `authenticate.User` — FKs for `created_by` (`PROTECT`) and `retired_by` (`SET_NULL`).
- `audit` — service call. Every mutation appends one event. No storage here.
- **Referenced by: nothing.** This app has no edge to any business app in either direction — the position `institutions` held until `offers` shipped. The concept's flow 3, "Attribution support", anticipates `leads` referencing a client as the origin of a referral; **that FK does not exist and is not built.** Recorded in `docs/INTEGRATION.md` §9 `Gaps` and in the concept file's open questions.

**Example:**

```json
{
  "id": "6d7e8f90-1a2b-4c3d-9e4f-5061728394a5",
  "name": "Himal Education",
  "spokesperson_name": "Sunita Shrestha",
  "spokesperson_designation": "Managing Director",
  "email": "info@himal.example",
  "website": "https://himal.example",
  "logo_url": "https://himal.example/logo.png",
  "address": "Putalisadak, Kathmandu",
  "contact_numbers": [
    { "id": "7e8f9012-2b3c-4d5e-af60-718293a4b5c6", "number": "9801111111", "label": "mobile", "is_primary": true },
    { "id": "8f901234-3c4d-4e5f-b071-8293a4b5c6d7", "number": "014567890", "label": "work", "is_primary": false }
  ],
  "status": "active",
  "is_active": true,
  "status_note": "",
  "retired_at": null,
  "retired_at_bs": null,
  "retired_by_username": null,
  "notes": "Refers mostly nursing applicants.",
  "created_by_username": "adminuser",
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T09:18:47Z"
}
```

---

## 2. ClientContactNumber

**Purpose:** One phone number for a client organization. A child table because an agency realistically has several numbers, while it has exactly one person you ask for — which is why the spokesperson is inline and the numbers are not.
**Table:** `clients_clientcontactnumber`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| client | FK → `Client` | Yes | No | No | `CASCADE` — see Soft Delete |
| number | CharField(32) | Yes | No | No | Validated by `core.validators.validate_contact_number` |
| label | CharField(20) | No | No | No | `core.constants.ContactNumberLabel` |
| is_primary | Boolean | No | No | No | Defaults to `false` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`label`** — `mobile` | `home` | `work` | `whatsapp` | `viber` | `other`. Imported from `core.constants.ContactNumberLabel`, shared with `leads` and `applicants` — §3 forbids duplicating an enum across apps. A client's numbers are labelled from the same vocabulary a person's are, because "which of these do I call" is the same question.

**Validation Rules:**

- `number` matches `^\+?[0-9][0-9 ()\-]{4,31}$` — deliberately permissive so Nepali mobiles, landlines with area codes, and `+country-code` forms all fit.
- **Managed through the client payload as a complete replacement set**, never through its own endpoints. Sending `contact_numbers` on create or update replaces every number the client has; the payload is the full set it should hold afterwards. Same handling as `applicants`.
- **`null` and `[]` mean different things on update.** Omitting `contact_numbers` leaves the existing numbers alone; sending `[]` clears them.
- The same number twice in one payload → `CLIENTS_CONTACT_NUMBER_DUPLICATE`. Two *different* clients may share a number — an agency switchboard is legitimately shared.

**Indexes:** none beyond the FK. `UniqueConstraint(client, number)` — `uniq_client_contact_number`.

**Soft Delete:** `N/A — but note the FK is CASCADE, not PROTECT.` Numbers are hard-deleted and recreated on every replacement write, which is the intended behaviour of a replacement set. The `CASCADE` to `Client` can never fire, because no code path deletes a client; `PROTECT` here would express a constraint in the wrong direction — a number does not exist independently of its organization.

**Cross-App Dependencies:** none of its own. `core.constants.ContactNumberLabel` and `core.validators.validate_contact_number` are shared vocabulary, not an app dependency.

**Example:**

```json
{
  "id": "7e8f9012-2b3c-4d5e-af60-718293a4b5c6",
  "number": "9801111111",
  "label": "mobile",
  "is_primary": true
}
```
