# Grandway — Deployment Guide (v1.1.0, 2026-09-13)

This is the deployer contract for Grandway, written for an autonomous deployer agent — or an engineer — who has **no access to the source** and must deploy the application and then operate it. The target is a **single Ubuntu 24.04 LTS VPS**: bare metal or a VM, systemd, no containers, no cloud services. It is refreshed at every release; a release whose `deploy.md` does not match the tagged code is incomplete. Companion files, all under `deploy/` in the release: `env.production.example` (every variable, annotated), `gunicorn.conf.py` (application server config), `nginx.sample.conf` (reverse proxy), `grandway.service` (application unit), `grandway-sweep.service` + `grandway-sweep.timer` (nightly notification sweep), `grandway-backup.service` + `grandway-backup.timer` (nightly backup), `backup.sh` (snapshot script), `manage.sh` (runs `manage.py` with the production environment, as the right user), and `crontab.sample` (cron fallback for the sweep). Conventions: commands are in fenced `bash` blocks and run **as root** from a fresh shell unless a `sudo -u grandway` prefix says otherwise; the shell variables exported once at the end of §1 (Deployer inputs) are reused by every later command, so re-export them in any new shell before continuing.

## 1. Deployer inputs

Everything below must be known before §5 (Host provisioning). Where a value is unknown, escalate as noted — do not guess.

| Input | Example | Used in | Escalate if unknown |
|---|---|---|---|
| `TAG` — the release tag to deploy | `v1.0.0` | §6, §15, §16 | Yes. Must equal `v` + the `VERSION` file in that tag; §6 verifies. |
| `REPO_URL` — the git repository | `https://github.com/CodeResound/grandway.git` | §6 | Yes, plus credentials (deploy key or token) if the repository is private. |
| `DOMAIN` — the API hostname, becomes `ALLOWED_HOSTS` | `admin.grandwayeducation.com` (the value in `deploy/env.production.example`) | §7, §9, every probe | Yes. Without it every request on the real hostname returns 400. |
| `FRONTEND_ORIGIN` — the browser origin(s) of the frontend, becomes `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` | `https://admin.grandwayeducation.com` (same origin as the API), or a separate `https://app.example.com` | §7 | Yes. A wrong value fails visibly in the browser, not at boot. Comma-separate several. |
| `NUM_PROXIES` — reverse-proxy hop count | `1` (nginx only, this guide); `2` behind a CDN | §7, §9 | Yes if anything sits in front of nginx. Drives both rate limiting and login lockout. |
| `EMAIL` — TLS contact for Let's Encrypt | `ops@example.com` | §9 | Yes. |
| `SUPERADMIN_USERNAME` / `SUPERADMIN_EMAIL` / `SUPERADMIN_DISPLAY_NAME` | `superadmin` / `admin@example.com` / `System Administrator` | §12 | Username defaults to `superadmin` if unset; email and display name default to empty / the username. |
| A human channel for two one-time secrets | a password manager share, a phone call | §12 | Yes. The temporary password and the TOTP secret are printed once and never recoverable; the agent must hand them to a human and must not persist them. |
| Off-host backup destination | `rsync` target, object-storage bucket the operator already owns | §17 | No — the on-host backup works without it, but the host is then a single point of loss. Record as open in §22 (Gaps). |
| Maintenance window, in Nepal time | `Sat 22:00–23:00 NPT` | §16, §21 | No, but MINOR upgrades wait for it and migrations flagged in release notes run only inside it. |
| Sizing | 2 vCPU / 4 GB is enough for a consultancy office; workers default to `cpu*2+1` (`deploy/gunicorn.conf.py` line 27) | §10 | No. |

Export the inputs once; every later block reads them. `DEVICE_ID` is a fixed, opaque string this agent will use for every scripted login — see §12 for why it must not change between logins.

```bash
export TAG="v1.0.0"
export REPO_URL="https://github.com/CodeResound/grandway.git"
export DOMAIN="admin.grandwayeducation.com"
export FRONTEND_ORIGIN="https://admin.grandwayeducation.com"
export EMAIL="ops@example.com"
export NUM_PROXIES="1"
export SUPERADMIN_USERNAME="superadmin"
export SUPERADMIN_EMAIL="admin@example.com"
export SUPERADMIN_DISPLAY_NAME="System Administrator"
export DEVICE_ID="deployer-agent-01"
```

## 2. System overview

Grandway is an internal operating system for an education consultancy in Nepal that helps people pursue study opportunities abroad. It tracks the applicant lifecycle from first enquiry, through lead follow-up and applicant profiling, to study planning, document preparation, offer tracking, and the outcome of each applicant's journey — one accountable source of truth replacing spreadsheets, paper files, and chat threads, with enough history to explain how every record reached its current state (`concepts/project_overview.txt`).

**Actors.** Three authority levels: `superadmin` (created once by a shell command, manages admins), `admin` (manages lead managers and owns every Admin-only module), and `lead_manager` (scoped to leads they created). There is no self-registration, invitation, or forgot-password flow; accounts are provisioned by the tier above (`authenticate/docs/INTEGRATION.md` §1).

