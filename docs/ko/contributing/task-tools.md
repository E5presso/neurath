# 공통 작업 실행

[English](../../en/contributing/task-tools.md) · **한국어**

[기여 안내](index.md) · [아키텍처](architecture.md) · [프로바이더 전송](provider-transports.md)

현재 소스의 `runtime/task_schema.py`와 도메인 모듈에는 **명명된 작업 88개**가 등록되어 있습니다.
등록만으로 기존 호스트가 모든 도구를 다시 로드했거나 설치된 실제 호스트에서 모든 경로가
통과했다는 뜻은 아닙니다. [모델 계획과 MCP 운용](model-planning-mcp.md),
[프로바이더 협업](collaboration-contract.md)이 요구 동작을 정의합니다.

에이전트는 명명된 MCP 도구로 하네스를 운용합니다. `runtime/tasks.py`는 구조화 입력을 기존
저장소·커널 서비스에 전달하며 에이전트가 CLI argv를 조립할 필요가 없습니다. 저장된 호출자와
근거 있는 네이티브 실행 예외를 위해 CLI 호환은 유지합니다. 일반 운용 경로는 아니며 범용
`agent(argv)` 통로만 제공하는 것으로 MCP 전환을 완료했다고 판단하지 않습니다.

## 소스에 등록된 도구

아래 표는 정확한 등록 이름을 묶은 목록입니다. 호출 전 현재 노출된 입력 스키마를 읽습니다.
같은 그룹의 모든 작업이 동일한 입력이나 권한을 요구하지는 않습니다.

| 영역 | 명명된 작업 |
| --- | --- |
| 준비 진단 | `session_status` |
| 프로바이더 실행·복구 | `provider_run`, `provider_status`, `provider_cancel`, `provider_recover` |
| 프로바이더 경로 발견 | `provider_capabilities`, `provider_route` |
| 기억·인계 | `memory_recall`, `memory_checkpoint` |
| 등록 검사 | `verification_run` |
| 동료 메시지·구독 | `collaboration_discover`, `collaboration_inbox`, `collaboration_send`, `collaboration_reply`, `collaboration_message`, `collaboration_ack`, `collaboration_forward`, `collaboration_submitted`, `collaboration_register`, `collaboration_conversation`, `collaboration_close`, `collaboration_subscribe`, `collaboration_unsubscribe`, `collaboration_publish` |
| 배정 작업 수명 | `collaboration_assign`, `collaboration_accept`, `collaboration_report`, `collaboration_task` |
| Newsroom | `newsroom_headlines`, `newsroom_read`, `newsroom_publish`, `newsroom_revise`, `newsroom_comment`, `newsroom_peers`, `newsroom_seen` |
| 상태·소유권·변경 작업 | `session_inspect`, `turn_inspect`, `worktree_inspect`, `worktree_claim`, `worktree_release`, `material_prepare`, `material_read`, `material_resolve`, `material_abandon` |
| 학습·업데이트·보고 | `learning_status`, `learning_pending`, `releases_status`, `reporting_status`, `reporting_list`, `learning_history`, `learning_defer`, `reporting_read`, `releases_check`, `releases_notice`, `releases_recover`, `releases_prepare`, `releases_apply`, `reporting_prepare`, `reporting_submit`, `reporting_reconcile`, `reporting_consent`, `reporting_approve`, `releases_choose` |
| 모델 목록·계획 | `provider_models`, `provider_plan`, `provider_plan_read` |
| 워크플로·단계·위임·평가 | `workflow_start`, `workflow_advance`, `workflow_finalize`, `phase_start`, `phase_current`, `phase_complete`, `phase_finalize`, `adaptive_read`, `adaptive_preflight`, `adaptive_replace`, `adaptive_override_goal`, `delegation_prepare`, `delegation_assign`, `evaluation_prepare`, `evaluation_read`, `evaluation_execute`, `evaluation_report`, `evaluation_consume` |
| 메시지 재처리 | `delivery_status`, `delivery_redrive` |
| 정확한 유지보수 선택 | `maintenance_choice_prepare`, `maintenance_choice_read` |

## 입력과 권한

