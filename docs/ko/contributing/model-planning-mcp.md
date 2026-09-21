<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# 관측된 과업과 모델을 연결해 선택하기

[English](../../en/contributing/model-planning-mcp.md) · [기여자 시작 안내](index.md)

모델 계획은 승인된 과업을 의도한 실행 설정으로 수행할 모델을 왜 선택했는지 기록합니다. 새 네이티브 세션이 실제 작업을 하기 전에 선택을 검토할 수 있게 합니다. 모델 품질에 점수를 매기거나 과업에 대한 에이전트의 판단을 대신하는 기능은 아닙니다.

가상의 저장 필터 문제에서도 독립 에이전트에게 API 저장과 응답 확인만 맡길 수도 있고, API 저장과 화면 복원을 함께 추적하도록 맡길 수도 있습니다. 과업에 따라 난이도와 필요한 기능이 달라집니다. 고정된 모델 이름을 고르거나 가장 비싼 모델이 필요하다고 가정하는 대신 실제 질문과 조건을 계획에 설명해야 합니다.

## 목적지에서 관측한 모델 목록으로 시작하기

`provider_models(provider, worktree, refresh)`는 대상 모델 목록과 `inventory_id`를 반환합니다. `provider`는 `codex` 또는 `claude-code`이며 `worktree`는 목적지 범위를, `refresh`는 새 관측 요청을 뜻합니다. 모델 ID, 추론 설정, 기능, 별칭, 기본 모델의 출처, 컨텍스트 크기, 가격, 지연 시간은 확인 가능한 실제 어댑터 관측에서 가져옵니다.

모르는 값은 모르는 상태로 둡니다. 가격을 모른다고 0으로 계산해 상한 조건을 통과시킬 수 없습니다. 다른 모델이 지원하는 추론 모드를 현재 모델도 지원한다고 추정할 수 없습니다. 네이티브 별칭을 실제 모델 ID로 해석하려면 출처와 revision이 있어야 합니다. CLI 설치나 기억 속 모델 목록은 현재 목록을 대신하지 못합니다.

## 선택과 다시 검토할 조건 기록하기

`provider_plan`에는 provider, 워크트리, 정확한 과업, 목록 참조, 실행 설정, 선택, 난이도, 확신도, 근거 설명, 안정적인 키가 필요합니다. `evidence`, `replan_triggers`에도 최소 하나의 항목을 넣어야 합니다. 스키마 기본값은 빈 배열이지만 계획 계약은 비어 있지 않은 값을 요구합니다. `assignment_revision`은 1부터 시작합니다.

| 필드 | 기록하는 판단 |
| --- | --- |
| `selection.model` | 관측된 모델 ID·확인된 별칭 또는 목적지의 관측된 기본 모델을 뜻하는 `"inherit"`. |
| `selection.reasoning` | 명시적으로 선택했다면 해당 모델이 실제 지원하는 추론 설정. |
| `execution` | 실행 모드, 승인 정책·검토 주체, 협업 모드, Claude 권한 모드, 선택적 프로젝트 메타데이터. |
| `difficulty` | 해당 과업에 근거한 `routine`, `standard`, `complex`. |
| `confidence` | 계획에 대한 `low`, `medium`, `high` 확신도. |
| `evidence`, `rationale` | 구체적인 과업·목록 관측과 그 선택을 한 이유. |
| `rejected_alternatives` | 검토한 대안과 선택하지 않은 이유. |
| `replan_triggers` | 범위·기능·정책 변경처럼 계획을 다시 검토할 조건. |
| `constraints` | 반드시 만족할 provider·모델·기능·컨텍스트·가격·지연 조건. |

`constraints`는 `explicit_model`, `allowed_providers`, `required_capabilities`, `min_context_tokens`, `max_input_price_per_million`, `max_latency_ms`를 지원합니다. 강제 조건을 넣었다면 관측으로 확인되어야 합니다. 필요한 기능 누락, 상한을 적용한 가격의 미확인, 지원하지 않는 추론 설정, provider 불일치는 사용할 수 있는 계획 생성을 거부합니다.

상속을 사용하는 호출의 기본 형태는 다음과 같습니다. 자리표시자는 현재 값으로 바꾸고 실행할 때 과업 원문을 그대로 유지합니다.

```json
{
  "provider": "codex",
  "worktree": "<승인된 워크트리 절대 경로>",
  "assignment": "저장 필터의 API 저장과 응답을 조사하고 보존 여부와 응답 근거를 반환한다.",
  "assignment_revision": 1,
  "inventory_id": "<반환된 목록 ID>",
  "execution": {"mode": "inherit"},
  "selection": {"model": "inherit"},
  "difficulty": "standard",
  "evidence": ["<실제 범위와 모델 목록 관측>"],
  "confidence": "medium",
  "rationale": "<관측된 기본 모델이 이 제한된 조사에 맞는 이유>",
  "replan_triggers": ["과업이 진단에서 구현으로 확대됨"],
  "key": "saved-filter-model-plan-1"
}
```

