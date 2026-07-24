# Data Contract — Document History

**Owner app:** `document_history`
**Version:** 1.0.2
**Status:** Active
**Created:** 2026-07-24
**Purpose:** Owns the immutable print snapshots of a document and the print events that produced them. It does **not** own the editable working record (`documents`), the template catalogue or its signatories (`document_templates`), generated files (`uploaded_files`), or the person (`applicants`). Only `uploaded_files` does not exist.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial contract — two models, `DocumentSnapshot` and `PrintEvent` |
| 1.0.1 | 2026-07-24 | AI (Claude) | Added the `-id` ordering tiebreaker on `PrintEvent` so a paginated timeline cannot skip or duplicate a row |
| 1.0.2 | 2026-07-24 | AI (Claude) | No schema change. `document_templates` shipped, so the signatory table the render context references now exists; corrected the template count to 53 |

---

## The rule that governs this app

**Nothing stored here is ever rewritten or removed.** `concepts/document_history.txt` — "Snapshots are append-only and never edited in place", "No editing of existing snapshots", "No deletion of historical snapshots". `concepts/project_overview.txt` makes it a hard constraint: "Historical document print snapshots must not be silently altered."

This is enforced at the **model layer**, not only in services: `DocumentSnapshot.save()` raises `SnapshotImmutableError` on any save to an already-stored row, and both models' `delete()` raise it unconditionally. The Django admin registration is inspect-only on top of that. There is no update service, no delete service, and no `PUT`, `PATCH`, or `DELETE` method on any route in this app.

A second rule follows from it: **the backend copies the document body, it never accepts one.** `content` is read off the `Document` inside the capture transaction. A client cannot influence what a snapshot claims the document said, because a snapshot that could disagree with its own document would be worthless as history.

---

## Deliberate Deviations

`concepts/document_history.txt` leaves five questions open. Four were settled with the project owner before implementation; the fifth was settled by the project's own state. Each departure from the concept or from `CLAUDE.md` is recorded here.

- **The snapshot stores source data plus render context, not rendered markup.** The concept's first open question asks which. Storing the full rendered HTML would reproduce the visual output exactly, but it is unbounded in size, duplicates data already held twice, and would be an injection liability the moment anything served it back. `render_context` carries what markup cannot be reconstructed from — the frontend-computed values (running balances, closing balance, amount-in-words), the template version, and the signatory metadata — which is what the concept actually requires: "If the document contains frontend-computed values, those values are frozen as part of the snapshot rather than recomputed later."
- **`render_context` is an unvalidated JSON object.** §5 requires a contract for every data object, and this one cannot have a *server-enforced* one, for the reason `documents.content` cannot: the shape differs across 53 templates and the authoritative version lives with the renderer. The two things checked are that it is an object and that it fits under 256 KiB. A serializer that named fields would silently drop the keys a template it has never heard of depends on.
- **Generated file references are deferred entirely.** The concept names "Generated file reference" as a core entity and its second open question asks whether PDFs should be retained. There is **no field for it**, because `uploaded_files` does not exist: any reference stored today would be an opaque string nothing can resolve, verify, or clean up. This is the same call `documents` made when it omitted a `printed` status — "a status no code writes is a lie in the schema". Adding the FK later is additive. The concept already permits this: "No assumption that a generated PDF must exist; the snapshot is the record, the file is optional."
- **The timeline is per-document only.** The concept's third open question asks whether a wider document-family view is needed for Admin review. It is not built (§32). Both list endpoints require a document id in the path; there is no cross-document snapshot or print-event query. Additive later.
- **`document_history` exposes a direct recover endpoint, not a recovery payload.** The concept's fifth open question asks which. A payload-only design makes recovery two client calls that can fail between, and the resulting write is not attributable to a recovery at all. The endpoint calls `documents.services.update_document` in one transaction, so the write goes through the owning app's own rules — and both apps' audit logs record it.
- **`label` is copied as a single field, not a §39.1 bilingual pair, and has no `_romanized` sibling.** It is copied verbatim from `documents.Document.label`, which recorded that deviation with its reasoning: a label is operational shorthand from a template picker, not an entity's legally canonical identity. Adding a language pair here would invent text the source record does not have. **Unicode normalization (§39.2) still applies in full** to `capture_note` and `note`, the two fields a user actually types.
- **No search, and no trigram index.** A version chain is short by nature and is always read whole. §39.6's requirement applies to "new searchable models"; neither of these is one.
- **`PrintEvent.document` is denormalized** from `snapshot.document`. See §2.
- **No history table of its own**, for the same reason as every other app: `audit` provides an immutable append-only log and §4 forbids duplicating it. Note the layering — this app's own tables are already immutable history *of a document*; the `audit` events are history *of this app's actions*.

