# FLOWS — Document History

**Owner app:** `document_history`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/document_history.txt` to the callable endpoints in
`backend/document_history/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **Five things govern every flow below.**
>
> 1. **Admin only — a Lead Manager cannot open any of these screens.** Not read-only, not empty:
>    **hidden**. The same rule as `documents`, for the same reason: a snapshot holds the same bank
>    statement the working document does.
> 2. **You never send a document body.** The capture request has no `content` field. The backend
>    reads the committed document row itself. **Save the workspace before printing** — an unsaved
>    edit is not what gets frozen.
> 3. **Send the computed values in `render_context`, not in `content`.** The running balances,
>    totals, closing balance, and amount-in-words that `documents` forbids you from persisting are
>    exactly what you *must* freeze here. This is the one place in Grandway where a derived value is
>    stored on purpose.
> 4. **Nothing here can be edited or deleted.** There is no `PUT`, `PATCH`, or `DELETE` on any route.
>    A mistaken snapshot is corrected by capturing a new one, never by fixing the old one.
> 5. **A reprint does not grow the version chain.** If the timeline grows while the chain stays
>    still, that is correct behaviour — do not treat it as a bug.

---

## Flow: Capture a print snapshot

- **Actor:** Admin
- **Goal:** Freeze what the document looks like right now, so it stays recoverable after later edits.
- **Entry point:** Document Workspace (from `concepts/documents.txt`) → Print

**Steps:**

1. **Document Workspace** — load the body →
   `GET /api/v1/documents/<document_id>/` (`documents.document.read`) **(cross-app: `documents`)**
   - **Requires state:** the document.
   - **Side effects:** none.

2. **Document Workspace** — save any pending edits →
   `PATCH /api/v1/documents/<document_id>/` (`documents.document.update`) **(cross-app: `documents`)**
   - **Requires state:** the document must not be archived.
   - **Side effects:** appends `document_updated` in `documents`.
   - **This step is not optional in practice.** Capture reads the *committed* row under a lock. A
     workspace with unsaved changes will freeze the old body and the user will not be told.

3. **Print Preview** — render locally, computing every derived value.
   - No endpoint. The frontend is the rendering engine; the backend has never computed a balance.

4. **Print Preview** — print or save to history →
   `POST /api/v1/document-history/documents/<document_id>/snapshots/`
   (`document_history.snapshot.capture`)
   - **Requires state:** the document. **No status precondition** — an archived document may be
     captured, because a freeze changes nothing.
   - **Side effects:** creates the snapshot **and** its `capture` print event in one transaction;
     appends `snapshot_captured` to the audit log. **Nothing in `documents` changes** — not the
     status, not `updated_at`.
   - **Put the computed values under `render_context`.** Everything the renderer calculated, plus the
     template version and the resolved signatories.
   - **Do not compute `version_number` client-side.** The server allocates it under a row lock;
     two people printing at once get *n* and *n+1*.
   - *Failure — `DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE`:* the context exceeds 256 KiB. Realistically
     only a very long bank statement. Trim per-row derived values rather than failing the print.
   - *Failure — `DOCUMENT_HISTORY_RENDER_CONTEXT_INVALID`:* an array or scalar was sent. A client bug.
   - *Failure — `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND`:* the document id is wrong.

5. **Document Workspace** — the print button does **not** need to disable afterwards. Printing twice
   is legitimate and produces two versions.

---

## Flow: Review a document's history

- **Actor:** Admin
- **Goal:** See everything that was ever issued from this document, and inspect one issue in full.
- **Entry point:** Document History Timeline

**Steps:**

1. **Document History Timeline** — load the chronological list →
   `GET /api/v1/document-history/documents/<document_id>/timeline/`
   (`document_history.print_event.list`)
   - **Requires state:** the document.
   - **Side effects:** none.
   - **Show `event_type` on every row.** Distinguishing an original capture from a reprint or a
     recovery is the screen's stated purpose in `concepts/document_history.txt`.
   - Rows carry `version_number` and `label` inline — no per-row fetch is needed to render them.
   - A document that has never been printed returns an **empty list**, not a 404. Render an empty
     state, not an error.
   - *Failure — `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND`:* the document itself does not exist. This is a
     genuine 404, distinct from the empty list above.

2. **Document History Timeline** — filter to originals only →
   `GET /api/v1/document-history/documents/<document_id>/timeline/?event_type=capture`
   - *Failure — `VALIDATION_ERROR` on `event_type`:* only `capture`, `reprint`, and `recovery` exist.
     An unrecognised value is **rejected, not ignored** — do not send a free-text filter.