응답은 `ok`, `operation`, 공통 `result` 또는 code/message/state/retryable/next_action을
포함하는 구조화된 `error`를 사용합니다. 실패한 검사도 결과를 보존하며 인계는 에이전트 보고로
남깁니다. 상태 기록 성공만으로 독립 검토나 제품 완료를 인정하지 않습니다.

네이티브 훅은 actor·세션·현재 턴·worktree·입력·도구 호출을 결속합니다. 자원 참조는 대상을
가리키며 호출자 신원을 직접 지정하는 수단이 아닙니다. 변경·만료·종료된 호출 결속으로 다른
변경을 승인하지 않습니다. 상태·워크플로 작업은 기존 소유자·revision·네이티브 검토자·근거
소비 검사를 유지합니다.

`session_status`는 설치·활성화·정책·소유권 진단, `session_inspect`·`turn_inspect`는 커널 상세
조회에 사용합니다. `worktree_claim`은 현재 작업 공간과 네이티브 actor를 사용하며 release는
관측한 lease epoch와 fencing token을 요구합니다. material 도구는 실제 호출·readback으로
정확한 로컬 작업을 준비·대조하며 셸이나 파일 편집 도구가 아닙니다. workflow·phase·adaptive·
evaluation 도구는 typed 도메인 입력을 받으며 임의 상태 패치를 받지 않습니다.

## 독립 작업 계획과 실행

1. `provider_capabilities`와 `provider_models`로 프로바이더·모델 기능을 발견합니다.
   모델 목록 관측은 저장하므로 `provider_models`를 순수 조회로 분류하지 않습니다.
2. `provider_plan`에 작업·revision, 목록 ID, 실행 설정, 선택, 제약, 난이도, 근거·확신도,
   이유, 대안, 재계획 조건과 key를 전달합니다. 정확한 revision은 `provider_plan_read`로 읽습니다.
3. provider/worktree/assignment/key와 계획 결속을 담아 `provider_run`을 호출합니다.
   기본 `mode="inherit"`는 바로 위 생성자의 정책을 해석합니다. 모델·추론·명시적 정책 필드는
   선택 계획과 승계 정책에 맞아야 하며 필드를 전달했다고 override가 승인되지는 않습니다.
4. 발행자에게 돌아오는 보고를 처리합니다. `provider_status`는 이벤트에 따른 진단,
   `provider_cancel`은 취소 요청, `provider_recover(run_id, key)`는 네이티브 프로세스·연결의
   실제 종료가 확인된 기록 세션 복구 요청입니다. 복구는 원래 작업의 재실행이 아닙니다.

영속 실행 접수는 모델 완료 전에 반환합니다. 설치·실제 모드·네이티브 활성화·소유권·모델 확인
후에 본 구현을 전달합니다. Codex·Claude 필드의 의미를 유지하며 지원하는 대응과 준비 제약은
[프로바이더 전송](provider-transports.md)에 설명합니다. Claude 목록은 설정을 보존한 짧은 공식 SDK
제어 연결에서 모델 질의 없이 조회합니다. 목록 메타데이터는 인증·추론 성공이 아니며,
확인되지 않은 기능·가격·설정된 기본값은 미확인으로 남깁니다.

## 메시지, 수신 확인과 재처리

정확한 수신자를 발견한 뒤 `collaboration_send`나 `collaboration_assign`을 사용합니다.
동료 작업 배정은 프로세스 생성과 다릅니다. 실제 네이티브 턴에서 작업을 수락하고
`collaboration_report`로 주요 상태를 보고합니다. 발행자는 본문 조회와 후속 행동을 책임집니다.

접수된 동료 메시지는 알림 전에 영속 저장합니다. 본문 조회·ACK·답장·진단에서 안정적인 메시지
ID를 사용합니다. `collaboration_ack`·`collaboration_reply`는 전체 본문을 먼저 수신해야 하며
알림 미리보기는 해당하지 않습니다. ACK는 작업 결과 수락이 아닙니다. 전달 서비스는 ACK까지
같은 ID·내용을 재전송할 수 있으며 불확실한 전송도 재시도합니다. 메시지 재시도를 주기적인
완료 폴링이나 별도 수신 LLM으로 바꾸지 않습니다.

