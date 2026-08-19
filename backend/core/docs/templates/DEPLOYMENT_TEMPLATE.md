<!-- Copy this file's structure into the repo-root GUIDE.txt when running /prepare-production,
and refresh it on every /release (CLAUDE.md §41.7). Delete this comment block.

AUDIENCE: a DevOps engineer or deployer agent in ANOTHER machine/repository who will deploy
this application WITHOUT reading its source. Everything they need must be in this one file.
What the author finds obvious is exactly what this reader lacks — when in doubt, state it.

HARD RULES (posture inherited from INTEGRATION_TEMPLATE.md / CLAUDE.md §19.3):
1. Use the 14 section headings below verbatim, in order. Omit nothing; a section with nothing
   to say states the literal `none` and why.
2. EXTRACT every value from the code (settings modules, config() reads, management commands,
   CI scripts) — never assume or invent. Anything not pinned down goes in §14 Gaps.
3. Every command is copy-paste runnable from a fresh clone. Every env var in §3 names what
   reads it and what breaks without it.
4. This file is a living contract: refreshed by every release; drift between it and the tagged
   code makes the release incomplete (§41.5 step 1).
5. GUIDE.txt is exempt from §19.2 rules 1–2 (§41.9) — no metadata block or Change History
   table; the release version and date go in the title line instead.
-->

# <Project> — Deployment Guide (v<N.M.P>, <YYYY-MM-DD>)

## 1. Module

- Application entrypoint (WSGI/ASGI path, e.g. `core.wsgi:application`), and any required working directory or `PYTHONPATH` note (e.g. the server must `--chdir backend/`).
- Language + exact runtime version. Framework + version.
- Where the version is visible at runtime (e.g. `GET /health/` → `version`).

## 2. Runtime requirements

- Database engine + major version, and **why specifically** (features the app depends on — extensions, index types — that a substitute engine lacks).
- Who creates required database extensions (a migration? manual step?).
- Cache/shared-store requirements and the single-worker escape hatch, if any.
- Anything deliberately NOT required (broker, object storage, external APIs) — say so, so the deployer doesn't provision it.

## 3. Configuration contract

- How the environment is selected (exact variable, and **where it is read from** — process environment vs an env file, and in what order). Call out explicitly if the selection variable cannot live in the env file itself.
- Which env file the production settings read, and the fallback when absent (e.g. "OS environment only — a container injecting env vars must not ship the file").
- The full variable table: `Variable | Required | Default | What reads it | What breaks without it`. Every mandatory variable's failure mode is "refuses to boot" — if not, that is a §14 gap.
- Pointer to the committed example file (e.g. `deploy/env.production.example`) and secret-generation one-liners.

## 4. Filesystem contract

- Every path the process must be able to write, when it is created (import time? first request?), and what happens if it can't.
- Media/upload storage: location variable, permission bits, whether it may ever be URL-served, backup priority.
- Static files: where `collectstatic` writes, who serves it (see §5).

## 5. Reverse proxy contract

- TLS termination requirements and the exact forwarded-proto header rule: the proxy MUST set it and MUST strip any client-supplied value (state what breaks in each failure direction — redirect loop / voided secure cookies).
- The proxy-hop count variable and what it must equal.
- What the proxy serves directly (static) and what it must NEVER serve (media), with a verbatim sample config block (reference the committed `deploy/nginx.sample.conf`).

## 6. Process model

- The exact server invocation (reference `deploy/gunicorn.conf.py` or equivalent).
- Worker-count coupling: anything that multiplies or breaks per-worker (rate-limit stores, file-handler logging). Name known limitations honestly.
- Restart/reload semantics and graceful-shutdown expectations.

## 7. Deploy sequence

The ordered, idempotent steps of every deploy (not just the first):

1. Install pinned production requirements
2. Collect static files
3. Apply migrations
4. Sync/validate any registry or derived state the app requires (state explicitly which steps run on EVERY deploy vs first boot only)
5. Start/reload the application server
6. Poll the readiness endpoint until healthy

State the failure rule: which step's non-zero exit MUST abort the deploy.

## 8. First-boot bootstrap

- The one-time commands (superadmin creation, seeds) in order, with flags.
- Credential handling: what is generated vs supplied, what is printed once, what must be changed on first login.
- **Lockout warnings:** any auth gate (MFA/OTP on the admin) that can lock the operator out on day one, and the named recovery commands.

## 9. Scheduled jobs

- Every command intended to run on a schedule: name, cadence, idempotency, what breaks if it never runs, the env it needs. Reference the committed `deploy/crontab.sample`.
- `none` if the release has no scheduled jobs.

## 10. Health and observability

- Liveness vs readiness endpoints: exact paths, what each checks, expected status codes, which one the load balancer should use, and confirmation they are public, unthrottled, and exempt from any HTTPS redirect.
- Log destinations and format; the request-correlation header if any.

## 11. Backup and restore

- The complete list of sources of truth (database, media volume — and nothing else, if the architecture says so).
- The restore sequence, including any post-restore steps (registry re-sync) without which the restore is incomplete.

## 12. Rollback

- The supported rollback unit (tag-to-tag) and the honest constraints: are migrations reversible? What is the policy when they aren't (forward-fix, restore)?

## 13. Security posture summary

One line per control already enforced by the application, so the deployer does not undo one at the proxy or "simplify" it away: HTTPS redirect + exemptions, HSTS (flag preload as a one-way door), secure cookies, frame/content-type headers, login lockout, admin MFA, media never URL-served, mandatory-env fail-closed boots.

## 14. Gaps

What this contract deliberately does NOT decide (packaging: container vs bare metal; secret store; TLS issuance; the shared-cache instance) and every known unknown a deployer must resolve. Specific only; never fabricate.
