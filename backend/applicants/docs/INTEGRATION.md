# Integration — Applicants

**Owner app:** `applicants`
**Version:** 1.5.0
**Status:** Active
**Created:** 2026-07-23

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial integration contract — 6 endpoints |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. Named the two calls that back an avatar, and the two caveats that still block a simple one |
| 1.1.0 | 2026-07-24 | AI (Claude Opus 4.8) | List endpoint widened (`applicants.applicant.list` → 1.1.0): `search` now spans email, contact number, and passport number and returns **relevance-ordered** results; new `country`, `country_code`, and `journey_stage` filters; both read shapes gained a `destinations` array. **Added `applicant_journeys` to §2 `Requires`** — the first thing this module needs from another business app, and the reason §3's "ordering is fixed newest-first" is no longer unconditionally true |
| 1.1.1 | 2026-07-24 | AI (Claude Opus 4.8) | No endpoint or schema change — `HistoryEntry` already carried every field of the now-shared shape. Recorded that the shape is owned by the `audit` module and identical across all six modules with a history endpoint, and corrected §2 `Requires`: the `audit` coupling is a read dependency as well as a write one |
| 1.2.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (`full_name` on Applicant, FamilyMember, EmergencyContact). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |
| 1.2.1 | 2026-08-17 | AI (Claude Fable 5) | No endpoint or schema change. List filters are now validated before any query runs: malformed values (non-UUID `country`, unknown enum, unconvertible `fiscal_year`) return 400 with field details instead of a 500 or a silently empty page — §3 conventions updated |
| 1.3.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Applicant notes** (`/applicants/<id>/notes/[<note_id>/]`: General/Visit, backdatable, author-or-Admin edit and soft delete; a converted lead's notes arrive here). **Admin-only `POST /applicants/<id>/restore/`** returns an archived applicant to the status held before; `status/` can still archive but **no longer un-archives** (409 `APPLICANTS_APPLICANT_ARCHIVED`) — an approved access change for Lead Managers. Archived applicants' notes are read-only |
| 1.4.0 | 2026-10-29 | AI (Claude Opus 5.5) | The applicant now holds **`educations`** and **`language_tests`** (nested collections, replaced wholesale like `family_members`), plus `citizenship_no`, `citizenship_issue_district`, `national_id_no`; family members gain `citizenship_no` and the `grandfather`/`grandmother` relationships. A converted lead's qualification and certificates arrive as these records. New errors `APPLICANTS_EDUCATION_INVALID` and `APPLICANTS_LANGUAGE_TEST_INVALID` (`details.fields`). Identity numbers are withheld from the audit log (`<changed>`). Additive |
| 1.5.0 | 2026-10-29 | AI (Claude Opus 5.5) | **Optional assignment** — both read shapes gain `assigned_to` (UserBrief or `null`); new list filter `?assigned_to=me|none|<user id>`; new `POST /applicants/<id>/assign/` (`applicants.applicant.assign`) with errors `APPLICANTS_ASSIGNEE_INVALID` (400) and `APPLICANTS_ASSIGNMENT_FORBIDDEN` (403); `HistoryEntry.action` gains `applicant_assigned`/`applicant_unassigned`. Routing only — access is unchanged. A converted applicant is assigned to the lead's owner. **New side effects:** status change, restore, visit notes, and assignment now raise notifications (`notifications` module). §2 gains the assignee lookup in `authenticate`. Additive |

---

## 1. Module

- **Name:** Applicants — the permanent record of a person the consultancy works with. Holds identity (including citizenship and national ID numbers), contact details, addresses, passport, family, emergency contacts, education records, and language-test results, plus an **optional assignee** — the one staff member notified about the file. It does not hold study plans — those are journeys.
- **Base path:** `/api/v1/applicants/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. Two authority types may use this module: `admin` and `lead_manager`. A `superadmin` token is rejected with 403 everywhere.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which decides whether the caller may read, edit, or create. | Every endpoint returns 401. Without a recognised `authority_type` the caller gets 403 `APPLICANTS_ACTOR_FORBIDDEN`. |
| `authenticate` | FK | `created_by` references a user account. | Applicants cannot be created; attribution is unresolvable. |
| `authenticate` | FK + service call | `assigned_to` references a user account, and `POST /assign/` resolves the requested assignee through authenticate's active-user lookup (an unknown or deactivated id is rejected). | `POST /assign/` cannot resolve anyone and answers 400 `APPLICANTS_ASSIGNEE_INVALID`; `assigned_to` cannot be rendered. Every other endpoint is unaffected. |
| `audit` | service call + read shape | Every mutation appends one immutable event; the history endpoint reads that log back through audit's selector and renders audit's shared entry shape. This module stores no history of its own. | Hard dependency in both directions of use — without it this module does not start. If only the write path failed, `GET /api/v1/applicants/<id>/history/` would return an empty list — the change history disappears, though the applicant itself still works. |
| `applicant_journeys` | reverse FK read | An applicant has **no destination of its own** — the destination belongs to the study plan. The `destinations` array on both read shapes, and the `country`, `country_code`, and `journey_stage` list filters, are all read back through the journeys that point here. | The three filters always return an empty page and `destinations` is always `[]`. Nothing else degrades: creating, reading, editing, and archiving an applicant work with no journey in the system, and a person with no journey is a normal, fully functional record today. |
| `institutions` | indirect FK read | `destinations[].country_id` / `country_code` / `country_name` are the catalogue country the journey targets. This module never queries the catalogue itself; it reads what the journey already points at. | The three country fields are `null`/`""` and `?country=`/`?country_code=` match nothing. `target_country` — the free text the destination was typed as — still resolves, and is the only destination a pre-catalogue journey ever had. |

**This module depends on `notifications` for nothing.** A status change, restore, visit note, or assignment announces a domain event once its write has committed; the `notifications` module listens and decides who is told. If notifications is absent or fails, the write still succeeds and the response is identical — only the alert is missing.

**This module depends on `leads` for nothing.** An applicant can be created, read, edited, and archived with no lead in the system. The relationship runs the other way: `leads` calls this module to create an applicant during conversion — and to copy the lead's notes onto it — and `leads` owns the link between the two. A copied note's `source_lead_id` is a bare id, not a link this module follows. `originating_lead_id` on the detail response is read back through that link and is simply `null` for a directly created applicant.

## 3. Conventions

- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`.

```json
{
  "success": true,
  "message": "Applicant retrieved.",
  "data": { "id": "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5", "status": "active" },
  "meta": {}
}
```

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object holding field-level problems.

```json
{
  "success": false,
  "error": {
    "code": "APPLICANTS_PASSPORT_EXPIRY_INVALID",
    "message": "Passport expiry must fall after its issue date.",
    "details": { "passport": { "expiry_date": ["Must be later than the issue date."] } }
  },
  "meta": {}
}
```

- **Per-entry errors on `educations` and `language_tests`** use a different `details` shape: a flat `fields` map from the entry's path (`<collection>[<index>].<field>`, index counted from 0 in the list you sent) to **one message string**, not a list. Every failing field of every entry is reported at once, and nothing is written.

```json
{
  "success": false,
  "error": {
    "code": "APPLICANTS_LANGUAGE_TEST_INVALID",
    "message": "One or more language tests are invalid.",
    "details": {
      "fields": {
        "language_tests[1].overall_score": "Must be between 0 and 9 for IELTS.",
        "language_tests[1].expiry_date": "Must be after test_date."
      }
    }
  },
  "meta": {}
}
```

- **Auth failures:** 401 with no token, an expired token, or a revoked session — produced by the authentication framework, not this module. 403 `APPLICANTS_ACTOR_FORBIDDEN` when the token is valid but the authority may not act: a `superadmin` on any endpoint, or a `lead_manager` on create.
- **Pagination:** page-number based. Params `page` and `page_size` (default 20, max 100). `meta` carries `count`, `page`, `page_size`, `next`, `previous`; the last two are absolute URLs or `null`. Applied to the applicant list and the history list. There are no unpaginated list endpoints in this module.
- **IDs:** UUID strings.
- **Times:** ISO 8601 UTC for datetimes; `YYYY-MM-DD` for dates. Every user-facing **date** carries a `<field>_bs` sibling holding a Bikram Sambat object. `created_at` and `updated_at` never do.
- **List/search/filter/order params:** on `GET /api/v1/applicants/` only — `status`, `creation_source`, `search`, `country`, `country_code`, `journey_stage`, `fiscal_year` (`YYYY/YY`), `assigned_to` (`me`, `none`, or a user UUID). They compose: supplying several narrows the same result set rather than one replacing another. Malformed values are **rejected with 400, not ignored**: a non-UUID `country`, an unknown enum value, an `assigned_to` that is neither `me`, `none`, nor a UUID, or a `fiscal_year` that does not convert returns the standard validation error with the field named in `error.details`. A well-formed but unknown id returns an empty page and 200. There is no client-controlled ordering anywhere in this module, but the server's ordering is **not** unconditionally newest-first — see below.
- **Ordering.** Every list is newest-first **except** `GET /api/v1/applicants/?search=…`, which is ordered by relevance and only tie-broken by recency. Do not assume `data[0]` is the most recently created applicant when you passed a `search`.
- **What `search` matches.** The `full_name`, the `email`, **any** of the applicant's contact numbers, and the passport number. All partial, case-insensitive, substring matches. It is **not** fuzzy: a misspelling matches nothing, and there is no did-you-mean.
- **How `search` ranks.** `3` the name equals the query, `2` the name starts with it, `1` the name contains it, `0` matched only on email, contact number, or passport. Ties fall to newest-first, then id. The score itself is not returned in the response — only the order reflects it.

## 4. Models

**BsDate** — `{ year, month, day, month_name, display }`

- Never sent by a client; appears only as the value of a `<field>_bs` key.

**UserBrief** — `{ id, username, display_name }`

**ContactNumber** — `{ id, number, label:[enum], is_primary }`

**Address** — `{ id, address_type:[enum], country, province, district, municipality, ward, street_address, postal_code }`

- At most one per `address_type` per applicant. Every component except `address_type` is optional.

**Passport** — `{ passport_number, issuing_country, place_of_issue, issued_date?, issued_date_bs?:BsDate, expiry_date?, expiry_date_bs?:BsDate }`

- Has no `id` in the response — it is a one-per-applicant record, not a collection member.
- `expiry_date` is the operationally important field; an expiring passport can block a visa application.

**FamilyMember** — `{ id, relationship:[enum], full_name, occupation, contact_number, citizenship_no }`

**EmergencyContact** — `{ id, full_name, relationship, contact_number, email, address }`

- `relationship` here is **free text**, unlike `FamilyMember.relationship` which is an enum — an emergency contact may be a friend, landlord, or colleague.

**Destination** — `{ journey_id, stage:[enum], country_id?, country_code, country_name, target_country }`

- One entry per journey the applicant holds. **Not owned by this module** — it is a read-only projection of `applicant_journeys`.
- `stage` is an `applicant_journeys` `JourneyStage` value, not an applicant status. The two lifecycles are independent: a journey reaching `closed` does not archive the applicant.
- `country_id`, `country_code`, and `country_name` are `null`/`""` together for a journey with no catalogue link. In that case `target_country` — free text — is the **only** destination that journey has. Render `country_name || target_country`.
- Use `journey_id` to call the `applicant_journeys` module; this module exposes no journey endpoints.

**Applicant (list shape)** — `{ id, full_name, date_of_birth?, date_of_birth_bs?:BsDate, gender:[enum], nationality, email, status:[enum], creation_source:[enum], created_by:UserBrief, assigned_to?:UserBrief, contact_numbers:[ContactNumber], destinations:[Destination], created_at, updated_at }`

- `assigned_to` is the staff member notified about this applicant, or `null` when nobody is assigned. It is **never an access control** — every Admin and Lead Manager reads and edits every applicant whoever it names. Set only through `POST /assign/` (or by lead conversion).

**Applicant (detail shape)** — the list shape plus `{ citizenship_no, citizenship_issue_district, national_id_no, addresses:[Address], passport?:Passport, family_members:[FamilyMember], emergency_contacts:[EmergencyContact], educations:[Education], language_tests:[LanguageTest], originating_lead_id? }`

**Education** — `{ id, level:[enum], qualification, institution, country, completion_status:[enum], score?:decimal-string, score_type:[enum], grading_system, start_year?:int, completion_year?:int, year_calendar:[enum], source_lead_id? }`
- `qualification` is the programme or stream ("BBS", "Science"); `level` is where it sits on the ladder. `grading_system` is how the score reads ("GPA (4.0)", "First Division").
- Years are bare years **in `year_calendar`** (`bs` or `ad`) — a BS year spans two AD years, so the calendar is part of the value. `source_lead_id` is set on the record carried over from a converted lead.

**LanguageTest** — `{ id, test_type:[enum], overall_score?, listening_score?, reading_score?, writing_score?, speaking_score?, test_date?, test_date_bs?:BsDate, certificate_number, expiry_date?, expiry_date_bs?:BsDate, source_lead_id? }`
- Scores are decimal strings with one place (`"7.0"`, `"65.0"`); any may be `null`. `source_lead_id` is set on tests carried over from a converted lead's certificates.

- The detail shape is returned by retrieve, create, update, **and** the status, restore, and assign actions. Only the list returns the shorter shape.
- `passport` is `null` when the applicant has none.
- `destinations` is `[]` for a person with no journey yet — a normal, common state, not an error and not a permission problem. It appears on **both** shapes.
- `originating_lead_id` is the id of the lead this applicant was converted from, or `null` when created directly. It is a bare id string, not an object — fetch the lead from the `leads` module if you need more.

**ApplicantNote** — `{ id, category:[enum], body, noted_at, noted_at_bs:BsDate, is_backdated:bool, source_lead_id?, author:UserBrief, updated_by?:UserBrief, created_at, updated_at }`

- Same shape as a lead note (`leads/docs/INTEGRATION.md` §4) plus `source_lead_id`, which is set on notes carried over from the lead this applicant was converted from (their `created_at` is the original one, so `is_backdated` stays truthful).
- `noted_at` is when it happened, set by the user; `created_at` is when it was saved. `is_backdated` is `true` when `created_at` is more than 15 minutes after `noted_at`.

**HistoryEntry** — `{ id, action:[enum], actor_type:[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:BsDate }`

- Owned by the `audit` module, where the same shape is called **AuditEventHistoryEntry** (`audit/docs/INTEGRATION.md` §4). This module renders it; it does not define it. Every module's `/history/` endpoint returns this identical shape, so one renderer serves all of them.
- `changes` maps a field name to `{ from, to }`, and is `{}` for actions with no field-level diff. On `applicant_assigned`/`applicant_unassigned`, `changes.assigned_to` is `{ from, to }` with user ids (or `null`), not names.
- Passport numbers, address text, and family names are deliberately **never** present in `changes` or `metadata`.

### Worked examples

**ApplicantNote** (carried over from a lead)

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

**Applicant (detail shape)**

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
  "contact_numbers": [
    { "id": "c1c2c3c4-0000-1111-2222-333344445555", "number": "9800000000", "label": "mobile", "is_primary": true }
  ],
  "addresses": [
    {
      "id": "a1a2a3a4-0000-1111-2222-333344445555",
      "address_type": "permanent",
      "country": "Nepal",
      "province": "Bagmati",
      "district": "Lalitpur",
      "municipality": "Lalitpur Metropolitan City",
      "ward": "5",
      "street_address": "",
      "postal_code": ""
    }
  ],
  "passport": {
    "passport_number": "PA1234567",
    "issuing_country": "Nepal",
    "place_of_issue": "Kathmandu",
    "issued_date": "2022-01-01",
    "issued_date_bs": {
      "year": 2078, "month": 9, "day": 17,
      "month_name": "Poush",
      "display": "2078 Poush 17"
    },
    "expiry_date": "2032-01-01",
    "expiry_date_bs": {
      "year": 2088, "month": 9, "day": 17,
      "month_name": "Poush",
      "display": "2088 Poush 17"
    }
  },
  "family_members": [
    {
      "id": "f1f2f3f4-0000-1111-2222-333344445555",
      "relationship": "father",
      "full_name": "Hari Shrestha",
      "occupation": "Teacher",
      "contact_number": "9841111111",
      "citizenship_no": "27-01-50-00001"
    }
  ],
  "emergency_contacts": [
    {
      "id": "e1e2e3e4-0000-1111-2222-333344445555",
      "full_name": "Gita Shrestha",
      "relationship": "Aunt",
      "contact_number": "9812345678",
      "email": "",
      "address": ""
    }
  ],
  "educations": [
    {
      "id": "0a1b2c3d-4e5f-4607-8192-a3b4c5d6e7f8",
      "level": "bachelor",
      "qualification": "BBS",
      "institution": "Shanker Dev Campus",
      "country": "Nepal",
      "completion_status": "completed",
      "score": "3.45",
      "score_type": "gpa",
      "grading_system": "GPA (4.0)",
      "start_year": 2076,
      "completion_year": 2080,
      "year_calendar": "bs",
      "source_lead_id": "9d8c7b6a-5e4f-3021-a1b2-c3d4e5f60718"
    }
  ],
  "language_tests": [
    {
      "id": "1b2c3d4e-5f60-4718-92a3-b4c5d6e7f809",
      "test_type": "ielts",
      "overall_score": "7.0",
      "listening_score": "7.5",
      "reading_score": "6.5",
      "writing_score": "6.5",
      "speaking_score": "7.0",
      "test_date": "2025-03-01",
      "test_date_bs": { "year": 2081, "month": 11, "day": 17, "month_name": "Falgun", "display": "2081 Falgun 17" },
      "certificate_number": "25NP000123",
      "expiry_date": "2027-03-01",
      "expiry_date_bs": { "year": 2083, "month": 11, "day": 17, "month_name": "Falgun", "display": "2083 Falgun 17" },
      "source_lead_id": null
    }
  ],
  "citizenship_no": "27-01-75-12345",
  "citizenship_issue_district": "Kathmandu",
  "national_id_no": "",
  "originating_lead_id": "9d8c7b6a-5e4f-3021-a1b2-c3d4e5f60718",
  "created_at": "2026-07-23T05:00:00Z",
  "updated_at": "2026-07-23T05:00:00Z"
}
```

**Paginated applicant list**

```json
{
  "success": true,
  "message": "",
  "data": [
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
      "assigned_to": null,
      "contact_numbers": [
        { "id": "c1c2c3c4-0000-1111-2222-333344445555", "number": "9800000000", "label": "mobile", "is_primary": true }
      ],
      "destinations": [
        {
          "journey_id": "1f2e3d4c-5b6a-7089-9a8b-7c6d5e4f3021",
          "stage": "offer_stage",
          "country_id": "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9",
          "country_code": "au",
          "country_name": "Australia",
          "target_country": ""
        },
        {
          "journey_id": "2a3b4c5d-6e7f-8091-a2b3-c4d5e6f70819",
          "stage": "closed",
          "country_id": null,
          "country_code": "",
          "country_name": "",
          "target_country": "Canada"
        }
      ],
      "created_at": "2026-07-23T05:00:00Z",
      "updated_at": "2026-07-23T05:00:00Z"
    }
  ],
  "meta": {
    "count": 128,
    "page": 1,
    "page_size": 20,
    "next": "https://api.example.com/api/v1/applicants/?page=2",
    "previous": null
  }
}
```

**HistoryEntry**

```json
{
  "id": "b0b1b2b3-1234-5678-9abc-def012345678",
  "action": "applicant_status_changed",
  "actor_type": "lead_manager",
  "actor_id": "aaaa1111-2222-3333-4444-555566667777",
  "actor_label": "leadmgr",
  "summary": "Status changed from active to dormant.",
  "reason": "",
  "changes": { "status": { "from": "active", "to": "dormant" } },
  "metadata": {},
  "created_at": "2026-07-23T06:30:00Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name": "Shrawan",
    "display": "2083 Shrawan 8"
  }
}
```

## 5. Enums

- `Applicant.status`: `active` | `dormant` | `archived`
- `Applicant.creation_source`: `lead_conversion` | `direct_admin`
- `Applicant.gender`: `male` | `female` | `other` | `undisclosed` | `""`
- `Address.address_type`: `permanent` | `current`
- `ContactNumber.label`: `mobile` | `home` | `work` | `whatsapp` | `viber` | `other`
- `FamilyMember.relationship`: `father` | `mother` | `spouse` | `sibling` | `child` | `guardian` | `grandfather` | `grandmother` | `other`
- `Education.level`: `see` (SEE / SLC) | `plus_two` (+2 / NEB) | `diploma` | `bachelor` | `master` | `phd` | `other` — shared with the lead's `highest_qualification_level`
- `Education.completion_status`: `completed` | `ongoing`
- `Education.score_type`: `gpa` | `percentage` | `""`
- `Education.year_calendar`: `bs` | `ad` | `""`
- `LanguageTest.test_type`: `ielts` | `pte` | `toefl` | `duolingo` | `other` — shared with lead certificates
- `EmergencyContact.relationship`: **not an enum** — free text.
- `Destination.stage`: `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage` | `completed` | `closed` | `deferred` — owned by `applicant_journeys`, not this module. Also the accepted values for the `?journey_stage=` filter.
- `HistoryEntry.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `ApplicantNote.category`: `general` | `visit` (shared with lead notes; may gain values such as `call`)
- `HistoryEntry.action`: `applicant_created` | `applicant_updated` | `applicant_contact_changed` | `applicant_address_changed` | `applicant_passport_changed` | `applicant_family_changed` | `applicant_emergency_contact_changed` | `applicant_status_changed` | `applicant_restored` | `applicant_note_added` | `applicant_note_updated` | `applicant_note_deleted` | `applicant_notes_imported` | `applicant_education_changed` | `applicant_language_tests_changed` | `applicant_assigned` | `applicant_unassigned`
- `?assigned_to=` filter literals: `me` (the caller) | `none` (unassigned) — or a user UUID

