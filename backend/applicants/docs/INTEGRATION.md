# Integration — Applicants

**Owner app:** `applicants`
**Version:** 1.2.0
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
| `audit` | service call + read shape | Every mutation appends one immutable event; the history endpoint reads that log back through audit's selector and renders audit's shared entry shape. This module stores no history of its own. | Hard dependency in both directions of use — without it this module does not start. If only the write path failed, `GET /api/v1/applicants/<id>/history/` would return an empty list — the change history disappears, though the applicant itself still works. |
| `applicant_journeys` | reverse FK read | An applicant has **no destination of its own** — the destination belongs to the study plan. The `destinations` array on both read shapes, and the `country`, `country_code`, and `journey_stage` list filters, are all read back through the journeys that point here. | The three filters always return an empty page and `destinations` is always `[]`. Nothing else degrades: creating, reading, editing, and archiving an applicant work with no journey in the system, and a person with no journey is a normal, fully functional record today. |
| `institutions` | indirect FK read | `destinations[].country_id` / `country_code` / `country_name` are the catalogue country the journey targets. This module never queries the catalogue itself; it reads what the journey already points at. | The three country fields are `null`/`""` and `?country=`/`?country_code=` match nothing. `target_country` — the free text the destination was typed as — still resolves, and is the only destination a pre-catalogue journey ever had. |

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
- **List/search/filter/order params:** on `GET /api/v1/applicants/` only — `status`, `creation_source`, `search`, `country`, `country_code`, `journey_stage`, `fiscal_year` (`YYYY/YY`). They compose: supplying several narrows the same result set rather than one replacing another. There is no client-controlled ordering anywhere in this module, but the server's ordering is **not** unconditionally newest-first — see below.
- **Ordering.** Every list is newest-first **except** `GET /api/v1/applicants/?search=…`, which is ordered by relevance and only tie-broken by recency. Do not assume `data[0]` is the most recently created applicant when you passed a `search`.
- **What `search` matches.** All three name forms, the `email`, **any** of the applicant's contact numbers, and the passport number. All partial, case-insensitive, substring matches. It is **not** fuzzy: a misspelling matches nothing, and there is no did-you-mean.
- **How `search` ranks.** `3` a name equals the query, `2` a name starts with it, `1` a name contains it, `0` matched only on email, contact number, or passport. Ties fall to newest-first, then id. The score itself is not returned in the response — only the order reflects it.

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

**FamilyMember** — `{ id, relationship:[enum], full_name, occupation, contact_number }`

**EmergencyContact** — `{ id, full_name, relationship, contact_number, email, address }`

- `relationship` here is **free text**, unlike `FamilyMember.relationship` which is an enum — an emergency contact may be a friend, landlord, or colleague.

**Destination** — `{ journey_id, stage:[enum], country_id?, country_code, country_name, target_country }`

- One entry per journey the applicant holds. **Not owned by this module** — it is a read-only projection of `applicant_journeys`.
- `stage` is an `applicant_journeys` `JourneyStage` value, not an applicant status. The two lifecycles are independent: a journey reaching `closed` does not archive the applicant.
- `country_id`, `country_code`, and `country_name` are `null`/`""` together for a journey with no catalogue link. In that case `target_country` — free text — is the **only** destination that journey has. Render `country_name || target_country`.
- Use `journey_id` to call the `applicant_journeys` module; this module exposes no journey endpoints.

**Applicant (list shape)** — `{ id, full_name, date_of_birth?, date_of_birth_bs?:BsDate, gender:[enum], nationality, email, status:[enum], creation_source:[enum], created_by:UserBrief, contact_numbers:[ContactNumber], destinations:[Destination], created_at, updated_at }`

**Applicant (detail shape)** — the list shape plus `{ addresses:[Address], passport?:Passport, family_members:[FamilyMember], emergency_contacts:[EmergencyContact], originating_lead_id? }`

- The detail shape is returned by retrieve, create, update, **and** the status action. Only the list returns the shorter shape.
- `passport` is `null` when the applicant has none.
- `destinations` is `[]` for a person with no journey yet — a normal, common state, not an error and not a permission problem. It appears on **both** shapes.
- `originating_lead_id` is the id of the lead this applicant was converted from, or `null` when created directly. It is a bare id string, not an object — fetch the lead from the `leads` module if you need more.

**HistoryEntry** — `{ id, action:[enum], actor_type:[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:BsDate }`

- Owned by the `audit` module, where the same shape is called **AuditEventHistoryEntry** (`audit/docs/INTEGRATION.md` §4). This module renders it; it does not define it. Every module's `/history/` endpoint returns this identical shape, so one renderer serves all of them.
- `changes` maps a field name to `{ from, to }`, and is `{}` for actions with no field-level diff.
- Passport numbers, address text, and family names are deliberately **never** present in `changes` or `metadata`.

### Worked examples

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
      "contact_number": "9841111111"
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
- `FamilyMember.relationship`: `father` | `mother` | `spouse` | `sibling` | `child` | `guardian` | `other`
- `EmergencyContact.relationship`: **not an enum** — free text.
- `Destination.stage`: `planning` | `profile_building` | `shortlisting` | `applying` | `offer_stage` | `visa_stage` | `completed` | `closed` | `deferred` — owned by `applicant_journeys`, not this module. Also the accepted values for the `?journey_stage=` filter.
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
- create: `full_name` (required), `full_name`, `date_of_birth`, `gender`, `nationality`, `email`, `contact_numbers` (required, at least one), `addresses`, `passport`, `family_members`, `emergency_contacts`
- update: any subset of the same fields, all optional

