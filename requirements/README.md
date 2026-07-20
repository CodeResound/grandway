# Requirements

Dependencies are split by environment. All files use `==` pinning for production packages.

## Files

| File | Purpose | Installs |
|------|---------|---------|
| `base.txt` | Core runtime dependencies | Django, DRF, psycopg, auth, etc. |
| `development.txt` | Dev + test tooling | `base.txt` + ruff, pytest, pytest-django |
| `production.txt` | Production server | `base.txt` + gunicorn |

## Install

```bash
# Development
pip install -r requirements/development.txt

# Production
pip install -r requirements/production.txt
```

## Continuous integration (CI)

The mechanical gates in this project are enforced in two places:

- **`.claude/hooks/`** — fire during an interactive Claude Code session (on Edit/Write and
  git Bash calls). They guide the AI as it works, but a `git push`, a PR, or any commit made
  outside Claude Code bypasses them entirely.
- **`.github/workflows/ci.yml`** — runs on every push and pull request. CI **mirrors** the hooks
  (it does not replace them) so the same checks apply no matter who or what produced the commit.

Both call the single shared runner **`scripts/ci.sh`** so local and CI enforcement can never drift:

```bash
scripts/ci.sh            # all stages: lint, policy, test
scripts/ci.sh lint       # ruff check + ruff format --check on backend/
scripts/ci.sh test       # pytest against PostgreSQL (--ds=core.settings.ci)
scripts/ci.sh policy     # migrate -> sync_policy_registry -> validate_policy_engine --strict
```

Both the `test` and `policy` stages need a reachable PostgreSQL — supply `DB_*` + `SECRET_KEY` via
the environment or your local `.env.development`. Tests run against Postgres (via the
`core.settings.ci` settings module), not the SQLite `core.settings.testing`, because the migrations
include Postgres-only SQL (`pg_trgm`) and several tests depend on the real migrated schema. Only the
`lint` stage runs without a database. Run `scripts/ci.sh` from the repo root with your `.venv`
activated before opening a PR.

## Adding a new dependency

Before adding any package, you must complete all steps below in order. Skipping any step is a violation of the project rules (CLAUDE.md §24 and §28).

1. **Get explicit approval** — present the library name, purpose, alternatives considered, and security concerns to the team. Wait for approval before proceeding (CLAUDE.md §28 item 1).
2. **Document it** — add a full entry to `backend/core/docs/THIRD_PARTY_LIBRARIES.md` using the 10-field template (name, purpose, docs link, package name, files used, alternatives considered, redundancy check, security concerns, maintenance status, final decision).
3. **Pin and add to the correct file** — add the package with an exact version pin (`==`) to the right file:
   - Runtime dependency used in staging/production → `requirements/base.txt`
   - Dev/test tooling only → `requirements/development.txt`
   - Production-server-only tooling → `requirements/production.txt`
4. **Install and verify** — `pip install -r requirements/<env>.txt` and confirm the environment works.
5. **Commit both files together** — the `THIRD_PARTY_LIBRARIES.md` entry and the requirements file change must be in the same commit.

## Upgrading a dependency

1. Update the pinned version in the requirements file.
2. Update the `Package` field in `THIRD_PARTY_LIBRARIES.md`.
3. Note the upgrade in `backend/core/docs/DEBUG_HISTORY.md` if it fixes a bug or closes a CVE.
4. Re-run the full test suite before committing.

## Management commands

After installing dependencies and configuring `.env`/`.env.development`, run these in order to take a fresh database to a usable state:

```bash
python manage.py migrate
python manage.py bootstrap_superadmin
python manage.py sync_policy_registry --by ai --identifier "claude-sonnet"
python manage.py validate_policy_engine --strict
```

| Command | App | Purpose |
|---------|-----|---------|
| `bootstrap_superadmin` | `authenticate` | Idempotently creates the platform's first `is_superuser` actor (bypasses all permission checks platform-wide). Needed before anything else, since there are no roles/permissions yet for any other actor to act with. Safe to re-run — corrects flags on an existing account instead of duplicating it. Flags: `--username`, `--email`, `--password`, `--display-name` (each falls back to a `SUPERADMIN_*` env var, then a built-in default; an unset password is auto-generated and printed once). |
| `sync_policy_registry` | `core.policy_engine` | Discovers `POLICY_ENDPOINTS` from every installed app's `registry.py` and registers them in the Core Policy Engine. Re-run any time after adding or changing an endpoint's registry entry — idempotent. Flags: `--dry-run` (preview without writing), `--by {human,ai,system}`, `--identifier`. |
| `validate_policy_engine` | `core.policy_engine` | Validates Policy Engine metadata integrity (duplicate permission keys, endpoints missing categories/dependencies, invalid permission-key format, etc.). Flag: `--strict` (exit code 1 on any finding — use this in CI). |
| `export_policy_registry` | `core.policy_engine` | Emits machine-readable artifacts derived from the registry declarations (no database): the canonical registry JSON or an OpenAPI 3.1 document. Not part of fresh-init. Flags: `--format {registry,openapi}` (default `registry`), `--output <path>` (default stdout), `--check` (fail if the committed `docs/registry_export.json`/`docs/openapi.json` has drifted from the registry — used in CI, mirrors `makemigrations --check`). |
| `validate_organization_integrity` | `organization` | Validates organizational structure integrity: unit-parent cycles, closure-table self-links/depths/organization-consistency, cross-organization references on positions/assignments/reporting lines, reporting-line self-cycles and duplicate active primary administrative lines, position capacity, delegation time windows, and unit-history-to-event-log completeness. Operates on already-existing org data, not a fresh DB — not part of the bootstrap sequence above. Flags: `--dry-run` (accepted for symmetry; this command never writes), `--strict` (exit code 1 on any finding). |
| `rebuild_organization_closure` | `organization` | Rebuilds `OrganizationUnitClosure` from `OrganizationUnit.parent` for one organization — disaster recovery / post-import correction, not the normal `move_unit()` path. Flags: `--organization-code` or `--organization-id` (exactly one required), `--dry-run` (preview only), `--force` (required to actually write unless `--dry-run` is passed). |
| `reset_superadmin_password` | `authenticate` | Resets the password of an existing superadmin actor when the original bootstrap password is lost — disaster recovery, not part of the fresh-init sequence above. Reuses `services.set_temporary_password()` so validation, password history, `password_change_required`, and the auth event log follow the same rules as the staff-facing reset endpoint. Refuses to run against a non-superuser account; does not create accounts (use `bootstrap_superadmin` for that). Flags: `--username` (falls back to `SUPERADMIN_USERNAME` env var, then `superadmin`), `--password` (falls back to `SUPERADMIN_PASSWORD` env var; unset is auto-generated and printed once). |
| `reset_dev_data` | `core` | Dev-only teardown tool: deletes all data except the Core Policy Engine registry (`core.policy_engine`, needed for the platform to run and regenerable from `registry.py` via `sync_policy_registry` anyway), so a developer can clear out hoax/test data without losing the permission registry. Also never touches any model that enforces its own append-only protection (e.g. `authenticate.AuthEvent`, `organization.OrganizationEventLog`) — detected generically, not by a hardcoded list. Refuses to run unless `ENVIRONMENT=development`. Clears `authenticate.User` including the superadmin account — re-run `bootstrap_superadmin` afterward. Not part of the fresh-init sequence above. Flags: `--dry-run` (preview row counts only), `--force` (required to actually delete unless `--dry-run` is passed). |

When you add a new management command, add a row here in the same commit (see CLAUDE.md §12).
