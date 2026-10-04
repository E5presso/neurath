---
name: create-pr
description: remote가 있으면 현재 branch를 push하고 PR을 생성합니다.
intent-class: pull-request.create
input-authority: repository-git-state
not-for: [pull-request.review, session.finish]
argument-hint: "<PR intent or issue number> [--acceptance-file PATH | --acceptance-missing]"
user-invocable: true
---

# create-pr

실제 branch, remote, local HEAD와 검증·독립 리뷰 결과를 확인한다. 승인된 branch를 push하고 실제 remote head를 read-back한다. 기존 PR이 있으면 재사용한다. PR에는 구체적 문제·결과 동작·실제 validation·관련 issue와 필요한 metadata를 담는다. 생성/수정 후 body와 head, issue 연결·labels·assignee/reviewer를 다시 읽는다. 현재 host의 PR attachment 도구가 있으면 생성한 PR을 붙인다. `publication_read`로 원격 결과를 보존한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| branch_state | git_status, remote_branch |
| push | remote_head |
| pr | pr_url, pr_body_audit, acceptance_handoff, pr_metadata_readback, linked_issue_readback, github_metadata_language |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.
