# API — Documents

**Owner app:** `documents`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24
**Base prefix:** `/api/v1/documents/`
**Auth:** Bearer access JWT (`authenticate.SessionBoundJWTAuthentication`) on every endpoint
**Throttle:** project defaults only — `UserRateThrottle` at 1000/hour. No endpoint here is public. The one cost worth noting is that the detail read returns a body of up to 256 KiB; the list endpoint deliberately omits it, so a page of twenty rows stays small.
**Access level:** protected. **Admin only, on every route including reads.** Lead Manager and Superadmin both denied.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial API documentation — 9 endpoints across one resource |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint change. Corrected the history endpoint's note now that `document_history` exists |

---

## Access model (§9 interim inline pattern)

This app uses the interim inline access check in `documents/access.py`. There is no `permissions.py`.

| Check | Applies to | Allows | Denies |
|-------|-----------|--------|--------|
| `require_document_actor` | **every endpoint**, read and write alike | `admin` | `lead_manager`, `superadmin` → 403 `DOCUMENTS_ACTOR_FORBIDDEN` |

One helper rather than the reader/writer pair other apps declare, because there is no split to express — the read population and the write population are the same set of one. Applied by the `DocumentActorView` base class that every view inherits, so a new endpoint cannot be added without it.

**This is the strictest access model in the project and the first that refuses a Lead Manager a read.** The reasoning, and the deliberate override of `concepts/documents.txt` flow 1 that it represents, is in `docs/SECURITY.md` §1. **No endpoint in this app is public.**

**No `DELETE` method is exposed on any resource.** Withdrawal from use is `POST .../archive/` with a mandatory reason — see `DATA_CONTRACT.md` "Soft Delete".

---

## Error codes

All codes live in `documents/constants.py` `ErrorCode`.

| Code | HTTP | Meaning |
|------|------|---------|
| `DOCUMENTS_ACTOR_FORBIDDEN` | 403 | The caller is not an Admin |
| `DOCUMENTS_DOCUMENT_NOT_FOUND` | 404 | No document with the id in the URL path |
| `DOCUMENTS_APPLICANT_NOT_FOUND` | 400 | The `applicant` in the create body does not resolve |
| `DOCUMENTS_OWNER_REQUIRED` | 400 | Neither an applicant nor a standalone purpose was given |
| `DOCUMENTS_TEMPLATE_KEY_INVALID` | 400 | The template slug does not agree with the family |
| `DOCUMENTS_CONTENT_INVALID` | 400 | The body is not a JSON object |
| `DOCUMENTS_CONTENT_TOO_LARGE` | 400 | The body exceeds `MAX_CONTENT_BYTES` (256 KiB) |
| `DOCUMENTS_OWNERSHIP_IMMUTABLE` | 400 | A `PATCH` carried `applicant`, `family`, or `template_key` |
| `DOCUMENTS_STATUS_IMMUTABLE` | 400 | A `PATCH` carried `status` or an archive field |
| `DOCUMENTS_DOCUMENT_NOT_EDITABLE` | 409 | The document is archived |
| `DOCUMENTS_STATUS_INVALID_TRANSITION` | 400 | The status action targeted a status it may not set |
| `DOCUMENTS_ARCHIVE_REASON_REQUIRED` | 400 | Archive was called with a missing or blank reason |
| `DOCUMENTS_DOCUMENT_ALREADY_ARCHIVED` | 409 | Archive was called on an archived document |
| `DOCUMENTS_DOCUMENT_NOT_ARCHIVED` | 409 | Restore was called on an active document |

Serializer-level failures return the project-wide `VALIDATION_ERROR` (400) with the offending fields in `error.details`.

---

## Module-wide rules

These hold on every endpoint below and are not repeated per endpoint.

