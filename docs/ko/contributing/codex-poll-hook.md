<!-- last_updated: 2026-09-28; synced_from: 653dedfdfce8a5f741317d23026d3bf8583981f8 -->
# 스톡 Codex 배치 실행

[English](../../en/contributing/codex-poll-hook.md)

Neurath는 일반 Codex 설치와 실행 경로를 사용합니다. 패치한 Codex 실행 파일,
커스텀 launcher, 교체한 code-mode host를 요구하지 않습니다.
아래 검사로 설치된 배포본과 실제 실행 중인 호스트를 확인합니다.
소스 테스트, 독립 실행, 데스크톱 활성화는 각각의 근거로 확인해야 합니다.

## 호스트 관측 경계

훅은 호스트가 해당 이벤트를 전달할 때만 대기를 거부할 수 있습니다.
관측한 스톡 code-mode 경로는 텍스트만 출력하는 `functions.exec` 호출에서도
바깥쪽 `PreToolUse` 이벤트를 보내지 않았습니다. 따라서 바깥 wrapper를 막는
방법으로 누락된 보장을 제공할 수 없습니다. 중첩 대기의 관측 가능성도 호스트에
따라 다릅니다. Wrapper 소스, 선언한 훅 설정, 모의 훅 테스트만으로 실제 실행 중인
호스트가 어떤 이벤트를 전달하는지 증명할 수 없습니다.

배치 스케줄링은 준비된 작업의 실행 결정을 Neurath 런타임으로 옮깁니다.
모든 에이전트 대기의 가로채기에 의존하지 않으며, 임의의 스톡 Codex 도구 호출에서
모든 대기를 막는다고 주장하지 않습니다.

## 런타임이 관리하는 worktree 배치

Root는 작업 요구와 관측한 호스트 지원에 따라 native subagent, 독립 세션, 교차 provider 위탁을 먼저 선택합니다. 독립 실행이 필요한 assignment만 `provider_wave_run`에 전달하며 worktree 격리나 stock Codex만으로 이 backend를 선택하지 않습니다.
각 항목은 `entry_id`, `depends_on`, assignment·서로 다른 설치된 issue worktree·
정확한 모델 plan ID/revision을 담은 provider `request`를 가집니다.
Wave는 현재 task ID/revision, 관측한 capacity, 해당하는 경우 소유한 workflow에
결속됩니다. 하나라도 실행하기 전에 모든 항목을 검증합니다. 대상은 격리되고
깨끗하며 claim되지 않은 worktree여야 하고, 실행 선택·모델·실행 정책 검사를 적용합니다.
각 request는 `purpose`와 구체적인 `reason`을 명시하며 같은 provider의 `worktree-worker`에는
`session_basis=independent-lifecycle` 또는 `native-capability-gap`도 필요합니다. 배치가 이 값을 자동 생성하지 않습니다.

런타임은 `max_parallel` 한도 내의 ready 항목을 한 transaction에서 예약하고,
제출 전에 실행할 항목을 영속 저장합니다. Worker의 종료 이벤트가 슬롯을 비우면
독립된 ready 항목을 실행합니다. 의존 항목은 root가 선행 작업의 정확한 성공
결과를 읽고 수락한 뒤에만 준비됩니다. 접수·실행·worker 완료·root 수락은
서로 다른 상태입니다.

이 worker는 선택한 `worktree-worker` 또는 교차 provider `perspective` 경로의 독립 세션입니다.
네이티브 직접 자식이나 독립 검토자가 아닙니다. 각 worker는 쓰기 전에 자신의
네이티브 준비 상태와 worktree claim을 확인해야 합니다. Root는 task/workflow
소유권, 통합, 검토와 최종 수락을 유지합니다.

결과나 복구 이벤트 뒤에는 `provider_wave_read`로 실제 run 신원과 결과 지문을
읽고 영속 저장된 미제출 작업을 조정합니다. `provider_wave_consume`에 정확한
entry ID·run ID·generation·digest와 `accepted` 또는 `rejected` 판정을
전달합니다. 종료 상태를 성공으로 간주하거나 불확실한 실행을 새 실행으로
재시도하지 않습니다. `provider_wave_cancel`은 이후 예약을 막고 각 run의 제어
채널로 취소를 요청합니다. 관측한 결과와 미완료 사용자 요구는 보존합니다.

`provider_wave_retry`는 정확한 run의 종료가 확인된 failed 또는 cancelled 구현
attempt에만 사용합니다. 원래 assignment·provider·worktree는 바꿀 수 없습니다.
모델 계획과 상속 정책을 새로 검증하고, generation 1의 종료 결과와 worker OS
lease 해제를 확인해야 합니다. Native 세션이 생성됐다면 해당 세션의 연결·프로세스
종료도 확인해야 합니다. 수락한 작업·수락한 후속 작업이 있거나 wave 자체가
취소됐다면 재시도할 수 없습니다. 이전 attempt의 요청·결과·지문·소비 기록은
변경 없이 보존합니다.

과거 native 연결 종료가 확인되지 않아 terminal failed/cancelled wave를 재시도할 수
없다면, 별도 wave가 같은 이슈 그래프를 완료할 수 있습니다. 대체 wave의 모든 항목을
root가 정확한 성공 결과로 수락한 뒤 `provider_wave_supersede(old_wave_id,
new_wave_id, key)`로 task 원장을 조정합니다. Task 정의, workflow, 항목 의존성,
provider와 worktree가 같아야 하며 이전 worker lease는 종료되고 OS 잠금도 풀려
있어야 합니다. 이전 결과는 failed/cancelled로 남고, 이 조정은 누락된 연결 종료를
증명하거나 이전 native 세션의 재실행을 허용하지 않습니다. 실행되지 않은 후속 항목은
cancelled, 이미 수락한 형제 결과는 accepted로 보존하며 이전 wave의 새 예약·재시도는
거부합니다.

이전 attempt를 포함한 모든 wave 연결 run은 `provider_recover`를 거부합니다.
이 도구의 inbox 연결 복구는 구현 assignment를 충족할 수 없습니다. 새로 검증한
구현 attempt와 같은 신원으로 영속 저장된 미제출 실행을 재개하는 것은 구분합니다.

Crash 이후 조정은 인증된 owner의 조회, 동일 요청 replay, 정확한 결과 소비와
worker 종료 callback에서 수행합니다. 영속 실행 기록과 lease 검사를 사용합니다.
시작 시 scanner나 주기적 polling은 없으며, 이런 계기 없이 관측하지 못한 crash가
스스로 복구된다고 주장하지 않습니다.

독립 리뷰는 별도로 준비한 `role="review"` 네이티브 자식을 계속 사용합니다.
Codex는 `fork_turns="none"`을 사용하며 호스트가 새 컨텍스트와 계보를 확인해야
합니다. Provider 결과는 이 증명을 대신할 수 없습니다.

## 검증 경계

접수와 스케줄링은 관련 테스트로 검사한 뒤, 설치된 배포본과 수정하지 않은 실제
호스트를 별도로 검증합니다. 실제 배치 검사는 ready worker 실행, 비워진 슬롯의
독립 작업 실행, 정확한 root 수락 전 의존 작업 보류, 취소와 실패 결과 보존을
관측해야 합니다. 실제 사용한 실행 파일과 관측 이벤트를 기록합니다.
패키지 설치나 독립 실행 성공만으로 현재 데스크톱의 동작을 증명할 수 없습니다.
호스트 신뢰·권한·기존 claim을 보존합니다.

[호스트 경계](hosts.md)와 [협업 계약](collaboration-contract.md)을 참고하세요.
