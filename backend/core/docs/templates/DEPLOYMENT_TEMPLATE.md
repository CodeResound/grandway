<!-- Copy this file's structure into the repo-root deploy.md when running /prepare-production,
and refresh it on every /release (CLAUDE.md §41.7). Delete this comment block.

AUDIENCE: an autonomous deployer agent, or a DevOps engineer, on ANOTHER machine who will
deploy this application WITHOUT reading its source and then operate it. Everything they need
must be in this one file. What the author finds obvious is exactly what this reader lacks —
when in doubt, state it.

HARD RULES (posture inherited from INTEGRATION_TEMPLATE.md / CLAUDE.md §19.3):
1. Use the 22 section headings below verbatim, in order. Omit nothing; a section with nothing
   to say states the literal `none` and why.
2. EXTRACT every value from the code (settings modules, config() reads, management commands,
   CI scripts) — never assume or invent. Anything not pinned down goes in §22 Gaps.
3. Every command is copy-paste runnable from a fresh clone. Every env var in §7 names what
   reads it, where it is read from (process environment vs env file), and what breaks without it.
4. This file is a living contract: refreshed by every release; drift between it and the tagged
   code makes the release incomplete (§41.5 step 1).
5. deploy.md is exempt from §19.2 rules 1–2 (§41.9) — no metadata block or Change History
   table; the release version and date go in the title line instead.
6. Every command is runnable as root on a fresh Ubuntu LTS host from a fresh shell; every
   loopback probe carries the Host header; nothing runs manage.py as root.
7. Cross-references from code and other docs use the form `deploy.md §N (Section name)` so a
   renumbering is caught by grep.
-->

# <Project> — Deployment Guide (v<N.M.P>, <YYYY-MM-DD>)

One preamble paragraph: audience, target platform, the "refreshed at every release" rule, the companion files under `deploy/`, and the command conventions (run as root unless prefixed; variables exported in §1 are reused everywhere).

## 1. Deployer inputs

- A table `Input | Example | Used in | Escalate if unknown` covering: the release tag (must equal the `VERSION` file), repository URL (+ credentials if private), the API hostname (→ allowed hosts), the frontend origin(s) (→ CORS/CSRF), the proxy hop count, the TLS contact email, the first administrator's identity, a human channel for one-time secrets, the off-host backup destination, the maintenance window, and a sizing note.
- End with one shell block exporting every input as a variable that every later command reuses.

## 2. System overview

- One paragraph: what the product is and who uses it. The actors/authority levels.
- The URL surface (every routed prefix), the registered endpoint count, and an app inventory table `App | Base path | One line`.
- Sources of truth vs derived stores. The auth mechanics an operator sees (token lifetimes, cookie name/path/flags, device limits, session expiry). Throttle rates. Upload limits. Time semantics (stored timezone vs business timezone).
- External contracts: outbound integrations (or `none`), inbound callers, machine-readable artifacts shipped with the release. Sensitive-data classes.

## 3. Module

- Application entrypoint (WSGI/ASGI path, e.g. `core.wsgi:application`), and any required working directory or `PYTHONPATH` note (e.g. the server must `--chdir backend/`).
- Language + exact runtime version. Framework + version.
- Where the version is visible at runtime (e.g. `GET /health/` → `version`).

## 4. Runtime requirements

- Database engine + major version, and **why specifically** (features the app depends on — extensions, index types — that a substitute engine lacks).
- Who creates required database extensions (a migration? manual step?).
- Cache/shared-store requirements and the single-worker escape hatch, if any.
- Anything deliberately NOT required (broker, object storage, external APIs) — say so, so the deployer doesn't provision it.

## 5. Host provisioning

- OS packages, in one copy-paste block; the service user; every directory with owner and mode in a table and the `install -d` commands that create them; database role/database/extension SQL; cache configuration lines and how to verify them; firewall rules; clock/NTP requirement.

## 6. Obtaining a release

- Clone-at-tag commands as the service user, and the verification that HEAD is the tag and the `VERSION` file matches.
- Virtualenv creation with the exact interpreter.
- What the clone does and does not contain; the release artifacts and what they are for; unsupported forms (tarballs).

## 7. Configuration contract

- How the environment is selected (exact variable, and **where it is read from** — process environment vs an env file, and in what order). Call out explicitly if the selection variable cannot live in the env file itself.
- Which env file the production settings read, and the fallback when absent (e.g. "OS environment only — a container injecting env vars must not ship the file").
- The full variable table: `Variable | Required | Default | Read by | Read from | What breaks without it`. Every mandatory variable's failure mode is "refuses to boot" — if not, that is a §22 gap. Include variables read from the process environment only (application-server and bootstrap variables), and name anything that looks like a variable but is not read.
- Pointer to the committed example file (e.g. `deploy/env.production.example`), secret-generation one-liners, and the exact install command (owner, group, mode) for the env file.

