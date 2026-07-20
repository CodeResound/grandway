#!/usr/bin/env bash
#
# ci.sh — single source of truth for Grandway's mechanical enforcement.
#
# This mirrors the checks that the .claude/hooks/* scripts run during an
# interactive Claude Code session, so the same gates apply in CI (GitHub Actions)
# and to any developer who runs them locally. The .claude protocol *guides* the
# AI; this script *enforces* the project regardless of who (or what) made the
# change. See CLAUDE.md §1, §18, §33, §35.
#
# Usage:
#   scripts/ci.sh                 # run all stages (lint, export, policy, test)
#   scripts/ci.sh lint            # run only the lint stage
#   scripts/ci.sh lint export     # run a subset, in the order given
#   scripts/ci.sh policy          # run only the policy-engine stage
#
# Stages:
#   lint    — ruff check + ruff format --check on backend/ (non-mutating)
#   export  — export_policy_registry --check for the registry + OpenAPI artifacts;
#             fails if backend/core/policy_engine/docs/{registry_export,openapi}.json
#             have drifted from the registry declarations. Pure registry read, no
#             database (uses core.settings.testing for a clean import).
#   test    — pytest (core.settings.testing, in-memory SQLite). Needs NO database
#             service. Add a Postgres-backed test settings module if you introduce
#             Postgres-only features (e.g. pg_trgm indexes) later.
#   policy  — migrate -> sync_policy_registry -> validate_policy_engine --strict.
#             Runs as three separate manage.py processes, so it needs a *persistent*
#             database (in-memory SQLite cannot be shared across processes) —
#             a reachable PostgreSQL.
#
# Only the `policy` stage needs a reachable PostgreSQL: supply DB_* + SECRET_KEY
# via the environment (CI) or a local .env.development file. The `lint`, `export`,
# and `test` stages run without a database.
#
# Run from the repository root. Uses `python`/`ruff`/`pytest` from PATH — in CI
# they are installed into the system environment; locally, activate your .venv
# first (source .venv/bin/activate).

set -euo pipefail

# Resolve repo root as this script's parent directory's parent, then cd there so
# the command works no matter where it is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

run_lint() {
    echo "==> [lint] ruff check backend"
    ruff check backend
    echo "==> [lint] ruff format --check backend"
    ruff format --check backend
}

run_test() {
    echo "==> [test] pytest (SQLite, core.settings.testing)"
    pytest
}

run_export() {
    # Generated policy artifacts must stay in sync with the registry declarations.
    # Pure registry read — no database — so it uses the SQLite testing settings
    # (which provide SECRET_KEY/DB defaults for a clean import) and runs in the
    # DB-less lint job. Mirrors `makemigrations --check`.
    echo "==> [export] export_policy_registry --format registry --check"
    python backend/manage.py export_policy_registry --format registry --check --settings=core.settings.testing
    echo "==> [export] export_policy_registry --format openapi --check"
    python backend/manage.py export_policy_registry --format openapi --check --settings=core.settings.testing
}

run_policy() {
    echo "==> [policy] manage.py migrate"
    python backend/manage.py migrate --noinput
    echo "==> [policy] manage.py sync_policy_registry"
    python backend/manage.py sync_policy_registry
    echo "==> [policy] manage.py validate_policy_engine --strict"
    python backend/manage.py validate_policy_engine --strict
}

# Default to all stages, in a fail-fast order (cheap lint/export first, tests last).
if [ "$#" -eq 0 ]; then
    stages="lint export policy test"
else
    stages="$*"
fi

for stage in $stages; do
    case "$stage" in
        lint) run_lint ;;
        export) run_export ;;
        test) run_test ;;
        policy) run_policy ;;
        *)
            echo "Unknown stage: '$stage' (valid: lint, export, test, policy)" >&2
            exit 2
            ;;
    esac
done

echo "==> ci.sh: all requested stages passed"
