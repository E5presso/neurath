# Phase 3: Wave Loop

각 dependency wave를 `/process-ticket --auto-merge`로 실행합니다.

## 절차

각 leaf 구현·조사·검토는 네이티브 직접 자식을 기본으로 배정합니다. 별도 세션 수명,
다른 provider 또는 네이티브 도구가 제공하지 못하는 필수 격리가 필요할 때만 provider_run을
사용합니다. 역할·난이도·제약에 맞는 최소 충분 모델을 선택하며 최상위 모델을 일괄 배정하지
않습니다. 세션에서 관측한 모델 목록은 재사용하고 새로운 조건에 필요한 계획만 만듭니다.

1. runtime이 worker를 지원하면 `tool:team_create` 또는 `tool:spawn_agent`로
   current wave의 모든 issue를 spawn합니다. 지원하지 않으면 같은 worker evidence를
   보존하며 serial로 실행합니다.

   - Worker prompt 또는 session bootstrap은 runtime이 발급한 immutable worker actor
     identity와 required process-ticket `workflow_id`를 제공합니다. Worker는 exact feature
     worktree에서 shared resource claim을 얻기 전까지 file mutation을 수행할 수 없습니다.
   - 각 worker는 `/process-ticket` phase 3에서 feature worktree를 CWD로 다음 command를
     실행한 뒤 file mutation을 시작합니다.

     ```bash
     python3 -m scripts.agent_harness.state_cli worktree claim
     ```

     `StateHandle.attach`가 exact session/actor를 선택하고 `WorktreeRegistry`가 CWD의
     canonical `worktree_id`를 claim합니다. Session path나 owner candidate를 탐색하지
     않습니다.
   - Spawn prompt는 monitor route owner가 main autopilot session이고 terminal
     sink도 main autopilot session임을 포함합니다. 이 route metadata는 durable
     route table과 worker workflow의 Phase 6 evidence에 남깁니다.
   - session이 owned worktree를 가진 뒤에는 root checkout, sibling worktree,
     repository 밖 temporary path를 mutation target으로 삼지 않습니다.
2. terminal state vocabulary를 정확히 보존합니다.
   - `merged`
   - `mergeable-clean`
   - `failed`
   - `skipped`
   - `blocked`
3. `mergeable-clean`은 아직 merged가 아닌 상태로 취급합니다.
4. spawned follow-up issue는 metadata 검증 후에만 수집합니다.
5. wave의 모든 blocker가 terminal 상태가 된 뒤에만 다음 wave로 이동합니다.

## Monitor event routing

같은 세션 안의 독립된 구현·검토 단위는 native subagent에 맡깁니다. 새 MCP 목록이나
설치된 런타임을 시작부터 읽어야 하는 검증은 별도 세션이므로 provider_run을 사용합니다.
앱의 create_thread는 실행 권한 승계를 보장하지 않으며 이 위임을 대신할 수 없습니다.
provider_run의 실제 권한·활성화·소유권 확인 후 작업을 전달하고 생성자가 결과를 회수합니다.

진행 중 새 작업은 기존 태스크를 지우지 않고 task_define으로 추가합니다. task_start와
task_resolve는 실제 상태와 근거에 맞춰 사용하고, task_list의 현재 목록을 호스트 TODO에
반영합니다. 도구 부재를 표시 성공으로 주장하지 않습니다. 중간 질문에 답해도 원래 작업을
계속하며 미완료 태스크를 남긴 정상 Stop은 허용하지 않습니다. 사용자 명시적 중단은 보존합니다.

`route_owner=autopilot`인 PR monitoring route table은 main autopilot session이
소유한 exact autopilot workflow의 `SkillStateStore`에 있습니다. Route entry는 issue/PR
number, immutable worker actor, worker `session_id + workflow_id`, registry `worktree_id`, head
SHA, event source ID, 마지막 처리 delivery ID를 연결합니다. Filesystem path는 route identity나
authority source가 아닙니다.

Event delivery가 도착했을 때 worker가 살아 있으면 `tool:send_message`로 깨웁니다.
Worker가 idle이면 route에 기록된 exact runtime continuation으로 같은 session/workflow를
resume합니다. Worker가 terminal이거나 exact runtime을 재개할 수 없으면 다른 session을
선택하지 않고 typed route failure로 남깁니다. Main session은 worker persistence를 직접
읽거나 PR 상태 반복 조회를 대신 수행하지 않고, event delivery가 typed workflow transition
또는 terminal report로 흡수됐는지만 검증합니다.

## Stuck recovery

worker가 monitoring 전에 idle이 되면 route의 exact runtime identity로 continuation을
요청하고, worker가 `StateHandle`로 읽은 required workflow projection과 current phase를
구조화된 실행 결과로 반환하게 합니다. Main session은 다른 session, 최근 수정 workflow,
worktree directory를 fallback으로 선택하지 않습니다.

### 모순 C (auto-merge clean terminal 미흡수)

Worker의 exact workflow skill state에 `monitor_started`가 있고,
PR read-back 결과가 `mergeStateStatus in {"CLEAN","UNSTABLE"}`, `pendingChecks == 0`,
`failedChecks == 0`, review approval 충족 상태인데 worker terminal report가 없으면
clean terminal이 흡수되지 않은 stuck 상태로 봅니다.

Invariant: `clean terminal stuck detection must start from monitor_started state` in the exact
worker workflow skill state.

이 경우 resume prompt에는 `phase7_ready={phase7_ready|null}`를 포함합니다.
`phase7_ready`가 true이고 original invocation이 `--auto-merge`라면 worker는
반환하지 말고 같은 turn에서 `gh pr merge --squash --delete-branch`와 cleanup까지
완료하라. `mergeable-clean`만 반환하고 멈추면 auto-merge continuation 위반입니다.

runtime이 worker-to-orchestrator message를 지원하면 worker는 phase ping과 terminal
summary에 `tool:send_message`를 사용해야 합니다.

## 조건부 reference

- spawned issue가 보고되면 `new-ticket-intake.md`를 읽습니다.
- bot review behavior가 merge state에 영향을 주면 `ledger-bot-violations.md`를
  읽습니다.
