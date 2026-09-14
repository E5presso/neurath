<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/design-principles.md)

# 하네스를 이해하기 쉽게 만드는 설계 판단

하네스는 사용자가 요청한 결과에 도달하고 그 결과를 확인하기 쉽게 해야 한다. 새 상태 기록, 필수 전이, 주입 지침을 추가할 때는 각각 무엇을 책임지는지 설명할 수 있어야 한다. 같은 완료 판단을 여러 곳에 기록하는 설계라면 자동화를 더하기 전에 판단 주체부터 단순하게 정리한다.

## 사용자에게 필요한 결과부터 정의한다

작업은 관찰 가능한 결과, 요청 출처, 완료 조건으로 정의한다. 저장소에서 확인한 사실, 현재 사용자의 결정, 되돌릴 수 있는 가정은 서로 다른 입력이다. 목표와 미확정 사항을 관리하는 모델은 이를 구분해 가정을 권한으로 바꾸지 않으면서 독립적으로 가능한 일을 진행하게 한다.

현재 사용자 지시와 현재 소스는 메모리, 동료 제안, 생성된 계획보다 우선한다. 중간 질문은 진행 중인 작업을 취소하지 않고 보완할 수 있다. 취소되거나 대체된 작업은 이유와 함께 명시적으로 기록한다. 화면에서 지우기만 하면 요청 이력을 잃는다.

## 판단을 대신하지 않고 자기 점검을 돕는다

Neurath의 핵심 전략은 작업 중 원래 목적과 완료 조건을 다시 떠올리게 하는 것이다. 에이전트는 다음 행동이 아직 충족하지 못한 사용자 요구를 해결하는지, 자신이 고른 방법만 더 다듬는지 살필 수 있다. 도움이 되지 않는 방법은 바꾸거나 버려도 원래 태스크는 유지한다.

목표 환기는 메타인지를 돕는 맥락이며 의미상 목표 수렴을 정량 판정하는 기능이 아니다. 별도 성찰문·태스크·평가 루프·완료 gate를 만들지 않는다. 시간과 토큰 한도는 낭비를 줄이는 기준이다. 완료 조건을 낮추거나 한 번 실패한 시도를 태스크 취소로 바꿀 권한은 주지 않는다. 진행 상황을 묻는 질문도 새 범위의 승인이 아니다.

조사는 관련 완료 조건에 필요한 범위에서 수행한다. 하네스 평가 스킬은 자체 절차를 만족시키기 위한 무제한 inventory나 generation을 요구하지 않는다. 다른 스킬의 적용 가능한 반복 계약은 유지하며, 검사는 프로젝트의 기존 실행기를 사용한다. 환기의 전달 조건은 [런타임 수명주기](runtime-lifecycle.md)에 설명한다.

## 판단마다 책임 주체를 하나로 정한다

| 판단 | 최종 기준 | 판단을 돕는 정보 |
| --- | --- | --- |
| Stop 시 등록 작업이 모두 정리되었는가? | 루트 턴 종료와 같은 트랜잭션에서 확인한 최신 작업 목록 | 네이티브 TODO 표시, 소유자 결과 참조 |
| 이 참여자가 워크트리를 바꿔도 되는가? | 검증된 호출자와 현재 소유권 및 fencing token | 세션 진단, 워크트리 식별 정보 |
| 계약이 있는 워크플로가 다음 단계로 가도 되는가? | 현재 단계 계약과 해당 평가 권한 | 근거 자료, 발견 사항, 보고 |
| 위임 결과가 받아들여졌는가? | 인증된 보고와 필요한 소유자의 결과 소비 | 전송 상태, 동료 논의 |
| 설치가 적용되었는가? | 트랜잭션 결과와 설치 내용 검증 | 계획 미리보기, 복원 자료 |
| 외부에 내용을 게시해도 되는가? | 해당 사용자 승인과 정확한 게시 계약 | 준비된 초안, 로컬 검증 |

일반 작업은 소유자가 종료 결과를 한 번 기록한다. 별도 워크플로, material batch, 완료 조건별 보고서, 독립 작업 검토자를 의무적으로 요구하지 않는다. 명시적으로 실행한 평가·검토 워크플로는 자체 계약을 계속 적용한다. 작업 목록이 있는 세션에서 이를 일반적인 Stop의 추가 투표로 사용하지 않는다.