1. **`content` is stored verbatim and returned verbatim.** Nothing in this app computes, injects, normalizes, reorders, or strips anything inside the document body. Running balances, debit/credit totals, closing balances, the auto interest and tax rows, and amount-in-words are frontend concerns. Unknown keys are preserved because a template the backend has never heard of may depend on them.
2. **The document body never reaches the audit log.** Every mutation appends one `audit.AuditEvent`, and `content` is replaced in the `changes` map by the literal marker `<changed>` (`constants.CONTENT_CHANGE_MARKER`). Implemented in `services._diff_for_audit`, which is written out in full rather than copied from the other apps' `_diff` so the redaction is visible where it happens. §17; see `SECURITY.md` §2.
3. **A `PATCH` that changes nothing writes no audit event** and still returns 200.
4. **Immutable fields are rejected, not dropped** — the inverse of the `institutions` convention, matching `offers` and `clients`.
5. **An archived document is frozen**: update and status change both return 409 until it is restored.
6. **Query strings are validated** by `DocumentSearchSerializer`; an unparseable filter is a 400.
7. **Only `archived_at` carries a `_bs` sibling** (§39.4). `created_at`/`updated_at` are system timestamps, and dates inside `content` are opaque frontend data that is never parsed.
8. **`label`, `notes`, `standalone_purpose`, and `archive_reason` are Unicode-normalized on write** (§39.2). **`content` is not walked or normalized** — that would be the backend touching the body.

---

## 1. Document

### 1.1 List documents

- **URI:** `GET /api/v1/documents/`
- **Permission key:** `documents.document.list` (risk: **medium**)
- **Auth:** required. Admin only.

**Query parameters:** `applicant` (UUID); `standalone` (bool — omitting it returns both kinds); `status`, `family` (exact enums); `template_key` (exact string); `search` (partial match on `label`); `fiscal_year` (`YYYY/YY`, on `created_at`); `page`, `page_size`.

**Response:** paginated list of the Document **list shape** — `content` is omitted. See `INTEGRATION.md` §4.

**Query access pattern.** `selectors.get_documents` applies `select_related("applicant", "created_by")`. `content` is deliberately **not** deferred: it is the bulk of every row and the list serializer never renders it, so `.defer("content")` looks like the obvious win — but it then triggers a second query the moment any caller touches the field, which is the N+1-by-accident this project avoids elsewhere. If body size ever makes the list slow, add `.defer()` here **and** a matching `.only()` on the detail selector so the two cannot disagree. The `applicant`, `status`, and `family` filters are each served by their own composite index; `search` by `document_label_trgm_idx`.

`selectors.search_documents` matches `label` only and **does not reach into `content`** — full-text search over personal financial data is a feature that needs its own decision, not an accident of a search box.

**Business rules:** none beyond access. Risk is `medium` rather than `low` because the list reveals which applicants have financial documents on file, even without returning the bodies.

**Error codes:** `DOCUMENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR` (bad filter).

**AI debugging notes:** if an archived document "will not disappear" from a list, check whether `status` was passed at all. Omitting it returns every status by design — the concept requires that no historical document vanish just because it is inactive.

### 1.2 Create a document

- **URI:** `POST /api/v1/documents/`
- **Permission key:** `documents.document.create` (risk: medium)

**Request:** `family`, `template_key`, `label` required; then either `applicant` or `standalone_purpose`; plus optional `content`, `notes`.

```json
{
  "applicant": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819",
  "family": "bank_statement",
  "template_key": "bank-vyas-statement",
  "label": "Vyas Statement",
  "content": {
    "statement_account_holder": "Ram Bahadur",
    "statement_opening_balance": 250000,
    "transactions": [{ "date": "2026-04-01", "description": "Deposit", "credit": 500000 }]
  }
}
```

**Response:** 201 with the Document detail shape — see `DATA_CONTRACT.md` §1 "Example".

**Validation rules:** `DATA_CONTRACT.md` §1 "Validation Rules". Ownership and template/family agreement are enforced in `services.assert_owner_declared` and `services.assert_template_key_matches_family`; body checks in `services.assert_content_storable`.

