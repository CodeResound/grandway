<!-- Title must be a commit subject: `<type>(<app>): <imperative description>` — it becomes the squash commit on dev. -->

## Summary

<!-- What and why, one paragraph. -->

## Base / merge method

- [ ] `feature|fix|refactor|chore/*` → `dev` (squash merge)
- [ ] `release/*` or `hotfix/*` → `main` (merge commit; tag afterwards; then merge `main` → `dev`)
- [ ] merge-back `main` → `dev` (merge commit)

## Change type

- [ ] Feature
- [ ] Bug fix
- [ ] Refactor
- [ ] Chore or docs
- [ ] Hotfix
- [ ] Release

## Contracts

- [ ] API contract changed → `API.md` / `INTEGRATION.md` updated
- [ ] Data contract changed → `DATA_CONTRACT.md` updated
- [ ] Migration included (`makemigrations --check` clean)
- [ ] Policy registry artifacts regenerated
- [ ] Breaking change (MAJOR) described below

## Verification

<!-- Paste the tail of `bash scripts/ci.sh` with its exit code. -->

## Session

- Branch: `<type>/<change_name>_<YYYYMMDD_HHMM>`
- Iteration log: `iterations/<YYYYMMDD_HHMM>_<apps>.md`
- Deferred items added to CHANGELOG `### Deferred`: yes / no
