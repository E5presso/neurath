#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"

: "${REPO:?REPO env required}"
: "${PR_NUMBER:?PR_NUMBER env required}"
: "${WORKFLOW_ID:?WORKFLOW_ID env required}"

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
worktree="$(git rev-parse --show-toplevel)"
state_dir="$worktree/.monitor-pr"
launch_lock_path="$worktree/.monitor-pr/monitor-launch.lock"

mkdir -p "$state_dir"

python_bin="${PYTHON_BIN:-$worktree/.venv/bin/python3}"
if [ ! -x "$python_bin" ]; then
  python_bin="$(command -v python3)"
fi
if command -v realpath >/dev/null 2>&1; then
  python_bin="$(realpath "$python_bin")"
fi

exec "$python_bin" "$skill_dir/scripts/monitor_launch_lock.py" \
  --lock-path "$launch_lock_path" \
  -- "$skill_dir/scripts/start_local_pr_monitor_locked.sh" "$@"
