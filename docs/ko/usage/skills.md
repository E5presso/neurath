# 스킬 목록
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[사용 안내](index.md) · [기여자 안내](../contributing/index.md)


[English](../../en/usage/skills.md) · **한국어**

스킬은 두 호스트에서 기본적으로 접두어 없이 사용합니다. 설치 접두어를 지정했다면
`/neurath-debug`처럼 호출 이름이 바뀝니다. 재현되는 오류는 `/debug`, 새 요구사항은 `/plan`,
변경 검토는 `/review-code`에서 시작할 수 있습니다. 전달할 내용과 결과 확인 방법은
[사용 안내](index.md)에 설명합니다. 역할이 분명한 이름은 유지하고,
불필요하게 길거나 뜻이 모호했던 이름을 정리했습니다.

| 스킬 | 하는 일 |
| --- | --- |
| `plan` | 제품 요구사항을 계획과 이슈 구조로 정리 |
| `review-spec` | 구현 전 스펙의 누락과 모순 검토 |
| `create-issue` | 승인된 작업을 GitHub 이슈로 생성 |
| `implement-issue` | 승인된 이슈 하나를 구현·검증 |
| `autopilot` | 여러 이슈의 자율 실행 조율 |
| `create-worktree` | 이슈 작업용 독립 작업 폴더 생성 |
| `debug` | 오류 재현과 원인 조사 |
| `explain-code` | 현재 소스에 근거해 코드 설명 |
| `review-code` | 변경 코드 검토 |
| `qa` | 실제 클라이언트·API·저장 결과를 연결해 동작 검증 |
| `design-ui` | 구현 전 UI 방향 탐색과 디자인 승인 |
| `sync-design` | 디자인 토큰과 컴포넌트 매핑 동기화 |
| `implement-ui` | 승인된 디자인을 UI로 구현 |
| `review-ui` | 승인된 디자인과 실행 화면 비교 |
| `checkpoint` | 되돌릴 수 있는 작업 중간 저장 |
| `commit` | 검증된 변경 커밋 |
| `create-pr` | 브랜치를 올리고 PR 생성·갱신 |
| `review-pr` | 정확한 PR 버전에 대한 검토 결과 처리 |
| `pr-feedback` | PR 리뷰 의견의 수용·반론 판단과 대응 |
| `watch-pr` | PR 상태 변화 확인 |
| `update-status` | 이슈·프로젝트 상태 갱신 |
| `finish-session` | 세션 검증과 마무리 |
| `sync-docs` | 문서 갱신 범위 분류와 연결 |
| `dev-docs` | 개발자 문서 갱신 |
| `user-docs` | 사용자 문서 갱신 |
| `audit-deps` | 의존성의 보안·라이선스·관리 상태 점검 |
| `update-deps` | 의존성 업데이트와 검증 |
| `test-harness` | 실패 시나리오로 하네스의 실제 강제력 검증 |
| `optimize-harness` | 동작을 유지하며 지침과 프롬프트 정리 |
| `memory-to-rules` | 반복해서 확인한 개인 작업 지식을 프로젝트 규칙으로 반영 |
| `graphify` | 코드·문서 관계를 지식 그래프로 탐색 |

## 바뀐 이름

| 이전 이름 | 현재 이름 |
| --- | --- |
| `audit-spec` | `review-spec` |
| `automate-qa` | `qa` |
| `create-ticket` | `create-issue` |
| `dependency-audit` | `audit-deps` |
| `evaluate-harness` | `test-harness` |
| `explore-ui` | `design-ui` |
| `investigate` | `debug` |
| `monitor-pr` | `watch-pr` |
| `plan-issues` | `plan` |
| `pr-review` | `review-pr` |
| `process-ticket` | `implement-issue` |
| `promote-memory` | `memory-to-rules` |
| `sync-dev-docs` | `dev-docs` |
| `sync-user-docs` | `user-docs` |
| `triage-comments` | `pr-feedback` |
| `update-dependencies` | `update-deps` |
| `update-project-status` | `update-status` |

설치를 갱신하면 이전 설치 경로를 정리합니다. 이름이 겹치는 사용자 스킬과 직접 수정한
관리 파일은 덮어쓰지 않습니다. 진행 중인 작업 기록을 계속 읽을 수 있도록 내부 계약
식별자는 유지합니다. 엔진 명령에는 스킬 본문의 `내장 계약`을 사용하고, 스크립트는
`.neurath/run skill watch-pr <script>`처럼 현재 이름으로 실행할 수 있습니다.

`create-package`, `local-dev`, `onboard`, `refactor-code`, `impact-analysis`,
`improve-coverage`, `property-test`는 독립 스킬에서 제외했습니다. 일반적인 구현·테스트
원칙은 공통 지침에서 다루며 디자인 하네스와 QA 검증 절차는 유지합니다.
