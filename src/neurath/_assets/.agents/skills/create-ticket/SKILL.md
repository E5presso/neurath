---
name: create-ticket
description: 승인된 plan, investigation result, follow-up work item에서 검증된 GitHub Issue를 생성합니다.
intent-class: ticket.create
input-authority: repository-spec
not-for: [spec.plan, ticket.execute]
argument-hint: "<plan path, investigation result, or work item> [--parent #N] [--milestone title]"
user-invocable: true
---

# create-issue

승인된 의도·spec·조사 결과에서 실제 work item을 만든다. 임의의 제품 요구를 추가하거나 생성 요청을 무한한 분해로 바꾸지 않는다. 기존 issue 중복, metadata 언어·label·assignee와 parent/dependency 관계를 확인한다. 본문에 범위·비목표·검증 가능한 인수 조건을 담고 GitHub 생성 뒤 실제 번호·내용·관계를 read-back한다. 필요한 분해가 사용자 의도를 바꾸면 그 결정만 먼저 받는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| prepare_issue_content | content_plan, body_files, label_plan, assignee_plan, relationship_plan, domain_dictionary_lookup, task_size_audit, parallelization_plan |
| create_github_objects | created_issue_urls, milestone_result, metadata_mutation_result |
| verify_readback | readback_issues, readback_metadata, metadata_readback, blocked_by_metadata, task_size_readback, github_metadata_language, verification_result |
| report_result | ticket_report |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.
