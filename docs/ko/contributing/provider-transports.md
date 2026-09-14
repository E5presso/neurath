<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# 다른 네이티브 세션에서 작업 실행하기

[English](../../en/contributing/provider-transports.md) · [기여자 시작 안내](index.md)

provider는 에이전트를 실행하는 호스트로, 현재 Codex와 Claude Code를 지원합니다. 전송 경로(transport)는 그 호스트의 세션을 생성하거나 통신하는 연결 방법입니다. 승인된 작업에 별도 신원·설정·활성화·체크아웃 소유권을 가진 독립 루트가 필요할 때 Neurath가 이 연결을 사용합니다.

가상의 필터 문제에서는 첫 루트가 새로고침 복원을 조사하는 동안 두 번째 루트가 API 저장과 응답을 독립적으로 확인할 수 있습니다. 이미 존재하는 동료가 답을 알고 있을 수도 있고, 제한된 조사라면 직접 자식으로 충분할 수도 있습니다. [협업 계약](collaboration-contract.md)에 따라 관계를 먼저 정해야 합니다. 독립 세션 생성은 별도 동작입니다.

## 사용할 경로를 찾는 것과 실행하는 것

`provider_capabilities(provider)`는 구현된 경로와 사용 조건을 보여 줍니다. 실제 사용 가능 여부는 현재 호스트의 도구와 연결에서 확인합니다. 바이너리 버전, 데스크톱 앱 설치, 기능 목록 한 줄만으로 사용할 세션이 있다고 판단할 수 없습니다.

| 경로 | 구현 범위 | 필요한 관측 |
| --- | --- | --- |
| Codex app-server | 생성·검색·연결·메시지·상태·재개·취소 | 명시적으로 연결된 JSON-RPC 전송, 소유 세션, 적용 정책의 재조회. |
| Codex 앱 도구 | 생성·검색·읽기/연결·메시지·상태·동료 메시지 | 현재 호스트 도구 목록의 해당 앱 도구. 이 목록은 앱 생성 정책을 증명하지 않습니다. |
| Claude Agent SDK | 생성·메시지·상태·취소 | 소유한 스트리밍 클라이언트, 명시적 네이티브 권한 모드, 훅 준비 상태. OS 격리는 따로 확인합니다. |
| Claude 네이티브 도구 | 동료 검색·메시지 | 현재 네이티브 도구와 검색으로 확인한 정확한 수신자. |
| Claude 백그라운드 목록 | 검색·상태 | 네이티브 백그라운드 작업 관측. 짧은 작업 ID와 세션 UUID는 다르며 정책도 별도로 관측합니다. |
| CLI | 소유한 제한 실행의 생성·상태·재개·취소 | 설치와 인증이 된 CLI. 임의의 실행 중 세션에 붙는 기능은 아닙니다. |
| Claude Desktop | 이 어댑터에는 외부 세션 제어 미구현 | Desktop 설치만으로 제어 경로가 생기지 않습니다. |

`provider_route`는 요청한 동작의 경로를 제안하거나 누락된 전제 조건을 구체적으로 보고합니다. 동작은 `create`, `discover`, `connect`, `status`, `message`, `resume`, `cancel`, `peer`입니다. 경로 응답만으로 세션 생성, 정책 변경, 과업 제출이 이루어진 것은 아닙니다.

## 모델과 실행 설정을 연결한 뒤 제출하기

`provider_models`를 읽고 revision이 있는 `provider_plan`을 저장한 뒤, 정확한 `plan_id`와 `plan_revision`을 `provider_run`에 전달합니다. 과업 본문과 `assignment_revision`도 계획과 같아야 합니다. 모델 목록의 출처, 강제 조건, 미확인 기본값은 [모델 계획 참조](model-planning-mcp.md)에서 설명합니다.

