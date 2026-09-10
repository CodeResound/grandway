#!/usr/bin/env bash
#
# git_audit.sh — read-only audit of the repository's git cycle (CLAUDE.md §34, §41).
#
# Verifies that this clone, its remote, and the hosting configuration agree with
# the branch cycle the project enforces:
#
#   main            permanent, production-ready, PR-only, tagged vN.M.P (annotated, human-only)
#   dev             permanent, integration, PR-only; receives the main -> dev merge-back
#                   after every merge into main
#   feature|fix|refactor|chore/<name>_<YYYYMMDD_HHMM>
#                   from dev, PR into dev, squash-merged
#   hotfix/<name>_<YYYYMMDD_HHMM>
#                   from main, PR into main, merge commit
#   release/N.M.P[-rc.N]
#                   from dev, PR into main, merge commit
#
# Prints one line per check, prefixed OK / WARN / FAIL / SKIP / INFO, reports every
# finding (it never stops at the first), and exits 1 if any check FAILed.
#
# Usage:
#   scripts/git_audit.sh            full audit (fetches origin, queries GitHub via gh)
#   scripts/git_audit.sh --quick    offline: no fetch, no gh, no protection/settings checks
#   scripts/git_audit.sh --help
#
# Portable: derives owner/repo from `gh repo view` or the origin URL, and reads the
# expected hosting configuration from .github/branch-protection/*.json and
# .github/repo-settings.json. Needs bash 3.2+ (no associative arrays, no mapfile),
# git, and optionally gh plus jq or python3 for the JSON comparisons.
set -uo pipefail

usage() {
  sed -n '3,29p' "$0" | sed 's/^# \{0,1\}//'
}

QUICK=0
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "git_audit: unknown argument '$arg' (try --help)" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

N_FAIL=0
N_WARN=0
ok()   { printf 'OK    %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; N_WARN=$((N_WARN + 1)); }
fail() { printf 'FAIL  %s\n' "$*"; N_FAIL=$((N_FAIL + 1)); }
skip() { printf 'SKIP  %s\n' "$*"; }
info() { printf 'INFO  %s\n' "$*"; }

TASK_RE='^(feature|fix|refactor|chore|hotfix)/[a-z0-9_]{1,30}_[0-9]{8}_[0-9]{4}$'
RELEASE_RE='^release/[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$'
LEGACY_RE='^release/[0-9]+\.[0-9]+\.x$'

if [ "$QUICK" -eq 1 ]; then
  info "mode: --quick (no fetch, no gh, no hosting checks)"
  MAIN_REF="main"
  DEV_REF="dev"
else
  info "mode: full"
  MAIN_REF="origin/main"
  DEV_REF="origin/dev"
fi

ref_exists() { git show-ref --verify --quiet "$1"; }

# --- JSON helpers: jq if present, python3 otherwise ---------------------------------
JSON_TOOL=""
if command -v jq >/dev/null 2>&1; then
  JSON_TOOL="jq"
elif command -v python3 >/dev/null 2>&1; then
  JSON_TOOL="python3"
fi

# json_contexts <file> -> sorted, comma-joined required_status_checks.contexts
json_contexts() {
  case "$JSON_TOOL" in
    jq) jq -r '.required_status_checks.contexts | sort | join(",")' "$1" 2>/dev/null ;;
    python3) python3 -c 'import json,sys; print(",".join(sorted(json.load(open(sys.argv[1]))["required_status_checks"]["contexts"])))' "$1" 2>/dev/null ;;
    *) return 1 ;;
  esac
}

# json_field <file> <key> -> scalar rendered as JSON (true / false / "PR_TITLE" ...)
json_field() {
  case "$JSON_TOOL" in
    jq) jq -c --arg k "$2" '.[$k]' "$1" 2>/dev/null ;;
    python3) python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))[sys.argv[2]]))' "$1" "$2" 2>/dev/null ;;
    *) return 1 ;;
  esac
}

# json_stdin_field <key> -> scalar from a JSON document on stdin, rendered as JSON
json_stdin_field() {
  case "$JSON_TOOL" in
    jq) jq -c --arg k "$1" '.[$k]' 2>/dev/null ;;
    python3) python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get(sys.argv[1])))' "$1" 2>/dev/null ;;
    *) return 1 ;;
  esac
}

# --- 1. hooks path --------------------------------------------------------------------
hooks_path="$(git config core.hooksPath 2>/dev/null || true)"
if [ "$hooks_path" = ".githooks" ]; then
  ok "core.hooksPath is .githooks"
else
  fail "core.hooksPath is '${hooks_path:-<unset>}' — fix: git config core.hooksPath .githooks"
fi

