# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) on the deployed application — distinct from the `/api/v1/` URL prefix, which versions the API contract separately.

Release tags are immutable: a released version is never rewritten, only superseded by a later one.

## [Unreleased]

### Fixed

- **The release workflow's annotated-tag check failed on correctly annotated tags** (PATCH) — it read
  `git cat-file -t` in the runner's working copy, where `actions/checkout` leaves the tag ref pointing at
  the peeled commit. It now asks GitHub's ref API, which reports the object the tag actually points at.
- **`delete_branch_on_merge` deleted the permanent `dev` branch** (PATCH) — the repository-wide setting
  removes the head branch of every merged pull request and cannot distinguish a disposable task branch
  from a permanent one, so merging a `dev → main` pull request deleted `dev`. The setting is now `false`;
  cleanup happens per-pull-request via `--delete-branch` on the merge command, which removes only the
  branch being landed. `dev` was restored from `main` with no content lost.

### Deferred

Findings recorded during release preparation that were triaged as not blocking. Each carries the version bump it would require. This registry is reviewed at every release: an item either ships, stays deferred, or is retired with a reason — it is never silently dropped.

- **Static files are not served by the application** (MINOR) — no whitenoise and no `STORAGES` configuration, so with `DEBUG=False` nothing serves `STATIC_ROOT`. The only consumer is the OTP-gated Django admin, which renders unstyled without a reverse proxy serving it. Deferred because adding whitenoise is a new dependency requiring approval, and because serving static is the deployment layer's job — `deploy/nginx.sample.conf` ships the block instead. Documented in `deploy.md` §9 (Reverse proxy contract) and §22 (Gaps).
- **The rotating file log handler is not multiprocess-safe** (MINOR) — under multi-worker gunicorn, plus the nightly cron writing to the same file, a 10 MB rollover can race: renames overwrite one another and a whole segment can be lost. The stdout stream gunicorn captures is the reliable source. Documented in `deploy.md` §10 (Process model).
- **No dependency lock file or hashes** (MINOR) — direct dependencies are pinned exactly, but transitive ones resolve fresh at install time, so a deploy-day install may not match what CI tested. Mitigation until fixed: build once and promote the same artifact. Documented in `deploy.md` §4 (Runtime requirements).
- **`psycopg[binary]` is used in production** (MINOR) — psycopg's own documentation recommends `psycopg[c]` or a system build for production. Deferred because the change requires build tooling in whatever image is chosen, and the packaging target is not yet decided. Documented in `deploy.md` §4 (Runtime requirements).
- **The test suite runs on SQLite, not PostgreSQL** (MINOR) — `select_for_update` is a no-op, failed statements do not abort transactions, and `pg_trgm` behaviour is untested. The `policy` CI stage is the only one touching real PostgreSQL. This gap has already masked real defects.
- **`sweep_notifications` exits 0 on partial failure** (PATCH) — individual alert generators that raise are reported to stderr but do not change the exit status, so cron cannot detect a partially failed night. Documented in `deploy.md` §13 (Scheduled jobs).
- **`/ready/` does not check the cache backend** (PATCH) — readiness opens a database connection only. In production the cache is the rate-limit store, so a failed Redis leaves throttling degraded without the readiness probe reporting it. Documented in `deploy.md` §14 (Health and observability).
- **`requirements/README.md` documents two commands that do not exist** (PATCH) — `validate_organization_integrity` and `rebuild_organization_closure`, for an `organization` app that was removed. Also referenced in `core/management/commands/reset_dev_data.py`.

## [1.1.0] - 2026-09-13

> **Verification note (added 2026-09-13).** The tag-triggered workflow for `v1.1.0` reports a
> failure on its `Tag is annotated` step. The tag is annotated — GitHub's ref API reports object
> type `tag` with a tagger and message — and the check itself is wrong: `actions/checkout` leaves
> the runner's local tag ref pointing at the commit the tag peels to, so `git cat-file -t` answers
> `commit`. Every other gate passed, including the policy-engine job on a fresh database. The check
> is fixed in 1.1.1 and takes effect from the next tag; the workflow that runs for a tag is the one
> committed at that tag, so this run cannot be made green. The release's artifacts, which the
> skipped `artifacts` job would have attached, were uploaded to the release directly.

### Security

