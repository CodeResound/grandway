# APPLICANTS — Grandway

## Purpose

The Applicants module owns the permanent, authoritative record of a person the
consultancy is working with.

An applicant is the person. It is not a study plan, an application, or a case.
The applicant record holds who someone is — their identity, how to reach them,
where they live, their passport, their family, and who to contact in an
emergency. Everything that changes per study objective belongs to an applicant
journey, not here.

There is exactly one applicant record per real person. Journeys, education
records, test attempts, documents, and files all reference that one record
rather than carrying their own copy of a name or a phone number.

## How an applicant comes into existence

There are exactly two ways, and the record remembers which one was used.

Lead conversion

An Admin converts a lead into an applicant. Identity and contact information are
copied across from the lead, and the lead stays permanently linked so the
applicant's origin — and the Lead Manager who first recorded the enquiry —
remains traceable.

Direct Admin creation

An Admin creates an applicant with no preceding lead. Grandway does not require
a reason for skipping the lead lifecycle; walk-ins who are already committed, or
people referred directly by a partner, do not need a lead record invented for
them after the fact.

Both paths record who created the applicant and when. A directly created
applicant has no originating lead unless one is explicitly linked later through
an approved correction.

A Lead Manager cannot create an applicant by either path. Lead Managers work
leads; entry into the applicant lifecycle is an Admin decision.

## Applicant information

The applicant record should hold the permanent identity of the person and
nothing that varies per study objective.

Identity

* Full name
* Date of birth
* Gender
* Nationality

Contact

* Multiple contact numbers, each labelled
* One email address
* Addresses — permanent and current

The same reasoning as leads applies: a person may have several usable numbers
but one working email address.

Identity documents

* Citizenship certificate number and the district that issued it
* National identity card number

Ward-office (Woda) letters print these. They are stored as entered.

Passport

* Passport number
* Issuing country
* Place of issue
* Issue date and expiry date

Passport expiry matters operationally, because an expiring passport can block a
visa application. The record should make that date easy to find.

Family

* Family members, each with a relationship (including grandfather and
  grandmother, for ward-office letters), name, occupation, contact number, and
  citizenship number
* Emergency contacts, each with a relationship and contact details

Family members and emergency contacts are recorded separately because they are
not the same thing. A person's emergency contact may be a friend, a landlord, or
a colleague rather than a relative.

## What does not belong on the applicant

Education records and language-test results are kept on the applicant
(2026-10-29) — the separate education and test-score modules sketched in
`concepts/education.txt` and `concepts/test_scores.txt` were folded in here,
because the requirement was small enough not to justify new modules:

* Education — each qualification with its level (SEE / +2 / Diploma / Bachelor /
  Master / PhD / Other), programme, institution, completion status, score (GPA or
  percentage) with how it reads, and start/completion years in BS or AD.
* Language tests — each IELTS, PTE, TOEFL, Duolingo, or other sitting with its
  overall and four skill scores (validated per test), test date, certificate
  number, and expiry date.

Both are lists on the applicant record, edited like family members. A converted
lead's highest qualification and language certificates arrive as these records.

Study objectives, destinations, intakes, budgets, and outcomes belong to
applicant journeys. Documents and uploaded files belong to their own modules.

The applicant record answers "who is this person." It does not answer "what are
they trying to do," "what have they studied," or "what have they scored."

## Applicant status

The applicant status describes the person's standing with the consultancy. It is
deliberately separate from any journey stage — a person may have one journey
that succeeded and another that was abandoned, and neither of those is the
person's status.

Recommended V1 statuses:

1. Active
2. Dormant
3. Archived

Active

The consultancy is currently working with this person.

Dormant

The person is not currently being worked with but may return. Nothing is wrong;
there is simply no active work.

Archived

The person's file is closed. Archival is reversible and destroys nothing.

Status is set manually. It is never changed automatically as a side effect of a
journey opening, closing, or reaching an outcome.

## Visibility

Applicants are shared across the consultancy. Any Admin or Lead Manager may view
and edit any applicant.

This is deliberately different from leads. A lead is owned by the Lead Manager
who created it and is invisible to their colleagues. An applicant is not: once a
person enters the applicant lifecycle, they are the consultancy's client rather
than one staff member's prospect, and several people will legitimately need to
work on their file.

Lead ownership attribution survives conversion, but it grants no exclusive
access to the resulting applicant. The lead's owner becomes the applicant's
assignee (see Assignment), which decides who is notified — not who may see.

## Assignment (decided 2026-10-29, frontend updates.md §4)

An applicant may optionally be assigned to one staff member — an active Admin or
Lead Manager. Assignment routes notifications only: the assignee hears about the
applicant's status changes, restores, visit notes, journey moves, expiring
passports and language tests, and due reminders. It never changes access —
every Admin and Lead Manager still views and edits every applicant, assigned or
not. Small teams can ignore it; an unassigned applicant's alerts go to the whole
team.

* An Admin may assign anyone eligible, reassign, or clear the assignment.
* A Lead Manager may take an unassigned applicant for themselves, or release one
  they hold — never assign someone else or take a colleague's file.
