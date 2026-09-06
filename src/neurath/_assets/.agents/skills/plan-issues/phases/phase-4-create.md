# Phase 6: GitHub Issue 계층 생성

문서화된 스펙, work item, dependency graph를 사용해 GitHub 변경을
`/create-ticket`에 위임합니다.

## 절차

1. `templates.md`의 GitHub Issue Hierarchy 형식으로 milestone, parent
   issue, child issue, label, assignee policy, dependency graph를 준비합니다.
   각 child issue에는 `task_size_audit`, `write_conflict_matrix`,
   `critical_path`, `parallel_groups`, `all_parallel_approval`을 반영합니다.
   각 child issue는 담당 `FR-*` 1개 이상과 기여 `SC-*` 1개 이상을 가져야 합니다.
2. `/create-ticket`을 호출해 GitHub 객체를 생성합니다.
3. 생성 후 readback으로 milestone, parent issue, child issue,
   `blocked_by_metadata`, label, assignee, project/milestone, sub-issue
   relationship을 검증합니다.
4. 검증 실패 시 부분 성공을 성공으로 보고하지 않습니다.

## 통과 조건

문서화된 스펙과 Issue 본문이 서로 다른 요구사항을 말하면 생성하지
않습니다.

모든 FR은 최소 1개 child issue에 매핑되어야 하고, 모든 SC는 child issue 산출물의
합으로 달성 가능해야 합니다. 누락이 있으면 issue를 생성하지 않습니다.

## 완료 evidence

- `work_items`
- `task_size_audit`
- `write_conflict_matrix`
- `fr_sc_coverage`
- `dependency_graph`
- `critical_path`
- `parallel_groups`
- `all_parallel_approval`
- `test_plan`
- `github_milestone`
- `parent_issue`
- `child_issues`
- `blocked_by_metadata`
- `metadata_readback`
- `verification_result`
