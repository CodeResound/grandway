# Security — Leads

**Owner app:** `leads`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-23

This document is required per project rulebook §19 (Documentation Requirements) because `leads` makes its own security-relevant decisions beyond the project's standard auth pattern: it is the first app with **row-level, owner-scoped** access, it deliberately excludes an authority type that `authenticate` grants full platform power to, and it reports out-of-scope records as missing rather than forbidden.

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial security documentation |

---

## 1. Access model

CLAUDE.md §9's interim pattern (`is_authenticated` + `is_staff`) cannot express what this app needs. `is_staff` is a Django admin flag, not an authority level, and it carries no notion of record ownership. The interim stand-in for this app is `leads/access.py` plus queryset-level scoping in `leads/selectors.py`.

| Authority | Leads | Sources / loss reasons |
|---|---|---|
| Lead Manager | read + write **only** rows where `created_by` is themselves | list only |
| Admin | read + write all rows | list, create, edit, deactivate |
| Superadmin | **denied — 403** | **denied — 403** |
| Unauthenticated | 401 | 401 |

Two helpers enforce the authority half:

- `require_lead_actor(user)` — allows Admin and Lead Manager; raises `ActorNotPermittedError` otherwise, which views translate to 403 `LEADS_ACTOR_FORBIDDEN`.
- `require_admin(user)` — allows Admin only; used for reference configuration and, in Phase 4, conversion.

Every view calls one of the two before touching data. There is no endpoint in this app that skips the check.

### Why Superadmin is denied

This is deliberate, not an oversight. `concepts/authenticate.txt` defines Superadmin as a platform-level authority responsible for managing Admin accounts, and states it "should not manage leads, applicants, documents, journeys, offers, or other business records unless it separately holds an ordinary Admin account." Granting it lead access would collapse that separation and put a platform-recovery credential inside day-to-day consultancy data. A person who needs both roles holds two accounts.

---

## 2. Owner scoping is applied in the database, not in Python

`selectors.get_leads_for_actor(actor)` returns `Lead.objects.filter(created_by=actor)` for a Lead Manager and the unfiltered queryset for an Admin. **Every** read path in the app — list, detail, update, all lifecycle actions, notes, and history — starts from that selector.

This matters because the alternative (fetch by id, then compare ownership in the view) leaks in two ways: it is easy to forget on a new endpoint, and it briefly loads a record the caller may not see. Scoping at the queryset level means an out-of-scope lead is never fetched at all, and a new endpoint that uses the selector inherits the rule for free.

`get_lead_for_actor(actor, lead_id)` composes on top of the scoped queryset, so a lead belonging to another Lead Manager simply does not exist as far as any code path in this app is concerned.

---

## 3. Out-of-scope records return 404, never 403

A lead the caller may not see returns **404 `LEADS_LEAD_NOT_FOUND`** — the same response as a lead id that does not exist.

A 403 would confirm that the id is real and belongs to someone else. Over a sequence of requests that turns the detail endpoint into an oracle for enumerating other Lead Managers' leads and, by extension, the consultancy's enquiry volume. Conflating the two cases removes the signal entirely.

This mirrors `authenticate.views._resolve_target`, which returns `AUTH_USER_NOT_FOUND` for accounts outside the caller's authority tier for the same reason. Reference-configuration endpoints do **not** need this treatment — sources and loss reasons are shared, non-sensitive, and listable by every lead actor, so a genuinely missing one returns a plain 404.

The distinction to hold onto: `LEADS_ACTOR_FORBIDDEN` (403) means "your authority type may never do this"; `LEADS_LEAD_NOT_FOUND` (404) means "no such lead, for you." The first is a property of the caller, the second of the record.

---

## 4. Ownership is immutable

`Lead.created_by` is set once at creation and is never accepted from a client afterwards — it is absent from both the create and update serializers, and the service sets it from `request.user`. There is no assignment, reassignment, or transfer endpoint anywhere in this app, deliberately: `concepts/leads.txt` states that a Lead Manager manages the leads they create and does not pass them to another Lead Manager.

The practical consequence is that attribution survives conversion. When Phase 4 lands, the applicant created from a lead can always be traced back to the Lead Manager who originally recorded the enquiry.

`created_by` uses `PROTECT`, so a user account referenced by any lead cannot be deleted out from under its history. Accounts are blocked rather than deleted (`concepts/authenticate.txt`), which keeps this consistent.

---

## 5. Audit trail and what never enters it

Every mutating service in this app appends exactly one `audit.AuditEvent` through `audit.services.record_event`. The event carries actor id/label/type, the entity type and id, a short summary, and — where meaningful — a `changes` map of `{field: {from, to}}`.

Constraints observed (§17):

- No passwords, tokens, session identifiers, or MFA material is ever passed in. This app handles none of them.
- No full record dumps. `changes` carries only fields that actually moved; `metadata` carries small scalars (a count, a note id, an ISO timestamp).
- Free-text the user wrote — note bodies, loss explanations, addresses — is **not** copied into audit payloads. The event records that a note was added and its id, not its contents. Note bodies live in `LeadNote` and are readable only through the owner-scoped notes endpoint.
- `AuditEvent` blocks `delete()` at both the queryset and instance level, so history cannot be rewritten by application code.

The history endpoint reads through the same owner-scoped resolution as every other per-lead route, so a Lead Manager cannot read the audit trail of a lead they do not own even though the underlying `audit` table is global.

---

## 6. Input handling

- Every user-entered text field is Unicode-normalized (NFC) in a serializer `validate_<field>()` before it reaches a service (§39.2). Un-normalized Devanagari produces byte-different strings that look identical, which breaks both equality checks and search.
- `code` fields on both reference tables are ASCII-only by validator (§39.7) and lowercased on write. Devanagari in a system identifier would leak into permission keys, log lines, and URLs.
- `full_name` (on a lead) and `name` (on a source or loss reason) are Unicode-normalized in the service layer as well as the serializer (§39.2), so a direct service caller cannot store an un-normalized name that would be unfindable by search.
- Contact numbers are validated against a permissive but bounded pattern (digits, spaces, `+ - ( )`, 5–32 chars). The permissiveness is intentional — Nepali landlines, mobiles, and international forms all differ — but it still refuses free text.

---

## 7. Known limitations

- **No object-level permission framework.** This is the interim inline pattern of §9, not the `permissions` app. When `check_permission()` is wired into the request path, the `require_*` helpers and the selector scoping should be replaced by declared `permission_key`s on the views; the registry entries needed for that already exist (`leads.lead.*`, `leads.source.*`, `leads.loss_reason.*`, `leads.note.*`). That wiring requires its own session and a §28 item 5 approval.
- **No rate limiting beyond project defaults.** Every endpoint here is authenticated and none is expensive enough to warrant a custom throttle scope today. The name-search endpoint is the one to watch as lead volume grows.
- **Conversion is not built.** `leads.lead.convert` does not exist yet. When it lands it will be Admin-only and must be idempotent, since a repeat call must not create a second applicant (§15).
