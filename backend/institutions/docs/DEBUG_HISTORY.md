# Debug History — Institutions

## 2026-09-13 — `0001_initial` could run before the `pg_trgm` extension existed

**Endpoint/module:** `institutions.migrations.0001_initial`
**Problem:** On an empty PostgreSQL database — a CI runner, a new host — `migrate` failed with `operator class "gin_trgm_ops" does not exist for access method "gin"` while applying this migration. Developer databases never showed it because the extension had been created there long ago by `leads.0002`.
**Root cause:** The migration builds GIN trigram indexes but declared no dependency on any migration that creates the extension, so the migration planner was free to schedule it first. `uploaded_files.0001` had already solved the same problem with an explicit dependency; this app's initial migration had not.
**Changed files:** `migrations/0001_initial.py` (dependency on `applicants.0001_initial`, the earliest extension creator, with a comment explaining it is an ordering dependency, not a data relation)
**Fix summary:** Dependencies only affect planning order; on databases where both migrations are already applied nothing changes. Verified by migrating an empty database from scratch: 76 migrations applied, `sync_policy_registry` and `validate_policy_engine --strict` green, `makemigrations --check` clean.
**Contract impact:** None.
**Tests added/updated:** None — the suite runs on SQLite, where trigram indexes are no-ops (a known deferral in `CHANGELOG.md`). The `policy-engine` CI job on a fresh PostgreSQL service is the regression check.
**Notes for future AI:** Any migration that uses `gin_trgm_ops` must depend on a migration that runs `TrigramExtension()`. A migration that only works because the developer's database is old is a migration that fails on deploy day.

---