---

## 1. DocumentSnapshot

**Purpose:** One immutable copy of a document, frozen at print or save-to-history time, plus the render-time context needed to reproduce what the frontend showed at that moment. Answers "what exactly did we issue, when, and who issued it".
**Table:** `document_history_documentsnapshot`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| document | FK → `documents.Document` | Yes | No | No | `PROTECT`, `related_name="snapshots"` |
| version_number | PositiveInteger | Yes | No | Yes | Position in this document's chain, 1-based. Allocated by the service, never supplied |
| family | CharField(20) | Yes | No | Yes | **Copied** from the document at capture |
| template_key | CharField(100) | Yes | No | Yes | **Copied** from the document at capture |
| label | CharField(255) | Yes | No | Yes | **Copied** from the document at capture |
| content | JSONField | No | No | Yes | **Copied** verbatim from `Document.content`. Never accepted from a client; defaults to `{}` |
| render_context | JSONField | No | No | No | Client-supplied, stored verbatim; defaults to `{}` |
| capture_note | Text | No | No | No | Why this snapshot was taken |
| captured_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps. `created_at` **is** the capture time; `updated_at` never moves, because the row is never saved twice |

**Why `family`, `template_key`, and `label` are copied rather than read through the FK.** Renaming a document later must not retitle what was already issued. That is the "later changes to the applicant, document data, or template must not silently rewrite historical print records" principle in `concepts/project_overview.txt`, expressed in the schema rather than trusted to a convention.

**Validation Rules:**

- `render_context` must be a JSON **object** → `DOCUMENT_HISTORY_RENDER_CONTEXT_INVALID`, and must serialize under **262 144 bytes (256 KiB)** → `DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE`. The cap mirrors `documents.MAX_CONTENT_BYTES` and is declared independently in `document_history/constants.py` — a cross-app constant import would be an undocumented runtime coupling (§4), and the two payloads may legitimately diverge later.
- `content` is **not** re-validated. It was already capped by `documents` on the way in, and this app copies rather than accepts it.
- `version_number` is allocated under `SELECT ... FOR UPDATE` on the parent `Document` row, so two simultaneous captures produce versions *n* and *n+1* rather than one `IntegrityError`. The unique constraint below is the backstop, not the mechanism.
- **A snapshot may be captured from an archived document.** A freeze is a read; it changes nothing. Recovery is the operation that respects the archive lock, because that one writes.
- `capture_note` is Unicode-normalized on write (§39.2). **`content` and `render_context` are not walked or normalized** — that would be the backend touching the frozen payload.
- **A stored snapshot cannot be saved again** → `SnapshotImmutableError`. **A snapshot cannot be deleted** → same. Both raised at the model layer.

**Indexes:**

- `(document, -version_number)` — `snapshot_document_version_idx`. Serves the version chain read and the next-version lookup during capture.
- `(document, version_number)` UNIQUE — `document_snapshot_version_unique`. The concurrency backstop described above.

Ordering is `-version_number`: the history timeline reads newest first, and the Snapshot Detail screen's "previous version" link walks the same order.