## 6. Dependency order

- `Applicant` needs an authenticated **Admin** account *(other module: `authenticate`)* — a Lead Manager cannot create one.
- `ContactNumber`, `Address`, `Passport`, `FamilyMember`, `EmergencyContact` all need `Applicant` — each is sent nested in the applicant payload, never created on its own.
- `ApplicantNote` needs an `Applicant` that is not archived (reads work on any applicant).
- `HistoryEntry` needs `Applicant` and is never created by a client.
- An assignment needs an `Applicant` that is not archived and an **active Admin or Lead Manager** account to assign *(other module: `authenticate`)*.
- An applicant may alternatively arrive from `POST /api/v1/leads/<id>/convert/` *(other module: `leads`)*, which creates it plus an initial journey in one call.

**Start here:** `POST /api/v1/applicants/` as an Admin, or convert an existing lead. Nothing else in this module needs to exist first.

## 7. Endpoints

### Applicant — `/api/v1/applicants/`

**Use it when:** the applicant list/search screen, the create-applicant form, and the applicant file page.
**Methods:**
- `GET /api/v1/applicants/` — list every applicant (permission: `applicants.applicant.list`, risk: low)
- `POST /api/v1/applicants/` — create one directly (permission: `applicants.applicant.create`, risk: high)
- `GET /api/v1/applicants/<applicant_id>/` — retrieve one (permission: `applicants.applicant.read`, risk: low)
- `PATCH /api/v1/applicants/<applicant_id>/` — correct one (permission: `applicants.applicant.update`, risk: medium)

