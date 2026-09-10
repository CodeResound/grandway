# Security — Document Templates

**Owner app:** `document_templates`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-09-10

This document is required per project rulebook §19 (Documentation Requirements) because `document_templates` makes its own security-relevant decisions beyond the project's standard auth pattern.

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-09-10 | AI (Claude Opus 5) | Initial security documentation, created when the app began accepting uploaded signature images |

---

## 1. Why this app has a SECURITY.md, and why it did not before

Until 2026-09-10 it did not need one, and `backend/core/docs/INTEGRATION.md` said so outright: *"Neither `document_history` nor `document_templates` publishes a `SECURITY.md`, because neither adds a security decision of its own."* That was true. This app held a staff member's name, a job title, a free-text role, and a link — no applicant data, no bytes, no decision that was not inherited from `authenticate` and `access.py`.

Accepting uploaded signature images changed four things at once, and none of them is inherited:

1. It accepts bytes from a client and writes them to the storage volume (§3).
2. Those bytes are the artefact that makes an issued certificate look authoritative — a forgery surface unlike anything else in the project (§2).
3. It decides an authorization rule about **another app's** resource: whether a signature file is Admin-only inside `uploaded_files` (§4).
4. It now has two sources for one rendered image, one of them an unvalidated external URL, and had to decide which wins (§5).

## 2. The threat this app is actually defending against is forgery, not disclosure

Every other access rule in this project protects **confidentiality** — an applicant's passport, a bank statement, a lead's phone number. A signature image is different in kind. Its content is not secret: the signature of a consultancy director appears at the bottom of every certificate that consultancy has ever issued, and any recipient holds a copy.

What matters is **integrity and scarcity of the source**. An attacker who obtains a clean, high-resolution, background-free PNG of a director's signature can affix it to a document Grandway never issued. The value of the stored file is not that it is unknown, but that it is the *usable* form — cropped, transparent, print-ready — which a photograph of a printed certificate is not.

Two consequences run through the rest of this document:

- **Read access to the bytes is a larger ask than read access to the signatory row**, not a smaller one. A staff member who may see that "Sunita Shrestha, Director" exists is not thereby entitled to a print-ready copy of her signature.
- **Write access is the more dangerous half.** Anyone who can replace a signature image controls what every future certificate — and, because reprints resolve live (§6), every past one — appears to be signed by. This is why the upload endpoint is rated `high` and why `signature_file` is refused on `PATCH` (§5).

## 3. Byte acceptance, and what this app does not re-implement

**This app stores nothing itself.** `services.set_signatory_signature` delegates wholly to `uploaded_files.services.upload_file`/`replace_file`, and reimplements no validation, no checksumming, and no path construction. That is a §4 requirement and also the security-relevant choice: the §14 file contract — 10 MB cap, extension allowlist, leading-byte verification, SHA-256 checksum, `0o640` files under a never-web-served `MEDIA_ROOT` — is defined and tested in one place, and a second implementation here would be a second place for it to be wrong.

**What this app adds is a narrowing, applied first.** `SIGNATURE_IMAGE_EXTENSIONS` is `{png, jpg, jpeg, webp}` — a strict subset of the ledger's seven-type allowlist, which also accepts PDF, DOCX, and XLSX. None of those is a signature. Without the narrowing, a 10 MB spreadsheet stored under a director's name would satisfy every check downstream, and the ledger would be right to accept it: its own module docstring says it *"stores bytes and the facts about them, and decides nothing about what those bytes mean."* What a signature *means* is this app's question, so this app answers it. A test asserts the narrowing stays a subset, so a future removal from the ledger's allowlist fails a test rather than a request.

**The narrowing is a name check; the ledger's is a bytes check.** A PDF renamed `signature.png` passes here and is refused by `assert_content_matches_extension` on its leading bytes. Both run, narrower first. Neither alone is sufficient and neither is a substitute for the other.

**Not defended against, and stated rather than implied:** a genuine PNG whose *content* is somebody else's signature. There is no image analysis, no provenance check, and no verification that the uploader had any right to the signature they uploaded. The control is procedural — Admin-only write access plus an audit trail naming who uploaded what and when — not technical.

## 4. Why signature files are Admin-only inside `uploaded_files`

`signatory` is a member of `uploaded_files.constants.ADMIN_ONLY_OWNER_TYPES`, alongside `document` and `snapshot`. This is a §28 item 5 decision and it was taken explicitly.

