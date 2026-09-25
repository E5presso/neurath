# Phase 3: Wave Loop

각 dependency wave를 `/process-ticket --auto-merge`로 실행합니다.

## 절차

Root orchestrator가 모든 티켓의 task/workflow, 통합, 검토와 monitor 결과 수락을 소유합니다.
구현 자식은 병렬로 bounded 분석·구현안·patch artifact·허용된 검증을 수행하고 root에 보고합니다.
자식에게 `/process-ticket` 전체 owner 역할이나 중첩 리뷰 호출을 넘기지 않습니다.
직접 쓰기는 실제 child policy와 해당 worktree claim이 확인될 때만 가능하며 이를 추정하지 않습니다.
권한이 없는 자식은 patch artifact를 반환하고 root가 자신의 claim 아래 통합합니다.
Root는 구현 자식과 별도의 `role=review` 직접 자식을 새 컨텍스트로 배정합니다.

1. `delegation_wave_prepare`에 현재 in-progress task ID/revision, 고유 wave ID,
   entries(delegation_id, depends_on), max_parallel, capacity_basis를 기록합니다.
   기존 phase workflow에서는 workflow_id도 결속하고 완료 시 native_wave_receipt의 wave_id를
   제출합니다. phase gate가 같은 workflow의 실제 consumed 성공 결과를 다시 읽습니다.
   Cycle·누락 dependency는 실행 전에 거부합니다. capacity는 실제 도구 inventory에서 관측한
   한도와 현재 사용량을 근거로 선택하며, 병렬 가능한 work를 1개로 제한하면
   serialization_reason을 남깁니다. 선언된 숫자를 호스트 확인으로 표현하지 않습니다.
   각 ready entry에 `delegation_prepare → tool:spawn_agent`를 실행합니다.
   현재 wave의 가용 slot을 모두 채운 뒤 기다립니다. Claude의 병렬 Agent는
   run_in_background=true를 사용합니다. spawn hook이 실제 접수와 자식을 결속하며,
   준비된 항목과 빈 slot이 남았으면 wait hook이 대기를 거부합니다.
   결과를 읽고 실제 owner가 consume한 성공만 후속 dependency를 해제합니다.
   새 이벤트 후 `delegation_wave_read`로 상태를 확인하며 주기적으로 조회하지 않습니다.
   실제 실패한 attempt는 `delegation_wave_retry`로 새 delegation ID에 연결하고 실패 이력은
   보존합니다. 불확실한 실행을 중복 dispatch하지 않습니다. 미완료 wave를 남긴 task 성공은 거부합니다.

   - 동일 세션 위임은 native subagent가 기본입니다. 별도 worktree나 장시간 실행은
     사용자용 독립 세션을 만드는 사유가 아닙니다.
   - 사용자가 해당 대화를 직접 방문하여 이어갈 가능성이 있으면 user-session을 선택합니다.
   - 새로운 시각·대안·반증이 필요하면 perspective 사유로 다른 provider를 자율 선택할 수
     있습니다. 이 기술적 worker의 결과는 현재 orchestrator가 회수합니다.
   - Native child가 없거나 권한이 없으면 실제 capability gap을 보고합니다. serial fallback은
     capacity_basis와 serialization_reason을 기록하고 root가 실행 가능한 작업에만 적용합니다.
     독립 review에는 serial fallback이 없습니다.

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

같은 세션 안의 구현·검토 단위는 native subagent에 맡깁니다. Provider 선택은 공통 정책의
purpose와 reason을 따릅니다. 앱 create_thread는 사용자가 방문할 독립 작업을 위한 도구이며
내부 티켓 위임을 대신하지 않습니다. Root가 각 티켓의 monitor route와 terminal sink를 소유합니다.

진행 중 새 작업은 기존 태스크를 지우지 않고 task_define으로 추가합니다. task_start와
task_resolve는 실제 상태와 근거에 맞춰 사용하고, task_list의 현재 목록을 호스트 TODO에
반영합니다. 도구 부재를 표시 성공으로 주장하지 않습니다. 중간 질문에 답해도 원래 작업을
계속하며 미완료 태스크를 남긴 정상 Stop은 허용하지 않습니다. 사용자 명시적 중단은 보존합니다.

`route_owner=autopilot`인 PR monitoring route table은 main autopilot session이
소유한 exact autopilot workflow의 `SkillStateStore`에 있습니다. Route entry는 issue/PR
number, immutable worker actor, root-owned ticket `session_id + workflow_id`, registry `worktree_id`, head
SHA, event source ID, 마지막 처리 delivery ID를 연결합니다. Filesystem path는 route identity나
authority source가 아닙니다.

Event delivery가 도착하면 root가 자신이 소유한 ticket workflow에 반영합니다.
추가 구현이 필요하고 해당 worker가 이어서 작업할 수 있으면 `tool:send_message`로
정확한 남은 범위를 전달합니다. 이미 끝난 worker의 역할을 다른 사용자 세션에 넘기지
않으며, 필요하면 root가 새 native child를 명시적으로 준비합니다. PR 상태를 반복 조회하는
대신 실제 monitor event와 typed workflow transition, 결과 수락을 연결합니다.

## Stuck recovery

Root가 자신의 required workflow projection과 current phase, monitor route를 읽어
어느 실행 결과가 남았는지 확인합니다. Worker에게 root workflow의 소유권이나 merge를
맡기지 않습니다. Worker continuation은 exact runtime identity와 남은 assignment로만
요청하며 다른 session이나 최근 수정된 workflow를 fallback으로 선택하지 않습니다.

### 모순 C (auto-merge clean terminal 미흡수)

Root의 exact workflow skill state에 `monitor_started`가 있고,
PR read-back 결과가 `mergeStateStatus in {"CLEAN","UNSTABLE"}`, `pendingChecks == 0`,
`failedChecks == 0`, review approval 충족 상태인데 root의 merge 결과가 없으면
clean terminal이 흡수되지 않은 stuck 상태로 봅니다.

Invariant: `clean terminal stuck detection must start from monitor_started state` in the exact
root-owned workflow skill state.

이 경우 resume prompt에는 `phase7_ready={phase7_ready|null}`를 포함합니다.
`phase7_ready`가 true이고 original invocation이 `--auto-merge`라면 root는
반환하지 말고 같은 turn에서 `gh pr merge --squash --delete-branch`와 cleanup까지
완료하라. `mergeable-clean`만 반환하고 멈추면 auto-merge continuation 위반입니다.

runtime이 worker-to-orchestrator message를 지원하면 worker는 phase ping과 terminal
summary에 `tool:send_message`를 사용해야 합니다.

## 조건부 reference

- spawned issue가 보고되면 `new-ticket-intake.md`를 읽습니다.
- bot review behavior가 merge state에 영향을 주면 `ledger-bot-violations.md`를
  읽습니다.