**Soft Delete:** `N/A — no deletion at all, and no soft-delete flag either.` There is no `is_deleted`, no `archived_at`, and no retirement state, because a snapshot has no lifecycle to be in. It exists, and it says what it said. `document` and `captured_by` are both `PROTECT`, so **a document with print history cannot be deleted**, and neither can the user who captured it.

**Cross-App Dependencies:**

- `documents.Document` — `PROTECT` FK, `related_name="snapshots"`. Read at capture (the body is copied off it) and **written at recovery**, through `documents.services.update_document` — never directly. See §3.
- `authenticate.User` — `PROTECT` FK for `captured_by`.
- `audit` — service call. Every action appends one event. **Neither the body nor the render context ever appears in it** — see §3.
- **Referenced by: nothing.** No other app points here.

**Example:**

```json
{
  "id": "7c1f9b20-3d44-4a8e-9f01-2b3c4d5e6f70",
  "document": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071",
  "version_number": 2,
  "family": "bank_statement",
  "template_key": "bank-vyas-statement",
  "label": "Vyas Statement",
  "content": {
    "statement_account_holder": "Ram Bahadur",
    "statement_account_no": "0123456789012",
    "statement_opening_balance": 250000,
    "transactions": [
      { "date": "2026-04-01", "description": "Deposit", "credit": 500000 }
    ]
  },
  "render_context": {
    "template_version": "2026.03",
    "computed": {
      "statement_debit_total": 0,
      "statement_credit_total": 500000,
      "statement_closing_balance": 750000,
      "amount_in_words": "Seven Hundred Fifty Thousand Only"
    },
    "signatories": [
      { "id": "9f8e7d6c-5b4a-4392-8172-6f5e4d3c2b1a", "role": "director", "name": "Sunita Shrestha" }
    ]
  },
  "capture_note": "Printed for the visa file.",
  "captured_by_username": "adminuser",
  "created_at": "2026-07-24T09:41:02Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
  }
}
```

Note that `content` holds **input fields only**, exactly as `documents` stores them, while every derived value lives under `render_context.computed` where it is unambiguously a frozen presentation value rather than source data. That separation is the point: `concepts/project_overview.txt` — "Derived presentation values are not treated as ordinary editable source data."

---

## 2. PrintEvent

**Purpose:** One act of producing output from a snapshot — the original capture, a later reprint, or a recovery. Answers "how many times was this issued, by whom, and was it an original or a reprint".
**Table:** `document_history_printevent`

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| snapshot | FK → `DocumentSnapshot` | Yes | No | No | `PROTECT`, `related_name="print_events"` |
| document | FK → `documents.Document` | Yes | No | Yes | `PROTECT`, `related_name="print_events"`. **Denormalized** — see below |
| event_type | CharField(20) | Yes | No | Yes | Set by the service, never by the client; indexed |
| note | Text | No | No | No | |
| performed_by | FK → `authenticate.User` | Yes | No | No | `PROTECT` |
| created_at / updated_at | DateTime | — | No | Yes | Base-model timestamps |

**Choice fields:**

- **`event_type`** — `capture` | `reprint` | `recovery`. Defined in `document_history/constants.py` `PrintEventType`. This enum exists because of one sentence in `concepts/document_history.txt`: "The timeline should make reprints and recoveries easy to distinguish from original first captures." Without it the timeline is an undifferentiated list of times and actors, and staff cannot answer "was this the version we issued, or a later reprint of it". **The client cannot set it** — a client that could name its own event type could file a recovery as a reprint.

**Why a print event is a separate model from a snapshot.** `concepts/document_history.txt` names them as two core entities, and the split is load-bearing: a reprint is new *activity* against an existing frozen body, not a new body. One row per print would force every reprint to duplicate a bank statement's entire transaction array, and "which version was actually issued" would stop having an answer.

Which action writes what:

| Action | Snapshot written | Print event written |
|--------|-----------------|---------------------|
| Capture | yes, version *n+1* | one, `capture` |
| Reprint | **no** | one, `reprint` |
| Recovery | **no** | one, `recovery` |