**Send (create/update):**
- create: `full_name` (required), `date_of_birth`, `gender`, `nationality`, `email`, `citizenship_no`, `citizenship_issue_district`, `national_id_no` (free text, at most 50, 100, and 50 characters respectively), `contact_numbers` (required, at least one), `addresses`, `passport`, `family_members` (each may carry `citizenship_no`), `emergency_contacts`, `educations`, `language_tests`
- `educations[]`: `level` (required), `qualification`, `institution`, `country`, `completion_status` (default `completed`), `score` + `score_type` (together; gpa 0–4, percentage 0–100), `grading_system`, `start_year`, `completion_year`, `year_calendar` (required when a year is given; a BS year must lie between 2000 and the current BS year + 1, an AD year between 1950 and the current AD year + 1, "current" judged in Nepal time; start ≤ completion; an `ongoing` record has no `completion_year`)
- `language_tests[]`: `test_type` (required), `overall_score`, `listening_score`, `reading_score`, `writing_score`, `speaking_score` (each optional; IELTS 0–9 in 0.5 steps, PTE 10–90, TOEFL 0–120, Duolingo 10–160, other ≥0), `test_date` (not in the future), `certificate_number`, `expiry_date` (after `test_date`)
- scores (`score` and every language-test score) may be sent as a JSON number or a decimal string (`7`, `7.0`, `"7.0"`); they are always returned as decimal strings
- `source_lead_id` is not writable on either collection — a client-supplied list never carries it
- update: any subset of the same fields, all optional