## 두 가지 상속을 구분하기

`selection.model="inherit"`는 대상의 관측된 기본 모델을 선택합니다. `execution.mode="inherit"`는 바로 생성하는 주체의 지원 가능한 네이티브 실행 정책을 보존합니다. `execution.mode="target-native"`는 명시적으로 승인된 목적지 설정을 사용합니다. 어느 것도 다른 세션의 미완료 작업 인수나 앱 프로젝트 소속을 성립시키지 않습니다.

기본 모델을 아직 확인할 수 없다면 강제 조건을 어기지 않는 범위에서 같은 승인된 세션의 `preparation-only`를 허용할 수 있습니다. 강제 조건이 걸린 미확인 기본값이나 지원하지 않는 명시적 추론 설정을 추정으로 통과시킬 수 없습니다. 실제 작업은 모델·기본값의 실제 조회를 기다립니다. 이 경계를 피하려고 관계없는 탐색 세션을 새로 만들지 않습니다.

상속 정책의 계획을 저장하기 전에 실행 단계와 동일한 권한 매핑을 검사합니다. 보존할 수 없는 훅·도구 제어나 충돌하는 요청 모드는 ready 계획을 만들기 전에 거부합니다. 기존 대상 설정 관측은 읽기 전용으로 유지하며 계획 단계에서 모델 작업을 발행하지 않습니다. 명시적인 `target-native`는 별도 선택이며 상속 실패의 자동 우회 수단이 아닙니다.

## 실행과 변경까지 revision 유지하기

반환된 계획에는 ID와 revision, 해석된 모델 또는 준비 전용 상태, 과업·목록 사실·정책·소유자·대상과의 연결이 포함됩니다. `provider_plan_read(plan_id, plan_revision)`로 정확한 버전을 읽습니다. 그 참조를 `provider_run`에 전달하고 모든 계획이 계속 revision 1이라고 가정하지 말고 실제 반환값을 사용합니다.

계획을 변경할 때는 `plan_id`, 현재 `expected_revision`, 새 안정적인 요청 키, 수정된 전체 제안을 제공합니다. 비교 후 갱신 방식으로 오래된 작성자를 거부합니다. 접수된 요청과 같은 키·내용을 반복하면 멱등적으로 같은 결과를 유지하며, 실패한 제안은 요청 키를 소비하지 않습니다.

과업, provider·호스트 대상, 정책, 강제 조건, 선택에 관련된 모델 사실이 바뀌면 계획이 무효화될 수 있습니다. 목록을 새로 읽었다는 사실만으로 만료되지는 않으며 선택에 영향을 주는 사실의 변경이 중요합니다. 명시적 모델 선택은 관계없는 기본 모델이 바뀌었다고 오래된 계획이 될 필요가 없습니다. 세션 생성 시 실제 모델은 해석된 계획 또는 확인된 별칭과 일치해야 합니다. 다르면 실제 과업을 정상 생성된 것처럼 접수해서는 안 됩니다.

## 요구를 약하게 만들지 않고 거부 원인 해결하기

목록이 없다면 목적지를 관측합니다. 강제 조건이 확인되지 않았다면 근거를 얻거나 승인된 요구 판단으로 돌아갑니다. 계획이 오래되었다면 현재 상태를 읽고 현재 과업을 설명하는 새 revision을 만듭니다. 생성된 네이티브 세션의 정책·모델이 불일치하면 그 상태를 유지하고 임의로 성공 처리해 과업을 제출하지 않습니다.

모델을 선택했다고 더 넓은 실행 권한, 추가 세션, 앱 동작, 워크트리 인수가 허용되지는 않습니다. 도구 오류에는 `code`, `message`, `state`, `retryable`, `next_action`이 있습니다. 거부될 때마다 조건을 줄여 재시도하는 대신 실제 전제 조건을 읽어야 합니다.

## 구현과 테스트

[src/neurath/providers/model_inventory.py](../../../src/neurath/providers/model_inventory.py)가 관측을 수집하고 `model_planning.py`가 계획을 검증·저장합니다. 명명 도구는 [src/neurath/runtime/model_tasks.py](../../../src/neurath/runtime/model_tasks.py), 실행과 계획의 연결은 [src/neurath/providers/execution_plan.py](../../../src/neurath/providers/execution_plan.py)에 있습니다.

