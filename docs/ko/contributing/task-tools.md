# 공통 작업 실행

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

[English](../../en/contributing/task-tools.md) · **한국어**

[기여 안내](index.md) · [아키텍처](architecture.md) · [프로바이더 전송](provider-transports.md)

현재 소스의 `runtime/task_schema.py`와 도메인 모듈에는 **공개 도구 130개(내부 호환 작업 137개)**가 등록되어 있습니다.
등록만으로 기존 호스트가 모든 도구를 다시 로드했거나 설치된 실제 호스트에서 모든 경로가
통과했다는 뜻은 아닙니다. [모델 계획과 MCP 운용](model-planning-mcp.md),
[프로바이더 협업](collaboration-contract.md)이 요구 동작을 정의합니다.

에이전트는 명명된 MCP 도구로 하네스를 운용합니다. `runtime/tasks.py`는 구조화 입력을 기존
저장소·커널 서비스에 전달하며 에이전트가 CLI argv를 조립할 필요가 없습니다. 저장된 호출자와
기존 저장 호출과 내부 실행 기반을 위해 CLI 호환은 유지합니다. 일반 운용 경로는 아니며 범용
`agent(argv)` 통로만 제공하는 것으로 MCP 전환을 완료했다고 판단하지 않습니다.

## 소스에 등록된 도구

아래 표는 정확한 등록 이름을 묶은 목록입니다. 호출 전 현재 노출된 입력 스키마를 읽습니다.
같은 그룹의 모든 작업이 동일한 입력이나 권한을 요구하지는 않습니다.

| 기능 | 실제 명명 도구 |
| --- | --- |
| 작업 목록 | `task_define`, `task_list`, `task_resolve`, `task_start` |
| 하네스 바이패스 | `harness_bypass` |
| 세션 준비 상태 | `session_status` |
| 독립 실행 | `provider_cancel`, `provider_recover`, `provider_run`, `provider_status` |
| 프로바이더 탐색 | `provider_capabilities`, `provider_route` |
| 기억 | `memory_checkpoint`, `memory_recall` |
| 동료 통신 | `collaboration_ack`, `collaboration_close`, `collaboration_conversation`, `collaboration_discover`, `collaboration_forward`, `collaboration_inbox`, `collaboration_message`, `collaboration_publish`, `collaboration_register`, `collaboration_reply`, `collaboration_send`, `collaboration_submitted`, `collaboration_subscribe`, `collaboration_unsubscribe` |
| 배정 작업 수명 | `collaboration_accept`, `collaboration_assign`, `collaboration_report`, `collaboration_task` |
| 뉴스룸 | `newsroom_comment`, `newsroom_headlines`, `newsroom_peers`, `newsroom_publish`, `newsroom_read`, `newsroom_revise`, `newsroom_seen` |
| 상태·아티팩트·소유권 | `artifact_put`, `artifact_read`, `session_inspect`, `turn_inspect`, `worktree_claim`, `worktree_inspect`, `worktree_release` |
| 학습·릴리스·보고 | `learning_defer`, `learning_history`, `learning_pending`, `learning_status`, `maintenance_choice_prepare`, `maintenance_choice_read`, `releases_apply`, `releases_check`, `releases_choose`, `releases_notice`, `releases_prepare`, `releases_recover`, `releases_status`, `reporting_approve`, `reporting_consent`, `reporting_list`, `reporting_prepare`, `reporting_read`, `reporting_reconcile`, `reporting_status`, `reporting_submit` |
| 모델 계획 | `provider_models`, `provider_plan`, `provider_plan_read` |
| 단계·평가 | `adaptive_override_goal`, `adaptive_preflight`, `adaptive_read`, `adaptive_replace`, `delegation_assign`, `delegation_prepare`, `evaluation_consume`, `evaluation_execute`, `evaluation_prepare`, `evaluation_read`, `evaluation_report`, `phase_complete`, `phase_current`, `phase_evidence_prepare`, `phase_finalize`, `phase_start`, `workflow_advance`, `workflow_finalize`, `workflow_start` |
| 컨텍스트·보호 기억·평가 루프 | `diagnostics_integrity`, `diagnostics_profile`, `diagnostics_project`, `enclave_delete`, `enclave_read`, `enclave_set`, `evaluation_loop_close`, `evaluation_loop_open`, `evaluation_loop_read`, `evaluation_loop_round`, `turn_yield` |
| 검증·사고·리뷰 | `diagnostics_continuation`, `incident_escalate`, `incident_record`, `incident_refresh`, `incident_resolve`, `incident_supersede`, `incident_validate`, `review_abort`, `review_begin`, `review_comments`, `review_consume`, `review_publish`, `review_report` |
| 설치 관리 | `installation_apply`, `installation_plan`, `installation_recover` |
| 작업 증거·정리 | `process_evidence_record`, `worktree_cleanup`, `worktree_isolation` |
| PR 감시 | `monitor_ack`, `monitor_cancel`, `monitor_event`, `monitor_external_wait`, `monitor_handoff`, `monitor_readback`, `monitor_recover`, `monitor_start`, `monitor_status` |
| 전달 복구 | `delivery_redrive`, `delivery_status` |

