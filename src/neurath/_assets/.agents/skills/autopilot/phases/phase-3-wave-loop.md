# Phase 3: Wave Loop

각 dependency wave를 `/process-ticket --auto-merge`로 실행합니다.

## 절차

Root orchestrator가 모든 티켓의 task/workflow, 통합, 검토와 monitor 결과 수락을 소유합니다.
각 issue의 성격·난이도·능력과 수명에 따라 native subagent, 독립 세션, 교차 provider
위탁을 먼저 선택합니다. Native child가 기본입니다. 독립 실행이 필요한 issue만
격리된 worktree의 `provider_wave_run` 배치로 실행합니다. Stock Codex라는 이유나
root/worktree 위치만으로 provider 배치를 고르지 않습니다.
Runtime이 ready 항목 예약과 실행을 관리하며 에이전트의 wait hook에 의존하지 않습니다.
Worker는 자신의 native 준비 상태와 worktree claim을 확인한 뒤 bounded 구현을 수행합니다.
이 worker는 독립 provider peer root이며 발행자의 직접 자식이나 독립 검토자가 아닙니다.
발행자의 workflow·최종 수락 권한을 넘기지 않습니다. 쓰기 권한이 없으면 patch artifact를 반환합니다.
Root는 구현 worker와 별도의 `role=review` native 직접 자식을 새 컨텍스트로 배정합니다.
Codex 리뷰는 `fork_turns="none"`이며 실제 호스트의 계보·컨텍스트 증명을 확인합니다.