- **Django REST Framework raised to 3.17.2** (CVE-2026-73228, GHSA-2m8g-3cmr-wg3w, medium) — versions below 3.17.2 let an oversized JSON or urlencoded body bypass Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` when read through DRF's `request.data`, which every endpoint in this project does. `DATA_UPLOAD_MAX_MEMORY_SIZE` is unset here, so the effective ceiling was the reverse proxy's `client_max_body_size` (25 MB) rather than Django's 2.5 MB default. Found by the release readiness audit's CVE pass. The companion advisory GHSA-g47c-3xmw-q6m2 does not apply: `DEFAULT_RENDERER_CLASSES` is `JSONRenderer` only, so `AdminRenderer` is never used.

### Added

- **Signature images can be uploaded and rendered** (MINOR) — `POST /api/v1/document-templates/signatories/<id>/signature/` stores a real image against a certificate signatory instead of relying on an external link. Multipart, PNG/JPG/WEBP only, 10 MB cap, with the leading bytes checked against the extension.
  - `uploaded_files` gained a **sixth owner type**, `signatory`, joining applicant, journey, offer, document, and print snapshot. One nullable `PROTECT` column plus one entry in `OWNER_FIELDS`, exactly as that app's model comments predicted; the `uploaded_file_single_owner` check constraint widens from a five-way to a six-way disjunction (migration `uploaded_files/0002_signatory_owner`).
  - `document_templates.Signatory` gained `signature_file`, a nullable `PROTECT` foreign key to the stored image (migration `0003_signatory_signature_file`) — the app's first database relation outside itself, and the project's first bidirectional app pair.
  - **`signature_image_url` is retained and still honoured**, so nothing shipped breaks. A new read-only `signature_source` field (`uploaded` / `url` / `none`) reports which of the two is in force, computed server-side because part of the rule — whether the linked file has been archived or superseded — is invisible to a client.
  - Signature files are **Admin-only** in the file ledger (`signatory` joins `ADMIN_ONLY_OWNER_TYPES`), matching `document_templates`' own Admin-only-including-reads rule. Without it a Lead Manager refused the signatory list could still have downloaded and replaced signature images through `/api/v1/files/`.
  - Signature files are **excluded from the file verification queue** and the three dashboard figures built on it. Every upload starts `pending`, and a signatory-owned row would otherwise render in Today's Work with no applicant and nowhere to click.
  - `document_templates` gained a `docs/SECURITY.md` — the first artefact in the project whose threat model is forgery rather than disclosure.

### Changed

- **Cutting a release is one command, end to end** (PATCH) — `/release <N.M.P>`, which "prepare for production" triggers, now runs the ten-point production-readiness audit, prepares the version bump, changelog, and `deploy.md`, verifies (CI, strict validators, and a production-settings smoke boot that includes one throttled request), opens the pull request into `main`, merges it, creates the annotated tag, publishes the GitHub Release with its artifacts, and merges `main` back into `dev` — ending with a release URL rather than a list of commands. `/prepare-production` is retired; its audit and first-release deliverables moved into `/release`, so two commands remain, `/pr` and `/release`. A changelog heading with no tag is now detected and published first, closing the gap that left `[1.0.0]` untagged. Moving or deleting a tag, deleting a published release, and force-pushing remain refused outright.
- **Development now follows the main/dev pull-request cycle** (PATCH) — permanent `main` (releases) and `dev` (integration); typed task branches `feature|fix|refactor|chore/<name>_<YYYYMMDD_HHMM>` that PR into `dev` and are squash-merged; temporary `release/<N.M.P>` branches from `dev` and `hotfix/*` branches from `main` that PR into `main` with a merge commit, after which `main` is merged back into `dev`. `.github/` gained `workflows/staging.yml` (release-candidate bundle on every push to `dev`), `workflows/production.yml` (renamed from `release.yml`; now also asserts the tag is annotated, on `main`, and has a changelog heading), `pull_request_template.md`, and `CODEOWNERS`; `ci.yml` runs on pull requests into `dev` and `main`. The local pre-push hook is retired (CI runs on GitHub for every pull request) and the long-lived `release/1.0.x` maintenance branch is retired.
- **The deployer contract is now `deploy.md`** (PATCH) — `GUIDE.txt` was renamed with `git mv` so its history follows, and rewritten as a 22-section Markdown contract for an autonomous deployer agent targeting a single Ubuntu 24.04 LTS host (systemd, no containers): deployer inputs, system overview, host provisioning, obtaining a release by tag, a one-file configuration contract (`/etc/grandway/grandway.env`, loaded by `EnvironmentFile=`), verification checklist, upgrade sequence, an operations runbook with a failure-signature table, and explicit agent decision rules. `deploy/` gained `grandway.service`, `grandway-sweep.service` + `.timer`, `grandway-backup.service` + `.timer`, `backup.sh`, and `manage.sh`; `crontab.sample` became a cron fallback for the sweep timer. `backend/core/docs/templates/DEPLOYMENT_TEMPLATE.md` carries the 22 headings, and every cross-reference now uses the form `deploy.md §N (Section name)`. The release workflow attaches `deploy.md` instead of `GUIDE.txt`.

### Fixed

- **GitHub CI had been failing since July** (PATCH) — `development.py` opened the gitignored `.env.development` unconditionally (crashing the `policy-engine` job) and one settings-selection test depended on the developer's gitignored repo-root `.env`. Development settings now fall back to the OS environment when the file is absent, like production and staging, and the test builds its own temporary repo. CI on GitHub is green for the first time since 2026-07-23.
- **`institutions.0001` and `clients.0001` could run before the `pg_trgm` extension existed** (PATCH) — on an empty PostgreSQL database `migrate` failed with `operator class "gin_trgm_ops" does not exist`; both migrations now depend on `applicants.0001_initial`, the earliest extension creator. Verified by migrating an empty database from scratch.
- **`redis` was not a declared dependency** (MINOR) — production and staging require `CACHE_BACKEND=django.core.cache.backends.redis.RedisCache`, but the `redis` client package was in no requirements file. Django imports it lazily, so the process booted and both probes passed, and the first rate-limited request failed with `ModuleNotFoundError: No module named 'redis'`. `redis==8.1.0` is now pinned in `requirements/production.txt` and documented in `THIRD_PARTY_LIBRARIES.md`.
- **nginx probe locations sent the upstream name as `Host`** (PATCH) — the `/health/` and `/ready/` blocks in `deploy/nginx.sample.conf` did not forward `Host`, so nginx sent `grandway` (the upstream name), Django's `ALLOWED_HOSTS` check rejected it, and every probe through the proxy returned 400 `DisallowedHost` while the same probe straight at gunicorn with a Host header returned 200. Both blocks now forward `Host` and `X-Forwarded-For`.
- **`SUPERADMIN_*` and `GUNICORN_*` are process-environment-only, and the env template said otherwise** (PATCH) — `bootstrap_superadmin`, the two `reset_superadmin_*` commands, and `deploy/gunicorn.conf.py` read these with `os.environ` directly, never through python-decouple, so placing them in a `.env.production` file did nothing. `deploy/env.production.example` now states that it must be loaded into the process environment (systemd `EnvironmentFile=` / `deploy/manage.sh`) and documents the `GUNICORN_*` block.

## [1.0.0] - 2026-09-06

> **Verification note (added 2026-09-13).** The tag-triggered workflow for `v1.0.0` fails.
> Both failures are CI-environment defects in the code at that commit — `development.py` opened the
> gitignored `.env.development` unconditionally, and one settings test read the developer's gitignored
> repo-root `.env` — and both are fixed in 1.1.0. Neither affects a production deployment: production
> and staging settings already fell back to the OS environment, and a production smoke boot of this code
> passes. `v1.1.0` is the first release whose verification workflow passes, and is what a new deployment
> should use. The tag is immutable and stays as published (§41.4).

First production release. The application has been in development since 2026-07; this release marks the point at which it is deployable by someone who did not build it.

### Added

- **Deployment contract** — `GUIDE.txt` documents everything needed to deploy, operate, back up, and roll back without reading source: runtime requirements, the complete environment-variable contract, filesystem and reverse-proxy contracts, the ordered deploy sequence, first-boot bootstrap, scheduled jobs, health endpoints, backup/restore, rollback, and the enforced security posture.
- **Reference deployment configs** — `deploy/env.production.example`, `deploy/gunicorn.conf.py`, `deploy/nginx.sample.conf`, and `deploy/crontab.sample`, all target-agnostic.
- **Operator README** — repository entry point with a routing table to the contract written for each audience.
- **Development env template** — `deploy/env.development.example`, tracked alongside the production one. The README's quick start told a new developer to copy `.env.development.example`, but every dotted env file is gitignored, so that template had never reached a clone; the first step of the quick start failed on a clean checkout.
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
- **A stray `.env` can no longer downgrade a production host** — environment selection had one path that failed open: `ENVIRONMENT` unset *with* a developer's `.env` present silently selected development settings — `DEBUG=True`, no HTTPS redirect, no HSTS, no secure cookies, stack traces to clients — with no error and no warning. A deploy that copies a working directory (rsync, a `docker COPY` of the tree, a VM image built from a checkout) could carry one. Boot now refuses when the production env file is present and a `.env` disagrees.
- **`GUIDE.txt` no longer documents a recovery command that does not exist** — the admin-lockout section listed `manage.py addstatictoken` as an emergency lever, but `otp_static` is deliberately not installed (recovery codes are concept-locked out), so the command fails with `Unknown command`. `reset_superadmin_mfa` is the only superadmin MFA recovery path and the section now says so.

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

[Unreleased]: https://github.com/CodeResound/grandway/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/CodeResound/grandway/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/CodeResound/grandway/releases/tag/v1.0.0