**Surface.** The application is API-only. `core/urls.py` routes exactly four prefixes: `/admin/` (Django's admin, OTP-gated — an account without a confirmed TOTP device cannot enter it at all, `core/apps.py`), `/health/` and `/ready/` (public probes), and `/api/v1/` (the API, **180 registered endpoints** per `backend/core/policy_engine/docs/registry_export.json` `endpoint_count`). Nothing else exists — in particular no URL serves uploaded files.

**App inventory** (`backend/core/docs/INTEGRATION.md` §6):

| App | Base path | One line |
|---|---|---|
| `authenticate` | `/api/v1/auth/` | Login (+ TOTP MFA), session-bound JWT, revocable device sessions (max 3), forced first-login password change, account management. |
| `audit` | `/api/v1/audit/` | Central immutable cross-app activity log; read-only over HTTP. |
| `core.policy_engine` | `/api/v1/policy/` | Read-only registry of every endpoint: permission keys, risk levels, dependencies, versions, change log. |
| `leads` | `/api/v1/leads/` | Enquiry tracking before conversion; owner-scoped; Admin-only conversion into an applicant + journey. |
| `applicants` | `/api/v1/applicants/` | The permanent identity record of a person: passport, contacts, family, standing. Shared. |
| `applicant_journeys` | `/api/v1/journeys/` | One overseas-study objective of one applicant: destination, intake, nine-stage lifecycle. |
| `institutions` | `/api/v1/catalogue/` | Countries, providers, campuses, programs; write Admin-only; nothing deleted. |
| `clients` | `/api/v1/clients/` | B2B partner directory (agencies, schools, companies). |
| `documents` | `/api/v1/documents/` | Editable document working record; Admin-only, reads included; archived, never deleted. |
| `document_history` | `/api/v1/document-history/` | Immutable print snapshots and print events; no update or delete routes. |
| `document_templates` | `/api/v1/document-templates/` | Signatory library and template catalogue; signature images stored via `uploaded_files`. |
| `uploaded_files` | `/api/v1/files/` | The file ledger — the only place bytes are stored; private; nothing deleted. |
| `offers` | `/api/v1/offers/` | Institutions' admission decisions against journeys, with immutable snapshots. |
| `dashboards` | `/api/v1/dashboard/` | Read-only operational summaries derived live; owns no table. |
| `checklists` | `/api/v1/checklists/` | Per-country requirement templates and each applicant's own copy. |
| `notifications` | `/api/v1/notifications/` | Per-person in-app alert inbox; deadlines raised by the nightly sweep. |
| `reminders` | `/api/v1/reminders/` | Staff-set one-off follow-up reminders; raised to Admins by the sweep. |
| `search` | `/api/v1/search/` | One global search across nine record types; rate-limited separately. |

**Sources of truth.** Exactly two: the PostgreSQL database and `MEDIA_ROOT`. Redis holds only rate-limit counters and is derived and rebuildable — losing it costs throttle state and nothing else (`backend/core/settings/base.py` lines 151–177).

**Auth mechanics an operator sees** (`base.py` lines 331–373, `authenticate/docs/INTEGRATION.md` §3): a 15-minute Bearer access JWT; an opaque refresh credential delivered in production as the cookie `grandway_refresh` on path `/api/v1/auth/`, `Secure; HttpOnly; SameSite=Lax`; at most 3 active devices per user; sessions expire after 12 h idle or 7 days absolute. Password hashing is Argon2id with a 12-character minimum. django-axes locks after 5 failures for 15 minutes, **independently on username or IP** (`base.py` lines 207–209) — relevant when scripting login attempts.

**Throttle rates** (`base.py` lines 314–328; counters live in Redis):

| Scope | Rate | Applies to |
|---|---|---|
| `anon` | 100/hour | any unauthenticated request |
| `user` | 1000/hour | any authenticated request |
| `auth_login_ip` | 20/minute | `POST /api/v1/auth/login/` per IP |
| `auth_login_user` | 10/minute | `POST /api/v1/auth/login/` per username |
| `auth_refresh` | 60/minute | `POST /api/v1/auth/refresh/` per IP |
| `search_query` | 60/minute | `/api/v1/search/` per user |

Exceeding one returns `RATE_LIMIT_EXCEEDED` (429). `/health/` and `/ready/` are exempt.

**Uploads.** One file per request (`DATA_UPLOAD_MAX_NUMBER_FILES = 1`, `base.py` line 284); the application's own cap is `MAX_UPLOAD_BYTES = 10 * 1024 * 1024` = 10,485,760 bytes (`backend/uploaded_files/constants.py` line 163). nginx's `client_max_body_size 25m` sits above that with headroom for multipart overhead.

**Time.** The database stores UTC (`TIME_ZONE = "UTC"`, `base.py` line 235). Business days, deadlines, and the nightly sweep are Nepal time (`Asia/Kathmandu`, UTC+05:45): "02:15 NPT" is 20:30 UTC.

**External contracts.** Outbound: **none** — no email backend, no HTTP clients, no third-party APIs at runtime. Inbound: the browser frontend at `FRONTEND_ORIGIN`, and the probes. Machine-readable artifacts shipped with each release: `registry_export.json` (the endpoint registry), `openapi.json` (OpenAPI 3.1), and `registry_schema.json` (the schema the first two are read with).

**Sensitive data classes.** Applicant passports, transcripts, and bank statements live under `MEDIA_ROOT` (`base.py` lines 249–252); staff signature images are stored beside them. Treat the media volume and every backup of it as personal data.

## 3. Module

| | |
|---|---|
| Entrypoint | `core.wsgi:application` (WSGI). An ASGI entrypoint exists at `core.asgi:application` (`base.py` line 137) but no ASGI server is pinned and no async views exist — use WSGI. |
| Working directory | The Django project lives under `backend/`; `core` is importable only from there, so the server must `--chdir backend` (`deploy/gunicorn.conf.py` lines 3–7). |
| Invocation | `gunicorn --chdir backend --config deploy/gunicorn.conf.py core.wsgi:application` |
| Runtime | Python 3.12 (`ruff.toml` `target-version = "py312"`; the project's own virtualenv runs 3.12.3). |
| Framework | `Django==5.2.17`, `djangorestframework==3.17.2`, `psycopg[binary]==3.2.13` (`requirements/base.txt`); `gunicorn==23.0.0` (`requirements/production.txt`). |
| API prefix | `/api/v1/` |
| Version at runtime | `GET /health/` returns `{"status":"ok","version":"1.0.0"}` (`backend/core/views.py` line 20). The value is read from the repo-root `VERSION` file (`backend/core/__init__.py` lines 13–16) and always equals the release tag without its `v`. |

**Deploy the whole clone.** If the `VERSION` file is missing — an installed copy of `backend/` without the repository root — `core.__version__` falls back to `0.0.0+unknown` (`backend/core/__init__.py` line 18) and `/health/` reports that. §6 (Obtaining a release) deploys the full checkout precisely so this never happens; a host reporting `0.0.0+unknown` is misdeployed.

## 4. Runtime requirements

**PostgreSQL 16 — REQUIRED, not a preference.** The application uses `django.contrib.postgres` and `pg_trgm` GIN indexes for substring search across nine record types; SQLite cannot run it. The `pg_trgm` extension is created by three migrations — `applicants/0001_initial` (`TrigramExtension()` line 29), `leads/0002_pg_trgm_lead_name_search` (line 25), and `audit/0002_audit_summary_search` (line 27) — all idempotent (`CREATE EXTENSION IF NOT EXISTS`). Whichever runs first needs the database user to be allowed to create the extension. On PostgreSQL 13+ `pg_trgm` is a *trusted* extension, so a database owner can create it without superuser rights; §5 (Host provisioning) nevertheless pre-creates it as `postgres` so the first `migrate` has nothing to prove. Keep `listen_addresses` at its localhost default; the application connects over the loopback.

**Redis — REQUIRED for any multi-worker deployment.** DRF throttle counters live in the Django cache. With the per-process `LocMemCache` every rate limit is silently multiplied by the worker count and resets on restart, so production settings **refuse to boot** on `LocMemCache` unless `THROTTLE_SINGLE_WORKER=true` is set as an explicit acknowledgement of a one-worker deploy (`backend/core/settings/production.py` lines 56–66). Use Ubuntu's `redis-server` package (7.x on 24.04 — **verify on host** with `redis-server --version`), bound to the loopback, database `1`, with `maxmemory 64mb` and `maxmemory-policy noeviction`. Rationale for `noeviction`: the counters are a few bytes each with TTLs of at most one hour, so 64 MB never fills in practice; if it ever does, `noeviction` makes that loud (write errors in the journal) instead of an eviction policy silently discarding counters and loosening rate limits. Redis is a derived store: no persistence and no backup are needed. The `redis` Python client the `RedisCache` backend imports is pinned in `requirements/production.txt`.

**Explicitly NOT required — do not provision:** no message broker (the one scheduled job is a management command on a timer, deliberately not Celery); no object storage (file bytes live on a local volume, §8); no outbound network access at runtime (no email, no third-party APIs).

**Dependency caveats** (also listed in §22 Gaps):

- There is no lock file and no hashes. `requirements/*.txt` pins direct dependencies exactly, but transitive dependencies resolve fresh at install time, so a deploy-day install may not match what CI tested. Mitigation on a single host: install once per release and do not re-run `pip install` casually; keep the previous virtualenv until §15 (Verification checklist) passes.
- `requirements/base.txt` pins `psycopg[binary]`. psycopg's own documentation recommends `psycopg[c]` or a system build for production; `[binary]` bundles its own libpq. Left as-is for 1.0.0 because changing it requires build tooling on the host.

## 5. Host provisioning

In order, on a fresh Ubuntu 24.04 LTS host, as root. Every step is idempotent.

**Packages.** `python3.12 --version` is the only Python version enforcement that exists anywhere; the venv in §6 is created with `python3.12` explicitly.

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3.12 python3.12-venv git nginx certbot postgresql-16 redis-server ufw
python3.12 --version
```

**Service user.** A system account with no login shell; its home is the checkout.

```bash
id grandway 2>/dev/null || useradd --system --home /opt/grandway --shell /usr/sbin/nologin grandway
```

**Directories.** Fixed layout (§8 Filesystem contract has the full rationale).

| Path | Owner | Mode | Purpose |
|---|---|---|---|
| `/opt/grandway` | `grandway:grandway` | `0755` | the git checkout at `$TAG`, and `.venv/` inside it |
| `/etc/grandway` | `root:grandway` | `0750` | holds the one env file |
| `/var/www/grandway/static` | `grandway:grandway` | `0755` | `STATIC_ROOT`; served by nginx |
| `/var/lib/grandway/media` | `grandway:grandway` | `0750` | `MEDIA_ROOT`; never web-served |
| `/var/log/grandway` | `grandway:grandway` | `0750` | `LOG_DIR` |
| `/var/www/certbot` | `www-data:www-data` | `0755` | ACME webroot |
| `/var/backups/grandway` | `root:root` | `0700` | backups |

```bash
install -d -o grandway -g grandway -m 0755 /opt/grandway
install -d -o root     -g grandway -m 0750 /etc/grandway
install -d -o grandway -g grandway -m 0755 /var/www/grandway/static
install -d -o grandway -g grandway -m 0750 /var/lib/grandway/media
install -d -o grandway -g grandway -m 0750 /var/log/grandway
install -d -o www-data -g www-data -m 0755 /var/www/certbot
install -d -o root     -g root     -m 0700 /var/backups/grandway
```

**`www-data` must NOT be in group `grandway`.** Media files are written `0640` inside `0750` directories (`base.py` lines 279–280), so group membership is read access to every applicant passport. nginx reads static files through the world bits, which is why `collectstatic` writes them `0644` inside `0755` directories and not with the upload modes above (`STORAGES` in `base.py`; the `0755` on `/var/www/grandway/static` itself covers only that one directory, not the tree `collectstatic` creates beneath it). Keeping nginx out of the group means that even a mistaken `alias /var/lib/grandway/media/` in a future nginx edit serves permission-denied, not documents. Verify: `id www-data` must not list `grandway`.

**PostgreSQL.** Generate the password now and keep it for §7.

```bash
export DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE grandway LOGIN PASSWORD '$DB_PASSWORD';" \
  -c "CREATE DATABASE grandway OWNER grandway ENCODING 'UTF8';"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d grandway \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
runuser -u postgres -- psql -tAc "SHOW listen_addresses;"   # expected: localhost
```

If the role already exists (a re-run), `CREATE ROLE` fails with `role "grandway" already exists`; use `ALTER ROLE grandway WITH PASSWORD '...'` instead and keep the password you set.

**Redis.** Loopback only (Ubuntu's default `bind 127.0.0.1 -::1`), bounded memory, no eviction.

```bash
sed -i -E 's/^#? ?maxmemory .*/maxmemory 64mb/; s/^#? ?maxmemory-policy .*/maxmemory-policy noeviction/' /etc/redis/redis.conf
grep -Eq '^maxmemory 64mb$' /etc/redis/redis.conf || echo 'maxmemory 64mb' >> /etc/redis/redis.conf
grep -Eq '^maxmemory-policy noeviction$' /etc/redis/redis.conf || echo 'maxmemory-policy noeviction' >> /etc/redis/redis.conf
systemctl enable --now redis-server
systemctl restart redis-server
redis-cli config get maxmemory-policy      # expected: maxmemory-policy / noeviction
redis-cli config get bind                  # expected: 127.0.0.1 -::1 (loopback only)
```

**Firewall.** SSH and HTTP/HTTPS only. gunicorn (8000), PostgreSQL (5432), and Redis (6379) stay on the loopback and are never opened.

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
ufw status
```

**Clock.** TOTP codes are valid only within a 30-second window (`authenticate/docs/INTEGRATION.md` §3). A host clock drifting by more than that rejects every authenticator code, including the superadmin's, which looks exactly like a lost authenticator. Keep NTP on.

```bash
timedatectl set-ntp true
timedatectl status | grep -E 'System clock synchronized|NTP service'   # expected: yes / active
```

## 6. Obtaining a release

Releases are obtained by **git checkout of the tag** into `/opt/grandway`, as the `grandway` user. Never run `git` in that tree as root: root-owned objects under `.git/` make every later `fetch` by `grandway` fail with permission errors.

```bash
test -d /opt/grandway/.git || sudo -u grandway -H git clone "$REPO_URL" /opt/grandway
sudo -u grandway -H git -C /opt/grandway fetch --tags --quiet
sudo -u grandway -H git -C /opt/grandway checkout -q "$TAG"
test "$(git -C /opt/grandway describe --tags --exact-match)" = "$TAG" || { echo "ABORT: HEAD is not $TAG"; exit 1; }
test "$(cat /opt/grandway/VERSION)" = "${TAG#v}" || { echo "ABORT: VERSION file $(cat /opt/grandway/VERSION) != ${TAG#v}"; exit 1; }
```

**Virtualenv** — created once, inside the checkout, as `grandway`, with `python3.12` explicitly:

```bash
test -x /opt/grandway/.venv/bin/python || sudo -u grandway -H python3.12 -m venv /opt/grandway/.venv
sudo -u grandway -H /opt/grandway/.venv/bin/python --version    # expected: Python 3.12.x
```

**What the clone contains:** `backend/` (the application), `deploy/` (everything this guide installs), `requirements/`, `VERSION`, `deploy.md`, `CHANGELOG.md`, `README.md`, `concepts/` and `docs/` (design documents, not needed at runtime), `.github/` and `.githooks/` (CI and developer hooks — irrelevant on a host). **What it never contains:** `.claude/` (gitignored), `.venv/`, `logs/`, any `.env*` file, `backend/staticfiles/`, `backend/mediafiles/`. A checkout therefore cannot carry a stray `.env` (§7); `.venv/` and `logs/` are gitignored and untouched by `git checkout`.

**Release artifacts** attached to the GitHub release are for reading *before* touching the host and are identical to files in the tag: `deploy.md` (this file), `deploy/env.production.example`, `registry_export.json`, `openapi.json`, `registry_schema.json`. Fetch this guide ahead of provisioning with `gh release download "$TAG" -p deploy.md` (or from the release page). **Tarballs are not supported for upgrades**: a tarball has no `.git`, so `git describe` cannot verify the tag and §16 (Upgrade sequence) cannot `fetch`.

## 7. Configuration contract

**How the environment is selected.** `backend/core/settings/__init__.py` reads `ENVIRONMENT` from the **process environment** (line 10) *before* any env file is opened. Only if it is unset does it look at a repo-root `.env` (lines 14–21). Then, with no valid value, the process fails closed (lines 55–58):

```
ImproperlyConfigured: ENVIRONMENT is unset or invalid (got None). Set ENVIRONMENT to one of production/staging/development/testing in the process environment or the repo-root .env; settings no longer fall back to development.
```

That is correct behaviour and the most common day-one failure. Production settings then read the rest of the configuration from `<repo>/.env.production` **if that file exists**, otherwise from the OS environment only (`production.py` lines 11–16) — never from a generic `.env`.

**The stray-`.env` trap.** If `ENVIRONMENT` is unset *and* a repo-root `.env` exists, its value is used. A developer's `.env` says `ENVIRONMENT=development`, and a production host in that state boots **silently in development mode** — `DEBUG=True`, no HTTPS redirect, no HSTS, no secure cookies, stack traces to clients — with no error and no warning. The guard at `__init__.py` lines 35–42 refuses that combination **only when `.env.production` is also present**:

```
ImproperlyConfigured: Refusing to boot: ENVIRONMENT is unset, so the repo-root .env selected 'development' — but .env.production is also present, so this host is meant to serve production. Booting would silently enable DEBUG and disable the HTTPS redirect, HSTS, and secure cookies. Export ENVIRONMENT=production in the process environment, and remove the stray .env (see deploy.md §7 (Configuration contract)).
```

This deployment ships **no** `.env.production`, so that guard never fires here; the defence is that `ENVIRONMENT` is always in the process environment, and that step 0 of §11 (Deploy sequence) and `deploy/manage.sh` refuse to run when `/opt/grandway/.env` exists.

**The one-file rule (D1).** All configuration lives in **one file, loaded into the process environment**: `/etc/grandway/grandway.env`, owned `root:grandway`, mode `0640`. systemd loads it with `EnvironmentFile=` in every unit; `deploy/manage.sh` loads it with `set -a; . file; set +a`. There is no repo-root `.env` and no `.env.production`. This works because python-decouple consults `os.environ` first, so a value in the process environment always wins over any file. It is also the only way to deliver `SUPERADMIN_*` and `GUNICORN_*`, which are read straight from `os.environ` (`bootstrap_superadmin.py` lines 52–54 and 84, `reset_superadmin_*.py`, `deploy/gunicorn.conf.py` lines 17, 27, 34, 57) and would never see an env file. Precedence note: systemd applies `EnvironmentFile=` *after* `Environment=`, so the `Environment=ENVIRONMENT=production` in the units is a floor, not an override — the file must itself say `ENVIRONMENT=production`, and §15 checks it with `grep`. Values must be shell-, systemd- and decouple-safe: `KEY=value`, quote anything with spaces, no `export`, no `$`.

**Variables.** "Read from" is *where the code actually looks*: `config()` (python-decouple: process environment, then `.env.production` if present) or `os.environ` only.

| Variable | Required | Default | Read by | Read from | What breaks without it |
|---|---|---|---|---|---|
| `ENVIRONMENT` | yes | — | `settings/__init__.py` | process env (then repo-root `.env`) | refuses to boot: `ENVIRONMENT is unset or invalid` |
| `SECRET_KEY` | yes | — | `base.py` line 35 (Django signing) and line 341 (JWT signing) | `config()` | refuses to boot: `UndefinedValueError: SECRET_KEY not found. Declare it as envvar or define a default value.` Rotating it logs every user out. |
| `DB_NAME` | yes | — | `base.py` line 142 | `config()` | refuses to boot: `UndefinedValueError: DB_NAME not found. …` |
| `DB_USER` | yes | — | `base.py` line 143 | `config()` | refuses to boot (same form) |
| `DB_PASSWORD` | yes | — | `base.py` line 144 | `config()` | refuses to boot (same form) |
| `ALLOWED_HOSTS` | yes | — (no production default) | `production.py` line 42 | `config()` | refuses to boot; if wrong, every request on the real hostname is 400 `DisallowedHost` |
| `CORS_ALLOWED_ORIGINS` | yes | — | `production.py` line 98 | `config()` | refuses to boot; if wrong, the browser cannot call the API or send the refresh cookie |
| `CSRF_TRUSTED_ORIGINS` | yes | — | `production.py` line 100 | `config()` | refuses to boot; if wrong, `/admin/` form posts fail CSRF |
| `CACHE_BACKEND` | yes | — | `production.py` line 56 | `config()` | refuses to boot; if `locmem` without `THROTTLE_SINGLE_WORKER=true`: `ImproperlyConfigured: CACHE_BACKEND is LocMemCache: rate limits are per-process and reset on restart. Set a shared cache backend, or set THROTTLE_SINGLE_WORKER=true to acknowledge a single-worker deployment.` |
| `DB_HOST` | no | `localhost` | `base.py` line 145 | `config()` | — |
| `DB_PORT` | no | `5432` | `base.py` line 146 | `config()` | — |
| `DB_CONN_MAX_AGE` | no | `60` | `base.py` line 147 | `config()` | seconds a connection is reused; raise only behind a pooler |
| `NUM_PROXIES` | no | `0` | `base.py` line 97 → DRF throttles and django-axes | `config()` | must be `1` here; `0` makes every client look like nginx, so one attacker locks out everybody; too high trusts a client header |
| `CACHE_LOCATION` | no | `grandway-default` | `base.py` line 175 | `config()` | must be `redis://127.0.0.1:6379/1` with `RedisCache`; the default is a LocMem name and fails to parse as a URL |
| `THROTTLE_SINGLE_WORKER` | no | `false` | `production.py` line 57 | `config()` | escape hatch for a one-worker LocMem deploy; never set here |
| `LOG_DIR` | no | `<repo>/logs` | `base.py` line 23 | `config()` | must be `/var/log/grandway`; created at settings import, `ImproperlyConfigured: LOG_DIR (…) could not be created` if it cannot be |
| `STATIC_ROOT` | no | `<repo>/backend/staticfiles` | `base.py` line 244 | `config()` | must be `/var/www/grandway/static` (what nginx serves) |
| `MEDIA_ROOT` | no | `<repo>/backend/mediafiles` | `base.py` line 274 | `config()` | must be `/var/lib/grandway/media` (outside any web root) |
| `AUTH_SESSION_IDLE_HOURS` | no | `12` | `base.py` line 353 | `config()` | — |
| `AUTH_SESSION_ABSOLUTE_DAYS` | no | `7` | `base.py` line 354 | `config()` | — |
| `AUTH_MAX_ACTIVE_DEVICES` | no | `3` | `base.py` line 355 | `config()` | — |
| `AUTH_SESSION_LAST_USED_MINUTES` | no | `5` | `base.py` line 363 | `config()` | — |
| `AXES_FAILURE_LIMIT` | no | `5` | `base.py` line 207 | `config()` | — |
| `AXES_COOLOFF_MINUTES` | no | `15` | `base.py` line 208 | `config()` | — |
| `JWT_ISSUER` | no | `grandway` | `base.py` line 342 | `config()` | — |
| `JWT_AUDIENCE` | no | `grandway-api` | `base.py` line 343 | `config()` | — |
| `OTP_TOTP_ISSUER` | no | `Grandway` | `base.py` line 232 | `config()` | label in the operator's authenticator app |
| `GUNICORN_BIND` | no | `127.0.0.1:8000` | `gunicorn.conf.py` line 17 | **`os.environ` only** | must stay on the loopback |
| `GUNICORN_WORKERS` | no | `cpu*2+1` | `gunicorn.conf.py` line 27 | **`os.environ` only** | — |
| `GUNICORN_TIMEOUT` | no | `60` | `gunicorn.conf.py` line 34 | **`os.environ` only** | coupled to nginx `proxy_read_timeout` (§9) |
| `GUNICORN_LOG_LEVEL` | no | `info` | `gunicorn.conf.py` line 57 | **`os.environ` only** | — |
| `SUPERADMIN_USERNAME` | first boot only | `superadmin` | `bootstrap_superadmin.py` line 52, `reset_superadmin_*.py` | **`os.environ` only** | — |
| `SUPERADMIN_EMAIL` | first boot only | `""` | `bootstrap_superadmin.py` line 53 | **`os.environ` only** | — |
| `SUPERADMIN_DISPLAY_NAME` | first boot only | the username | `bootstrap_superadmin.py` line 54 | **`os.environ` only** | — |
| `SUPERADMIN_PASSWORD` | **leave unset** | generated | `bootstrap_superadmin.py` line 84 | **`os.environ` only** | if set, the temporary password is whatever you put in a file; unset → generated and printed once |
| `DJANGO_SETTINGS_MODULE` | **must be unset** or `core.settings` | — | `settings/__init__.py` line 8 | process env | any other value bypasses environment selection entirely |

**Explicitly NOT variables** — setting them does nothing: `DEBUG` (production hardcodes `DEBUG = False`, `production.py` line 20; no settings module reads a `DEBUG` variable) and `DISABLE_SIGNALS` (a constant in `base.py` line 81, not a `config()` read).

**Secret one-liners.**

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(50))'   # SECRET_KEY (shell-safe alphabet)
python3 -c 'import secrets; print(secrets.token_urlsafe(24))'   # DB_PASSWORD
```

`token_urlsafe` is used instead of Django's `get_random_secret_key()` because Django's alphabet includes `#$%^&*()`, which break a file that is sourced by a shell (`#` starts a comment, `$` expands).

**Install the env file.** The template is `deploy/env.production.example` (every variable, annotated in the same order as this table). Substitute the §1 inputs, then install with the exact ownership and mode:

```bash
SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" \
    -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$DB_PASSWORD|" \
    -e "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=$DOMAIN|" \
    -e "s|^CORS_ALLOWED_ORIGINS=.*|CORS_ALLOWED_ORIGINS=$FRONTEND_ORIGIN|" \
    -e "s|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=$FRONTEND_ORIGIN|" \
    -e "s|^NUM_PROXIES=.*|NUM_PROXIES=$NUM_PROXIES|" \
    -e "s|^# SUPERADMIN_USERNAME=.*|SUPERADMIN_USERNAME=$SUPERADMIN_USERNAME|" \
    -e "s|^# SUPERADMIN_EMAIL=.*|SUPERADMIN_EMAIL=$SUPERADMIN_EMAIL|" \
    -e "s|^# SUPERADMIN_DISPLAY_NAME=.*|SUPERADMIN_DISPLAY_NAME=\"$SUPERADMIN_DISPLAY_NAME\"|" \
    /opt/grandway/deploy/env.production.example > /root/grandway.env.tmp
install -m 0640 -o root -g grandway /root/grandway.env.tmp /etc/grandway/grandway.env
shred -u /root/grandway.env.tmp
unset SECRET_KEY
grep -q '^ENVIRONMENT=production$' /etc/grandway/grandway.env && grep -c 'CHANGE-ME' /etc/grandway/grandway.env   # expected: 0
( set -a; . /etc/grandway/grandway.env; set +a; echo "parsed OK" )                                                    # expected: parsed OK
```

`SUPERADMIN_*` are uncommented here for §12 (First-boot bootstrap) and removed again at the end of it.

## 8. Filesystem contract

Every path, who owns it, and what happens when it is wrong.

| Path | Variable | Owner | Mode | Created by | If it cannot be written |
|---|---|---|---|---|---|
| `/opt/grandway` | — | `grandway` | `0755` | §5 + `git clone` | checkout/upgrade fails |
| `/opt/grandway/.venv` | — | `grandway` | `0755` | §6 `python3.12 -m venv` | `pip install` fails |
| `/etc/grandway/grandway.env` | — | `root:grandway` | `0640` | §7 | units fail to start: `Failed to load environment files` |
| `/var/www/grandway/static` | `STATIC_ROOT` | `grandway` | `0755`, and `0644`/`0755` within | §5; filled by `collectstatic` | `collectstatic` fails; if empty, `/admin/` renders unstyled; if not world-readable, nginx 403s every asset |
| `/var/lib/grandway/media` | `MEDIA_ROOT` | `grandway` | `0750` | §5 | every upload returns 500; nothing else degrades |
| `/var/log/grandway` | `LOG_DIR` | `grandway` | `0750` | §5 (settings import also tries `mkdir -p`) | **every process exits at import** with `ImproperlyConfigured: LOG_DIR (/var/log/grandway) could not be created: …` (`base.py` lines 23–33) |
| `/var/log/grandway/app.log` | — | `grandway` | `0640` | the first process that imports settings | see the root-ownership trap below |
| `/var/backups/grandway` | — | `root` | `0700` | §5 | `backup.sh` fails |

**STATIC_ROOT** is public by design — nginx serves it at `/static/` (§9). Nothing in Django serves it with `DEBUG=False`; its only consumer is the admin. Its contents must be **world-readable** (`0644` files in `0755` directories): nginx runs as `www-data`, which is in neither the owner nor the group (§5), so the world bits are the only ones it has. `collectstatic` sets these itself — the modes come from `STORAGES` in the settings, deliberately separate from the `0640`/`0750` that protect `MEDIA_ROOT` — so no `chmod` is needed on a fresh host. If the tree is ever left owner-and-group-only, every `/static/` request returns 403 and `/admin/` renders unstyled while the JSON API looks perfectly healthy; repair with `chmod -R a+rX /var/www/grandway/static`.

**MEDIA_ROOT — deliberately outside any web root.** It is `/var/lib/…`, not `/var/www/…`, and that is not stylistic. Django guarantees no URL maps to this volume — the only path from these bytes to a client is the authenticated endpoint `GET /api/v1/files/<id>/download/`, and a test enforces that no route exists. But no test can police an nginx config. Keeping the directory outside the web root means a careless `root /var/www/grandway;` cannot reach it even by accident, and §5's group rule means nginx could not read it even if pointed there. Do not relocate it, and do not add a media `location` (§9). One temptation is worth naming: `uploaded_files/signatory/` holds signature images that a certificate renders, and those look like ordinary web assets in a way a passport scan does not. Serving "just the signatures" is one location block that would publish every applicant passport beside them, because they share this volume. The application already renders signatures correctly without it — the frontend fetches them through the authenticated download endpoint. There is no supported configuration in which any part of this volume is web-served.

On disk the layout is `uploaded_files/<owner_type>/<YYYY>/<MM>/<uuid4>.<ext>` (`backend/uploaded_files/models.py` line 65) — `owner_type` is one of `applicant`, `journey`, `offer`, `document`, `snapshot`, `signatory`, so new top-level directories appear over time as owner types are first used. Filenames are UUIDs; the original name lives only in the database. Files are written `0640` inside `0750` directories (`FILE_UPLOAD_PERMISSIONS` / `FILE_UPLOAD_DIRECTORY_PERMISSIONS`, `base.py` lines 279–280). No action is required as the tree grows; it is backed up wholesale (§17). This is the primary backup target alongside the database.

**LOG_DIR** is created at settings import — before the application can report anything. Every worker, every management command, and the nightly sweep fail identically if it cannot be created.

**The root-ownership trap.** `app.log` is opened by a `RotatingFileHandler` at settings import (`base.py` lines 394–402), i.e. by *any* `manage.py` invocation, before the command even runs. Run `manage.py` once as root on a fresh host and `app.log` is created `root:root 0644`; every gunicorn worker started afterwards then dies at import with `PermissionError: [Errno 13] Permission denied: '/var/log/grandway/app.log'`. That is why `deploy/manage.sh` re-executes itself as `grandway` unconditionally, why the units run as `grandway`, and why §15 checks `stat -c '%U %a' /var/log/grandway/app.log` → `grandway 640`. Fix if it happens: `chown grandway:grandway /var/log/grandway/app.log*`.

All units run with `UMask=0027`, so anything the application creates (log rotations, upload directories) is owner-and-group only; `www-data` is not in the group (§5).

`.venv/` and `logs/` under `/opt/grandway` are gitignored and are never touched by `git checkout` — a release upgrade cannot remove the virtualenv.

## 9. Reverse proxy contract

nginx MUST terminate TLS and MUST set the headers below. The reference config is `deploy/nginx.sample.conf`, reproduced in full further down; install it with the hostname substituted and **diff the installed copy against the sample on every upgrade** (§16).

**(1) `X-Forwarded-Proto` — set it, and always overwrite the client's value.** Django trusts this header to decide whether a request arrived over HTTPS (`SECURE_PROXY_SSL_HEADER`, `production.py` line 82). Two failure directions, both severe: forwarding the client's value lets anyone declare a plain-HTTP request secure, and every `Secure` cookie flag stops meaning anything; not setting it at all makes every proxied request look insecure, so `SECURE_SSL_REDIRECT` redirects it to a URL that terminates back at the proxy — an unconditional redirect loop, the whole site down on the first request.

**(2) `X-Forwarded-For` — and `NUM_PROXIES` must equal the real hop count.** nginx alone = 1; nginx behind a CDN = 2. This decides which entry is taken as the client IP, and it drives both API rate limiting and login lockout. Too high: a client spoofs its own header and evades both. Too low: every request looks like the proxy, so one user's failed logins lock out everybody.

**(3) `Host` — on every proxied location, including the probes.** Without `proxy_set_header Host $http_host;` nginx sends the upstream name (`grandway`) as the Host header, Django's `ALLOWED_HOSTS` check rejects it, and the probe returns 400 through the proxy while the same URL hit directly on `127.0.0.1:8000` with a Host header returns 200. This is why every loopback probe in this guide is `curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/ready/`.

**Serve** `/static/` from `STATIC_ROOT`. **NEVER serve `MEDIA_ROOT`** (§8). **Probes** `/health/` and `/ready/` are public, unthrottled, and exempt from the application's HTTPS redirect (`SECURE_REDIRECT_EXEMPT`, `production.py` line 120), so plain-HTTP probes return 200 rather than 301.

**Timeout coupling.** `proxy_read_timeout` (60s in the sample) must be ≥ `GUNICORN_TIMEOUT` (default 60, `deploy/gunicorn.conf.py` line 34). Raise them together; a proxy timeout below the worker timeout produces 504s while the worker is still legitimately working. `client_max_body_size 25m` sits above the application's own 10 MiB upload cap (§2) and must not be lowered below it.

**TLS issuance — stage 1 (HTTP-only, for the ACME challenge).** Certificates do not exist yet, so the full config (which references them) cannot be loaded. Install a minimal server block first:

```bash
cat > /etc/nginx/sites-available/grandway <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 404; }
}
EOF
ln -sf /etc/nginx/sites-available/grandway /etc/nginx/sites-enabled/grandway
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl enable --now nginx && systemctl reload nginx
certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive
test -s "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" || { echo "ABORT: no certificate"; exit 1; }
```

**Stage 2 — install the full configuration.**

```bash
sed "s/admin.grandwayeducation.com/$DOMAIN/g" /opt/grandway/deploy/nginx.sample.conf > /etc/nginx/sites-available/grandway
nginx -t && systemctl reload nginx
```

If `nginx -t` reports `unknown directive "http2"`, the host's nginx predates 1.25.1 (Ubuntu 24.04 ships 1.24 — **verify with `nginx -v`**): replace the `http2 on;` line with nothing and change both `listen 443 ssl;` lines to `listen 443 ssl http2;` / `listen [::]:443 ssl http2;`, then re-run `nginx -t`. Record the edit so the §16 diff does not surprise you.

**Renewal.** certbot's systemd timer renews automatically; nginx must reload afterwards to pick up the new files:

```bash
install -d /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\nsystemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
certbot renew --dry-run
systemctl list-timers certbot.timer --no-pager
```

**HSTS preload is a one-way door.** The application sends `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` (`production.py` lines 121–123). That header alone does nothing irreversible; *submitting the apex domain to the browser preload list* does — it makes serving any subdomain over plain HTTP impractical for a long time. Submission is a human decision (§21).

**`deploy/nginx.sample.conf` — corrected reference, verbatim:**

```nginx
# =============================================================================
# Grandway — nginx reference configuration
#
# Adapt hostnames and certificate paths. The two rules marked REQUIRED are not
# stylistic: the application's security guarantees depend on them.
#
# Installed by deploy.md §9 (Reverse proxy contract) as
# /etc/nginx/sites-available/grandway with the hostname substituted by sed.
# Diff the installed copy against this file on every upgrade.
# =============================================================================

upstream grandway {
    server 127.0.0.1:8000 fail_timeout=0;
}

server {
    listen 80;
    listen [::]:80;
    server_name admin.grandwayeducation.com;

    # ACME challenges must stay on plain HTTP.
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name admin.grandwayeducation.com;

    ssl_certificate     /etc/letsencrypt/live/admin.grandwayeducation.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/admin.grandwayeducation.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    # Uploads: the API accepts one file per request; raise only if that changes.
    client_max_body_size 25m;

    # -------------------------------------------------------------------------
    # Static files.
    #
    # Must match STATIC_ROOT in the environment. Nothing in Django serves these
    # with DEBUG=False, so without this block the admin renders unstyled.
    #
    # nginx reads these off the disk as www-data, which is in neither the owner
    # nor the group (§5) — so the tree must be world-readable. collectstatic
    # writes 0644 in 0755 directories; a 403 on every asset here means the
    # modes, not this alias (§8, §21).
    # -------------------------------------------------------------------------
    location /static/ {
        alias /var/www/grandway/static/;
        access_log off;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # =========================================================================
    # *** DO NOT ADD A LOCATION FOR MEDIA. READ THIS BEFORE EDITING. ***
    #
    # MEDIA_ROOT holds applicant passports, transcripts, and bank statements.
    # It is deliberately located OUTSIDE this web root (/var/lib/grandway/media,
    # not /var/www/...) precisely so that no `root` or `alias` directive here
    # can reach it, however this file is later edited.
    #
    # The ONLY path from those bytes to a client is the authenticated endpoint
    # GET /api/v1/files/<id>/download/, which applies the same authority check
    # as every other route. Serving MEDIA_ROOT from nginx would publish every
    # applicant document at a guessable URL and bypass that check entirely —
    # with no error, no log line, and no test able to catch it.
    #
    # If you find yourself adding `location /media/` to "fix" a broken image,
    # the correct fix is the download endpoint, not this file.
    # =========================================================================

    location / {
        # ---------------------------------------------------------------------
        # REQUIRED (1): set X-Forwarded-Proto, and always overwrite it.
        #
        # `proxy_set_header` replaces any client-supplied value, which is the
        # point. Django trusts this header to decide whether a request arrived
        # over HTTPS. Passing a client's own value through would let anyone
        # declare a plain HTTP request secure, and every Secure-cookie flag
        # would stop meaning anything.
        #
        # Omitting it is equally fatal in the other direction: every proxied
        # request arrives over plain HTTP on the loopback, Django judges them
        # all insecure, and SECURE_SSL_REDIRECT redirects them to a URL that
        # terminates right back here — an unconditional redirect loop taking
        # the whole site down on the first request after deploy.
        # ---------------------------------------------------------------------
        proxy_set_header X-Forwarded-Proto $scheme;

        # ---------------------------------------------------------------------
        # REQUIRED (2): X-Forwarded-For, and NUM_PROXIES must match reality.
        #
        # This is one proxy hop, so NUM_PROXIES=1. Behind an additional CDN it
        # would be 2. The value decides which entry is taken as the client IP,
        # and it drives both API rate limiting and login lockout. Set it too
        # high and a client can spoof past both; too low and every request
        # looks like the proxy, so one user's failed logins lock out everyone.
        # ---------------------------------------------------------------------
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Host $http_host;

        proxy_redirect off;
        # Coupled to GUNICORN_TIMEOUT (default 60, deploy/gunicorn.conf.py):
        # keep this >= the gunicorn timeout and raise the two together, or nginx
        # returns 504 while the worker is still legitimately working.
        proxy_read_timeout 60s;
        proxy_pass http://grandway;
    }

    # Probes. Both are public and unthrottled by design, and are exempt from
    # the application's HTTPS redirect so a plain-HTTP health check from a load
    # balancer returns 200 rather than a 301.
    #
    # Host MUST be forwarded here too: without it nginx sends the upstream name
    # ("grandway") as the Host header, Django's ALLOWED_HOSTS check rejects it,
    # and every probe through the proxy returns 400 (DisallowedHost) while the
    # same probe straight at 127.0.0.1:8000 with a Host header returns 200.
    location = /health/ {
        access_log off;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_pass http://grandway;
    }
    location = /ready/ {
        access_log off;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_pass http://grandway;
    }
}
```

## 10. Process model

```
gunicorn --chdir backend --config deploy/gunicorn.conf.py core.wsgi:application
```

Bound to the loopback only (`GUNICORN_BIND` default `127.0.0.1:8000`); nginx is the sole thing that should reach it. Sync workers, `cpu*2+1` by default, `timeout=60`, `graceful_timeout=30`, `keepalive=5`, `max_requests=1000` ± 100 jitter, `preload_app=False`, access and error logs to stdout/stderr (`deploy/gunicorn.conf.py`). `proc_name` is `grandway`.

**Worker count is coupled to two things.** `CACHE_BACKEND` — with `LocMemCache` every rate limit is multiplied by the worker count; production refuses to boot in that combination unless `THROTTLE_SINGLE_WORKER=true` (§4). Logging — **known limitation (1.0.0)**: Django's `LOGGING` writes a `RotatingFileHandler` under `LOG_DIR` (`base.py` lines 394–402). That handler is not multiprocess-safe. With multiple workers — and the nightly sweep writing to the same file — a 10 MB rollover can race: renames overwrite each other and a whole segment can be lost, and long lines can interleave. The stdout/stderr stream that gunicorn emits, captured by journald, is the reliable log source (§14); treat `app.log` as secondary.

**Reload vs restart.** `systemctl reload grandway` sends `SIGHUP` (the unit's `ExecReload`). gunicorn then re-reads `deploy/gunicorn.conf.py` and gracefully replaces its workers; because `preload_app=False`, each new worker imports the application afresh, so a HUP after a `git checkout` of a new tag is a **zero-downtime code reload**. HUP does **not** re-read the unit file or `EnvironmentFile=`, and does not change which packages are installed — after any change to `/etc/grandway/grandway.env`, to `requirements/`, or to a unit file, use `systemctl restart grandway` (a few seconds of 502 from nginx). `daemon-reload` is additionally required after editing a unit.

**Shutdown.** `KillMode=mixed` sends `SIGTERM` to the master only, which lets gunicorn finish in-flight requests for up to `graceful_timeout=30` seconds before killing workers; `TimeoutStopSec=45` gives that room before systemd escalates to `SIGKILL`.

**Worker recycling noise.** With `max_requests=1000`, journald shows periodic `Autorestarting worker after current request` / `Booting worker with pid` lines. That is expected and is not a crash; a crash looks like `Worker (pid:N) was sent SIGKILL!` or `[CRITICAL] WORKER TIMEOUT` (§19).

**`deploy/grandway.service` — verbatim:**

```ini
[Unit]
Description=Grandway application server (gunicorn)
Documentation=file:///opt/grandway/deploy.md
After=network-online.target postgresql.service redis-server.service
Wants=network-online.target

[Service]
Type=notify
NotifyAccess=all
User=grandway
Group=grandway
WorkingDirectory=/opt/grandway
EnvironmentFile=/etc/grandway/grandway.env
Environment=ENVIRONMENT=production
ExecStart=/opt/grandway/.venv/bin/gunicorn --chdir backend --config deploy/gunicorn.conf.py core.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=45
Restart=on-failure
RestartSec=5
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/lib/grandway /var/log/grandway

[Install]
WantedBy=multi-user.target
```

`Type=notify` works because gunicorn 23 speaks `sd_notify`; systemd considers the service started only once the master reports readiness, so `systemctl start` blocking and returning is itself a first signal. `ProtectSystem=full` mounts `/usr`, `/boot` and `/etc` read-only for the process (it needs to read the env file, which is fine); `ReadWritePaths` is the explicit list of what it may write. The unit deliberately does not include `/var/www/grandway/static` — `collectstatic` runs from `manage.sh`, not from the service.

## 11. Deploy sequence

The **first deploy**, copy-paste, after §5–§10 are done. Every command that touches `manage.py` goes through `deploy/manage.sh`, which loads the env file, exports `ENVIRONMENT=production`, refuses a stray `.env`, and always runs as `grandway`. Steps are tagged **every deploy** or **first only**; §16 (Upgrade sequence) is the every-deploy variant with the extra safety steps.

```bash
# 0. every deploy — a stray .env can boot production in development mode (§7)
test ! -e /opt/grandway/.env || { echo "REFUSING: stray /opt/grandway/.env present"; exit 1; }

# 1. every deploy — pinned production requirements into the venv, as grandway
sudo -u grandway -H /opt/grandway/.venv/bin/pip install --quiet --upgrade pip
sudo -u grandway -H /opt/grandway/.venv/bin/pip install --quiet -r /opt/grandway/requirements/production.txt

# 2. every deploy — static files into STATIC_ROOT (what nginx serves)
/opt/grandway/deploy/manage.sh collectstatic --noinput

# 3. every deploy — schema
/opt/grandway/deploy/manage.sh migrate --noinput

# 4. every deploy — the endpoint/permission registry is declared in code and synced into the database
/opt/grandway/deploy/manage.sh sync_policy_registry --by system --identifier "deployer:$TAG"

# 5. every deploy — GATE: a non-zero exit MUST abort the deploy
/opt/grandway/deploy/manage.sh validate_policy_engine --strict || { echo "ABORT: policy registry inconsistent with shipped code"; exit 1; }

# 6. first only (repeat only when a unit file changed) — install and start the units
install -m 0644 /opt/grandway/deploy/grandway.service /opt/grandway/deploy/grandway-sweep.service /opt/grandway/deploy/grandway-sweep.timer /opt/grandway/deploy/grandway-backup.service /opt/grandway/deploy/grandway-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now grandway
systemctl enable --now grandway-sweep.timer grandway-backup.timer

# 7. every deploy — do not route traffic before /ready/ returns 200
for i in $(seq 1 30); do
  curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/ready/ && break
  sleep 2
done
curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/ready/ || { echo "ABORT: /ready/ not 200 after 60s — journalctl -u grandway -n 100"; exit 1; }
curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/health/    # expected: {"status":"ok","version":"1.0.0"}
```

**Step 3** takes brief exclusive locks. Most migrations here add nullable columns and are effectively instant, but a migration that adds or alters a CHECK constraint takes ACCESS EXCLUSIVE on its table and scans it to validate — the table is unavailable for the duration. Harmless on a young database; once `uploaded_files_uploadedfile` has grown, schedule such a deploy off-peak. The release notes name any migration of that kind.

**Step 4** runs on every deploy, not only the first: skipping it leaves the database describing the previous release's endpoints. **Step 5** is a gate: a non-zero exit means the shipped code and the permission registry disagree, and authorization metadata is not something to run inconsistent. **Step 7**: `/ready/` opens a database connection; any non-200 means do not route (§14).

**8. Optional seeds — first only, and only AFTER §12 (First-boot bootstrap).** `seed_document_templates` attributes catalogue rows to the first superadmin (`created_by` is a non-null foreign key) and fails on a database with no superadmin. Both are idempotent and safe to re-run.

```bash
/opt/grandway/deploy/manage.sh seed_document_templates --activate   # 53 template slugs, created active
/opt/grandway/deploy/manage.sh apply_country_checklists              # no-op on a fresh database; safe
```

Then proceed to §12, and finish with §15 (Verification checklist).

## 12. First-boot bootstrap

**Create the superadmin.** `SUPERADMIN_*` come from the env file loaded by `manage.sh` (§7). Leave `SUPERADMIN_PASSWORD` unset: the command generates a password, **prints it once**, and flags the account to force a change at first login (`bootstrap_superadmin.py` lines 78–81). Capture that line — it is not recoverable.

```bash
/opt/grandway/deploy/manage.sh bootstrap_superadmin
# expected:
#   Superadmin 'superadmin' created.
#   Temporary password (store securely, shown once): <password>
#   The account must change its password on first login.
# on a re-run:  Superadmin 'superadmin' already exists; no changes made (idempotent).
```

**ADMIN LOCKOUT WARNING — read before first login.** The Django admin is OTP-gated: `core/apps.py` swaps the admin site class for `OTPAdminSite` at process start. An account **without a confirmed TOTP device cannot enter `/admin/` at all** — not with a correct password. Superadmin MFA is mandatory (`mfa_enrollment_required` is `true` until enrolled, and `mfa/disable` is refused with `AUTH_MFA_MANDATORY`). Enrol the superadmin's authenticator immediately after bootstrap, in the same session, by one of the two paths below.

**Preferred path — a human through the frontend.** Hand the temporary password to the human over the §1 channel. They log in at `FRONTEND_ORIGIN`; the frontend drives the sequence documented in `authenticate/docs/INTEGRATION.md` §8: forced password change (`POST /api/v1/auth/password/change/`, which revokes every session → log in again), then MFA enrolment (`POST /api/v1/auth/mfa/enroll/` renders a QR code; `POST /api/v1/auth/mfa/verify/` with the authenticator's code confirms it). Done when `GET /api/v1/auth/me/` shows `must_change_password: false`, `mfa_enabled: true`, `mfa_enrollment_required: false`.

**Agent fallback — scripted through nginx.** Use this only when no human can complete the preferred path now; the account must not be left without MFA. Field names and error codes below are from `authenticate/docs/INTEGRATION.md` §7. Two rules: (a) **reuse the fixed `DEVICE_ID`** from §1 for every login — each *new* `device_id` consumes one of the 3 device slots (`AUTH_MAX_ACTIVE_DEVICES`), and a fourth returns `AUTH_DEVICE_LIMIT_REACHED` (409); re-logging in on the same `device_id` replaces that session instead. (b) A wrong password counts toward the 5-failure lockout on both the username and your IP, so do not loop on failures.

```bash
API="https://$DOMAIN/api/v1"
json() { python3 -c 'import json,os,sys; print(json.dumps({k: os.environ[k.upper()] for k in sys.argv[1:]}))' "$@"; }
field() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(d); sys.exit(0 if d.get("success") else 1)'; }

# 1. log in with the temporary password (must_change_password is true; an access token is still issued)
read -rs -p "Temporary password from bootstrap_superadmin: " PASSWORD; echo; export PASSWORD
export USERNAME="$SUPERADMIN_USERNAME" DEVICE_NAME="deployer"
RESP=$(curl -sS -X POST "$API/auth/login/" -H 'Content-Type: application/json' -d "$(json username password device_id device_name)")
ACCESS=$(printf '%s' "$RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["data"]["access"]) if d.get("success") else sys.exit(f"login failed: {d}")')

# 2. forced password change — 200 revokes ALL sessions (including this one); AUTH_PASSWORD_WEAK (400) lists reasons in error.details.new_password
export CURRENT_PASSWORD="$PASSWORD"
export NEW_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
curl -sS -X POST "$API/auth/password/change/" -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d "$(json current_password new_password)" | field || { echo "password change failed"; exit 1; }
echo "NEW PASSWORD (hand to the human once, then forget it): $NEW_PASSWORD"

# 3. log in again with the new password, same DEVICE_ID
export PASSWORD="$NEW_PASSWORD"
RESP=$(curl -sS -X POST "$API/auth/login/" -H 'Content-Type: application/json' -d "$(json username password device_id device_name)")
ACCESS=$(printf '%s' "$RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["data"]["access"]) if d.get("success") else sys.exit(f"login failed: {d}")')

# 4. begin MFA enrolment — data.secret (base32) and data.otpauth_url are returned ONCE; AUTH_MFA_ALREADY_ENROLLED (409) means it is already done
RESP=$(curl -sS -X POST "$API/auth/mfa/enroll/" -H "Authorization: Bearer $ACCESS")
SECRET=$(printf '%s' "$RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["data"]["secret"]) if d.get("success") else sys.exit(f"enroll failed: {d}")')
OTPAUTH=$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["otpauth_url"])')
echo "TOTP SECRET (hand to the human once for their authenticator; never persist): $SECRET"
echo "otpauth URL: $OTPAUTH"

# 5. confirm with a current 6-digit code — from the human's authenticator, or computed here from the secret
export CODE="$(/opt/grandway/.venv/bin/python -c 'import base64,sys; from django_otp.oath import totp; print(f"{totp(base64.b32decode(sys.argv[1])):06d}")' "$SECRET")"
curl -sS -X POST "$API/auth/mfa/verify/" -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d "$(json code)" | field || { echo "mfa verify failed (AUTH_MFA_INVALID = wrong/expired code, retry within 30s)"; exit 1; }

# 6. confirm the account state, and that the admin login page is reachable
curl -sS "$API/auth/me/" -H "Authorization: Bearer $ACCESS" | python3 -c 'import json,sys; u=json.load(sys.stdin)["data"]; print({k: u[k] for k in ("username","authority_type","must_change_password","mfa_enabled","mfa_enrollment_required")})'
# expected: must_change_password False, mfa_enabled True, mfa_enrollment_required False
curl -sI "https://$DOMAIN/admin/login/" | head -1     # expected: HTTP/2 200 (or HTTP/1.1 200)
unset PASSWORD NEW_PASSWORD CURRENT_PASSWORD SECRET CODE ACCESS RESP
```

`mfa/verify` does not revoke the current session, so `$ACCESS` stays valid for step 6. From now on every login by this account needs `otp_code` (login returns `AUTH_MFA_REQUIRED` (401) without it). If the human later scans the secret into an authenticator app, it produces the same codes; the agent must not keep `SECRET` anywhere.

**Recovery — all require shell access on the host; there are no backup codes by design.**

```bash
/opt/grandway/deploy/manage.sh reset_superadmin_mfa        # removes the TOTP device(s) and revokes sessions → log in with password alone, re-enrol immediately
/opt/grandway/deploy/manage.sh reset_superadmin_password   # sets a temporary password (printed once), forces change at next login, revokes sessions
```

Both default to the `superadmin` username; override with `--username`, or `SUPERADMIN_USERNAME` in the env file. Both refuse to run against a non-superadmin account. Either is a §21 escalation — a human must ask for it.

**Finally, remove the bootstrap block.** `SUPERADMIN_*` must not stay in the env file.

```bash
sed -i -E 's/^(SUPERADMIN_(USERNAME|EMAIL|DISPLAY_NAME|PASSWORD)=.*)$/# \1/' /etc/grandway/grandway.env
grep -c '^SUPERADMIN_' /etc/grandway/grandway.env   # expected: 0
```

(No restart is needed: the running service never read them.)

## 13. Scheduled jobs

One job. It runs from a **systemd timer** (`deploy/grandway-sweep.timer` → `deploy/grandway-sweep.service`), installed and enabled in §11 step 6. Cron is a fallback only.

**`sweep_notifications`** — nightly at 02:15 Asia/Kathmandu (20:30 UTC). Raises alerts (checklist items due or overdue, missing documents, offer response deadlines passed or approaching, passport expiry, staff-set custom reminders) fanned out to every active Admin, and resolves alerts whose source condition has since cleared. Idempotent: every write is a `get_or_create` against a `(recipient, dedupe_key)` unique constraint, so it is safe to re-run and safe to run concurrently. It needs the full production environment — the unit loads the same `EnvironmentFile=` as the application, sets `ENVIRONMENT=production`, and runs as `grandway` so it can never leave a root-owned `app.log` (§8). If it never runs, no deadline notifications are raised or resolved; nothing else degrades, and the failure is silent from the API's perspective.

Flags (`sweep_notifications.py` lines 66–106): `--type {checklist_item_due,checklist_item_overdue,missing_documents,offer_response_due,offer_expired,passport_expiring,custom_reminder}` (one generator; the resolve pass is narrowed to match), `--due-within-days N` (default 7), `--passport-horizon-days N` (default 180), `--limit N` (stop each generator after N rows; **implies `--no-resolve`**), `--dry-run`, `--no-resolve`.

```bash
systemctl list-timers 'grandway-*' --no-pager          # both timers listed with NEXT in the future
systemctl start grandway-sweep.service                 # run now (idempotent)
journalctl -u grandway-sweep -n 50 --no-pager          # its output
/opt/grandway/deploy/manage.sh sweep_notifications --dry-run   # preview by hand
```

**Timezone.** The timer's `OnCalendar=*-*-* 02:15:00 Asia/Kathmandu` fixes the wall-clock time in Nepal regardless of the host's own timezone. `Persistent=true` runs a missed night as soon as the host is back up, which the idempotency makes safe. The backup timer fires at 01:30 Asia/Kathmandu, 45 minutes earlier, so the snapshot never overlaps the sweep.

**KNOWN LIMITATION (1.0.0).** The command exits 0 even when individual alert generators fail. It reports failures to stderr (journald) but does not signal them, so a failed unit status will not flag a partially failed night. Monitor:

```bash
journalctl -u grandway-sweep -p warning --since "-2 days" --no-pager   # expected: empty
```

**Cron fallback** (hosts without systemd timers): `deploy/crontab.sample` is the corrected reference — install with `crontab -u root -e`. The line is `30 20 * * * /opt/grandway/deploy/manage.sh sweep_notifications 2>&1 | logger -t grandway-sweep` (a UTC host; `manage.sh` supplies the environment and the user, so no `ENVIRONMENT=` or `PATH=` lines). Output goes to syslog under the tag `grandway-sweep` (`journalctl -t grandway-sweep`). If you instead redirect to a file, rotate it — this is the only case in this guide that needs a logrotate stanza:

```
/var/log/grandway/sweep.log {
    weekly
    rotate 8
    compress
    missingok
    create 0640 grandway grandway
}
```

## 14. Health and observability

| Probe | Checks | Returns | Use for |
|---|---|---|---|
| `GET /health/` | nothing — the process is alive | 200 `{"status":"ok","version":"1.0.0"}` | process supervisor; identifying the build even when the database is down |
| `GET /ready/` | opens a database connection (`connection.ensure_connection()`, `views.py` line 28) | 200 `{"status":"ready"}`; 503 `{"status":"not ready"}` | **routing decisions** |

Both are public, unauthenticated, unthrottled (`throttle_classes([])`), and exempt from the HTTPS redirect, so plain-HTTP probes work. Always send the Host header on the loopback (§9):

```bash
curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/health/
curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/ready/
curl -fsS "https://$DOMAIN/ready/"        # the same through nginx
```

**Operational rule: any non-200 from `/ready/` means do not route.** `/ready/` catches only `OperationalError` (`views.py` line 29): psycopg raises that for a refused connection, a wrong password, or an unknown database — all 503. Anything else raised while connecting surfaces as a 500 through the global exception handler. Both mean the same thing to a router. **`/ready/` does not check Redis**: a dead Redis leaves `/ready/` at 200 while every throttled endpoint (login, refresh, search, and every authenticated call) returns 500 — check Redis separately (`redis-cli ping` → `PONG`, and §15 item 7).

**Where each log lives.**

| Stream | Where | What |
|---|---|---|
| gunicorn access + error log, and Django's `console` handler | journald: `journalctl -u grandway` | the reliable, multi-worker-safe source; tracebacks appear here |
| Django `RotatingFileHandler` | `/var/log/grandway/app.log` (10 MB × 10 rotations, self-rotating, `base.py` lines 394–402) | secondary; not multiprocess-safe (§10) |
| nightly sweep | `journalctl -u grandway-sweep` | |
| nightly backup | `journalctl -u grandway-backup` | |
| nginx | `/var/log/nginx/access.log`, `/var/log/nginx/error.log` | |

**Log line format** (`backend/core/logging.py` lines 17–22): `[LEVEL] <UTC ISO-8601 timestamp> request_id=<id> logger=<name> msg=<text>`, with a traceback appended on its own lines when present. Outside a request `request_id=unknown`.

**Request correlation.** Every response carries `X-Request-ID` (`backend/core/middleware.py` line 50). A client may supply its own; it is honoured only if it matches `^[A-Za-z0-9._-]{1,64}$` (line 24), otherwise a fresh UUID is generated. To trace a user-reported error: take the `X-Request-ID` from the failing response and `journalctl -u grandway | grep request_id=<id>`. Passwords, tokens, OTPs, and keys are never logged.

**Retention** is a deployer choice: journald defaults keep logs by size; set `SystemMaxUse=` in `/etc/systemd/journald.conf` (e.g. `SystemMaxUse=1G`, then `systemctl restart systemd-journald`) if the default is not acceptable. Nothing in the application depends on it.

## 15. Verification checklist

Run after every deploy or upgrade, in order. Each command states its expected output; any deviation is a failure to report. Items 6–7 send exactly **one** bad login; do not repeat them in a loop (5 failures lock the username or IP for 15 minutes).

```bash
# 1. services
systemctl is-active grandway nginx postgresql redis-server                  # expected: four lines of "active"
# 2. build identity
curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/health/ | grep -q "\"version\":\"${TAG#v}\"" && echo "version OK"
# 3. readiness
curl -fsS -o /dev/null -w '%{http_code}\n' -H "Host: $DOMAIN" http://127.0.0.1:8000/ready/           # expected: 200
# 4. TLS + HSTS through nginx
curl -fsSI "https://$DOMAIN/health/" | grep -i '^strict-transport-security'   # expected: strict-transport-security: max-age=31536000; includeSubDomains; preload
# 5. plain HTTP redirects
curl -sI "http://$DOMAIN/api/v1/" | head -1                                  # expected: HTTP/1.1 301 Moved Permanently
# 6. auth envelope
curl -sS "https://$DOMAIN/api/v1/auth/me/"                                   # expected: {"success":false,"error":{"code":"AUTHENTICATION_REQUIRED",...},"meta":{}}  (HTTP 401)
# 7. the throttled path hits Redis: a bad login must be a 401 JSON error, never a 500 (which would mean the redis client is missing or Redis is down)
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "https://$DOMAIN/api/v1/auth/login/" -H 'Content-Type: application/json' \
  -d '{"username":"nobody-verification","password":"not-a-real-password","device_id":"verify"}'     # expected: 401
redis-cli -n 1 --scan --pattern ':1:throttle_*' | head -3                    # expected: at least one key, e.g. :1:throttle_auth_login_ip_...
# 8. static served by nginx
curl -fsS -o /dev/null -w '%{http_code}\n' "https://$DOMAIN/static/admin/css/base.css"               # expected: 200
sudo -u www-data test -r /var/www/grandway/static/admin/css/base.css && echo "static readable by nginx"   # expected: static readable by nginx (a 403 above means this line, not the alias)
# 9. media is NOT served and NOT readable by nginx
grep -E '^\s*location.*media' /etc/nginx/sites-enabled/grandway && echo "FAIL: media location present" || echo "no media location"   # expected: no media location
sudo -u www-data test ! -r /var/lib/grandway/media && echo "media unreadable by www-data"           # expected: media unreadable by www-data
id www-data | grep -q grandway && echo "FAIL: www-data is in group grandway" || echo "group OK"
# 10. Django deployment checks
/opt/grandway/deploy/manage.sh check --deploy --fail-level WARNING           # expected: System check identified no issues (0 silenced).
# 11. no unapplied migrations
/opt/grandway/deploy/manage.sh showmigrations --plan | grep -q '^\[ \]' && echo "FAIL: unapplied migrations" || echo "migrations OK"
# 12. registry gate
/opt/grandway/deploy/manage.sh validate_policy_engine --strict; echo "exit $?"                        # expected: exit 0
# 13. timers
systemctl list-timers 'grandway-*' --no-pager | grep -c grandway              # expected: 2
# 14. no tracebacks in the recent journal
journalctl -u grandway -n 100 --no-pager | grep -c Traceback                 # expected: 0
# 15. configuration hygiene
test ! -e /opt/grandway/.env && echo "no stray .env"
grep -q '^ENVIRONMENT=production$' /etc/grandway/grandway.env && echo "ENVIRONMENT OK"
stat -c '%U %a' /var/log/grandway/app.log                                    # expected: grandway 640
stat -c '%U:%G %a' /etc/grandway/grandway.env                                # expected: root:grandway 640
# 16. certificate renewal
certbot renew --dry-run 2>&1 | grep -E 'Congratulations|success' | head -1   # expected: a success line
```

## 16. Upgrade sequence

For a new tag `$NEW_TAG`. Distinct from §11: it snapshots before migrating, diffs shipped config against installed config, and reloads rather than restarts when only code changed.

**1. Read the release notes** (`CHANGELOG.md` section for `$NEW_TAG`, or `gh release view "$NEW_TAG"`), and classify:

- **PATCH** (`x.y.Z`) — proceed, any time.
- **MINOR** (`x.Y.0`) — proceed inside the maintenance window.
- **MAJOR** (`X.0.0`), or any release whose notes flag a migration as CHECK-constraint / off-peak / not backward-compatible, or a new **mandatory** environment variable — **escalate** (§21); a human confirms the plan first.

**2. Snapshot, then fetch.**

```bash
export NEW_TAG="v1.0.1"
test ! -e /opt/grandway/.env || { echo "REFUSING: stray .env"; exit 1; }
/opt/grandway/deploy/backup.sh "pre-$NEW_TAG" | tail -1          # record the two printed paths
export PREV_TAG="$(git -C /opt/grandway describe --tags --exact-match)"
sudo -u grandway -H git -C /opt/grandway fetch --tags --quiet
sudo -u grandway -H git -C /opt/grandway checkout -q "$NEW_TAG"
test "$(cat /opt/grandway/VERSION)" = "${NEW_TAG#v}" || { echo "ABORT: VERSION mismatch"; exit 1; }
```

**3. Config drift.** Diff every shipped operational file against its installed copy; apply what changed, and note which kind of change it was (it decides reload vs restart in step 6).

```bash
cd /opt/grandway
for u in grandway.service grandway-sweep.service grandway-sweep.timer grandway-backup.service grandway-backup.timer; do
  diff -u "/etc/systemd/system/$u" "deploy/$u" && echo "$u: unchanged" || echo "$u: CHANGED — install and daemon-reload"
done
diff -u /etc/nginx/sites-available/grandway <(sed "s/admin.grandwayeducation.com/$DOMAIN/g" deploy/nginx.sample.conf) && echo "nginx: unchanged" || echo "nginx: CHANGED — review, install, nginx -t, reload nginx"
git -C /opt/grandway diff --stat "$PREV_TAG" "$NEW_TAG" -- deploy/env.production.example requirements/   # new variables or pins?
diff <(grep -oE '^#? ?[A-Z_]+=' deploy/env.production.example | tr -d '# ' | sort -u) <(grep -oE '^#? ?[A-Z_]+=' /etc/grandway/grandway.env | tr -d '# ' | sort -u)   # variables the template has that the env file lacks (lines starting with <)
```

A unit changed → `install -m 0644 deploy/<unit> /etc/systemd/system/ && systemctl daemon-reload`. nginx changed → review the diff (keep any local `http2` edit from §9), install with the same `sed`, `nginx -t && systemctl reload nginx`. A new mandatory variable → add it to `/etc/grandway/grandway.env` (this is a restart, and MAJOR by definition — should already have been escalated in step 1).

**4. Install, collect, migrate, sync, validate.**

```bash
sudo -u grandway -H /opt/grandway/.venv/bin/pip install --quiet -r /opt/grandway/requirements/production.txt
/opt/grandway/deploy/manage.sh collectstatic --noinput
/opt/grandway/deploy/manage.sh showmigrations --plan | grep '^\[ \]'        # what is about to be applied (empty = none)
/opt/grandway/deploy/manage.sh migrate --noinput
/opt/grandway/deploy/manage.sh showmigrations --plan | grep -q '^\[ \]' && { echo "ABORT: migrations still unapplied"; exit 1; }
/opt/grandway/deploy/manage.sh sync_policy_registry --by system --identifier "deployer:$NEW_TAG"
/opt/grandway/deploy/manage.sh validate_policy_engine --strict || { echo "ABORT: registry inconsistent — see §18"; exit 1; }
```

**One-time, and only on a host first deployed before `v1.1.1`:** repair the static tree's permissions. Releases before `v1.1.1` collected static with the upload modes (`0640` in `0750` directories), which `www-data` cannot read — every `/static/` request 403s and `/admin/` renders unstyled (§21). Upgrading alone does **not** fix an existing tree: `collectstatic` skips files it considers unmodified, and even `--clear` leaves the already-created directories at `0750`. One `chmod` settles it, and it is harmless to run on a correct tree:

```bash
chmod -R a+rX /var/www/grandway/static
sudo -u www-data test -r /var/www/grandway/static/admin/css/base.css && echo "static readable by nginx"   # expected: static readable by nginx
```

**5. Reload or restart** (§10): code only → `systemctl reload grandway` (zero downtime); env file, `requirements/`, or a unit changed → `systemctl restart grandway`. Then poll:

```bash
systemctl reload grandway        # or: systemctl restart grandway
for i in $(seq 1 30); do curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/ready/ && break; sleep 2; done
curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/health/ | grep -q "\"version\":\"${NEW_TAG#v}\"" && echo "running $NEW_TAG" || { echo "ABORT: old version still serving"; exit 1; }
```

**6. Run §15 (Verification checklist)** with `TAG="$NEW_TAG"`. A failure **after** step 4's `migrate` has run is a schema-boundary situation: go to §18 (Rollback) and escalate — do not improvise.

## 17. Backup and restore

Exactly two sources of truth. Everything else is derived and rebuildable.

1. The PostgreSQL database.
2. `MEDIA_ROOT` (`/var/lib/grandway/media`).

Back up both, and back them up together — a database referencing files that the media backup does not contain is a broken restore. That coupling is tight: a signatory row points at its signature image, so a database restored newer than the media volume does not merely leave a file panel short an entry — the signature fails to load with `UPLOADED_FILES_FILE_BYTES_MISSING` (404) and the certificate that names that signatory renders without a signature. The same code is the symptom for any database/media skew after a restore.

**Order: database first, then media.** The file ledger never deletes bytes, so a database snapshot taken *before* the media tar can at worst leave orphan files in the tar that no row references — harmless. The reverse order can produce a row pointing at bytes the tar does not hold — the 404 above. `deploy/backup.sh` encodes this order. The cache needs no backup — it holds only throttle counters.

**`deploy/backup.sh`** (root; nightly via `grandway-backup.timer` at 01:30 Asia/Kathmandu, and by hand before every upgrade):

```bash
/opt/grandway/deploy/backup.sh                 # label "scheduled" — pruned after 14 days
/opt/grandway/deploy/backup.sh "pre-v1.0.1"    # labelled — kept until a human deletes it
ls -l /var/backups/grandway/                    # db-<UTC stamp>-<label>.dump, media-<stamp>-<label>.tar.gz, manifest-<stamp>-<label>.sha256
```

Overridable via environment: `BACKUP_DIR` (`/var/backups/grandway`), `DB_NAME` (`grandway`), `MEDIA_ROOT` (`/var/lib/grandway/media`), `KEEP_DAYS` (`14`). Manual equivalents, in the same order:

```bash
runuser -u postgres -- pg_dump -Fc grandway > /var/backups/grandway/db-manual.dump
tar -C /var/lib/grandway -cpzf /var/backups/grandway/media-manual.tar.gz media
```

**Off-host copy and restore rehearsal are deployer decisions** this guide does not make (§22). At minimum, copy `/var/backups/grandway` off the host after each nightly run, e.g. `rsync -a --delete /var/backups/grandway/ backup-host:/srv/grandway-backups/`, and verify with `sha256sum -c manifest-*.sha256` at the destination. A restore that has never been rehearsed is a hypothesis.

**Full restore sequence** — every step, in order, as root. Any restore is a §21 escalation: a human authorises it, because everything written after the snapshot is lost.

```bash
DUMP=/var/backups/grandway/db-<stamp>-<label>.dump
MEDIA_TAR=/var/backups/grandway/media-<stamp>-<label>.tar.gz
(cd /var/backups/grandway && sha256sum -c manifest-<stamp>-<label>.sha256)     # both: OK

# 1. stop everything that writes
systemctl stop grandway grandway-sweep.timer grandway-backup.timer

# 2. recreate the database (FORCE disconnects any straggler), owned by the app role, with the extension
runuser -u postgres -- psql -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS grandway WITH (FORCE);" \
  -c "CREATE DATABASE grandway OWNER grandway ENCODING 'UTF8';"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d grandway -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
runuser -u postgres -- pg_restore --no-owner --role=grandway -d grandway "$DUMP"

# 3. media: move the current tree aside (never delete it), unpack, fix ownership
mv /var/lib/grandway/media "/var/lib/grandway/media.replaced-$(date -u +%Y%m%dT%H%M%SZ)"
tar -C /var/lib/grandway -xpzf "$MEDIA_TAR"
chown -R grandway:grandway /var/lib/grandway/media
chmod 0750 /var/lib/grandway/media

# 4. bring the schema and the registry up to the DEPLOYED code
/opt/grandway/deploy/manage.sh migrate --noinput
/opt/grandway/deploy/manage.sh sync_policy_registry --by system --identifier "restore:$(cat /opt/grandway/VERSION)"    # REQUIRED
/opt/grandway/deploy/manage.sh validate_policy_engine --strict || { echo "ABORT: registry inconsistent"; exit 1; }

# 5. start, and verify
systemctl start grandway grandway-sweep.timer grandway-backup.timer
```

Then run §15 (Verification checklist). **A restore is not complete until `sync_policy_registry` has run**: the registry must be re-synced from the deployed code, or the database describes whatever endpoints existed when the backup was taken. The moved-aside `media.replaced-*` directory is deleted only by a human, later (§21).

## 18. Rollback

The rollback unit is a release tag: check out the previous tag and re-run the deploy steps. Two cases.

**(a) Code-only rollback** — the release being left applied **no** migrations (its `showmigrations --plan` diff in §16 step 4 was empty). Reverse of the upgrade, no data risk:

```bash
export PREV_TAG="v1.0.0"
sudo -u grandway -H git -C /opt/grandway checkout -q "$PREV_TAG"
test "$(cat /opt/grandway/VERSION)" = "${PREV_TAG#v}" || { echo "ABORT: VERSION mismatch"; exit 1; }
sudo -u grandway -H /opt/grandway/.venv/bin/pip install --quiet -r /opt/grandway/requirements/production.txt
/opt/grandway/deploy/manage.sh collectstatic --noinput
/opt/grandway/deploy/manage.sh sync_policy_registry --by system --identifier "rollback:$PREV_TAG"
/opt/grandway/deploy/manage.sh validate_policy_engine --strict || { echo "ABORT"; exit 1; }
systemctl reload grandway      # restart instead if the env file, requirements, or a unit changed between the tags
for i in $(seq 1 30); do curl -fsS -H "Host: $DOMAIN" http://127.0.0.1:8000/ready/ && break; sleep 2; done
```

Then §15 with `TAG="$PREV_TAG"`. Re-apply any nginx/unit diffs from §16 step 3 in reverse if the tags differ there.

**(b) Schema rollback** — the release being left applied migrations. **Migrations are not automatically reversible**, and rolling the code back across a migration boundary does NOT roll the schema back. The supported path is: restore the `pre-$NEW_TAG` snapshot taken in §16 step 2 (§17 full restore sequence, with the code already checked out at `$PREV_TAG` before step 4 of the restore), then finish with (a). **Everything written after the snapshot is lost** — always escalate (§21) before doing this; a human decides whether that loss is acceptable or whether to forward-fix instead.

**Why not `migrate <app> <previous>`?** A migration can be reversible when it is applied and irreversible once the release has run, because the reverse may restore a constraint that live data no longer satisfies. `uploaded_files` migration `0002_signatory_owner` is the worked example: reversing it drops a column and restores a narrower CHECK, which fails — mid-transaction — if any file has been stored against the owner type that column added. Every migration's docstring states its own reverse conditions; an explicit reverse is a human's call after reading it, never the agent's default.

**1.0.0 policy: FORWARD-FIX BY DEFAULT.** Ship a patch release rather than rolling back across a schema change. Release tags are immutable, so `v1.0.1` supersedes `v1.0.0` — `v1.0.0` itself is never rewritten.

## 19. Operations runbook

**Lifecycle.**

```bash
systemctl status grandway --no-pager             # state, main PID, recent log lines
systemctl start|stop|reload|restart grandway     # reload = code only; restart = env/requirements/unit (§10)
journalctl -u grandway -f                        # follow the application log
journalctl -u grandway --since "-1h" -p err      # errors in the last hour
systemctl list-timers 'grandway-*' --no-pager    # sweep and backup schedules
systemctl start grandway-sweep.service           # run the sweep now
systemctl start grandway-backup.service          # run a backup now
redis-cli ping; redis-cli info memory | grep -E 'used_memory_human|maxmemory_human'
redis-cli -n 1 --scan --pattern ':1:throttle_*' | wc -l    # live throttle buckets
df -h / /var/lib/grandway /var/backups/grandway  # disk: media and backups grow without bound
du -sh /var/lib/grandway/media /var/backups/grandway
runuser -u postgres -- psql -tAc "SELECT pg_size_pretty(pg_database_size('grandway'));"
certbot certificates                             # expiry of the live certificate
```

**Rotating `SECRET_KEY`** (escalate first, §21): change the value in `/etc/grandway/grandway.env`, `systemctl restart grandway`. Effect: every access token and every session becomes invalid — **all users are logged out** and must log in again; nothing else is affected (passwords and TOTP devices are stored independently). Intended after a compromise.

**Failure signatures.** Messages in the "Symptom" column are the literal strings the code or its dependencies emit.

| Symptom | Where seen | Cause | Fix |
|---|---|---|---|
| `ImproperlyConfigured: ENVIRONMENT is unset or invalid (got None)` | `journalctl -u grandway` at start; any `manage.py` | `ENVIRONMENT` not in the process environment | Use `manage.sh`; ensure the env file has `ENVIRONMENT=production` and the unit has `EnvironmentFile=` (§7) |
| `Refusing to boot: ENVIRONMENT is unset, so the repo-root .env selected 'development' — but .env.production is also present` | start-up | someone copied a developer's tree with `.env` and `.env.production` | `rm /opt/grandway/.env /opt/grandway/.env.production`; this deployment uses neither (§7) |
| `UndefinedValueError: SECRET_KEY not found. Declare it as envvar or define a default value.` (or `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `CACHE_BACKEND`) | start-up | mandatory variable missing from the env file, or the unit did not load it | add it; `systemctl restart grandway` |
| `ImproperlyConfigured: CACHE_BACKEND is LocMemCache: rate limits are per-process and reset on restart.` | start-up | `CACHE_BACKEND` points at LocMem | set `django.core.cache.backends.redis.RedisCache` + `CACHE_LOCATION=redis://127.0.0.1:6379/1` (§7) |
| `ImproperlyConfigured: LOG_DIR (/var/log/grandway) could not be created:` | start-up, every command | directory missing or not writable by `grandway` | `install -d -o grandway -g grandway -m 0750 /var/log/grandway` (§5) |
| `PermissionError: [Errno 13] Permission denied: '/var/log/grandway/app.log'` | workers die at boot; commands fail | `manage.py` was once run as root → root-owned `app.log` | `chown grandway:grandway /var/log/grandway/app.log*`; only ever use `manage.sh` (§8) |
| `ModuleNotFoundError: No module named 'redis'` | first throttled request → 500; or start-up | `pip install` skipped or ran against another venv | re-run §11 step 1 as `grandway` against `/opt/grandway/.venv`; `systemctl restart grandway` |
| `Invalid HTTP_HOST header: 'grandway'. You may need to add 'grandway' to ALLOWED_HOSTS.` / 400 `DisallowedHost` | `journalctl -u grandway`; probes through nginx return 400 | nginx not forwarding `Host` (old probe blocks), or `ALLOWED_HOSTS` ≠ `$DOMAIN` | reinstall `deploy/nginx.sample.conf` (§9); fix `ALLOWED_HOSTS`; probes on the loopback need `-H "Host: $DOMAIN"` |
| Browser `ERR_TOO_MANY_REDIRECTS`; `curl` loops on 301 to the same URL | any HTTPS page | nginx not sending `X-Forwarded-Proto https` | restore `proxy_set_header X-Forwarded-Proto $scheme;` in `location /` (§9) |
| Every user gets 429 `RATE_LIMIT_EXCEEDED`, or one user's failures lock everyone out | API | `NUM_PROXIES=0` behind nginx, so every client is 127.0.0.1 | `NUM_PROXIES=1` (2 behind a CDN); restart (§7, §9) |
| `/admin/` renders with no CSS | browser; nginx `error.log` shows `Permission denied` on a `/static/` path | `collectstatic` not run; nginx `/static/` alias ≠ `STATIC_ROOT`; or the tree is not world-readable (host first deployed before v1.1.1) | `manage.sh collectstatic --noinput`; check `alias /var/www/grandway/static/;` (§8, §9); `chmod -R a+rX /var/www/grandway/static`, then `sudo -u www-data test -r /var/www/grandway/static/admin/css/base.css` |
| `/admin/` refuses a correct password ("Please enter the correct username and password") | admin login page | the account has no confirmed TOTP device — the admin is OTP-gated | enrol MFA via the API (§12); the admin form needs the OTP token too |
| `role "grandway" already exists` / `database "grandway" already exists` / `Superadmin 'superadmin' already exists; no changes made (idempotent).` | provisioning / bootstrap | re-run of an idempotent step | benign; continue |
| `validate_policy_engine --strict` exits 1 | deploy step 5 / §16 | shipped code and registry disagree, or `sync_policy_registry` was skipped | re-run `sync_policy_registry`; if still failing, **abort the deploy** and escalate — do not start the service on an inconsistent registry |
| `Couldn't import Django. Are you sure it's installed and available on your PYTHONPATH environment variable?` | any command | wrong interpreter (system `python3` instead of `/opt/grandway/.venv/bin/python`) | use `manage.sh`, which always uses the venv |
| nginx returns **502 Bad Gateway** | browser / `curl` | gunicorn not running or not on `127.0.0.1:8000` | `systemctl status grandway`; `journalctl -u grandway -n 100`; check `GUNICORN_BIND` |
| nginx returns **504 Gateway Time-out** | slow endpoint | `proxy_read_timeout` < `GUNICORN_TIMEOUT`, or the request genuinely exceeds both | raise both together (§9); investigate the slow request via its `X-Request-ID` |
| nginx returns **413 Request Entity Too Large** | upload | body > `client_max_body_size 25m` | the app's own cap is 10 MiB; a 413 at 25 MB means a client bug, not a config change |
| `[CRITICAL] WORKER TIMEOUT (pid:N)` | `journalctl -u grandway` | a request ran past `GUNICORN_TIMEOUT` (60 s); worker killed and replaced | find the request in the log by `request_id`; raise `GUNICORN_TIMEOUT` + `proxy_read_timeout` only within §21 bounds |
| `FATAL:  password authentication failed for user "grandway"` | `/ready/` 503; `journalctl` | `DB_PASSWORD` ≠ the role's password | `ALTER ROLE grandway WITH PASSWORD '…'` to match, or fix the env file; restart |
| `permission denied to create extension "pg_trgm"` | `migrate` | extension not pre-created and the role may not create it | `runuser -u postgres -- psql -d grandway -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"` (§5) |
| API 404 with code `UPLOADED_FILES_FILE_BYTES_MISSING` | file download / signature render | database row references bytes not on disk — media/database skew after a restore, or a media directory moved | restore media from the matching snapshot (§17); never "fix" by adding an nginx media location |
| Sweep unit shows `SUCCESS` but `journalctl -u grandway-sweep -p warning` has generator errors | nightly | known limitation: partial failure exits 0 (§13) | read the generator error; re-run `systemctl start grandway-sweep.service` after fixing; alerts are idempotent |
| `/health/` reports `"version":"0.0.0+unknown"` | probe | `VERSION` file missing — the host is not running a full checkout | redeploy from a git checkout of the tag (§6) |
| Browser: CORS error, or the refresh cookie is never sent / login "works" but the next request is 401 | frontend | `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` ≠ the frontend's exact origin (scheme + host + port); or the frontend is on plain HTTP so the `Secure` cookie is dropped | set the exact origin(s) (§7); serve the frontend over HTTPS; restart |
| `AUTH_DEVICE_LIMIT_REACHED` (409) during scripted logins | §12 / scripts | a new `device_id` per login consumed the 3 device slots | reuse the fixed `DEVICE_ID`; a human revokes sessions via `/api/v1/auth/sessions/` or the superadmin logs out devices |
| `/ready/` returns 503 `{"status":"not ready"}` | probe | PostgreSQL refused/auth failed/unknown DB (`OperationalError`) | `systemctl status postgresql`; check `DB_*`; do not route until 200 |
| `/ready/` returns 500 | probe | a non-`OperationalError` raised while connecting (e.g. a broken driver install) | `journalctl -u grandway -n 100`; treat exactly like 503 — do not route (§14) |
| `nginx -t`: `unknown directive "http2"` | installing the proxy config | nginx < 1.25.1 | use `listen 443 ssl http2;` and drop `http2 on;` (§9) |

## 20. Security posture summary

Each of these is enforced by the application (file and line given). Several can be silently defeated at the proxy or on the host; the list exists so that does not happen by accident.

- `DEBUG = False`, hardcoded (`production.py` line 20). No variable can turn it on.
- HTTPS redirect for all traffic (`SECURE_SSL_REDIRECT = True`, line 102), except `/health/` and `/ready/` (`SECURE_REDIRECT_EXEMPT`, line 120).
- HSTS: 1 year, `includeSubDomains`, `preload` (lines 121–123). **Preload is a one-way door for the apex domain** — submitting to the preload list makes it impractical to serve any subdomain over plain HTTP for a long time. Confirm that is intended before submitting (§21).
- `Secure` + `HttpOnly` + `SameSite=Lax` cookies (`base.py` lines 370–372; `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`, `production.py` lines 124–125); the refresh token is cookie-only in production (`AUTH_REFRESH_COOKIE_ENABLED = True`, line 26), never in a response body.
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, XSS filter on (`production.py` lines 126–128).
- CORS is an explicit allow-list with credentials enabled (`production.py` lines 98–99). Never widen it to allow-all: with credentials on, that would let any site on the internet make authenticated calls with a user's refresh cookie.
- Argon2id password hashing (`base.py` line 193); 12-character minimum (line 183).
- django-axes lockout — 5 failures, 15-minute cool-off, on username or IP (`base.py` lines 207–209), with the client IP resolved through `NUM_PROXIES` (lines 225–227).
- The Django admin is OTP-gated (`core/apps.py`) — §12.
- `MEDIA_ROOT` is never web-served (§8); files `0640` in `0750` directories (`base.py` lines 279–280).
- Every mandatory setting fails closed at boot rather than degrading silently (§7).
- Client-supplied `X-Request-ID` is validated before it reaches logs or headers (`middleware.py` line 24).

**Host posture added by this guide:** gunicorn, PostgreSQL, and Redis listen on the loopback only; `ufw` admits SSH and 80/443 only (§5); `www-data` is not in group `grandway`, so nginx cannot read media even if misconfigured (§5); the env file is `root:grandway 0640` (§7); units run as an unprivileged system user with `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, `ProtectHome`, an explicit `ReadWritePaths` list, and `UMask=0027` (§10); backups are `root 0700` (§17).

## 21. Agent decision rules

**MAY decide alone** (no human in the loop; log what was done):

- Apply a **PATCH** release (§16) at any time, and a MINOR release inside the maintenance window when its notes flag no migration as off-peak / CHECK-constraint.
- Tune `GUNICORN_WORKERS` within `[1, cpu*2+1]` and `GUNICORN_TIMEOUT` within `[30, 120]` seconds — and in the same change set nginx `proxy_read_timeout` ≥ the new timeout (§9).
- Choose `systemctl reload` vs `restart` per §10.
- Retry `/ready/` polling (§11 step 7) up to the stated timeout; retry a failed `pip install` once.
- Re-run idempotent commands: `sync_policy_registry`, `seed_document_templates`, `apply_country_checklists`, `sweep_notifications`, `backup.sh`, `collectstatic`.
- Vacuum journald (`journalctl --vacuum-size=…`) or set a retention cap (§14).
- Renew TLS (`certbot renew`), reload nginx after it.
- Run `backup.sh` with any label, at any time.

**MUST escalate — stop, report the situation and the intended command, and wait:**

- A **MAJOR** upgrade, or any release whose notes flag a migration as CHECK-constraint / off-peak / non-backward-compatible, or that adds a mandatory environment variable (§16 step 1).
- Any rollback across a migration boundary (§18 b), and **any restore** (§17) — data written after the snapshot is lost.
- Rotating `SECRET_KEY` (logs every user out, §19).
- Changing `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, or `NUM_PROXIES`.
- Running `reset_superadmin_mfa` or `reset_superadmin_password` (§12).
- Deleting or moving anything under `/var/lib/grandway/media` (including a `media.replaced-*` directory left by a restore) or under `/var/backups/grandway`.
- Submitting the domain to the HSTS preload list (§9, §20).
- Installing any package not listed in `requirements/` — into the venv or via `apt` beyond §5's list.
- Setting `THROTTLE_SINGLE_WORKER=true` (§4).
- Editing `deploy/nginx.sample.conf` content beyond the hostname `sed` and the `http2` compatibility edit in §9.

**NEVER** (no approval makes these acceptable; refuse and report):

- Add an nginx `location` for media, or any `root`/`alias` that reaches `/var/lib/grandway` (§8, §9).
- Widen CORS to all origins, or set `CORS_ALLOW_ALL_ORIGINS` (§20).
- Bind gunicorn to anything but the loopback (`GUNICORN_BIND`), or open 8000/5432/6379 in `ufw`.
- Run `manage.py` as root — always `deploy/manage.sh` (§8).
- Create `/opt/grandway/.env` or `/opt/grandway/.env.production` (§7).
- Run `reset_dev_data` (it refuses outside `ENVIRONMENT=development`, but do not try).
- Create, move, or delete git tags, or run `git` as root inside `/opt/grandway` (§6).
- Persist the temporary password or the TOTP secret anywhere — hand them over once and forget them (§12).
- Add `www-data` to group `grandway` (§5).

## 22. Gaps

**Deliberately left to the deployer** (decisions this contract does not make):

- Off-host backup destination and transport (§17) — undecided; the nightly backup is on-host only until it is.
- Restore rehearsal is not automated (§17); schedule one after the first backup and after every MINOR.
- journald retention (§14) — the default size-based policy applies until `SystemMaxUse=` is set.
- Monitoring and alerting integration — nothing ships one; the probes (§14), `journalctl -p warning`, `redis-cli ping`, and disk usage (§19) are the raw signals.
- Redis `requirepass` is not set; it relies on the loopback bind and `ufw` (§5).
- The CDN/second-hop question: if a CDN is later placed in front of nginx, `NUM_PROXIES` becomes 2 and the real client IP must be verified end-to-end (§9) — escalate (§21).
- Python version is not machine-enforced beyond `python3.12 -m venv` (§6); nothing in the application asserts it at import.
- The nginx sample uses `http2 on;` (nginx ≥ 1.25.1); Ubuntu 24.04's packaged nginx may be older (§9) — verify on the host.
- Redis version on Ubuntu 24.04 is stated as 7.x from memory of the distribution, not read from this repository — verify with `redis-server --version`.

**Known imperfections in 1.0.0** (all recorded in `CHANGELOG.md` under `[Unreleased]` → `Deferred`):

- Static files are not served by the application; nginx serves them (§8, §9). Without a reverse proxy the admin renders unstyled.
- The rotating file log handler is not multiprocess-safe (§10); journald is the reliable log.
- No dependency lock file or hashes (§4).
- `psycopg[binary]` rather than `psycopg[c]` in production (§4).
- The test suite runs on SQLite, not PostgreSQL — `select_for_update`, transaction-abort semantics, and `pg_trgm` are untested by the suite; only the CI `policy` stage touches real PostgreSQL. Not operator-visible, but it bounds the confidence a green test run gives.
- `sweep_notifications` exits 0 on partial failure (§13).
- `/ready/` does not check the cache backend, only the database (§14).
- `requirements/README.md` documents two management commands that do not exist (`validate_organization_integrity`, `rebuild_organization_closure`, for an `organization` app that was removed). They are not part of any sequence in this guide; do not attempt to run them.
- The application runs on a single node: file storage is a local volume, so horizontal scaling across hosts requires shared storage that has not been designed or tested.