모델 상속은 `selection.model="inherit"`입니다. 실행 설정 상속은 계획의 `execution.mode="inherit"`, 제출 시의 `mode="inherit"`입니다. 서로 다른 설정입니다. 실행 상속은 바로 생성하는 주체의 현재 네이티브 정책을 보존합니다. 함께 제공하는 명시적 설정은 동등성 확인 조건이므로 권한을 조용히 넓히거나 줄일 수 없습니다. provider 사이의 변환은 관측된 파일시스템·네트워크·도구·훅 제한을 보존해야 하며 표현할 수 없는 동등성은 요청을 막습니다. Claude의 `dontAsk`를 `bypassPermissions`로 바꾸면 안 됩니다.

명시적으로 승인된 `target-native`는 목적지에 이미 있는 기본값, 훅, 도구 규칙을 사용합니다. 출발지 자격 증명을 복사하거나 목적지 설정을 고치지 않습니다. 충돌하는 덮어쓰기 요청은 거부되며 상속 실패를 이유로 모드를 몰래 바꿀 수 없습니다. 목적지 설정을 선택했다고 모델이 정해지거나 권한 동등성, 앱 소속, 미완료 작업 인수가 확인되는 것은 아닙니다.

## 접수 결과는 감독의 시작으로 읽기

계획을 사용하는 호출은 다음 형태입니다. 꺾쇠괄호 값은 실제 관측값이나 반환된 참조로 교체해야 합니다.

```json
{
  "provider": "codex",
  "worktree": "<승인된 워크트리 절대 경로>",
  "assignment": "<계획에 기록한 API 조사 과업 원문>",
  "assignment_revision": 1,
  "mode": "inherit",
  "plan_id": "<반환된 계획 ID>",
  "plan_revision": 1,
  "key": "saved-filter-api-run-1"
}
```

`provider_run`은 영속적인 `run_id`를 신속하게 반환합니다. 실행 감독을 기록했다는 뜻이며 과업 완료를 뜻하지 않습니다. 목적지에서 수정하기 전에는 설치, 네이티브 활성화, 실제 정책, 실제 선택 모델, claim, 필요한 도구를 각각 확인해야 합니다. 생성 후 조회한 모델이나 정책이 요청과 다르면 생성에 성공한 것처럼 과업을 제출해서는 안 됩니다.

일반 provider 작업에는 전체 작업 수명을 제한하는 마감 시간이 없습니다. 요청·연결·쓰기 제한 시간은 해당 전송 동작만 제한합니다. 진행과 완료는 영속적인 상태·결과 메시지로 전달됩니다. `provider_status(run_id)`는 보고된 이벤트나 전송 실패 이후의 진단에 사용하며 완료를 기다리는 반복 폴링으로 쓰지 않습니다.

## Claude 결과는 정해진 우선순위로 해석하기

Claude의 `ResultMessage`는 결과를 담는 형식이지 성공 판정 자체가 아닙니다. 어댑터는 다음 순서로 해석합니다.

1. 중단 또는 취소 사유가 있으면 `cancelled`입니다.
2. 그렇지 않고 `deferred_tool_use`가 있으면 과거 `permission_denials`가 함께 있어도 `waiting`입니다.
3. 그렇지 않고 `is_error` 또는 권한 거부가 있으면 `failed`입니다.
4. 나머지는 `completed`입니다.

대기 결과에는 `approval_pending`이 포함되며 취소가 승인 대기보다 우선합니다. SDK 어댑터를 수정할 때 이 순서를 지켜야 합니다. 권한 거부가 있다는 이유만으로 실패 처리하면 현재 승인 대기를 잘못 종료하고, 모든 결과를 성공으로 처리하면 실제 실패를 놓칩니다.

완료하려면 인증된 결과가 원래 참여자에게 도달하고, 전체 본문을 읽고 확인하며, 소유자가 작업 결과를 기록해야 합니다. API 조사가 끝났다는 보고만으로 전체 필터 문제가 해결된 것은 아닙니다. 결과 통합의 기준은 원래 수락 조건입니다.