## 일반 작업

`session_status`로 설치·네이티브 활성화·현재 정책·소유권을 한 번 확인하고 현재 worktree를
정상 claim합니다. `task_define`, `task_start`, `task_resolve`로 작업을 기록하며 응답의 ID와
revision을 재사용합니다. 완료는 소유자가 terminal 상태·요약·근거를 한 번 보고하는 방식입니다.
루트 턴을 닫는 트랜잭션에서 최신 작업 목록을 검사합니다. 네이티브 TODO 표시는 별도 완료 gate가 아닙니다.

파일 편집과 프로젝트 검사는 호스트 도구로 수행합니다. material 배치, 검증 부채, 반복 acceptance
JSON, 학습과 체크포인트는 추가 완료 조건이 아닙니다. 기존 workflow·평가 도구는 명시적인
워크플로 실행과 저장된 기록 복구에 사용합니다. task를 종결하기 위해 새 workflow를 만들지 않습니다.
[작업 목록과 세션 완료](task-todo-contract.md)를 참고하세요.

## 바이패스

`harness_bypass`는 `enabled=true`로 켜고 `false`로 끄며, 생략 또는 null로 상태를 조회합니다.
설정된 worktree의 Neurath 훅만 중지하고, 끄면 정상 훅 처리를 복구합니다. 호스트 권한과 사용자
지시는 그대로 적용합니다. 스위치는 native binding이나 실행 worker 슬롯 없이 동작하므로
다시 끄는 작업도 일반 작업 대기에 막히지 않습니다. 다른 MCP 도구는 실제 native binding이
필요합니다. 바이패스 중 시작한 세션은 끈 뒤 정상 네이티브 활성화를 확인해야 합니다.

## 호출과 응답 줄이기

MCP 응답 데이터는 `structuredContent`에 한 번 전달하고 텍스트에는 짧은 상태 요약을 둡니다.
작업 변경 응답은 ID·revision·상태·네이티브 TODO 지시만 포함하고 재시도 장부는 저장소에 둡니다.
전체 목록이 필요할 때 `task_list`를 사용하며 성공한 변경을 다시 확인하기 위해 반복 조회하지 않습니다.

이미 받은 메시지 본문을 재조회하지 않습니다. `collaboration_reply`는 수신 확인과 답장을 한 번에
처리합니다. inbox에서 읽은 메시지는 `collaboration_ack.message_ids`로 묶어 확인하고,
여러 메시지는 `collaboration_send.messages`로 보냅니다. 대기열 접수·수신 확인·결과 검토는
서로 다른 사실입니다. idle 동료를 폴링하거나 별도 수신 세션을 만들지 않습니다.

자동 기억 주입은 SessionStart에서만 최대 3 KB로 제한합니다. 이후 프롬프트의 이력은 보존하되
과거 패치와 도구 결과를 매번 다시 주입하지 않습니다.

## 설치와 호환성

소스 등록·설치·현재 MCP에 로드된 도구·실제 네이티브 실행은 별도로 확인합니다.
새 불변 런타임을 설치해도 기존 MCP 프로세스는 교체되지 않습니다. 공유 저장소 전환 전에
기존 writer를 종료하고 소스를 설치한 뒤 호스트 연결을 다시 로드하여 실제 도구와 훅을 확인합니다.
설치된 불변 런타임을 직접 수정하거나 native binding을 만들지 않습니다.

`material_*`, `verification_*`, 기존 `agent(argv)` 통로는 공개 목록에서 제외한 내부 호환
인터페이스입니다. 일반 편집과 검사에 준비·종결 왕복을 요구하지 않습니다. 공개 작업의
소유권·네이티브 신원·revision과 호스트 권한 정책은 유지됩니다.
