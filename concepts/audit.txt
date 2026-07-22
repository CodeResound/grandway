CONCEPT — Audit
===============

Ideation / grounding file for the `audit` app (CLAUDE.md §36). Freeform prose —
the formal schema/endpoint contracts live in the app's docs/ folder later. This
file grounds the work; it does not by itself authorize building. Draft prepared
for review — adjust anything that does not match the intended design before the
app is built.


Purpose
-------

The audit app is Grandway's accountability backbone. It owns one immutable,
queryable history of every important action and change across the whole system —
who did what, to which record, when, why, under what authority, and from where.
It exists so that any consequential state in Grandway can be explained after the
fact: how a record reached its current form, who changed it, and on whose
authority. This is the concrete expression of the project's core principle,
"Accountability over speed."

It is the system-wide counterpart to the per-app event logs that already exist
(e.g. `authenticate.AuthEvent`). Those capture events local to one app; the audit
app is the central, cross-app record other domains write their important events
into so there is a single place to review activity spanning leads, applicants,
journeys, documents, offers, files, and account/authentication actions.


Actors / Users
--------------

- System / other apps: the primary writers. Every app records its important
  actions here through an audit service call — never by writing the table
  directly. The audit app owns the write path and the immutability guarantee.
- Admin: the primary reader. Reviews activity across the system, investigates
  what happened to a record, and reconstructs a timeline for accountability.
- Superadmin: reviews platform- and authentication-level audit for admin
  accounts (mirrors the authority split in the authenticate app).
- Lead Manager: at most a limited reader — may review activity on the records
  they own/are assigned, subject to privacy scope. Not a broad audit reader.
- AI/system actors: when an action is AI-generated, the event carries AI
  provenance (model identifier, prompt/template version) per CLAUDE.md §38, so
  automated changes are as attributable as human ones.

The applicant is never a direct actor here (consistent with V1).


Core entities
-------------

- Audit event: one immutable record of a single important action. It captures
  the traceability model already defined in project_overview.txt:
  - Actor — who performed it (the acting user, or a system/AI actor), by UUID.
  - Authority — the authority the actor held when acting (Admin / Lead Manager /
    Superadmin / system / AI).
  - Action — what occurred, as a stable event type (e.g. created, updated,
    blocked, converted, printed, replaced, revoked, restored).
  - Scope / subject — which record was affected, referenced by entity type +
    UUID (never by copied identity data). May reference more than one entity
    (e.g. an action on a journey that touches an applicant).
  - Time — when it occurred (stored UTC; presented in NPT / BS at the boundary
    per the Nepal localization rules).
  - Reason — why, when an explanation is required (e.g. an admin override).
  - Source — where the action originated (app/module, request context).
  - Change — previous value and new value for the meaningful fields, when the
    action is a change. Captured as a compact before/after, not a full row copy.
  - Provenance — for AI-generated actions, the model/prompt metadata (§38).
- Entity reference: the typed pointer (entity type + UUID) that links an event
  to the record it concerns, so a record's full timeline can be assembled by
  UUID without coupling audit to any other app's models.
- Actor reference: the typed pointer to who acted, resilient to that user later
  being blocked or renamed (attribution is preserved).

Audit events are append-only: once written they are never edited or deleted.
There are no "statuses" on an event — it is a fact that happened.


Key user flows
--------------

1. Record an event (system): an app completes an important action -> it calls
   the audit service with actor, authority, action, scope, time, reason, source,
   and before/after change -> the audit app validates and appends one immutable
   event. Never blocks or silently drops; a failure to record an important
   action must be surfaced, not swallowed.
2. Review system activity (admin): open the audit log -> filter by actor, entity
   type, action, authority, date/fiscal-year range -> scan the results ->
   open one event to see full detail including before/after.
3. Reconstruct a record's history (admin): from any record, view its timeline ->
   the audit app returns every event referencing that entity UUID, oldest to
   newest -> the admin reads how the record reached its current state.
   - Failure branch: a referenced actor was later blocked/renamed -> the event
     still shows the original attribution (never rewritten).
