# Security — Uploaded Files

**Owner app:** `uploaded_files`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial security notes — the project's first byte storage, first split authority model, and first `critical`-risk endpoint |
| 1.0.1 | 2026-07-24 | AI (Claude) | **Closed a cross-module authorization leak** found by the §19.5 consumer-comprehension review: a Lead Manager could list and download files owned by a `document` or a print snapshot, bypassing those modules' Admin-only rule. Added §2.1 |

---

## 1. Why this app has a SECURITY.md at all

Most apps in this project do not need one: they store text, apply the standard auth pattern, and make no security decision of their own. This app makes six, and each of them is the kind that is invisible once shipped and expensive to reverse.

It is also the app holding the most sensitive data in Grandway. `applicants` stores a passport *number*; this stores the *scan*. `documents` stores the inputs to a bank statement; this stores the bank's own PDF. Everything below follows from that.

## 2. Access model, and the one rule that is a judgement

Two levels, both interim §9 inline checks in `access.py`:

| Action | Admin | Lead Manager | Superadmin |
|---|---|---|---|
| list, read, edit, upload, replace, download, versions | ✅ | ✅ | ❌ |
| verify / reject, archive, restore | ✅ | ❌ | ❌ |
| **anything at all, on a `document`- or `snapshot`-owned file** | ✅ | ❌ | ❌ |

**The split between the two rows is the security decision.** A Lead Manager is the person who sits with the applicant and receives the passport scan, so requiring an Admin to attach it would push a daily clerical act through an authority gate and get worked around. But if the uploader were also the reviewer, `verification_status` would record *who uploaded a file* rather than anyone's judgement — which is the one thing the field exists to avoid. Separation of duties, applied at the only point in this app where it buys anything.

**Reads are not owner-scoped, and that is a deliberate acceptance of risk.** Any Lead Manager may read and download any file, including files on applicants assigned to someone else. This is inherited from `applicants`, which made the same call for the same reason — once a person enters the applicant lifecycle several staff legitimately work on their file — and `concepts/project_overview.txt` leaves the question open ("Can Lead Managers view all records, or only records explicitly assigned to them?").

The consequence is sharper here than in any other app: **an unscoped read in `applicants` exposes a name; an unscoped read here exposes a passport.** Two things carry the weight instead of scoping — every download writes an audit event naming the actor, and the user population is small, named, and internal. If the project ever answers that open question with "assigned records only", **this app is the first place it must be applied**, not the last.

**Superadmin is refused outright** on every route, matching `applicants`, `applicant_journeys`, and `offers`: it is a platform authority that manages Admin accounts and does not participate in consultancy operations.

Authority is checked **before** existence on every per-file route, so a caller who may not act cannot use 404-vs-403 to probe for valid file ids. Owner visibility (§2.1) is checked **after** existence and reported as 404, for the opposite reason.

## 2.1 A file inherits the visibility of the record it belongs to

**This is the one defect the §19.5 consumer-comprehension review found in the code rather than the prose, and it is worth recording how it was missed.**

The flat rule in §2 — "Admin and Lead Manager may read any file" — was written against the three owner types that motivated the app: an applicant, a journey, an offer. It was applied to all of them. But `documents` and `document_history` are **Admin-only on every route including reads**, the strictest access model in the project. A file owned by a document or a print snapshot therefore had two contradictory rules, and the looser one won: **a Lead Manager who could not open a bank statement could list and download the PDF attached to it, and neither module would know.** The file ledger had become a side door around another module's access decision.

The reviewer found it by asking a question the author never had to: *what is a `document`-owned file, and who may see it?*

The fix, in `access.py`, `selectors.py`, and `views.py`:

- `ADMIN_ONLY_OWNER_TYPES` names the restricted owner types — `document`, `snapshot`, and, since 2026-09-10, `signatory`. It is a **membership list for a rule**, not the rule itself — the rule is "a file inherits the visibility of its owner", and the list must be revisited in the same change as any decision to give Lead Managers document access.
- Per-file routes check the resolved file's owner in `FileScopedView.resolve`, so no route can omit it.
- Upload checks the owner it is about to attach to, **before** anything is written to disk.
- The list **excludes** restricted rows from the queryset for a non-Admin rather than refusing them per row.

**Read refusals are 404, not 403**, and that asymmetry is deliberate. A 403 confirms the file exists, which confirms the *document* exists — precisely what `documents` hides from that authority. Upload refusals stay 403, because there is nothing to conceal: the client named the owner id itself.

