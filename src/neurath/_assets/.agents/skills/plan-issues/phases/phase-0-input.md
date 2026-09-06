# Phase 0: 입력 수집

제품 방향과 planning 요청을 수집하고 ledger를 초기화합니다.

## 절차

1. 사용자의 기능 방향, 제품 질문, 문제 설명을 요약합니다.
2. `decision_tree`, `decision_log`, `compaction_resume_source`,
   `language_ledger`, `product_context`, `doc_updates`, `adr_candidates`,
   `work_items`, `test_plan`, `github_issue_hierarchy`를 초기화합니다.
3. `GoalContract` 초안을 만들고 goal, scope/non-goal, constraint, success/verification,
   brownfield context/ownership/lifecycle의 material gap을 authority와 함께 등록합니다.
4. 문서나 코드로 답할 수 있는 repository gap과 사용자 판단이 필요한 gap을 분리합니다.
5. 입력이 너무 넓으면 adaptive control이 고른 upstream user gap을 최대 하나만 묻습니다.

## 통과 조건

대상 프로젝트의 제품 context가 누락됐거나 낡았으면 새 제품 질문을 시작하지
않습니다. 먼저 `.neurath/project.json (documents 슬롯)`와
`.neurath/project.json (documents 슬롯)`를 읽습니다.

## 완료 evidence

- `input_summary`
- `ledgers_initialized`
- `upstream_question_status`
- `adaptive_control_initialized`
