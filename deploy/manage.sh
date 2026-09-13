#!/usr/bin/env bash
# Run a Grandway manage.py command with the production environment loaded.
#
# Usage (as root or as grandway):
#   /opt/grandway/deploy/manage.sh migrate --noinput
#   /opt/grandway/deploy/manage.sh sync_policy_registry
#   /opt/grandway/deploy/manage.sh validate_policy_engine --strict
#
# It always re-executes itself as the application user. Running manage.py as
# root would create a root-owned /var/log/grandway/app.log at settings import
# (the RotatingFileHandler opens it before any command runs), and every
# gunicorn worker started afterwards would then die with PermissionError on
# that file. See deploy.md §8 (Filesystem contract).
#
# The environment file is the same one systemd loads (EnvironmentFile=), so a
# command here sees exactly what the service sees. Values in the file must be
# shell-safe: quote anything with spaces, no `export`.
#
# Environment overrides: APP_DIR, ENV_FILE, APP_USER.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/grandway}"
ENV_FILE="${ENV_FILE:-/etc/grandway/grandway.env}"
APP_USER="${APP_USER:-grandway}"

if [ "$(id -un)" != "$APP_USER" ]; then
    exec sudo -u "$APP_USER" -H --preserve-env=APP_DIR,ENV_FILE,APP_USER -- "$(readlink -f "$0")" "$@"
fi

if [ -e "$APP_DIR/.env" ]; then
    echo "manage.sh: REFUSING — stray $APP_DIR/.env present. A repo-root .env can override" >&2
    echo "ENVIRONMENT and boot production in development mode. Remove it. See deploy.md §7 (Configuration contract)." >&2
    exit 1
fi

if [ ! -r "$ENV_FILE" ]; then
    echo "manage.sh: cannot read $ENV_FILE (expected root:$APP_USER 0640). See deploy.md §7 (Configuration contract)." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
export ENVIRONMENT=production

cd "$APP_DIR"
exec .venv/bin/python backend/manage.py "$@"