1. Phase 2의 구현 대상 이슈마다 `issue-<번호>`를 고유 entry ID로 사용합니다.
   실제 지원을 관측한 native child wave를 우선합니다. 아래 provider 배치는 각 항목에
   독립 실행 또는 교차 provider 필요를 확인한 뒤에만 사용합니다.

   - 각 항목에 distinct isolated worktree와 bounded assignment, `provider_plan`의
     정확한 ID/revision을 준비합니다. 대상은 설치되고 깨끗하며 claim되지 않은 issue
     worktree여야 합니다. 각 request에 선택한 `purpose`와 구체적인 `reason`을 넣습니다.
     같은 provider의 `worktree-worker`에는 `session_basis=independent-lifecycle` 또는
     `native-capability-gap`과 실제 수명·호스트 관측을 기록합니다. 다른 provider의
     `perspective`에는 필요한 능력·관점을 기록합니다. 배치는 이 선택이나 이유를 자동 생성하지 않습니다.
     네이티브 대안을 검토하고 기존 모델 계획과 실행 정책을 유지합니다.
     기본 `mode=inherit`를 실패한 권한 승계를 피하는 다른 모드로 바꾸지 않습니다.
   - `provider_wave_run`에 현재 in-progress task ID/revision, 고유 wave ID,
     entries(entry_id, depends_on, request), max_parallel, capacity_basis, 안정된 key를
     전달합니다. 기존 phase workflow의 workflow_id도 결속합니다. 모든 항목을 검증한 뒤
     runtime이 한 transaction에서 가용 슬롯의 ready set을 예약하고 실행할 항목을
     영속 저장합니다. Capacity는 실제 관측에 근거하며 선언값을 호스트 확인으로 표현하지 않습니다.
   - Worker 종료 이벤트가 슬롯을 비우면 runtime이 독립 ready 항목을 실행합니다.
     선행 worker의 종료만으로 의존 작업을 실행하지 않습니다. Root가 결과를 읽고
     `provider_wave_consume`에 정확한 entry_id, run_id, generation, result_digest,
     accepted/rejected 판정과 key를 전달합니다. 수락한 성공 결과만 dependency를 해제합니다.
   - 결과·복구 이벤트 뒤 `provider_wave_read`로 실제 상태와 미제출 실행의 조정을 확인합니다.
     주기적으로 조회하지 않으며 불확실한 실행을 중복 dispatch하지 않습니다.
     `provider_wave_cancel`은 새 예약을 막고 실제 run에 취소를 요청합니다.
     취소·실패 결과와 원래 미완료 사용자 요구를 보존합니다.

   - 재시도는 `provider_wave_retry(wave_id, entry_id, request, key)`로 명시합니다.
     원래 assignment·provider·worktree를 유지하고 모델 계획·상속 정책을 새로 검증합니다.
     정확한 이전 run의 failed/cancelled 결과, generation 1 종료와 worker OS lease 해제,
     생성된 native 세션의 일치하는 연결·프로세스 종료를 확인해야 합니다.
     수락한 작업·후속 작업이 있거나 wave가 취소됐으면 재시도하지 않습니다.
     이전 attempt의 요청·결과·지문·소비 기록을 변경 없이 보존합니다.
     모든 wave 연결 run과 이전 attempt에서 `provider_recover`를 사용하지 않습니다.
     Inbox 연결 복구로 구현 assignment가 완료됐다고 처리하지 않습니다.
   - 과거 native 연결 종료 근거가 없어 terminal failed/cancelled wave를 재시도할 수
     없으면 같은 task·workflow·entry DAG·provider·worktree의 별도 wave를 실행할 수
     있습니다. 대체 wave의 모든 항목을 root가 정확한 성공 결과로 수락한 뒤에만
     `provider_wave_supersede(old_wave_id, new_wave_id, key)`로 이전 wave를 task 완료
     계산에서 제외합니다. 이전 결과와 누락된 종료 근거는 그대로 보존하며, 이 도구를
     과거 run의 재시도나 성공 처리로 표현하지 않습니다. 실행되지 않은 후속 항목과
     이미 수락한 형제 결과를 각각 그대로 보존하고, 이전 wave의 새 예약·재시도를 막습니다.
   - Crash 조정은 인증된 owner의 read·동일 요청 replay·정확한 consume과 worker 종료
     callback에서 수행합니다. 영속 실행 신원과 lease로 중복 실행을 막습니다.
     Startup scanner나 주기적 polling은 없으며, 미제출 실행 replay와 새 구현 retry를 구분합니다.

   Native dispatch와 wait hook 지원이 검증된 호스트에서는 `delegation_wave_prepare`의
   native child wave를 사용할 수 있습니다. 현재 task revision에 entries(delegation_id,
   assignment, depends_on, role), capacity, workflow_id를 결속하고 반환된 정확한 준비
   코드/key로 각 ready 항목을 준비한 뒤 native spawn 도구를 호출합니다. Claude 병렬
   Agent는 run_in_background=true를 사용합니다. 가용 슬롯을 모두 채운 뒤 기다립니다.
   `delegation_wave_read`는 이벤트 뒤 읽으며 실제 실패한 attempt만
   `delegation_wave_retry`로 교체합니다. 원래 이력과 실제 자식 계보를 보존합니다.
   Wrapper 소스나 선언한 hook만으로 중첩 또는 바깥 PreToolUse 전달을 증명하지 않습니다.
   Stock Codex의 임의 대기 전부를 차단한다고 주장하거나 커스텀 Codex 빌드를 요구하지 않습니다.

   Phase 3 완료 근거 label은 호환성을 위해 `native_wave_receipt`를 유지합니다.
   Provider 배치는 `native_wave_receipt: provider_wave_id=<id>`,
   native 자식 wave는 `native_wave_receipt: wave_id=<id>`로 backend를 구분합니다.
   Gate는 같은 root/workflow의 실제 wave에서 Phase 2의 모든 구현 대상 ID,
   dependency edge와 root가 수락한 성공을 확인합니다. Provider 결과를 native 자식
   계보로 변환하지 않습니다. Native retry의 교체 ID는 원래 issue ID에 연결합니다.
   구현 대상이 없으면 수집 근거에 결속된
   `native_wave_receipt: no_op=all_satisfied`를 사용합니다.
   미완료·실패 wave를 성공으로 기록하지 않습니다.

   - 같은 대화의 bounded 작업은 native subagent가 기본입니다. 필요한 독립 실행만
     위 provider 배치를 사용합니다. 별도 worktree나 실행 시간만으로 세션을 만들지 않습니다.
   - 사용자가 직접 방문해 이어갈 작업은 user-session, 다른 관점이 필요한 작업은
     구체적인 perspective 사유로 선택합니다. 결과 수락은 현재 root가 맡습니다.
   - 배치 도구·격리 대상·권한이 없으면 정확한 capability gap을 보고합니다.
     실행 가능한 root 작업의 serial fallback에는 관측 근거와 이유를 기록합니다.
     이를 성공한 병렬 wave로 표시하지 않으며 독립 review에는 serial fallback이 없습니다.

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

같은 세션 안의 bounded 작업과 독립 검토는 native subagent를 사용하고, 독립 실행이
선택된 병렬 구현에만 provider 배치를 사용합니다. 선택은 공통 정책의 purpose,
session_basis와 reason을 따릅니다. 앱 create_thread는 사용자가 방문할 독립 작업을 위한 도구이며
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
