<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/skills-reference.md)

# 원하는 결과에 맞는 절차 선택

스킬은 특정 종류의 작업을 에이전트가 수행하는 절차입니다. 사용자가 원하는 결과와 제약에 맞춰 선택하며, 공개 이름은 개발자나 명시적 요청에서 사용할 안정적인 이름입니다. 설치되는 공개 스킬은 31개입니다. 29개에는 단계 계약이 있고 `explain-code`, `graphify`는 단계 계약이 없는 보조 스킬입니다.

## 공개 이름과 내부 식별자

사용자 안내에는 공개 이름을 씁니다. 소스 디렉터리와 내부 계약에는 아래 식별자를 유지합니다. 설치 접두사는 공개 이름에 붙습니다. 예를 들어 `neurath-`를 설정하면 `debug`는 `neurath-debug`로 제공되며 내부 식별자는 `investigate`입니다.

| 수행할 작업 | 공개 스킬 | 내부 식별자 |
| --- | --- | --- |
| 구현 전 요구사항 검토 | `review-spec` | `audit-spec` |
| 배포된 UI·API·저장 결과 검증 | `qa` | `automate-qa` |
| 명시적으로 요청한 여러 이슈 조정 | `autopilot` | `autopilot` |
| 되돌릴 수 있는 작업 중간 저장 | `checkpoint` | `checkpoint` |
| 승인되고 검증된 변경 커밋 | `commit` | `commit` |
| 승인된 push와 PR 생성 | `create-pr` | `create-pr` |
| 승인된 작업 항목 생성 | `create-issue` | `create-ticket` |
| 격리된 이슈 작업 공간 준비 | `create-worktree` | `create-worktree` |
| 의존성 보안·라이선스·최신성·드리프트 검사 | `audit-deps` | `dependency-audit` |
| 실패 시나리오로 하네스 집행 검증 | `test-harness` | `evaluate-harness` |
| 소스와 테스트로 현재 동작 설명 | `explain-code` | `explain-code` |
| 디자인 대안 탐색과 정확한 캔버스 선택 | `design-ui` | `explore-ui` |
| 승인된 저장·전송·그래프 갱신·소유권 해제 | `finish-session` | `finish-session` |
| 코드·문서 관계 그래프 탐색 | `graphify` | `graphify` |
| 승인된 정확한 디자인 노드 구현 | `implement-ui` | `implement-ui` |
| 결함 재현과 원인 분리 | `debug` | `investigate` |
| PR의 변화 관찰 | `watch-pr` | `monitor-pr` |
| 기능을 유지하며 주입 지침 축소 | `optimize-harness` | `optimize-harness` |
| 제품 결정 정리와 문서·이슈 분해 | `plan` | `plan-issues` |
| 현재 PR head에 검증된 검토 게시 | `review-pr` | `pr-review` |
| 승인된 이슈 한 건 구현 | `implement-issue` | `process-ticket` |
| 반복되는 비공개 지식을 승인된 규칙으로 반영 | `memory-to-rules` | `promote-memory` |
| 변경에서 근거 있는 결함 발견 | `review-code` | `review-code` |
| 승인 디자인과 실행 화면 비교 | `review-ui` | `review-ui` |
| 저장소 토큰·컴포넌트와 캔버스 연결 | `sync-design` | `sync-design` |
| 개발자 문서 갱신 | `dev-docs` | `sync-dev-docs` |
| 문서 작업 범위 분류 | `sync-docs` | `sync-docs` |
| 승인되고 구현된 사용자 동작 문서화 | `user-docs` | `sync-user-docs` |
| 리뷰 의견 판단과 응답 | `pr-feedback` | `triage-comments` |
| 통제된 의존성 갱신과 검사 | `update-deps` | `update-dependencies` |
| 이슈·프로젝트 메타데이터 갱신 | `update-status` | `update-project-status` |

과거 독립 이름인 `create-package`, `local-dev`, `onboard`, `refactor-code`, `impact-analysis`, `improve-coverage`, `property-test`는 추가 공개 스킬이 아닙니다. 예전 이름이 설치되어 있다고 가정하지 말고 현재 수행할 작업에 맞는 절차를 선택합니다.

## 입력과 완료 결과 연결

구현 작업에는 승인된 이슈·명세, 현재 checkout, 관련 소스, 실제 프로젝트 검사를 확보합니다. 요청한 동작과 제약은 측정 가능한 작업 정의에 유지합니다. 코드 검토는 정확한 변경을 읽고 소스 근거가 있는 결함을 보고합니다. 디자인 작업은 승인된 캔버스나 정확한 노드 참조를 보존해야 구현·비교 대상을 고정할 수 있습니다.