**The structural argument.** `access.require_template_actor` refuses a Lead Manager on *every* route in this app, `GET` included. Meanwhile `uploaded_files.access.require_file_actor` permits Admin **and** Lead Manager to list, read, download, and upload. Without the tuple membership, a Lead Manager who is refused the signatory list could nevertheless call `GET /api/v1/files/?category=signature_image`, read every signature's filename and owner, `GET /api/v1/files/<id>/download/` the bytes, and `POST /api/v1/files/` with `signatory=<id>` to attach a signature of their choosing. The file ledger would become a side door around this app's access rule, and neither app would know. That is the exact failure `uploaded_files/docs/SECURITY.md` §2.1 was written to close for `document`-owned files, and its own text requires the tuple be revisited in the same change as any decision of this kind.

**The specific argument** is §2: the write path lets an attacker choose what future certificates appear to be signed by, and the read path yields the print-ready artefact.

**It is enforced in three places**, because a file can be reached three ways, and all three fall out of the tuple with no new code: per-file routes check the resolved file's owner and answer **404** rather than 403 (confirming the file exists would leak what this app hides), the upload route checks the owner it is about to attach to and answers 403, and the list selector excludes restricted rows so they never appear in a page. Search inherits it too, since `search` narrows the file bucket through `get_visible_files`.

**Superadmin is refused as well**, matching this app's own rule and the ledger's. There is no authority in the system that can read a signature file but not the signatory row, or vice versa.

## 5. Two signature sources, one of them unvalidated

`signature_image_url` is a plain link this API stores verbatim, never fetches, and never validates beyond well-formedness. It is retained for backward compatibility (§29) and remains the rendering source for any signatory with no uploaded file.

**The server never fetches it, and that is the security property worth naming.** If it did, an attacker who could set the field would have an SSRF primitive pointed at whatever the server can reach. Nothing in this project dereferences the URL — the *client* fetches it, from its own network position — so the exposure is the client's, and the honest statement is that this API will happily store and return a link to anywhere.

**Precedence is decided server-side, in one place.** `selectors.get_current_signature_file` returns the linked file only when it is neither archived nor superseded, and `signature_source` reports `uploaded` / `url` / `none`. The reason this is not left to the client is a security one as much as an ergonomic one: a client cannot see that a file was archived, so a client-side rule of the form "use the file if `signature_file` is non-null" would keep rendering a signature that an Admin had deliberately withdrawn.

**`signature_file` is never accepted from a request.** A `PATCH` carrying it is refused with `DOCUMENT_TEMPLATES_SIGNATURE_FILE_IMMUTABLE` rather than ignored, and the Django admin renders it read-only. Both guards close the same hole: a bare file id would let an Admin point a signatory at *any* `UploadedFile` on the platform — an applicant's passport included — with no ownership check and no bytes ever uploaded for that signer. The only way to set it is to upload bytes, which stores and links them in one transaction.

## 6. Replacing a signature rewrites the past, by design

`document_history` freezes a signatory's `id`, `name`, and `role` into a snapshot's `render_context` and **never the image**. A reprint therefore resolves the signature live. Replacing a director's signature changes what every historical certificate renders, beside a frozen historical name.

This is recorded here rather than only in the API docs because it is a **non-repudiation** property, and it is the weaker of the two available ones. The audit trail is intact — every version is kept, superseded rather than deleted, with the uploader and timestamp on each — so the question "what did this signature look like in Baisakh 2082" is answerable from `GET /api/v1/files/<id>/versions/`. The question "what did the certificate we issued in Baisakh 2082 look like" is *not* answerable from this system alone. If that matters for a given document class, the image must be frozen at print time by the client; this API will not do it.

## 7. Accepted risks

- **No image content analysis.** Any valid PNG/JPEG/WEBP under 10 MB is accepted as a signature. Grandway cannot tell a signature from a photograph of a cat, and does not try.
- **No provenance check on the signature itself.** Nothing verifies the uploader was entitled to that person's signature. Mitigated procedurally: Admin-only, fully audited.
- **Signature bytes traverse an authenticated, uncached, audited route on every fresh render.** Two signers per certificate means two `file_downloaded` audit events per render. Accepted for v1 rather than carved out, because exempting one owner type from the project's only audited read would weaken a property that is currently absolute. The mitigation is a client contract — fetch once per session, hold the object URL — documented in `docs/INTEGRATION.md` §3 and `concepts/document_templates_flows.md`. Revisit if audit volume becomes a real operational problem; a carve-out would require rewriting `uploaded_files/docs/SECURITY.md` §5.
- **The upload endpoint inherits the shared `UserRateThrottle` of 1000/hour** with no dedicated scope, so one Admin account could push roughly 10 GB through it in an hour. Identical to the accepted limit already recorded for `POST /files/`, and reachable only by an Admin.
- **No concurrency control.** Two Admins uploading a signature for the same signatory concurrently is last-write-wins; both files are stored and audited, but only one ends up linked. Consistent with the rest of this app, which has no ETag or `If-Match` on any route.
