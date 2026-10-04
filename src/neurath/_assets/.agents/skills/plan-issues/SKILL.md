---
name: plan-issues
description: 새 Neurath product intent와 product·domain·architecture decision을 질문(grilling)으로 명확히 하고, 확정 결과를 durable 문서와 GitHub Issue hierarchy로 분해합니다. 기존 spec audit, 승인된 single work item 실행, private-memory pattern 승격에는 사용하지 않습니다.
intent-class: spec.plan
input-authority: user-product-intent
not-for: [ticket.create, ticket.execute]
argument-hint: "<제품 방향, 기능 아이디어, 문제 설명>"
user-invocable: true
---

# plan

새 product 의도와 domain/architecture 결정을 실제 질문으로 명확히 한다. 현재 지시·상위 의도·용어 정의·코드를 읽고 결정되지 않은 사항과 이미 확정된 사실을 구분한다. 루프를 위한 질문을 만들지 않고 실제 선택에 필요한 질문만 한다.

확정 결과를 FR/SC와 비목표, 인수 조건, 오류·권한·복구 경계가 있는 durable spec에 기록한다. 긴 작업의 질문·결정·남은 쟁점을 checkpoint로 보존한다. 독립 cold-read로 문서만 가지고 실행 가능한지 검토하고 누락·모순을 해소한다.

승인된 결과를 응집된 work item과 실제 dependency·write conflict·critical path로 분해한다. 무조건 병렬로 만들거나 크기만으로 잘게 쪼개지 않는다. GitHub 생성이 승인된 범위에서 milestone/parent/child/dependency를 만들고 실제 metadata와 FR/SC coverage를 읽는다. 새로 만든 spec을 이전 미확정 문서로 덮어쓰지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| input | input_summary, upstream_question_status |
| analysis | grill_with_docs_source, repo_evidence, docs_evidence, language_conflicts, domain_dictionary_lookup |
| grill_and_plan | decision_tree, decision_log, compaction_resume_source, language_ledger, domain_dictionary_delta, doc_update_plan |
| spec_artifact | spec_artifact, no_clarification_markers, fr_index, sc_index, approval_source |
| documentation | persisted_spec, product_context, decision_log, domain_dictionary_delta, doc_updates, adr_decisions |
| cold_read_simulation | simulation_result, ambiguity_check, task_size_audit, parallelization_check, critical_path_check, t1_spec_probe_result, t2_dag_coherence_result, t3_value_drift_result, t4_grill_replay_result, soft_block_decision, clean_slate_read_result, context_rot_check, all_parallel_approval, evaluation_loop_receipt |
| github_issue_hierarchy | work_items, task_size_audit, write_conflict_matrix, fr_sc_coverage, dependency_graph, critical_path, parallel_groups, test_plan, github_milestone, parent_issue, child_issues, blocked_by_metadata, metadata_readback, verification_result |
| report_result | plan_report |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.
