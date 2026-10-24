# 기존 기능의 배치와 대체 경로

[공개 목록](interfaces.md) · [명세](specification.md) · [요구사항 검증](acceptance.md) · [English](../en/capability-continuity.md)

이 표의 128개 작업과 33개 스킬은 **과거 기능의 감사 목록**입니다. 새 공개 목록은 스킬 14개와 실제 기능별 CLI입니다. 기능의 목적과 B 결과 계약은 유지하되 옛 이름·개수·노출 방식은 유지하지 않습니다. 기준은 Git `e4bcc85`의 기능 문서, 이후 이름, 현재 사용자 정정입니다. 기존 코드의 복제 지침이 아닙니다.

## 1. 과거 작업 128개의 목적지

| 이전 이름 | 새 경로 | 노출 | 이유 | 결과 계약 |
| --- | --- | --- | --- | --- |
| `harness_bypass` | maintenance CLI | internal/config/CLI | CLI/런타임 장애 때도 필요한 관리 CLI 복구 경로 | B01 |
| `session_status` | context show | CLI | 동일 현재 실행의 조회 중복 통합 | B02 |
| `session_inspect` | context show | CLI | 동일 현재 실행의 조회 중복 통합 | B02 |
| `turn_inspect` | context show | CLI | 동일 현재 실행의 조회 중복 통합 | B02 |
| `worktree_inspect` | context show | CLI | 동일 현재 실행의 조회 중복 통합 | B02 |
| `worktree_claim` | runtime writer lifecycle | internal | 실제 작성 시작/종료에서 조정·해제; 모델이 임대 토큰을 수작업으로 조립하지 않음 | B03 |
| `worktree_release` | runtime writer lifecycle | internal | 실제 작성 시작/종료에서 조정·해제; 모델이 임대 토큰을 수작업으로 조립하지 않음 | B03 |
| `worktree_isolation` | host worktree / Git / filesystem | host | 체크아웃 생성·보존·정리는 호스트 도구; 충돌 조정만 Neurath 내부 | B03 |
| `worktree_cleanup` | host worktree / Git / filesystem | host | 체크아웃 생성·보존·정리는 호스트 도구; 충돌 조정만 Neurath 내부 | B03 |
| `task_define` | task create | CLI | 원문과 작업 정의 | B04 |
| `task_list` | context show | CLI | 작업과 배정을 같은 원장에서 조회 | B04 |
| `task_start` | task update | CLI | 작업 시작/배정 수락 등 역할별 전이 통합 | B04 |
| `task_resolve` | task report | CLI | 현재 작업/단계 결과 평가에 검토 수용 포함; 별도 완료 투표 제거 | B04 |
| `phase_start` | workflow start | CLI | 선택 절차 또는 검토 반복을 같은 run으로 시작 | B05 |
| `phase_current` | context show | CLI | 절차/시도/조건/반복 이력 통합 조회 | B05 |
| `phase_evidence_prepare` | workflow validation and evidence binding | internal | 실행 전 입력 검증과 결과 연결은 runner 책임 | B05 |
| `phase_complete` | task report | CLI | 실제 단계/회차 결과를 현재 시도에 반영 | B05 |
| `phase_finalize` | workflow finalization | internal | 마지막 결과 반영과 종결을 함께 처리 | B05 |
| `adaptive_read` | context show | CLI | 절차/시도/조건/반복 이력 통합 조회 | B06 |
| `adaptive_preflight` | workflow validation and evidence binding | internal | 실행 전 입력 검증과 결과 연결은 runner 책임 | B06 |
| `adaptive_replace` | workflow revise | CLI | 방법/범위 정정 경로 통합; 원문 변경 권한은 없음 | B06 |
| `adaptive_override_goal` | workflow revise | CLI | 방법/범위 정정 경로 통합; 원문 변경 권한은 없음 | B06 |
| `turn_yield` | host turn lifecycle / Stop | internal | 모델이 종료 예외 도구로 허가를 발급하지 않음 | B06 |
| `delegation_prepare` | assignment validation | internal | 배정 호출에서 대상/범위/검토 조건 검증 | B07 |
| `delegation_assign` | collaboration delegate | CLI | 실제 작업/검토 배정 통합 | B07 |
| `evaluation_prepare` | assignment validation | internal | 배정 호출에서 대상/범위/검토 조건 검증 | B08 |
| `evaluation_read` | context show | CLI | 절차/시도/조건/반복 이력 통합 조회 | B08 |
| `evaluation_execute` | host execution tools | host | 검사는 실제 호스트 실행; Neurath는 시도/결과 관찰 | B08 |
| `evaluation_report` | task report | CLI | 수행자/검토자의 출처 있는 결과 보고 | B08 |
| `evaluation_consume` | task report | CLI | 현재 작업/단계 결과 평가에 검토 수용 포함; 별도 완료 투표 제거 | B08 |
| `evaluation_loop_open` | workflow start | CLI | 선택 절차 또는 검토 반복을 같은 run으로 시작 | B09 |
| `evaluation_loop_read` | context show | CLI | 절차/시도/조건/반복 이력 통합 조회 | B09 |
| `evaluation_loop_round` | task report | CLI | 실제 단계/회차 결과를 현재 시도에 반영 | B09 |
| `evaluation_loop_close` | workflow finalization | internal | 마지막 결과 반영과 종결을 함께 처리 | B09 |
| `review_begin` | collaboration delegate | CLI | 실제 작업/검토 배정 통합 | B10 |
| `review_report` | task report | CLI | 수행자/검토자의 출처 있는 결과 보고 | B10 |
| `review_consume` | task report | CLI | 현재 작업/단계 결과 평가에 검토 수용 포함; 별도 완료 투표 제거 | B10 |
| `review_abort` | task update | CLI | 배정 취소로 처리하고 결과/이력 보존 | B10 |
| `review_publish` | host GitHub / review tools | host | 원격 리뷰/댓글의 게시·조회는 제공 도구 사용 | B10 |
| `review_comments` | host GitHub / review tools | host | 원격 리뷰/댓글의 게시·조회는 제공 도구 사용 | B10 |
| `provider_models` | context show | CLI | 모델/지원 정책을 한 조회에서 반환 | B11 |
| `provider_plan` | provider validation and routing | internal | collaboration delegate 전에 필요한 설정/경로를 검증·보존; 준비를 실행으로 표시하지 않음 | B11 |
| `provider_plan_read` | context show | CLI | 고정 계획과 실제 실행 상태를 함께 조회 | B11 |
| `provider_capabilities` | context show | CLI | 모델/지원 정책을 한 조회에서 반환 | B11 |
| `provider_route` | provider validation and routing | internal | collaboration delegate 전에 필요한 설정/경로를 검증·보존; 준비를 실행으로 표시하지 않음 | B11 |
| `provider_run` | collaboration delegate | CLI | 지원 제공자의 실제 실행에 필요한 진입점 | B12 |
| `provider_status` | context show | CLI | 고정 계획과 실제 실행 상태를 함께 조회 | B12 |
| `provider_cancel` | task update | CLI | 대상 실행의 실제 중단 제어 | B12 |
| `provider_recover` | provider recovery | internal | 재연결 시 원 run 대조; 명시적 수리는 session resume | B12 |
| `collaboration_register` | peer connection lifecycle | internal | 실제 연결의 주소/신원으로 등록·갱신 | B13 |
| `collaboration_discover` | context show | CLI | 피어 목록의 중복 제거 | B13 |
| `collaboration_inbox` | context show | CLI | 메시지·대화·실제 전달 상태 통합 조회 | B13 |
| `collaboration_send` | collaboration send | CLI | 수신자/구독자/답장 참조만 다른 동일 전달 동작 | B14 |
| `collaboration_reply` | collaboration send | CLI | 수신자/구독자/답장 참조만 다른 동일 전달 동작 | B13 |
| `collaboration_message` | collaboration read | CLI | 선택한 실제 본문 읽기 | B13 |
| `collaboration_ack` | message transport and receipt | internal | 읽기/전송 결과가 수신 기록 생성; 유한한 실제 실패 복구를 어댑터가 수행 | B13 |
| `collaboration_forward` | message transport and receipt | internal | 읽기/전송 결과가 수신 기록 생성; 유한한 실제 실패 복구를 어댑터가 수행 | B14 |
| `collaboration_submitted` | message transport and receipt | internal | 읽기/전송 결과가 수신 기록 생성; 유한한 실제 실패 복구를 어댑터가 수행 | B14 |
| `collaboration_assign` | collaboration delegate | CLI | 실제 작업/검토 배정 통합 | B15 |
| `collaboration_accept` | task update | CLI | 작업 시작/배정 수락 등 역할별 전이 통합 | B15 |
| `collaboration_report` | task report | CLI | 수행자/검토자의 출처 있는 결과 보고 | B15 |
| `collaboration_task` | context show | CLI | 작업과 배정을 같은 원장에서 조회 | B15 |
| `collaboration_conversation` | context show | CLI | 메시지·대화·실제 전달 상태 통합 조회 | B16 |
| `collaboration_close` | project notification settings / lifecycle | internal/config/CLI | 호스트 도구로 관리하는 프로젝트 알림 설정과 내부 수명주기 | B16 |
| `collaboration_subscribe` | project notification settings | internal/config/CLI | 호스트 도구로 관리하는 프로젝트 알림 설정과 내부 수명주기 | B16 |
| `collaboration_unsubscribe` | project notification settings | internal/config/CLI | 호스트 도구로 관리하는 프로젝트 알림 설정과 내부 수명주기 | B16 |
| `collaboration_publish` | collaboration send | CLI | 수신자/구독자/답장 참조만 다른 동일 전달 동작 | B16 |
| `delivery_status` | context show | CLI | 메시지·대화·실제 전달 상태 통합 조회 | B14 |
| `delivery_redrive` | message transport and receipt | internal | 읽기/전송 결과가 수신 기록 생성; 유한한 실제 실패 복구를 어댑터가 수행 | B14 |
| `newsroom_headlines` | newsroom list | CLI | 제목/개정 목록 조회 | B17 |
| `newsroom_read` | newsroom read | CLI | 본문/댓글 조회 | B17 |
| `newsroom_publish` | newsroom publish | CLI | 기사 게시 | B17 |
| `newsroom_revise` | newsroom revise | CLI | 개정 확인 후 수정 | B17 |
| `newsroom_comment` | newsroom comment | CLI | 기사 개정에 댓글 | B17 |
| `newsroom_peers` | context show | CLI | 피어 목록의 중복 제거 | B17 |
| `newsroom_seen` | article read receipt | internal | 실제 전체 읽기 결과로 기록; 에이전트 자기 신고 제거 | B17 |
| `artifact_put` | host artifact tools + internal reference ingestion | host+internal | 파일 저장을 중복 구현하지 않고 결과 보고/체크포인트에 참조 보존 | B18 |
| `artifact_read` | memory read / host artifact tools | CLI+host | Neurath 기록 참조는 memory read, 원 파일은 호스트 읽기 | B18 |
| `memory_recall` | memory search / memory read | CLI | 관련 이력/교훈을 유형·상태로 검색 후 상세 조회 | B18 |
| `memory_checkpoint` | memory checkpoint | CLI | 보고 저장 하나에 스킬 불필요 | B18 |
| `memory_pull` | memory search / memory read / session preview / session resume | CLI | 발견·미리보기와 실제 인수의 효과 분리 | B18 |
| `enclave_read` | context show | CLI | 현재 사실의 명확한 읽기/수정/삭제 | B19 |
| `enclave_set` | memory update | CLI | 현재 사실의 명확한 읽기/수정/삭제 | B19 |
| `enclave_delete` | memory update | CLI | 현재 사실의 명확한 읽기/수정/삭제 | B19 |
| `learning_status` | memory search / memory read | CLI | 관련 이력/교훈을 유형·상태로 검색 후 상세 조회 | B20 |
| `learning_pending` | memory search / memory read | CLI | 관련 이력/교훈을 유형·상태로 검색 후 상세 조회 | B20 |
| `learning_history` | memory search / memory read | CLI | 관련 이력/교훈을 유형·상태로 검색 후 상세 조회 | B20 |
| `learning_defer` | reflection / versioned lesson source | internal/config/CLI | 출처 있는 교훈 자료와 회고 수명주기에 보류/철회 반영 | B20 |
| `diagnostics_integrity` | context show / maintenance CLI | CLI | 하네스 진단의 입력 범위만 구분 | B21 |
| `diagnostics_project` | context show / maintenance CLI | CLI | 하네스 진단의 입력 범위만 구분 | B21 |
| `diagnostics_profile` | context show / maintenance CLI | CLI | 하네스 진단의 입력 범위만 구분 | B21 |
| `diagnostics_continuation` | context show / maintenance CLI | CLI | 하네스 진단의 입력 범위만 구분 | B21 |
| `incident_record` | incident / observation lifecycle | internal | 실제 장애·실행·복구 사건으로 기록; 임의 정상화 도구 제거 | B22 |
| `incident_validate` | context show / maintenance CLI | CLI | 하네스 진단의 입력 범위만 구분 | B22 |
| `incident_resolve` | incident / observation lifecycle | internal | 실제 장애·실행·복구 사건으로 기록; 임의 정상화 도구 제거 | B22 |
| `incident_escalate` | incident / observation lifecycle | internal | 실제 장애·실행·복구 사건으로 기록; 임의 정상화 도구 제거 | B22 |
| `incident_refresh` | incident / observation lifecycle | internal | 실제 장애·실행·복구 사건으로 기록; 임의 정상화 도구 제거 | B22 |
| `incident_supersede` | incident / observation lifecycle | internal | 실제 장애·실행·복구 사건으로 기록; 임의 정상화 도구 제거 | B22 |
| `process_evidence_record` | incident / observation lifecycle | internal | 실제 장애·실행·복구 사건으로 기록; 임의 정상화 도구 제거 | B22 |
| `monitor_start` | task dependency lifecycle | internal/config/CLI | 실제 요청된 작업의 외부 의존성에서 내부 감시 시작 | B23 |
| `monitor_status` | context show | CLI | 감시/사건/실제 상태 통합 조회 | B23 |
| `monitor_cancel` | task update | CLI | 감시 종료 의도 | B23 |
| `monitor_recover` | monitor lifecycle | internal | 사건 소비·대기·재개/인계는 실제 작업/호스트 사건에서 처리 | B23 |
| `monitor_readback` | context show | CLI | 감시/사건/실제 상태 통합 조회 | B23 |
| `monitor_event` | context show | CLI | 감시/사건/실제 상태 통합 조회 | B24 |
| `monitor_ack` | monitor lifecycle | internal | 사건 소비·대기·재개/인계는 실제 작업/호스트 사건에서 처리 | B24 |
| `monitor_external_wait` | monitor lifecycle | internal | 사건 소비·대기·재개/인계는 실제 작업/호스트 사건에서 처리 | B24 |
| `monitor_handoff` | monitor lifecycle | internal | 사건 소비·대기·재개/인계는 실제 작업/호스트 사건에서 처리 | B24 |
| `installation_plan` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B25 |
| `installation_apply` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B25 |
| `installation_recover` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B25 |
| `releases_status` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `releases_check` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `releases_notice` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `releases_prepare` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `releases_choose` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `releases_apply` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `releases_recover` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `maintenance_choice_read` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `maintenance_choice_prepare` | maintenance CLI + update-neurath / session resume | CLI+skill | 자신을 교체/복구하는 경로는 CLI 밖에서도 작동; 추가 승인 객체 API 제거 | B26 |
| `reporting_status` | host artifact / GitHub tools | host | 일반 초안/외부 제출은 기존 도구와 실제 사용자 권한 사용; Neurath 전용 게시/승인 원장 불필요 | B27 |
| `reporting_list` | host artifact / GitHub tools | host | 일반 초안/외부 제출은 기존 도구와 실제 사용자 권한 사용; Neurath 전용 게시/승인 원장 불필요 | B27 |
| `reporting_read` | host artifact / GitHub tools | host | 일반 초안/외부 제출은 기존 도구와 실제 사용자 권한 사용; Neurath 전용 게시/승인 원장 불필요 | B27 |
| `reporting_prepare` | host artifact / GitHub tools | host | 일반 초안/외부 제출은 기존 도구와 실제 사용자 권한 사용; Neurath 전용 게시/승인 원장 불필요 | B27 |
| `reporting_consent` | host artifact / GitHub tools | host | 일반 초안/외부 제출은 기존 도구와 실제 사용자 권한 사용; Neurath 전용 게시/승인 원장 불필요 | B27 |
| `reporting_approve` | host artifact / GitHub tools | host | 일반 초안/외부 제출은 기존 도구와 실제 사용자 권한 사용; Neurath 전용 게시/승인 원장 불필요 | B27 |
| `reporting_submit` | host artifact / GitHub tools | host | 일반 초안/외부 제출은 기존 도구와 실제 사용자 권한 사용; Neurath 전용 게시/승인 원장 불필요 | B27 |
| `reporting_reconcile` | host artifact / GitHub tools | host | 일반 초안/외부 제출은 기존 도구와 실제 사용자 권한 사용; Neurath 전용 게시/승인 원장 불필요 | B27 |