**Returns:** Applicant (detail shape) for create, retrieve, and update; list[Applicant (list shape)] for the list, paginated.
**Requires state:**
- an authenticated Admin or Lead Manager for read and update; an authenticated **Admin** for create. No other resource needs to exist first.
- for the list: nothing. But `?country=`, `?country_code=`, and `?journey_stage=` match only applicants who **already have a journey** — an applicant created a moment ago has none and is invisible to all three until one is opened through the `applicant_journeys` module.

**Side effects:**
- create — appends `applicant_created` to the audit log; its `metadata.assigned_to` is the assignee's id, or `null` (always `null` for a direct create).
- update — appends `applicant_updated` when scalar fields moved, plus one further event per nested collection actually supplied (`applicant_contact_changed`, `applicant_address_changed`, `applicant_passport_changed`, `applicant_family_changed`, `applicant_emergency_contact_changed`, `applicant_education_changed`, `applicant_language_tests_changed`). Scores never appear in the audit log — only a count. A `PATCH` that changes nothing writes no event.
- list and retrieve — none, these are reads.

**Notes:**
- **Shared, not owner-scoped.** Every Admin and Lead Manager sees and edits every applicant — including applicants assigned to someone else. `assigned_to` changes who is notified, never who may see. This deliberately differs from `leads`, where a Lead Manager sees only their own records.
- **Creation is Admin-only**, by both paths. Editing is not — a Lead Manager who may not admit someone to the lifecycle may still maintain their file.
- All seven sub-resources are nested in the payload; there are no standalone endpoints for them. Sending a collection **replaces it entirely** — always send the complete intended list, never a delta; `[]` clears it; omitting the key leaves it untouched. Sending `passport` upserts the single record. This includes `educations` and `language_tests`: to change one IELTS score, send every test back. **Resending a record carried over from a lead drops its `source_lead_id`** — replacement creates new rows, and the field is not writable — so the record no longer shows it came from the lead.
- `educations` are returned most recent `completion_year` first (`ongoing` records, which have none, come before all others), then oldest-entered first; `language_tests` most recent `test_date` first (undated tests first), then oldest-entered first.
- `citizenship_no` and `national_id_no` never enter the audit log: a change to either is recorded as `{"from": "<changed>", "to": "<changed>"}` in the `applicant_updated` event, the same way the passport number is withheld.
- `status`, `creation_source`, `created_by`, and `assigned_to` are not writable here; sending them is ignored, not rejected. A directly created applicant is always unassigned — use `POST /assign/`.
- **`?assigned_to=`** — `me` lists the caller's own caseload, `none` the unassigned applicants, a user UUID that person's. It composes with every other filter. A well-formed id of nobody returns an empty page.
- `search` matches the applicant's `full_name`, and also the email, any contact number, and the passport number.
- **A `search` result set is relevance-ordered, not newest-first.** See §3 for the scoring. Every other list is newest-first.
- **The country filters mean "has *a* journey there", not "is currently going there".** A person who tried for Australia, closed that journey, and is now applying to Canada matches `?country_code=au` **and** `?country_code=ca`. Read `destinations[].stage` to tell which is live; there is no "current destination" field and no filter for one.
- An applicant with two journeys to the same country is returned **once**, not twice.
- An unknown `country`/`country_code` returns an empty page with `200`, not a `400`. Do not treat empty as an invalid-input signal.
- Archived applicants still appear in the list — filter on `status` to exclude them.
- `originating_lead_id` appears only on the detail shape and is `null` for directly created applicants.

