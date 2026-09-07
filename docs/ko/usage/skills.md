# 스킬 목록
<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[사용 안내](index.md) · [기여자 안내](../contributing/index.md)


[English](../../en/usage/skills.md) · **한국어**

에이전트가 요청의 목적, 근거와 권한에 맞춰 스킬을 선택합니다.
원하는 결과를 평소 쓰는 말로 전달하면 되며, 스킬을 직접 호출하거나 이름을 외울 필요는 없습니다.
“이 오류를 재현하고 수정해주세요”는 오류 조사로, “이 변경을 검토해주세요”는 코드 검토로
이어집니다. 아래 목록은 에이전트가 사용할 수 있는 절차를 설명합니다.

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

설치 이름과 호환성의 상세 내용은 [스킬 실행 참조](../contributing/skills-reference.md)에 정리했습니다.
