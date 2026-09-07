#!/usr/bin/env bash
# Validates ticket topology, then delegates ownership to the canonical registry.
set -euo pipefail

usage() {
  printf 'usage: %s [--init] <issue-number>\n' "$0" >&2
}

fail() {
  printf 'isolation-failed: %s\n' "$*" >&2
  exit 2
}

mode="check"
if [ "${1:-}" = "--init" ]; then
  mode="init"
  shift
fi
issue="${1:-}"
case "$issue" in
  \#*) issue="${issue#\#}" ;;
esac
[[ "$issue" =~ ^[1-9][0-9]*$ ]] || { usage; exit 2; }
[ "$#" -eq 1 ] || { usage; exit 2; }

worktree="$(git rev-parse --show-toplevel)"
common_dir="$(git -C "$worktree" rev-parse --path-format=absolute --git-common-dir)"
repo_root="$(dirname "$common_dir")"
[ "$worktree" != "$repo_root" ] || fail "cwd-is-root worktree=$worktree"
branch="$(git -C "$worktree" branch --show-current)"
[ -n "$branch" ] || fail "detached-worktree"
root_inside="$(git -C "$repo_root" rev-parse --is-inside-work-tree 2>/dev/null || true)"
root_bare="$(git --git-dir="$common_dir" config --bool --get core.bare 2>/dev/null || true)"
[ "$root_inside" = "true" ] && [ "$root_bare" != "true" ] \
  || fail "root-worktree-invalid root=$repo_root"
root_branch="$(git -C "$repo_root" branch --show-current)"
[ -n "$root_branch" ] && [ "$root_branch" != "$branch" ] \
  || fail "root-and-task-branches-must-be-distinct"

root_status="$(git -C "$repo_root" status --porcelain=v1 --untracked-files=all)"
[ -z "$root_status" ] \
  || fail "root-dirty mode=$mode status=$(printf '%s' "$root_status" | tr '\n' ';')"

cd "$worktree"
# Keep the target's scripts package behind the bundled engine on PYTHONPATH.
claim="$("${PYTHON_BIN:-python3}" -P -m scripts.agent_harness.state_cli worktree claim)" \
  || fail "canonical-worktree-claim-rejected"
printf 'isolation-ok: mode=%s issue=%s claim=%s\n' "$mode" "$issue" "$claim"