3. **Document History Timeline** — the version list beside the timeline →
   `GET /api/v1/document-history/documents/<document_id>/snapshots/`
   (`document_history.snapshot.list`)
   - **Requires state:** the document.
   - **Side effects:** none.
   - Rows omit `content` and `render_context`. Do not try to render a preview from a list row.

4. **Snapshot Detail** — open one frozen record →
   `GET /api/v1/document-history/snapshots/<snapshot_id>/` (`document_history.snapshot.read`)
   - **Requires state:** the snapshot.
   - **Side effects:** none.
   - **Render the snapshot's own `label` and `render_context.computed`, never the document's current
     values.** Reaching back to the live document here would defeat the entire module.
   - This screen is **read-only, permanently**. There is no edit affordance to hide behind a
     permission — there is no endpoint at all.

---

## Flow: Compare two versions

- **Actor:** Admin
- **Goal:** Understand what changed between two issues of the same document.
- **Entry point:** Compare Snapshots

**Steps:**

1. **Document History Timeline** — pick two versions →
   `GET /api/v1/document-history/documents/<document_id>/snapshots/`
   (`document_history.snapshot.list`)
   - **Requires state:** the document.
   - **Side effects:** none.

2. **Compare Snapshots** — fetch both, **as two separate calls** →
   `GET /api/v1/document-history/snapshots/<id_a>/` and
   `GET /api/v1/document-history/snapshots/<id_b>/` (`document_history.snapshot.read`)
   - **Requires state:** both snapshots.
   - **Side effects:** none.
   - **There is no compare endpoint.** The backend computes, returns, and stores no diff. Diff
     `content` and `render_context.computed` client-side.
   - Two snapshots of the same document may legitimately carry different `label` values — a rename
     between prints is exactly the kind of change this screen exists to surface.

---

## Flow: Recover a prior version into the workspace

- **Actor:** Admin
- **Goal:** Put an older body back into the working document without losing the historical record.
- **Entry point:** Snapshot Detail → Recover

**Steps:**

1. **Snapshot Detail** — show the user what they are about to restore →
   `GET /api/v1/document-history/snapshots/<snapshot_id>/` (`document_history.snapshot.read`)
   - **Requires state:** the snapshot.
   - **Side effects:** none.

2. **Recover Snapshot Dialog** — confirm →
   `POST /api/v1/document-history/snapshots/<snapshot_id>/recover/`
   (`document_history.snapshot.recover`)
   - **Requires state:** the snapshot, and the target document **must not be archived**. This is the
     only endpoint in the module with a state precondition.
   - **Side effects:** writes `label` and `content` into the working document **(cross-app write into
     `documents`)**; creates a `recovery` print event; appends **two** audit events, one in each app.
     **The snapshot is not altered and no new snapshot is created.**
   - **The response is the updated `Document`, not the snapshot.** Re-render the workspace from it
     directly — no follow-up fetch.
   - **Warn the user what is *not* restored:** `notes` and `status` stay as they are. A note written
     after the print survives; a document marked `ready` stays `ready`.
   - *Failure — `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE` (409):* **the document is archived, not the
     snapshot.** Snapshots have no lifecycle. Offer the restore action below and retry.
   - **A no-op recovery is not an error.** If the body already matches, nothing changes in `documents`
     and `updated_at` does not move — but the recovery *is* recorded. Do not report failure.

3. **Document Workspace** — if step 2 returned 409, restore the document first →
   `POST /api/v1/documents/<document_id>/restore/` (`documents.document.restore`)
   **(cross-app: `documents`)**
   - **Requires state:** the document must be archived.
   - **Side effects:** returns it to `draft` and clears the archive fields.
   - Then retry step 2.

4. **Document Workspace** — capture again to freeze the recovered state →
   `POST /api/v1/document-history/documents/<document_id>/snapshots/`
   (`document_history.snapshot.capture`)
   - Optional, but this is how the recovered body enters the chain as version *n+1*. A recovery on
     its own leaves the chain untouched.

---

## Flow: Reprint an earlier issue

- **Actor:** Admin
- **Goal:** Produce another copy of something already issued, and record that it happened.
- **Entry point:** Snapshot Detail → Reprint

**Steps:**

1. **Snapshot Detail** — load the frozen record →
   `GET /api/v1/document-history/snapshots/<snapshot_id>/` (`document_history.snapshot.read`)
   - **Requires state:** the snapshot.
   - **Side effects:** none.

2. **Print Preview** — render from **the snapshot's own** `content` and `render_context`.
   - Never re-render from the live document. The point of a reprint is to reproduce what was issued.

