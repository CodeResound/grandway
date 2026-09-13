# Grandway — Education Consultancy Platform (Backend)

**Version:** 1.0.0
**Status:** Active
**Created:** 2026-08-19
**Audience:** Anyone arriving at this repository — maintainers, operators, and integrators. Start here, then follow the routing table in §3 to the document written for your job.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-19 | AI (Claude Opus 5) | Initial operator README, created during v1.0.0 production preparation |
| 1.1.0 | 2026-09-10 | AI (Claude Fable 5.1) | Adopt the main/dev PR-based git cycle; `GUIDE.txt` becomes `deploy.md`; endpoint count 180 |
| 1.1.1 | 2026-09-13 | AI (Claude Opus 5) | Releases are cut by one command end to end; §6 rewritten |

---

## 1. What this is

Grandway is the backend for an education consultancy operating in Nepal: it tracks a student from first enquiry through applications, offers, documents, and visa journeys, and records who did what, when, and under whose authority at every step. Every record is auditable and every endpoint is registered in a permission registry before it exists.

It is an API-only Django service. There is no server-rendered UI beyond the Django admin, which exists for operations staff and is gated behind mandatory TOTP.

## 2. Status

| | |
|---|---|
| Version | 1.0.0 |
| Runtime | Python 3.12 |
| Framework | Django 5.2 LTS · Django REST Framework 3.17 |
| Database | PostgreSQL 16 (required — see `deploy.md` §4 (Runtime requirements)) |
| Auth | JWT (SimpleJWT), Argon2id hashing, django-axes lockout, TOTP-gated admin |
| Apps | 18 business apps + `core` |
| Endpoints | 180, all registered in the policy engine |
| Tests | 1521 |

## 3. Where to go next

| You are… | Read | Why |
|---|---|---|
| **Deploying this** | **`deploy.md`** | The complete deployment contract for an operator or an autonomous deployer agent: deployer inputs, host provisioning, obtaining a release, every environment variable, filesystem and reverse-proxy contracts, the ordered deploy and upgrade sequences, first-boot bootstrap, verification checklist, backup, rollback, operations runbook, and agent decision rules. Written so you never need to read source. |
| Configuring an environment | `deploy/env.production.example` (production) · `deploy/env.development.example` (local) | Every variable, annotated, with the mandatory ones flagged. The templates live under `deploy/` rather than as dotted `.env.*` files precisely so they reach a fresh clone. |
| Building a client against the API | `backend/core/docs/INTEGRATION.md` | The project-level consumer contract: global conventions, app inventory, cross-app dependency graph. Then each app's own `docs/INTEGRATION.md`. |
| Building the frontend | `FRONTEND_README.md` | How to read the concept files, flow maps, and integration contracts together. |
| Understanding *why* something exists | `concepts/project_overview.txt`, `concepts/<app>.txt` | Product intent and grounding, authored before each app was built. |
| Maintaining a specific app | `backend/<app>/docs/` | `API.md`, `DATA_CONTRACT.md`, `DEBUG_HISTORY.md`, and where relevant `SECURITY.md`. |
| Tracking what changed | `CHANGELOG.md` | Release history, and the `### Deferred` registry of known-but-not-yet-fixed items. |
| Starting a new project from this template | `docs/TEMPLATE_GUIDE.txt` | Historical — describes the empty platform template this repository grew from. |

## 4. Local development

Requires Python 3.12 and a reachable PostgreSQL.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements/development.txt


cp deploy/env.development.example .env.development   # then edit the DB credentials
echo "ENVIRONMENT=development" > .env                # selects the settings module

python backend/manage.py migrate
python backend/manage.py bootstrap_superadmin        # prints a generated password once
python backend/manage.py sync_policy_registry
python backend/manage.py validate_policy_engine --strict
python backend/manage.py seed_document_templates --activate

python backend/manage.py runserver
```

Work always happens on a typed branch and lands in `dev` through a pull request (§6); CI runs on GitHub for every pull request.

Full command inventory, including the ordered fresh-database sequence: `requirements/README.md`.

## 5. Checks

`scripts/ci.sh` is the single source of truth for every mechanical gate, run identically by GitHub Actions and by hand:

```bash
bash scripts/ci.sh                 # all stages
bash scripts/ci.sh lint migrations # a subset, in the order given
```

| Stage | Checks | Needs a database |
|---|---|---|
| `lint` | `ruff check` + `ruff format --check` | no |
| `migrations` | every model change has a migration | no |
| `export` | committed policy/OpenAPI artifacts are fresh | no |
| `docs` | every registered endpoint has a consumer contract | no |
| `test` | the full pytest suite (SQLite) | no |
| `policy` | migrate → sync registry → validate registry | **yes** |

## 6. Branching, versioning, and releases

Work follows one fixed cycle (the maintainer's rulebook is `.claude/CLAUDE.md` §34/§41 — governance is local to a checkout and is not published):

| Branch | Base | Pull request into | Merge method | Who merges |
|---|---|---|---|---|
| `feature/*` `fix/*` `refactor/*` `chore/*` | `dev` | `dev` | squash | the author, end to end |
| `release/<N.M.P>` | `dev` | `main` | merge commit | the author, end to end |
| `hotfix/<name>_<ts>` | `main` | `main` | merge commit | the author, end to end |
| merge-back `main → dev` (after every release or hotfix) | — | `dev` | merge commit | the author, same run as the release |
| `main`, `dev` | — | protected, PR-only | — | — |

Task branches are named `<type>/<change_name>_<YYYYMMDD_HHMM>` and are deleted by GitHub when their PR merges. `main` always represents the latest release; `dev` the latest integrated code. Local clones stay in sync with GitHub: fetch with prune, fast-forward `main`/`dev`, and drop local branches whose remote is gone at the start and end of every task.

Semantic versioning applies to the deployed application, distinct from the `/api/v1/` URL prefix. Releases are immutable: `v1.0.0` is an annotated tag on `main` plus a GitHub Release, and it never moves — a release found wrong is superseded by the next PATCH, never rewritten. A bug fixed in a deployed version becomes `v1.0.1`, developed on a `hotfix/*` branch from `main` and merged back into `dev`.

Cutting a release runs one command, which audits production readiness, verifies, merges into `main`, tags, publishes the GitHub Release with its artifacts, and merges `main` back into `dev`. `.github/workflows/production.yml` independently verifies every tag (version chain, annotated tag, reachable from `main`, changelog heading present) and attaches the artifacts a consumer cannot reconstruct without cloning; `staging.yml` packages a release candidate from every push to `dev`. A deployer pulls a version with `git checkout vN.M.P` and follows `deploy.md`.

## 7. Ownership

Maintained by CodeResound. Repository: `https://github.com/CodeResound/grandway`.
