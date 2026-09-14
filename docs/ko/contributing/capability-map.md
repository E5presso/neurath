<!-- last_updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->
# 필요한 작업에서 도구 찾기

[English](../../en/contributing/capability-map.md)

사용자가 원하는 결과를 먼저 확인하고 그 결과를 만드는 데 필요한 도구를 선택합니다. **태스크**는 목표와 관찰 가능한 완료 조건을 기록합니다. 호스트 **세션**의 **루트 에이전트**가 태스크 목록을 소유합니다. **워크트리 claim**은 체크아웃의 작업 소유권을 조정합니다. **receipt**는 특정 이벤트나 보고의 기록입니다. 워크플로의 **phase**는 절차를 나누고 **리뷰**는 정해진 범위를 평가합니다. 각 요소의 관계는 [아키텍처](architecture.md)에서 설명합니다.

사용자의 웹앱에서 저장한 필터가 새로고침 후 사라지는 예시라면, 기본 경로는 태스크 등록, 호스트 도구로 재현·구현, 필요한 API 리뷰, 근거 확인, 결과 기록입니다. 메모리와 학습은 재현 방법과 올바른 테스트 명령을 보존합니다. 제공자 실행·공개 보고·릴리스 설치·모니터링은 요청이나 선택한 절차에서 필요할 때 사용합니다.

아래는 현재 소스의 **공개 도구 128개 전체**입니다. **내부 작업은 138개**이며 저장된 호출의 호환 경로와 내부 material/verification 작업은 추가 공개 도구가 아닙니다. 표에는 최상위 필수 인자와 스키마의 읽기 전용 표시를 적었습니다. 선택 인자·중첩 구조·도메인 선행 조건은 실제 발견된 스키마에서 확인합니다. 읽기 전용 표시가 권한을 부여하지 않으며, 상태 변경 표시가 제품 파일 편집을 뜻하지도 않습니다.

`_neurath_binding`은 호스트 훅이 제공하므로 표에서 생략했습니다. 에이전트가 만들어 넣으면 안 됩니다. `harness_bypass`를 제외한 도구에는 유효한 호스트 호출이 필요하며 우회 중에는 사용할 수 없습니다. 입력·오류·재시도 규칙은 [태스크 도구](task-tools.md)를 참고하세요.

## 현재 세션과 작업 소유권 확인

세션은 호스트의 대화이며 루트 에이전트가 태스크 목록을 소유합니다. 워크트리 claim은 체크아웃의 작업 소유권을 조정합니다. claim을 얻기 전에 현재 상태를 확인합니다. isolation은 기존 이슈·루트 워크트리 관계를 검증하며 워크트리를 만들거나 전환하지 않습니다. cleanup에는 실제 브랜치·참조와 소유권 근거가 필요합니다. bypass는 Neurath 훅 제약만 바꿉니다. enabled 생략은 조회, true는 우회, false는 복원이며 호스트 권한과 기록은 유지됩니다.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `harness_bypass` | 상태 변경 | 없음 |
| `session_status` | 조회 | 없음 |
| `session_inspect` | 조회 | 없음 |
| `turn_inspect` | 조회 | 없음 |
| `worktree_inspect` | 조회 | 없음 |
| `worktree_claim` | 상태 변경 | 없음 |
| `worktree_release` | 상태 변경 | `expected_lease_epoch`, `fencing_token` |
| `worktree_isolation` | 상태 변경 | `issue_number`, `key` |
| `worktree_cleanup` | 상태 변경 | `workflow_id`, `base_branch`, `remote_ref`, `key` |

## 관찰 가능한 목표를 태스크로 기록

태스크는 목표·지시 출처·완료 조건을 연결합니다. 필요한 작업을 정의하고 반환된 리비전으로 시작한 뒤 실제 관찰에 따른 소유자 보고를 기록합니다. 목록은 실행 종료와 성공을 구분하고 호스트 TODO 표시값을 제공합니다. [태스크 도구](task-tools.md)와 [태스크 계약](task-todo-contract.md)을 참고하세요.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `task_define` | 상태 변경 | `tasks`, `expected_revision`, `key` |
| `task_list` | 조회 | 없음 |
| `task_start` | 상태 변경 | `task_id`, `expected_revision`, `expected_task_revision`, `key` |
| `task_resolve` | 상태 변경 | `task_id`, `expected_revision`, `expected_task_revision`, `key`, `status`, `references`, `summary` |

