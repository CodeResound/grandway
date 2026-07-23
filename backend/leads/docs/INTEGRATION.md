# Integration — Leads

**Owner app:** `leads`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-23

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial integration contract — 17 endpoints; conversion not yet available |

---

## 1. Module

- **Name:** Leads — tracks people who have shown interest in the consultancy but have not yet become applicants. Records who they are, how they found the consultancy, what they are considering, what stage they are at, when they were last followed up, and whether they were lost or converted.
- **Base path:** `/api/v1/leads/`
- **Auth:** Bearer access JWT on every endpoint. Obtain one from `POST /api/v1/auth/login/` (see the `authenticate` module). Two authority types may use this module: `admin` and `lead_manager`. A `superadmin` token is rejected with 403 on every endpoint here.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies the caller's `authority_type`, which decides whether the caller sees all leads, only their own, or none. | Every endpoint returns 401. Without a valid `authority_type` claim the caller is treated as neither Admin nor Lead Manager and gets 403 `LEADS_ACTOR_FORBIDDEN`. |
| `authenticate` | FK | Lead ownership (`created_by`) and every attribution field (`last_followed_up_by`, `lost_by`, `converted_by`, note `author`) reference a user account. | Leads cannot be created; attribution fields would be unresolvable. |
| `audit` | service call | Every mutation appends one immutable event to the central audit log; the lead history endpoint reads that log back. This module stores no history of its own. | `GET /api/v1/leads/<lead_id>/history/` returns an empty list — the lead's entire chronological history disappears, though the lead itself still works. |
| `applicants` | service call | **Not yet available.** Conversion will call it to create the applicant record. | Conversion is not exposed at all — see §9. |
| `applicant_journeys` | service call | **Not yet available.** Conversion will call it to create the initial journey. | As above. |

## 3. Conventions

- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Single resources put the object in `data`; lists put an array in `data`.

```json
{
  "success": true,
  "message": "Lead retrieved.",
  "data": { "id": "9d8c7b6a-5e4f-3021-a1b2-c3d4e5f60718", "stage": "counselling" },
  "meta": {}
}
```

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object holding field-level problems.

```json
{
  "success": false,
  "error": {
    "code": "LEADS_LOSS_DETAIL_REQUIRED",
    "message": "This loss reason requires an explanation.",
    "details": { "detail": ["This field is required for the selected reason."] }
  },
  "meta": {}
}
```

- **Auth failures:** 401 with no token, an expired token, or a revoked session — body produced by the framework, not by this module. 403 with `LEADS_ACTOR_FORBIDDEN` when the token is valid but the authority type may not perform the action (a `superadmin` on any endpoint; a `lead_manager` on a create/edit under `/sources/` or `/loss-reasons/`).
- **Pagination:** page-number based. Params `page` and `page_size` (default 20, max 100). Paginated responses put the array in `data` and fill `meta` with `count`, `page`, `page_size`, `next`, `previous`; `next`/`previous` are absolute URLs or `null`. **Paginated:** lead list, notes list, history list. **Not paginated:** `/sources/` and `/loss-reasons/` — both return the full array with `meta` as `{}`.
- **IDs:** UUID strings everywhere. Sent as strings in request bodies and path segments.
- **Times:** ISO 8601, UTC, e.g. `2026-07-23T04:00:00Z`. User-facing datetimes additionally carry a `<field>_bs` sibling holding the Bikram Sambat projection as an object (see `BsDate` in §4). `created_at` and `updated_at` never have a `_bs` sibling.
- **List/search/filter/order params:** on `GET /api/v1/leads/` only — `stage`, `source` (a lead-source id), `search`, `fiscal_year` (`YYYY/YY`, Nepali fiscal year, filters on creation date). Ordering is fixed: leads, notes, and history are always newest first; sources and loss reasons are always by `display_order` then `name_np`. There is no client-controlled ordering. `GET /api/v1/leads/sources/` and `/loss-reasons/` accept `include_inactive=true` and nothing else.

## 4. Models

**BsDate** — `{ year, month, day, month_name_en, month_name_np, display_en, display_np }`

- Never sent by a client; appears only as the value of a `<field>_bs` key.

