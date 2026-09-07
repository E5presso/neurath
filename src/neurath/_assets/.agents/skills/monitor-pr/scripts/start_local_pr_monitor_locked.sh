#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"

: "${REPO:?REPO env required}"
: "${PR_NUMBER:?PR_NUMBER env required}"
: "${WORKFLOW_ID:?WORKFLOW_ID env required}"

if [ -n "${CODEX_THREAD_ID:-}" ] && [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  printf 'multiple runtime-owned session identities are present\n' >&2
  exit 2
fi
if [ -n "${CODEX_THREAD_ID:-}" ]; then
  runtime_environment=("CODEX_THREAD_ID=$CODEX_THREAD_ID")
elif [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  runtime_environment=("CLAUDE_CODE_SESSION_ID=$CLAUDE_CODE_SESSION_ID")
else
  printf 'runtime-owned session identity is unavailable\n' >&2
  exit 2
fi

neurath_overlay_count=0
for overlay_key in NEURATH_AGENT_SESSION_ID NEURATH_AGENT_ACTOR_ID NEURATH_AGENT_RUNTIME; do
  if [ -n "${!overlay_key:-}" ]; then
    neurath_overlay_count=$((neurath_overlay_count + 1))
  fi
done
if [ "$neurath_overlay_count" -ne 0 ] && [ "$neurath_overlay_count" -ne 3 ]; then
  printf 'Neurath runtime identity overlay must be all-or-none\n' >&2
  exit 2
fi
if [ "$neurath_overlay_count" -eq 3 ]; then
  runtime_environment+=(
    "NEURATH_AGENT_SESSION_ID=$NEURATH_AGENT_SESSION_ID"
    "NEURATH_AGENT_ACTOR_ID=$NEURATH_AGENT_ACTOR_ID"
    "NEURATH_AGENT_RUNTIME=$NEURATH_AGENT_RUNTIME"
  )
fi

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
worktree="$(git rev-parse --show-toplevel)"
state_dir="$worktree/.monitor-pr"
poll_interval="${MONITOR_POLL_INTERVAL_SECONDS:-30}"
turn_completion_wait="${MONITOR_TURN_COMPLETION_WAIT_SECONDS:-5}"
startup_readback_attempts="${MONITOR_STARTUP_READBACK_ATTEMPTS:-300}"
process_manager_readiness_attempts="${MONITOR_PROCESS_MANAGER_READINESS_ATTEMPTS:-50}"
log_path="$state_dir/monitor.log"
launch_label="com.neurath.pr${PR_NUMBER}.local-monitor"

mkdir -p "$state_dir"

python_bin="${PYTHON_BIN:-}"
if [ ! -x "$python_bin" ]; then
  python_bin="$(command -v python3)"
fi
if command -v realpath >/dev/null 2>&1; then
  python_bin="$(realpath "$python_bin")"
fi
# Inline Python must ignore target modules; file-based helpers retain sibling imports.
if ! "$python_bin" -P -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' >/dev/null 2>&1; then
  printf 'monitor requires the Neurath tool Python 3.14+; rerun Neurath setup for %s. refusing to launch with %s\n' \
    "$worktree" "$python_bin" >&2
  exit 1
fi

runtime_id="$("$python_bin" -P -c 'import uuid; print(uuid.uuid4().hex)')"
handoff_receipt="$("$python_bin" "$skill_dir/scripts/monitor_runtime_handoff.py" \
  --workflow-id "$WORKFLOW_ID" \
  --expected-label "$launch_label" \
  --user-id "$(id -u)")"
printf '%s\n' "$handoff_receipt" >>"$log_path"

command=(
  "$python_bin" "$skill_dir/scripts/local_pr_monitor.py"
  --repo "$REPO"
  --pr-number "$PR_NUMBER"
  --workflow-id "$WORKFLOW_ID"
  --runtime-id "$runtime_id"
  --poll-interval-seconds "$poll_interval"
)

resume_adapter_status="command"
if [ -n "${NEURATH_CODEX_RESUME_COMMAND:-}" ]; then
  command+=(--resume-command "$NEURATH_CODEX_RESUME_COMMAND")
else
  probe_output="$("$python_bin" "$skill_dir/scripts/app_server_resume.py" --probe || true)"
  if ! printf '%s' "$probe_output" | grep -Eq '"probe_status"[[:space:]]*:[[:space:]]*"available"'; then
    resume_adapter_status="unavailable"
    command+=(
      --resume-unavailable-reason "resume-capability-missing"
      --resume-probe-output "$probe_output"
    )
    printf 'resume adapter unavailable; starting collector-only monitor for PR #%s\n' \
      "$PR_NUMBER" >>"$log_path"
    printf '%s\n' "$probe_output" >>"$log_path"
  else
    printf -v resume_command '%q %q --turn-timeout-seconds %q' \
      "$python_bin" "$skill_dir/scripts/app_server_resume.py" "$turn_completion_wait"
    command+=(--resume-command "$resume_command")
  fi
fi

if command -v launchctl >/dev/null 2>&1; then
  launcher="launchctl"
else
  launcher="nohup"
fi
command+=(--launcher "$launcher")

launcher_command=(/usr/bin/env "PATH=$PATH" "HOME=$HOME" "${runtime_environment[@]}")
if [ -n "${CODEX_HOME:-}" ]; then
  launcher_command+=("CODEX_HOME=$CODEX_HOME")
fi
if [ -n "${CODEX_APP_SERVER_BIN:-}" ]; then
  launcher_command+=("CODEX_APP_SERVER_BIN=$CODEX_APP_SERVER_BIN")
fi
if [ -n "${SSH_AUTH_SOCK:-}" ]; then
  launcher_command+=("SSH_AUTH_SOCK=$SSH_AUTH_SOCK")
fi
launcher_command+=("${command[@]}")
launch_started_at_epoch="$("$python_bin" -P -c 'import time; print(time.time())')"

if [ "$launcher" = "launchctl" ]; then
  "$python_bin" "$skill_dir/scripts/launch_agent_plist.py" \
    --label "$launch_label" \
    -- "${launcher_command[@]}"
fi

manager_receipt="$("$python_bin" "$skill_dir/scripts/monitor_process_manager.py" \
  --launcher "$launcher" \
  --label "$launch_label" \
  --poll-interval-seconds "$poll_interval" \
  --user-id "$(id -u)" \
  --readiness-attempts "$process_manager_readiness_attempts" \
  -- "${launcher_command[@]}")"
launcher="$("$python_bin" -P -c 'import json,sys; print(json.loads(sys.argv[1])["launcher"])' "$manager_receipt")"
manager_pid="$("$python_bin" -P -c 'import json,sys; print(json.loads(sys.argv[1]).get("manager_pid", ""))' "$manager_receipt")"

evidence_helper="$skill_dir/../process-ticket/scripts/process_state_evidence.py"
runtime_assets=""
evidence_receipt=""
attempt=0
while [ "$attempt" -lt "$startup_readback_attempts" ]; do
  attempt=$((attempt + 1))
  runtime_assets="$("$python_bin" "$skill_dir/scripts/monitor_runtime_readback.py" \
    --repo "$REPO" \
    --pr-number "$PR_NUMBER" \
    --workflow-id "$WORKFLOW_ID" \
    --runtime-id "$runtime_id" \
    --resume-adapter "$resume_adapter_status" \
    --poll-interval-seconds "$poll_interval" \
    --minimum-heartbeat-at-epoch "$launch_started_at_epoch" \
    --manager-json "$manager_receipt" || true)"
  if [ -n "$runtime_assets" ]; then
    subscription_json="$("$python_bin" -P -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])["subscription"], ensure_ascii=False, separators=(",", ":")))' "$runtime_assets")"
    if evidence_receipt="$("$python_bin" "$evidence_helper" \
      --workflow-id "$WORKFLOW_ID" \
      --field monitor_event_subscription \
      --value-json "$subscription_json" 2>/dev/null)"; then
      break
    fi
  fi
  runtime_assets=""
  evidence_receipt=""
  sleep 0.1
done

if [ -z "$runtime_assets" ] || [ -z "$evidence_receipt" ]; then
  if [ "$launcher" = "launchctl" ]; then
    launch_domain="gui/$(id -u)"
    launchctl print "$launch_domain/$launch_label" >&2 || true
    launchctl bootout "$launch_domain/$launch_label" >/dev/null 2>&1 || true
  elif [ -n "${manager_pid:-}" ]; then
    kill "$manager_pid" >/dev/null 2>&1 || true
  fi
  printf 'monitor runtime failed to start for PR #%s\n' "$PR_NUMBER" >&2
  exit 1
fi

receipt="$("$python_bin" -P -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])["receipt"], ensure_ascii=False, separators=(",", ":")))' "$runtime_assets")"
printf '%s\n' "$receipt"