## 실제 호스트에서 권한을 확인한다

세션 식별자, 현재 턴, 자식 관계는 호스트가 제공한다. Neurath는 변경을 허용하기 전에 이를 검증한다. 호출 인자, 복사한 환경 변수, 임의의 프로세스 번호, 동료의 주장으로 그 권한을 만들 수 없다.

허용 판단은 정확한 작업과 입력에 묶는다. 검토 후 인자를 바꾸어 구체적인 행동에 대한 승인을 다른 행동으로 넓히면 안 된다. 네이티브 도구로 끝낸 테스트 역시 사용자가 나중에 질문했다고 관찰 결과가 바뀌지 않는다. 이후 턴 상태로 이미 수행된 검사를 다시 해석하지 않는다.

실패 시에는 호출자 식별, 현재 턴, 작업 공간 소유권, 제공자 실행 모드, 외부 전달 중 어느 경계에 문제가 있는지 드러낸다. 지원하지 않는 모드는 명시적인 제한이다. 같은 요청을 성공처럼 보이게 하려고 더 느슨한 셸 경로를 추가하지 않는다.

## 동시 실행과 재시도를 계약에 포함한다

상태 변경에는 반환된 식별자와 예상 리비전을 사용한다. 목록 리비전은 작업 집합을, 작업 리비전은 개별 작업을, fencing token은 현재 소유권 세대를 보호한다. 제목, 이전 세션, 인접 워크트리의 값에서 이 정보를 추측할 수 없다.

멱등 키는 하나의 정확한 요청을 가리킨다. 결과가 불확실한 동일 요청을 재시도할 때는 같은 키를 사용한다. 입력을 바꾸려면 현재 상태를 확인하고 새 키를 쓴다. 같은 키에 다른 입력을 넣는 것은 갱신이 아니라 충돌이다.

함께 일치해야 하는 조회와 판단은 하나의 트랜잭션에 넣는다. 작업 Stop 확인과 턴 종료가 대표적이다. 동시에 추가한 작업은 종료 판단에 보이거나, 종료 후 유효한 호출 조건 아래 추가되어야 한다. 예전 목록을 확인한 다음 별도로 턴을 닫으면 작업을 놓칠 수 있다.

## 관찰한 수준에 맞게 결과를 설명한다

| 관찰 | 확인할 수 있는 사실 |
| --- | --- |
| `accepted` 또는 대기열 등록 | 요청이 접수됨 |
| 네이티브 프로세스 시작 | 실행이 시작됨 |
| 검사 출력과 종료 코드 | 그 실행 범위에서 관찰한 검사 결과 |
| 소유자의 작업 결과 | 소유자가 인증된 방식으로 보고한 결과 |
| 독립 평가 결과 소비 | 필요한 평가자가 정확한 후보를 평가했고 소유자가 그 결과를 반영함 |
| 원격 재조회 | 외부 시스템에 관찰한 게시물이나 변경이 존재함 |

메시지 수신 확인은 할당 결과의 소비와 다르다. 체크포인트는 맥락과 진행 상황을 보존한다. 어느 것도 작업 공간 소유권을 이전하지 않는다. 이 차이를 결과 객체와 사용자 설명에 반영하되 매 문단마다 모든 구분을 되풀이하지 않는다.

## 호스트와 프로젝트를 보존한다

generic 프로필은 실제 프로젝트 문서와 검사 절차에 연결한다. 애플리케이션 프레임워크를 강제하거나 기존 의존성을 대체하지 않는다. 설치는 사용자 지침, 훅, 호스트 권한, 수정된 프로젝트 설정을 보존한다. 불변 계획으로 정확한 교체 내용을 적용 전에 확인하고 충돌을 해결할 수 있게 한다.

호스트 어댑터는 네이티브 이벤트를 공통 모델에 연결하면서 호스트별 근거를 유지한다. Codex와 Claude Code의 자식 확인 절차는 다르다. 무리하게 같은 입력 형태를 강제하면 실제 차이를 숨기게 된다. 하네스 실행 환경도 대상 애플리케이션 환경과 분리한다.

## 보존하는 맥락에 한계를 둔다

