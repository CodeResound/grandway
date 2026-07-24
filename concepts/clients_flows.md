# FLOWS — Clients

**Owner app:** `clients`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/clients.txt` to the callable endpoints in `backend/clients/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **Four things govern every flow below.**
>
> 1. **Writes are Admin-only; reads are shared.** A Lead Manager loads every screen here but receives
>    403 `CLIENTS_ACTOR_FORBIDDEN` on every create, edit, retire, and restore. Hide or disable the
>    write controls for a Lead Manager rather than let them fail. Only `institutions` shares this
>    split — `applicants`, `applicant_journeys`, and `offers` do **not**.
> 2. **There is no delete, anywhere.** No screen gets a delete button. Withdrawal from use is
>    "retire", which demands a reason and keeps the record forever.
> 3. **A retired client is not hidden.** It still comes back from the unfiltered list. Whether to
>    grey it out, move it to a separate section, or drop it from a picker is a **presentation
>    decision the API deliberately leaves to the UI** — the concept asks that retired partners stay
>    "visible historically but not treated as a preferred current contact", which is a rendering rule,
>    not a filtering one.
> 4. **The romanized name fields are never displayed.** `name_romanized` and
>    `spokesperson_name_romanized` are auto-derived ASCII search keys — `"हिमाल एजुकेशन"` becomes
>    `"himala ejukesana"`. They exist so a Roman-keyboard search finds a Devanagari record. Render
>    `name_en` if present, else `name_np`.

---

## Flow: Maintain the client directory

- **Actor:** Admin
- **Goal:** Keep the partner directory current — add new partners, correct details, retire the ones
  the consultancy no longer works with.
- **Entry point:** Client List

**Steps:**

1. **Client List** — see what exists →
   `GET /api/v1/clients/` (`clients.client.list`)
   - **Requires state:** nothing. This is the only screen in the project that works against a
     completely empty database with no prerequisite record anywhere.
   - **Side effects:** none.
   - Ordered **alphabetically by `name_np`**, not newest-first — the opposite of every other list in
     the project. Do not add a "recently added" default sort; there is no `ordering` parameter.
   - Rows carry `primary_contact_number` and `email`, so the directory's phone-and-email columns need
     no per-row detail fetch.

2. **New Client Form** — add a partner →
   `POST /api/v1/clients/` (`clients.client.create`)
   - **Requires state:** nothing.
   - **Side effects:** appends `client_created` to the audit log. Nothing outside this app changes —
     nothing outside this app references a client.
   - **Only `name_np` is required.** Everything else, including the spokesperson and any phone
     number, is optional: a partner may be an organization you deal with before you know who to ask
     for. Do not mark the spokesperson fields required in the form.
   - *Failure — `VALIDATION_ERROR` on `name_np`:* inline error. The form's one mandatory field.
   - *Failure — `CLIENTS_CONTACT_NUMBER_DUPLICATE`:* the same number was entered twice in the numbers
     repeater. Highlight the duplicate rows, not the whole form.
   - *Failure — `CLIENTS_ACTOR_FORBIDDEN`:* a Lead Manager reached this form. The button should not
     have been there.
   - **Do not send `name_romanized`** unless the user has explicitly overridden a bad transliteration.
     It is derived server-side, and a supplied value is never overwritten — including on later edits.

3. **Edit Client Form** — correct details →
   `PATCH /api/v1/clients/<client_id>/` (`clients.client.update`)
   - **Requires state:** the client.
   - **Side effects:** appends `client_updated` carrying each changed field's previous and new value.
     **This is where the concept's "the previous value should remain traceable" requirement is met** —
     there is no version history to browse.
   - **Send only the changed fields.** A read-modify-write-the-whole-object form fails here: including
     `status` in the payload returns 400 `CLIENTS_STATUS_IMMUTABLE`. This differs from `institutions`,
     which silently drops immutable fields — do not carry that form component across.
   - **Contact numbers replace, they do not append.** Send the complete new array. Omit the key to
     leave them alone; send `[]` to clear them. The two are different, and a form that always sends
     `contact_numbers: []` when the repeater is empty will silently wipe them.
   - **A no-op save writes no audit event.** A UI that shows "saved, history updated" after an
     unchanged submit will be lying. *(Exception: sending `contact_numbers` always counts as a change.)*

4. **Client Detail** — retire a partner →
   `POST /api/v1/clients/<client_id>/retire/` (`clients.client.retire`)
   - **Requires state:** the client's status is `active`.
   - **Side effects:** appends `client_retired` with the reason; sets `status`, `status_note`,
     `retired_at`, `retired_by`. **The client stays in the directory.**
   - **The reason input is mandatory** — enforce it before submit. Inactive clients are kept forever,
     so "why is this one inactive" must be answerable from the record.
   - *Failure — `CLIENTS_STATUS_NOTE_REQUIRED`:* whitespace-only reason reached the server.
   - *Failure — `CLIENTS_CLIENT_ALREADY_RETIRED` (409):* refetch; someone else retired it.
   - **This is the closest thing to a delete this app has.** Label the button "Retire", not "Delete"
     or "Archive", and say in the confirmation that the record is kept.