**Errors:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — a Superadmin called any method, or a Lead Manager attempted create
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id (always literal; never "not yours")
- `APPLICANTS_CONTACT_REQUIRED` (400) — no contact number supplied
- `APPLICANTS_PASSPORT_EXPIRY_INVALID` (400) — passport expiry is not after its issue date
- `APPLICANTS_EDUCATION_INVALID` (400) — an education entry breaks a rule; `error.details.fields` maps each `educations[i].field` to its message
- `APPLICANTS_LANGUAGE_TEST_INVALID` (400) — a language test breaks a rule; `error.details.fields` maps each `language_tests[i].field`
- `VALIDATION_ERROR` (400) — a field of the wrong type, an unknown enum value, a missing required key, or a malformed list filter (including `assigned_to`)

### Applicant status — `POST /api/v1/applicants/<applicant_id>/status/`

**Use it when:** the status control in the applicant file header.
**Methods:**
- `POST /api/v1/applicants/<applicant_id>/status/` — set the applicant's standing (permission: `applicants.applicant.change_status`, risk: medium)

**Send (create/update):**
- `status` (required) — `active`, `dormant`, or `archived`

**Returns:** Applicant (detail shape)
**Requires state:** the applicant must exist and must **not** be archived — leaving `archived` is the restore action below. No journey state is consulted.
**Side effects:**
- appends `applicant_status_changed` with `changes.status = {from, to}`. Setting the status it already holds is a no-op and writes no event. Moving to `archived` also remembers the status it left, for restore.
- raises an `applicant_status_changed` notification *(other module: `notifications`)* to the assignee and every Admin — or, when the applicant is unassigned, to every Admin and Lead Manager — never to the caller. Sent after the write commits; a notification failure never affects this response. A no-op raises nothing.
- **Nothing else changes** — in particular, no journey is opened or closed.
**Notes:**
- Status is always manual. It is never changed automatically by journey activity, and archiving an applicant does not close their journeys.
- Admins and Lead Managers may archive. **Only an Admin can un-archive**, through `POST /restore/`. (Before 1.3.0 this endpoint could set any status from any status.)
- Archiving deletes nothing and is fully reversible by an Admin. The UI may call it "Delete"; keep user-facing wording neutral ("This applicant has been deleted").
- Archival is not a privacy control: an archived applicant is still visible to every lead actor and still appears in unfiltered lists (`?status=archived` lists only them).