**ReferenceEntry** — `{ id, code, name_np, name_en, name_romanized, requires_detail, is_active, display_order, created_at, updated_at }`

- The shape of both `LeadSource` and `LossReason`; they are identical.
- `name_np` is the Devanagari name and `name_en` the English one — independent identities, not translations. `name_romanized` is a server-derived ASCII search form; never send it.
- `requires_detail` true means a lead choosing this entry must supply an explanation — `source_detail` for a source, `detail` for a loss reason.
- `is_active` false means retired: it stays referenced by old leads but must not be offered in a picker.

**ContactNumber** — `{ id, number, label:[enum], is_primary }`

**StudyInterest** — `{ interested_countries:json, study_level:[enum], field_of_study, preferred_intake, budget_amount?, budget_currency, scholarship_interest, highest_qualification, language_test_status:[enum], interest_notes }`

- `interested_countries` is an array of strings. `budget_amount` is a decimal **string** or `null`.
- Every field is optional and may be blank — this record deliberately holds incomplete information.

**UserBrief** — `{ id, username, display_name }`

**Lead (list shape)** — `{ id, full_name_np, full_name_en, full_name_romanized, email, address, source:ReferenceEntry, source_detail, stage:[enum], created_by:UserBrief, contact_numbers:[ContactNumber], last_followed_up_at?, last_followed_up_at_bs?:BsDate, created_at, updated_at }`

**Lead (detail shape)** — the list shape plus `{ study_interest?:StudyInterest, last_followed_up_by?:UserBrief, lost_reason?:ReferenceEntry, lost_detail, lost_at?, lost_at_bs?:BsDate, lost_by?:UserBrief, stage_before_loss, converted_at?, converted_at_bs?:BsDate, converted_by?:UserBrief }`

- The detail shape is returned by retrieve, create, update, **and every lifecycle action**. Only the lead *list* returns the shorter shape.
- `study_interest` is `null` when the lead has none.
- The `lost_*` fields are all populated together when `stage` is `lost`, and all cleared together on reopen. `stage_before_loss` is `""` unless the lead is currently lost.
- `converted_at`/`converted_by` are always `null` in this version — conversion is not yet available (§9).

**LeadNote** — `{ id, body, author:UserBrief, created_at }`

**HistoryEntry** — `{ id, action:[enum], actor_type:[enum], actor_id?, actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:BsDate }`

- `changes` maps a field name to `{ from, to }` — e.g. `{"stage": {"from": "new", "to": "contacted"}}`. It is `{}` when the action carried no field-level diff.
- `metadata` holds small action-specific scalars and varies by `action`.
- Note bodies, addresses, and loss explanations are deliberately **not** copied into `changes` or `metadata`.

### Worked examples

**Lead (detail shape)**

```json
{
  "id": "9d8c7b6a-5e4f-3021-a1b2-c3d4e5f60718",
  "full_name_np": "राम श्रेष्ठ",
  "full_name_en": "Ram Shrestha",
  "full_name_romanized": "raam shrestha",
  "email": "ram@example.com",
  "address": "Lalitpur",
  "source": {
    "id": "0f1c2b3a-4d5e-6f70-8192-a3b4c5d6e7f8",
    "code": "walk_in",
    "name_np": "वाक-इन",
    "name_en": "Walk-in",
    "name_romanized": "waak-in",
    "requires_detail": false,
    "is_active": true,
    "display_order": 1,
    "created_at": "2026-07-20T05:00:00Z",
    "updated_at": "2026-07-20T05:00:00Z"
  },
  "source_detail": "",
  "stage": "counselling",
  "created_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "leadmgr", "display_name": "Leadmgr" },
  "contact_numbers": [
    { "id": "c1c2c3c4-0000-1111-2222-333344445555", "number": "9800000000", "label": "mobile", "is_primary": true }
  ],
  "last_followed_up_at": "2026-07-23T04:00:00Z",
  "last_followed_up_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
  },
  "study_interest": {
    "interested_countries": ["Australia", "Canada"],
    "study_level": "masters",
    "field_of_study": "Computer Science",
    "preferred_intake": "Fall 2026",
    "budget_amount": "2500000.00",
    "budget_currency": "NPR",
    "scholarship_interest": true,
    "highest_qualification": "BSc CSIT",
    "language_test_status": "preparing",
    "interest_notes": "Prefers Melbourne."
  },
  "last_followed_up_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "leadmgr", "display_name": "Leadmgr" },
  "lost_reason": null,
  "lost_detail": "",
  "lost_at": null,
  "lost_at_bs": null,
  "lost_by": null,
  "stage_before_loss": "",
  "converted_at": null,
  "converted_at_bs": null,
  "converted_by": null,
  "created_at": "2026-07-20T05:00:00Z",
  "updated_at": "2026-07-23T04:00:00Z"
}
```