4. Review an account's authentication activity (superadmin/admin): a focused
   slice of (3) scoped to auth events for a given user — reconciled with the
   per-account review the authenticate app already exposes.


UI screens & wireframe notes
----------------------------

- Audit log: a filterable, paginated table of events, newest first. Columns:
  time (NPT + BS), actor, authority, action, affected record (type + link),
  source, and a success/outcome marker. Filters: actor, entity type, action,
  authority, date / fiscal-year range, and a free-text search over the
  human-readable summary. Primary action: open an event.
- Event detail: one event in full — actor, authority, action, time (Gregorian +
  BS), reason, source, provenance (if AI), and a before/after diff of the
  changed fields rendered side by side. Read-only; no edit or delete controls.
- Record timeline: all events for a single entity (reached from that record's
  screen in its own app), oldest-to-newest, as a vertical timeline. Each item
  links to its event detail. Serves flow 3.
- Authentication activity: a pre-filtered audit log scoped to one account's auth
  events; serves flow 4. Shares the log layout.


Constraints / Out of scope
--------------------------

- Append-only and immutable: no edit, no delete, no soft-delete of events. Any
  attempt is a bug. (Mirrors the immutability the authenticate.AuthEvent log and
  the policy_engine change log already enforce.)
- Never a secondary source of truth for the records it describes. It stores
  references (entity type + UUID) and compact before/after values — not copies
  of applicant identity, documents, or files. PostgreSQL remains the source of
  truth (CLAUDE.md §37).
- No secrets or sensitive payloads: passwords, tokens, OTPs, MFA secrets, hashes,
  and full document/file contents are never stored in an event (§17). Financial
  and identity values appear only as the minimal before/after needed for
  accountability, subject to privacy scope.
- Local-first, privacy-first (§37): a self-hosted PostgreSQL table is the store.
  No cloud log service. A derived search/analytics projection, if ever needed,
  is rebuildable from the authoritative table and requires its own approval.
- Nepal localization (§39): timestamps stored UTC, presented in NPT and BS at
  the API boundary; audit list endpoints support the `?fiscal_year=` filter.
- Writes go through a documented audit service API only. Apps never write the
  audit table directly, and audit never contains business logic of its own.
- Out of scope for V1: tamper-proofing beyond immutability (e.g. cryptographic
  hash chaining), external SIEM export, real-time alerting/streaming, and an
  analytics/reporting layer — those are later, separately-approved additions.
  Log-based undo/rollback is explicitly NOT a goal; audit records history, it
  does not reverse it.


Resolved decisions (V1)
-----------------------

- Central vs federated: FEDERATED. Each app keeps its own log (e.g.
  authenticate.AuthEvent stays authoritative for its own review endpoint) AND
  also emits each important event to the central audit. The central audit is the
  cross-app aggregate; per-app logs are not retired. No destructive migration.
- Write path: SYNCHRONOUS service call. Apps call audit.services.record_event()
  directly. For a federated secondary emission (where the per-app log is already
  authoritative), the central emit is best-effort: wrapped so a central-audit
  failure is logged, never breaking the triggering action.
- Read authority: ADMIN + SUPERADMIN only in V1 (checked via is_staff). Lead
  Managers have no audit-read access. Own-scope Lead Manager access is deferred
  until record-ownership lives in the operational apps that own those records.


Open questions
--------------
- Before/after capture: how is "previous value / new value" produced uniformly
  across very different models without each app hand-rolling it — a shared helper,
  a serializer contract, or app-provided change dicts?
- Retention: how long are audit events kept, and are any ever archived (never
  deleted)? Does retention differ for auth vs business events?
- Relationship to core.policy_engine's change log: policy_engine already has its
  own append-only changelog for endpoint metadata — is that in scope for audit
  or deliberately separate (it is infrastructure, not business activity)?
- Does the audit app expose any write endpoint over HTTP, or is writing strictly
  an internal service call (no external write surface at all)?