## 스킬 절차와 의사결정 관리

워크플로는 스킬 실행이며 phase는 그 절차의 한 단계입니다. 선택한 계약을 읽은 뒤 단계를 진행합니다. 근거는 정확한 현재 단계와 리비전에 연결됩니다. 적응형 의사결정과 목표 변경에는 해당 권한이 필요하고 yield의 결과 이름만으로 Stop 조건을 면제할 수 없습니다. 공개 스킬 이름과 고정 내부 계약 ID는 [스킬 참조](skills-reference.md)에 정리되어 있습니다.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `phase_start` | 상태 변경 | `workflow_id`, `key`, `skill`, `run_id`, `north_star` |
| `phase_current` | 조회 | `workflow_id` |
| `phase_evidence_prepare` | 상태 변경 | `workflow_id`, `expected_revision`, `key` |
| `phase_complete` | 상태 변경 | `workflow_id`, `expected_revision`, `key`, `phase_id`, `status`, `summary` |
| `phase_finalize` | 상태 변경 | `workflow_id`, `expected_revision`, `key`, `terminal_state` |
| `adaptive_read` | 조회 | `workflow_id` |
| `adaptive_preflight` | 조회 | 없음 |
| `adaptive_replace` | 상태 변경 | `workflow_id`, `expected_revision`, `key`, `state` |
| `adaptive_override_goal` | 상태 변경 | `workflow_id`, `expected_revision`, `key`, `state` |
| `turn_yield` | 상태 변경 | `expected_turn_revision`, `outcome`, `key` |

## 범위가 정해진 작업 위임과 평가

위임은 참여자에게 범위가 정해진 작업을 맡깁니다. 준비 결과는 spawn 의도이며 실제 실행 증거가 아닙니다. 독립 평가에는 검증된 역할, 정확한 평가 대상, 인증된 보고의 수용이 추가로 필요합니다. 소스·목표·의도·소유자·리비전이 바뀌면 이전 평가 보고를 재사용할 수 없을 수 있습니다. 평가 루프는 open/round/close 계약을 따릅니다.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `delegation_prepare` | 상태 변경 | `delegation_id`, `assignment`, `key` |
| `delegation_assign` | 상태 변경 | `workflow_id`, `delegation_id`, `assignment`, `target`, `key` |
| `evaluation_prepare` | 상태 변경 | `workflow_id`, `key`, `state` |
| `evaluation_read` | 조회 | `workflow_id`, `assignment` |
| `evaluation_execute` | 상태 변경 | `workflow_id`, `key`, `state`, `criterion_id`, `evidence_kind`, `pytest_node` |
| `evaluation_report` | 상태 변경 | `delegation_id`, `key`, `verdict`, `summary`, `outcome_ref` |
| `evaluation_consume` | 상태 변경 | `delegation_id`, `key` |
| `evaluation_loop_open` | 상태 변경 | `workflow_id`, `loop_id`, `goal`, `acceptance`, `key` |
| `evaluation_loop_read` | 조회 | `workflow_id`, `loop_id` |
| `evaluation_loop_round` | 상태 변경 | `workflow_id`, `loop_id`, `number`, `findings`, `key` |
| `evaluation_loop_close` | 상태 변경 | `workflow_id`, `loop_id`, `outcome`, `summary`, `key` |

## 리뷰를 요청하고 결과 수용

