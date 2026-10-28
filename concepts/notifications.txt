# notifications

## Goal
`notifications` is the user-facing alert layer for Grandway. It tells staff what needs attention, why it matters, and where to go next. It does not own the underlying business state; it reacts to it.

## Why it exists
The platform already tracks the real work in other apps:
- applicants and journeys hold the person and study plan
- documents, document_history, and document_templates handle document work
- uploaded_files handles files and file lifecycle
- offers handles admission decisions
- checklists handles outstanding work
- dashboards summarize operational health
- audit records important actions

`notifications` turns important state changes and deadlines into actionable alerts.

## What should create notifications
The project overview calls out these events as the core set:
- assignment
- follow-up
- missing information
- missing documents
- appointment dates
- checklist deadlines
- offer expiry
- passport or test expiry
- important lifecycle changes

That is the right starting list because each one is operationally useful and time-sensitive.

2026-10-29 — the frontend's updates.md §4 widened the sources. Besides the nightly deadline sweep and the original save-driven alerts, these events now raise notifications, each announced by the owning app after its change commits, with the person who acted (who is never told about their own action):
- leads: a lead created, converted into an applicant, deleted, or restored
- applicants: a status change, a restore from archive, an applicant assigned to or taken off someone
- visit notes on a lead or an applicant (general notes raise nothing)
- documents: a document marked ready (Admins only, as documents are Admin-only)
- language-test results expiring or expired (the sweep raises these now that applicants hold language tests)
Alerts about an applicant also reach that applicant's assignee when one is set.

## What makes a good notification
A useful notification should answer:
- what happened
- who it is for
- what record it belongs to
- why it needs attention
- when it becomes urgent or overdue
- what action the user should take next

Notifications should be short, specific, and linked to the source record.

## Notification types
The app should support a small set of practical types:
- assignment alerts
- follow-up reminders
- missing information alerts
- missing document alerts
- appointment reminders
- checklist due and overdue alerts
- offer response reminders and expiry alerts
- passport or test expiry alerts
- lifecycle change alerts, such as status transitions or closure

The type should drive priority, iconography, and grouping, not business logic.

2026-10-29 — types are grouped into eleven categories for tabs, counts, and muting: lead, applicant status, journey, assignment, notes, follow-up, documents, checklist, offer, file, expiry. A category is derived from the type, never stored. There is no "case" category — journeys are Grandway's equivalent of a case.

## Recommended user experience
The best notification experience is an inbox-like feed with:
- unread and read state
- due now / due soon / later grouping
- filters by type and source record
- quick links to the underlying record
- optional dismiss, snooze, or mark-resolved actions
- bulk clear for low-priority items, if allowed

The most important notifications should stay visible until the work is handled.

2026-10-29 — per-person preferences exist: each user can turn any category off for the in-app feed, and can choose "only my applicants" so alerts about applicants assigned to someone else (or to no one) are not raised for them. Preferences apply to new alerts only; they never hide what is already in the feed. The inbox can be split into per-category tabs with their own unread counts and their own "mark all read". Snooze is still not built — dismiss remains one-way.

## Delivery model
`notifications` should first be thought of as an in-app alert stream.

Future delivery channels can be added later, but they should all point back to the same notification record:
- in-app center
- email
- SMS or messaging
- push, if the product ever needs it

The alert record should remain the source of truth for delivery status.

## State model
A practical notification usually needs:
- unique id
- recipient
- source app and source record id
- notification type
- title and body
- priority or severity
- read/unread state
- delivery state
- created time
- due time or expiry time when relevant
- resolved or dismissed state
- audit trail for important changes

## Relationship to other apps
Notifications should point at, but not replace:
- offers for response and expiry alerts
- checklists for overdue work
- documents for missing or pending document work
- uploaded_files for rejected or replacement-needed files
- test_scores for expiry alerts (2026-10-29: there is no test_scores app — language tests live on the applicant, and the expiry alert points there)
- leads for the enquiry lifecycle and visit notes (2026-10-29)
- journeys for stage changes
- applicants for person-level follow-up

If the source record changes, the notification should not silently rewrite history.

## Lifecycle
A notification usually moves through:
1. Created
2. Delivered or queued
3. Read or acknowledged
4. Resolved, dismissed, or expired

Some alerts may remain active until the source issue is fixed. Others can be informational and simply become read.

2026-10-29 — retention: the nightly sweep deletes event alerts and resolved deadline alerts once they are older than 90 days (an operator setting). Dismissed and still-open deadline alerts are kept, because they are what stops the same condition being raised again. This replaces "keep every alert forever"; the audit log, not the feed, is the long-term record.

## Rules for useful alerts
- Alert on things that need action, not every minor update.
- Prefer one clear notification over several noisy ones.
- Link each notification to the exact record that caused it.
- Keep the wording specific enough that the user knows what to do next.
- Preserve the alert history even after the source issue is fixed.

## Boundaries
`notifications` should not:
- own applicants, documents, offers, or checklists
- compute core business status by itself
- duplicate dashboards
- become a general messaging inbox
- hide the original source record

## Rules to keep aligned with the current project
- Grandway keeps business state in the domain apps.
- Notifications are triggered by meaningful source events and deadlines.
- Dashboards summarize the current state; notifications push the user toward action.
- Audit keeps the immutable record of the action itself.

## Open questions
- Which notification types are mandatory in v1.
- Whether users can mute or snooze specific notification categories. (2026-10-29: muting by category is built, per user, along with "only my applicants". Snooze is still out.)
- Whether emails are required at launch or only in-app alerts.
- How aggressively overdue items should keep resurfacing.
- Whether each role gets a separate default notification feed. (2026-10-29: no separate feeds; routing differs by role — e.g. new leads go to Admins, unassigned applicants' status changes go to every Admin and Lead Manager — and each user can narrow their own with preferences.)
- Whether push delivery is needed. (2026-10-29: the frontend asked for server-sent events and an unread-count endpoint; both declined for now — the client polls the summary, which carries every count.)

## Outcome
This app should keep staff informed about the most important work in the system without turning into another source of business data.
