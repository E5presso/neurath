# Harness Index

The task owns skill progress. Read the current project policy before acting.

## Rules

- [behavioral](rules/behavioral.md)
- [constructive-skeptic-policy](rules/constructive-skeptic-policy.json)
- [core-work](rules/core-work.md)
- [deterministic-harness](rules/deterministic-harness.md)
- [domain-dictionary](rules/domain-dictionary.md)
- [evaluation-loops](rules/evaluation-loops.md)
- [harness-writing](rules/harness-writing.md)
- [knowledge-graph](rules/knowledge-graph.md)
- [tool-runtime-map](rules/tool-runtime-map.md)
- [worktree-isolation](rules/worktree-isolation.md)

## Skills

- [audit-deps](skills/dependency-audit/SKILL.md): execute
- [autopilot](skills/autopilot/SKILL.md): collect_issues → dependency_dag → execute_waves → recovery → meta_detection → intent_audit → sync_docs → terminal_report
- [checkpoint](skills/checkpoint/SKILL.md): execute
- [commit](skills/commit/SKILL.md): status_and_diff → stage_scope → commit
- [create-issue](skills/create-ticket/SKILL.md): prepare_issue_content → create_github_objects → verify_readback → report_result
- [create-pr](skills/create-pr/SKILL.md): branch_state → push → pr
- [create-worktree](skills/create-worktree/SKILL.md): execute
- [debug](skills/investigate/SKILL.md): execute
- [design-ui](skills/explore-ui/SKILL.md): authority_and_references → canvas_exploration → user_selection → implementation_handoff
- [dev-docs](skills/sync-dev-docs/SKILL.md): execute
- [explain-code](skills/explain-code/SKILL.md): scope → inspect → explain
- [finish-session](skills/finish-session/SKILL.md): status_and_diff → stage_scope → commit → push_readback → graphify_update → worktree_release
- [graphify](skills/graphify/SKILL.md): scope → graph_work → report
- [implement-issue](skills/process-ticket/SKILL.md): orientation → intent_and_scan → worktree_context → test_first → implementation → verification → publication → monitoring → merge_cleanup
- [implement-ui](skills/implement-ui/SKILL.md): execute
- [memory-to-rules](skills/promote-memory/SKILL.md): execute
- [optimize-harness](skills/optimize-harness/SKILL.md): inventory → optimize → evaluate
- [plan](skills/plan-issues/SKILL.md): input → analysis → grill_and_plan → spec_artifact → documentation → cold_read_simulation → github_issue_hierarchy → report_result
- [pr-feedback](skills/triage-comments/SKILL.md): execute
- [qa](skills/automate-qa/SKILL.md): scenario_and_environment → deployed_surface_evidence → gap_and_loop_closure
- [reconnect-host](skills/reconnect-host/SKILL.md): inspect → authorize → schedule → verify → cleanup
- [review-code](skills/review-code/SKILL.md): execute
- [review-pr](skills/pr-review/SKILL.md): execute
- [review-spec](skills/audit-spec/SKILL.md): execute
- [review-ui](skills/review-ui/SKILL.md): capture_and_compare → user_visual_decision
- [sync-design](skills/sync-design/SKILL.md): execute
- [sync-docs](skills/sync-docs/SKILL.md): plan → write → verify → reconcile → report → deliver
- [test-harness](skills/evaluate-harness/SKILL.md): define_failure_scenario → independent_evaluation → gap_and_verification
- [update-deps](skills/update-dependencies/SKILL.md): execute
- [update-neurath](skills/update-neurath/SKILL.md): inspect → check_release → prepare → choose → apply → activation
- [update-status](skills/update-project-status/SKILL.md): execute
- [user-docs](skills/sync-user-docs/SKILL.md): execute
- [watch-pr](skills/monitor-pr/SKILL.md): start_monitor → record_subscription → resume_event → terminal_state