**`document` is deliberately denormalized** from `snapshot.document`. The per-document timeline is this app's primary read, and carrying the document here makes it one index scan on `print_event_doc_recent_idx` instead of a join through the snapshot table. It cannot drift: a snapshot's `document` is immutable, so the two can never disagree, and the service sets this column from `snapshot.document_id` rather than from any request field.

**Validation Rules:**

- `note` is Unicode-normalized on write (§39.2).
- **A print event cannot be deleted** → `SnapshotImmutableError`, raised at the model layer. Unlike `DocumentSnapshot`, `save()` is *not* blocked — there is no update path to it in any service, and blocking it would add a guard nothing can reach.

**Indexes:**

- `(document, -created_at)` — `print_event_doc_recent_idx`. The Document History Timeline. Name shortened from the descriptive form because Django caps index names at 30 characters (`models.E034`).
- `event_type` — `db_index=True`. The `?event_type=` timeline filter.

Ordering is `("-created_at", "-id")` — the timeline reads newest first, with `id` as a tiebreaker.

**The tiebreaker is not cosmetic.** `created_at` is **not unique** on this table: a capture writes its snapshot and its print event in one transaction, and two events can share a timestamp. The timeline is paginated and offers no client-controllable ordering, and a non-unique sort key under page-number pagination lets a row appear on two pages or on none. On an append-only history that reads as an event silently vanishing — the one failure mode this module exists to make impossible. `id` is a UUID, so it breaks ties arbitrarily but *stably*, which is all pagination requires.

`DocumentSnapshot` needs no such tiebreaker: it orders by `-version_number`, which is unique within the one document every chain query is filtered to.

**Soft Delete:** `N/A — no deletion at all.` Same reasoning as `DocumentSnapshot`. `snapshot`, `document`, and `performed_by` are all `PROTECT`.

**Cross-App Dependencies:** as `DocumentSnapshot` above, plus the `PROTECT` FK to `documents.Document`.

---

## 3. Cross-App Dependencies — the recovery write

This is the only place in the module where data leaves it, and the only cross-app **write** in the project outside lead conversion. It is recorded here and in `docs/INTEGRATION.md` §2 (§4 requires both), and mirrored in `documents/docs/DATA_CONTRACT.md`.

`document_history.services.recover_snapshot()` calls `documents.services.update_document()` with the snapshot's frozen `label` and `content`. It does **not** write to `Document` directly, which means the working record's own rules still apply in full and are not reimplemented here:

- the archive lock — recovering into an archived document raises `DocumentNotEditableError`, surfaced as 409 `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE`;
- the 256 KiB content cap;
- the redacted `document_updated` audit event, with the body replaced by `<changed>`.

**What is deliberately *not* recovered:** `notes`, `status`, `applicant`, `family`, and `template_key`. The last three are immutable in `documents` and identical here by construction. `status` is excluded because recovering a body is not a judgement that the result is ready. `notes` is excluded because it is the working annotation staff keep *about* a document rather than part of what was issued — the snapshot does not freeze it, so a recovery cannot clobber a note written after the print.

**Two audit events result from one recovery,** one per app: `documents.document_updated` (body redacted) and `document_history.snapshot_recovered`. That is correct, not duplication — they answer different questions, and the `documents` one appears in that document's own history panel where a reader would look for it.

**A no-op recovery** — the body already matches — writes no `document_updated` event, because `update_document` suppresses unchanged saves. It still writes `snapshot_recovered` and its print event: the action happened, and a timeline that hid it would misrepresent what staff did.

**Audit redaction — a contract detail, not an implementation note.** Every action appends one `audit.AuditEvent` whose `metadata` carries `document_id`, `version_number`, `template_key`, and `event_type` — identity and position only. **Neither `content` nor `render_context` is ever passed**, and there is no `changes` map. Both fields hold personal financial data, `render_context` additionally holds the computed closing balances, and the audit log is readable by every Admin and Superadmin through the `audit` app (§17). Covered by `tests/test_services.py::FrozenPayloadNeverReachesTheAuditLogTests`.