**`signatory` joined the list when signature images became uploadable, and it is the first entry added by design rather than by discovery.** The structural argument is identical — `document_templates.access.require_template_actor` refuses a Lead Manager on every route including `GET`, so listing or downloading a signatory's file here would be the same side door. The specific argument is not: a signature image is **not** applicant data and is not confidential in the ordinary sense — the director's signature appears on every certificate the consultancy has ever issued. What is protected is the *usable* form. A print-ready, background-free copy is what lets someone affix that signature to a document Grandway never issued, and write access is worse still, because whoever controls the stored image controls what every future certificate — and, since reprints resolve live, every past one — appears to be signed by. `document_templates/docs/SECURITY.md` carries that argument in full.

The general lesson, which applies to every app that follows: **an access rule stated per-app is incomplete the moment one app stores data on behalf of another.** This app holds data belonging to six modules with three different access models, and the newest of them arrived with a threat model — forgery rather than disclosure — that none of the original three had.

## 3. The bytes are private by construction

Four decisions, each of which independently prevents a file from being reachable without authorization:

1. **Nothing serves `MEDIA_ROOT`.** `core/urls.py` routes exactly four prefixes — `admin/`, `health/`, `ready/`, and `api/v1/` — and none is a static file handler, so **no URL maps to the storage volume in any environment**. This is the load-bearing decision: one `static(MEDIA_URL, document_root=MEDIA_ROOT)` line added for local convenience would publish every applicant passport at a guessable path. Guarded by a test that fails if such a route ever appears (`core/tests/test_media_is_not_served.py`). `MEDIA_URL` itself is left at Django's default and is inert — nothing in this project calls `FileField.url`.
2. **The `file` column is never serialized.** It is the only model field in this project excluded from its serializer under all circumstances. A response that carried the storage path would leak the volume's layout and imply a fetchable URL.
3. **The storage path is never logged and never recorded in an audit event.** `services._record` writes the file's id, category, and owner; a path in the log would let anyone with log access locate an applicant's passport on disk without touching the API. Enforced by `tests/test_services.py::AuditTests::test_no_event_leaks_the_storage_path`.
4. **The stored filename is a fresh UUID**, never the client's. A crafted name cannot traverse a path, two identical scans cannot collide, and an operator browsing the volume cannot read applicant identities off the filenames.

Files are written mode `0640` in directories `0750` (`FILE_UPLOAD_PERMISSIONS`), so they are not readable by unrelated accounts on the host.

The layout is `uploaded_files/<owner_type>/<YYYY>/<MM>/<uuid>.<ext>`, so a sixth top-level directory — `signatory/` — appears the first time a signature image is uploaded. **This is the one place where the temptation to add a static handler will be strongest**: a signature is the one stored artefact that looks like an ordinary web asset, and "just serve the signatures" is a single line that would publish every applicant passport alongside them. Decision 1 above is absolute and has no per-owner-type exception. The signature render path is an authenticated `fetch` plus a blob URL, documented in `document_templates/docs/INTEGRATION.md` §3.

## 4. What upload validation does and does not do

Three checks, in `validators.py`, applied before anything is written — a rejected upload leaves **no row and no bytes**:

1. Size ≤ 10 MB and non-zero.
2. Extension in `pdf, jpg, jpeg, png, webp, docx, xlsx`. The **last** dot-segment decides, so `passport.pdf.exe` is an `exe` and is refused — a double extension cannot smuggle a type past the allowlist.
3. The leading bytes match the signature expected for that extension.

**This is a type check, not a malware check.** A file that begins `%PDF-` and is otherwise a malicious document passes. There is no virus scanning, no sandbox, and no content inspection anywhere in this project. What check 3 buys is narrow and real: a renamed executable cannot enter the system wearing a `.pdf`.

**Two known limits, recorded rather than glossed:**

- `docx` and `xlsx` are both ZIP containers sharing `PK\x03\x04`, so the check cannot tell them apart; the extension decides which of the two a file is. Both are accepted types, so confusing them changes nothing about who may read the file or how it is stored.
- Accepting Office formats at all is a considered risk. They are the main macro-carrier class, and they are accepted because staff receive institution letters and financial statements in them. The mitigation is #5 below — nothing in this system ever *opens* one.

**No third-party library.** `python-magic` was deliberately not taken: it requires `libmagic` on every developer machine, in CI, and in every deployment, and it would be this project's first dependency needing a system package. What it buys over the module here is recognition of types this app does not accept.

## 5. The download path

`GET /files/<id>/download/` is registered at **`critical`** risk — the only endpoint in Grandway at that level — because it is the only route in the system that returns an applicant's passport, transcript, or bank statement as bytes. Since 2026-09-10 it is also the route a certificate fetches a signature image from, which changes its traffic profile without changing its rating; see §7.

Three response headers are set deliberately:

- **`Content-Disposition: attachment`, always, never `inline`.** A file rendered in the API's own origin could execute against it; forcing a download removes the whole class of stored-XSS problem, including for the Office formats §4 accepts.
- **`X-Content-Type-Options: nosniff`** — stops a browser second-guessing the declared type and rendering something as HTML.
- **`Cache-Control: private, no-store`** — an applicant's passport must not sit in a shared cache or on disk after the tab closes.

