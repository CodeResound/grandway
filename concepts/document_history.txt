# DOCUMENT HISTORY — Grandway

## Purpose

The Document History module owns Grandway's immutable document snapshots.

It records what a document looked like at a specific moment in time, who
captured that state, and why. The `documents` app is the editable working
record; `document_history` is the frozen record of what was printed, saved to
history, or later reprinted. This is the layer that makes a document's previous
state recoverable without turning the working record into a version-control
system.

The module exists because document work in Grandway is not just "edit and save".
Staff need to know what was shown at print time, what was issued, and which
version of a document a client or institution actually received.

## Relationship to other records

A print snapshot is not the same thing as a document.

The `documents` app owns the current editable body: identity, ownership,
template association, status, and source data. `document_history` owns the
immutable copies of that body plus the render-time context needed to reproduce
what the frontend showed at that moment. It must never rewrite the working
document, and the working document must never silently rewrite history.

`document_templates` supplies the template family, template version, and any
signatory metadata used by the frontend when the snapshot was produced.
`uploaded_files` may eventually hold generated PDFs or exported files and can be
referenced from history when that is implemented. The snapshot itself remains
the authoritative historical record even if no file is retained.

## Core entities

Print snapshot

The immutable copy of a document at print or save-to-history time. It should
capture the document id, family, template key, label, source data, frontend
render context, and any metadata needed to understand exactly what was issued.
Snapshots are append-only and never edited in place.

Print event

The action that produced a snapshot. This records who triggered the print or
history save, when it happened, and what kind of capture it was. A document may
have many print events over time.

Version chain

The ordered series of snapshots for one document. Each new print or saved
history entry creates a new point in the chain; older entries remain visible and
unchanged.

Generated file reference

An optional pointer to a generated PDF or other exported artifact if the system
decides to retain one. The file itself, if stored, lives elsewhere; history only
keeps the reference and the fact that it existed.

Recovery payload

The data returned when staff choose to recover a previous snapshot into the
working document. This is not a rewrite of the historical record. It is a
source of truth for the documents app to create a new working state from.

## Key user flows

1. Capture a snapshot: An Admin opens a document in the frontend -> reviews the
   rendered document -> prints or saves it to history -> `document_history`
   stores an immutable snapshot of the current state, including the render-time
   context.
   - If the document contains frontend-computed values, those values are frozen
     as part of the snapshot rather than recomputed later.
   - If a generated file is produced, the snapshot may keep a reference to it.

2. Review history: An Admin opens a document's history timeline -> sees every
   snapshot and print event in order -> opens one snapshot to inspect what was
   issued at that time.
   - The timeline should make reprints and recoveries easy to distinguish from
     original first captures.

3. Recover a prior version: An Admin selects an older snapshot -> asks the
   system to recover it -> `document_history` returns the frozen payload needed
   to restore the document workspace in `documents`.
   - The historical snapshot is not altered by recovery.
   - The recovery should create a new working state in `documents`, not mutate
     the old snapshot.

4. Reprint the same issue: An Admin reuses a past snapshot -> the system records
   a new print event linked to the same historical document lineage -> the
   frontend can regenerate the output from the saved snapshot context.
   - A reprint is new activity, not a new body rewrite.

## UI screens & wireframe notes

Document History Timeline

The main history view, usually opened from the documents workspace. Shows the
chronological list of snapshots and print events for one document, newest or
oldest first depending on the review mode. Each row should show time, actor,
event type, and a short label or version marker.

Snapshot Detail

Shows one frozen snapshot in full: document identity, template context, rendered
metadata, source data, and any generated-file reference. This is read-only.

Compare Snapshots

A side-by-side view of two historical versions of the same document. Useful for
understanding what changed between prints or revisions.

Recover Snapshot Dialog

A focused confirmation step that returns a prior snapshot to the documents
workspace as the starting point for a new working version.

## Constraints / Out of scope

* No editing of existing snapshots.
* No deletion of historical snapshots.
* No replacement of the live document workspace.
* No template authoring or rendering engine.
* No recomputation of display-only values from current data once the snapshot is
  stored.
* No Lead Manager access if the project keeps document data restricted to Admins
  only, which is the current direction of the documents app.
* No assumption that a generated PDF must exist; the snapshot is the record,
  the file is optional.

## Open questions

Four of the five below were settled with the project owner before the module was
built on 2026-07-24. The resolutions are recorded inline; the reasoning for each
is in backend/document_history/docs/DATA_CONTRACT.md under "Deliberate
Deviations". The concept text above is left as originally written.

* Should the stored snapshot include the full rendered HTML/markup, or only the
  source data plus enough render metadata to reproduce it?
  -> RESOLVED: source data plus render context. The backend copies the document
     body verbatim; the frontend supplies a render_context holding the values it
     computed, the template version, and the signatory metadata. No markup is
     stored: it is unbounded, duplicates data held twice already, and would be
     an injection liability if anything ever served it back.

* Should generated PDFs be retained by default, or only when a user explicitly
  chooses to keep one?
  -> RESOLVED (deferred): neither, for now. There is no file field at all,
     because uploaded_files does not exist and any reference stored today would
     be an opaque string nothing can resolve. Adding it later is additive. The
     "Generated file reference" entity above is therefore not built.

* Should the history timeline be per-document only, or also support a wider
  document-family view for Admin review?
  -> RESOLVED: per-document only. Both list endpoints require a document id.
     A wider view is additive and was not built (CLAUDE.md §32).

* What exact fields must be frozen in the snapshot for each document family so
  recovery is reliable?
  -> STILL OPEN, and deliberately so. The backend freezes the whole body
     verbatim rather than a per-family field list, for the same reason the
     documents app does not validate content: 42 template shapes, all open. The
     unresolved half is that **nothing enforces the split** between input fields
     (content) and computed values (render_context) — a client that puts a
     closing balance in the body will have it frozen there silently. That
     convention is load-bearing for recovery and invisible to the backend.

* Should the history app expose a direct restore endpoint, or only a recovery
  payload for the documents app to consume?
  -> RESOLVED: a direct recover endpoint. A payload-only design makes recovery
     two client calls that can fail between, and the resulting write would not
     be attributable to a recovery at all. The endpoint writes through the
     documents app's own update service, so that app's archive lock, size cap,
     and redacted audit event still apply.

## Correction notes

* **Access is Admin only, reads included.** The Constraints section above says
  "No Lead Manager access if the project keeps document data restricted to
  Admins only, which is the current direction of the documents app." It does,
  so that is what was built. A Lead Manager receives 403 on every route here.