**Paginated lead list**

```json
{
  "success": true,
  "message": "",
  "data": [
    {
      "id": "9d8c7b6a-5e4f-3021-a1b2-c3d4e5f60718",
      "full_name_np": "राम श्रेष्ठ",
      "full_name_en": "Ram Shrestha",
      "full_name_romanized": "raam shrestha",
      "email": "ram@example.com",
      "address": "Lalitpur",
      "source": {
        "id": "0f1c2b3a-4d5e-6f70-8192-a3b4c5d6e7f8",
        "code": "walk_in",
        "name_np": "वाक-इन",
        "name_en": "Walk-in",
        "name_romanized": "waak-in",
        "requires_detail": false,
        "is_active": true,
        "display_order": 1,
        "created_at": "2026-07-20T05:00:00Z",
        "updated_at": "2026-07-20T05:00:00Z"
      },
      "source_detail": "",
      "stage": "counselling",
      "created_by": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "leadmgr", "display_name": "Leadmgr" },
      "contact_numbers": [
        { "id": "c1c2c3c4-0000-1111-2222-333344445555", "number": "9800000000", "label": "mobile", "is_primary": true }
      ],
      "last_followed_up_at": "2026-07-23T04:00:00Z",
      "last_followed_up_at_bs": {
        "year": 2083, "month": 4, "day": 8,
        "month_name_en": "Shrawan", "month_name_np": "श्रावण",
        "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
      },
      "created_at": "2026-07-20T05:00:00Z",
      "updated_at": "2026-07-23T04:00:00Z"
    }
  ],
  "meta": {
    "count": 43,
    "page": 1,
    "page_size": 20,
    "next": "https://api.example.com/api/v1/leads/?page=2",
    "previous": null
  }
}
```

**LeadNote**

```json
{
  "id": "e1e2e3e4-9999-8888-7777-666655554444",
  "body": "Wants Australia, needs IELTS.",
  "author": { "id": "aaaa1111-2222-3333-4444-555566667777", "username": "leadmgr", "display_name": "Leadmgr" },
  "created_at": "2026-07-23T04:05:00Z"
}
```

**HistoryEntry**

```json
{
  "id": "f0f1f2f3-1234-5678-9abc-def012345678",
  "action": "lead_marked_lost",
  "actor_type": "lead_manager",
  "actor_id": "aaaa1111-2222-3333-4444-555566667777",
  "actor_label": "leadmgr",
  "summary": "Lead marked lost (no_response).",
  "reason": "no_response",
  "changes": { "stage": { "from": "follow_up", "to": "lost" } },
  "metadata": { "loss_reason": "no_response", "has_detail": true },
  "created_at": "2026-07-23T06:30:00Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
  }
}
```

## 5. Enums

