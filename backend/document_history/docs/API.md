# API — Document History

**Owner app:** `document_history`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24
**Base prefix:** `/api/v1/document-history/`
**Auth:** Bearer access JWT (`authenticate.SessionBoundJWTAuthentication`) on every endpoint
**Throttle:** project defaults only — `UserRateThrottle` at 1000/hour. No endpoint here is public. Two costs are worth noting: the snapshot detail read returns up to 512 KiB (a frozen body plus its render context), and a capture *writes* that much per call. The list and timeline endpoints deliberately omit both JSON columns, so a page of twenty rows stays small.
**Access level:** protected. **Admin only, on every route including reads.** Lead Manager and Superadmin both denied.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial API documentation — 6 endpoints across two resources |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint change. Documented the `PrintEvent` ordering tiebreaker and the Bikram Sambat `fiscal_year` footgun |

---

## Access model (§9 interim inline pattern)

This app uses the interim inline access check in `document_history/access.py`. There is no `permissions.py`.

| Check | Applies to | Allows | Denies |
|-------|-----------|--------|--------|
| `require_document_history_actor` | **every endpoint**, read and write alike | `admin` | `lead_manager`, `superadmin` → 403 `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` |

One helper rather than the reader/writer pair other apps declare, because there is no split to express. Applied by the `HistoryActorView` base class that every view inherits, so a new endpoint cannot be added without it.

**Identical to `documents`, deliberately.** A snapshot holds the same bank statement, account number, and transaction history the working document does; freezing a body does not make it less sensitive, so the app storing the frozen copies cannot be more open than the app storing the original. The reasoning is argued once, in `documents/docs/SECURITY.md` §1, and applies to both apps — which is why this app publishes no `SECURITY.md` of its own. **No endpoint in this app is public.**

**No `PUT`, `PATCH`, or `DELETE` method is exposed on any resource.** Snapshots and print events are append-only at the model layer, not merely by convention — see `DATA_CONTRACT.md` "The rule that governs this app".

---

## Error codes

All codes live in `document_history/constants.py` `ErrorCode`.

| Code | HTTP | Meaning |
|------|------|---------|
| `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` | 403 | The caller is not an Admin |
| `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND` | 404 | No document with the id in the URL path |
| `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` | 404 | No snapshot with the id in the URL path |
| `DOCUMENT_HISTORY_RENDER_CONTEXT_INVALID` | 400 | `render_context` is not a JSON object |
| `DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE` | 400 | `render_context` exceeds `MAX_RENDER_CONTEXT_BYTES` (256 KiB) |
| `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE` | 409 | Recovery targeted a document that is archived |
| `DOCUMENT_HISTORY_CONTENT_TOO_LARGE` | 400 | Recovery's frozen body no longer fits the working record's cap |

Serializer-level failures return the project-wide `VALIDATION_ERROR` (400) with the offending fields in `error.details`.

**Two of these are re-coded from `documents`.** `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE` and `DOCUMENT_HISTORY_CONTENT_TOO_LARGE` arise inside `documents.services.update_document` during a recovery, where they would otherwise surface as `DOCUMENTS_*`. They are translated at this app's view boundary, because a consumer calling a `/document-history/` route should never receive a code naming a route it did not call.

`SnapshotImmutableError` has an error code (`DOCUMENT_HISTORY_SNAPSHOT_IMMUTABLE`) but **no reachable HTTP path** — there is no update or delete endpoint to raise it from. It guards the model layer against a future service, a management command, or the Django admin. The code is registered so that if such a path is ever added, the envelope is already defined.

---

## 1. Snapshots

The frozen record. A snapshot belongs to exactly one document and is identified by its position in that document's version chain.

### 1.1 List a document's version chain

- **URI:** `GET /api/v1/document-history/documents/<document_id>/snapshots/`
- **Permission key:** `document_history.snapshot.list`
- **Auth:** required. Admin only.
- **Query parameters:** `fiscal_year` (`YYYY/YY`, Nepali fiscal year — §39.4), `page`, `page_size`.
- **Response:** paginated list of `DocumentSnapshot`, **omitting `content` and `render_context`** — see `DATA_CONTRACT.md` §1. Newest version first.
- **Business rules:** an unknown `document_id` is a **404**, not an empty list. An empty list asserts "this document has never been printed", which would be a different and possibly false statement.
- **Query access pattern:** `selectors.get_snapshots_for_document` — one query, `select_related("captured_by")`, `defer("content", "render_context")`, served by `snapshot_document_version_idx`. The two JSON columns are deferred rather than left in place (the opposite of `documents.get_documents`) because the list serializer has no field that could reach either one, so the second-query risk that stopped `documents` deferring does not exist here.
- **Errors:** `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403), `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND` (404), `VALIDATION_ERROR` (400) on a malformed `fiscal_year`.
- **AI debugging notes:** if a chain looks short, check `?fiscal_year=` first — it filters on the *capture* date, not the document's creation date.

### 1.2 Capture a snapshot

- **URI:** `POST /api/v1/document-history/documents/<document_id>/snapshots/`
- **Permission key:** `document_history.snapshot.capture`
- **Auth:** required. Admin only.
- **Request:**

```json
{
  "render_context": {
    "template_version": "2026.03",
    "computed": { "statement_closing_balance": 750000, "amount_in_words": "Seven Hundred Fifty Thousand Only" },
    "signatories": [{ "id": "9f8e7d6c-5b4a-4392-8172-6f5e4d3c2b1a", "role": "director", "name": "Sunita Shrestha" }]
  },
  "capture_note": "Printed for the visa file."
}
```

  Both fields are optional. **There is no `content` field, no `label`, and no `version_number`** — all three come from the document or are allocated by the service. A client that posts `content` has it **silently ignored**, which is intended: accepting a body would let a snapshot disagree with the record it claims to freeze.
- **Response:** `201` with the full `DocumentSnapshot`, including `content` and `render_context`.
- **Validation rules:** `render_context` must be a JSON object under 256 KiB; `capture_note` max 2000 characters and Unicode-normalized (§39.2).
- **Business rules:**
  - `version_number` is allocated as `max(existing) + 1` under `SELECT ... FOR UPDATE` on the parent `Document` row, so concurrent captures produce *n* and *n+1* rather than an `IntegrityError`.
  - `family`, `template_key`, `label`, and `content` are **copied** from the document at this moment and never re-read afterwards.
  - Writes **two rows in one transaction**: the snapshot and its `capture` print event.
  - **An archived document may be captured.** A freeze is a read and changes nothing.
- **Errors:** `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403), `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND` (404), `DOCUMENT_HISTORY_RENDER_CONTEXT_INVALID` (400), `DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE` (400).
- **AI debugging notes:** if a captured body is not what the user saw on screen, the cause is almost always that the client rendered from unsaved local state — capture reads the *committed* document row under a lock. Save the workspace before capturing.

