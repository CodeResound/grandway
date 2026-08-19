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

---

## 1. What this is

Grandway is the backend for an education consultancy operating in Nepal: it tracks a student from first enquiry through applications, offers, documents, and visa journeys, and records who did what, when, and under whose authority at every step. Every record is auditable and every endpoint is registered in a permission registry before it exists.

It is an API-only Django service. There is no server-rendered UI beyond the Django admin, which exists for operations staff and is gated behind mandatory TOTP.

## 2. Status

| | |
|---|---|
| Version | 1.0.0 |
| Runtime | Python 3.12 |
| Framework | Django 5.2 LTS · Django REST Framework 3.16 |
| Database | PostgreSQL 16 (required — see `GUIDE.txt` §2) |
| Auth | JWT (SimpleJWT), Argon2id hashing, django-axes lockout, TOTP-gated admin |
| Apps | 18 business apps + `core` |
| Endpoints | 179, all registered in the policy engine |
| Tests | 1521 |

## 3. Where to go next

| You are… | Read | Why |
|---|---|---|
| **Deploying this** | **`GUIDE.txt`** | The complete deployment contract: runtime requirements, every environment variable, filesystem and reverse-proxy contracts, the ordered deploy sequence, first-boot bootstrap, backup, and rollback. Written so you never need to read source. |
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

git config core.hooksPath .githooks     # once per clone — enables the pre-push CI gate

cp deploy/env.development.example .env.development   # then edit the DB credentials
echo "ENVIRONMENT=development" > .env                # selects the settings module

python backend/manage.py migrate
python backend/manage.py bootstrap_superadmin        # prints a generated password once
python backend/manage.py sync_policy_registry
python backend/manage.py validate_policy_engine --strict
python backend/manage.py seed_document_templates --activate

python backend/manage.py runserver
```

`git config core.hooksPath .githooks` is not carried by a clone and must be run in every working copy — without it, pushes to `main` skip the local CI gate entirely.

Full command inventory, including the ordered fresh-database sequence: `requirements/README.md`.

## 5. Checks

`scripts/ci.sh` is the single source of truth for every mechanical gate, run identically by the pre-push hook, GitHub Actions, and by hand:

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

## 6. Versioning and releases

Semantic versioning on the deployed application, distinct from the `/api/v1/` URL prefix — see `.claude/CLAUDE.md` §41 (governance is local to a maintainer's checkout and is not published).

Releases are immutable: `v1.0.0` is an annotated tag plus a GitHub Release, and it never moves. A bug fixed in a deployed version becomes `v1.0.1`, developed on the `release/1.0.x` maintenance branch while `main` moves on. Tags are cut by a human maintainer only.

`main` always represents the latest code.

## 7. Ownership

Maintained by CodeResound. Repository: `https://github.com/CodeResound/grandway`.