- `Lead.stage`: `new` | `contact_attempted` | `contacted` | `counselling` | `follow_up` | `ready_for_conversion` | `converted` | `lost`
- **Selectable stages** (the only values accepted by the stage-change, follow-up, and reopen endpoints): `new` | `contact_attempted` | `contacted` | `counselling` | `follow_up` | `ready_for_conversion`. `lost` and `converted` are read-only outcomes reached through their own actions.
- `Lead.stage_before_loss`: same set as `Lead.stage`, plus `""` when the lead has never been lost.
- `ContactNumber.label`: `mobile` | `home` | `work` | `whatsapp` | `viber` | `other`
- `StudyInterest.study_level`: `school` | `certificate` | `diploma` | `bachelors` | `postgraduate_diploma` | `masters` | `phd` | `other` | `""`
- `StudyInterest.language_test_status`: `not_taken` | `preparing` | `booked` | `taken` | `not_required` | `""`
- `HistoryEntry.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`
- `HistoryEntry.action`: `lead_created` | `lead_updated` | `lead_source_changed` | `lead_contact_changed` | `lead_interest_changed` | `lead_stage_changed` | `lead_followup_recorded` | `lead_marked_lost` | `lead_reopened` | `lead_note_added`. Two further values, `lead_converted` and `lead_applicant_created`, are defined but never emitted in this version.
- `LeadSource.code` / `LossReason.code`: **not a fixed enum** — these are runtime-configurable rows created by an Admin. Never hardcode a code; always populate pickers from the list endpoints.

## 6. Dependency order

