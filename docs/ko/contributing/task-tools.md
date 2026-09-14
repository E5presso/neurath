<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/task-tools.md)

# 프로젝트 작업을 위한 이름이 있는 도구

하네스 상태는 Neurath의 이름이 있는 MCP 도구로 조회하고 변경한다. 일반 소스 편집과 프로젝트 검사는 호스트의 네이티브 도구로 수행한다. 이 API는 범위가 정해진 도메인 인터페이스다. 각 작업은 특정 입력을 받고 실제 호출자를 확인한 뒤 구조화된 결과를 반환한다.

## 도구 조회, 호출자 연결, 결과

표준 입출력 서버는 표준 입력으로 JSON-RPC를 받고 표준 출력에는 프로토콜 JSON을 쓴다. 진단은 표준 오류로 보낸다. 현재 `tools/list`는 공개 도구 128개를 알리며 내부 작업 연결표에는 작업 138개가 있다. 설치 버전의 정확한 스키마는 실제 도구 조회 결과를 기준으로 한다.

입력은 `additionalProperties=false`인 닫힌 객체이며 중첩 도메인 스키마도 허용 필드를 정의한다. 선택적인 전달 필드 `_neurath_binding`은 1~64자 문자열이다. 실제 호스트 연결을 나타내므로 다른 참여자의 값을 복사하거나 만들어 넣으면 안 된다. 공개 입력은 임의 `argv`, Python 모듈 실행, 직접 상태 패치를 제공하지 않는다.

이름이 있는 도구는 공통 외부 결과 형식을 사용한다.

```json
{
  "ok": true,
  "operation": "task_start",
  "result": {
    "revision": 2,
    "all_terminal": false,
    "tasks": [{"id": "TASK_ID_FROM_DEFINE", "revision": 2, "status": "in_progress"}],
    "native_todo": {}
  }
}
```

구조를 보여 주는 예제이며 실제 `native_todo`에는 전체 표시 지침이 들어 있다. 성공 응답은 작업별 결과를 담는다. 실패 응답의 `error`에는 `code`, `message`, `state`, `retryable`, `next_action`이 있다. 일부 실패는 시도한 실행을 설명하는 결과도 보존하므로 재시도 여부를 정하기 전에 상태를 읽는다.

작업 변경 응답은 목록 리비전, `all_terminal`, 작업별 ID·리비전·상태, `native_todo`만 간결하게 반환한다. 전체 정의나 결과 보고 상세는 생략한다. `task_list`는 전체 원장, `current_prompt_source`, 정의 해시, 존재하는 결과 보고 참조와 `assurance`, `todo_projection`, `native_todo`를 반환한다. 변경 직후 중복 조회하지 말고 반환받은 값을 다음 호출에 사용한다.

## 권한 변경 전에 실행 준비 상태 진단하기

실행 도구는 필요한 설치·활성화·소유권·정책 관측 단계가 준비되지 않으면 `execution-readiness-required`와 실패한 단계 이름을 반환합니다. 실행 중인 MCP 패키지가 설치된 배포본과 다르면 해당 MCP 호스트의 재연결이 필요합니다. 반복 설치나 권한 변경으로 기존 프로세스가 갱신되지는 않습니다. `session_status`도 같은 복구 방향을 안내합니다. 준비 상태는 충족하지만 관측된 실행 정책을 지원하지 못하면 기존 `native-execution-required` 거부를 유지합니다. 어떤 진단도 다른 경로를 통한 재실행, 신원 조작, 소유권 강제 회수나 권한 변경을 승인하지 않습니다.

## 작업 등록, 시작, 결과 확정

| 도구 | 필수 입력 | 결과 또는 조건 |
| --- | --- | --- |
| `task_list` | 없음 | 현재 목록과 표시 투영을 읽는다. 작업이 없으면 `all_terminal=false`다. |
| `task_define` | `tasks`, `expected_revision`, `key` | 정의 1~64개를 추가하고 안정적인 ID와 갱신 리비전을 반환한다. |
| `task_start` | `task_id`, `expected_revision`, `expected_task_revision`, `key` | 대기 작업을 `in_progress`로 바꾸며 의존 작업은 종료 상태여야 한다. |
| `task_resolve` | 시작 필드와 `status`, `references`, `summary` | `succeeded`, `failed`, `invalidated`를 기록하며 성공에는 의존 작업 종료가 필요하다. |