리뷰는 명시한 범위를 평가합니다. 리뷰어와 해당 커밋을 정해 시작하고 보고를 받은 뒤 정확한 결과를 수용합니다. 게시 시 현재 PR 커밋과 리뷰 범위를 확인하며, 리뷰 수용이 게시 권한을 자동으로 만들지는 않습니다. 필터 예시에서는 API 리뷰가 구현 및 저장·새로고침 회귀 검증과 함께 근거를 제공합니다.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `review_begin` | 상태 변경 | `workflow_id`, `to`, `kind`, `label`, `scope`, `key` |
| `review_report` | 상태 변경 | `workflow_id`, `delegation_id`, `verdict`, `summary`, `key` |
| `review_consume` | 상태 변경 | `workflow_id`, `delegation_id`, `outcome_ref`, `key` |
| `review_abort` | 상태 변경 | `workflow_id`, `delegation_id`, `outcome_ref`, `key` |
| `review_publish` | 상태 변경 | `workflow_id`, `repo`, `pr_number`, `key` |
| `review_comments` | 상태 변경 | `repo`, `pr_number` |

## 독립 제공자 세션 선택과 실행

실제 모델 목록을 확인하고 리비전이 있는 계획을 만든 다음 그 계획을 실행합니다. 모델 선택의 inherit와 실행 정책의 inherit는 다릅니다. target-native는 별도 명시적 선택이 필요하며 대상 설정을 유지합니다. 작업을 맡기기 전에 실제 모델·정책·활성화·도구·소유권을 확인합니다. status는 이벤트·실패 진단이며 완료를 반복 조회하는 용도가 아닙니다. [모델 계획](model-planning-mcp.md)과 [제공자 전송](provider-transports.md)을 참고하세요.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `provider_models` | 상태 변경 | `provider` |
| `provider_plan` | 상태 변경 | `provider`, `worktree`, `assignment`, `inventory_id`, `execution`, `selection`, `difficulty`, `confidence`, `rationale`, `key` |
| `provider_plan_read` | 조회 | `plan_id` |
| `provider_capabilities` | 조회 | `provider` |
| `provider_route` | 조회 | `provider`, `operation` |
| `provider_run` | 상태 변경 | `worktree`, `assignment` |
| `provider_status` | 조회 | `run_id` |
| `provider_cancel` | 상태 변경 | `run_id` |
| `provider_recover` | 상태 변경 | `run_id`, `key` |

## 인증된 동료 메시지 교환

정확한 수신자를 발견하고 승인된 범위에서 메시지를 보냅니다. ACK 전에 본문 전체를 읽습니다. 전송 접수·호스트 알림 제출·수신 확인·작업 수락·작업 완료는 별도 관찰입니다. 복구는 원래 메시지 ID를 유지하며 오래된 전송 세대가 새 ACK를 되돌릴 수 없습니다. [협업 계약](collaboration-contract.md)을 참고하세요.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `collaboration_register` | 상태 변경 | `name` |
| `collaboration_discover` | 조회 | 없음 |
| `collaboration_inbox` | 조회 | 없음 |
| `collaboration_send` | 상태 변경 | 없음 |
| `collaboration_reply` | 상태 변경 | `message_id`, `message`, `key` |
| `collaboration_message` | 조회 | `message_id` |
| `collaboration_ack` | 상태 변경 | 없음 |
| `collaboration_forward` | 조회 | `message_id` |
| `collaboration_submitted` | 상태 변경 | `message_id`, `transport` |
| `collaboration_assign` | 상태 변경 | `to`, `message`, `key` |
| `collaboration_accept` | 상태 변경 | `task_id` |
| `collaboration_report` | 상태 변경 | `task_id`, `state`, `key` |
| `collaboration_task` | 조회 | `task_id` |
| `collaboration_conversation` | 조회 | `conversation` |
| `collaboration_close` | 상태 변경 | `conversation` |
| `collaboration_subscribe` | 상태 변경 | `to` |
| `collaboration_unsubscribe` | 상태 변경 | `to` |
| `collaboration_publish` | 상태 변경 | `message`, `key` |
| `delivery_status` | 조회 | `message_id` |
| `delivery_redrive` | 상태 변경 | `message_id`, `expected_revision`, `repair_reference`, `key` |

## 프로젝트 발견 사항 공유

