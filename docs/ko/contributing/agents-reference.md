<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/agents-reference.md)

# 참여자의 역할과 권한 확인

Neurath는 사용자의 현재 에이전트, 네이티브 직접 자식, 별도로 소유한 provider 세션을 구분합니다. 이 구분에 따라 worktree 편집, 할당 수락, 후보 평가, 중단 후 재개 권한이 달라집니다. 표시 이름이나 역할을 설명하는 메시지만으로 해당 권한을 얻을 수 없습니다.

## 협업 형태 선택

| 필요한 일 | 참여자 | 권한과 수명 |
| --- | --- | --- |
| 현재 작업에서 분리 가능한 제한된 일 | 네이티브 말단 자식 | 호스트가 확인한 직접 부모·자식 관계 |
| 독립 수명, 다른 provider, 필요한 격리 | 소유한 provider 세션 | 별도 실행 기록과 해당 worktree의 준비 확인 |
| 기존 협업자의 정보 | 발견한 동료 | 인증된 메시지 출처와 동료 자신의 사용자 지시 범위 |
| 명시적 계약이 요구하는 독립 검토 | 연결된 검토자 | 정확한 후보·할당 권한과 소유자의 결과 소비 |

현재 작업에서 이미 승인된 일을 나눌 때는 네이티브 말단 자식이 기본입니다. 독립 provider 실행에는 이유와 기존 승인이 필요합니다. 받은 동료 요청이 새 세션 생성이나 사용자 목표 확대를 허용하지는 않습니다. fork는 자체 시작 확인과 자체 worktree 소유권이 필요한 별도 루트입니다.

## 상태 변경 전 호출자 확인

네이티브 훅은 실제 호스트·세션·현재 턴·worktree·정확한 도구 입력을 연결합니다. 호출자가 입력한 ID만으로 권한이 생기지 않습니다. MCP 입력 스키마는 닫혀 있으며, 선택 필드 `_neurath_binding`은 호스트가 제공하는 인증 자료입니다. 예제에 임의로 채우거나 다른 호출자의 값을 복사하면 안 됩니다.

`session_status`에 `{"detail":"full"}`을 전달하면 설치, 활성화, 정책, 세션, 소유권을 진단할 수 있습니다. `session_inspect`, `turn_inspect`, `worktree_inspect`는 해당 상태를 좁혀 읽습니다. 설치 파일 존재, 실제 호스트 활성화, 적용된 정책, 소유권 획득은 각각 확인해야 합니다. 실행 경로 제안만으로 준비가 완료되지 않습니다.

직접 자식을 만들 때는 부모가 네이티브 spawn 직전에 `delegation_prepare`로 `delegation_id`, `assignment`, 안정적인 `key`를 기록합니다. 일회용 의도는 실제 호스트 근거와 일치해야 합니다. Codex는 실제 spawn 결과와 자식 대화 기록의 메타데이터를, Claude는 자식 대화 기록의 부모 Agent 호출 참조를 확인합니다. 오래되거나 재사용·복사한 참조로 관계를 만들 수 없습니다. 대화 기록 등록이 늦으면 첫 상태 작업에서 재확인할 수 있지만, 확인 전에는 자식의 셸·쓰기 동작이 `child-identity-unverified`로 차단됩니다.

이 구조에서는 네이티브 직접 자식만 지원합니다. 중첩 spawn에 부모 식별자를 복사해도 유효해지지 않습니다. 관계 확인 후 `delegation_assign`에 `workflow_id`, `delegation_id`, `assignment`, `target`, `key`를 전달해 명시적 workflow에 연결합니다. 독립 평가에는 실제 평가 계약과 인증된 보고 소비도 필요합니다.

## worktree별 쓰기 소유자 유지

인증된 호출자는 `{}`로 `worktree_claim`을 호출하고 반환된 lease epoch와 fencing token을 보존합니다. lease는 현재 소유자를 식별하고 token은 소유권이 바뀐 뒤 이전 소유자가 쓰는 것을 막습니다. 다른 에이전트의 탐색 결과, 작업 수락, checkpoint, 루트 식별자는 소유권을 대신하지 않습니다.

`worktree_release`에는 실제 소유권 기록의 `expected_lease_epoch`와 `fencing_token`이 필요합니다. 값이 오래되었다면 새 token을 추측하거나 강제로 인수하지 말고 현재 소유자를 확인합니다. 여러 에이전트가 같은 worktree를 읽을 수 있지만 쓰기는 한 명이 맡아야 합니다. 독립 provider가 편집하기 전에는 자기 대상의 설치·실제 활성화·적용 정책·선택 모델·소유권을 확인합니다.

