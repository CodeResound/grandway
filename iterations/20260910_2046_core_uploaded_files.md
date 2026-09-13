# Session 20260910_2046 — adopt the main/dev git cycle and the deploy.md deployer contract (branch `chore/adopt_universal_git_structure_20260910_2046`)

## Core

## 1. Module
- Name: Core
- Base path: `/api/v1/`
- Auth: unchanged this session

## 2. Conventions
- Response: unchanged
- Error: unchanged
- Auth failures: unchanged
- Pagination: unchanged
- IDs: unchanged
- Times: unchanged
- List/search/filter/order params: unchanged

## 3. Models
- No model changes. No migration was generated; `makemigrations --check` is clean.

## 4. Enums
- No changes.

## 5. Dependency order
- No changes.

## 6. Endpoints
No endpoint was added, changed, or retired this session. The session changed governance (the git cycle), deployment files, and one runtime dependency; no view, serializer, service, selector, or registry file was modified. Two observable changes for a deployer rather than an API client:
- `requirements/production.txt` now pins `redis==8.1.0`, so a production process configured with `CACHE_BACKEND=django.core.cache.backends.redis.RedisCache` no longer returns a 500 on the first rate-limited request.
- `backend/core/settings/__init__.py` error text for the stray-`.env` refusal now points at `deploy.md §7 (Configuration contract)` instead of `GUIDE.txt`.

## 7. Flows

**Land a session's work** (the new cycle, replaces ff-only pushes to `main`)
1. `/start-session <type> <change_name>` — `scripts/git_audit.sh --quick` must show no `FAIL` (a pending `main → dev` merge-back blocks here), then branch `<type>/<change_name>_<ts>` from `dev`.
2. Work, commit with `-m "<type>(<app>): …"` — `enforce_branch_policy.sh` refuses any other branch name or subject.
3. `/end-session` — iteration log, `scripts/ci.sh` green, `git push -u origin <branch>`, `gh pr create --base dev`, STOP.
4. Human squash-merges; GitHub deletes the remote branch; the next `/start-session` prunes the local copy once GitHub reports the PR merged.
   - `gh pr merge` from an agent, a push to `main`/`dev`, a tag, or a release mutation is blocked by `block_release_ops.sh`.

**Cut a release** (`/release N.M.0`)
1. Audit green, `release/N.M.0` cut from `dev`; bump `VERSION`, move `[Unreleased]` into the release section, review `### Deferred`, refresh `deploy.md`.
2. Verify, push (pre-push gates run), `gh pr create --base main`, STOP.
3. Human: merge commit, annotated tag on `main`, `gh release create --verify-tag`, then merge `main` back into `dev`.
   - `production.yml` fails the tag if `VERSION`, `core.__version__`, the tag, or the changelog heading disagree, if the tag is lightweight, or if it is not reachable from `main`.

**Ship a hotfix** (`/hotfix <change_name>`)
1. Branch from `main`; regression test, fix, `VERSION` to N.M.(P+1), changelog section, `deploy.md` if operator-visible.
2. Verify, `/end-session --base main`, STOP; human merges, tags, releases, merges back into `dev`.

**Deploy or upgrade the VPS** (`deploy.md`)
1. §1 inputs → §5 host provisioning → §6 clone at tag → §7 `/etc/grandway/grandway.env` → §9 nginx + TLS → §11 deploy sequence → §12 bootstrap and TOTP enrolment → §15 verification checklist.
2. Upgrade: §16 (snapshot with `deploy/backup.sh pre-<tag>`, checkout new tag, diff `deploy/*` against installed copies, migrate, sync, validate, reload or restart, §15 again).
   - Failure after migrate → §18 rollback; any restore or migration-boundary rollback escalates per §21.

## 8. Gaps
- **`dev` does not exist yet and no tag exists.** This bootstrap session branched from `main` and its PR targets `main`; `dev`, branch protection, repository merge settings, the retirement of `release/1.0.x`, and the `v1.0.0` tag are human-only steps printed in the completion report. `scripts/git_audit.sh` reports two `FAIL` lines (missing `dev`) until they run.
- **`gh` is not authenticated on this machine**, so `/end-session` could only print the `gh pr create` command, and the hook's MERGED check for pruning task branches cannot succeed until `gh auth login`.
- **`deploy.md` has not been rehearsed on a fresh host.** Every command was extracted from code and dry-run where possible (collectstatic, sweeps, seeds, validators, `check --deploy`, the TOTP one-liner, the redis import path), but the §5–§15 sequence on a clean Ubuntu 24.04 VM is a follow-up for the deployer agent; the §15 throttled-login check is the proof the redis fix works end to end.
- `deploy.md §22` lists the remaining undecided items: Redis version on the host, nginx `http2` directive compatibility, off-host backup destination, restore rehearsal, journald retention, Redis `requirepass`, monitoring, Python-version enforcement, horizontal scaling.
- The `v1.0.0` GitHub release, once created, attaches the `GUIDE.txt` present at that commit; `deploy.md` ships from 1.1.0.

## Uploaded Files

## 1. Module
- Name: Uploaded Files
- Base path: `/api/v1/files/`
- Auth: unchanged this session

## 2. Conventions
- Response: unchanged
- Error: unchanged
- Auth failures: unchanged
- Pagination: unchanged
- IDs: unchanged
- Times: unchanged
- List/search/filter/order params: unchanged

## 3. Models
- No model changes. The only edit is the docstring of migration `0002_signatory_owner`, whose rollback note now cites `deploy.md §18 (Rollback)` (it previously cited a GUIDE.txt section number that pointed at the security posture, not rollback). No operations changed; `makemigrations --check` is clean.

## 4. Enums
- No changes.

## 5. Dependency order
- No changes.

## 6. Endpoints
No endpoint was added, changed, or retired this session.

## 7. Flows
- No flow changes this session.

## 8. Gaps
- None specific to this app this session.
