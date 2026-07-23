# Security — Applicant Journeys

**Owner app:** `applicant_journeys`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-23

This document is required per project rulebook §19 because `applicant_journeys` makes its own access decisions beyond the project's standard auth pattern: it adopts the shared model from `applicants` but deliberately relaxes the creation restriction, and it enforces a lifecycle whose terminal states must not be reachable by an ordinary field write.

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-23 | AI (Claude) | Initial security documentation |

---

## 1. Access model

| Authority | Read / edit / create journeys | Close, defer, reopen |
|---|---|---|
| Lead Manager | any journey | allowed |
| Admin | any journey | allowed |
| Superadmin | **denied — 403** | **denied — 403** |
| Unauthenticated | 401 | 401 |

Journeys follow `applicants`: shared across the consultancy, not owner-scoped. The reasoning is identical — once a person is a client rather than one Lead Manager's prospect, several staff will legitimately work on their objectives.

**Creation is deliberately *not* Admin-restricted here**, which differs from `applicants`. Creating an applicant is an entry decision: it admits someone to the applicant lifecycle, so `concepts/applicants.txt` reserves it to an Admin. Adding a second or third objective for someone who is *already* a client is ordinary operational work — a Lead Manager who cannot record "this person now also wants Canada" would have to escalate a routine update.

Superadmin exclusion matches every other operational app: it is a platform authority for managing Admin accounts and does not participate in consultancy operations (`concepts/authenticate.txt`).

## 2. Terminal states are unreachable by field write

The three non-active stages — `completed`, `closed`, `deferred` — cannot be set through the update endpoint or the stage dropdown. Each requires its own action, and each action demands information a bare stage change does not carry:

- `close` requires an `outcome`, and requires a `closure_reason` when that outcome is `other`.
- `defer` requires the intake being deferred to.
- `completed` is not directly settable at all: it is the result of closing with `outcome = successful`.

This is enforced in three places rather than one: the stage serializer offers only the six active stages, `services._assert_selectable_stage` rejects a terminal value reaching the service by any other path, and the update serializer has no `stage` field at all.

The point is not ceremony. A journey that ended is a fact the consultancy will be asked to explain later, and a stage dropdown that can silently write `closed` produces records with no recorded reason. Requiring the outcome at the moment of closure is the only way to guarantee every ended journey can be accounted for.

## 3. A terminal journey is frozen until reopened

While a journey is completed, closed, or deferred, the stage, defer, and close actions all refuse with 409 `JOURNEYS_STAGE_NOT_EDITABLE`. The only way forward is `reopen`.

This prevents a closed journey drifting back into active work without anyone recording that it was revived — the reopen writes its own audit event, so the revival is visible in the history rather than appearing as an ordinary stage change.

Reopening clears the closure and deferment fields, but **the audit events recording them are never removed**. A journey that was completed and then reopened still shows both facts in its history.

## 4. Ownership and immutability

- **`applicant` is immutable.** It is set once at creation and dropped from the update serializer. A journey belongs to exactly one applicant and is never transferred — moving someone's study objective to a different person would corrupt both files' histories.
- **`creation_source` and `created_by` are set once by the service** and appear in no write serializer, so no client can claim a manually created journey came from a lead conversion.
- `applicant` uses `PROTECT`, so an applicant with any journey cannot be removed from under it. `created_by` is likewise `PROTECT`.

## 5. Lifecycle independence

A journey's stage never changes the applicant's status, and archiving an applicant never closes their journeys. Neither app's service touches the other's state field.

This is a correctness property rather than an access control, but it belongs here because the failure mode is silent: if closing a journey auto-archived the applicant, a person with one abandoned plan and one active plan would disappear from active lists. Both directions are covered by tests in `applicant_journeys/tests/test_journeys.py`.

## 6. Audit trail

Every mutating service appends exactly one `audit.AuditEvent` through `audit.services.record_event`, carrying actor identity, the entity, a summary, and — where meaningful — a `changes` map.

Constraints observed (§17):

- No secrets or credentials; this app handles none.
- No full record dumps. `changes` carries only fields that moved.
- Free text the user wrote — journey notes, closure reasons, deferment reasons — is **not** copied into audit payloads. The event records that a journey was closed and with which outcome, not the prose explaining it.
- `AuditEvent` blocks `delete()` at both queryset and instance level.

## 7. Known limitations

- **No object-level permission framework.** Interim inline pattern of §9; registry entries (`applicant_journeys.journey.*`) exist for the eventual `permissions`-app wiring.
- **No per-journey ownership.** Any lead actor may close or reopen any journey. There is no notion of a journey owner, deliberately — but it also means nothing prevents one staff member closing another's work.
- **Institution and program are unvalidated free text**, so they are not a trustworthy basis for any access or reporting decision.
- **No rate limiting beyond project defaults.**