# --- 2. gh auth + owner/repo -----------------------------------------------------------
GH_AUTH=0
OWNER_REPO=""
if [ "$QUICK" -eq 0 ]; then
  if ! command -v gh >/dev/null 2>&1; then
    warn "gh CLI not installed — hosting checks will be skipped"
  elif gh auth status >/dev/null 2>&1; then
    GH_AUTH=1
    ok "gh is authenticated"
    OWNER_REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
  else
    warn "gh is not authenticated (gh auth login) — hosting checks will be skipped"
  fi
fi
if [ -z "$OWNER_REPO" ]; then
  origin_url="$(git remote get-url origin 2>/dev/null || true)"
  # https://host/owner/repo(.git) | git@host:owner/repo(.git) | ssh://git@host/owner/repo(.git)
  OWNER_REPO="$(printf '%s' "$origin_url" \
    | sed -E 's#^(https?://[^/]+/|ssh://[^/]+/|[^@]+@[^:]+:)##; s#/+$##; s#\.git$##')"
fi
if [ -n "$OWNER_REPO" ]; then
  info "repository: $OWNER_REPO"
else
  warn "could not determine owner/repo (no origin remote?)"
fi

# --- 3. fetch ----------------------------------------------------------------------------
if [ "$QUICK" -eq 0 ]; then
  if git fetch --prune origin >/dev/null 2>&1; then
    ok "fetched origin (--prune)"
  else
    warn "git fetch --prune origin failed — continuing with stale remote-tracking refs"
  fi
fi

# --- 4. permanent branches exist ---------------------------------------------------------
have_local_main=0; have_remote_main=0; have_local_dev=0; have_remote_dev=0
ref_exists refs/heads/main && have_local_main=1
ref_exists refs/remotes/origin/main && have_remote_main=1
ref_exists refs/heads/dev && have_local_dev=1
ref_exists refs/remotes/origin/dev && have_remote_dev=1

DEV_BOOTSTRAP="create dev from main: git checkout -b dev && ALLOW_DIRECT_PUSH=1 git push -u origin dev"
if [ "$have_local_main" -eq 1 ]; then ok "local branch main exists"; else fail "local branch main is missing"; fi
if [ "$have_remote_main" -eq 1 ]; then ok "origin/main exists"; else fail "origin/main is missing"; fi
if [ "$have_local_dev" -eq 1 ]; then ok "local branch dev exists"; else fail "local branch dev is missing — $DEV_BOOTSTRAP"; fi
if [ "$have_remote_dev" -eq 1 ]; then ok "origin/dev exists"; else fail "origin/dev is missing — $DEV_BOOTSTRAP"; fi

# --- 5. local == remote for main/dev ------------------------------------------------------
check_sync() {
  local b="$1" counts ahead behind
  if ! ref_exists "refs/heads/$b" || ! ref_exists "refs/remotes/origin/$b"; then
    skip "$b sync check (branch missing locally or on origin)"
    return
  fi
  counts="$(git rev-list --left-right --count "$b...origin/$b" 2>/dev/null || echo "? ?")"
  ahead="${counts%%[[:space:]]*}"
  behind="${counts##*[[:space:]]}"
  if [ "$ahead" = "0" ] && [ "$behind" = "0" ]; then
    ok "local $b == origin/$b"
  else
    warn "local $b differs from origin/$b (ahead $ahead, behind $behind) — git checkout $b && git pull --ff-only"
  fi
}
check_sync main
check_sync dev

# --- 6. merge-back pending ------------------------------------------------------------------
main_ok=0; dev_ok=0
if [ "$QUICK" -eq 1 ]; then
  [ "$have_local_main" -eq 1 ] && main_ok=1
  [ "$have_local_dev" -eq 1 ] && dev_ok=1
else
  [ "$have_remote_main" -eq 1 ] && main_ok=1
  [ "$have_remote_dev" -eq 1 ] && dev_ok=1
fi
if [ "$main_ok" -eq 1 ] && [ "$dev_ok" -eq 1 ]; then
  pending="$(git rev-list --count "$DEV_REF..$MAIN_REF" 2>/dev/null || echo "?")"
  if [ "$pending" = "0" ]; then
    ok "merge-back: $MAIN_REF is fully contained in $DEV_REF"
  else
    fail "main has $pending commits not in dev — merge main -> dev before branching (merge commit, human-only)"
  fi
else
  skip "merge-back check ($MAIN_REF or $DEV_REF missing)"
fi

# --- 7. current branch name -------------------------------------------------------------------
current="$(git symbolic-ref --short -q HEAD 2>/dev/null || true)"
if [ -z "$current" ]; then
  warn "detached HEAD — check out a branch"
elif [[ "$current" =~ $TASK_RE ]] || [[ "$current" =~ $RELEASE_RE ]]; then
  ok "current branch '$current' matches the naming rule"
