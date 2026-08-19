# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) on the deployed application — distinct from the `/api/v1/` URL prefix, which versions the API contract separately.

Release tags are immutable: a released version is never rewritten, only superseded by a later one.

## [Unreleased]

### Deferred

Findings recorded during release preparation that were triaged as not blocking. Each carries the version bump it would require. This registry is reviewed at every release: an item either ships, stays deferred, or is retired with a reason — it is never silently dropped.

- **Static files are not served by the application** (MINOR) — no whitenoise and no `STORAGES` configuration, so with `DEBUG=False` nothing serves `STATIC_ROOT`. The only consumer is the OTP-gated Django admin, which renders unstyled without a reverse proxy serving it. Deferred because adding whitenoise is a new dependency requiring approval, and because serving static is the deployment layer's job — `deploy/nginx.sample.conf` ships the block instead. Documented in `GUIDE.txt` §5 and §14.
- **The rotating file log handler is not multiprocess-safe** (MINOR) — under multi-worker gunicorn, plus the nightly cron writing to the same file, a 10 MB rollover can race: renames overwrite one another and a whole segment can be lost. The stdout stream gunicorn captures is the reliable source. Documented in `GUIDE.txt` §6.
- **No dependency lock file or hashes** (MINOR) — direct dependencies are pinned exactly, but transitive ones resolve fresh at install time, so a deploy-day install may not match what CI tested. Mitigation until fixed: build once and promote the same artifact. Documented in `GUIDE.txt` §2.
- **`psycopg[binary]` is used in production** (MINOR) — psycopg's own documentation recommends `psycopg[c]` or a system build for production. Deferred because the change requires build tooling in whatever image is chosen, and the packaging target is not yet decided. Documented in `GUIDE.txt` §2.
- **The test suite runs on SQLite, not PostgreSQL** (MINOR) — `select_for_update` is a no-op, failed statements do not abort transactions, and `pg_trgm` behaviour is untested. The `policy` CI stage is the only one touching real PostgreSQL. This gap has already masked real defects.
- **`sweep_notifications` exits 0 on partial failure** (PATCH) — individual alert generators that raise are reported to stderr but do not change the exit status, so cron cannot detect a partially failed night. Documented in `GUIDE.txt` §9.
- **`/ready/` does not check the cache backend** (PATCH) — readiness opens a database connection only. In production the cache is the rate-limit store, so a failed Redis leaves throttling degraded without the readiness probe reporting it. Documented in `GUIDE.txt` §10.
- **`requirements/README.md` documents two commands that do not exist** (PATCH) — `validate_organization_integrity` and `rebuild_organization_closure`, for an `organization` app that was removed. Also referenced in `core/management/commands/reset_dev_data.py`.

## [1.0.0] - 2026-08-19

First production release. The application has been in development since 2026-07; this release marks the point at which it is deployable by someone who did not build it.

### Added

- **Deployment contract** — `GUIDE.txt` documents everything needed to deploy, operate, back up, and roll back without reading source: runtime requirements, the complete environment-variable contract, filesystem and reverse-proxy contracts, the ordered deploy sequence, first-boot bootstrap, scheduled jobs, health endpoints, backup/restore, rollback, and the enforced security posture.
- **Reference deployment configs** — `deploy/env.production.example`, `deploy/gunicorn.conf.py`, `deploy/nginx.sample.conf`, and `deploy/crontab.sample`, all target-agnostic.
- **Operator README** — repository entry point with a routing table to the contract written for each audience.
- **Version identity** — a repo-root `VERSION` file, `core.__version__`, and a `version` field on `GET /health/`, so a deployed host can report which build it is running even when its database is unreachable. Optional response field, non-breaking.
- **Tag-triggered release verification** — `.github/workflows/release.yml` re-runs every gate against a tagged commit and asserts `VERSION` == tag == `core.__version__`.
- **Migration drift check in CI** — `makemigrations --check` now runs as a first-class stage; two comments had long claimed an existing check "mirrored" it, but it had never actually run.
- **Configurable deployment paths** — `STATIC_ROOT` and `LOG_DIR` join `MEDIA_ROOT` as environment-configurable, so a deployment can place static under the web root it serves and media deliberately outside any web root.

### Fixed

- **Health probes no longer redirect** — `SECURE_SSL_REDIRECT` returned 301 for the plain-HTTP probes a load balancer sends, which reads as unhealthy. A host would have served correctly and never received traffic.
- **`ALLOWED_HOSTS` is mandatory in production** — it previously inherited a `localhost` default from base settings, so every request on the real hostname would have returned 400 at request time rather than failing the deploy.
- **An unwritable log directory now fails with a named error** — the directory was created by an unguarded `mkdir` at settings import, before `SECRET_KEY` was read, so a read-only filesystem or non-root user killed every worker, migration, and cron job with a bare traceback naming no setting.
- **Staging now matches production's posture** — it was missing `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_BROWSER_XSS_FILTER`, `X_FRAME_OPTIONS`, and the `ALLOWED_HOSTS` and `CACHE_BACKEND` requirements, so it could not validate production before production depended on it. HSTS remains deliberately weaker, asserted explicitly by a parity test.
- **Live migration drift** — `notifications.notification_type` had gained choices with no migration.

### Security

Carried from the 2026-08-17 security audit and its remediation:

- **Django upgraded to 5.2 LTS** with CVE-affected pins patched (CVE-2025-48432, CVE-2025-57833, CVE-2024-22513, CVE-2024-6827).
- **Environment selection fails closed** — an unset or unrecognised `ENVIRONMENT` refuses to boot instead of silently defaulting to development settings with `DEBUG=True`.
- **The Django admin is OTP-gated** and no longer renders password hashes.
- **Production requires an explicit throttle-cache backend** — inheriting the per-process cache silently multiplied every rate limit by the worker count and reset it on restart.
- **Audited client IPs resolve through `NUM_PROXIES`**, closing an `X-Forwarded-For` spoofing path that affected both rate limiting and login lockout.
- **An audit-log leak and six correctness defects** were closed.
- **List-filter query parameters are validated** before reaching selectors; malformed input previously produced unhandled 500s, and unknown enum values silently returned an empty page.

### Performance

- Trigram indexes on four fields substring search could not otherwise reach.
- N+1 queries eliminated in checklists and across core; `decided_at` indexed on offers.

[Unreleased]: https://github.com/CodeResound/grandway/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/CodeResound/grandway/releases/tag/v1.0.0
