<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/model-planning-mcp.md)

# 관찰한 모델 선택을 한 작업에 연결하기

모델 계획은 승인된 독립 작업에 어떤 관찰된 모델이 충분한지 기록하고 실제 provider 실행에 연결합니다. 사용자 제약을 보존하며 할당·정책·실제 생성 모델이 달라졌는데 예전 결정을 조용히 재사용하는 것을 막습니다. 계획 자체가 세션 생성 권한을 부여하지는 않습니다.

## 독립 실행이 필요한지 판단

현재 작업에서 나눌 수 있는 제한된 일은 지원되는 구조 안에서 네이티브 말단 자식을 사용합니다. 독립 수명, 다른 provider, 필요한 격리가 있으면 소유한 provider 세션을 선택할 수 있으며 계획 전에 이유를 기록합니다. 동료 메시지·모델 추천·사용 가능한 카탈로그만으로 생성을 승인받을 수 없습니다.

모호함, 변경 범위, 추론 깊이, 실패 영향, 도구·모달리티·문맥 요구, 검증 수단의 강도로 역할을 평가합니다. `difficulty`는 `routine`, `standard`, `complex`, `confidence`는 `low`, `medium`, `high`입니다. 근거를 갖춘 판단이며 고정 점수나 토큰 수로 통과시키는 문턱이 아닙니다.

| 할당 예시 | 기록할 판단 | 선택에 미치는 영향 |
| --- | --- | --- |
| 명시된 필드 목록과 테스트를 기계적으로 비교 | 좁은 범위·적은 모호함·직접 검사 | 제약을 만족하는 관찰된 가장 작은 모델 |
| 소유권·복구에 걸친 생명주기 경쟁 해결 | 여러 상태 전이·불확실한 효과·실패 영향 | 필요한 능력을 뒷받침하는 근거가 있는 모델 |
| 사용자가 provider·모델을 지정 | 선호 순위와 무관한 고정 제약 | 정확한 모델을 사용하거나 이용 불가 사유 설명 |
| 비용·지연 상한을 명시 | 제한된 차원의 관찰 값 필요 | 알 수 없는 값으로 준수를 입증할 수 없음 |

고정 모델 순위나 내장 가격표를 기준으로 삼지 않습니다. 능력·비용·지연을 모르면 미확인으로 남깁니다. 계획이 사용량 구매, 조용한 provider 대체, 새 데이터 전송 대상의 승인을 뜻하지 않습니다.

## 모델 목록 관찰과 재사용

`provider_models`의 필수 값은 `provider`(`codex` 또는 `claude-code`)입니다. `worktree`는 선택적이며 `refresh` 기본값은 `false`입니다.

```json
{"provider":"codex","worktree":"/absolute/path/to/authorized-worktree","refresh":false}
```

결과에는 목록 식별자, 모델, 출처, 관찰 revision이 남습니다. 같은 네이티브 발행자·provider 세션에서는 턴과 worktree가 바뀌어도 재사용합니다. 새 할당에는 새 계획이 필요할 수 있지만 카탈로그를 다시 조회할 필요는 없습니다. 사용자가 명시적으로 새로고침을 요청했거나 관찰을 무효화하는 구체적인 근거가 있을 때 갱신합니다.

Codex는 네이티브 어댑터를 사용합니다. Claude는 모델 query 없이 짧은 공식 SDK 메타데이터 연결을 수행하며 관련 설정을 유지하고 부모 식별자 환경을 제거합니다. 목록을 받았다는 사실만으로 인증·실제 추론·적용된 기본 모델을 증명하지 않습니다.

## 정확한 계획 준비

`provider_plan`에는 provider·대상 worktree·할당·목록 ID·실행 객체·선택·난이도·확신도·근거 설명·안정적인 키가 필요합니다. `evidence`, `replan_triggers`도 비어 있지 않게 제공합니다. 기본 빈 배열은 도메인 계약을 만족하지 않습니다. 목록별 최대 32개 항목, 할당 최대 16,000자이며 revision은 양의 정수입니다.

아래 입력은 예시 경로·목록·모델을 실제 승인된 대상과 관찰 값으로 바꾸면 구조에 맞습니다. `evidence`에 적은 관찰도 실제로 수행했어야 합니다.

