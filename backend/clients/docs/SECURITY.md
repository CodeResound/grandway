# Security — Clients

**Owner app:** `clients`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial security notes — the read/write split and the no-deletion posture |

---

## 1. The access split: read-shared, write-restricted

| Action | `admin` | `lead_manager` | `superadmin` |
|--------|---------|----------------|--------------|
| `GET` (list, detail, history) | allowed | allowed | **denied** |
| `POST` / `PATCH` (create, update, retire, restore) | allowed | **denied** | **denied** |

Implemented in `clients/access.py` as `require_client_reader` and `require_admin`, applied per route by `ClientScopedView.resolve(..., check=...)` and by the two methods of `ClientListCreateView`. Denial is 403 `CLIENTS_ACTOR_FORBIDDEN` in every case, with a message distinguishing the two refusals.

This is the second app in the project with this shape, after `institutions` — and the second of seven, so it is the exception rather than the pattern. `applicants`, `applicant_journeys`, and `offers` all grant reads and writes to the same population.

**Why reads are shared.** Looking up who to call at a partner is the whole point of a directory. `concepts/clients.txt` — "Find the right partner" — describes a Lead Manager doing exactly this, unassisted. A directory only Admins can open is a phone list in a drawer.

**Why writes are Admin-only.** Every maintenance flow in the concept begins "An Admin creates or updates a client". Client records are *shared reference data* rather than one person's work: unlike a lead or a journey, which affects only its own subject, a single careless edit to a spokesperson's number silently changes who every Lead Manager calls. The blast radius, not the sensitivity of the data, is what narrows the write right — the same reasoning as `institutions`.

**Why Superadmin is denied outright**, reads included: it is a platform authority that manages Admin accounts and does not participate in consultancy operations (`concepts/authenticate.txt` — "Authority structure"). This matches every business app in the project.

**Consequence worth stating.** A 404 from this app always means the record genuinely does not exist — never "exists but is out of your scope", as it can in `leads`. Nothing here is hidden from an authorised caller, and there is no owner scoping.

**Interim pattern, not the permissions app.** These are inline `authority_type` checks per §9. No view in this app — or any app — calls a `check_permission()` engine; the `permission_key` values in `registry.py` are metadata, not enforcement. Wiring the two together is a separate, not-yet-built piece.

## 2. No destructive operation exists

There is **no `DELETE` method on any endpoint in this app**, and no delete service function. This is a data-retention property and a security one: the most damaging action available against a shared directory — removing the record other people's work references — is not reachable through the API at all, by any authority.

Defence in depth, four layers:

1. **No route.** `urls.py` maps only `GET`, `POST`, and `PATCH`.
2. **No service.** `services.py` exposes no delete; withdrawal is `retire_client`, an audited status change.
3. **A test that fails if one appears.** `tests/test_services.py::NothingIsDeletedTests::test_the_app_exposes_no_delete_service` scans the service module for any `delete_*` or `remove_*` callable. A future session that adds one has to remove the test deliberately rather than slip past review.
4. **Database `PROTECT`** on `Client.created_by`, so the account that added a client cannot be deleted out from under it.

`ClientContactNumber.client` is `CASCADE`, which looks like an exception and is not: numbers are a replacement set, hard-deleted and recreated on every write, and the cascade can never fire because nothing deletes a client.

## 3. Standing has exactly one path

`status`, `status_note`, `retired_at`, and `retired_by` are all unreachable through `PATCH` — a request carrying any of them returns 400 `CLIENTS_STATUS_IMMUTABLE` with the offending fields listed. They move only through the retire and restore actions, which stamp the actor and, for retirement, demand a reason.

Rejecting rather than silently ignoring is the deliberate choice, and it differs from `institutions`, which drops immutable fields quietly so a round-trip edit form works. Here the field is not merely immutable-by-this-route, it is *accountability-bearing*: a caller who set `status` and received 200 would reasonably believe a partner had been retired, with no record of who did it or why.

## 4. Attribution on every mutation

Every create, update, retire, and restore appends one `audit.AuditEvent` carrying the actor, their authority type, the changed fields' previous and new values, and the client IP. Two facts are additionally denormalized onto the row so "who retired this, and when" is a field read rather than a log query: `retired_at` and `retired_by`. The append-only log remains the authoritative event history (§35 item 15).

A `PATCH` that changes nothing writes no event — a UI reporting "saved, history updated" after an unchanged submit would be claiming something that did not happen. Replacing contact numbers **does** count as a change and is recorded, even when the resulting set is identical, because the write path cannot tell the difference without comparing sets and the cost of a spurious event is lower than the cost of a missing one.

## 5. What is deliberately not protected

- **No field-level redaction.** Every field of a client is visible to every Admin and Lead Manager. `concepts/project_overview.txt` lists "Which sensitive fields or files should be hidden from Lead Managers by default?" as an open project question; until it is answered, this app does not invent an answer.
- **`logo_url` and `website` are not fetched, validated for reachability, or proxied.** They are stored strings that a browser will load from a third-party host. A UI rendering `logo_url` in an `<img>` tag leaks a referrer to that host and will display whatever it serves. If that matters, proxy or allowlist at the frontend — this app makes no guarantee about what is behind the URL, and format validation is not safety validation.
- **No rate limiting beyond project defaults.** No endpoint here is public, and none is expensive — the directory is a small table and every list is paginated at 100 rows.