5. **Client Detail** — bring one back →
   `POST /api/v1/clients/<client_id>/restore/` (`clients.client.restore`)
   - **Requires state:** the client's status is `inactive`.
   - **Side effects:** appends `client_restored`; clears the three retirement fields.
   - *Failure — `CLIENTS_CLIENT_NOT_RETIRED` (409):* the client was already active.
   - **Restoring does not erase the retirement.** `client_retired` and its reason stay in the history
     forever. If the UI shows "never retired" after a restore it is contradicting the audit trail.

---

## Flow: Find the right partner

- **Actor:** Lead Manager or Admin
- **Goal:** Confirm who to call or email at a partner organization.
- **Entry point:** Client List, opened from anywhere in the app.

**Steps:**

1. **Client List** — search →
   `GET /api/v1/clients/?status=active&search=<query>` (`clients.client.list`)
   - **Requires state:** nothing.
   - **Side effects:** none.
   - **One search box covers six fields** — the organization's Devanagari, English, and romanized
     names, **and** the spokesperson's three. The concept's "look up the company or contact person"
     is one input, not two.
   - **Pass `status=active` for this flow.** Omitting it returns retired partners too, which is right
     for the maintenance directory and wrong for "who do I call".
   - *Failure — `VALIDATION_ERROR` on `status`:* the value is `inactive`, not `retired` or `archived`.

2. **Client Detail** — read the full record →
   `GET /api/v1/clients/<client_id>/` (`clients.client.read`)
   - **Requires state:** the client.
   - **Side effects:** none.
   - The list row has only one number; the detail has all of them with their labels
     (`mobile`, `work`, `whatsapp`, `viber`, …), plus website, address, and notes.
   - **`is_primary` is not guaranteed unique or present.** A client may have zero primary numbers or
     three. The array is ordered primaries-first, so `contact_numbers[0]` is the sensible default —
     do not assume exactly one is flagged.
   - **If `is_active` is false, show it.** The record is still readable and its numbers may still
     work, but the concept asks that a retired partner not be presented as a preferred current
     contact. A badge and a muted row are enough.

3. **Client Detail → history panel** — *(optional)* see how the record got here →
   `GET /api/v1/clients/<client_id>/history/` (`clients.client.list_history`)
   - **Requires state:** the client.
   - **Side effects:** none.
   - **Readable by a Lead Manager**, unlike every write in this app. The concept asks for "a visible
     history or audit trail panel if available" — it is available.
   - This is the only place a past retirement shows up after a restore, and the only place a previous
     spokesperson's name can be recovered.
   - Contact-number changes appear as a marker (`changes.contact_numbers`), **not** as a before/after
     list of the numbers. You cannot show "0141234567 was removed" from this data.

---

## Flow: Attribution support — NOT DELIVERABLE

`concepts/clients.txt` flow 3 describes referencing a client when recording where a lead or applicant
came from, so reporting can later show which organizations send work.

**No endpoint in this project supports it.** There is no `client` field on a lead or an applicant, no
`?client=` filter, and no referral count, statistic, or report anywhere. The `clients` app supplies
the directory; nothing consumes it yet.

This is listed rather than omitted because a frontend author reading the concept file will look for
these endpoints and needs to know they do not exist rather than conclude they missed them. Building
this means changing the shipped `leads` app and is a separate session.

**Do not ship UI that implies attribution works** — no "referred by" picker on a lead form, no
"leads referred" count on the client detail. Both would need an API that is not there.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `clients.client.list` | `GET /api/v1/clients/` | Maintain the directory (step 1); Find the right partner (step 1) | The **Client List** screen. Alphabetical, not newest-first |
| `clients.client.create` | `POST /api/v1/clients/` | Maintain the directory (step 2) | Admin only. Only `name_np` is required |
| `clients.client.read` | `GET /api/v1/clients/<client_id>/` | Find the right partner (step 2) | The **Client Detail** screen |
| `clients.client.update` | `PATCH /api/v1/clients/<client_id>/` | Maintain the directory (step 3) | Admin only. Rejects `status` — send only changed fields |
| `clients.client.retire` | `POST /api/v1/clients/<client_id>/retire/` | Maintain the directory (step 4) | Admin only. Reason mandatory |
| `clients.client.restore` | `POST /api/v1/clients/<client_id>/restore/` | Maintain the directory (step 5) | Admin only |
| `clients.client.list_history` | `GET /api/v1/clients/<client_id>/history/` | Find the right partner (step 3) | Readable by a Lead Manager |

**Every screen in `concepts/clients.txt` is backed** — Client List, Client Detail (including its
history panel), and the New / Edit Client Form. The unbacked item is not a screen but flow 3,
"Attribution support", above.

## Cross-app dependencies

- **This app references (outbound):** none. No flow here calls another app's endpoint, and the
  backend holds no foreign key into any business app.
- **Referenced by other apps (inbound):** none. No other app's flow file references a `clients.*`
  permission key.

**This is the only app in the project with no cross-app flow in either direction.** It will not stay
that way: when `leads.Lead` gains a client reference, `concepts/leads_flows.md` will reference
`clients.client.list` in its lead-creation flow (a picker fed by this directory), and the ripple rule
below will apply for the first time.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.