`delivery_status(message_id)`는 메시지 상태·최근 전달 시도·복구 보류를 조회합니다.
`delivery_redrive`는 message_id/expected_revision/repair_reference/key를 받아 신원·내용을
바꾸지 않고 복구된 보류를 재시도 가능하게 합니다. 정상 전달 검사는 유지합니다. 보존된 대기
메시지는 대화 TTL을 넘겨 유지하며 `collaboration_close`는 몰래 없애지 않고 대기 상태를
반환합니다. Newsroom은 별도 active-only 제목·본문·정정·댓글 작업을 제공합니다.

## 유지보수와 네이티브 실행 제약

학습 status/history/pending은 진단이며 defer는 사유 기록입니다. 검사 성공이나 수동 승격이
아닙니다. 업데이트·보고 작업은 기존 버전·digest·미리보기·개인정보·동의·복구 조건을 유지합니다.
`releases_check`는 네트워크·로컬 상태 작업이고 `releases_notice`는 안내 소비를 기록하므로
순수 조회가 아닙니다. 제출은 고정 목적지와 기존 공통 보고 동의 또는 정확한 기여 승인을 사용합니다.

`maintenance_choice_prepare`로 정확한 업데이트·기여 초안·보고 설정과 검토할 질문을 결속합니다.
질문을 표시한 뒤 `releases_choose`, `reporting_consent`, `reporting_approve`는 새 네이티브 사용자
응답을 해당 질문, 대상 스냅샷과 커널 입력 기록에 대조합니다. `maintenance_choice_read`는
동의 접수와 실제 적용 완료를 구분합니다. 도구 출력·동료 메시지·무관한 응답은 동의가 아닙니다.
지원하지 않는 입력 형식은 구체적인 오류로 알립니다. 기존 승인이 있으면 지원되는 네이티브
경로로 보존하며 자동으로 다시 묻지 않습니다. 강제 메타데이터 재조회에는 사용자의 명시적
요청과 현재 실행 정책을 적용하고, 두 번째 동의 질문을 요구하지 않습니다.

명령·네트워크를 수행하는 MCP 작업에는 실제 네이티브 루트의 소유권과 실행 정책이 필요합니다.
현재 Codex 직접 실행 게이트는 준비 완료, `danger-full-access`, `never`, 검토자 `None` 또는
`user`를 요구합니다. Claude 게이트는 준비 완료, `bypassPermissions`, 알려진 네이티브 deny가
없고 관측된 파일·네트워크 제한이 없는 경우를 요구합니다. OS 실행 환경의 `unobserved`를
무제한 접근으로 바꾸지 않습니다. 이는 프로바이더 어댑터가 받는 모드 범위보다 좁습니다.
스키마가 모드를 받는 것과 MCP가 해당 모드의 모든 제한을 집행하는 것은 다릅니다.

작업이 `native-execution-required`를 반환하면 에이전트는 정책을 유지하면서 같은 승인된 작업의
지원되는 네이티브 실행 경로를 사용합니다. 작업·도구 노출·사유·실제 결과를 전환 예외로 남깁니다.
설정을 넓히거나 deny를 우회하지 않습니다. 일반 소스 편집·테스트용 셸과 하네스 운용 명령은 구분합니다.

불확실한 작업 생성·유지보수·material 효과는 기록된 결과로 대조합니다. CLI로 바꾸는 것은
그 효과를 재실행할 권한이 아닙니다. 이 처리는 at-least-once 메시지 전달과 별개입니다.
구 서버·도구는 저장된 호출자와 호환되며 활성 지시·오류 복구는 동등한 명명 도구가 노출되면
그 도구를 선택해야 합니다.

## 검증

소스 모듈은 `runtime/task_schema.py`, `tasks.py`, `state_tasks.py`, `workflow_tasks.py`,
`maintenance_tasks.py`, `user_choices.py`, `model_tasks.py`, `communication_schema.py`입니다. 스키마 검사,
dispatch·kernel 검사, 패키지 설치, 새 호스트의 도구 선택은 각각 다른 근거입니다. 실제 목록·
호출·결과·예외를 비공개로 보존합니다. 통합 설치본의 Codex·Claude 자연어 실행, 모델 계획,
턴 종료 후 보고 왕복은 각각 검증합니다. 등록 수 88만으로 해당 수용 시나리오의 통과를 증명하지 않습니다.