* A converted applicant starts assigned to the lead's owner, when that person is
  still an active Admin or Lead Manager; a directly created one starts unassigned.
* The list can be filtered to "mine", "unassigned", or a named person.
* Assigning and unassigning appear in the applicant's history, and the person
  gaining or losing the applicant is notified.

## No deletion

Applicants are never deleted. A closed file is archived (the UI may call it
"Delete"), and archival is reversible — by an Admin, who restores the applicant
to the status they had before archiving. Anyone who can change status may
archive; only an Admin brings a file back. (Enforced from 2026-10-29.)

The record carries identity, history, and the attribution for where the person
came from. Deleting it would destroy the consultancy's ability to explain its
own past work.

## Correction and history

Applicant information is corrected in place rather than versioned. Names change,
people move, passports are renewed.

Important applicant actions should appear in a chronological history, including:

* Applicant created, noting whether from a lead or directly
* Identity information changed
* Contact information changed
* Address changed
* Passport information changed
* Family or emergency contact changed
* Status changed
* Assigned or unassigned

History entries should not be silently rewritten or removed.

## Permissions

Admin

An Admin may:

* Create an applicant directly
* Convert a lead into an applicant
* View and edit any applicant
* Change applicant status
* Archive and restore an applicant
* Review applicant history
* Read, write, correct, and remove any note on an applicant
* Assign any applicant to any active Admin or Lead Manager, or clear it

Lead Manager

A Lead Manager may:

* View any applicant
* Edit any applicant's information
* Change applicant status, including archiving — but not restoring
* Review applicant history
* Read and write notes on any applicant (General or Visit, backdatable), and
  correct or remove their own
* Take an unassigned applicant, or release one assigned to them

A Lead Manager may not:

* Create an applicant, by either path
* Restore an archived applicant
* Correct or remove another person's note
* Assign an applicant to someone else, or take or clear one assigned to a
  colleague
* Delete an applicant or any part of its history

Superadmin

The Superadmin is a platform authority for managing Admin accounts. It does not
participate in consultancy operations and has no access to applicant records.

## UI screens & wireframe notes

Applicant List

Shows every applicant, newest first. Columns: name, status, contact number,
whether the person came from a lead, assignee, and creation date. Filters for
status, assignee ("mine", "unassigned", or a person), and a
search box matching the name, email, contact number, and passport number,
so staff can type in either script. Primary action "New applicant" is visible to
Admins only. Serves the direct-creation and find-an-applicant flows.

New Applicant Form

Admin only. Sections for identity, contact numbers (repeating rows with a label
and a primary flag), addresses (permanent and current), passport, family members
(repeating), and emergency contacts (repeating). Only name is required; the
whole point is that a file can be started before every detail is known.

Applicant Detail

The person's file. Header shows name, status, the assignee (with Assign / Take /
Release as the viewer's authority allows), and a link to the originating lead
where one exists. Panels for identity, contact, addresses, passport (with the
expiry date visually prominent), family, and emergency contacts. A journeys
panel lists the person's study objectives with a "New journey" action. A history
panel shows the chronological record. Status is changed from a control in the
header, not by editing a field.

Edit Applicant Form

The same layout as the create form, pre-filled. Contact numbers, addresses,
family, and emergency contacts are replaced as a set rather than patched row by
row, so the form always submits the complete intended state.

## Constraints / Out of scope

* Applicants are not system users and cannot sign in.
* No applicant self-service portal.
* No photograph in V1. A photograph needs a documented file contract — permitted
  types, size limits, storage location, and access rules — and files belong to
  the uploaded files module. Adding an image field here would pre-empt that
  module or ship an undocumented upload path.
* No duplicate detection or merging. Two records for the same person is a real
  risk, but resolving it needs a merge process that preserves both histories,
  and that is its own piece of work.
* No documents or files on the applicant record (they have their own modules).
  Education gaps, training records, and non-language tests (SAT, GRE) are not
  recorded.
* No deletion, and no hard archival that hides a record from search.
* No automatic status changes driven by journey activity.

## Notes (added 2026-10-29, frontend updates.md §2)

Staff keep notes on an applicant — general notes, and records of office visits —
each dated to when it happened, which may be earlier than when it was written.
Notes written on a lead arrive here when the lead is converted, so the enquiry →
applicant story reads as one feed. While an applicant is archived their notes can
be read but not changed.

## Open questions

* Should passport renewals keep history? V1 stores one current passport and
  overwrites it on renewal, with the change captured in the audit history. If
  old passport numbers turn out to matter for visa history, this needs to become
  a collection with a current flag.
* Should an address use Nepal's structured hierarchy — province, district,
  municipality, ward — or free text? V1 offers structured optional fields plus a
  free-text line, but the right level of rigidity is not settled.
* Is nationality ever anything but Nepali in practice? If it is effectively
  constant, it may not deserve a field.
* Should archiving an applicant do anything to their open journeys, or are the
  two lifecycles fully independent? V1 keeps them independent.
* Can a Lead Manager really edit any applicant, or should some fields —
  passport, status — be Admin-only? V1 allows full edit access.
* What happens when a directly created applicant is later discovered to have had
  a lead? The "approved correction process" for linking them is not defined.
