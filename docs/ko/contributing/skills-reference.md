# 스킬 실행과 호환성 참조

[English](../../en/contributing/skills-reference.md) · **한국어**

<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[기여자 안내](index.md) · [사용자 스킬 목록](../usage/skills.md)

아래 식별자와 명령은 승인된 작업을 수행하는 에이전트의 참조입니다. 사용자가 목표를 전달하면 에이전트가 알맞은 스킬을 선택하고 실행합니다. 호스트의 기본 이름은 `/debug`처럼 접두어가 없으며, 설치 접두어를 지정하면 `/neurath-debug`처럼 바뀝니다.

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