## 2. 과거 스킬 33개의 목적지

| 이전 스킬 | 결정 | 새 경로 | 이유 | 보존할 결과 |
| --- | --- | --- | --- | --- |
| `review-spec` | skill | review-spec | 판단·검증을 포함하는 재사용 가능한 절차 | 각 항목의 요구·설계·구현의 모순/누락과 근거 위치를 보고하며 구현 전 감사는 구현 합격이라고 하지 않는다. |
| `qa` | skill | qa | 판단·검증을 포함하는 재사용 가능한 절차 | 지정한 사용자 시나리오의 UI/API/저장 결과를 실제 재현하고 실패/미검증을 구분한다. |
| `autopilot` | skill | autopilot | 판단·검증을 포함하는 재사용 가능한 절차 | 요청된 이슈와 의존 작업을 실제 완료하고 범위 밖 이슈를 자동 추가하지 않는다. |
| `checkpoint` | CLI | memory checkpoint | 보고 저장 한 번에 별도 스킬 불필요 | 원문·현재 결과·남은 일·다음 행동을 재개 가능한 보고로 보존한다. |
| `commit` | host/project | host tools / selected project skill | 일반 에이전트 작업 또는 프로젝트별 전문 절차; Neurath 기본 스킬로 설치하지 않음 | 변경 diff와 검사 결과를 대조해 승인 범위 파일만 커밋하고 실제 SHA를 확인한다. |
| `create-pr` | host/project | host tools / selected project skill | 일반 에이전트 작업 또는 프로젝트별 전문 절차; Neurath 기본 스킬로 설치하지 않음 | 현재 브랜치·변경·검증을 반영한 PR을 요청 범위로 생성하고 원격 ID/본문을 확인한다. |
| `create-issue` | host/project | host tools / selected project skill | 일반 에이전트 작업 또는 프로젝트별 전문 절차; Neurath 기본 스킬로 설치하지 않음 | 원 요구와 수락 조건·의존 관계를 보존한 이슈를 만들고 게시 결과를 확인한다. |
| `create-worktree` | host/project | host tools / selected project skill | 일반 에이전트 작업 또는 프로젝트별 전문 절차; Neurath 기본 스킬로 설치하지 않음 | 지정 Git 상태에서 분리 체크아웃을 만들고 원 작업/미커밋 파일을 보존한다. |
| `audit-deps` | external/project | project dependency tooling / selected specialist skill | 프로젝트/전문 도구의 역할이며 Neurath 기본 제공에서 제외 | 실제 manifest/lock과 조사 근거로 의존성 위험·라이선스·업데이트 후보를 보고하며 자동 갱신하지 않는다. |
| `test-harness` | internal/development | harness tests and internal improvement validation | Neurath 개발 또는 사용자가 요청한 회고 안에서 검증·개선 수행; 기본 사용자 스킬 아님 | 지정 시나리오의 실제 이벤트·판정·실패를 기록하고 fixture/네이티브 검증을 구분한다. |
| `explain-code` | host/project | host tools / selected project skill | 일반 에이전트 작업 또는 프로젝트별 전문 절차; Neurath 기본 스킬로 설치하지 않음 | 실제 코드 경로와 출처로 동작을 설명하고 근거 없는 동작을 단정하지 않는다. |
| `design-ui` | skill | design-ui | 판단·검증을 포함하는 재사용 가능한 절차 | 사용자가 선택할 방향과 동작을 제안하되 제안을 채택된 디자인으로 간주하지 않는다. |
| `finish-session` | skill | finish-session | 판단·검증을 포함하는 재사용 가능한 절차 | 남은 요구/절차/검사와 범위 내 Git·그래프·인계·소유권 정리를 실제 확인하고 미완료를 보고한다. |
| `graphify` | external | existing Graphify skill / CLI | 전용 도구의 절차를 Neurath에서 복제하지 않음 | 요청된 소스·문서 관계를 조회/갱신하고 의미 관계 손실 여부를 확인한다. |
| `implement-ui` | merge | implement-spec | 같은 구현 절차 안에서 UI 참조와 화면/상호작용 검증 적용 | 선택된 방향의 실제 화면·상호작용을 구현/검증하며 다른 디자인으로 바꾸지 않는다. |
| `debug` | skill | debug | 판단·검증을 포함하는 재사용 가능한 절차 | 관찰한 실패를 재현하고 원인·수정·회귀 결과를 연결한다. |
| `watch-pr` | CLI | task dependency lifecycle / context show / task update | 감시 등록은 도구, 대기/재개는 런타임 | 지정 PR의 의미 있는 변화만 알리고 취소·완료 후 감시를 정리한다. |
| `optimize-harness` | internal/development | internal reflection and improvement evaluation | Neurath 개발 또는 사용자가 요청한 회고 안에서 검증·개선 수행; 기본 사용자 스킬 아님 | 관찰된 문제에 대한 개선의 효과와 정상 대조/비용을 비교하고 악화 시 철회한다. |
| `plan` | merge | define-spec | 실행 계획을 명세 정의에 통합; 별도 스킬 단계 불필요 | 실행 가능한 범위·순서·의존·검증을 정리하고 계획을 실행 완료라고 하지 않는다. |
| `review-pr` | merge | review-code | PR은 코드 검토 대상의 한 형태이므로 review-code로 통합 | 정확한 PR HEAD/요구에 대한 조치 가능한 결함을 보고하고 stale 검토를 통과시키지 않는다. |
| `implement-issue` | merge | implement-spec | 명세·요청을 구현하며 이슈 생성 불필요 | 이슈의 요구를 구현하고 관련 검증·실제 산출물로 수락 조건을 대조한다. |
| `memory-to-rules` | internal+host | learning lifecycle / host file editing | Neurath 개발 또는 사용자가 요청한 회고 안에서 검증·개선 수행; 기본 사용자 스킬 아님 | 검증된 교훈의 관련 규칙 변경을 제안/적용하며 기존 사용자 지시를 바꾸지 않는다. |
| `review-code` | skill | review-code | 판단·검증을 포함하는 재사용 가능한 절차 | 지정 변경의 실제 결함과 위치·영향을 보고하고 일반 취향을 필수 요구로 만들지 않는다. |
| `review-ui` | skill | review-ui | 판단·검증을 포함하는 재사용 가능한 절차 | 실제 화면·상호작용을 지정 기준과 대조하고 캡처만으로 동작 성공을 단정하지 않는다. |
| `sync-design` | skill | sync-design | 판단·검증을 포함하는 재사용 가능한 절차 | 선택 디자인과 구현의 차이를 찾아 해당 범위만 동기화한다. |
| `dev-docs` | merge | sync-docs | 독자별 지침을 문서 절차 안에 유지 | 실제 개발·확장·검증 경로에 맞는 기여자 문서를 작성하고 예제/링크를 확인한다. |
| `sync-docs` | skill | sync-docs | 판단·검증을 포함하는 재사용 가능한 절차 | 같은 사실의 언어/관련 페이지를 함께 맞추고 사실 차이나 오래된 지침을 남기지 않는다. |
| `user-docs` | merge | sync-docs | 독자별 지침을 문서 절차 안에 유지 | 사용자 목적·사용 경로·실제 제한을 설명하고 미지원 동작을 지원한다고 쓰지 않는다. |
| `pr-feedback` | skill | pr-feedback | 판단·검증을 포함하는 재사용 가능한 절차 | 피드백을 현재 변경에 대조해 타당한 수정·검증·답변을 하고 무관한 요구는 분리한다. |
| `update-deps` | external/project | project dependency tooling / selected specialist skill | 프로젝트/전문 도구의 역할이며 Neurath 기본 제공에서 제외 | 요청 범위 manifest/lock 갱신과 호환 검사·회귀 결과를 확인한다. |
| `update-status` | host/project | host tools / selected project skill | 일반 에이전트 작업 또는 프로젝트별 전문 절차; Neurath 기본 스킬로 설치하지 않음 | 실제 근거의 진행/미완료를 상태 문서에 반영하며 완료를 부풀리지 않는다. |
| `update-neurath` | skill | update-neurath | 판단·검증을 포함하는 재사용 가능한 절차 | 요청 배포본과 설치·DB 보존·실제 새 연결의 동작을 확인하고 이전 실패를 감추지 않는다. |
| `reconnect-host` | CLI/internal | session resume / runtime recovery; maintenance CLI when CLI is unavailable | 기존 resume_session과 런타임 복구; CLI/런타임 장애 시 관리 CLI | 공식 경로로 실제 연결을 복구하고 원 작업을 이어가며 다른 프로세스 실행을 기존 연결이라고 하지 않는다. |

