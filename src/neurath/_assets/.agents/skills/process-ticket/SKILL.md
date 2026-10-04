---
name: process-ticket
description: 승인된 Neurath work item 하나를 분석, test, 구현, PR, monitoring, 선택적 merge까지 실행합니다.
intent-class: ticket.execute
input-authority: github-work-item
not-for: [work-item-set.execute, spec.plan]
argument-hint: "<plan path, issue number, or work item title> [--require-approval] [--auto-merge]"
user-invocable: true
---

# Implement issue

승인된 work item 하나를 실제 결과까지 처리한다. 먼저 현재 사용자 요청·저장소 지침·`.neurath/project.json`의 문서를 읽고 범위와 완료 조건을 확인한다. 계획·검사·보고를 사용자 목표의 완료로 대신하지 않는다.

## 실행 상태

`session_status`와 `task_list`로 기존 작업을 복구한다. 새 요구이면 보존된 실제 입력을 참조하여 `task_define`, `task_start`, `skill_start(skill="implement-issue")`를 실행한다. 위임받았다면 전달된 Task와 Assignment를 사용한다. 다른 완료 원장이나 workflow를 만들지 않는다.

`phase_read`가 현재 단계와 필요한 근거를 반환한다. 아래 순서를 지키며 각 단계의 결과를 `phase_complete`로 기록한다. 실패는 같은 Task의 재작업이며 `phase_restart`가 정한 지점부터 다시 진행한다. 순서를 건너뛰거나 실패·대기를 완료로 바꾸지 않는다. Task 완료에는 모든 단계와 원래 인수 조건이 모두 필요하다.

| 단계 ID | 수행할 일 | 상세 |
| --- | --- | --- |
| orientation | work item, 지침, 정의처 확인 | [분석](phases/phase-1-analysis.md) |
| intent_and_scan | 의도, 코드와 검증 계획 | [계획](phases/phase-2-plan.md) |
| worktree_context | 적절한 checkout과 writer 선택 | [작업 공간](phases/phase-3-worktree.md) |
| test_first | 적용되는 실패/특성 테스트 확인 | [테스트](phases/phase-4-review.md) |
| implementation | 승인된 범위 구현 | [구현](phases/phase-4-review.md) |
| verification | 인수 조건과 필수 검사 | [검증](phases/phase-4_5-acceptance-grep.md) |
| publication | commit, 독립 리뷰, push와 PR | [게시](phases/phase-5-commit.md) |
| monitoring | CI, 리뷰, 코멘트와 병합 준비 | [관찰](phases/phase-6-monitor.md) |
| merge_cleanup | 승인된 병합, 실제 결과와 정리 | [마무리](phases/phase-8-merge-cleanup.md) |

## 실행 선택

현재 에이전트가 선택한 worktree에서 계속 수행할 수 있다. 별도 작업이 필요할 때 `assignment_prepare`로 `subagent`, `session`, `cross-provider` 중 하나를 고른다. 기본은 현재 작업 안의 bounded subagent다. 독립 대화·수명이 필요할 때 session, 다른 provider의 능력·관점이 필요할 때 cross-provider를 선택하고 근거를 남긴다. Worker는 역할이며 실행 종류가 아니다. Repository root 진입이나 worktree 필요만으로 새 세션·앱 프로젝트를 만들지 않는다.

Native child는 반환된 dispatch marker와 Task/Assignment ID를 받고 실제 native 도구로 시작한다. 독립/provider 세션은 `provider_prepare`의 native 실행 안내를 따른다. Prepared, 시작, 결과 보고, 소유자의 수락을 구분한다. Executor는 같은 Task의 절차를 수행하고 owner는 사용자 목표의 최종 수락을 맡는다.

## 권한과 범위

읽기와 결과 보고에는 writer lease가 필요 없다. 수정 전에 실제 대상 checkout을 `worktree_claim`하고 native 도구의 workdir/파일 경로를 그 대상으로 지정한다. CWD 변경은 신원 변경이 아니다. 다른 writer의 claim을 덮어쓰지 않는다.

기존 대화의 승인은 계속 유효한 범위에서 사용한다. 게시·병합은 실제 입력과 정확한 계획 대상에 대한 `approval_record`로 판단을 남기며, 원문 일치와 승인 의미의 판단을 구분한다. `--auto-merge`와 사용자의 직접 병합 요청은 같은 검증 gate를 거친 병합의 승인이다. 이미 승인된 수정·재검증·코멘트 처리에 반복 승인을 요구하지 않는다.

새 product 결정, 범위 변경, 실제 credential/권한 부족, 되돌릴 수 없는 외부 변경이 필요할 때만 구체적으로 묻는다. 실행 요청된 ticket을 임의로 다른 issue들로 바꾸지 않는다. 필요한 분해가 사용자의 의도를 바꾸면 먼저 그 결정을 받는다.

완료는 실제 PR·issue·검사·리뷰·병합 상태를 확인한 뒤 보고한다. PR 준비만 요청받았다면 정의된 `pr-ready` 경로를 사용한다. 병합까지 요청받았다면 PR 준비 상태에서 Task를 끝내지 않는다.
