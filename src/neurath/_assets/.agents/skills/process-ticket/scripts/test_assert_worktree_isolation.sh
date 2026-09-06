#!/usr/bin/env bash
# Static smoke test for the canonical resource-registry worktree guard.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
guard="$script_dir/assert_worktree_isolation.sh"

bash -n "$guard"
grep -Fq 'scripts.agent_harness.state_cli worktree claim' "$guard"
! grep -Fq '.process-state.json' "$guard"
! grep -Fq 'stamp_agent_session.py' "$guard"
! grep -Eq -- '--state([ =]|$)' "$guard"
printf 'worktree-isolation-guard-ok\n'