전달 절차에도 승인된 범위가 필요합니다. 되돌릴 수 있는 중간 저장, 로컬 커밋, 브랜치 push, PR 게시, 세션 종료는 각각 다른 결과입니다. `create-pr`이나 `finish-session`을 선택했다고 사용자가 부여하지 않은 권한이 생기지 않습니다. 의존성 작업은 해당 프로젝트의 실제 환경과 검사를 사용합니다. QA는 요청에 관련된 배포 화면, API 동작, 저장 결과를 확인합니다.

일반 작업에서는 작업 원장이 있으면 그것이 완료 판단의 기준입니다. 네이티브 편집과 검사는 일반 호스트 도구로 실행합니다. 화면의 TODO는 표시용 사본입니다. 스킬을 사용한다고 모든 작업에 기준별 추가 수락 보고, material batch, 독립 작업 검토를 의무적으로 더하지 않습니다.

## 명시적으로 필요한 단계 계약 실행

작업에서 단계 진행이나 독립 평가를 명시적으로 요구하면 해당 계약을 따릅니다.

1. `phase_start`로 시작하고 반환된 workflow 식별자와 revision을 보존합니다.
2. 중단되었거나 최신 상태가 불확실하면 변경 전에 `phase_current`로 현재 지침·요구·상태를 읽습니다.
3. `phase_evidence_prepare`로 필수 label과 현재 revision을 검사하고 불변 근거 참조를 등록합니다. 임의 artifact 문자열은 계약 근거가 아닙니다.
4. 실제로 반환된 근거를 `phase_complete`에 제출합니다. 통과했다고 서술하거나 지침을 읽는 것만으로 단계가 진행되지는 않습니다.
5. 별도 종료가 필요한 계약은 `phase_finalize`를 사용합니다. 마지막 운영 단계가 `terminal_state`와 함께 원자적으로 완료되었다면 두 번 종료하지 않습니다.

적응형 workflow는 초기화 전에 실제 독립 검토자가 필요합니다. 검토자는 목표·의도·소스·workflow revision에 연결된 정확한 후보와 근거를 읽고, 소유자는 `evaluation_consume`으로 인증된 결과를 소비합니다. 내용·소유자·workflow 상태가 바뀌면 기존 근거를 재사용할 수 없습니다. provider 동료의 보고만으로 네이티브 직접 자식의 검토 권한을 만들 수 없습니다.

현재 공개 이름은 `phase_start`, `phase_complete`, `phase_finalize`입니다. 예전 `workflow_start`, `workflow_advance`, `workflow_finalize` 호출은 저장된 호출의 호환 경로로 유지하지만 새 호출자에게 공개하지 않습니다. 이 호환 경로를 일반적인 셸 우회 통로로 사용하지 않습니다.

조사 범위는 원래 완료 조건을 따른다. 특히 `test-harness`는 자체 절차를 끝내기 위해 무제한 inventory나 평가 generation을 요구하지 않는다. 시간과 토큰 한도는 유용한 다음 행동을 고르는 기준이며 사용자 목표를 낮추지 않는다. [목표 환기](design-principles.md)는 추가 단계나 보고서 없이 그 판단을 돕는다. 다른 스킬의 적용 가능한 반복 계약은 유지한다.

## 스킬 원본 변경

설치된 `.agents/skills`와 `.neurath/rules`는 생성 결과입니다. `src/neurath/_assets`의 원본을 변경하고 공개·내부 이름 매핑과 두 호스트의 설치 결과를 보존합니다. 접두사는 설치 경로와 참조 전체에 일관되게 적용해야 하며, 이름이 충돌하면 기존 사용자 스킬을 보존하고 충돌을 반환해야 합니다.

실행 자산을 변경한 뒤에는 manifest 생성, 필수 검사, 빌드, 자기 설치 업데이트를 각각 수행합니다.

```sh
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv run --locked python -m build
./setup --self
```

이 명령은 기여자의 실행 참조입니다. 설명만 바꾼 문서 수정 때문에 자기 설치를 수행할 필요는 없습니다.

## 소스와 계약 검사

[스킬 이름](../../../src/neurath/skill_names.py)은 공개 이름 매핑을 정의합니다. [카탈로그](../../../src/neurath/_assets/scripts/skill_harness/harness_catalog.py), [단계 실행기](../../../src/neurath/_assets/scripts/skill_harness/phase_runner.py), [스킬 상태 계약](../../../src/neurath/_assets/scripts/agent_harness/skill_state_contract.py)은 계약 탐색과 실행을 구현합니다. [단계 실행기 테스트](../../../tests/runtime/skill_harness/test_phase_runner.py), [MCP 지침 테스트](../../../tests/test_mcp_guidance.py), [설치 테스트](../../../tests/test_installer.py)는 관련 소스와 설치 동작을 검사합니다.

완료 판단은 [작업·TODO 계약](task-todo-contract.md), 독립 역할은 [협업 계약](collaboration-contract.md)을 참고합니다. [사용자 스킬 안내](../usage/skills.md)는 결과를 자연어로 요청하는 방법을 설명합니다.