**Errors:**
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id
- `APPLICANTS_APPLICANT_ARCHIVED` (409) — the applicant is archived and a different status was requested; an Admin must restore them

### Applicant restore — `POST /api/v1/applicants/<applicant_id>/restore/`

**Use it when:** an Admin brings back an archived ("deleted") applicant.
**Methods:**
- `POST /api/v1/applicants/<applicant_id>/restore/` — un-archive (permission: `applicants.applicant.restore`, risk: medium)

**Send (create/update):**
- `reason` (optional, ≤2000 characters)

**Returns:** Applicant (detail shape) with `status` back to what it was before archiving — `active` or `dormant`; `active` for applicants archived before 2026-10-29, whose prior status was not recorded.
**Requires state:** the caller is an **Admin** and the applicant is archived.
**Side effects:**
- appends `applicant_restored` with the reason and `changes.status = {from: "archived", to}`.
- raises an `applicant_restored` notification *(other module: `notifications`)* — same recipients as a status change: the assignee and every Admin, or every Admin and Lead Manager when unassigned, never the caller.
- Journeys, notes, and every sub-record are untouched — archiving destroyed nothing, so restoring recreates nothing.
**Notes:**
- There is no "merged duplicate" state in this module, so no restore is ever refused for that reason.

**Errors:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — the caller is not an Admin
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id
- `APPLICANTS_APPLICANT_NOT_ARCHIVED` (409) — the applicant is not archived
- `VALIDATION_ERROR` (400) — `reason` too long

### Applicant assignment — `POST /api/v1/applicants/<applicant_id>/assign/`

**Use it when:** the "Assigned to" control in the applicant file header — an Admin picks a person or clears it; a Lead Manager sees "Take" on an unassigned file and "Release" on their own.
**Methods:**
- `POST /api/v1/applicants/<applicant_id>/assign/` — set or clear the assignee (permission: `applicants.applicant.assign`, risk: medium)

**Send (create/update):**
- `assigned_to` (required key) — a user UUID, or `null` to clear. Omitting the key is a 400 `VALIDATION_ERROR`. There is no `me` shorthand here (unlike the list filter): a Lead Manager taking a file sends their own `id` from `GET /api/v1/auth/me/` *(other module: `authenticate`, `User.id`)*.

**Returns:** Applicant (detail shape), message `Applicant assignment updated.`
**Requires state:**
- the caller is an Admin or Lead Manager, the applicant exists and is **not archived**.
- a non-null `assigned_to` is an **active Admin or Lead Manager** account.
- an **Admin** may assign anyone eligible, reassign, or clear. A **Lead Manager** may only take an **unassigned** applicant for themselves (`assigned_to` = their own id) or release one they currently hold (`assigned_to: null`).

**Side effects:**
- appends `applicant_assigned` (new assignee set) or `applicant_unassigned` (cleared) with `changes.assigned_to = {from, to}` (user ids or `null`).
- raises notifications *(other module: `notifications`)*: `applicant_assigned` to the new assignee and `applicant_unassigned` to the previous one — never to the caller, so a Lead Manager taking a file is not told about it. Sent after the write commits; a notification failure never affects this response.
- sending the current value is a no-op for any caller: 200, nothing written, nothing raised. That includes a Lead Manager sending `null` for an applicant nobody holds.
- from then on the assignee receives this applicant's status, restore, visit-note, journey, passport-expiry, language-test-expiry, and reminder alerts (`notifications` routing).

**Notes:**
- **Routing only.** Assignment never grants or removes access; every Admin and Lead Manager keeps full read and write access to the applicant. Small teams can ignore it entirely — an unassigned applicant's alerts go to the whole team.
- A Superadmin can never be assigned (they do not work files) — 400 `APPLICANTS_ASSIGNEE_INVALID`.
- An archived applicant is frozen: restore it first.
- **Check order**, so a request with several problems always gets the same answer: authentication (401) → Superadmin caller (403 `APPLICANTS_ACTOR_FORBIDDEN`) → applicant exists (404) → body shape (400 `VALIDATION_ERROR`) → assignee eligible (400 `APPLICANTS_ASSIGNEE_INVALID`) → applicant archived (409) → Lead Manager take/release rule (403 `APPLICANTS_ASSIGNMENT_FORBIDDEN`).
- A converted applicant arrives already assigned to the lead's owner, when that person is still an active Admin or Lead Manager; otherwise it arrives unassigned.

**Errors:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — a Superadmin called it
- `APPLICANTS_ASSIGNMENT_FORBIDDEN` (403) — a Lead Manager tried to assign someone else, to take an applicant someone else holds, or to clear an applicant someone else holds. Message `"A Lead Manager may only take an unassigned applicant or release their own."`, `details: {}`
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id
- `APPLICANTS_ASSIGNEE_INVALID` (400) — the assignee is not an active Admin or Lead Manager (unknown id, deactivated, or a Superadmin); `error.details` is `{ "assigned_to": ["…"] }`
- `APPLICANTS_APPLICANT_ARCHIVED` (409) — the applicant is archived
- `VALIDATION_ERROR` (400) — `assigned_to` missing or not a UUID/`null`

### Applicant Note — `/api/v1/applicants/<applicant_id>/notes/`

**Use it when:** the notes panel on the applicant file — a "General" tab and a "Visit" tab.
**Methods:**
- `GET /api/v1/applicants/<applicant_id>/notes/` — list notes (permission: `applicants.note.list`, risk: low)
- `POST /api/v1/applicants/<applicant_id>/notes/` — write a note (permission: `applicants.note.create`, risk: low)
- `PATCH /api/v1/applicants/<applicant_id>/notes/<note_id>/` — correct a note (permission: `applicants.note.update`, risk: medium)
- `DELETE /api/v1/applicants/<applicant_id>/notes/<note_id>/` — remove a note (permission: `applicants.note.delete`, risk: medium)

**Send (create/update):**
- create: `body` (required, ≤10 000 characters, not blank), `category` (`general` default, or `visit`), `noted_at` (optional ISO 8601 datetime, default now; may be in the past, never more than 5 minutes in the future)
- update: any subset of `category`, `body`, `noted_at` — same rules

