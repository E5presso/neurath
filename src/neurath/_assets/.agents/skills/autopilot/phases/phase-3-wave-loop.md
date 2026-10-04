# execute_waves — 준비된 작업 실행과 수락

각 issue Task는 `implement-issue` 스킬의 순서와 인수 조건을 가진다. Autopilot Task는 대상 집합과 의존 관계, 결과 수락을 맡는다. 읽기·위임만 허용된 autopilot phase의 worker에게 구현을 맡겨 쓰기 범위를 넓히지 않는다. 구현 executor는 해당 issue Task에 배정한다.

1. 준비된 독립 Task를 가용 슬롯에 먼저 배정한다. 첫 항목이 끝날 때까지 기다린 뒤 다음 독립 항목을 시작하지 않는다. 실제 충돌 또는 capability 부족으로 직렬화하면 이유를 기록한다.
2. `assignment_prepare`에 Task, 범위, 역할, subject, 실행 선택과 이유를 연결한다. 실행 선택은 `subagent`, `session`, `cross-provider`다. 현재 작업의 bounded 실행은 native subagent를 우선한다. 독립적인 수명이 필요한 경우 session, 다른 provider가 필요한 경우 cross-provider를 선택한다. Worktree 필요나 repository root라는 이유로 새 세션·프로젝트를 만들지 않는다.
3. Native subagent는 반환된 marker를 실제 spawn에 전달하고 관측된 수신자 binding을 확인한다. 독립/provider 세션은 `provider_prepare`가 반환한 native 실행을 사용한다. 준비·접수·연결 성공은 작업 완료가 아니다. 모델·권한은 현재 사용자의 선택과 호스트 설정을 보존한다.
4. Worker 결과는 해당 Assignment의 실제 발신자·대상·현재 소스를 대조해 수락하거나 거절한다. 실패·차단·취소는 실패한 시도의 결과로 남기고 원래 사용자 Task를 완료하지 않는다. 실행 결과가 불확실하면 같은 일을 새 세션으로 중복 시작하지 않는다.
5. Issue의 독립 리뷰, 실제 검사, exact PR head, 저장소가 요구하는 review/CI, unresolved comment와 병합 승인을 충족한다. 구현자는 final reviewer를 겸하지 않는다. `mergeable-clean`은 병합 전 상태다. 승인된 auto-merge 요청은 실제 병합·종료·정리 결과까지 수행한다.
6. 인수된 선행 Task의 결과를 읽은 후 다음 ready Task를 배정한다. Task의 skill phase와 원래 인수 조건을 모두 충족한 결과만 성공으로 집계한다.

Monitor 이벤트는 정확한 issue Task, PR, head와 수신 경로에 연결한다. 이벤트 이후 실제 상태를 읽고 필요한 작업을 이어간다. 다른 세션의 상태를 대신 쓰거나 경과 시간만으로 성공·실패를 추정하지 않는다. Mailbox-only 메시지를 즉시 깨우기 성공이라고 보고하지 않는다.

`wave_plan`에는 대상·의존 관계·선택한 실행 방식·동시성 근거를, `process_ticket_terminal_states`에는 Task ID별 실제 인수 결과와 GitHub 원문을 담는다. 구현 대상이 없으면 수집 단계에서 확인한 이유를 기록한다. 필수 결과가 남아 있으면 이 phase를 완료하지 않는다.

새 follow-up은 `new-ticket-intake.md`, bot의 반복 지적은 `ledger-bot-violations.md`를 필요할 때 읽는다.
