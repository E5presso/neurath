<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/capability-map.md)

# 스킬, 도구, 구현을 찾는 기능 지도

요청한 동작을 어디에서 담당할지, 함께 바꿔야 할 소스와 회귀 계약이 무엇인지 이 지도에서 찾는다. 공개 스킬 이름은 에이전트가 수행할 일을 설명하고 내부 이름은 배포 원본의 위치를 가리킨다. 이름이 있는 도구는 지속 상태를 다룬다. 스킬 이름 자체가 도구 호출이나 워크플로 실행 근거가 되지는 않는다.

## 공개 스킬 목록

공개 스킬은 31개이고 이 중 29개에 단계 계약이 있다. `explain-code`, `graphify`는 단계 계약이 없는 지원 스킬이다. 설치 접두사는 소스 신원을 유지하면서 표시 이름을 바꾼다. 예를 들어 `neurath-` 접두사를 쓰면 `debug`를 `neurath-debug`로 설치한다.

| 수행할 일 | 공개 스킬 | 내부 소스 이름 | 계약 |
| --- | --- | --- | --- |
| 보안·라이선스·최신성·선언 불일치 조사 | `audit-deps` | [dependency-audit](../../../src/neurath/_assets/.agents/skills/dependency-audit/SKILL.md) | 단계 |
| 명시적으로 요청한 여러 이슈의 수행 조정 | `autopilot` | [autopilot](../../../src/neurath/_assets/.agents/skills/autopilot/SKILL.md) | 단계 |
| 되돌릴 수 있는 진행 중 상태 저장 | `checkpoint` | [checkpoint](../../../src/neurath/_assets/.agents/skills/checkpoint/SKILL.md) | 단계 |
| 검증된 승인 변경 커밋 | `commit` | [commit](../../../src/neurath/_assets/.agents/skills/commit/SKILL.md) | 단계 |
| 승인된 작업 항목 생성 | `create-issue` | [create-ticket](../../../src/neurath/_assets/.agents/skills/create-ticket/SKILL.md) | 단계 |
| 승인된 push와 PR 생성 | `create-pr` | [create-pr](../../../src/neurath/_assets/.agents/skills/create-pr/SKILL.md) | 단계 |
| 이슈별 격리 작업 공간 준비 | `create-worktree` | [create-worktree](../../../src/neurath/_assets/.agents/skills/create-worktree/SKILL.md) | 단계 |
| 결함 재현과 원인 분리 | `debug` | [investigate](../../../src/neurath/_assets/.agents/skills/investigate/SKILL.md) | 단계 |
| 설계 대안 탐색과 정확한 캔버스 선택 확보 | `design-ui` | [explore-ui](../../../src/neurath/_assets/.agents/skills/explore-ui/SKILL.md) | 단계 |
| 개발자 문서 갱신 | `dev-docs` | [sync-dev-docs](../../../src/neurath/_assets/.agents/skills/sync-dev-docs/SKILL.md) | 단계 |
| 현재 소스와 테스트에 근거한 동작 설명 | `explain-code` | [explain-code](../../../src/neurath/_assets/.agents/skills/explain-code/SKILL.md) | 지원 |
| 승인된 커밋·push·그래프 갱신·소유권 해제 | `finish-session` | [finish-session](../../../src/neurath/_assets/.agents/skills/finish-session/SKILL.md) | 단계 |
| 코드·문서 관계 그래프 탐색 | `graphify` | [graphify](../../../src/neurath/_assets/.agents/skills/graphify/SKILL.md) | 지원 |
| 승인된 단일 이슈 구현 | `implement-issue` | [process-ticket](../../../src/neurath/_assets/.agents/skills/process-ticket/SKILL.md) | 단계 |
| 승인된 정확한 디자인 노드 구현 | `implement-ui` | [implement-ui](../../../src/neurath/_assets/.agents/skills/implement-ui/SKILL.md) | 단계 |
| 반복되는 비공개 지식을 검토해 승인된 프로젝트 규칙으로 반영 | `memory-to-rules` | [promote-memory](../../../src/neurath/_assets/.agents/skills/promote-memory/SKILL.md) | 단계 |
| 기능을 보존하며 주입 프롬프트 줄이기 | `optimize-harness` | [optimize-harness](../../../src/neurath/_assets/.agents/skills/optimize-harness/SKILL.md) | 단계 |
| 제품 결정 명확화와 문서·이슈 분해 | `plan` | [plan-issues](../../../src/neurath/_assets/.agents/skills/plan-issues/SKILL.md) | 단계 |
| 검토 의견 평가와 대응 | `pr-feedback` | [triage-comments](../../../src/neurath/_assets/.agents/skills/triage-comments/SKILL.md) | 단계 |
| 배포된 화면·API·저장 결과 확인 | `qa` | [automate-qa](../../../src/neurath/_assets/.agents/skills/automate-qa/SKILL.md) | 단계 |
| 변경에서 근거 있는 결함 찾기 | `review-code` | [review-code](../../../src/neurath/_assets/.agents/skills/review-code/SKILL.md) | 단계 |
| 정확한 PR head에서 확인한 검토 게시 | `review-pr` | [pr-review](../../../src/neurath/_assets/.agents/skills/pr-review/SKILL.md) | 단계 |
| 구현 전 요구사항의 누락과 모순 검토 | `review-spec` | [audit-spec](../../../src/neurath/_assets/.agents/skills/audit-spec/SKILL.md) | 단계 |
| 승인된 디자인과 실행 화면을 비교해 사용자 판단 지원 | `review-ui` | [review-ui](../../../src/neurath/_assets/.agents/skills/review-ui/SKILL.md) | 단계 |
| 저장소 토큰과 컴포넌트 연결을 캔버스에 반영 | `sync-design` | [sync-design](../../../src/neurath/_assets/.agents/skills/sync-design/SKILL.md) | 단계 |
| 문서 변경 범위 분류 | `sync-docs` | [sync-docs](../../../src/neurath/_assets/.agents/skills/sync-docs/SKILL.md) | 단계 |
| 실패 시나리오로 하네스 통제 검증 | `test-harness` | [evaluate-harness](../../../src/neurath/_assets/.agents/skills/evaluate-harness/SKILL.md) | 단계 |
| 범위를 통제한 의존성 업데이트와 검사 | `update-deps` | [update-dependencies](../../../src/neurath/_assets/.agents/skills/update-dependencies/SKILL.md) | 단계 |
| 이슈·프로젝트 메타데이터 갱신 | `update-status` | [update-project-status](../../../src/neurath/_assets/.agents/skills/update-project-status/SKILL.md) | 단계 |
| 승인되고 구현된 사용자 동작 문서화 | `user-docs` | [sync-user-docs](../../../src/neurath/_assets/.agents/skills/sync-user-docs/SKILL.md) | 단계 |
| PR 변경 관찰 | `watch-pr` | [monitor-pr](../../../src/neurath/_assets/.agents/skills/monitor-pr/SKILL.md) | 단계 |