격리가 필요하면 [기능별 실행 경로](capability-map.md)의 worktree 준비·정리 절차를 사용합니다. 정리에는 독립적으로 확인한 기준 브랜치와 remote 참조가 필요하며 저장소 관례를 추측하거나 기존 소유자를 밀어내면 안 됩니다.

## 기존 동료 찾기와 할당

동료는 `collaboration_register`로 간결한 이름과 소개를 등록하며 실제 식별자는 런타임이 연결합니다. 전체 대화를 복사하지 않고 필요한 동료를 찾을 수 있습니다.

```json
{"tool":"collaboration_discover","arguments":{"query":"API","limit":10}}
```

반환된 정확한 주소를 사용합니다. 질문·제안은 `collaboration_send`, 일반 작업 할당은 `to`, `message`, `key`를 받는 `collaboration_assign`으로 보냅니다. 수신자는 반환된 작업 ID로 `collaboration_accept`를 호출하고, `collaboration_report`에서 `started`, `waiting`, `error`, `failed`, `cancelled`, `completed` 상태를 보고합니다. `collaboration_task`는 할당 기록을 읽습니다.

메시지 수신 확인과 작업 수락은 별개입니다. 연결이 끊긴 수신자는 새로 확인된 네이티브 턴에서 다시 수락해야 하며, 무관한 과거 턴으로 재개할 수 없습니다. 완료 보고를 받으면 발행자가 요청한 실제 효과를 확인해야 합니다. 본문 읽기·ACK·응답·복구는 [메시지 전달 계약](collaboration-contract.md)에 설명합니다.

## 원래 작업 재개

일반 호스트 `SessionEnd`는 재개 가능한 세션·작업·enclave·소유권을 보존합니다. 재개 근거가 확인된 `SessionStart`에서 네이티브 관계를 복원합니다. 커널의 명시적 `SessionEnded`는 영구 종료이며 시작 문자열로 되살릴 수 없습니다. 올바른 루트 요청이나 네이티브 재개는 이전에 중단된 현재 턴을 닫되 남은 작업과 위임은 보존합니다.

작업 목록이 있으면 Stop은 공통 데이터베이스에서 최신 목록 확인과 종료를 원자적으로 처리합니다. 일반 작업은 인증된 소유자가 직접 근거와 결과 요약으로 해결합니다. checkpoint·학습·TODO·독립 검토가 추가 완료 투표를 하지는 않습니다. 명시적 단계와 검토 workflow에는 해당 요구가 유지됩니다. [작업 도구](task-tools.md)와 [작업·TODO 계약](task-todo-contract.md)을 참고합니다.

확인된 루트 턴에는 무한 반복을 막는 Stop 계속 실행 기회가 한 번 있습니다. 남은 작업은 미완료로 반환하며 이후 확인된 사용자 턴은 자체 기회를 갖습니다. 늦게 온 Stop이 더 최신 턴을 닫을 수 없습니다. 일치하는 턴이 없는 Stop은 상태 변경 없이 비차단 진단을 남깁니다. 지원되는 앱 동료 전달도 실제 대화 기록과 네이티브 턴 근거가 있을 때 기존 목표를 이어갈 수 있으며 사용자 승인을 생성하지는 않습니다.

## 구현과 확인 대상

[호스트 식별](../../../src/neurath/hosts/identity.py)과 [훅](../../../src/neurath/hosts/hooks.py)이 호출자를 확인합니다. [SessionKernel](../../../src/neurath/_assets/scripts/agent_harness/session_kernel.py), [StateHandle](../../../src/neurath/_assets/scripts/agent_harness/state_handle.py), [WorktreeRegistry](../../../src/neurath/_assets/scripts/agent_harness/worktree_registry.py)는 생명주기·접근·소유권을 담당합니다.

[호스트 생명주기 테스트](../../../tests/test_host_lifecycle.py), [프롬프트 전달 테스트](../../../tests/test_prompt_delivery.py), [worktree 테스트](../../../tests/runtime/agent_harness/test_worktree_registry.py)는 이 경계를 검사합니다. 실제 호스트 수락 검증에서는 새 시작, 실제 자식 관계, 중단·재개, 조기 완료 거절, 인증된 결과 소비, 소유권 해제를 추가로 관찰해야 합니다. 프로토콜 모의 검사나 소스 테스트의 통과는 각각 검사한 범위의 근거입니다.
