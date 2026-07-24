# Security — Applicants

**Owner app:** `applicants`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-23

This document is required per project rulebook §19 because `applicants` makes its own security-relevant decisions beyond the project's standard auth pattern: it **deliberately inverts** the owner-scoping model that `leads` established, it splits read/write access from creation authority, and it holds the most sensitive personal data in the system so far.

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial security documentation |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. Noted where a photograph may now be stored and how its access differs |

---

## 1. Access model — and why it differs from leads

| Authority | Read / edit applicants | Create an applicant |
|---|---|---|
| Lead Manager | **any** applicant | **denied — 403** |
| Admin | **any** applicant | allowed |
| Superadmin | **denied — 403** | **denied — 403** |
| Unauthenticated | 401 | 401 |

`leads` scopes rows to their creator: a Lead Manager sees only leads they recorded. This app does the opposite, and the difference is intentional rather than an inconsistency.

`concepts/leads.txt` draws the line explicitly: "The Lead Manager owns the lead record only during the lead lifecycle. Once an applicant is created, the applicant and applicant journey belong to their respective modules and follow their own lifecycle rules." A lead is one staff member's prospect; an applicant is the consultancy's client, and several people will legitimately work on their file.

There is also a practical trap that owner-scoping would spring. Conversion is Admin-only, so a converted applicant's `created_by` is the **Admin who converted**, not the Lead Manager who sourced the enquiry. Under owner-scoping the applicant would become invisible to the person who knows the most about them. Sharing avoids that without needing a special case.

Attribution survives regardless: `leads.Lead.created_by` still names the originating Lead Manager, and `applicant.originating_lead` resolves back to that lead.

## 2. Creation is Admin-only

Both creation paths — direct creation and lead conversion — require Admin authority.

`concepts/applicants.txt` states it plainly: "A Lead Manager cannot create an applicant by either path. Lead Managers work leads; entry into the applicant lifecycle is an Admin decision."

Enforced by `access.require_admin` on `POST /api/v1/applicants/` and, for the conversion path, by the same check inside `leads.views.LeadConvertView`. Editing is *not* restricted this way — a Lead Manager who may not admit someone to the lifecycle may still maintain their file afterwards.

## 3. Superadmin exclusion

Identical to `leads`. The Superadmin is a platform authority for managing Admin accounts and "should not manage leads, applicants, documents, journeys, offers, or other business records unless it separately holds an ordinary Admin account" (`concepts/authenticate.txt`).

This matters more here than in `leads`: the applicant record holds dates of birth, passport numbers, family details, and home addresses. A platform-recovery credential should not open that.

## 4. Why 404-not-403 does *not* apply here

`leads` reports an out-of-scope lead as 404 so ownership cannot be enumerated. This app has no equivalent, because there is no scoping to hide — every applicant is visible to every lead actor, so a 404 means the record genuinely does not exist. Introducing the conflation here would obscure real errors for no security gain.

The distinction to carry across both apps: `LEADS_LEAD_NOT_FOUND` may mean "not yours"; `APPLICANTS_APPLICANT_NOT_FOUND` always means "no such applicant."

## 5. Immutable provenance

`creation_source` and `created_by` are set once by the service and appear in **neither** write serializer, so no client can claim an applicant was converted from a lead when it was created directly, or reassign authorship.

This matters because `creation_source` is the only field distinguishing a lead-originated applicant from a direct one once the lead itself is out of view, and it feeds the reporting that will eventually answer "where do our clients come from."

`created_by` uses `PROTECT`, so a user account referenced by any applicant cannot be deleted out from under its history. Accounts are blocked rather than deleted, which keeps this consistent.

## 6. Sensitive data handling

This app holds the most sensitive data in the system to date: dates of birth, passport numbers and expiry, home addresses, and family members' names and contact details.

- **Nothing sensitive enters the audit log.** Events record *that* a passport or address changed and the count of rows replaced — never the passport number, never the address text, never a family member's name. `changes` is populated only for scalar identity fields on the applicant itself.
- **No field-level redaction exists.** Every lead actor who can read an applicant reads the whole record, passport included. Whether passport and date of birth should be Admin-only is an open question in `concepts/applicants.txt`; today they are not.
- **No photograph is stored *by this app***, deliberately (§14) — see `DATA_CONTRACT.md` Deliberate Deviations. A photograph may now be stored **against** an applicant in `uploaded_files`, which owns the whole §14 contract for it (see that app's `docs/SECURITY.md`). Note the access difference: this app's records and that app's files are both readable by any Admin or Lead Manager, but a file's *bytes* leave the system only through an audited download endpoint.
- **No export endpoint.** There is no bulk download of applicant data, which keeps the exposure surface to one record per request.

## 7. Input handling

- Every user-entered text field is Unicode-normalized (NFC) in a serializer `validate_<field>()` before reaching a service (§39.2).
- `full_name` is derived server-side from `full_name` and never accepted on create, so the search field cannot be poisoned to make an applicant unfindable.
- `passport_number` is upper-cased on write, so lookups do not silently miss on case.
- Contact numbers use the shared `core.validators.validate_contact_number` — permissive enough for Nepali landlines, mobiles, and international forms, but still refusing free text.
- `expiry_date` must follow `issued_date`, which catches the common transposition of the two dates at entry time.

## 8. Known limitations

- **No object-level permission framework.** This is the interim inline pattern of §9. Registry entries (`applicants.applicant.*`) already exist for the eventual `permissions`-app wiring; that requires its own session and a §28 item 5 approval.
- **No duplicate detection.** Two records for the same person is a real risk and is explicitly out of scope — resolving it needs a merge process that preserves both histories.
- **Archival hides nothing.** An archived applicant still appears in list and search results unless the caller filters on status. This is deliberate (nothing is hidden from staff) but means archival is not a privacy control.
- **No rate limiting beyond project defaults.** Every endpoint is authenticated; the name-search endpoint is the one to watch as volume grows.