수정할 원본은 `src/neurath/_assets/.agents/skills` 아래에 있다. 설치된 `.agents/skills`와 `.neurath/rules`는 투영 결과다. 이름 연결은 [skill_names.py](../../../src/neurath/skill_names.py)에 있으며 공개 검사는 스킬 목록, 로케일 구성, 패키지 내용을 확인한다.

`create-package`, `local-dev`, `onboard`, `refactor-code`, `impact-analysis`, `improve-coverage`, `property-test`는 공개 단독 스킬 목록에서 제외된 이름이다. 설치된 독립 기능으로 안내하지 않고 실제 요청을 현재 담당 스킬과 프로젝트 절차로 연결한다.

## 공개 도구 계열

현재 공개 조회 스키마의 도구는 128개이며 아래 표에 각각 한 번씩 실었다. 내부 실행 연결표의 138개와는 범위가 다르다. 저장된 기존 호출의 호환성을 위해 남은 작업 일부는 공개 조회에 없다. 정확한 필드는 설치된 `tools/list` 스키마를 사용하고 공통 결과 형식과 기본 예제는 [작업 도구](task-tools.md)를 참고한다.

| 목적 | 이름이 있는 도구 |
| --- | --- |
| 요청 작업과 현재 세션 | `harness_bypass`, `session_status`, `session_inspect`, `turn_inspect`, `turn_yield`, `task_define`, `task_list`, `task_start`, `task_resolve` |
| 작업 공간 소유권 | `worktree_inspect`, `worktree_claim`, `worktree_release`, `worktree_isolation`, `worktree_cleanup` |
| 제공자 선택과 실행 | `provider_run`, `provider_status`, `provider_cancel`, `provider_recover`, `provider_capabilities`, `provider_route`, `provider_models`, `provider_plan`, `provider_plan_read` |
| 동료 메시지와 할당 | `collaboration_discover`, `collaboration_inbox`, `collaboration_send`, `collaboration_reply`, `collaboration_message`, `collaboration_ack`, `collaboration_forward`, `collaboration_submitted`, `collaboration_assign`, `collaboration_accept`, `collaboration_report`, `collaboration_task`, `collaboration_register`, `collaboration_conversation`, `collaboration_close`, `collaboration_subscribe`, `collaboration_unsubscribe`, `collaboration_publish` |
| 전달 복구 | `delivery_status`, `delivery_redrive` |
| 공통 소식 | `newsroom_headlines`, `newsroom_read`, `newsroom_publish`, `newsroom_revise`, `newsroom_comment`, `newsroom_peers`, `newsroom_seen` |
| 메모리와 세션 사실 | `memory_recall`, `memory_checkpoint`, `memory_pull`, `artifact_put`, `artifact_read`, `enclave_read`, `enclave_set`, `enclave_delete` |
| 학습 | `learning_status`, `learning_pending`, `learning_history`, `learning_defer` |
| 계약이 있는 단계 | `phase_start`, `phase_current`, `phase_evidence_prepare`, `phase_complete`, `phase_finalize` |
| 적응형 판단과 독립 평가 | `adaptive_read`, `adaptive_preflight`, `adaptive_replace`, `adaptive_override_goal`, `delegation_prepare`, `delegation_assign`, `evaluation_prepare`, `evaluation_read`, `evaluation_execute`, `evaluation_report`, `evaluation_consume`, `evaluation_loop_open`, `evaluation_loop_read`, `evaluation_loop_round`, `evaluation_loop_close` |
| 고정 검토와 게시 | `review_begin`, `review_report`, `review_consume`, `review_abort`, `review_publish`, `review_comments` |
| 진단과 하네스 문제 | `diagnostics_integrity`, `diagnostics_project`, `diagnostics_profile`, `diagnostics_continuation`, `incident_record`, `incident_validate`, `incident_resolve`, `incident_escalate`, `incident_refresh`, `incident_supersede`, `process_evidence_record` |
| 설치와 업데이트 | `releases_status`, `releases_check`, `maintenance_choice_read`, `maintenance_choice_prepare`, `releases_notice`, `releases_recover`, `releases_prepare`, `releases_apply`, `releases_choose`, `installation_plan`, `installation_apply`, `installation_recover` |
| 공개 보고 | `reporting_status`, `reporting_list`, `reporting_read`, `reporting_prepare`, `reporting_submit`, `reporting_reconcile`, `reporting_consent`, `reporting_approve` |
| 백그라운드 관찰 | `monitor_start`, `monitor_status`, `monitor_cancel`, `monitor_recover`, `monitor_readback`, `monitor_event`, `monitor_ack`, `monitor_external_wait`, `monitor_handoff` |