뉴스룸은 출처가 있는 프로젝트 참고 자료와 논의를 공유합니다. 제목을 보고 필요한 본문을 선택해 읽습니다. 글·댓글·열람 상태는 사용자 지시 권한, 소유권, 태스크 완료 승인을 만들지 않습니다.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `newsroom_headlines` | 조회 | 없음 |
| `newsroom_read` | 조회 | `article_id` |
| `newsroom_publish` | 상태 변경 | `title`, `body`, `key` |
| `newsroom_revise` | 상태 변경 | `article_id`, `revision`, `title`, `body`, `key` |
| `newsroom_comment` | 상태 변경 | `article_id`, `revision`, `body`, `key` |
| `newsroom_peers` | 조회 | 없음 |
| `newsroom_seen` | 상태 변경 | `event_id` |

## 근거·문맥·학습 지식 보존

artifact는 크기가 제한된 JSON 근거를, enclave는 변경 전 상태를 확인하는 최신 사실을, memory는 출처가 있는 기록을 보관합니다. 회상과 체크포인트는 참고 자료 또는 소유자 보고입니다. pull의 adopt는 원본 정지와 정확한 미리보기를 요구하는 별도 이전입니다. 학습은 같은 동작의 실패·복구와 등록 검증을 연결하고, 다른 세션에 실제 전달되어 재현과 검증에 성공해야 승격됩니다. 올바른 테스트 명령도 제안만으로는 부족하고 실제 관찰이 필요합니다. [메모리 참조](memory-reference.md)와 [제공자 연속성](provider-continuity.md)을 참고하세요.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `artifact_put` | 상태 변경 | `document`, `key` |
| `artifact_read` | 조회 | `reference` |
| `memory_recall` | 조회 | 없음 |
| `memory_checkpoint` | 상태 변경 | `summary`, `key` |
| `memory_pull` | 상태 변경 | 없음 |
| `enclave_read` | 조회 | 없음 |
| `enclave_set` | 상태 변경 | `fact_key`, `value`, `expected_digest`, `key` |
| `enclave_delete` | 상태 변경 | `fact_key`, `expected_digest`, `key` |
| `learning_status` | 조회 | 없음 |
| `learning_pending` | 조회 | 없음 |
| `learning_history` | 조회 | `strategy_id` |
| `learning_defer` | 상태 변경 | `reason`, `key` |

## 하네스 문제 진단과 복구

진단은 문제가 발생한 경계를 찾습니다. incident는 하네스 문제와 수정 또는 책임 있는 이관을 기록하며 상태 이름만으로 수정이 입증되지는 않습니다. 실제 재현·근본 원인·해당 회귀 근거를 남깁니다. 파일 배치·프로토콜 진단과 실제 호스트 활성화는 별도입니다. [검증](validation.md)을 참고하세요.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `diagnostics_integrity` | 조회 | 없음 |
| `diagnostics_project` | 상태 변경 | 없음 |
| `diagnostics_profile` | 조회 | 없음 |
| `diagnostics_continuation` | 조회 | 없음 |
| `incident_record` | 상태 변경 | `rule_id`, `symptom`, `key` |
| `incident_validate` | 조회 | 없음 |
| `incident_resolve` | 상태 변경 | `incident_id`, `root_cause`, `fixes`, `checks`, `key` |
| `incident_escalate` | 상태 변경 | `incident_id`, `summary`, `checks`, `key` |
| `incident_refresh` | 상태 변경 | `incident_ids`, `key` |
| `incident_supersede` | 상태 변경 | `incident_id`, `fixes`, `checks`, `key` |
| `process_evidence_record` | 상태 변경 | `workflow_id`, `field`, `value`, `key` |

## 승인된 진행 작업 관찰

