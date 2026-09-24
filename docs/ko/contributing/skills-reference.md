<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# 사용자 결과에 맞는 절차 선택하기

[English](../../en/contributing/skills-reference.md) · [기여자 시작 안내](index.md)

스킬은 에이전트가 반복해서 사용할 수 있는 작업 절차입니다. 어떤 종류의 일을 어떻게 수행하는지, 단계 계약이 있다면 어떤 근거를 남겨야 하는지 안내합니다. 사용자의 목표를 대체하거나 절차에 적힌 모든 행동을 자동으로 승인하지는 않습니다.

가상의 저장 필터 문제에서는 `debug`로 재현과 원인 분석을 진행하고, 수정 뒤 `review-code`로 코드를 검토하며, `qa`로 화면·API·저장 데이터의 결과를 확인할 수 있습니다. 목적은 여전히 기존 동작을 보존하면서 새로고침 후에도 선택값이 유지되게 하는 것입니다. 스킬의 한 단계를 끝내는 일도 그 결과에 기여할 때 의미가 있습니다.

## 공개 이름을 사용하고 원본 자산 수정하기

설치되는 공개 스킬은 31개입니다. 29개에 단계 계약이 있고 `explain-code`, `graphify`는 단계 계약이 없는 보조 스킬입니다. 공개 이름과 소스 식별자가 연결됩니다. 예를 들어 사용자는 `debug`를 부르지만 소스 디렉터리와 계약의 식별자는 `investigate`입니다. 설치 접두사는 호출 표기만 바꾸며 내부 스킬 식별자나 단계 ID를 바꾸지 않습니다.

수정할 원본은 [src/neurath/_assets/.agents/skills/](../../../src/neurath/_assets/.agents/skills/) 아래 있습니다. 설치된 `.agents/skills`, `.neurath/rules`는 투영 결과입니다. 승인된 구현 변경에서는 원본 자산을 고치고 생성된 manifest를 갱신합니다. 설치, 패키지 실행, 실제 호스트 활성화는 따로 검증해야 합니다. 절차 파일을 고쳤다고 이미 열린 호스트가 새 내용을 읽었다는 뜻은 아닙니다.

아래 목록은 수행할 일을 기준으로 정리했습니다. 실행하기 전에는 선택한 스킬의 현재 전체 지침과 대상 프로젝트의 바인딩을 읽습니다.