## 취소, 복구, 앱에서 생성한 작업

`provider_cancel(run_id)`는 소유 실행의 비공개 이벤트 채널로 취소를 요청합니다. 실제 종료는 종결 메시지로 확인합니다. 접수만으로 프로세스가 멈췄다고 볼 수 없으며 임의 PID에 신호를 보내는 기능도 아닙니다.

`provider_recover(run_id, key)`는 네이티브 프로세스와 연결의 종료가 확인된 뒤 발행자의 기존 실행을 복원합니다. 원래 실행을 유지하며 목표를 다시 실행하거나 다른 주체의 실행 중 세션을 재개하지 않습니다. 접수 결과가 불확실하면 같은 키와 요청을 유지해 중복 실행을 피합니다. 다른 루트로 미완료 작업의 소유권을 옮기는 경우에는 [수신자 주도의 이어가기](provider-continuity.md)를 사용합니다.

앱에서 생성하는 루트는 별도 경로입니다. 사용자가 앱 프로젝트에 속한 작업을 요청했다면 실제 `create_thread` 또는 `send_message_to_thread` 전달, 그 완료, 일치하는 네이티브 턴을 함께 확인합니다. 알려진 컨텍스트 종류 `plugins.recommendations`, `agents_md.instructions`, `environments.environment_context`가 전달에 동반될 수 있습니다. 알 수 없는 컨텍스트, 턴 불일치, 완료 누락, 충돌하는 사람의 입력이 있으면 대조가 거부됩니다. 이러한 전달로 네이티브 턴이 활성화되어도 새 사용자 프롬프트 receipt나 추가 승인이 생기지는 않습니다. 로컬 `app_project` 진단과 네이티브 실행 메타데이터는 따로 판단해야 합니다. [에이전트 역할](agents-reference.md)을 참고하세요.

## 구현과 회귀 검사

경로 목록은 [src/neurath/providers/catalog.py](../../../src/neurath/providers/catalog.py), 정책 변환은 [src/neurath/runtime/provider_policy.py](../../../src/neurath/runtime/provider_policy.py), [src/neurath/providers/permission_inheritance.py](../../../src/neurath/providers/permission_inheritance.py)에 있습니다. 실행과 감독은 [src/neurath/providers/execution.py](../../../src/neurath/providers/execution.py), `execution_claude.py`, `jobs.py`, `supervision.py`, `job_recovery.py`에서 다룹니다.

관련 검사는 [tests/test_provider_task_run.py](../../../tests/test_provider_task_run.py), [tests/test_provider_policy_bridge.py](../../../tests/test_provider_policy_bridge.py), [tests/test_target_native_policy.py](../../../tests/test_target_native_policy.py), [tests/test_provider_jobs.py](../../../tests/test_provider_jobs.py), [tests/test_provider_reply_route.py](../../../tests/test_provider_reply_route.py)입니다. 소스와 어댑터 검사는 각각의 계약을 확인합니다. 실제 설치를 검증할 때는 네이티브 활성화, 권한, 결과, 앱 관측을 각각 보고해야 합니다.
## 명명 도구 입력 참조

아래는 현재 명명 도구의 입력 계약입니다. 중첩 필드의 필수 조건은 상위 객체나 배열 항목을 제공했을 때 적용됩니다. 스키마 통과는 첫 검사일 뿐이며 네이티브 신원, 소유권, 출처, revision, 각 동작의 전제 조건도 적용됩니다. `_neurath_binding`은 호스트가 제공하므로 임의로 만들지 않습니다.

모든 응답에는 `ok`, `operation`이 있습니다. 성공 호출에는 표준 `result`, 실패에는 `error.code`, `error.message`, `error.state`, `error.retryable`, `error.next_action`이 포함됩니다. `ok`는 해당 동작의 성공만 뜻하며 사용자 목표 달성을 뜻하지 않습니다. 후속 호출에는 반환된 ID와 revision을 유지합니다.