- `Lead` needs `LeadSource` — a lead cannot be created without attributing it to a source.
- `Lead` needs an authenticated Admin or Lead Manager account *(other app: `authenticate`)`* — the caller becomes the permanent owner.
- `ContactNumber` needs `Lead` — sent nested inside the lead payload, never created on its own.
- `StudyInterest` needs `Lead` — sent nested inside the lead payload, never created on its own.
- `LeadNote` needs `Lead`.
- Marking a lead lost needs `LossReason` — a reason is always mandatory.
- `HistoryEntry` needs `Lead` and is never created by a client; the server writes it on every mutation.

**Start here:** `GET /api/v1/leads/sources/` to populate the source picker, then `POST /api/v1/leads/` to create the first lead. If the source list is empty, an Admin must create a source first.

## 7. Endpoints

### Lead Source — `/api/v1/leads/sources/`

**Use it when:** populating the "how did they find us" picker on the create-lead form, and on the Admin settings screen where these are managed.
**Methods:**
- `GET /api/v1/leads/sources/` — list sources (permission: `leads.source.list`, risk: low)
- `POST /api/v1/leads/sources/` — add a source (permission: `leads.source.create`, risk: medium)
- `PATCH /api/v1/leads/sources/<source_id>/` — edit or retire a source (permission: `leads.source.update`, risk: medium)

**Send (create/update):**
- create: `code` (required, lowercase ASCII, letters/digits/`_`/`-`), `name_np` (required), `name_en`, `requires_detail`, `is_active`, `display_order`
- update: `name_np`, `name_en`, `requires_detail`, `is_active`, `display_order` — `code` is immutable and is ignored if sent

**Returns:** `ReferenceEntry` | list[`ReferenceEntry`]
**Requires state:** an authenticated Admin or Lead Manager for `GET`; an authenticated **Admin** for `POST` and `PATCH`.
**Side effects:** `POST` and `PATCH` each append one event to the central audit log (`lead_source_created` / `lead_source_updated`). These do **not** appear in any lead's history. A `PATCH` that changes nothing writes no event.
**Notes:**
- `GET` hides retired entries by default; pass `include_inactive=true` to see them. Show retired entries on the settings screen, never in the create-lead picker.
- `name_romanized` is generated server-side from `name_np`; sending it has no effect.
- `code` is lowercased on write, so `"Referral"` is stored as `"referral"`.
- There is no delete. Retire with `{"is_active": false}` — existing leads keep pointing at the entry.

**Errors:**
- `LEADS_ACTOR_FORBIDDEN` (403) — a Lead Manager attempted `POST`/`PATCH`, or a Superadmin called any method
- `LEADS_SOURCE_CODE_TAKEN` (409) — a source with that code already exists
- `LEADS_SOURCE_NOT_FOUND` (404) — no source with that id

### Loss Reason — `/api/v1/leads/loss-reasons/`

**Use it when:** populating the mandatory reason picker on the "mark lost" dialog, and on the Admin settings screen.
**Methods:**
- `GET /api/v1/leads/loss-reasons/` — list reasons (permission: `leads.loss_reason.list`, risk: low)
- `POST /api/v1/leads/loss-reasons/` — add a reason (permission: `leads.loss_reason.create`, risk: medium)
- `PATCH /api/v1/leads/loss-reasons/<reason_id>/` — edit or retire a reason (permission: `leads.loss_reason.update`, risk: medium)

**Send (create/update):** identical to the Lead Source block above.
**Returns:** `ReferenceEntry` | list[`ReferenceEntry`]
**Requires state:** same as Lead Source.
**Side effects:** appends `loss_reason_created` / `loss_reason_updated` to the audit log. Not visible in any lead's history.
**Notes:**
- Set `requires_detail: true` on a catch-all entry such as `other`; the mark-lost call will then reject a blank `detail`.

**Errors:**
- `LEADS_ACTOR_FORBIDDEN` (403) — as above
- `LEADS_LOSS_REASON_CODE_TAKEN` (409) — a reason with that code already exists
- `LEADS_LOSS_REASON_NOT_FOUND` (404) — no reason with that id

### Lead — `/api/v1/leads/`

**Use it when:** the lead inbox/list screen, the create-lead form, and the lead detail page.
**Methods:**
- `GET /api/v1/leads/` — list leads in scope (permission: `leads.lead.list`, risk: low)
- `POST /api/v1/leads/` — record a new enquiry (permission: `leads.lead.create`, risk: medium)
- `GET /api/v1/leads/<lead_id>/` — retrieve one lead (permission: `leads.lead.read`, risk: low)
- `PATCH /api/v1/leads/<lead_id>/` — correct a lead (permission: `leads.lead.update`, risk: medium)

**Send (create/update):**
- create: `full_name_np` (required), `full_name_en`, `email`, `address`, `source` (required, a lead-source id), `source_detail`, `contact_numbers` (required, at least one), `study_interest` (optional object)
- update: any subset of the same fields, all optional

**Returns:** Lead (detail shape) for create, retrieve, and update; list[Lead (list shape)] for the list, paginated.
**Requires state:** at least one active `LeadSource` must exist before a lead can be created. The caller must be an Admin or Lead Manager.
**Side effects:**
- create — appends `lead_created` to the audit log; the caller becomes the lead's permanent owner.
- update — appends `lead_updated` (or `lead_source_changed` if the source moved); additionally `lead_contact_changed` when `contact_numbers` was sent and `lead_interest_changed` when `study_interest` was sent. A `PATCH` that changes nothing writes no event.

**Notes:**
- **Scope:** an Admin sees and edits every lead; a Lead Manager sees and edits only leads they created. A lead outside the caller's scope returns 404, identical to a non-existent one — do not treat 404 as proof the lead does not exist.
- **Ownership never moves.** There is no assignment, reassignment, or transfer endpoint anywhere in this module, by design. `created_by` is set from the token at creation and can never be changed.
- `stage` is **not** writable through `PATCH`. Sending it is ignored, not rejected. Use the stage, follow-up, lost, or reopen actions instead.
- `full_name_romanized` is generated server-side from `full_name_np`; sending it has no effect.
- Sending `contact_numbers` **replaces the entire set** — always send the complete list the lead should end up with, never a delta. The same number cannot appear twice on one lead.
- Sending `study_interest` upserts the single interest record; a lead never has more than one.
- A new lead always starts at `stage: "new"`.
- `search` matches across the Devanagari, English, and romanized names simultaneously, so a user can type in either script.

**Errors:**
- `LEADS_ACTOR_FORBIDDEN` (403) — the caller is a Superadmin
- `LEADS_LEAD_NOT_FOUND` (404) — no such lead, or it belongs to another Lead Manager
- `LEADS_SOURCE_INACTIVE` (400) — the chosen source has been retired
- `LEADS_SOURCE_DETAIL_REQUIRED` (400) — the chosen source has `requires_detail` but `source_detail` was blank
- `LEADS_CONTACT_REQUIRED` (400) — no contact number was supplied

### Lead stage change — `POST /api/v1/leads/<lead_id>/stage/`

**Use it when:** the user picks a new stage from the dropdown on the lead detail page.
**Methods:**
- `POST /api/v1/leads/<lead_id>/stage/` — move to another active stage (permission: `leads.lead.change_stage`, risk: medium)

**Send (create/update):**
- `stage` (required) — must be one of the six **selectable** stages in §5

**Returns:** Lead (detail shape)
**Requires state:** the lead must **not** be `lost` or `converted`. Reopen it first if it is.
**Side effects:** appends `lead_stage_changed` with `changes.stage = {from, to}`. Moving to the stage the lead already holds is a no-op and writes no event.
**Notes:**
- `lost` and `converted` are rejected here — each has its own action. Do not offer them in the stage dropdown.
- `ready_for_conversion` signals readiness only; it does **not** create an applicant.

**Errors:**
- `LEADS_STAGE_NOT_EDITABLE` (409) — the lead is lost or converted
- `LEADS_STAGE_INVALID_TRANSITION` (400) — a terminal stage was requested

### Lead follow-up — `POST /api/v1/leads/<lead_id>/follow-up/`

**Use it when:** the Lead Manager has just phoned or met the person and wants to record that it happened.
**Methods:**
- `POST /api/v1/leads/<lead_id>/follow-up/` — record a manual follow-up (permission: `leads.lead.record_followup`, risk: low)

**Send (create/update):**
- `note` (optional) — creates a `LeadNote` when non-blank
- `stage` (optional) — a selectable stage; applies the same rules as the stage-change action
- `followed_up_at` (optional) — defaults to now

**Returns:** Lead (detail shape), with `last_followed_up_at`, `last_followed_up_at_bs`, and `last_followed_up_by` updated.
**Requires state:** the lead must not be `lost` or `converted`.
**Side effects:** appends `lead_followup_recorded`; additionally `lead_note_added` when `note` was non-blank and `lead_stage_changed` when `stage` was supplied and differed. A non-blank `note` creates a real `LeadNote` visible on the notes endpoint.
**Notes:**
- Grandway does **not** schedule follow-ups, send reminders, or integrate with phone, email, SMS, chat, or calendar. Follow-up happens outside the system; this endpoint only records that it occurred. Do not build a scheduling UI against it.
- An empty body `{}` is valid and records a follow-up at the current time.

**Errors:**
- `LEADS_STAGE_NOT_EDITABLE` (409) — the lead is lost or converted
- `LEADS_STAGE_INVALID_TRANSITION` (400) — a terminal stage was requested

### Lead mark lost — `POST /api/v1/leads/<lead_id>/lost/`

**Use it when:** the person will not proceed and the Lead Manager is closing the enquiry.
**Methods:**
- `POST /api/v1/leads/<lead_id>/lost/` — close the lead (permission: `leads.lead.mark_lost`, risk: high)

**Send (create/update):**
- `loss_reason` (required) — a loss-reason id
- `detail` (conditionally required) — mandatory when the chosen reason has `requires_detail`

**Returns:** Lead (detail shape) with `stage: "lost"` and all `lost_*` fields populated.
**Requires state:** at least one active `LossReason` must exist. The lead must not already be `lost` or `converted`.
**Side effects:** appends `lead_marked_lost`, carrying the reason code in the entry's `reason` field. Sets `stage_before_loss` to whatever stage the lead held.
**Notes:**
- Nothing is deleted. The lead, its notes, its contact numbers, and its complete history all survive, and it can be reopened later.
- A reason is always mandatory — there is no way to close a lead without one.
- The free-text `detail` is stored on the lead but deliberately **not** copied into the audit entry.

**Errors:**
- `LEADS_STAGE_NOT_EDITABLE` (409) — already lost or converted
- `LEADS_LOSS_REASON_REQUIRED` (400) — no reason supplied
- `LEADS_LOSS_REASON_INACTIVE` (400) — the chosen reason has been retired
- `LEADS_LOSS_DETAIL_REQUIRED` (400) — the reason requires an explanation but `detail` was blank

### Lead reopen — `POST /api/v1/leads/<lead_id>/reopen/`

**Use it when:** a closed enquiry comes back to life, or a converted lead needs further lead-side follow-up.
**Methods:**
- `POST /api/v1/leads/<lead_id>/reopen/` — return the lead to active work (permission: `leads.lead.reopen`, risk: high)

**Send (create/update):**
- `stage` (optional) — a selectable stage; defaults to `follow_up`

**Returns:** Lead (detail shape) with all `lost_*` fields cleared.
**Requires state:** the lead must currently be `lost` or `converted`. Calling this on an active lead fails.
**Side effects:** appends `lead_reopened` with `metadata.reopened_from_converted` indicating whether the lead was converted rather than lost. Clears `lost_reason`, `lost_detail`, `lost_at`, `lost_by`, and `stage_before_loss`.
**Notes:**
- This is the **only** way back from a terminal stage.
- Reopening a converted lead does **not** undo the conversion: `converted_at` and `converted_by` are left untouched, the applicant created earlier is not deleted, and the lead stays permanently linked so a second applicant can never be created from it.
- All previous history is preserved; the reopen is appended, not a rewrite.

**Errors:**
- `LEADS_LEAD_NOT_LOST` (409) — the lead is already active
- `LEADS_STAGE_INVALID_TRANSITION` (400) — a terminal stage was requested as the target

### Lead Note — `/api/v1/leads/<lead_id>/notes/`

**Use it when:** the notes panel on the lead detail page.
**Methods:**
- `GET /api/v1/leads/<lead_id>/notes/` — list notes, newest first (permission: `leads.note.list`, risk: low)
- `POST /api/v1/leads/<lead_id>/notes/` — append a note (permission: `leads.note.create`, risk: low)

**Send (create/update):**
- create: `body` (required)

**Returns:** `LeadNote` | list[`LeadNote`], paginated
**Requires state:** the lead must be in the caller's scope.
**Side effects:** `POST` appends `lead_note_added` to the audit log, carrying only the note's id — the note text is never copied into the audit payload.
**Notes:**
- Notes are **append-only**. There is no edit and no delete, and none will be added — `PUT`, `PATCH`, and `DELETE` on this path return 405. Build the UI without edit/delete affordances.
- Notes can be added to a lead at any stage, including a lost or converted one.

**Errors:**
- `LEADS_LEAD_NOT_FOUND` (404) — no such lead, or it belongs to another Lead Manager

### Lead History — `/api/v1/leads/<lead_id>/history/`

**Use it when:** the activity/timeline panel on the lead detail page.
**Methods:**
- `GET /api/v1/leads/<lead_id>/history/` — the lead's chronological action history (permission: `leads.lead.list_history`, risk: low)

**Send (create/update):** none
**Returns:** list[`HistoryEntry`], paginated, newest first
**Requires state:** the lead must be in the caller's scope.
**Side effects:** none — this is a read.
**Notes:**
- History is written by the server on every mutation; a client never creates entries.
- Entries are immutable: they are never rewritten or removed, including when a lead is lost or reopened.
- `changes` is populated only for actions carrying a field-level diff (mainly `lead_stage_changed`, `lead_updated`). Render `summary` as the fallback label for every action.
- Only lead-scoped actions appear here. Changes to sources and loss reasons are audited separately and are not part of any lead's history.

**Errors:**
- `LEADS_LEAD_NOT_FOUND` (404) — no such lead, or it belongs to another Lead Manager

## 8. Flows

**Record and work a new enquiry**
1. `GET /api/v1/leads/sources/` → capture the chosen `source.id`
   - empty list: no sources are configured. A Lead Manager cannot fix this; an Admin must create one first.
2. `POST /api/v1/leads/` with `full_name_np`, `source`, and at least one entry in `contact_numbers` → capture `lead.id`. The lead starts at `new`.
   - `LEADS_SOURCE_DETAIL_REQUIRED`: the chosen source needs an explanation — re-submit with `source_detail` filled in.
   - `LEADS_CONTACT_REQUIRED` or a 400 on `contact_numbers`: at least one number is mandatory.
3. `POST /api/v1/leads/<lead.id>/stage/` with `{"stage": "contact_attempted"}` after the first call attempt.
4. `POST /api/v1/leads/<lead.id>/follow-up/` with `{"note": "Spoke to them.", "stage": "contacted"}` once contact succeeds — this records the follow-up, adds the note, and moves the stage in one call.
5. `POST /api/v1/leads/<lead.id>/stage/` with `{"stage": "ready_for_conversion"}` when the person is ready to become an applicant. This does **not** create an applicant — conversion is not yet available (§9).

**Close an enquiry that will not proceed**
1. `GET /api/v1/leads/loss-reasons/` → capture the chosen `reason.id`
2. `POST /api/v1/leads/<lead.id>/lost/` with `{"loss_reason": "<reason.id>", "detail": "…"}`
   - `LEADS_LOSS_DETAIL_REQUIRED`: the reason requires an explanation — re-submit with `detail` filled in.
   - `LEADS_STAGE_NOT_EDITABLE`: the lead was already closed or converted; refresh the lead and show its current state.
3. The lead now reads `stage: "lost"` with `lost_reason`, `lost_at`, `lost_by`, and `stage_before_loss` populated. It stays visible in the list — filter on `stage` to separate active from closed work.

**Revive a closed enquiry**
1. `POST /api/v1/leads/<lead.id>/reopen/` with `{}` (lands on `follow_up`) or `{"stage": "contacted"}`
   - `LEADS_LEAD_NOT_LOST`: the lead is already active; no action needed.
2. `GET /api/v1/leads/<lead.id>/` → the `lost_*` fields are now cleared, but `converted_at` (if it was ever set) is unchanged.
3. `GET /api/v1/leads/<lead.id>/history/` → both the original `lead_marked_lost` and the new `lead_reopened` entries are present. Nothing was erased.

**Audit a lead's full story** *(crosses into the `audit` module)*
1. `GET /api/v1/leads/<lead.id>/` → the current state.
2. `GET /api/v1/leads/<lead.id>/history/` → every action, newest first. Entries originate in the central audit log owned by the `audit` module; this endpoint is a scoped view of it.
3. `GET /api/v1/leads/<lead.id>/notes/` → the free text the Lead Manager wrote. Note bodies live only here, never in history entries, so a complete picture needs both calls.

**Configure the pickers** *(Admin only)*
1. `POST /api/v1/leads/sources/` with `{"code": "tiktok", "name_np": "टिकटक", "name_en": "TikTok"}` → capture `source.id`
   - `LEADS_ACTOR_FORBIDDEN`: the caller is a Lead Manager or Superadmin; only an Admin may configure.
   - `LEADS_SOURCE_CODE_TAKEN`: that code already exists, possibly on a retired entry — list with `include_inactive=true` to check.
2. `POST /api/v1/leads/loss-reasons/` with `{"code": "other", "name_np": "अन्य", "requires_detail": true}` so choosing it forces an explanation.
3. `PATCH /api/v1/leads/sources/<source.id>/` with `{"is_active": false}` to retire a channel. Existing leads keep it; new leads can no longer pick it.

## 9. Gaps

- **Conversion does not exist in this version.** `concepts/leads.txt` describes converting a lead into an applicant, but there is no such endpoint: the `applicants` and `applicant_journeys` modules have not been built. `stage: "converted"` is therefore unreachable through the API, and `converted_at`/`converted_by` are always `null`. Do not build a convert button against this version. `ready_for_conversion` is the furthest a lead can currently advance.
- **No direct applicant creation.** `concepts/leads.txt` also describes an Admin creating an applicant without a lead. That is not part of this module and has no endpoint anywhere yet.
- **401 body shape is not specified here.** Unauthenticated and expired-token responses are produced by the authentication framework, not by this module. Consult the `authenticate` module's contract for their exact shape.
- **`LeadSource.code` and `LossReason.code` values are not fixed.** They are runtime-configured rows and vary per installation. The codes used in the examples above (`walk_in`, `no_response`, `other`) are illustrative only — always populate pickers from the list endpoints and never branch on a hardcoded code.
- **`HistoryEntry.metadata` keys are per-action and not exhaustively specified.** Observed keys include `source`, `stage`, `count`, `followed_up_at`, `loss_reason`, `has_detail`, `note_id`, and `reopened_from_converted`. Treat the object as advisory display data; render `summary` as the primary label.
- **No bulk operations.** There is no bulk create, bulk stage change, or bulk close. Each lead is acted on individually.
- **No lead deletion or archival.** By design — a lead's availability is expressed entirely through its stage. Do not expect a delete endpoint to appear.
- **`updated_at` on `LeadNote` is present in the model but not exposed** in the note response shape, because notes are never edited.