| 스킬 | 수행할 일 | 소스 ID | 단계 수 | 종결 상태 |
| --- | --- | --- | --- | --- |
| `review-spec` | 명세와 구현의 일치 여부 검토 | `audit-spec` | 1 | `completed`, `blocked`, `failed` |
| `qa` | 사용자 동작·API·저장 결과 검증 | `automate-qa` | 3 | `qa-complete`, `blocked`, `failed` |
| `autopilot` | 승인된 이슈 작업과 의존성 조정 | `autopilot` | 7 | `merged`, `failed`, `skipped`, `blocked` |
| `checkpoint` | 현재 작업과 다음 행동 보존 | `checkpoint` | 1 | `completed`, `blocked`, `failed` |
| `commit` | 승인된 파일 범위 검토·커밋 | `commit` | 3 | `committed`, `failed`, `blocked` |
| `create-pr` | 승인된 PR 준비·생성 | `create-pr` | 3 | `pr-created`, `blocked`, `failed` |
| `create-issue` | 요구를 실행 가능한 이슈로 정리 | `create-ticket` | 4 | `created`, `blocked`, `failed` |
| `create-worktree` | 승인된 작업의 분리 체크아웃 생성 | `create-worktree` | 1 | `completed`, `blocked`, `failed` |
| `audit-deps` | 의존성 안전성·라이선스·최신성 검토 | `dependency-audit` | 1 | `completed`, `blocked`, `failed` |
| `test-harness` | 명시적 시나리오로 하네스 동작 평가 | `evaluate-harness` | 3 | `evaluated`, `blocked`, `failed` |
| `explain-code` | 관련 코드 경로와 동작 설명 | `explain-code` | — | 보조 |
| `design-ui` | 선택 전 UI 방향 탐색 | `explore-ui` | 4 | `direction-selected`, `needs-more-exploration`, `blocked`, `failed` |
| `finish-session` | 세션 마무리 전 작업 상태 대조 | `finish-session` | 6 | `finished`, `failed`, `blocked` |
| `graphify` | 소스·지식 관계 탐색 | `graphify` | — | 보조 |
| `implement-ui` | 합의한 UI 방향 구현 | `implement-ui` | 1 | `implemented`, `blocked`, `failed` |
| `debug` | 실패 재현과 원인 확인 | `investigate` | 1 | `completed`, `blocked`, `failed` |
| `watch-pr` | 승인된 PR의 주요 변화 추적 | `monitor-pr` | 4 | `mergeable-clean`, `merged`, `failed`, `blocked` |
| `optimize-harness` | 근거에 따라 하네스 실행 개선 | `optimize-harness` | 3 | `optimized`, `blocked`, `failed` |
| `plan` | 이슈 작업 범위·의존성 계획 | `plan-issues` | 8 | `persisted`, `blocked` |
| `review-pr` | PR과 수락 조건 검토 | `pr-review` | 1 | `completed`, `blocked`, `failed` |
| `implement-issue` | 이슈 구현과 검증 수행 | `process-ticket` | 9 | `merged`, `mergeable-clean`, `failed`, `skipped`, `blocked` |
| `memory-to-rules` | 기억에서 검토할 영구 지침 제안 | `promote-memory` | 1 | `completed`, `blocked`, `failed` |
| `review-code` | 변경에서 조치 가능한 결함 검토 | `review-code` | 1 | `completed`, `blocked`, `failed` |
| `review-ui` | 구현된 사용자 화면 검토 | `review-ui` | 2 | `review-ready`, `accepted`, `revision-requested`, `blocked`, `failed` |
| `sync-design` | 구현과 디자인 원본 대조 | `sync-design` | 1 | `synced`, `no-change`, `blocked`, `failed` |
| `dev-docs` | 개발자·기여자 문서 갱신 | `sync-dev-docs` | 1 | `completed`, `blocked`, `failed` |
| `sync-docs` | 문서 동기화 조정 | `sync-docs` | 6 | `synced`, `blocked`, `failed` |
| `user-docs` | 사용자용 사용 문서 갱신 | `sync-user-docs` | 1 | `completed`, `blocked`, `failed` |
| `pr-feedback` | PR 피드백 분류·처리 | `triage-comments` | 1 | `completed`, `blocked`, `failed` |
| `update-deps` | 승인된 의존성 갱신·검증 | `update-dependencies` | 1 | `completed`, `blocked`, `failed` |
| `update-status` | 확인한 진행 내용을 프로젝트 상태에 반영 | `update-project-status` | 1 | `completed`, `blocked`, `failed` |

## 근거가 있을 때만 단계 진행 기록하기

명시적인 단계 계약은 상태를 갖는 절차입니다. `phase_start`는 `workflow_id`, 런타임이 요구하는 공개·소스 스킬 식별자, `run_id`, `north_star` 목표를 연결합니다. `phase_current`는 현재 단계와 revision을 반환합니다. 스킬을 읽거나 단계가 통과했다고 말하는 것만으로 상태가 진행되지는 않습니다.

`phase_evidence_prepare`는 현재 단계와 revision에 맞는 불변 근거 참조를 만듭니다. 근거 label은 선택한 스킬 계약에서 가져옵니다. 메모에서는 에이전트 보고와 소스·실행 관측을 구분합니다. `phase_complete`에는 정확한 expected revision과 근거 참조를 사용합니다. 별도의 종료가 필요하면 `phase_finalize`로 허용된 종결 상태를 기록합니다. 운영 절차의 마지막 단계는 `terminal_state`와 함께 원자적으로 끝날 수 있으므로 두 번 종료하지 않습니다.