## 3. 기능별로 실제 관찰할 결과

B 항목은 위 작업들의 결과 계약입니다. 요구사항 검증 A39에서 각 기능을 맡은 새 실행 경로로 이 결과를 관찰해야 하며 그룹 이름이나 공통 시험의 통과로 대체하지 않습니다. 새 승인 절차가 아닙니다.

| ID | 결과 기준 |
| --- | --- |
| B01 | 조회는 상태 불변; 우회는 하네스 차단만 해제하고 복원 후 실제 차단 경로를 재검증한다. 호스트 권한은 바뀌지 않는다. |
| B02 | 각 조회는 실제 대상·실행/연결/작성 상태와 불확실성을 반환하고 소유권 취득이나 모델 실행을 만들지 않는다. |
| B03 | 동시 claim 한 작성자만 유효; 옛 세대 release는 현재 임대를 해제하지 않는다. isolation은 지정 관계를 확인한다. cleanup은 미병합 커밋·dirty·untracked·필요 ignored 자료를 보존하고 복원 확인 없이는 제거하지 않는다. |
| B04 | 정의와 시작은 원문·현재 개정에 대응하며 전체 목록/TODO가 같다. resolve는 실제 결과·미완료 후속을 보존하고 stale 결과로 새 요구를 닫지 않는다. |
| B05 | 시작은 선택 정의를 고정; current는 수행 조건 반환; 근거 준비는 실행 결과가 아님; 현재 attempt의 조건 확인 뒤 단계 진행과 run 종결을 중복 없이 반영한다. |
| B06 | 조회/사전 확인은 실행이나 범위 변경이 아니다. 방법 변경은 이전 상태와 이유를 보존하고 목표 변경은 실제 사용자 정정에 대응한다. yield는 완료/대기/중단의 실제 이유를 보존한다. |
| B07 | 준비와 실제 배정을 구분하고 정확한 수신자·요청 개정·범위를 연결한다. 정정/취소의 전파와 미확인 전달을 표시한다. |
| B08 | 조건·대상·역할을 조회하고 실제 평가를 실행한다. report는 해당 후보 결과이며 consume은 현재 후보와 대조한다. 실패·오래된 평가로 통과시키지 않는다. |
| B09 | 원래 목표와 수용 기준으로 루프를 열고 각 회차 수정·결함·결과를 누적한다. read는 실행을 만들지 않고 close는 해결/미해결을 구분하며 무진전에는 유한하게 중지한다. |
| B10 | 검토 대상·담당자·범위를 고정하고 결과 수용과 게시를 분리한다. 중단은 통과가 아니며 현재 PR에 맞는 결과/댓글만 허용된 범위로 게시·조회한다. |
| B11 | 실제 모델·기능·경로를 확인하고 모델/정책이 명시된 계획을 저장·조회한다. 미지원 경로를 성공으로 대체하거나 조회로 실행하지 않는다. |
| B12 | 확인한 계획대로 실제 실행; status는 접수와 수행 결과 구분; cancel은 중단 확인; recover는 기존 실행을 대조해 중복 시작과 취소 후 부활을 막는다. |
| B13 | 실제 피어 주소와 발신자 보존; inbox 요약과 본문 조회 구분; 답장은 원 대화에 연결; ACK는 읽은 메시지에만 대응하며 작업 수락/완료가 아니다. |
| B14 | 원 메시지와 수신자에 대한 전달 자료를 읽고 제출 결과를 기록한다. 상태 조회는 재전송하지 않으며 redrive는 같은 메시지/확인된 실패를 복구하고 늦은 전송이 새 ACK를 퇴행시키지 않는다. |
| B15 | 배정·수락·진행·완료를 구분한다. 수신자는 재차 인간 입력 없이 받은 범위를 수행하고 task 조회는 현재 요청 개정의 결과와 남은 일을 보여준다. |
| B16 | 대화 조회/종료는 자료나 미완료 작업을 삭제하지 않는다. 구독/해제 후 발행 대상이 실제로 바뀌며 무관한 피어를 깨우지 않는다. |
| B17 | 제목/본문 선택 조회, 활성 피어만 알림; 개정 충돌 거절과 이전 본문 보존; 댓글은 읽은 개정 연결; peers는 실제 활성 상태, seen은 해당 사건 열람만 표시하고 새 개정의 열람을 대신하지 않는다. |
| B18 | artifact 왕복 시 내용/출처/크기 제한 유지; recall은 관련 이력; checkpoint는 보고; pull 미리보기는 소유권 불변, 인수는 원 작성 정지와 실제 작업 재개 확인을 포함한다. |
| B19 | set/read/delete는 같은 현재 사실과 개정을 사용한다. stale set/delete 거절; 삭제 이력 보존, 원 사용자 요구나 관련 태스크가 삭제되지는 않는다. 큰 자료는 조회 가능한 참조로 보존한다. |
| B20 | 새 교훈 생성·적용은 사용자가 요청한 회고에서 수행한다. 현재 적용/대기/과거 효과를 구분해 조회한다. defer는 이유와 미적용 상태를 보존하고 성공으로 승격하지 않는다. 뒤의 실패는 해당 교훈 철회에 반영한다. |
| B21 | 무결성·프로젝트 연결·설정·재개 경계를 각각 진단해 재현 가능한 원인을 반환한다. 자료 없음/실패를 정상 빈 상태로 표시하거나 진단으로 설정을 덮어쓰지 않는다. |
| B22 | 증상과 실제 근거를 기록하고 재현·수정·회귀 확인으로 해결한다. escalate는 미해결 이관, refresh는 실제 재관찰, supersede는 이전 사건 연결이며 이력 삭제나 성공 위조가 아니다. |
| B23 | 원래 요청 범위만 감시하고 첫 관찰/실제 대상 상태를 표시한다. 취소 후 신규 알림/실행을 중지하고 복구는 현재 취소 상태·소유 실행을 대조한다. 같은 상태는 모델을 깨우지 않는다. |
| B24 | 정확한 사건을 조회·소비하고 ACK와 작업 해결을 구분한다. 외부 대기는 해소 조건을 보존; 인계는 자원 종료/이전과 미처리 사건·잔여 예산을 이어가 중복 감시를 막는다. |
| B25 | 계획에 소유 설정의 변경 전후와 배포본을 연결한다. 적용은 기존 사용자 설정을 보존하며 writer 전환을 검증한다. 복구는 새 기록을 버리지 않고 읽기/재개를 확인한다. |
| B26 | 공식 릴리스 관찰/안내/준비/선택/적용을 구분한다. 이미 승인된 업데이트는 추가 선택을 강제하지 않는다. 선택 필요 시 실제 의도와 대상/범위를 연결하며 활성화는 새 호스트 관찰로 확인하고 복구 시 새 자료를 보존한다. |
| B27 | 비공개 초안 조회·준비는 공개하지 않는다. 실제 사용자 권한의 내용/대상을 확인하며 이미 받은 승인을 반복 요구하지 않는다. 제출 결과 불명은 원격 대조로 처리하고 보고 실패가 원 작업을 삭제하지 않는다. |

[#138: 결과 평가·회고 구현](result-evaluation.md)