elif [ "$current" = "main" ] || [ "$current" = "dev" ]; then
  warn "on '$current' — expected only during bootstrap; branch off before writing code (CLAUDE.md §34)"
else
  fail "current branch '$current' violates the naming rule: (feature|fix|refactor|chore|hotfix)/<name>_<YYYYMMDD_HHMM> (name: [a-z0-9_]{1,30}) or release/N.M.P[-rc.N]"
fi

# --- 8./9. local task branches vs PR state ------------------------------------------------------
local_branches="$(git for-each-ref --format='%(refname:short)' refs/heads/ 2>/dev/null)"
if [ "$QUICK" -eq 1 ]; then
  skip "merged-PR / open-PR branch checks (--quick)"
elif [ "$GH_AUTH" -eq 0 ]; then
  skip "merged-PR / open-PR branch checks (gh not authenticated)"
else
  merged_list=""
  no_pr_list=""
  for b in $local_branches; do
    if [[ "$b" =~ $TASK_RE ]] || [[ "$b" =~ $RELEASE_RE ]]; then
      merged_n="$(gh pr list --head "$b" --state merged --json number --jq length 2>/dev/null || echo 0)"
      if [ "${merged_n:-0}" != "0" ]; then
        merged_list="$merged_list $b"
        continue
      fi
      open_n="$(gh pr list --head "$b" --state open --json number --jq length 2>/dev/null || echo 0)"
      if [ "${open_n:-0}" = "0" ]; then
        no_pr_list="$no_pr_list $b"
      fi
    fi
  done
  if [ -n "$merged_list" ]; then
    for b in $merged_list; do
      warn "branch '$b' has a merged PR — delete it: git branch -D $b"
    done
  else
    ok "no local branches with an already-merged PR"
  fi
  for b in $no_pr_list; do
    info "branch '$b' has no open PR"
  done
fi

# --- 10. version chain -----------------------------------------------------------------------------
version_file=""
if [ -f VERSION ]; then
  version_file="$(tr -d '[:space:]' < VERSION)"
  info "VERSION file: $version_file"
else
  fail "VERSION file is missing at the repo root (CLAUDE.md §41.2)"
fi

pkg_version=""
if [ -f backend/core/__init__.py ]; then
  if [ -x .venv/bin/python ]; then py=".venv/bin/python"; else py="python3"; fi
  pkg_version="$("$py" -c "import sys; sys.path.insert(0,'backend'); import core; print(core.__version__)" 2>/dev/null || true)"
  if [ -z "$pkg_version" ]; then
    skip "core.__version__ (import failed with $py)"
  elif [ -n "$version_file" ]; then
    if [ "$pkg_version" = "$version_file" ]; then
      ok "core.__version__ ($pkg_version) == VERSION"
    else
      fail "core.__version__ ($pkg_version) != VERSION ($version_file)"
    fi
  fi
fi

changelog_version=""
if [ -f CHANGELOG.md ]; then
  changelog_version="$(grep -m1 -E '^## \[[0-9]+\.[0-9]+\.[0-9]+[^]]*\]' CHANGELOG.md 2>/dev/null \
    | sed -E 's/^## \[([^]]+)\].*/\1/' || true)"
  if [ -z "$changelog_version" ]; then
    warn "CHANGELOG.md has no released '## [x.y.z] - date' heading yet"
  elif [ -n "$version_file" ]; then
    if [ "$changelog_version" = "$version_file" ]; then
      ok "CHANGELOG.md latest release heading ($changelog_version) == VERSION"
    else
      fail "CHANGELOG.md latest release heading ($changelog_version) != VERSION ($version_file)"
    fi
  fi
else
  skip "CHANGELOG.md check (file missing)"
fi

tag_count="$(git tag -l | wc -l | tr -d '[:space:]')"
latest_tag=""
if [ "$main_ok" -eq 1 ]; then
  latest_tag="$(git describe --tags --abbrev=0 "$MAIN_REF" 2>/dev/null || true)"
fi
if [ "$tag_count" = "0" ]; then
  warn "no tags yet (pre-first-release)"
else
  if [ -n "$latest_tag" ]; then
    info "latest tag reachable from $MAIN_REF: $latest_tag"
    tag_type="$(git cat-file -t "refs/tags/$latest_tag" 2>/dev/null || echo "?")"
    if [ "$tag_type" = "tag" ]; then
      ok "tag $latest_tag is annotated"
    else
      fail "tag $latest_tag is lightweight (type '$tag_type') — annotated tags only (CLAUDE.md §41.4)"
    fi
    if [ -n "$version_file" ] && [ "v$version_file" != "$latest_tag" ]; then
      info "VERSION ($version_file) differs from the latest tag on $MAIN_REF ($latest_tag) — unreleased work"
    fi
  else
    warn "no tag reachable from $MAIN_REF"
  fi
  if [ -n "$changelog_version" ]; then
    if git rev-parse -q --verify "refs/tags/v$changelog_version" >/dev/null 2>&1; then
      ok "CHANGELOG.md release $changelog_version has tag v$changelog_version"
    else
      fail "CHANGELOG has a release heading with no tag (v$changelog_version)"
    fi
  fi
