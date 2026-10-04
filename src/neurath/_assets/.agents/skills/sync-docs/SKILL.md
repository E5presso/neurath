---
name: sync-docs
description: documentation synchronization을 developer/user documentation scope로 routing합니다.
intent-class: docs.route
input-authority: repository-source
not-for: [developer-docs.sync, user-docs.sync]
argument-hint: "[dev|user|all] [component]"
user-invocable: true
---

# sync-docs

현재 source와 승인된 동작을 기준으로 developer/user documentation 범위를 정한다. 조건에 맞는 dev-docs/user-docs를 사용한다. 작성과 검증을 구분하고 사실·metadata·링크·중요 경고를 독립적으로 대조한다. 문서가 실행 동작을 바꾸거나 미승인 요구를 확정하지 않게 한다. 불일치를 수정하고 실제 전달/게시 범위까지만 완료한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| plan | sync_scope, source_evidence |
| write | writer_report, changed_docs, source_sha, frontmatter_or_metadata_check |
| verify | verifier_report, source_fact_check, frontmatter_or_metadata_check, critical_warning_findings, writer_independence_check, ten_point_fact_check, critical_warning_report |
| reconcile | reconcile_result |
| report | sync_report |
| deliver | delivery_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.