### `provider_capabilities`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `provider` | 필수 | 문자열: `"codex"`, `"claude-code"` |

### `provider_route`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `provider` | 필수 | 문자열: `"codex"`, `"claude-code"` |
| `operation` | 필수 | 문자열: `"create"`, `"discover"`, `"connect"`, `"status"`, `"message"`, `"resume"`, `"cancel"`, `"peer"` |
| `native_session` | 선택; 기본 `""` | 문자열; 0–256 자 |
| `model` | 선택; 기본 `""` | 문자열; 0–256 자 |
| `project_id` | 선택; 기본 `""` | 문자열; 0–256 자 |
| `message_id` | 선택; 기본 `""` | 문자열; 0–256 자 |
| `worktree` | 선택; 기본 `""` | 문자열; 0–4096 자 |
| `assignment` | 선택; 기본 `""` | 문자열; 0–16000 자 |
| `plan_id` | 선택; 기본 `""` | 문자열; 0–128 자 |
| `plan_revision` | 선택; 기본 `1` | 정수; 1–2147483647 |
| `assignment_revision` | 선택; 기본 `1` | 정수; 1–2147483647 |
| `reasoning_effort` | 선택; 기본 `""` | 문자열; 0–100 자 |
| `requested` | 선택; 기본 `{}` | 객체; 정의된 필드만 허용 |
| `requested.sandbox` | 선택 | 문자열: `"read-only"`, `"workspace-write"`, `"danger-full-access"`, `"native"` |
| `requested.permission_mode` | 선택 | 문자열: `"plan"`, `"dontAsk"`, `"default"`, `"acceptEdits"`, `"bypassPermissions"`, `"auto"` |
| `requested.approval_policy` | 선택 | 문자열: `"never"`, `"on-request"`, `"untrusted"` |
| `requested.approvals_reviewer` | 선택 | 문자열: `"user"`, `"auto_review"` |
| `requested.collaboration_mode` | 선택 | 문자열: `"default"`, `"plan"` |

### `provider_run`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `worktree` | 필수 | 문자열; 1–4096 자 |
| `assignment` | 필수 | 문자열; 1–16000 자 |
| `model` | 선택; 기본 `""` | 문자열; 0–256 자 |
| `project_id` | 선택; 기본 `""` | 문자열; 0–256 자 |
| `provider` | 선택; 기본 `"codex"` | 문자열: `"codex"`, `"claude-code"` |
| `mode` | 선택; 기본 `"inherit"` | 문자열: `"inherit"`, `"target-native"`, `"read-only"`, `"workspace-write"`, `"danger-full-access"`, `"native"` |
| `permission_mode` | 선택; 기본 `""` | 문자열: `""`, `"plan"`, `"dontAsk"`, `"default"`, `"acceptEdits"`, `"bypassPermissions"`, `"auto"` |
| `approval_policy` | 선택; 기본 `""` | 문자열: `""`, `"never"`, `"on-request"`, `"untrusted"` |
| `approvals_reviewer` | 선택; 기본 `""` | 문자열: `""`, `"user"`, `"auto_review"` |
| `collaboration_mode` | 선택; 기본 `""` | 문자열: `""`, `"default"`, `"plan"` |
| `plan_id` | 선택; 기본 `""` | 문자열; 0–128 자 |
| `plan_revision` | 선택; 기본 `1` | 정수; 1–2147483647 |
| `assignment_revision` | 선택; 기본 `1` | 정수; 1–2147483647 |
| `reasoning_effort` | 선택; 기본 `""` | 문자열; 0–100 자 |
| `key` | 선택; 기본 `""` | 문자열; 0–512 자 |

### `provider_status`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `run_id` | 필수 | 문자열; 1–128 자 |

### `provider_cancel`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `run_id` | 필수 | 문자열; 1–128 자 |

### `provider_recover`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `run_id` | 필수 | 문자열; 1–128 자 |
| `key` | 필수 | 문자열; 1–512 자 |
