# Phase 3: Worktree

구현 전에 isolated working context를 만들거나 확인합니다.

## 절차

1. workflow가 branch 또는 PR을 요구하면 `tool:create_worktree`를 사용합니다.
   이때 worktree path는 반드시 `<대상 프로젝트의 분리된 worktree 경로>`입니다.
2. 이후 모든 command에 사용할 absolute worktree path를 보존합니다.
3. Runtime identity가 시작한 exact session에 required `workflow_id`가 active인지 phase runner
   `current`로 확인합니다. 경로나 issue 번호로 다른 workflow를 찾지 않습니다.
4. 새 worktree를 command cwd로 사용해 shared resource를 claim합니다.

   ```bash
   python3 -m scripts.agent_harness.state_cli worktree claim
   ```

   `WorktreeRegistry`가 Git common directory와 top-level에서 `worktree_id`를 계산하고 current
   `(session_id, actor_id)`를 owner로 기록합니다. 동일 owner retry는 idempotent하며 다른
   owner의 claim은 기존 값을 덮어쓰지 않고 거부합니다.
5. session actor가 worktree를 claim한 뒤에는 sibling worktree, repository root,
   repository 밖 temporary path를 편집하지 않습니다.
   `.agents/skills/process-ticket/scripts/assert_worktree_isolation.sh`로 exact root/worktree
   경계를 read-back합니다.
6. 현재 local-only task에 worktree가 필요 없으면 이유를 기록합니다.

## State

Canonical process state는 runtime-owned session aggregate입니다. Phase state와 operational
skill state는 exact `workflow_id` 아래 분리되고, worktree claim은 repository-wide resource
registry에 분리됩니다. Agent는 persistence 파일을 만들거나 수정하지 않습니다.

- Phase transition: `scripts.skill_harness.phase_runner --workflow-id ...`
- Operational evidence: `process_state_evidence.py --workflow-id ...`
- Worktree ownership: `state_cli worktree claim|release`
- Delegation, incident, monitor: 각 identity-keyed typed application

Workflow-local mutation은 original revision을 compare key로 사용하는 optimistic CAS입니다.
Conflict가 발생하면 latest state를 다시 읽어 pure transform을 재계산하며 stale replacement를
그대로 반복하지 않습니다. Worktree release와 handoff는 current lease epoch와 fencing token이
일치해야 합니다.

## Evidence

- `worktree_decision`
- `workflow_state_initialized`
- `worktree_absolute_path`
- `session_workflow_ownership`
- `root_worktree_isolation_check`