**Every download writes an audit event**, before the stream starts, so a client that aborts mid-transfer still leaves the record that it asked. This is the only read in the entire project that is audited, and it exists because `concepts/project_overview.txt` requires that "broad access, exports, file replacement, and sensitive actions must be reviewable" — a download *is* an export of one file.

**That property is absolute, with no per-owner-type carve-out, and it was deliberately kept absolute when signature images arrived.** A signature fetched to render a certificate produces a `file_downloaded` event exactly like a passport export does, which means certificate rendering adds audit volume that is not, in any interesting sense, an export. Exempting `signatory`-owned files was considered and rejected: the value of "every read of every file is recorded" comes from having no exceptions, and the first exception is the one that makes the second easy. The cost is managed by client contract instead — fetch a signature once per session and hold the object URL — recorded in §7 and in `document_templates/docs/INTEGRATION.md` §3.

`UPLOADED_FILES_FILE_BYTES_MISSING` (404) is returned when the row exists and the file does not. It is deliberately a 404 with no path in the body, and an `ERROR`-level log entry carrying only the file id: the client learns nothing about the volume, and an operator learns that the database and the storage have diverged.

## 6. Integrity and non-repudiation

- **SHA-256 at upload**, streamed in 64 KB chunks and stored hex-encoded. It is computed once and never recomputed on read — this app detects nothing about later tampering on the volume, and does not claim to.
- **Nothing is ever overwritten.** There is no path that replaces the bytes of an existing row. A replacement is a new row with a `OneToOne` link back to its predecessor, so "what did we hold at the time" stays answerable.
- **Nothing is ever deleted.** No delete endpoint, no delete service, no admin delete, and no model path. Enforced structurally by `tests/test_services.py::NothingIsDeletedTests`, which fails the moment a delete path appears — which is exactly when the decision should be re-argued rather than absorbed.
- **The Django admin is fully read-only**, including for a superuser: no add, no change, no delete. An admin able to edit `checksum_sha256`, `size_bytes`, or `content_type` could make the row disagree with the file it describes, silently and undetectably.
- **Exactly one owner, enforced in the database.** The `uploaded_file_single_owner` check constraint binds the admin, the shell, and any future management command, not just the serializer.

## 7. Accepted risks

Recorded here rather than left implicit. None of these is a defect; each is a decision whose cost is understood.

| Risk | Why it is accepted | What would change it |
|---|---|---|
| Any Lead Manager can download any applicant's passport | §2 — inherited from `applicants`; small, named, internal user population; every download is audited. Note this does **not** extend to document- or snapshot-owned files (§2.1) | Answering `project_overview.txt`'s open question with "assigned records only" |
| No malware scanning | No scanner exists anywhere in this project; §4's type check plus §5's forced download cover the delivery vector | An engagement with untrusted uploaders, or applicant self-service |
| Throttle is the project default (1000/hour) | A single account could move ~10 GB/hour through upload + download. Internal staff system, and the audit trail makes abuse visible after the fact rather than preventing it | Any external or semi-trusted caller, at which point these two routes need their own scope |
| `original_filename` is recorded in audit summaries | It can carry identity ("sita_passport_scan.pdf"). The log is already staff-scoped, and an event that cannot say which file it was about is not worth writing | A wider audit-log audience |
| No encryption at rest | Files sit on the host filesystem in plain form. §37 makes local-first the posture; disk-level encryption is a deployment concern, not an application one | A hosting arrangement where the volume is not physically controlled |
| Signature renders inflate the audited-download trail | Kept deliberately, to preserve §5's no-exceptions property. A certificate naming two signers writes two `file_downloaded` events per fresh render, so the export trail for genuine exports gets noisier. Mitigated by a client contract (fetch once per session) rather than a code carve-out | Audit volume becoming an operational problem in practice. The fix would be exempting `signatory`-owned downloads, which requires rewriting §5's absolute claim — do it knowingly or not at all |
| No orphan-byte reclamation | Rows are never deleted, so files never orphan through normal operation. A process killed mid-upload could leave bytes with no row | Evidence of it happening; the fix is a sweeper command comparing the volume against the table |
| No upload idempotency (a §15 departure) | Duplicates are legitimate by design, so a request-level de-duplication key cannot distinguish an intentional re-upload from a retry. A timed-out upload that succeeded leaves a second row | A client-supplied idempotency key, which is the recommended fix |
| `upload_source` is caller-asserted | Nothing on the backend generates a file, so there is no trustworthy value to enforce against. `uploaded_by` carries the accountability | Any server-side generation path, which would make the field meaningful and therefore worth protecting |
