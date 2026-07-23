# Security — Institutions

**Owner app:** `institutions`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial security notes — the read/write authority split |

---

## 1. The access split: read-shared, write-restricted

This app is the first in the project where **the read population and the write population differ**. Every app shipped before it grants the same set of authorities both rights, or gates only creation. The rule here:

| Action | `admin` | `lead_manager` | `superadmin` |
|--------|---------|----------------|--------------|
| `GET` (any resource) | allowed | allowed | **denied** |
| `POST` / `PATCH` (any resource) | allowed | **denied** | **denied** |

Implemented in `institutions/access.py` as `require_catalogue_reader` and `require_admin`, applied by the `CatalogueView` base class's `check_read` / `check_write` in `views.py`. Denial is 403 `INSTITUTIONS_ACTOR_FORBIDDEN` in every case.

**Why reads are shared.** Search *is* the catalogue's purpose. `concepts/institutions.txt` — "staff can now rely on the catalogue during counselling" — describes a Lead Manager using it while advising an applicant. A Lead Manager who cannot see the catalogue cannot do their job.

**Why writes are Admin-only.** Every maintenance flow in the concept begins "Admin creates or updates". Catalogue data is *shared infrastructure* rather than one person's record: unlike a lead or a journey, which affects only its own subject, a single careless edit to a program's tuition or entry expectations silently changes the advice every Lead Manager gives every applicant. The blast radius, not the sensitivity of the data, is what narrows the write right.

**Why Superadmin is denied outright**, reads included: it is a platform authority that manages Admin accounts and does not participate in consultancy operations (`concepts/authenticate.txt` — "Authority structure"). This matches `applicants` and `applicant_journeys`.

**Interim pattern, not the permissions app.** These are inline `authority_type` checks per §9. No view in this app — or any app — calls a `check_permission()` engine; the `permission_key` values registered in `registry.py` are metadata, not enforcement. Wiring the two together is a separate, not-yet-built piece.

## 2. No destructive operation exists

There is **no `DELETE` method on any endpoint in this app**, and no delete service function. This is a security property as much as a data-retention one: the most damaging action available against a shared catalogue — removing a record other people's work references — is not reachable through the API at all, by any authority.

Defence in depth, three layers:

1. **No route.** `urls.py` maps only `GET`, `POST`, and `PATCH`.
2. **No service.** `services.py` exposes no delete; withdrawal is `availability_status = inactive`, an ordinary audited update.
3. **Database `PROTECT`.** Every child FK (`Institution.country`, `Campus.institution`, `Program.institution`, `Program.campus`, `Program.field`) is `on_delete=PROTECT`, so even a Django-admin deletion or a direct ORM call raises `ProtectedError` rather than cascading. Covered by `tests/test_services.py::TestNothingIsDeleted`.

An Admin acting through Django admin can still delete an *unreferenced* record. That is accepted: `/admin/` is not client API surface, is session-authenticated, and is already outside the registry-completeness guarantee.

## 3. Accountability of catalogue edits

Admins may change anything, but no change is invisible (`concepts/project_overview.txt` — "Admin authority with full accountability"). Every create and update appends one event to the central `audit` log, and update events carry a `changes` map of `{field: {from, to}}`. That map is the mechanism behind the concept's "if a record changes later, the previous values should remain visible in history."

Two deliberate consequences:

- **A no-op `PATCH` writes no event.** Fabricating a "record updated" entry for a request that changed nothing would dilute exactly the log someone reads to find out what actually happened.
- **A non-`active` `availability_status` requires an `availability_note`, checked against the resulting state.** Withdrawing a record from use is the single most consequential catalogue action — it removes options from every counsellor's search — and it must carry a stated reason. Patching only the status fails even when an old note is already stored, so the reason is re-affirmed by whoever makes the change rather than inherited from a previous one.

## 4. Data sensitivity

Catalogue records contain **no applicant data, no personal data, and no secrets** — they describe universities and their programs. This is the least sensitive data in the project, which is what makes the shared read right safe.

The `audit` payloads written here carry field names, previous and new values, and record ids. Because the underlying data is non-sensitive, no field is withheld from `changes` — unlike `applicant_journeys`, which deliberately keeps notes and closure reasons out of its audit payloads (§17).

## 5. Input handling

- **Every user-entered text field is Unicode-normalized on write** (§39.2), via `NormalizedTextMixin` in `serializers.py`, which normalizes every string in `validated_data` rather than relying on a per-field `validate_<field>()` that can be forgotten when a field is added.
- **`code` fields are ASCII-only** (§39.7), enforced by `validate_reference_code`. Devanagari in a system identifier is rejected — codes appear in logs, URLs, and permission keys.
- **Invalid query parameters are rejected, not ignored.** Every list endpoint validates its query string through a serializer. A silently-dropped filter would return a broader result set than the caller asked for and present it as an answer — which, on a search that decides what is offered to an applicant, is a correctness problem rather than a cosmetic one.
- **Money is `DecimalField` throughout** and serialized as a string (§8). No tuition figure passes through a float.

## 6. Known gaps

- **No object-level access control.** Every reader sees every catalogue record; there is no per-country or per-institution scoping. This is intentional for V1 — the catalogue is consultancy-wide reference data.
- **No rate limiting beyond the project default.** The search is index-backed, paginated at 100 rows, and available only to authenticated staff, so the standard `UserRateThrottle` (1000/hour) applies with no scoped throttle. Should the catalogue ever be exposed to an unauthenticated or applicant-facing client, the program search would need its own throttle.
- **`permission_key` metadata is not enforced.** See §1.