```json
{
  "provider":"codex",
  "worktree":"/absolute/path/to/authorized-worktree",
  "assignment":"문서의 응답 필드를 현재 API 테스트와 비교하고 편집 없이 불일치를 보고합니다.",
  "assignment_revision":1,
  "inventory_id":"RETURNED_INVENTORY_ID",
  "execution":{"mode":"inherit"},
  "selection":{"model":"OBSERVED_MODEL_ID"},
  "constraints":{"allowed_providers":["codex"]},
  "difficulty":"routine",
  "evidence":["비교할 필드 범위가 정해져 있고 직접 확인할 테스트가 있습니다."],
  "confidence":"high",
  "rationale":"관찰한 모델이 제한된 비교에 필요한 도구와 문맥을 지원합니다.",
  "rejected_alternatives":["이 할당에서 더 큰 모델이 유리하다는 근거가 없습니다."],
  "replan_triggers":["할당이 구현으로 확대되거나 관찰한 모델을 사용할 수 없게 되는 경우"],
  "key":"response-contract-plan-1"
}
```

실행 객체에는 실제 경로가 지원하는 `mode`, 승인 관련 필드, 협업 모드, Claude 권한 모드, 선택적 프로젝트 ID를 담을 수 있습니다. 선택 객체는 `model`과 선택적 `reasoning`을 받습니다. 제약에는 `explicit_model`, `allowed_providers`, `required_capabilities`, `min_context_tokens`, `max_input_price_per_million`, `max_latency_ms`를 지정할 수 있습니다. 추론 설정은 관찰한 모델이 지원해야 하며 생략했다고 임의 값을 만들면 안 됩니다.

저장 결과는 할당 digest·revision, 발행자·provider, 적용 정책 digest·대응 revision, 모델 목록 관찰, 선택·이유·제약·제외 대안을 연결합니다. `plan_id`, `revision`, 선택 상태, `resolved_model_id`를 반환하며 필요하면 기본값 출처도 보존합니다. `provider_plan_read`는 지정한 `plan_id`, `plan_revision`을 읽습니다.

계획을 수정할 때는 `plan_id`, 실제 최신 `expected_revision`, 새 요청 키를 전달합니다. 같은 키로 입력을 바꾸면 충돌합니다. 과거 결정을 덮어쓰지 않고 revision별 출처를 유지합니다.

## 모델 상속과 권한 상속 구분

`execution.mode="inherit"`, `provider_run.mode="inherit"`는 실행 정책에 관한 값이며 모델을 선택하지 않습니다. 현재 모델 상속 표기는 `selection.model="inherit"`입니다. 공개 스키마에는 `selection.mode`가 없습니다.

모델 상속은 대상 provider에서 관찰한 설정 기본값을 뜻합니다. 다른 provider 부모의 모델이나 카탈로그 추천값이 아닙니다. 기본값이 확정되면 `resolved_model_id`와 함께 `default_source`, `default_observation_revision`이 필요합니다. 기본 모델을 알 수 없다면 입증이 필요한 모델·능력·문맥·가격·지연의 강제 제약과 추론 설정이 없는 경우에만 `preparation-only`가 가능합니다. 실제 할당 검증에는 준비된 계획이 필요합니다.

준비 과정은 이미 승인된 같은 세션에서 기본값을 관찰하고 할당 전에 새 계획 revision을 만들 수 있습니다. 별도 탐색 세션을 만들지 않습니다. 유료 호출 제약을 만족하며 필요한 관찰을 할 수 없다면 부족한 조건을 남깁니다. 권한 상속은 [transport 정책 계약](provider-transports.md)의 별도 제한을 따릅니다. 어느 상속도 모든 provider 고유 설정이 복제되었다는 뜻은 아닙니다.

## Target-native 실행을 명시적으로 선택하기

사용자가 제공자마다 고유 설정을 유지하도록 요청하면 `provider_plan`의 `execution.mode="target-native"`와 `provider_run`의 `mode="target-native"`를 사용합니다. 상속 예제와 마찬가지로 계획 리비전과 배정 내용이 일치해야 합니다. 모델 선택은 별개입니다. 관측한 모델을 지정하거나 `selection.model="inherit"`로 대상의 관측된 기본 모델을 선택할 수 있습니다.

대상의 실제 기본값을 관측할 수 있고 지원하는지 먼저 확인합니다. 이 값과 충돌하는 승인·검토자·협업·permission 설정을 추가하거나 원본 설정을 복사하지 않습니다. `inherit`가 실패했다는 이유만으로 전략을 바꾸지도 않습니다. 정책 경계는 [제공자 실행](provider-transports.md), 새 배정 대신 기존 작업을 이어받는 방법은 [작업 승계](provider-continuity.md)에 설명합니다.

## 접수와 실제 모델 확인