### 1.3 Retrieve one snapshot

- **URI:** `GET /api/v1/document-history/snapshots/<snapshot_id>/`
- **Permission key:** `document_history.snapshot.read`
- **Auth:** required. Admin only.
- **Response:** the full `DocumentSnapshot` — `DATA_CONTRACT.md` §1. **The only endpoint that returns a frozen body.**
- **Business rules:** read-only, always. There is no path by which this record can change between two reads.
- **Errors:** `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403), `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404).
- **AI debugging notes:** the "Compare Snapshots" screen is **two calls to this endpoint**, diffed client-side. There is no compare endpoint (§32) — see `INTEGRATION.md` §9.

### 1.4 Recover a snapshot into the working document

- **URI:** `POST /api/v1/document-history/snapshots/<snapshot_id>/recover/`
- **Permission key:** `document_history.snapshot.recover`
- **Auth:** required. Admin only.
- **Request:** `{ "note": "Reverting to the version issued in Shrawan." }` — optional, max 2000 characters, Unicode-normalized.
- **Response:** `200` with the **updated `Document`** (`documents/docs/DATA_CONTRACT.md` §1), not the snapshot, so the client can drop it straight back into the workspace without a second request.
- **Business rules:**
  - Restores `label` and `content` only. `notes`, `status`, `applicant`, `family`, and `template_key` are **not** recovered — see `DATA_CONTRACT.md` §3 for why each is excluded.
  - **The snapshot is not altered**, and no new snapshot is created. The next capture does that, and it will carry the recovered body as a new version.
  - The write goes through `documents.services.update_document`, so that app's archive lock, size cap, and redacted audit event all apply.
  - Writes a `recovery` print event, plus one audit event in each app.
  - **A no-op recovery** — the body already matches — writes no `document_updated` event but still writes the print event and `snapshot_recovered`.
- **Errors:** `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403), `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404), `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE` (409), `DOCUMENT_HISTORY_CONTENT_TOO_LARGE` (400).
- **AI debugging notes:** a 409 here means the *document* is archived, not the snapshot — snapshots have no lifecycle. Restore the document (`POST /api/v1/documents/<id>/restore/`) and retry.

---

## 2. Print events

The activity record. Every capture, reprint, and recovery appends one.

### 2.1 List a document's print timeline

- **URI:** `GET /api/v1/document-history/documents/<document_id>/timeline/`
- **Permission key:** `document_history.print_event.list`
- **Auth:** required. Admin only.
- **Query parameters:** `event_type` (`capture` | `reprint` | `recovery`), `fiscal_year` (`YYYY/YY`), `page`, `page_size`.
- **Response:** paginated list of `PrintEvent` — `DATA_CONTRACT.md` §2. Newest first. Each row carries the referenced snapshot's `version_number` and `label` inline, so a timeline renders without one extra request per row.
- **Business rules:** an unknown `document_id` is a 404, for the same reason as §1.1.
- **Query access pattern:** `selectors.get_print_events_for_document` — one query, `select_related("snapshot", "performed_by")`, filtered on the denormalized `document` column and served by `print_event_doc_recent_idx`. The `select_related("snapshot")` is what keeps the inline `version_number`/`label` fields from being an N+1.
- **Errors:** `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403), `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND` (404), `VALIDATION_ERROR` (400) on an unrecognised `event_type` or a malformed `fiscal_year`.

### 2.2 Reprint a snapshot

- **URI:** `POST /api/v1/document-history/snapshots/<snapshot_id>/reprint/`
- **Permission key:** `document_history.print_event.reprint`
- **Auth:** required. Admin only.
- **Request:** `{ "note": "Second copy for the bank." }` — optional, max 2000 characters, Unicode-normalized.
- **Response:** `201` with the new `PrintEvent`.
- **Business rules:**
  - Writes **an event and no new snapshot** — "A reprint is new activity, not a new body rewrite" (`concepts/document_history.txt` flow 4). The frontend regenerates output from the snapshot's own saved `render_context`, so nothing needs duplicating.
  - `event_type` is set to `reprint` by the service. The client cannot name it.
  - Nothing about the working document changes.
- **Errors:** `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403), `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404).
- **AI debugging notes:** if a version chain is not growing but the timeline is, that is reprints working correctly — not a capture bug.