[tests/test_model_planning.py](../../../tests/test_model_planning.py)는 소유자 차단, 영속 재호출, revision, 오래된 연결, 강제 조건의 미확인 값, 미확인 기본값, 별칭·기본값 출처를 검사합니다. 이는 계획 계약의 검증이며 보편적인 모델 순위를 정하거나 특정 모델이 사용자의 필터 문제를 해결한다고 입증하는 것은 아닙니다.
## 명명 도구 입력 참조

아래는 현재 명명 도구의 입력 계약입니다. 중첩 필드의 필수 조건은 상위 객체나 배열 항목을 제공했을 때 적용됩니다. 스키마 통과는 첫 검사일 뿐이며 네이티브 신원, 소유권, 출처, revision, 각 동작의 전제 조건도 적용됩니다. `_neurath_binding`은 호스트가 제공하므로 임의로 만들지 않습니다.

모든 응답에는 `ok`, `operation`이 있습니다. 성공 호출에는 표준 `result`, 실패에는 `error.code`, `error.message`, `error.state`, `error.retryable`, `error.next_action`이 포함됩니다. `ok`는 해당 동작의 성공만 뜻하며 사용자 목표 달성을 뜻하지 않습니다. 후속 호출에는 반환된 ID와 revision을 유지합니다.

### `provider_models`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `provider` | 필수 | 문자열: `"codex"`, `"claude-code"` |
| `worktree` | 선택; 기본 `""` | 문자열; 0–4096 자 |
| `refresh` | 선택; 기본 `false` | 불리언 |

### `provider_plan`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `provider` | 필수 | 문자열: `"codex"`, `"claude-code"` |
| `worktree` | 필수 | 문자열; 1–4096 자 |
| `assignment` | 필수 | 문자열; 1–16000 자 |
| `assignment_revision` | 선택; 기본 `1` | 정수; 1–2147483647 |
| `inventory_id` | 필수 | 문자열; 1–128 자 |
| `execution` | 필수 | 객체; 정의된 필드만 허용 |
| `execution.mode` | 선택 | 문자열: `"inherit"`, `"target-native"`, `"read-only"`, `"workspace-write"`, `"danger-full-access"`, `"native"` |
| `execution.approval_policy` | 선택 | 문자열: `"never"`, `"on-request"`, `"untrusted"` |
| `execution.approvals_reviewer` | 선택 | 문자열: `"user"`, `"auto_review"` |
| `execution.collaboration_mode` | 선택 | 문자열: `"default"`, `"plan"` |
| `execution.permission_mode` | 선택 | 문자열: `"plan"`, `"dontAsk"`, `"default"`, `"acceptEdits"`, `"bypassPermissions"`, `"auto"` |
| `execution.project_id` | 선택 | 문자열; 1–256 자 |
| `selection` | 필수 | 객체; 정의된 필드만 허용 |
| `selection.model` | 필수 | 문자열; 1–256 자 |
| `selection.reasoning` | 선택 | 문자열; 1–100 자 |
| `constraints` | 선택; 기본 `{}` | 객체; 정의된 필드만 허용 |
| `constraints.explicit_model` | 선택 | 문자열; 1–256 자 |
| `constraints.allowed_providers` | 선택; 기본 `[]` | 배열; 0–32 항목; 문자열; 1–16000 자 |
| `constraints.required_capabilities` | 선택; 기본 `[]` | 배열; 0–32 항목; 문자열; 1–16000 자 |
| `constraints.min_context_tokens` | 선택 | 정수; 0–∞ |
| `constraints.max_input_price_per_million` | 선택 | 숫자; 0–∞ |
| `constraints.max_latency_ms` | 선택 | 숫자; 0–∞ |
| `difficulty` | 필수 | 문자열: `"routine"`, `"standard"`, `"complex"` |
| `evidence` | 선택; 기본 `[]` | 배열; 1–32 항목; 문자열; 1–16000 자 |
| `confidence` | 필수 | 문자열: `"low"`, `"medium"`, `"high"` |
| `rationale` | 필수 | 문자열; 1–16000 자 |
| `rejected_alternatives` | 선택; 기본 `[]` | 배열; 0–32 항목; 문자열; 1–16000 자 |
| `replan_triggers` | 선택; 기본 `[]` | 배열; 1–32 항목; 문자열; 1–16000 자 |
| `key` | 필수 | 문자열; 1–512 자 |
| `plan_id` | 선택; 기본 `""` | 문자열; 0–128 자 |
| `expected_revision` | 선택; 기본 `0` | 정수; 0–2147483647 |

### `provider_plan_read`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `plan_id` | 필수 | 문자열; 1–128 자 |
| `plan_revision` | 선택; 기본 `1` | 정수; 1–2147483647 |