모니터는 특정 관찰·재개 계약을 담당합니다. 실행 접수와 첫 실제 관찰은 다릅니다. 워크플로·PR 범위, 소유자 정책, 프로세스 세대를 유지합니다. 이벤트 ACK는 정확한 이벤트를 소비하고 external_wait는 리뷰어가 맡은 미해결 이벤트를 남기며 handoff는 검증된 자원을 종료하거나 이전합니다. 취소도 최종 결과 확인이 필요합니다.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `monitor_start` | 상태 변경 | `workflow_id`, `repo`, `pr_number`, `key` |
| `monitor_status` | 조회 | `run_id` |
| `monitor_cancel` | 상태 변경 | `run_id`, `key` |
| `monitor_recover` | 상태 변경 | `run_id`, `key` |
| `monitor_readback` | 조회 | `run_id` |
| `monitor_event` | 조회 | `workflow_id` |
| `monitor_ack` | 상태 변경 | `workflow_id`, `event_id`, `key` |
| `monitor_external_wait` | 상태 변경 | `workflow_id`, `event_id`, `key` |
| `monitor_handoff` | 상태 변경 | `workflow_id`, `pr_number`, `key` |

## 명시적인 설치·업데이트 선택 적용

계획은 대상·배포본과 정확한 변경 전후 상태를 묶습니다. 릴리스 확인은 고정된 공식 공개 릴리스 소스를 사용하며 자동 훅은 로컬 확인 시점 안내만 제공합니다. 업데이트 선택은 실제 사용자 응답과 변경 불가능한 준비 제안에 연결되어야 합니다. 적용 후 설치 결과를 검증해도 실제 다음 호스트 이벤트 전까지 새 활성화는 미관찰 상태입니다. [설치 설계](installation-design.md)와 [릴리스 참조](releases-reference.md)를 참고하세요.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `installation_plan` | 상태 변경 | `key` |
| `installation_apply` | 상태 변경 | `plan_ref`, `key` |
| `installation_recover` | 상태 변경 | `key` |
| `releases_status` | 조회 | 없음 |
| `releases_check` | 상태 변경 | `key` |
| `releases_notice` | 상태 변경 | `key` |
| `releases_prepare` | 상태 변경 | `offer_id`, `key` |
| `releases_choose` | 상태 변경 | `decision`, `user_choice_ref`, `key`, `offer_id` |
| `releases_apply` | 상태 변경 | `offer_id`, `key` |
| `releases_recover` | 상태 변경 | `key` |
| `maintenance_choice_read` | 조회 | `user_choice_ref` |
| `maintenance_choice_prepare` | 상태 변경 | `operation`, `key` |

## 검토한 공개 보고 준비

보고는 고정 업스트림 목적지와 내용에 연결된 비공개 초안을 사용합니다. 공통 결함·개선 보고에는 저장된 명시적 프로젝트 동의가, 기여에는 정확한 초안 승인이 필요합니다. 준비 전에 개인정보 검토를 수행합니다. 게시 결과가 불확실하면 다시 보내기 전에 기존 원격 결과와 대조합니다. 보고 실패가 원래 사용자 목표를 대체하지 않습니다. [보고 참조](reporting-reference.md)를 참고하세요.

| 도구 | 스키마상 효과 | 필수 인자 |
| --- | --- | --- |
| `reporting_status` | 조회 | 없음 |
| `reporting_list` | 조회 | 없음 |
| `reporting_read` | 조회 | `draft_id` |
| `reporting_prepare` | 상태 변경 | `report`, `privacy_reviewed`, `key` |
| `reporting_consent` | 상태 변경 | `decision`, `user_choice_ref`, `key` |
| `reporting_approve` | 상태 변경 | `decision`, `user_choice_ref`, `key`, `draft_id` |
| `reporting_submit` | 상태 변경 | `draft_id`, `key` |
| `reporting_reconcile` | 상태 변경 | `draft_id`, `url`, `key` |

## 반환된 결과에서 다음 단계 결정하기

준비된 작업은 실행 결과가 아니며 전송 접수는 수신 확인이 아닙니다. 종료 상태의 태스크도 항상 성공한 것은 아닙니다. 현재 결과와 `next_action`에 따라 다음 호출을 선택하고 정확한 참조·리비전·작업 키를 유지합니다. 소스 정의는 `src/neurath/runtime/task_schema.py`와 가져온 도메인 모듈에 있고, `src/neurath/agents/mcp.py`가 호스트 호출을 검증합니다. [기여 안내](index.md)에서 개발 절차와 이 참조 문서의 연결을 확인할 수 있습니다.
