# Security — Offers

**Owner app:** `offers`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial security notes — the shared access model, decision finality, and immutable history |

---

## 1. Access model: shared, one rule for read and write

| Action | `admin` | `lead_manager` | `superadmin` |
|--------|---------|----------------|--------------|
| `GET` (any resource) | allowed | allowed | **denied** |
| `POST` / `PATCH` (any resource) | allowed | allowed | **denied** |

Implemented in `offers/access.py` as `require_offer_actor`, applied by every view. Denial is 403 `OFFERS_ACTOR_FORBIDDEN` in every case.

**Why there is no read/write split.** `institutions` — the app this one references most — has one, and the contrast is deliberate. Catalogue data is *shared infrastructure*: one careless edit changes the advice every Lead Manager gives every applicant, so the write right is narrower than the read right. An offer is the opposite: it is journey-scoped operational work with a blast radius of exactly one applicant. The Lead Manager running the journey is the person who receives the institution's letter and records the applicant's answer. Putting an Admin in the middle of every routine admission response would add an approval step to the most ordinary act in the module without protecting anything.

**Why access is not owner-scoped.** Offers inherit the visibility of the journeys they hang from, and journeys are shared across the consultancy (`applicant_journeys/docs/SECURITY.md` §1). An offer visible to fewer people than its journey would produce a Journey Detail screen with an offers panel some staff could not load.

**Why Superadmin is denied outright**, reads included: it is a platform authority that manages Admin accounts and does not participate in consultancy operations (`concepts/authenticate.txt` — "Authority structure"). This matches `applicants`, `applicant_journeys`, and `institutions`.

**Consequence worth stating.** A 404 from this app always means the record genuinely does not exist — never "exists but is out of your scope", as it can in `leads`. Nothing here is hidden from an authorised caller.

**Interim pattern, not the permissions app.** These are inline `authority_type` checks per §9. No view in this app — or any app — calls a `check_permission()` engine; the `permission_key` values in `registry.py` are metadata, not enforcement. Wiring the two together is a separate, not-yet-built piece.

## 2. History cannot be rewritten

The concept's central requirement is that an offer preserves what was true when the institution made its decision. Three mechanisms enforce it, and each is a security property as much as a data-integrity one — an unfalsifiable record is what makes the audit trail worth having.

1. **The snapshot is write-once.** `institution_name_en`, `institution_name_np`, `campus_name`, `program_title`, `country_name`, `qualification_level`, and `intake_label` are copied from the catalogue at creation and are unreachable afterwards. A `PATCH` carrying any of them — or `journey`, any catalogue FK, or `status` — is **rejected** with 400 `OFFERS_REFERENCE_IMMUTABLE`, not silently ignored. Silent ignoring is the `institutions` convention and is wrong here: a client that sent a corrected `program_title` and received 200 would believe it had changed the record.
2. **A decision is final.** There is no reopen action, deliberately, unlike `applicant_journeys`. Once `status` is terminal the offer accepts no further decision (409 `OFFERS_OFFER_NOT_DECIDABLE`). An institution that changes its position has issued a *new* offer.
3. **Nothing is deleted.** No `DELETE` route, no delete service, and `PROTECT` on `journey`, `institution`, `campus`, `program`, and `created_by`. An offer that no longer applies is given a terminal status; a condition that does not apply becomes `not_applicable` with a note.

Catalogue edits are the case this exists for: renaming a program or marking an institution inactive changes nothing on an offer already recorded against it. Covered by `tests/test_services.py::OfferCreationTests::test_snapshot_survives_a_later_catalogue_edit`.

## 3. Attribution on every mutation

Every create, update, issue, decision, and condition change appends one `audit.AuditEvent` carrying the actor, the actor's authority type, the changed fields' previous and new values, and the client IP. Two facts are additionally denormalized onto the row itself so that "who decided this, and when" is a field read rather than a log query: `decided_at` / `decided_by` on the offer, and `resolved_at` / `resolved_by` on each condition. The append-only log remains the authoritative event history (§35 item 15).

A `PATCH` that changes nothing writes no event — a UI reporting "saved, history updated" after an unchanged submit would be claiming something that did not happen.

## 4. What is deliberately not protected

- **No field-level redaction.** Every field of an offer, including tuition, scholarship, and deposit figures, is visible to every Admin and Lead Manager. `concepts/project_overview.txt` lists "Which sensitive fields or files should be hidden from Lead Managers by default?" as an open project question; until it is answered, this app does not invent an answer.
- **No rate limiting beyond project defaults.** No endpoint here is public, and none is expensive — every list is index-backed and paginated at 100 rows.
- **Deposit amounts are recorded, never collected.** There is no payment path, no card data, and no financial integration in this app (`concepts/offers.txt` — "No payments or accounting"). The deposit fields are inert text and numbers.