목록·작업 예상 리비전은 0~9,007,199,254,740,991 정수다. `task_id`는 1~128자, 작업 호출 키는 1~512자다. 결과 확정에는 서로 다른 참조 1~32개가 필요하고 각 참조는 1~4,096자다. 요약은 1~4,096자다.

정의에는 다음 여섯 필드를 모두 넣는다.

| 필드 | 정확한 입력 형태 |
| --- | --- |
| `key` | 1~512자 문자열. 세션 안에서 정의를 식별하는 안정적인 키다. |
| `title` | 1~512자 문자열. |
| `goal` | 1~16,000자 문자열. |
| `sources` | 필수 `kind`, `reference`, `revision`을 가진 객체 0~31개. 추가 필드는 허용하지 않는다. |
| `acceptance` | 1~16,000자 문자열 1~32개. |
| `dependencies` | 1~128자 작업 ID 0~64개. |

출처의 `kind`는 `prompt`, `ticket`, `spec` 중 하나이고 `reference`, `revision`은 각각 1~4,096자다. 빈 출처 배열을 전달해도 서비스가 실제 사용자 프롬프트를 보존한다. 직접 넣은 프롬프트 참조는 실제 저장된 네이티브 수신 근거와 일치해야 한다.

새 빈 원장에서는 프롬프트 참조를 만들어 넣지 않고 다음처럼 정의할 수 있다.

```json
{
  "tool": "task_define",
  "arguments": {
    "tasks": [{
      "key": "parser-empty-input",
      "title": "Handle empty parser input",
      "goal": "Empty input returns the documented empty result.",
      "sources": [],
      "acceptance": ["The empty-input regression passes.", "Existing valid-input behavior is preserved."],
      "dependencies": []
    }],
    "expected_revision": 0,
    "key": "define-parser-empty-input"
  }
}
```

현재 목록이 실제로 빈 리비전 0일 때만 0을 사용한다. 다음 호출에는 반환된 작업 ID와 리비전을 복사한다.

```json
{
  "tool": "task_start",
  "arguments": {
    "task_id": "TASK_ID_FROM_DEFINE",
    "expected_revision": 1,
    "expected_task_revision": 1,
    "key": "start-parser-empty-input"
  }
}
```

승인된 편집과 실제 검사를 수행한 뒤 결과를 제출한다. 아래 참조와 숫자는 역할을 보여 주는 예제이므로 관찰한 결과 및 이전 호출에서 반환된 리비전으로 바꾼다.

```json
{
  "tool": "task_resolve",
  "arguments": {
    "task_id": "TASK_ID_FROM_DEFINE",
    "expected_revision": 2,
    "expected_task_revision": 2,
    "key": "resolve-parser-empty-input",
    "status": "succeeded",
    "references": ["tests/test_parser.py::test_empty_input"],
    "summary": "The empty-input regression and existing valid-input checks passed."
  }
}
```

기준 결과의 `assurance=agent-report`는 인증된 소유자 보고를 뜻한다. 테스트 이름만으로 실행 관찰이 되는 것은 아니므로 실제 수행한 검사를 정확히 설명해야 한다. 종료 이력의 불변성, 의존 순서, 네이티브 표시 기록, 원자적인 Stop 판단은 [작업과 TODO 계약](task-todo-contract.md)에 있다.

## 소유권과 세션 조회

