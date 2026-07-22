# Security — Audit

**Owner app:** `audit`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-22

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-22 | AI (Claude Opus 4.8) | Initial security notes — immutable central audit log |

---

## §1 Immutability

`AuditEvent` is append-only. Its `QuerySet.delete()` and instance `delete()` raise
`ImmutabilityError`, and rows are never updated. There is no write API — events are
appended only through `audit.services.record_event`, called by other apps in-process.
The Django admin registration for `AuditEvent` disables add/change/delete. This makes
the audit log a trustworthy accountability record: once written, an event cannot be
altered or removed through the application. (`reset_dev_data` detects the blocked
bulk delete and preserves the table, like every append-only log in the project.)

## §2 No secrets, no record copies

Events store references — actor and affected record as `type + UUID` (+ a preserved
label), never foreign keys or copies of the underlying identity, document, or file
content. Passwords, hashes, tokens, OTP/MFA secrets, and full document/file bodies are
never written to `changes`, `metadata`, `reason`, or `summary` (§17). The `changes`
map carries only the minimal before/after values needed for accountability, subject to
the emitting app's privacy scope. Because there are no FKs, attribution survives even a
hard delete of the referenced user.

## §3 Read access — Admin/Superadmin only

The read endpoints require an authenticated user with `is_staff` (Admin/Superadmin);
Lead Managers have no audit access in V1. This is the interim access pattern (§9): 401
when unauthenticated, 403 when authenticated but not staff. Own-scope Lead Manager
access is deferred until record ownership lives in the operational apps.

## §4 Federated, best-effort emission

Emitting apps keep their own authoritative logs (e.g. `authenticate.AuthEvent`) and
*also* emit to audit. The central emit is best-effort: `authenticate` wraps its
`audit.services.record_event` call so a failure is logged and swallowed, never breaking
the triggering authentication action. The trade-off is explicit — the per-app log is
the source of truth for its own domain; the central audit is the cross-app aggregate,
and a rare emit failure loses a central copy but not the authoritative per-app record.

## §5 AI provenance

When an action is AI-generated, the event carries `actor_type = "ai"` and AI provenance
in `metadata` (model identifier, prompt/template version) per §38, so automated changes
are as attributable as human ones.

## §6 Deferred (later phases)

Tamper-evidence beyond application immutability (e.g. cryptographic hash chaining),
external SIEM export, real-time alerting/streaming, arbitrary date-range and free-text
filtering, and own-scope Lead Manager read access are deferred to later, separately
approved work.