**Returns:** Applicant (detail shape) for create, retrieve, and update; list[Applicant (list shape)] for the list, paginated.
**Requires state:**
- an authenticated Admin or Lead Manager for read and update; an authenticated **Admin** for create. No other resource needs to exist first.
- for the list: nothing. But `?country=`, `?country_code=`, and `?journey_stage=` match only applicants who **already have a journey** — an applicant created a moment ago has none and is invisible to all three until one is opened through the `applicant_journeys` module.

**Side effects:**
- create — appends `applicant_created` to the audit log.
- update — appends `applicant_updated` when scalar fields moved, plus one further event per nested collection actually supplied (`applicant_contact_changed`, `applicant_address_changed`, `applicant_passport_changed`, `applicant_family_changed`, `applicant_emergency_contact_changed`). A `PATCH` that changes nothing writes no event.
- list and retrieve — none, these are reads.

**Notes:**
- **Shared, not owner-scoped.** Every Admin and Lead Manager sees and edits every applicant. This deliberately differs from `leads`, where a Lead Manager sees only their own records.
- **Creation is Admin-only**, by both paths. Editing is not — a Lead Manager who may not admit someone to the lifecycle may still maintain their file.
- All five sub-resources are nested in the payload; there are no standalone endpoints for them. Sending a collection **replaces it entirely** — always send the complete intended list, never a delta. Sending `passport` upserts the single record.
- `status`, `creation_source`, and `created_by` are not writable here; sending them is ignored, not rejected.
- `full_name` is generated server-side; sending it has no effect.
- `search` matches the applicant's name, and also the email, any contact number, and the passport number.
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
1. `POST /api/v1/applicants/` with `full_name` and at least one contact number → capture `applicant.id`. `creation_source` reads `direct_admin`.
   - `APPLICANTS_ACTOR_FORBIDDEN`: the caller is a Lead Manager — this path is Admin-only.
   - `APPLICANTS_CONTACT_REQUIRED` or a 400 on `contact_numbers`: at least one number is mandatory.
2. `PATCH /api/v1/applicants/<applicant.id>/` to fill in passport, addresses, and family as they become known. Each collection is sent complete.
3. `POST /api/v1/journeys/` with `applicant: <applicant.id>` *(other module: `applicant_journeys`)* to record what they are actually trying to do — an applicant with no journey has no objective.

**Arrive via lead conversion** *(crosses into `leads`)*
1. `POST /api/v1/leads/<lead_id>/convert/` *(other module: `leads`)* → returns `applicant_id` and `journey_id`.
   - `LEADS_LEAD_ALREADY_CONVERTED`: this lead already produced an applicant; fetch it rather than retrying.
2. `GET /api/v1/applicants/<applicant_id>/` → identity and contact numbers were copied from the lead; `creation_source` reads `lead_conversion` and `originating_lead_id` points back.
3. `PATCH /api/v1/applicants/<applicant_id>/` to add the detail a lead never carried — passport, date of birth, family, emergency contacts.

**Find a person you have something about but not a name**
1. `GET /api/v1/applicants/?search=<the fragment you have>` → matches names in either script, the email, any contact number, and the passport number. Results are relevance-ordered, so an exact name match is `data[0]`.
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

- **No photograph *on this resource*.** `concepts/applicants.txt` lists one; no file handling exists in this module and none is planned here. **Files live in `uploaded_files` (`/api/v1/files/`), which is now built** — upload with `applicant=<applicant_id>` and `category=photograph`, list with `GET /api/v1/files/?applicant=<applicant_id>&category=photograph`. Two caveats before you build an avatar: an applicant payload carries **no file reference at all**, and **nothing designates a primary photograph** — the filter can return several, and choosing among them is a client-side convention, not a backend rule.
- **No academic history, test scores, documents, or files.** The `education` and `test_scores` modules are specified but not built; there is no endpoint for either.
- **No duplicate detection or merging.** Two records for the same person can be created and nothing prevents or resolves it.
- **No field-level redaction.** Every lead actor who can read an applicant reads the whole record including passport and date of birth. Whether those should be Admin-only is unresolved.
- **Passport renewal history is not kept.** The record holds one current passport; a renewal overwrites it and only the audit event records that a change happened — not the previous number.
- **401 body shape is not specified here.** Unauthenticated and expired-token responses come from the authentication framework; consult the `authenticate` module's contract.
- **`HistoryEntry.metadata` keys are per-action and not exhaustively specified.** Observed keys: `creation_source`, `count`. Treat as advisory display data.
- **No bulk operations and no export.** Each applicant is acted on individually.
- **`nationality` is free text** with no validation or canonical list, so values will vary in spelling.
- **Search is substring-based, not fuzzy.** A misspelt or transliterated-differently name matches nothing, and there is no did-you-mean, no similarity threshold, and no minimum query length. A one-character `search` will match a large fraction of the table.
- **The relevance score is not returned.** Only the ordering reflects it, so a client cannot show "how good" a match is or set its own cut-off.
- **There is no "current destination".** `destinations` lists every journey the person ever had, in no documented order, and nothing marks one as the live one. Deriving it from `stage` is a client-side convention, not a backend rule.
- **No filter for "has no journey".** `?country=`/`?journey_stage=` can only narrow *to* a destination; there is no documented way to list the applicants who have none — precisely the cohort someone would want to chase.
- **`destinations[].country_code` casing is not guaranteed.** The example shows `"au"`; the filter accepts either case, but what the field returns follows however the catalogue row was created. Compare case-insensitively.