| 도구 | 입력 | 목적 |
| --- | --- | --- |
| `session_status` | 선택 `detail`: 기본 `summary` 또는 `full` | 현재 참여 상태, 준비 상태, 소유권을 확인한다. |
| `session_inspect`, `turn_inspect`, `worktree_inspect` | 업무 필드 없음 | 복구·변경 전에 해당 도메인 상태를 읽는다. |
| `worktree_claim` | 업무 필드 없음 | 실제 호출자의 현재 워크트리 소유권을 얻는다. |
| `worktree_release` | `expected_lease_epoch`(1~9,007,199,254,740,991), `fencing_token`(1~256자) | 해제 계약에 따라 이 소유자에게 반환된 정확한 소유권을 해제한다. |
| `worktree_isolation` | `issue_number`(1~2,147,483,647), `key`; 선택 `initialize=false` | 지원되는 계약으로 이슈의 격리 작업 공간을 준비한다. |
| `worktree_cleanup` | `workflow_id`, 확인된 `base_branch`, 확인된 `remote_ref`, `key` | 소유권과 Git 상태를 확인하며 계약에 따라 정리한다. |

소유권은 설치와 호스트 활성화에서 독립적이다. 모델이 실행 중이거나 이전 체크포인트가 있다는 이유로 현재 소유권을 추정하지 않는다. 해제, 정리 예약, 재개는 [실행 수명주기](runtime-lifecycle.md)에 설명한다.

## 명시적인 스킬 워크플로의 단계

실제 스킬 계약에서 시작해 그 계약의 현재 ID와 레이블을 사용한다. 공통 단계 입력은 다음과 같다.

| 도구 | 필수 필드 | 선택 필드와 제한 |
| --- | --- | --- |
| `phase_start` | `workflow_id`, `key`, `skill`, `run_id`, `north_star` | 빈 문자열 불가. 워크플로·실행 ID 최대 256자, 스킬 128자, 키 512자, 목표 16,000자. |
| `phase_current` | `workflow_id` | 현재 계약 상태와 리비전을 반환한다. |
| `phase_evidence_prepare` | `workflow_id`, `expected_revision`, `key` | `labels=[]`: 1~16,000자 문자열 최대 32개. `notes=[]`: `label`(1~128자), `text`(1~16,000자)를 가진 객체 최대 128개. |
| `phase_complete` | `workflow_id`, `expected_revision`, `key`, `phase_id`, `status`, `summary` | `phase_id`: 0~1000. 상태는 `completed`, `skipped`, `failed`, `blocked`. `reason=""`, `terminal_state=""`, `evidence_refs=[]`. |
| `phase_finalize` | `workflow_id`, `expected_revision`, `key`, `terminal_state` | 종료 상태는 1~128자 문자열. |

단계 리비전도 0~9,007,199,254,740,991 정수다. `phase_complete`의 요약은 1~16,000자, 이유는 최대 16,000자, 종료 상태는 최대 128자이며 근거 참조는 1~16,000자 문자열 최대 32개다. 스키마에 맞는 값이라도 상태, 생략 이유, 종료 상태가 실제로 유효한지는 워크플로 계약이 결정한다.

`evidence_refs`에는 `phase_evidence_prepare` 결과를 사용한다. 레이블은 현재 단계에 맞는지 검사한다. 운영형 마지막 단계는 `terminal_state`로 원자적으로 끝낼 수 있다. 별도 종료 전이가 필요한 계약은 `phase_finalize`를 쓴다. 스킬을 읽거나 통과했다고 문장으로 쓰는 것만으로 단계가 바뀌지는 않는다.

`workflow_start`, `workflow_advance`, `workflow_finalize`는 저장된 기존 호출의 호환성을 위해 연결을 유지하지만 공개 도구 조회에는 나오지 않는다. 현재 클라이언트는 단계 도구를 사용한다.

## 다른 제공자의 미완료 작업을 이어받는다

`memory_pull`은 `list`, `preview`, `read`, `adopt`를 제공한다. 수신자는 세션을 찾고 정확한 원본을 미리 읽은 뒤 승계를 선택한다. 승계에는 반환된 변경 불가능한 `reference`, 수신자 원장의 현재 `expected_revision`, 미리보기와 다른 안정된 key를 사용한다. 원본 실행이 정리됐을 때만 미완료 작업과 worktree 소유권을 넘긴다. [전체 입력과 페이지 읽기](provider-continuity.md)를 참고한다.