**Returns:** `ApplicantNote` for create and update; list[`ApplicantNote`], paginated, for the list; `data: null` for delete.
**Requires state:**
- read: the applicant exists. Admins and Lead Managers alike — the same access as the applicant record.
- write: the applicant is **not archived**. Update and delete also need the caller to be the note's **author or an Admin**.

**Side effects:**
- appends `applicant_note_added`, `applicant_note_updated` (with `changes`; `body` shows only `<changed>`), or `applicant_note_deleted` to the applicant's history, each with `metadata: { note_id, category, noted_at, is_backdated }`. The note text is never copied into the audit log. Delete is soft — the note leaves the list but the row and its history remain.
- creating a **`visit`** note raises a `visit_note_added` notification *(other module: `notifications`)* to the assignee only — or, when the applicant is unassigned, to every Admin and Lead Manager — never the author. The alert carries the note id, never its text. `general` notes, edits, and deletes raise nothing.
**Notes:**
- **List params:** `category` (`general`|`visit`), `ordering` (`-noted_at` default, `noted_at`, `-created_at`), `page`, `page_size`.
- **`meta.counts`** — `{ "general": n, "visit": n }` on every list response, counting live notes regardless of the `category` filter.
- **Send `noted_at` with a UTC offset.** A value without one is read as **Nepal time** (Asia/Kathmandu, +05:45), never UTC.
- Notes converted from a lead arrive with `source_lead_id` set and keep their author and original timestamps; they are ordinary notes from then on (editable by their author or an Admin).

**Errors:**
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id
- `APPLICANTS_NOTE_NOT_FOUND` (404) — no such note on this applicant, or it was deleted
- `APPLICANTS_NOTE_FORBIDDEN` (403) — editing or deleting someone else's note without Admin authority
- `APPLICANTS_NOTE_FUTURE_DATE` (400) — `noted_at` is later than now (+5 min)
- `APPLICANTS_APPLICANT_ARCHIVED` (409) — any note write while the applicant is archived
- `VALIDATION_ERROR` (400) — blank or over-long `body`, unknown `category` or `ordering`

### Applicant History — `GET /api/v1/applicants/<applicant_id>/history/`

**Use it when:** the activity panel on the applicant file page.
**Methods:**
- `GET /api/v1/applicants/<applicant_id>/history/` — the applicant's change history (permission: `applicants.applicant.list_history`, risk: low)

**Send (create/update):** none
**Returns:** list[HistoryEntry], paginated, newest first
**Requires state:** the applicant must exist.
**Side effects:** none — this is a read.
**Notes:**
- Written by the server on every mutation; a client never creates entries.
- Entries are immutable and are never rewritten or removed.
- `changes` is populated only for scalar identity and status changes. Nested-collection events carry a count in `metadata` instead — render `summary` as the primary label for every action.
- Sensitive values are never present: no passport numbers, no address text, no family names.

**Errors:**
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id

## 8. Flows

**Create an applicant directly** *(Admin only)*
1. `POST /api/v1/applicants/` with `full_name` and at least one contact number → capture `applicant.id`. `creation_source` reads `direct_admin`.
   - `APPLICANTS_ACTOR_FORBIDDEN`: the caller is a Lead Manager — this path is Admin-only.
   - `APPLICANTS_CONTACT_REQUIRED` or a 400 on `contact_numbers`: at least one number is mandatory.
2. `PATCH /api/v1/applicants/<applicant.id>/` to fill in passport, addresses, and family as they become known. Each collection is sent complete.
3. `POST /api/v1/journeys/` with `applicant: <applicant.id>` *(other module: `applicant_journeys`)* to record what they are actually trying to do — an applicant with no journey has no objective.

**Arrive via lead conversion** *(crosses into `leads`)*
1. `POST /api/v1/leads/<lead_id>/convert/` *(other module: `leads`)* → returns `applicant_id` and `journey_id`.
   - `LEADS_LEAD_ALREADY_CONVERTED`: this lead already produced an applicant; fetch it rather than retrying.
2. `GET /api/v1/applicants/<applicant_id>/` → identity and contact numbers were copied from the lead; `creation_source` reads `lead_conversion` and `originating_lead_id` points back. `assigned_to` is the lead's owner — or `null` if that person is no longer an active Admin or Lead Manager.
3. `PATCH /api/v1/applicants/<applicant_id>/` to add the detail a lead never carried — passport, date of birth, family, emergency contacts.

**Find a person you have something about but not a name**
1. `GET /api/v1/applicants/?search=<the fragment you have>` → matches the name, the email, any contact number, and the passport number. Results are relevance-ordered, so an exact name match is `data[0]`.
   - Empty `data` with `meta.count = 0`: nothing matched. The search is substring-based, not fuzzy, so a misspelling matches nothing — retry with a shorter fragment rather than a corrected guess.
2. Read `destinations` on each row to disambiguate two people with the same name by where each is headed.
3. `GET /api/v1/applicants/<applicant.id>/` → the full record.

**Work a destination cohort** *(what the country filter is for)*
1. `GET /api/v1/catalogue/countries/` *(other module: `institutions`)* → capture the `id` or `code` of the destination.
2. `GET /api/v1/applicants/?country_code=au&status=active` → every active applicant with a journey to Australia. Filters compose; add `journey_stage=offer_stage` to narrow to those awaiting a decision.
   - Empty page and `200`: either nobody matches, or the code does not exist. The two are indistinguishable — verify the code against step 1 rather than treating empty as an error.
   - A person appears here on the strength of **any** journey to that country, including a closed one. Read `destinations[].stage` before treating the row as live work.
3. `GET /api/v1/journeys/?applicant=<applicant.id>` *(other module: `applicant_journeys`)* → the journeys themselves, if you need more than the projected summary.

**Maintain a file over time**
1. `GET /api/v1/applicants/?search=Ram` → find the person by name.
2. `GET /api/v1/applicants/<applicant.id>/` → the full record.
3. `PATCH /api/v1/applicants/<applicant.id>/` with a complete `contact_numbers` list to add a number.
   - Sending only the new number silently drops the existing ones — this is replace, not append.
4. `GET /api/v1/applicants/<applicant.id>/history/` → confirm what changed and who changed it.