3. **Snapshot Detail** — record the reprint →
   `POST /api/v1/document-history/snapshots/<snapshot_id>/reprint/`
   (`document_history.print_event.reprint`)
   - **Requires state:** the snapshot. **No status precondition** — a snapshot of an archived
     document may be reprinted, because reprinting writes nothing to the document.
   - **Side effects:** creates one `reprint` print event; appends `snapshot_reprinted`. **No new
     snapshot**, and nothing in `documents` changes.
   - *Failure — `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND`:* the snapshot id is wrong.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `document_history.snapshot.capture` | `POST /api/v1/document-history/documents/<document_id>/snapshots/` | Capture a print snapshot; Recover (step 4) | Send `render_context`, never `content` |
| `document_history.snapshot.list` | `GET /api/v1/document-history/documents/<document_id>/snapshots/` | Review history; Compare | Omits both JSON columns. `?fiscal_year=` |
| `document_history.snapshot.read` | `GET /api/v1/document-history/snapshots/<snapshot_id>/` | Review history; Compare; Recover; Reprint | **The only endpoint returning a frozen body** |
| `document_history.print_event.list` | `GET /api/v1/document-history/documents/<document_id>/timeline/` | Review history | `?event_type=`, `?fiscal_year=` |
| `document_history.print_event.reprint` | `POST /api/v1/document-history/snapshots/<snapshot_id>/reprint/` | Reprint | Writes an event, never a snapshot |
| `document_history.snapshot.recover` | `POST /api/v1/document-history/snapshots/<snapshot_id>/recover/` | Recover | **Writes into `documents`.** Returns a `Document` |

**Screens from `concepts/document_history.txt`, and whether they are backed:**

- **Document History Timeline** — backed by `print_event.list` for the event rows and
  `snapshot.list` for the version list. Both are per-document.
- **Snapshot Detail** — backed by `snapshot.read`. Read-only, with no edit endpoint to hide.
- **Compare Snapshots** — backed by **two** `snapshot.read` calls. No compare endpoint exists.
- **Recover Snapshot Dialog** — backed by `snapshot.recover`, which performs the restore rather than
  returning a payload for the client to apply.

**Not backed, and deliberately so:**

- **Any generated-file link.** A snapshot has no file field. `uploaded_files` does not exist, so a
  generated PDF cannot be stored, referenced, or retrieved through any endpoint in this project.
  **Do not ship a "download the saved PDF" control** — there is nothing behind it.
- **Any cross-document view** — "everything printed this month", "all snapshots of family
  `bank_statement`". Both list endpoints require a document id.
- **A signatory picker** is not this app's to provide, but one now exists —
  `GET /api/v1/document-templates/signatories/?status=active`
  (`document_templates.signatory.list`) **(cross-app: `document_templates`)**. The ids you freeze
  into `render_context.signatories` resolve against it, and a retired signatory stays retrievable
  forever precisely so old snapshots keep working.
  - **Keep freezing the name and role alongside the id.** This app validates nothing inside
    `render_context`, and an id alone would leave a snapshot dependent on a lookup that may return a
    since-renamed record — which is exactly what freezing exists to prevent.

## Cross-app dependencies

- **This app references (outbound):** `documents.document.read` and `documents.document.update`
  (the workspace load and save preceding a capture), and `documents.document.restore` (the recovery
  409 recovery path). The backend additionally holds `PROTECT` FKs to `documents.Document` and
  performs the recovery write through that app's own update service — see
  `backend/document_history/docs/INTEGRATION.md` §2.
- **Referenced by other apps (inbound):** `concepts/documents_flows.md` — its "Review and print"
  flow delegates here rather than restating these steps.

**Note the asymmetry with `documents`.** That app depends on this one for nothing and works with no
snapshot in the system. This one is useless without it: every route is document- or snapshot-scoped,
and there is no route you can call before a document exists.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.

## Open questions

- **Should the timeline gain a document-family or date-range view for Admin review?**
  `concepts/document_history.txt` asks this; it is deferred, and both list endpoints are per-document
  today. The `audit` module's event list (`?app=document_history`) is the nearest substitute and
  returns audit events, not snapshots.
- **Should generated PDFs be retained?** Deferred until `uploaded_files` exists. Nothing in the
  schema anticipates it beyond the fact that adding an FK later is additive.
- **Nothing enforces the `content` / `render_context` split.** A client that puts a computed closing
  balance inside the document body will have it frozen there, and no endpoint will flag it. The
  convention is load-bearing for the frontend and invisible to the backend.
- **`render_context` has no schema and no version gate.** If the client's shape changes, older
  snapshots keep the old one and nothing migrates or warns. `template_version` is the conventional
  place to record which shape a snapshot uses; the backend does not read it.