`task_list`는 `all_succeeded`와 `unsuccessful_task_ids`도 반환한다. `all_terminal`만으로 목표 달성을 판단하지 않는다. 정의에는 네이티브 프롬프트 출처가 필요하며 새로 접한 프롬프트 출처는 명시적으로 선택한다. 결과와 등록 규칙은 [작업 계약](task-todo-contract.md)에 설명한다.

## 다른 도메인과 호환성

전체 공개 도구 계열과 구현 담당은 [기능 지도](capability-map.md)에 있다. 개별 계약은 [에이전트 참조](agents-reference.md), [모델 계획](model-planning-mcp.md), [협업](collaboration-contract.md), [메모리](memory-reference.md), [설치](installation.md), [업데이트](releases-reference.md), [보고](reporting-reference.md)를 참고한다.

일반 동료 작업에는 `collaboration_assign`, `collaboration_accept`, `collaboration_report`를 사용한다. 메시지 수신 확인에는 본문 전체 조회가 필요하며 이것으로 할당이 완료되지는 않는다. 일괄 전송과 수신 확인은 공개된 닫힌 스키마를 따르고, 단일 전송 필드와 `messages` 배열을 섞지 않는다. 실제 자식 위임과 평가에는 메시지 외에도 검증된 네이티브 부모 관계가 필요하다.

material·등록 검사 작업과 일반 `agent(argv)` 진입점은 저장된 기존 호출의 호환성 기능이다. 현재 공개 조회에는 없으며 일반 네이티브 편집과 검사의 필수 래퍼가 아니다.

`harness_bypass`는 일반 바인딩 허용 조건의 예외다. `enabled=true`, `false`는 현재 워크트리 스위치를 변경하고 생략 또는 `null`은 조회한다. 네이티브 바인딩이나 작업자 슬롯 없이 사용할 수 있으며 이력과 호스트 권한은 보존한다. 다른 MCP 작업은 실제 바인딩이 필요하고 우회 활성 중에는 사용할 수 없다.

## 요청을 바꾸기 전에 실패 원인을 확인한다

| 실패 | 의미 | 다음 행동 |
| --- | --- | --- |
| `revision-conflict` | 목록이나 작업 리비전이 바뀌었다. | 최신 원장을 읽고 실제 리비전으로 새 요청을 판단한다. |
| `task-contract-rejected` | 잘못된 작업 입력, 미해결 의존 작업, 불변 종료 이력 등 도메인 조건 위반이다. | 메시지가 가리키는 조건을 해결하고 저장 상태를 직접 패치하지 않는다. |
| `native-turn-changed` | 트랜잭션 허용 판단에서 프롬프트나 활성 연결이 달라졌다. | 실제 현재 네이티브 턴으로 들어와 상태를 확인한다. |
| 같은 키에 다른 입력 | 하나의 멱등 식별자를 서로 다른 요청에 사용했다. | 원래 요청의 식별자를 유지하고 새 입력에는 새 키를 쓴다. |
| 제공자·전달 접수 후 미완료 | 실행이나 전달이 아직 남아 있다. | 이벤트, 본문 전체 재조회, 해당 복구 계약을 따른다. |

재시도 가능한 오류는 그 작업의 복구 절차를 따를 수 있다는 뜻이지 호스트 권한을 넓혀도 된다는 뜻이 아니다. 불확실한 결과는 실제 결과나 지원되는 복구가 해결할 때까지 보존한다.

스키마와 실행 연결은 [작업 스키마](../../../src/neurath/runtime/task_schema.py), [작업 정의](../../../src/neurath/runtime/task_ledger_tasks.py), [실행 연결표](../../../src/neurath/runtime/tasks.py), [MCP 서버](../../../src/neurath/agents/mcp.py)에 있다. 회귀 범위는 [통신 MCP](../../../tests/test_communication_mcp.py), [작업 도구](../../../tests/test_task_tools.py), [MCP 지침](../../../tests/test_mcp_guidance.py)에서 확인한다.
