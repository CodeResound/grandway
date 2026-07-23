# Integration — Applicants

**Owner app:** `applicants`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-23

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial integration contract — 6 endpoints |

---

## 1. Module

- **Name:** Applicants — the permanent record of a person the consultancy works with. Holds identity, contact details, addresses, passport, family, and emergency contacts. It does not hold study plans, academic history, or test scores.
- **Base path:** `/api/v1/applicants/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. Two authority types may use this module: `admin` and `lead_manager`. A `superadmin` token is rejected with 403 everywhere.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which decides whether the caller may read, edit, or create. | Every endpoint returns 401. Without a recognised `authority_type` the caller gets 403 `APPLICANTS_ACTOR_FORBIDDEN`. |
| `authenticate` | FK | `created_by` references a user account. | Applicants cannot be created; attribution is unresolvable. |
| `audit` | service call | Every mutation appends one immutable event; the history endpoint reads that log back. This module stores no history of its own. | `GET /api/v1/applicants/<id>/history/` returns an empty list — the change history disappears, though the applicant itself still works. |

**This module depends on `leads` for nothing.** An applicant can be created, read, edited, and archived with no lead in the system. The relationship runs the other way: `leads` calls this module to create an applicant during conversion, and `leads` owns the link between the two. `originating_lead_id` on the detail response is read back through that link and is simply `null` for a directly created applicant.

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

- **Auth failures:** 401 with no token, an expired token, or a revoked session — produced by the authentication framework, not this module. 403 `APPLICANTS_ACTOR_FORBIDDEN` when the token is valid but the authority may not act: a `superadmin` on any endpoint, or a `lead_manager` on create.
- **Pagination:** page-number based. Params `page` and `page_size` (default 20, max 100). `meta` carries `count`, `page`, `page_size`, `next`, `previous`; the last two are absolute URLs or `null`. Applied to the applicant list and the history list. There are no unpaginated list endpoints in this module.
- **IDs:** UUID strings.
- **Times:** ISO 8601 UTC for datetimes; `YYYY-MM-DD` for dates. Every user-facing **date** carries a `<field>_bs` sibling holding a Bikram Sambat object. `created_at` and `updated_at` never do.
- **List/search/filter/order params:** on `GET /api/v1/applicants/` only — `status`, `creation_source`, `search` (matches all three name forms at once), `fiscal_year` (`YYYY/YY`). Ordering is fixed newest-first; there is no client-controlled ordering anywhere in this module.

## 4. Models

**BsDate** — `{ year, month, day, month_name_en, month_name_np, display_en, display_np }`

- Never sent by a client; appears only as the value of a `<field>_bs` key.

**UserBrief** — `{ id, username, display_name }`

**ContactNumber** — `{ id, number, label:[enum], is_primary }`

**Address** — `{ id, address_type:[enum], country, province, district, municipality, ward, street_address, postal_code }`

- At most one per `address_type` per applicant. Every component except `address_type` is optional.

**Passport** — `{ passport_number, issuing_country, place_of_issue, issued_date?, issued_date_bs?:BsDate, expiry_date?, expiry_date_bs?:BsDate }`

- Has no `id` in the response — it is a one-per-applicant record, not a collection member.
- `expiry_date` is the operationally important field; an expiring passport can block a visa application.

**FamilyMember** — `{ id, relationship:[enum], full_name_np, full_name_en, occupation, contact_number }`

**EmergencyContact** — `{ id, full_name_np, full_name_en, relationship, contact_number, email, address }`

- `relationship` here is **free text**, unlike `FamilyMember.relationship` which is an enum — an emergency contact may be a friend, landlord, or colleague.

**Applicant (list shape)** — `{ id, full_name_np, full_name_en, full_name_romanized, date_of_birth?, date_of_birth_bs?:BsDate, gender:[enum], nationality, email, status:[enum], creation_source:[enum], created_by:UserBrief, contact_numbers:[ContactNumber], created_at, updated_at }`

**Applicant (detail shape)** — the list shape plus `{ addresses:[Address], passport?:Passport, family_members:[FamilyMember], emergency_contacts:[EmergencyContact], originating_lead_id? }`

- The detail shape is returned by retrieve, create, update, **and** the status action. Only the list returns the shorter shape.
- `passport` is `null` when the applicant has none.
- `originating_lead_id` is the id of the lead this applicant was converted from, or `null` when created directly. It is a bare id string, not an object — fetch the lead from the `leads` module if you need more.

**HistoryEntry** — `{ id, action:[enum], actor_type:[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:BsDate }`

- `changes` maps a field name to `{ from, to }`, and is `{}` for actions with no field-level diff.
- Passport numbers, address text, and family names are deliberately **never** present in `changes` or `metadata`.

### Worked examples

**Applicant (detail shape)**

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
      "month_name_en": "Poush", "month_name_np": "पुष",
      "display_en": "2078 Poush 17", "display_np": "२०७८ पुष १७"
    },
    "expiry_date": "2032-01-01",
    "expiry_date_bs": {
      "year": 2088, "month": 9, "day": 17,
      "month_name_en": "Poush", "month_name_np": "पुष",
      "display_en": "2088 Poush 17", "display_np": "२०८८ पुष १७"
    }
  },
  "family_members": [
    {
      "id": "f1f2f3f4-0000-1111-2222-333344445555",
      "relationship": "father",
      "full_name_np": "हरि श्रेष्ठ",
      "full_name_en": "Hari Shrestha",
      "occupation": "Teacher",
      "contact_number": "9841111111"
    }
  ],
  "emergency_contacts": [
    {
      "id": "e1e2e3e4-0000-1111-2222-333344445555",
      "full_name_np": "गीता श्रेष्ठ",
      "full_name_en": "Gita Shrestha",
      "relationship": "Aunt",
      "contact_number": "9812345678",
      "email": "",
      "address": ""
    }
  ],
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
      "contact_numbers": [
        { "id": "c1c2c3c4-0000-1111-2222-333344445555", "number": "9800000000", "label": "mobile", "is_primary": true }
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
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
  }
}
```

## 5. Enums

- `Applicant.status`: `active` | `dormant` | `archived`
- `Applicant.creation_source`: `lead_conversion` | `direct_admin`
- `Applicant.gender`: `male` | `female` | `other` | `undisclosed` | `""`
- `Address.address_type`: `permanent` | `current`
- `ContactNumber.label`: `mobile` | `home` | `work` | `whatsapp` | `viber` | `other`
- `FamilyMember.relationship`: `father` | `mother` | `spouse` | `sibling` | `child` | `guardian` | `other`
- `EmergencyContact.relationship`: **not an enum** — free text.
- `HistoryEntry.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `HistoryEntry.action`: `applicant_created` | `applicant_updated` | `applicant_contact_changed` | `applicant_address_changed` | `applicant_passport_changed` | `applicant_family_changed` | `applicant_emergency_contact_changed` | `applicant_status_changed`

## 6. Dependency order

- `Applicant` needs an authenticated **Admin** account *(other module: `authenticate`)* — a Lead Manager cannot create one.
- `ContactNumber`, `Address`, `Passport`, `FamilyMember`, `EmergencyContact` all need `Applicant` — each is sent nested in the applicant payload, never created on its own.
- `HistoryEntry` needs `Applicant` and is never created by a client.
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
- create: `full_name_np` (required), `full_name_en`, `date_of_birth`, `gender`, `nationality`, `email`, `contact_numbers` (required, at least one), `addresses`, `passport`, `family_members`, `emergency_contacts`
- update: any subset of the same fields, all optional

**Returns:** Applicant (detail shape) for create, retrieve, and update; list[Applicant (list shape)] for the list, paginated.
**Requires state:** an authenticated Admin or Lead Manager for read and update; an authenticated **Admin** for create. No other resource needs to exist first.
**Side effects:**
- create — appends `applicant_created` to the audit log.
- update — appends `applicant_updated` when scalar fields moved, plus one further event per nested collection actually supplied (`applicant_contact_changed`, `applicant_address_changed`, `applicant_passport_changed`, `applicant_family_changed`, `applicant_emergency_contact_changed`). A `PATCH` that changes nothing writes no event.

**Notes:**
- **Shared, not owner-scoped.** Every Admin and Lead Manager sees and edits every applicant. This deliberately differs from `leads`, where a Lead Manager sees only their own records.
- **Creation is Admin-only**, by both paths. Editing is not — a Lead Manager who may not admit someone to the lifecycle may still maintain their file.
- All five sub-resources are nested in the payload; there are no standalone endpoints for them. Sending a collection **replaces it entirely** — always send the complete intended list, never a delta. Sending `passport` upserts the single record.
- `status`, `creation_source`, and `created_by` are not writable here; sending them is ignored, not rejected.
- `full_name_romanized` is generated server-side; sending it has no effect.
- `search` matches Devanagari, Roman, and romanized names simultaneously, so a user may type in either script.
- Archived applicants still appear in the list — filter on `status` to exclude them.
- `originating_lead_id` appears only on the detail shape and is `null` for directly created applicants.

**Errors:**
- `APPLICANTS_ACTOR_FORBIDDEN` (403) — a Superadmin called any method, or a Lead Manager attempted create
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id (always literal; never "not yours")
- `APPLICANTS_CONTACT_REQUIRED` (400) — no contact number supplied
- `APPLICANTS_PASSPORT_EXPIRY_INVALID` (400) — passport expiry is not after its issue date

### Applicant status — `POST /api/v1/applicants/<applicant_id>/status/`

**Use it when:** the status control in the applicant file header.
**Methods:**
- `POST /api/v1/applicants/<applicant_id>/status/` — set the applicant's standing (permission: `applicants.applicant.change_status`, risk: medium)

**Send (create/update):**
- `status` (required) — `active`, `dormant`, or `archived`

**Returns:** Applicant (detail shape)
**Requires state:** the applicant must exist. No journey state is consulted.
**Side effects:** appends `applicant_status_changed` with `changes.status = {from, to}`. Setting the status it already holds is a no-op and writes no event. **Nothing else changes** — in particular, no journey is opened or closed.
**Notes:**
- Status is always manual. It is never changed automatically by journey activity, and archiving an applicant does not close their journeys.
- Archiving deletes nothing and is fully reversible.
- Archival is not a privacy control: an archived applicant is still visible to every lead actor and still appears in unfiltered lists.

**Errors:**
- `APPLICANTS_APPLICANT_NOT_FOUND` (404) — no applicant with that id

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
1. `POST /api/v1/applicants/` with `full_name_np` and at least one contact number → capture `applicant.id`. `creation_source` reads `direct_admin`.
   - `APPLICANTS_ACTOR_FORBIDDEN`: the caller is a Lead Manager — this path is Admin-only.
   - `APPLICANTS_CONTACT_REQUIRED` or a 400 on `contact_numbers`: at least one number is mandatory.
2. `PATCH /api/v1/applicants/<applicant.id>/` to fill in passport, addresses, and family as they become known. Each collection is sent complete.
3. `POST /api/v1/journeys/` with `applicant: <applicant.id>` *(other module: `applicant_journeys`)* to record what they are actually trying to do — an applicant with no journey has no objective.

**Arrive via lead conversion** *(crosses into `leads`)*
1. `POST /api/v1/leads/<lead_id>/convert/` *(other module: `leads`)* → returns `applicant_id` and `journey_id`.
   - `LEADS_LEAD_ALREADY_CONVERTED`: this lead already produced an applicant; fetch it rather than retrying.
2. `GET /api/v1/applicants/<applicant_id>/` → identity and contact numbers were copied from the lead; `creation_source` reads `lead_conversion` and `originating_lead_id` points back.
3. `PATCH /api/v1/applicants/<applicant_id>/` to add the detail a lead never carried — passport, date of birth, family, emergency contacts.

**Maintain a file over time**
1. `GET /api/v1/applicants/?search=राम` → find the person by name in either script.
2. `GET /api/v1/applicants/<applicant.id>/` → the full record.
3. `PATCH /api/v1/applicants/<applicant.id>/` with a complete `contact_numbers` list to add a number.
   - Sending only the new number silently drops the existing ones — this is replace, not append.
4. `GET /api/v1/applicants/<applicant.id>/history/` → confirm what changed and who changed it.

**Wind a file down**
1. `POST /api/v1/applicants/<applicant.id>/status/` with `{"status": "dormant"}` when there is no active work.
2. `POST /api/v1/applicants/<applicant.id>/status/` with `{"status": "archived"}` when the file is closed.
3. `POST /api/v1/applicants/<applicant.id>/status/` with `{"status": "active"}` if they return — archival is reversible and destroyed nothing.
   - Note their journeys were not touched by any of this; close those separately if appropriate.

## 9. Gaps

- **No photograph.** `concepts/applicants.txt` lists one, but no file handling exists in this module and none is planned here — files will belong to a separate module. Do not build an avatar upload against this contract.
- **No academic history, test scores, documents, or files.** The `education` and `test_scores` modules are specified but not built; there is no endpoint for either.
- **No duplicate detection or merging.** Two records for the same person can be created and nothing prevents or resolves it.
- **No field-level redaction.** Every lead actor who can read an applicant reads the whole record including passport and date of birth. Whether those should be Admin-only is unresolved.
- **Passport renewal history is not kept.** The record holds one current passport; a renewal overwrites it and only the audit event records that a change happened — not the previous number.
- **401 body shape is not specified here.** Unauthenticated and expired-token responses come from the authentication framework; consult the `authenticate` module's contract.
- **`HistoryEntry.metadata` keys are per-action and not exhaustively specified.** Observed keys: `creation_source`, `count`. Treat as advisory display data.
- **No bulk operations and no export.** Each applicant is acted on individually.
- **`nationality` is free text** with no validation or canonical list, so values will vary in spelling.