필터 문제의 QA 단계에는 실제 브라우저 관측, API·네트워크 결과, 저장 내용 재조회가 필요할 수 있습니다. 새로고침 전 필터가 선택된 스크린샷은 새로 불러온 뒤에도 유지된다는 증거가 아닙니다. 계획에 테스트 이름이 있다는 사실도 실행 결과를 대신하지 못합니다.

계약마다 의미가 다릅니다. 운영 절차는 커밋이나 체크포인트 준비처럼 범위가 정해진 행동을 표현합니다. 의미·적응 평가를 포함하는 절차는 독립 평가와 정확한 후보 연결을 요구할 수 있습니다. 이때는 올바른 평가자 역할과 인증된 보고 소비가 필요하며 임의의 동료가 좋다고 말한 것으로 계약을 만족할 수 없습니다. 소스, 의도, 소유자, 워크플로 revision이 바뀌면 이전 후보 근거가 무효화될 수 있습니다.

## 승인된 범위 안에서 절차 수행하기

절차에는 이슈 생성, push, PR 공개, 정리, 규칙 승격 단계가 들어갈 수 있습니다. 실제로 허용되는지는 현재 사용자 요청과 프로젝트 지침이 결정합니다. 단계의 전제 조건이 없다면 진행 중인 작업을 보존하고 정확히 무엇이 없는지 보고합니다. 단계를 통과시키려고 기본 브랜치, 원격 ref, 검증 명령, 권한 모드, 수락 조건을 임의로 만들어서는 안 됩니다.

`worktree_isolation`은 이슈·루트 워크트리가 구분되고 루트가 깨끗한지 검사한 뒤 claim합니다. 체크아웃을 생성하거나 전환하는 도구가 아닙니다. 정리에는 실제 브랜치·ref 관측과 저장된 소유권·정리 조건이 필요합니다. `memory-to-rules`도 규칙을 수정하지 않고 교훈을 제안할 수 있으며, 승인된 영구 규칙 반영은 별도 저장소 변경입니다.

일반 작업의 완료 기준은 작업 원장입니다. TODO 표시, 체크포인트, 학습된 안내, 독립적으로 받은 검토 의견이 일반 완료 판정에 추가 표를 행사하지 않습니다. 승인된 작업에 명시적 단계·검토 계약을 선택했다면 그 계약은 적용됩니다. 시도 실패, 곁가지 질문, 예산 한도로 원래 필터 요구가 취소되지는 않습니다.

`review-pr`은 저장소에 필요한 `.github/workflows/ai-review.yml` approval 자동화가 존재하고 활성 상태인지 확인한 뒤에만 comment와 exact-head `ai-review` status를 게시합니다. Workflow가 없거나 비활성·조회 불가이면 지원되지 않는 전제 조건으로 실패하며 원격 게시 부작용을 만들지 않습니다. 절차는 status-only 저장소 정책을 추정하거나 승인자를 꾸며내지 않습니다.

## 계약과 실패를 원본에서 확인하기

소스·공개 이름 연결은 [src/neurath/skill_names.py](../../../src/neurath/skill_names.py), 설치 투영은 [src/neurath/install/projection.py](../../../src/neurath/install/projection.py)에 있습니다. 계약은 [src/neurath/_assets/.agents/skills/contracts.json](../../../src/neurath/_assets/.agents/skills/contracts.json)에 모여 있고 각 스킬 디렉터리에 지침과 해당하는 단계 파일이 있습니다. 아래 표의 단계 수와 허용 종결 상태로 절차를 찾을 수 있으며 정확한 label과 근거 패턴은 선택한 계약을 확인해야 합니다.

명명된 단계 도구는 [src/neurath/runtime/workflow_tasks.py](../../../src/neurath/runtime/workflow_tasks.py)에 정의됩니다. 현재 도구 검색에는 `phase_start`, `phase_complete`, `phase_finalize`가 나오며 이전 `workflow_start`, `workflow_advance`, `workflow_finalize`는 저장된 호출과의 호환용입니다. 두 번째 절차로 중복 실행하지 않습니다.

