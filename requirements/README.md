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
python manage.py seed_document_templates --activate
```

| Command | App | Purpose |
|---------|-----|---------|
| `bootstrap_superadmin` | `authenticate` | Idempotently creates the platform's first superadmin (`authority_type=superadmin`, `is_superuser`), flagged `must_change_password` so the temporary password must be replaced on first login. Needed before anything else, since there are no roles/permissions yet for any other actor to act with. Safe to re-run — returns the existing superadmin instead of duplicating it. Flags: `--username`, `--email`, `--password`, `--display-name` (each falls back to a `SUPERADMIN_*` env var, then a built-in default; an unset password is auto-generated and printed once). |
| `sync_policy_registry` | `core.policy_engine` | Discovers `POLICY_ENDPOINTS` from every installed app's `registry.py` and registers them in the Core Policy Engine. Re-run any time after adding or changing an endpoint's registry entry — idempotent. Flags: `--dry-run` (preview without writing), `--by {human,ai,system}`, `--identifier`. |
| `validate_policy_engine` | `core.policy_engine` | Validates Policy Engine metadata integrity (duplicate permission keys, endpoints missing categories/dependencies, invalid permission-key format, etc.). Flag: `--strict` (exit code 1 on any finding — use this in CI). |
| `export_policy_registry` | `core.policy_engine` | Emits machine-readable artifacts derived from the registry declarations (no database): the canonical registry JSON or an OpenAPI 3.1 document. Not part of fresh-init. Flags: `--format {registry,openapi}` (default `registry`), `--output <path>` (default stdout), `--check` (fail if the committed `docs/registry_export.json`/`docs/openapi.json` has drifted from the registry — used in CI, mirrors `makemigrations --check`). |
| `validate_integration_docs` | `core` | Validates that every app exposing endpoints publishes a consumer-facing `docs/INTEGRATION.md` (`CLAUDE.md` §19.1) whose endpoint inventory matches the registry: no registered endpoint left undocumented, no documented key that no longer exists, all nine required sections present and in order, and the mandatory `Requires`/`Requires state`/`Side effects` depth fields answered. Reads registry declarations only — no database — so it runs in the DB-less CI job (`scripts/ci.sh docs`). Not part of fresh-init. Flag: `--strict` (treat warnings as failures — use this in CI). |
| `validate_organization_integrity` | `organization` | Validates organizational structure integrity: unit-parent cycles, closure-table self-links/depths/organization-consistency, cross-organization references on positions/assignments/reporting lines, reporting-line self-cycles and duplicate active primary administrative lines, position capacity, delegation time windows, and unit-history-to-event-log completeness. Operates on already-existing org data, not a fresh DB — not part of the bootstrap sequence above. Flags: `--dry-run` (accepted for symmetry; this command never writes), `--strict` (exit code 1 on any finding). |
| `rebuild_organization_closure` | `organization` | Rebuilds `OrganizationUnitClosure` from `OrganizationUnit.parent` for one organization — disaster recovery / post-import correction, not the normal `move_unit()` path. Flags: `--organization-code` or `--organization-id` (exactly one required), `--dry-run` (preview only), `--force` (required to actually write unless `--dry-run` is passed). |
| `reset_superadmin_password` | `authenticate` | Resets the password of an existing superadmin when the original bootstrap password is lost — disaster recovery, not part of the fresh-init sequence above. Reuses `services.admin_reset_password()` (actor=None) so it forces a change at next login, revokes the superadmin's sessions, applies strength validation, and writes an `admin_password_reset` auth event — the same rules as the staff-facing reset endpoint. Refuses to run against a non-superadmin account; does not create accounts (use `bootstrap_superadmin` for that). Flags: `--username` (falls back to `SUPERADMIN_USERNAME` env var, then `superadmin`), `--password` (falls back to `SUPERADMIN_PASSWORD` env var; unset is auto-generated and printed once). |
| `reset_superadmin_mfa` | `authenticate` | Deployment-level MFA recovery for a superadmin who has lost their authenticator: removes the superadmin's `django-otp` TOTP device(s) and revokes their sessions so they can log in with password alone and re-enroll. There are no recovery/backup codes by design, so this shell command is the only superadmin MFA recovery path. Refuses to run against a non-superadmin account. Not part of the fresh-init sequence above. Flags: `--username` (falls back to `SUPERADMIN_USERNAME` env var, then `superadmin`). |
| `seed_document_templates` | `document_templates` | Populates the document template catalogue with the 53 template slugs transcribed from the frontend's own contract (`document_templates/seed_data.py`), so the New Document picker has something to offer on a fresh database. Part of fresh-environment initialization — needs `bootstrap_superadmin` first, since `created_by` is a non-null `PROTECT` foreign key. **Idempotent and non-destructive:** an existing row is left completely untouched, including a label an Admin has renamed and a template someone retired, so a re-run never reverts curation. Validates every transcribed slug against `documents`' key/family rule before writing anything. Flags: `--dry-run` (report what would be created; write nothing), `--activate` (create rows as `active` rather than `draft`, so the picker is usable immediately), `--username` (attribute created rows to this user instead of the first superadmin). |
| `apply_country_checklists` | `checklists` | Applies each country's default checklist template to journeys that name that country but hold no checklist. Automatic inheritance (a `post_save` receiver on `ApplicantJourney`) covers every journey saved *after* its country's template was authored; this command covers the three populations it cannot reach — journeys that named their country before anyone wrote its requirements (the common case, since the catalogue fills in over time), journeys written by a bulk import that ran with `DISABLE_SIGNALS`, and journeys whose inheritance failed once and was logged rather than retried. **Idempotent and safe on a live system:** it uses the same existence check the signal does, so a second run is a no-op and no existing checklist is ever touched. Not part of fresh-init — there are no journeys yet on a fresh database. Flags: `--country` (restrict to one catalogue country id; errors if that country has no active default template), `--dry-run` (report what would be created; write nothing), `--limit` (stop after N journeys, for a cautious first pass on a large database). |
| `sweep_notifications` | `notifications` | Raises deadline notifications — overdue and due-soon checklist items, offer response deadlines already passed or approaching, expiring passports, and checklists holding uncollected documents nobody set a date on — and resolves alerts whose source condition has since cleared. **Intended to run nightly from cron**, which is the whole reason it is a command rather than a Celery task: only "must run outside the request cycle" applies, and cron already provides that without a broker, a worker, and a result backend. Reads each owning app's own selectors and never re-implements another app's definition of "overdue". **Idempotent and safe on a live database** — every write goes through `get_or_create` on a `(recipient, dedupe_key)` unique constraint, so a second run in the same minute creates nothing and two concurrent runs race into the database rather than into each other. A generator that fails is logged and audited, the remaining generators still run, and **the failed generator's types are withheld from the resolve pass** so a transient error can never read as "nothing is overdue any more". Not part of fresh-init — there are no deadlines yet on a fresh database. Flags: `--type` (run one generator; the resolve pass is narrowed to match), `--due-within-days` (horizon for due-soon items and offer deadlines, default 7), `--passport-horizon-days` (default 180 — renewing a Nepali passport is not a same-week errand), `--limit` (stop each generator after N source rows, for a cautious first pass; pair with `--no-resolve`, since a truncated run has an incomplete picture of what is still true), `--dry-run` (report and write nothing), `--no-resolve` (raise only). |
| `reset_dev_data` | `core` | Dev-only teardown tool: deletes all data except the Core Policy Engine registry (`core.policy_engine`, needed for the platform to run and regenerable from `registry.py` via `sync_policy_registry` anyway), so a developer can clear out hoax/test data without losing the permission registry. Also never touches any model that enforces its own append-only protection (e.g. `authenticate.AuthEvent`, `organization.OrganizationEventLog`) — detected generically, not by a hardcoded list. Refuses to run unless `ENVIRONMENT=development`. Clears `authenticate.User` including the superadmin account — re-run `bootstrap_superadmin` afterward. Not part of the fresh-init sequence above. Flags: `--dry-run` (preview row counts only), `--force` (required to actually delete unless `--dry-run` is passed). |

When you add a new management command, add a row here in the same commit (see CLAUDE.md §12).