`provider_run`에는 정확한 계획 ID·반환 revision, 바뀌지 않은 할당·할당 revision, 안정적인 키를 전달합니다. 앞 계획의 연결 예시는 다음과 같습니다.

```json
{
  "provider":"codex",
  "worktree":"/absolute/path/to/authorized-worktree",
  "assignment":"문서의 응답 필드를 현재 API 테스트와 비교하고 편집 없이 불일치를 보고합니다.",
  "assignment_revision":1,
  "model":"OBSERVED_MODEL_ID",
  "mode":"inherit",
  "plan_id":"RETURNED_PLAN_ID",
  "plan_revision":1,
  "key":"response-contract-run-1"
}
```

새 계획 예시 밖에서는 revision이 `1`이라고 가정하지 말고 실제 반환값을 사용합니다. 검증은 지속 접수 전에 이루어집니다. 네이티브 생성 후 본 작업 전달 전에 실제 모델을 확인합니다. 값이 없거나 다르면 작업을 막고 진단용 네이티브 식별자를 보존합니다. 별칭이 같다는 판단에는 공식적인 대응 근거가 필요하며 이름의 유사성으로 인정할 수 없습니다.

공통 도구 결과에는 `ok`, `operation`이 있고 성공 시 `result`, 오류 시 `code`, `message`, `state`, `retryable`, `next_action`을 담은 오류 객체가 있습니다. 구조화된 결과를 읽습니다. 계획 유효성이나 실행 접수가 요청한 효과의 완료를 증명하지는 않습니다.

## 중요한 변화가 있을 때 재계획

| 상황 | 필요한 조치 |
| --- | --- |
| 할당·대상·provider·제약·적용 정책 변경 | 현재 문맥에 연결한 새 계획 revision |
| 정책 대응 revision·관찰된 기본값 변경 | 필요한 관찰을 갱신한 뒤 재계획 |
| 목록을 무효화하는 구체적인 근거 | 현재 목록 관찰과 선택 재검증 |
| 시간 경과·일반 메시지만 발생 | 선택 유지; 시간만으로 만료되지 않음 |
| 생성 응답 불확실 | 다음 시도 전에 기존 요청·키·계획 결과 대조 |
| 다른 모델 필요 | 새 revision과 기존 승인 시도의 결과 조정 |
| 생성 모델 불일치·누락 | 본 작업 차단 후 보존한 네이티브 진단 확인 |

재개와 일반 메시지는 선택을 유지합니다. 턴이 끝났다고 재시작하거나 모델을 바꾸지 않습니다. 불확실한 생성이 두 개의 독립 세션으로 이어지면 안 됩니다. `provider_status`는 관련 이벤트·오류 뒤 진단용이며, 복구는 [provider transport](provider-transports.md)의 기록된 소유 세션을 사용합니다.

## 모델 계획과 이름 있는 도구 검증

[모델 계획](../../../src/neurath/providers/model_planning.py)은 형식화된 관찰, 선택 검증, 불변 revision, 오래된 계획 검사를 구현합니다. [도구 스키마](../../../src/neurath/runtime/task_schema.py), [provider 실행](../../../src/neurath/runtime/provider_execution.py), [MCP 서버](../../../src/neurath/agents/mcp.py)가 이름 있는 인터페이스를 제공합니다. 결정적인 검사는 구조·제약·연결을 확인하며 주관적인 난이도 평가나 최종 작업 품질을 인증하지 않습니다.

[모델 계획 테스트](../../../tests/test_model_planning.py), [provider 작업 테스트](../../../tests/test_provider_jobs.py), [MCP 지침 테스트](../../../tests/test_mcp_guidance.py)는 관련 계약을 검사합니다. 수락 시나리오에는 고정·이용 불가 모델, 제한 속성 미확인, 미지원 추론, 계획 변경, 별칭·불일치 확인, 접수 후 불확실성이 포함됩니다. 설치된 정책·스킬·알림·오류 `next_action`도 이름 있는 도구로 안내해야 합니다. 회상·동료 메시지·뉴스룸·상태 조회는 해당 도구를 사용하며 일반 편집과 검사는 네이티브 호스트 작업입니다.

MCP 이용 불가나 미지원 모드는 명시적인 한계입니다. 일반 작업을 임의 CLI나 `agent(argv)` 통로로 돌릴 권한이 생기지 않습니다. [검증 안내](validation.md)에 따라 소스 검사·설치 지침·실제 호스트의 모델 및 도구 선택 관찰을 구분합니다.