**Business rules:** `status` is always `draft` on creation and is not accepted from the request. `content` defaults to `{}` — a workspace is opened before anything is typed into it.

**Error codes:** `DOCUMENTS_APPLICANT_NOT_FOUND`, `DOCUMENTS_OWNER_REQUIRED`, `DOCUMENTS_TEMPLATE_KEY_INVALID`, `DOCUMENTS_CONTENT_INVALID`, `DOCUMENTS_CONTENT_TOO_LARGE`, `DOCUMENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

**AI debugging notes:** a malformed slug (`"Student Certificate"`) fails at the **serializer** with `VALIDATION_ERROR` on `template_key`, while a well-formed slug in the wrong family (`bank-vyas-statement` under `lor`) reaches the **service** and fails with `DOCUMENTS_TEMPLATE_KEY_INVALID`. Both are 400; the codes differ because the layers do.

### 1.3 List document workspaces

- **URI:** `GET /api/v1/documents/workspaces/`
- **Permission key:** `documents.document.list_workspaces` (risk: medium)

**Response:** paginated list of WorkspaceSummary, ordered by most recent edit.

**Query access pattern.** `selectors.get_workspace_summaries` is a single aggregate query — `values(...).annotate(Count, Max)` — not a fetch-and-group in Python, which would mean pulling every document in the system to build one table. Standalone documents are excluded via `applicant__isnull=False` (they have no applicant to group under, and a null bucket would produce a row the UI cannot link anywhere), and archived documents via `.exclude(status=ARCHIVED)`, because this table answers "whose files have live work on them".

**Business rules:** an applicant whose documents are all archived does not appear at all.

**Error codes:** `DOCUMENTS_ACTOR_FORBIDDEN`.

**AI debugging notes:** `workspaces/` is a literal path segment declared **before** `<uuid:document_id>/` in `urls.py`. If it ever starts returning 404 `DOCUMENTS_DOCUMENT_NOT_FOUND`, the route order has been changed and the id pattern is shadowing it.

### 1.4 Retrieve a document

- **URI:** `GET /api/v1/documents/<document_id>/`
- **Permission key:** `documents.document.read` (risk: **high**)

**Response:** the Document detail shape, including the full body.

**Query access pattern.** `selectors.get_document_by_id` adds `archived_by` to the list relations, so rendering the workspace header — including who archived it — is a fixed small number of queries.

**Business rules:** rated `high` because **this is the only endpoint that returns a document body**, and a body may hold an account number, balance, and full transaction history.

**Error codes:** `DOCUMENTS_DOCUMENT_NOT_FOUND`, `DOCUMENTS_ACTOR_FORBIDDEN`.

### 1.5 Save a document

- **URI:** `PATCH /api/v1/documents/<document_id>/`
- **Permission key:** `documents.document.update` (risk: **high**)

**Request:** any subset of `label`, `content`, `standalone_purpose`, `notes`.

**Response:** 200 with the Document detail shape.

**Business rules:**
- The immutable-field guards run in the view **before** serializer validation, so a request carrying both a legal and an illegal field is rejected whole — a partial apply would be worse than a refusal. Ownership fields and standing fields return different codes so a client can tell which rule it hit.
- **`content` is replaced wholesale, not merged.** Sending `{"content": {"a": 1}}` on a document whose body had ten keys leaves it with one.
- Clearing a standalone document's `standalone_purpose` is rejected — the ownership rule is re-checked against the resulting record, not just on create.
- An archived document returns 409 before any of this runs.

**Error codes:** `DOCUMENTS_OWNERSHIP_IMMUTABLE`, `DOCUMENTS_STATUS_IMMUTABLE`, `DOCUMENTS_DOCUMENT_NOT_EDITABLE`, `DOCUMENTS_OWNER_REQUIRED`, `DOCUMENTS_CONTENT_INVALID`, `DOCUMENTS_CONTENT_TOO_LARGE`, `DOCUMENTS_DOCUMENT_NOT_FOUND`, `DOCUMENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