공개 단계 진입점은 `phase_start`, `phase_complete`, `phase_finalize`다. 이전 워크플로 이름은 저장된 호출과 호환된다. material batch, 등록 검사 도구, `agent(argv)` 역시 호환 기능이며 일반 편집·검사의 공개 필수 절차가 아니다.

## 상황에 맞는 판단 기준

| 상황 | 따라야 할 계약 |
| --- | --- |
| 측정 가능한 일반 작업 | 작업을 정의하고 네이티브 편집·검사를 수행한 뒤 소유자 결과를 한 번 기록한다. 작업 목록이 있으면 Stop의 기준이 된다. |
| 명시적인 적응형 스킬 | 실제 독립 평가 권한을 확보하고 정확한 후보를 연결하며 인증된 결과를 소비한 뒤 계약 전이를 수행한다. |
| 고정 코드·PR 검토 | 별도 검토 기준을 적용하고 게시는 현재 PR head에 묶는다. |
| 동료 할당 | 실제 동료를 찾아 전체 할당을 전달하고 네이티브 수락과 보고를 받는다. 수신 확인은 전송 진행 상태다. |
| 워크트리 변경·정리 | 현재 소유권과 반환된 fencing 세대를 사용하고 정리 전 실제 Git 참조를 확인한다. |
| 설치·업데이트·보고 | 정확한 변경이나 초안을 준비하고 해당 사용자 선택을 유지하며 이름이 있는 도메인 작업으로 적용해 실제 결과를 확인한다. |