메모리는 다음 작업에 필요한 결정과 사실을 출처 및 크기 제한과 함께 보존한다. 숨겨진 추론을 수집하거나 기억한 모든 선호를 현재 규칙으로 만들지 않는다. 최근 세션 사실, 프로젝트 이력, 학습 전략, 승인된 저장소 규칙을 구분하고 바뀔 수 있는 저장소·런타임 사실은 다시 확인한다.

공개 문서에는 재사용 가능한 동작과 소스 참조를 싣는다. 설치 원본, 네이티브 대화 기록, 호스트 식별자, 개인 경로, 상세 검증 자료는 비공개로 보관한다. 문서는 검증 항목을 재현하는 방법을 설명하며 과거 실행을 현재 검증처럼 제시하지 않는다.

## 변경안을 검토하는 기준

사용자가 확인할 결과가 명확한지, 완료 판단 주체가 하나인지, 출처와 신원이 정확히 연결되는지, 실패 복구 범위와 관련 회귀 테스트가 있는지 확인한다. 이름이 있는 도구 스키마가 이미 제공하는 정보는 중복 도움말 조회나 기록 절차로 다시 만들지 않는다. 속도와 토큰 절감 주장은 실측이 필요하며 스키마가 단순하다는 사실만으로는 설계 의도를 설명할 수 있을 뿐이다.

모듈 책임은 [구조](architecture.md), 작업 호출 계약은 [작업 도구](task-tools.md), 변경을 뒷받침할 관찰은 [검증](validation.md)을 참고한다.

## 설계 검토의 소스 근거

변경이 앞서 설명한 책임을 유지하는지 다음 구현에서 확인한다. 호환 코드는 저장된 기존 호출 경로를 검토할 때 참고한다.

| 책임 | 소스와 회귀 검사 |
| --- | --- |
| 목표·단계·평가 | [adaptive_control.py](../../../src/neurath/_assets/scripts/agent_harness/adaptive_control.py), [adaptive_control_authority.py](../../../src/neurath/_assets/scripts/agent_harness/adaptive_control_authority.py), [efficiency_assessment.py](../../../src/neurath/_assets/scripts/agent_harness/efficiency_assessment.py), [evaluation_loop.py](../../../src/neurath/_assets/scripts/agent_harness/evaluation_loop.py) |
| 호스트와 정확한 호출 확인 | [harness_persona_policy.py](../../../src/neurath/_assets/scripts/harness_persona_policy.py), [mcp.py](../../../src/neurath/agents/mcp.py), [hooks.py](../../../src/neurath/hosts/hooks.py), [identity.py](../../../src/neurath/hosts/identity.py), [tasks.py](../../../src/neurath/runtime/tasks.py), [test_prompt_delivery.py](../../../tests/test_prompt_delivery.py) |
| 메시지와 제공자 수명 | [delivery.py](../../../src/neurath/agents/delivery.py), [store.py](../../../src/neurath/agents/store.py), [permission_inheritance.py](../../../src/neurath/providers/permission_inheritance.py), [supervision.py](../../../src/neurath/providers/supervision.py) |
| 제한된 맥락 보존 | [graphify](../../../src/neurath/_assets/.agents/skills/graphify/SKILL.md), [promote-memory](../../../src/neurath/_assets/.agents/skills/promote-memory/SKILL.md), [enclave_store.py](../../../src/neurath/_assets/scripts/agent_harness/enclave_store.py), [learning.py](../../../src/neurath/memory/learning.py), [store.py](../../../src/neurath/memory/store.py), [test_learning.py](../../../tests/test_learning.py) |
| 설치 및 사용자 선택 보존 | [projection.py](../../../src/neurath/install/projection.py), [transaction.py](../../../src/neurath/install/transaction.py), [release_install.py](../../../src/neurath/release_install.py), [reporting.py](../../../src/neurath/reporting.py), [maintenance_tasks.py](../../../src/neurath/runtime/maintenance_tasks.py), [user_choices.py](../../../src/neurath/runtime/user_choices.py) |
| 저장된 호출의 호환성 | [material_action.py](../../../src/neurath/_assets/scripts/agent_harness/material_action.py), [verification.py](../../../src/neurath/runtime/verification.py) |