**AI debugging notes:** if a caller reports that "the document lost most of its fields", they merged client-side and sent a partial body. The API replaces `content` wholesale — this is documented in `INTEGRATION.md` §9 and is the most likely integration mistake in this module.

### 1.6 Change status

- **URI:** `POST /api/v1/documents/<document_id>/status/`
- **Permission key:** `documents.document.change_status` (risk: medium)

**Request:** `{ "status": "ready" }` — `draft` or `ready` only.

**Response:** 200 with the Document detail shape.

**Business rules:** `archived` is excluded at **both** layers — from `SELECTABLE_STATUS_CHOICES` in the serializer, so the request is refused with a field-level error, and from `SELECTABLE_STATUSES` in the service, so a caller reaching the service another way still cannot set it. Archiving demands a reason, and this endpoint has no field for one. Re-sending the current status is a no-op: 200, no event.

**Error codes:** `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409), `DOCUMENTS_STATUS_INVALID_TRANSITION`, `DOCUMENTS_DOCUMENT_NOT_FOUND`, `DOCUMENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.7 Archive a document

- **URI:** `POST /api/v1/documents/<document_id>/archive/`
- **Permission key:** `documents.document.archive` (risk: **high**)

**Request:** `{ "reason": "Superseded by the 2083 revision." }` — required, non-empty.

**Response:** 200 with the Document detail shape: `status: "archived"`, `is_editable: false`, `archived_at` / `archived_by` stamped.

**Business rules:** only an active document may be archived. The reason is mandatory because archived documents are kept forever, so why one is archived must be answerable from the record. **This is what a delete button becomes** — nothing in this app removes a row.

**Error codes:** `DOCUMENTS_DOCUMENT_ALREADY_ARCHIVED` (409), `DOCUMENTS_ARCHIVE_REASON_REQUIRED`, `DOCUMENTS_DOCUMENT_NOT_FOUND`, `DOCUMENTS_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

**AI debugging notes:** a missing `reason` key fails at the serializer with `VALIDATION_ERROR`; a whitespace-only reason reaches the service and fails with `DOCUMENTS_ARCHIVE_REASON_REQUIRED`. Both 400, different layers.

### 1.8 Restore a document

- **URI:** `POST /api/v1/documents/<document_id>/restore/`
- **Permission key:** `documents.document.restore` (risk: **high**)

**Request:** empty body.

**Response:** 200 with the Document detail shape: `status: "draft"`, archive fields cleared.

**Business rules:** only an archived document may be restored, and it **always returns to `draft`, never to `ready`** — whoever archived it may have done so precisely because it was not ready, and a restore should not re-assert a judgement nobody made. Clearing the denormalized archive fields does not erase the archiving from history.

**Error codes:** `DOCUMENTS_DOCUMENT_NOT_ARCHIVED` (409), `DOCUMENTS_DOCUMENT_NOT_FOUND`, `DOCUMENTS_ACTOR_FORBIDDEN`.

### 1.9 Document history

- **URI:** `GET /api/v1/documents/<document_id>/history/`
- **Permission key:** `documents.document.list_history` (risk: medium)

**Response:** paginated list of HistoryEvent, newest first.

**Query access pattern.** `selectors.get_history_for_document` delegates to `audit.selectors.get_events` filtered on `app_label="documents"`, `entity_type="document"`, `entity_id=<id>` — the audit table's own index serves it.

**Business rules:** **a body change appears as the `<changed>` marker, never as content.** This endpoint answers "who changed this document and when", never "what did it say before". Reconstructing a previous body is what `document_history` print snapshots are for — so **editing a document that was never printed loses its previous contents irrecoverably.** A snapshot is captured by an explicit print action, not automatically on save.

**Error codes:** `DOCUMENTS_DOCUMENT_NOT_FOUND`, `DOCUMENTS_ACTOR_FORBIDDEN`.
