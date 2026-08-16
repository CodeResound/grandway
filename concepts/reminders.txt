CONCEPT — Reminders
===================

Purpose
-------
Grandway needs a lightweight reminder capability so staff can set a future note
against a record and be prompted to revisit it on a specific date.

This is for operational follow-up, not task management. A reminder can exist for
any reason: payment chase, document follow-up, callback, deadline check, or any
other future action the consultancy wants to remember.

The reminder feature belongs with Grandway's existing record-centric model. It
attaches to the same kinds of records the consultancy already works on, instead
of creating a separate to-do system. The reminder lives as a note on the person
or company record, and later becomes a notification when its date arrives.


Actors / Users
--------------
- Admin: creates and maintains reminders on records; receives the reminder
  alert in the notification feed when the date arrives and acts on it.
- Lead Manager: creates and maintains reminders on the records they work on.
  Does not receive reminder alerts — the alert itself is Admin follow-up only.

Reminders are for internal operational use. They are not a customer-facing
feature.


Core entities
-------------
- Reminder: a future follow-up note tied to exactly one source record — an
  applicant or a client. Three essential parts: the source record, a future
  due date, and a note explaining why the reminder exists. The due date is
  date-only, not time-based; the reminder is considered due at the start of
  the chosen day. This avoids the complexity of time zones, exact hours, and
  user scheduling differences while still giving the consultancy a clear
  future trigger. A reminder is one-off: it is either completed (the
  follow-up happened) or dismissed (no longer relevant). While still open it
  may be rescheduled to a new date or have its note corrected.


Key user flows
--------------
1. Set a follow-up: open an applicant or client record -> add a reminder with
   a due date and a note -> the reminder sits on the record until its date.
2. Due date arrives: Grandway surfaces the reminder as an actionable alert in
   the normal notification layer, visible to Admins only -> the Admin jumps
   from the alert back to the reminder and the record it belongs to -> the
   Admin (or the staff member working the record) completes or dismisses the
   reminder -> the alert clears.
   - If nobody acts, the alert stays visible; it does not duplicate.
3. Reschedule: a reminder that should fire later is moved to a new date with
   an updated note -> the change is traceable -> the alert fires on the new
   date instead.
   - If a reminder still needs attention after it was completed or dismissed,
     the user creates a new reminder with a new date and note (no snooze).


UI screens & wireframe notes
----------------------------
- Reminders panel (on the applicant detail and client detail screens): the
  record's reminders, most recent first, showing due date, note, status, and
  who set it. Primary actions: add reminder, reschedule, complete, dismiss.
  Serves flows 1 and 3.
- Notification feed (existing notifications screen): a due reminder appears as
  a normal alert whose link jumps back to the reminder/record. Serves flow 2.
- Reminder history (within the record's reminder panel or detail view): the
  audit trail of what was set, when, and what happened to it later — creation,
  reschedules, completion, dismissal. Reminders are operational memory; the
  consultancy should be able to tell why a reminder existed even after the
  date has passed.


Constraints / Out of scope
--------------------------
This feature is not:
- a general task board
- a recurring scheduler
- a messaging inbox
- a CRM workflow engine
- a replacement for the underlying applicant or client record

Hard boundaries:
- Attachable to applicants and clients only.
- Date-only due dates; due at the start of the chosen day (Nepal time).
- One-off reminders; no snooze. A follow-up that outlives its reminder gets a
  new reminder.
- Only Admin users receive reminder notifications.
- Reminder lifecycle events (creation, completion, dismissal, rescheduling)
  remain traceable in Grandway's history model.
- The reminder only exists to surface a future follow-up at the right time.


Open questions
--------------
None outstanding. Decisions settled at planning: due dates may be today or
later (a today-dated reminder fires on the next nightly sweep); note-only
edits are allowed while a reminder is open; completed/dismissed are final
(create a new reminder instead of reopening); an optional reason on
complete/dismiss is recorded in history only.
