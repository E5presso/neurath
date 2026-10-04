---
name: pr-review
description: 검증된 final-local-review를 exact PR head의 ai-review 승인 신호로 게시합니다.
intent-class: pull-request.review
input-authority: github-pr-state
not-for: [source.review, pull-request-comments.triage]
argument-hint: "[pr-number]"
user-invocable: true
---

# review-pr

이미 수행한 final local independent review를 정확한 PR head에 게시한다. 이 스킬은 새 소스 리뷰를 대신하지 않는다. 실제 local commit, accepted reviewer subject, remote/PR head가 일치하는지 확인한다. 검토되지 않은 head에 ai-review success를 게시하지 않는다. 게시 후 commit status/check와 GitHub reviewDecision을 별도로 읽는다. 필요한 GitHub actor 권한이 없으면 정확히 보고하고 user/host permission을 바꾸지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | pr_metadata, local_review_receipt, status_posted |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.
