# Implementation tickets and requirement coverage

[Specification](specification.md) · [Architecture](architecture.md) · [Interfaces](interfaces.md) · [Acceptance](acceptance.md)

Tracking: [#153](https://github.com/E5presso/neurath/issues/153).

This is the ticketed implementation plan. Ticket creation and documentation coverage do not establish implemented or host-validated behavior.

| Ticket | Dependencies | Requirement cases | Capability results |
| --- | --- | --- | --- |
| [#137 — [Core] Hook·CLI 요청을 SQLite 기반 stateless 서비스로 처리](https://github.com/E5presso/neurath/issues/137) | — | A85, A86, A87, A88, A89 | — |
| [#140 — [Tasks] 사용자 요구·태스크·TODO와 결과 상태 관리](https://github.com/E5presso/neurath/issues/140) | [#137](https://github.com/E5presso/neurath/issues/137) | A01, A04, A05, A06, A44 | B04 |
| [#141 — [Workflow] 스킬 phase runner와 시도·검증·재개 구현](https://github.com/E5presso/neurath/issues/141) | [#140](https://github.com/E5presso/neurath/issues/140) | A07, A08, A10, A11, A12, A13, A32, A33, A48, A49, A58 | B05, B06, B09 |
| [#142 — [Runtime] 호스트 훅·세션 수명주기·작성 충돌과 중단 처리](https://github.com/E5presso/neurath/issues/142) | [#140](https://github.com/E5presso/neurath/issues/140) | A15, A31, A53, A65, A83 | B03 |
| [#143 — [Memory] Enclave·기억·체크포인트·인계와 압축 후 자동 복원](https://github.com/E5presso/neurath/issues/143) | [#137](https://github.com/E5presso/neurath/issues/137), [#142](https://github.com/E5presso/neurath/issues/142) | A16, A24, A26, A72, A81, A82 | B18, B19 |
| [#144 — [Collaboration] 피어 메시징·작업 위임·provider 실행과 복구](https://github.com/E5presso/neurath/issues/144) | [#140](https://github.com/E5presso/neurath/issues/140), [#142](https://github.com/E5presso/neurath/issues/142) | A17, A18, A19, A22, A47, A69, A73 | B07, B11, B12, B13, B14, B15, B16 |
| [#145 — [Newsroom] 프로젝트 기사·댓글·개정과 활성 피어 알림](https://github.com/E5presso/neurath/issues/145) | [#144](https://github.com/E5presso/neurath/issues/144) | A20, A21, A56 | B17 |
| [#146 — [Monitoring] 요청된 외부 의존 감시·알림·재개 관리](https://github.com/E5presso/neurath/issues/146) | [#140](https://github.com/E5presso/neurath/issues/140), [#142](https://github.com/E5presso/neurath/issues/142), [#144](https://github.com/E5presso/neurath/issues/144) | A37, A54 | B23, B24 |
| [#147 — [Maintenance] 진단·장애 기록·공식 우회·복구 경로](https://github.com/E5presso/neurath/issues/147) | [#137](https://github.com/E5presso/neurath/issues/137), [#142](https://github.com/E5presso/neurath/issues/142) | A36, A61 | B01, B21, B22 |
| [#138 — [Runtime] TODO 기반 종료 판정과 제3자 결과·회고 평가](https://github.com/E5presso/neurath/issues/138) | [#141](https://github.com/E5presso/neurath/issues/141), [#144](https://github.com/E5presso/neurath/issues/144) | A02, A03, A09, A14, A23, A25, A42, A43, A52, A71, A74, A75, A76, A90, A91, A92 | B08, B10, B20 |
| [#148 — [CLI] Typer 기반 19개 업무 명령과 관리 진입점 구현](https://github.com/E5presso/neurath/issues/148) | [#140](https://github.com/E5presso/neurath/issues/140), [#141](https://github.com/E5presso/neurath/issues/141), [#142](https://github.com/E5presso/neurath/issues/142), [#143](https://github.com/E5presso/neurath/issues/143), [#144](https://github.com/E5presso/neurath/issues/144), [#145](https://github.com/E5presso/neurath/issues/145), [#146](https://github.com/E5presso/neurath/issues/146), [#147](https://github.com/E5presso/neurath/issues/147) | A64, A70, A84 | B02 |
| [#149 — [Skills] 14개 기본 스킬과 phase 정의·검증 절차 구현](https://github.com/E5presso/neurath/issues/149) | [#141](https://github.com/E5presso/neurath/issues/141), [#138](https://github.com/E5presso/neurath/issues/138), [#148](https://github.com/E5presso/neurath/issues/148) | A66, A67, A68 | — |
| [#139 — [Skills] Rules를 기본 진입점으로 에이전트의 스킬 선택 연결](https://github.com/E5presso/neurath/issues/139) | [#149](https://github.com/E5presso/neurath/issues/149) | A63, A93 | — |
| [#150 — [Migration] 기존 DB 보존·사용자 단위 이전·무손실 복구](https://github.com/E5presso/neurath/issues/150) | [#137](https://github.com/E5presso/neurath/issues/137), [#140](https://github.com/E5presso/neurath/issues/140), [#141](https://github.com/E5presso/neurath/issues/141), [#143](https://github.com/E5presso/neurath/issues/143), [#144](https://github.com/E5presso/neurath/issues/144), [#145](https://github.com/E5presso/neurath/issues/145), [#138](https://github.com/E5presso/neurath/issues/138) | A34, A50, A51 | — |
| [#151 — [Distribution] CLI·스킬·훅 설치와 릴리스 가이드 자동 생성](https://github.com/E5presso/neurath/issues/151) | [#148](https://github.com/E5presso/neurath/issues/148), [#149](https://github.com/E5presso/neurath/issues/149), [#139](https://github.com/E5presso/neurath/issues/139), [#150](https://github.com/E5presso/neurath/issues/150), [#147](https://github.com/E5presso/neurath/issues/147) | A35, A77, A78, A79, A80 | B25, B26 |
| [#152 — [Delivery] 전체 요구 검증·문서 동기화·세 프로젝트 업데이트와 종료](https://github.com/E5presso/neurath/issues/152) | [#151](https://github.com/E5presso/neurath/issues/151), [#138](https://github.com/E5presso/neurath/issues/138), [#146](https://github.com/E5presso/neurath/issues/146), [#145](https://github.com/E5presso/neurath/issues/145), [#142](https://github.com/E5presso/neurath/issues/142) | A39, A40, A41, A55, A57, A62 | B27 |

All 84 requirement cases and 27 capability results have a primary implementation ticket. Issue #148 lists all 19 CLI commands; #149 lists all 14 default skills. The 128 historical operations map through their B results; the capability map retains public/internal/host/specialist destinations for all 33 historical skills.

## Implementation order

1. Core persistence/request handling → tasks, runner and host execution.
2. Memory, collaboration, newsroom, external monitoring, recovery and independent outcome/retrospective evaluation.
3. CLI integration → skill definitions → rules entry and actual startup.
4. Data migration and distribution/guide installation → full validation, three-project rollout and finish.

## Core foundation implementation

The internal request-scoped identity/storage foundation for #137 is described in
[Core foundation](core-foundation.md). Isolated tests do not establish live hook,
CLI, migration, or deployment completion; those remain in their assigned tickets.

[Task ledger implementation](task-ledger.md) is the current #140 scope, not completion of subsequent runner/host/CLI work.