이 판단을 뒷받침하는 상태와 네이티브 근거는 [작업과 TODO 계약](task-todo-contract.md), [실행 수명주기](runtime-lifecycle.md), [호스트 통합](hosts.md)에 설명한다.

## 구현과 회귀 검사 담당

각 동작을 담당하는 소스와 테스트를 연결했다. 검증할 범위를 찾기 위한 목록이며 특정 설치에서 테스트나 실제 호스트 시나리오가 통과했다는 주장은 아니다.

| 책임 | 구현과 회귀 계약 |
| --- | --- |
| 배포 자산 무결성 | [resources.py](../../../src/neurath/resources.py), [manifest.json](../../../src/neurath/manifest.json), [test_installer.py](../../../tests/test_installer.py) |
| 설치 보존 | [projection.py](../../../src/neurath/install/projection.py), [transaction.py](../../../src/neurath/install/transaction.py), [test_installer.py](../../../tests/test_installer.py), [test_publication.py](../../../tests/test_publication.py) |
| 실제 신원과 프롬프트 | [identity.py](../../../src/neurath/hosts/identity.py), [hooks.py](../../../src/neurath/hosts/hooks.py), [test_host_lifecycle.py](../../../tests/test_host_lifecycle.py), [test_prompt_delivery.py](../../../tests/test_prompt_delivery.py) |
| 상태와 쓰기 소유권 | [session_kernel.py](../../../src/neurath/_assets/scripts/agent_harness/session_kernel.py), [state_handle.py](../../../src/neurath/_assets/scripts/agent_harness/state_handle.py), [worktree_registry.py](../../../src/neurath/_assets/scripts/agent_harness/worktree_registry.py), [runtime_database.py](../../../src/neurath/_assets/scripts/agent_harness/runtime_database.py), [test_session_kernel.py](../../../tests/runtime/agent_harness/test_session_kernel.py), [test_worktree_registry.py](../../../tests/runtime/agent_harness/test_worktree_registry.py) |
| 요청 작업과 결과 | [task_ledger_tasks.py](../../../src/neurath/runtime/task_ledger_tasks.py), [task_ledger.py](../../../src/neurath/_assets/scripts/agent_harness/task_ledger.py), [task_service.py](../../../src/neurath/_assets/scripts/agent_harness/task_service.py), [test_task_acceptance_review.py](../../../tests/test_task_acceptance_review.py), [test_task_tools.py](../../../tests/test_task_tools.py), [test_task_todo.py](../../../tests/test_task_todo.py) |
| 단계와 평가 권한 | [phase_runner.py](../../../src/neurath/_assets/scripts/skill_harness/phase_runner.py), [adaptive_control_authority.py](../../../src/neurath/_assets/scripts/agent_harness/adaptive_control_authority.py), [evaluation_loop.py](../../../src/neurath/_assets/scripts/agent_harness/evaluation_loop.py), [test_phase_runner.py](../../../tests/runtime/skill_harness/test_phase_runner.py), [test_adaptive_control_authority.py](../../../tests/runtime/agent_harness/test_adaptive_control_authority.py) |
| 이름이 있는 API와 조회 | [task_schema.py](../../../src/neurath/runtime/task_schema.py), [tasks.py](../../../src/neurath/runtime/tasks.py), `src/neurath/runtime/*_tasks.py`, [mcp.py](../../../src/neurath/agents/mcp.py), [mcp_guidance.py](../../../src/neurath/install/mcp_guidance.py), [test_communication_mcp.py](../../../tests/test_communication_mcp.py), [test_mcp_guidance.py](../../../tests/test_mcp_guidance.py) |
| 모델과 제공자 실행 | [model_planning.py](../../../src/neurath/providers/model_planning.py), [permission_inheritance.py](../../../src/neurath/providers/permission_inheritance.py), [jobs.py](../../../src/neurath/providers/jobs.py), [job_recovery.py](../../../src/neurath/providers/job_recovery.py), [supervision.py](../../../src/neurath/providers/supervision.py), [provider_execution.py](../../../src/neurath/runtime/provider_execution.py), [provider_policy.py](../../../src/neurath/runtime/provider_policy.py), [test_model_planning.py](../../../tests/test_model_planning.py), [test_inherited_provider_modes.py](../../../tests/test_inherited_provider_modes.py), [test_provider_jobs.py](../../../tests/test_provider_jobs.py) |
| 지속 메시지와 전달 | [store.py](../../../src/neurath/agents/store.py), [lifecycle.py](../../../src/neurath/agents/lifecycle.py), [delivery.py](../../../src/neurath/agents/delivery.py), [delivery_recovery.py](../../../src/neurath/agents/delivery_recovery.py), [newsroom.py](../../../src/neurath/agents/newsroom.py), [test_delivery_recovery.py](../../../tests/test_delivery_recovery.py), [test_newsroom_mcp.py](../../../tests/test_newsroom_mcp.py) |
| 메모리·enclave·학습 | [store.py](../../../src/neurath/memory/store.py), [hooks.py](../../../src/neurath/memory/hooks.py), [transcript.py](../../../src/neurath/memory/transcript.py), [learning.py](../../../src/neurath/memory/learning.py), [enclave_store.py](../../../src/neurath/_assets/scripts/agent_harness/enclave_store.py), [test_project_memory.py](../../../tests/test_project_memory.py), [test_learning.py](../../../tests/test_learning.py), [test_enclave_store.py](../../../tests/runtime/agent_harness/test_enclave_store.py) |
| 업데이트와 보고 | [updates.py](../../../src/neurath/updates.py), [release_install.py](../../../src/neurath/release_install.py), [reporting.py](../../../src/neurath/reporting.py), [user_choices.py](../../../src/neurath/runtime/user_choices.py), [test_user_choices_mcp.py](../../../tests/test_user_choices_mcp.py), [test_reporting.py](../../../tests/test_reporting.py) |

저장된 호출이 material·등록 검사 경로를 사용한다면 남아 있는 호환 구현도 확인해야 한다. 관련 소스는 [material_action.py](../../../src/neurath/_assets/scripts/agent_harness/material_action.py), [verification.py](../../../src/neurath/runtime/verification.py), 검사는 [material 동작 회귀](../../../tests/runtime/agent_harness/test_material_action.py)다. 네이티브 검사 실행이 이 호환 경로의 근거를 자동으로 생성하지는 않는다.

## 기능 지도 변경 검증

목록, 패키지, 링크 변경은 공개 회귀 검사부터 실행한다. 필요한 전체 검사는 최종 소스에서 수행한다.

```sh
uv run --locked pytest -q tests/test_publication.py
uv run --locked python tools/check.py
```

실행 자산을 바꿨다면 [개발 안내](index.md)에 따라 manifest 갱신, 빌드, 자기 설치 업데이트도 수행한다. 문장만 바꾼 경우 그 이유만으로 설치할 필요는 없다. 결과를 설명할 때 원문 무결성, 패키지 동작, 설치 위치, 실제 활성화 관찰을 구분한다.