관련 검사는 [tests/runtime/skill_harness/](../../../tests/runtime/skill_harness/), [tests/runtime/agent_harness/test_workflow_terminal_admission.py](../../../tests/runtime/agent_harness/test_workflow_terminal_admission.py)에 있습니다. 선언된 계약과 상태 전환 허용을 검증합니다. 실제 결과를 확인하려면 에이전트의 변경 내용, 관련 프로젝트 검사, 필요한 네이티브·화면 근거도 살펴야 합니다.
## 명명 도구 입력 참조

아래는 현재 명명 도구의 입력 계약입니다. 중첩 필드의 필수 조건은 상위 객체나 배열 항목을 제공했을 때 적용됩니다. 스키마 통과는 첫 검사일 뿐이며 네이티브 신원, 소유권, 출처, revision, 각 동작의 전제 조건도 적용됩니다. `_neurath_binding`은 호스트가 제공하므로 임의로 만들지 않습니다.

모든 응답에는 `ok`, `operation`이 있습니다. 성공 호출에는 표준 `result`, 실패에는 `error.code`, `error.message`, `error.state`, `error.retryable`, `error.next_action`이 포함됩니다. `ok`는 해당 동작의 성공만 뜻하며 사용자 목표 달성을 뜻하지 않습니다. 후속 호출에는 반환된 ID와 revision을 유지합니다.

### `phase_start`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `workflow_id` | 필수 | 문자열; 1–256 자 |
| `key` | 필수 | 문자열; 1–512 자 |
| `skill` | 필수 | 문자열; 1–128 자 |
| `run_id` | 필수 | 문자열; 1–256 자 |
| `north_star` | 필수 | 문자열; 1–16000 자 |

### `phase_current`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `workflow_id` | 필수 | 문자열; 1–256 자 |

### `phase_evidence_prepare`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `workflow_id` | 필수 | 문자열; 1–256 자 |
| `expected_revision` | 필수 | 정수; 0–9007199254740991 |
| `labels` | 선택; 기본 `[]` | 배열; 0–32 항목; 문자열; 1–16000 자 |
| `notes` | 선택; 기본 `[]` | 배열; 0–128 항목 |
| `notes[].label` | 필수 | 문자열; 1–128 자 |
| `notes[].text` | 필수 | 문자열; 1–16000 자 |
| `key` | 필수 | 문자열; 1–512 자 |

### `phase_complete`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `workflow_id` | 필수 | 문자열; 1–256 자 |
| `expected_revision` | 필수 | 정수; 0–9007199254740991 |
| `key` | 필수 | 문자열; 1–512 자 |
| `phase_id` | 필수 | 정수; 0–1000 |
| `status` | 필수 | 문자열: `"completed"`, `"skipped"`, `"failed"`, `"blocked"` |
| `summary` | 필수 | 문자열; 1–16000 자 |
| `reason` | 선택; 기본 `""` | 문자열; 0–16000 자 |
| `terminal_state` | 선택; 기본 `""` | 문자열; 0–128 자 |
| `evidence_refs` | 선택; 기본 `[]` | 배열; 0–32 항목; 문자열; 1–16000 자 |

### `phase_finalize`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `workflow_id` | 필수 | 문자열; 1–256 자 |
| `expected_revision` | 필수 | 정수; 0–9007199254740991 |
| `key` | 필수 | 문자열; 1–512 자 |
| `terminal_state` | 필수 | 문자열; 1–128 자 |

### `delegation_assign`

| 필드 | 필수 여부·기본값 | 형식·제한 |
| --- | --- | --- |
| `workflow_id` | 필수 | 문자열; 1–256 자 |
| `delegation_id` | 필수 | 문자열; 1–128 자 |
| `assignment` | 필수 | 문자열; 1–8192 자 |
| `target` | 필수 | 문자열; 1–512 자 |
| `key` | 필수 | 문자열; 1–512 자 |