**Wind a file down, and bring it back**
1. `POST /api/v1/applicants/<applicant.id>/status/` with `{"status": "dormant"}` when there is no active work.
2. `POST /api/v1/applicants/<applicant.id>/status/` with `{"status": "archived"}` when the file is closed (or "deleted" in the UI).
3. If they return, an **Admin** calls `POST /api/v1/applicants/<applicant.id>/restore/` with an optional `{"reason": "…"}` → back to `dormant` (the status they left).
   - `APPLICANTS_ACTOR_FORBIDDEN`: a Lead Manager — hide the restore control for them.
   - Sending `{"status": "active"}` to `status/` instead returns `APPLICANTS_APPLICANT_ARCHIVED` (409).
   - Note their journeys were not touched by any of this; close those separately if appropriate.

**Keep notes on a file**
1. `GET /api/v1/applicants/<applicant.id>/notes/` → notes, newest event first; `meta.counts` feeds the General/Visit tab badges. After a conversion the lead's notes are already here (`source_lead_id` set).
2. `POST /api/v1/applicants/<applicant.id>/notes/` with `{"category": "visit", "body": "…", "noted_at": "2026-07-22T15:15:00+05:45"}`.
   - `APPLICANTS_APPLICANT_ARCHIVED`: the file is archived — notes are read-only until an Admin restores it.
3. `PATCH` / `DELETE /api/v1/applicants/<applicant.id>/notes/<note.id>/` to correct or remove — the author or an Admin only (`APPLICANTS_NOTE_FORBIDDEN` otherwise).

**Assign, take, or release an applicant**
1. `GET /api/v1/applicants/<applicant.id>/` → read `assigned_to` to decide which control to show.
2. Admin: `POST /api/v1/applicants/<applicant.id>/assign/` with `{"assigned_to": "<user id>"}` to assign or reassign, or `{"assigned_to": null}` to clear.
   - `APPLICANTS_ASSIGNEE_INVALID` (400): the person is not an active Admin or Lead Manager — refresh the picker.
3. Lead Manager: `POST /api/v1/applicants/<applicant.id>/assign/` with their own id when `assigned_to` is `null` (take), or with `null` when `assigned_to` is them (release).
   - `APPLICANTS_ASSIGNMENT_FORBIDDEN` (403): someone else holds it, or they named another person — ask an Admin to reassign.
   - `APPLICANTS_APPLICANT_ARCHIVED` (409): the file is archived — an Admin restores it first.
4. The new assignee receives an `applicant_assigned` notification and the previous one `applicant_unassigned` *(other module: `notifications`)*; the caller receives neither.

**Work my caseload**
1. `GET /api/v1/applicants/?assigned_to=me&status=active` → the active applicants assigned to the caller. Filters compose.
2. `GET /api/v1/applicants/?assigned_to=none` → the unassigned pool a Lead Manager may take from.
   - 400 `VALIDATION_ERROR`: the value was neither `me`, `none`, nor a UUID.
3. Open a row with `GET /api/v1/applicants/<applicant.id>/`. Being on someone else's caseload never hides an applicant — the unfiltered list still shows everyone.

## 9. Gaps

- **No photograph *on this resource*.** `concepts/applicants.txt` lists one; no file handling exists in this module and none is planned here. **Files live in `uploaded_files` (`/api/v1/files/`), which is now built** — upload with `applicant=<applicant_id>` and `category=photograph`, list with `GET /api/v1/files/?applicant=<applicant_id>&category=photograph`. Two caveats before you build an avatar: an applicant payload carries **no file reference at all**, and **nothing designates a primary photograph** — the filter can return several, and choosing among them is a client-side convention, not a backend rule.
- **Education is a core record only.** Education gaps, training courses, backlogs, and medium of instruction are not modelled (deferred, `concepts/education.txt`). Divisions and letter grades are only a `grading_system` label, not a validated score.
- **Language tests only.** SAT, GRE, and other standardized tests are out of scope; `other` accepts any non-negative score. Test types are a fixed enum, not a configurable list.
- **Editing one education or test means resending the whole list** — they replace wholesale, like every other sub-record here.
- **Citizenship and national ID numbers are not format-checked** and are not searchable.
- **No documents or files on this resource.** Documents live in `documents`, files in `uploaded_files`.
- **No duplicate detection or merging.** Two records for the same person can be created and nothing prevents or resolves it.
- **No field-level redaction.** Every lead actor who can read an applicant reads the whole record including passport and date of birth. Whether those should be Admin-only is unresolved.
- **Passport renewal history is not kept.** The record holds one current passport; a renewal overwrites it and only the audit event records that a change happened — not the previous number.
- **`HistoryEntry.metadata` keys are per-action and not exhaustively specified.** Observed keys: `creation_source`, `count` (on `applicant_education_changed` and `applicant_language_tests_changed`, the number of records now held). Treat as advisory display data.
- **No bulk operations and no export.** Each applicant is acted on individually — including assignment: there is no bulk reassign when someone leaves.
- **No assignee picker in this module.** Nothing here lists the eligible assignees. An Admin can list the accounts they manage through `GET /api/v1/auth/users/` *(other module: `authenticate`)*, which covers Lead Managers but not fellow Admins; a Lead Manager cannot list accounts and only ever assigns themselves.
- **A deactivated assignee stays on the record.** `assigned_to` keeps naming them until an Admin reassigns or clears it. For notification routing they count as nobody: the applicant's alerts fall back to the unassigned routing (the whole team for status and visit-note alerts, Admins for the rest).
- **`nationality` is free text** with no validation or canonical list, so values will vary in spelling.
- **Search is substring-based, not fuzzy.** A misspelt or transliterated-differently name matches nothing, and there is no did-you-mean, no similarity threshold, and no minimum query length. A one-character `search` will match a large fraction of the table.
- **The relevance score is not returned.** Only the ordering reflects it, so a client cannot show "how good" a match is or set its own cut-off.
- **There is no "current destination".** `destinations` lists every journey the person ever had, in no documented order, and nothing marks one as the live one. Deriving it from `stage` is a client-side convention, not a backend rule.
- **No filter for "has no journey".** `?country=`/`?journey_stage=` can only narrow *to* a destination; there is no documented way to list the applicants who have none — precisely the cohort someone would want to chase.
- **`destinations[].country_code` casing is not guaranteed.** The example shows `"au"`; the filter accepts either case, but what the field returns follows however the catalogue row was created. Compare case-insensitively.