## 8. Filesystem contract

- Every path the process must be able to write, when it is created (import time? first request?), and what happens if it can't.
- Media/upload storage: location variable, permission bits, whether it may ever be URL-served, backup priority.
- Static files: where `collectstatic` writes, who serves it (see §9).

## 9. Reverse proxy contract

- TLS termination requirements and the exact forwarded-proto header rule: the proxy MUST set it and MUST strip any client-supplied value (state what breaks in each failure direction — redirect loop / voided secure cookies).
- The proxy-hop count variable and what it must equal.
- What the proxy serves directly (static) and what it must NEVER serve (media), with a verbatim sample config block (reference the committed `deploy/nginx.sample.conf`).

## 10. Process model

- The exact server invocation (reference `deploy/gunicorn.conf.py` or equivalent).
- Worker-count coupling: anything that multiplies or breaks per-worker (rate-limit stores, file-handler logging). Name known limitations honestly.
- Restart/reload semantics and graceful-shutdown expectations.

## 11. Deploy sequence

The ordered, idempotent steps of every deploy (not just the first):

1. Install pinned production requirements
2. Collect static files
3. Apply migrations
4. Sync/validate any registry or derived state the app requires (state explicitly which steps run on EVERY deploy vs first boot only)
5. Start/reload the application server
6. Poll the readiness endpoint until healthy

State the failure rule: which step's non-zero exit MUST abort the deploy.

## 12. First-boot bootstrap

- The one-time commands (superadmin creation, seeds) in order, with flags.
- Credential handling: what is generated vs supplied, what is printed once, what must be changed on first login.
- **Lockout warnings:** any auth gate (MFA/OTP on the admin) that can lock the operator out on day one, and the named recovery commands.

## 13. Scheduled jobs

- Every command intended to run on a schedule: name, cadence, idempotency, what breaks if it never runs, the env it needs. Reference the committed `deploy/crontab.sample`.
- `none` if the release has no scheduled jobs.

## 14. Health and observability

- Liveness vs readiness endpoints: exact paths, what each checks, expected status codes, which one the load balancer should use, and confirmation they are public, unthrottled, and exempt from any HTTPS redirect.
- Log destinations and format; the request-correlation header if any.

## 15. Verification checklist

- Numbered commands, each with its expected output, covering: services active, build identity, readiness, TLS/HSTS headers, HTTP→HTTPS redirect, the error envelope on an unauthenticated call, **at least one throttled request** proving the shared cache is reachable, static served, media not served and not readable by the web server, framework deployment checks, no unapplied migrations, registry validation, timers present, no tracebacks in the recent log, configuration-hygiene checks, certificate renewal dry run.

## 16. Upgrade sequence

- Distinct from the first deploy: read and classify the release notes (which classes proceed alone, which escalate), snapshot **before** migrating, fetch and verify the tag, diff every shipped operational file (units, proxy config, env template) against its installed copy, install/collect/migrate/sync/validate, reload vs restart, poll, verify the new version, then run §15. What to do if a failure happens after migrations ran.

## 17. Backup and restore

- The complete list of sources of truth (database, media volume — and nothing else, if the architecture says so).
- The restore sequence, including any post-restore steps (registry re-sync) without which the restore is incomplete.

## 18. Rollback

- The supported rollback unit (tag-to-tag) and the honest constraints: are migrations reversible? What is the policy when they aren't (forward-fix, restore)?

## 19. Operations runbook

- Lifecycle commands (status/start/stop/reload/restart, log following, timers, cache and disk checks, secret rotation and its effect).
- A failure-signature table `Symptom | Where seen | Cause | Fix`, quoting the literal messages the code emits.

## 20. Security posture summary

One line per control already enforced by the application, so the deployer does not undo one at the proxy or "simplify" it away: HTTPS redirect + exemptions, HSTS (flag preload as a one-way door), secure cookies, frame/content-type headers, login lockout, admin MFA, media never URL-served, mandatory-env fail-closed boots. Then the host posture this guide adds.

## 21. Agent decision rules

- Three lists for an autonomous deployer: **MAY decide alone**, **MUST escalate** (stop and report before acting), **NEVER** (refuse regardless of approval).

## 22. Gaps

What this contract deliberately does NOT decide (secret store beyond the env file; off-host backup; monitoring; retention) and every known unknown a deployer must resolve, plus every `Deferred` item from `CHANGELOG.md` that is operator-visible. Specific only; never fabricate.