fi

# --- 11. branch protection ---------------------------------------------------------------------------
if [ "$QUICK" -eq 1 ]; then
  skip "branch protection checks (--quick)"
elif [ "$GH_AUTH" -eq 0 ] || [ -z "$OWNER_REPO" ]; then
  skip "branch protection checks (gh not authenticated or repo unknown)"
else
  for b in main dev; do
    expected_file=".github/branch-protection/$b.json"
    apply_hint="gh api -X PUT repos/$OWNER_REPO/branches/$b/protection --input $expected_file"
    prot_lines="$(gh api "repos/$OWNER_REPO/branches/$b/protection" \
      --jq '[((.required_status_checks.contexts // []) | sort | join(",")), (.allow_force_pushes.enabled | tostring), (.allow_deletions.enabled | tostring)] | join("\n")' 2>/dev/null)" || prot_lines=""
    if [ -z "$prot_lines" ]; then
      fail "branch protection on '$b' is absent — apply: $apply_hint"
      continue
    fi
    remote_contexts="$(printf '%s\n' "$prot_lines" | sed -n '1p')"
    force_pushes="$(printf '%s\n' "$prot_lines" | sed -n '2p')"
    deletions="$(printf '%s\n' "$prot_lines" | sed -n '3p')"
    if [ ! -f "$expected_file" ]; then
      fail "$expected_file is missing — cannot compare required status checks for '$b'"
    elif [ -z "$JSON_TOOL" ]; then
      skip "required status checks comparison for '$b' (neither jq nor python3 available)"
    else
      expected_contexts="$(json_contexts "$expected_file" || true)"
      if [ "$remote_contexts" = "$expected_contexts" ]; then
        ok "'$b' required status checks: $remote_contexts"
      else
        fail "'$b' required status checks are '$remote_contexts', expected '$expected_contexts' — apply: $apply_hint"
      fi
    fi
    if [ "$force_pushes" = "false" ]; then ok "'$b' force pushes disabled"; else fail "'$b' allows force pushes — apply: $apply_hint"; fi
    if [ "$deletions" = "false" ]; then ok "'$b' deletions disabled"; else fail "'$b' allows deletion — apply: $apply_hint"; fi
  done
fi

# --- 12. repository merge settings ---------------------------------------------------------------------
if [ "$QUICK" -eq 1 ]; then
  skip "repository settings checks (--quick)"
elif [ "$GH_AUTH" -eq 0 ] || [ -z "$OWNER_REPO" ]; then
  skip "repository settings checks (gh not authenticated or repo unknown)"
elif [ ! -f .github/repo-settings.json ]; then
  fail ".github/repo-settings.json is missing — cannot compare repository settings"
elif [ -z "$JSON_TOOL" ]; then
  skip "repository settings checks (neither jq nor python3 available)"
else
  settings_fix="gh api -X PATCH repos/$OWNER_REPO --input .github/repo-settings.json"
  settings_keys="allow_squash_merge allow_merge_commit allow_rebase_merge delete_branch_on_merge squash_merge_commit_title squash_merge_commit_message"
  settings_json="$(gh api "repos/$OWNER_REPO" 2>/dev/null || true)"
  if [ -z "$settings_json" ]; then
    fail "could not read repository settings for $OWNER_REPO — fix: $settings_fix"
  else
    for key in $settings_keys; do
      expected="$(json_field .github/repo-settings.json "$key" || true)"
      actual="$(printf '%s' "$settings_json" | json_stdin_field "$key" || echo '<unreadable>')"
      if [ "$expected" = "$actual" ]; then
        ok "repo setting $key == $actual"
      else
        fail "repo setting $key is $actual, expected $expected — fix: $settings_fix"
      fi
    done
  fi
fi

# --- 13. legacy maintenance branches ---------------------------------------------------------------------
legacy_found=0
for ref in $(git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/origin/ 2>/dev/null); do
  short="${ref#origin/}"
  if [[ "$short" =~ $LEGACY_RE ]]; then
    legacy_found=1
    warn "'$ref' is a legacy maintenance branch; retire per §41.6 (release branches are now temporary release/N.M.P)"
  fi
done
[ "$legacy_found" -eq 0 ] && ok "no legacy release/N.M.x maintenance branches"

# --- summary --------------------------------------------------------------------------------------------------
echo "git_audit: $N_FAIL FAIL, $N_WARN WARN"
if [ "$N_FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
