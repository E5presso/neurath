# 공통 작업 실행

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

[English](../../en/contributing/task-tools.md) · **한국어**

[기여 안내](index.md) · [아키텍처](architecture.md) · [프로바이더 전송](provider-transports.md)

현재 소스의 `runtime/task_schema.py`와 도메인 모듈에는 **명명된 작업 132개**가 등록되어 있습니다.
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
| 세션 준비 상태 | `session_status` |
| 독립 실행 | `provider_cancel`, `provider_recover`, `provider_run`, `provider_status` |
| 프로바이더 탐색 | `provider_capabilities`, `provider_route` |
| 기억 | `memory_checkpoint`, `memory_recall` |
| 프로젝트 검사 | `verification_run` |
| 동료 통신 | `collaboration_ack`, `collaboration_close`, `collaboration_conversation`, `collaboration_discover`, `collaboration_forward`, `collaboration_inbox`, `collaboration_message`, `collaboration_publish`, `collaboration_register`, `collaboration_reply`, `collaboration_send`, `collaboration_submitted`, `collaboration_subscribe`, `collaboration_unsubscribe` |
| 배정 작업 수명 | `collaboration_accept`, `collaboration_assign`, `collaboration_report`, `collaboration_task` |
| 뉴스룸 | `newsroom_comment`, `newsroom_headlines`, `newsroom_peers`, `newsroom_publish`, `newsroom_read`, `newsroom_revise`, `newsroom_seen` |
| 상태·아티팩트·소유권 | `artifact_put`, `artifact_read`, `material_abandon`, `material_prepare`, `material_read`, `material_resolve`, `session_inspect`, `turn_inspect`, `worktree_claim`, `worktree_inspect`, `worktree_release` |
| 학습·릴리스·보고 | `learning_defer`, `learning_history`, `learning_pending`, `learning_status`, `maintenance_choice_prepare`, `maintenance_choice_read`, `releases_apply`, `releases_check`, `releases_choose`, `releases_notice`, `releases_prepare`, `releases_recover`, `releases_status`, `reporting_approve`, `reporting_consent`, `reporting_list`, `reporting_prepare`, `reporting_read`, `reporting_reconcile`, `reporting_status`, `reporting_submit` |
| 모델 계획 | `provider_models`, `provider_plan`, `provider_plan_read` |
| 단계·평가 | `adaptive_override_goal`, `adaptive_preflight`, `adaptive_read`, `adaptive_replace`, `delegation_assign`, `delegation_prepare`, `evaluation_consume`, `evaluation_execute`, `evaluation_prepare`, `evaluation_read`, `evaluation_report`, `phase_complete`, `phase_current`, `phase_evidence_prepare`, `phase_finalize`, `phase_start`, `workflow_advance`, `workflow_finalize`, `workflow_start` |
| 컨텍스트·보호 기억·평가 루프 | `diagnostics_integrity`, `diagnostics_profile`, `diagnostics_project`, `enclave_delete`, `enclave_read`, `enclave_set`, `evaluation_loop_close`, `evaluation_loop_open`, `evaluation_loop_read`, `evaluation_loop_round`, `turn_yield` |
| 검증·사고·리뷰 | `diagnostics_continuation`, `incident_escalate`, `incident_record`, `incident_refresh`, `incident_resolve`, `incident_supersede`, `incident_validate`, `review_abort`, `review_begin`, `review_comments`, `review_consume`, `review_publish`, `review_report`, `verification_builtin`, `verification_nodes` |
| 설치 관리 | `installation_apply`, `installation_plan`, `installation_recover` |
| 작업 증거·정리 | `process_evidence_record`, `worktree_cleanup`, `worktree_isolation` |
| PR 감시 | `monitor_ack`, `monitor_cancel`, `monitor_event`, `monitor_external_wait`, `monitor_handoff`, `monitor_readback`, `monitor_recover`, `monitor_start`, `monitor_status` |
| 전달 복구 | `delivery_redrive`, `delivery_status` |

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

`material_prepare`로 준비한 Git 관리 대상 파일에 실제 변화가 있으면 프로젝트 `check` 검증
의무가 남습니다. 의무는 이후 변경 배치나 인계 작성으로 지워지지 않습니다. 현재 소스와 검사
설정이 일치하고 호출자 권한을 다시 확인한 `verification_run(check="check")` 성공으로 확인합니다.
조회만 한 턴, 변화 없는 준비, Git에서 제외된 비공개 검증 자료는 이 의무를 만들지 않습니다.
검사가 미설정이거나 실행 정책상 불가능하면 미완료 상태와 구체적 제약을 보존합니다.
Stop은 검증과 인계 필요를 함께 안내하며 재개 횟수 제한은 유지합니다. 이는 등록된 프로젝트
검사의 완료 확인이며, 실제 호스트 왕복이나 독립 검토 등 목표별 추가 검증은 별도로 등록해야 합니다.

## 호출 수와 응답 크기 줄이기

`session_status`의 기본 `detail="summary"`는 설치·활성화·정책·소유권과 다음 행동을
반환합니다. `detail="full"`은 전체 기능 목록도 반환합니다. 내부 CLI의 기존 상세 결과는
유지합니다. 공통 사용 지침은 MCP 초기화 응답의 `instructions`에 한 번 제공합니다.
호스트가 이를 표시하지 않아도 네이티브 신원·권한·소유권 검사는 유지합니다.

| 겉으로 비슷한 작업 | 선택과 통합 판단 |
| --- | --- |
| `session_status`, `session_inspect`, `turn_inspect` | 준비 진단과 커널 상세 조회는 목적이 다릅니다. 정상 준비에는 요약 한 번으로 시작합니다. |
| `collaboration_message`, `collaboration_inbox`, `collaboration_ack`, `collaboration_reply` | 이미 받은 본문을 다시 조회하지 않습니다. 답장이 필요하면 ACK를 포함한 `collaboration_reply`로 처리합니다. |
| `verification_run`, `verification_builtin`, `verification_nodes` | 프로젝트 설정·내장 검사·정확한 테스트 노드는 입력과 증거 계약이 다릅니다. 이름은 유지하고 실패 전달을 일관되게 처리합니다. |
| `phase_*`, `workflow_*`, `evaluation_*`, `review_*` | 단계 진행·독립 평가·리뷰 수락의 권한이 다릅니다. 자유 형식 실행 도구로 합치지 않습니다. |
| `releases_*`, `installation_*` | 릴리스 검증과 사용자 선택, 로컬 설치 계획·적용은 서로 다른 계약을 유지합니다. |

`verification_nodes`에는 `tests/test_example.py::test_example`처럼 공개 테스트 노드를
전달합니다. `material_prepare.expectations[].observable_id`에는 `targets`의 파일 경로를
그대로 사용하고 `file:` 접두어를 붙이지 않습니다.

여러 대기 메시지는 `collaboration_inbox`로 본문을 받은 뒤 기존 `collaboration_ack`의
`message_ids` 배열로 한 번에 수신 확인할 수 있습니다. 단일 `message_id` 호출도 유지합니다.
둘을 함께 지정하거나 읽지 않은 메시지·다른 수신자의 메시지를 포함하면 전체 묶음을 거부합니다.

Codex 설치에는 `tool_timeout_sec=3660`을 기록해 최대 3600초인 프로젝트 검사보다 전송
제한을 길게 둡니다. 기존 연결은 재로딩이 필요할 수 있습니다. 전송 시간 초과는 검사 종료가
아니므로 실행 상태를 확인하고 중복 실행하지 않습니다. 검사 자체의 속도나 다른 호스트의
연결 제한을 바꾸지는 않습니다.

내장 검사와 노드 검사의 실패는 종료 코드·출력 해시·전후 파일 지문·제한된 진단과 함께
MCP 오류로 반환합니다. 완료된 실패는 같은 키로 재호출해도 다시 실행하지 않습니다.
진단 본문은 첫 응답에만 포함하고 영속 상태에는 저장하지 않습니다. 원인을 수정한 새 검사에
새 키를 사용합니다. 결과가 불확실한 실행은 기존과 같이 상태 확인이 필요합니다.

메모리 동기화는 제한된 네이티브 기록을 먼저 읽고 기록·학습 관측을 같은 트랜잭션에서
순서대로 처리합니다. 재생 시 원문 충돌 검사를 유지하고 충돌하면 해당 묶음을 롤백합니다.
합성 기록의 처리 시간 개선을 실제 LLM 세션 전체 시간이나 토큰 비용의 절감률로 환산하지 않습니다.

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

`native-execution-required`는 현재 모드에서 해당 작업을 집행할 수 없다는 결과입니다.
`session_status`로 제약을 확인하고 구체적인 미지원 상태를 보고합니다. 다른 전송으로 재실행하거나
설정을 넓히지 않습니다. 명명 도구 노출과 실제 실행 성공은 별도로 기록합니다.

불확실한 작업 생성·유지보수·material 효과는 기록된 결과로 대조합니다. CLI로 바꾸는 것은
그 효과를 재실행할 권한이 아닙니다. 이 처리는 at-least-once 메시지 전달과 별개입니다.
구 서버·도구는 저장된 호출자와 호환되며 활성 지시·오류 복구는 동등한 명명 도구가 노출되면
그 도구를 선택해야 합니다.

## 검증

소스 모듈은 `runtime/task_schema.py`, `tasks.py`, `state_tasks.py`, `workflow_tasks.py`,
`maintenance_tasks.py`, `user_choices.py`, `model_tasks.py`, `communication_schema.py`입니다. 스키마 검사,
dispatch·kernel 검사, 패키지 설치, 새 호스트의 도구 선택은 각각 다른 근거입니다. 실제 목록·
호출·결과·예외를 비공개로 보존합니다. 통합 설치본의 Codex·Claude 자연어 실행, 모델 계획,
턴 종료 후 보고 왕복은 각각 검증합니다. 등록 수 132만으로 해당 수용 시나리오의 통과를 증명하지 않습니다.

## 사용 흐름과 새 기능

`artifact_put/read`는 경로 입력 없이 현재 세션의 제한된 JSON 문서를 저장·조회합니다.
`enclave_read/set/delete`는 실제 턴과 digest를 대조하는 컨텍스트 편집이며, `turn_yield`는 현재 턴의
명시적 양보입니다. foreground 복구는 호스트 수명 이벤트의 책임입니다.

`phase_evidence_prepare`는 현재 단계 라벨과 revision에 맞춘 증거를 만들며 `phase_complete`는
반환된 reference를 받습니다. 라벨과 문장만으로 독립 평가 권위를 만들지 않습니다.
추가 관측은 `supplemental_<name>` 보고로 기록할 수 있으며 기존 최소 증거 개수와 검사를 그대로 유지합니다.

`installation_plan`은 검토 가능한 요약과 불변 계획 참조를 반환하고, `installation_apply`는
그 등록 계획을 적용합니다. 원래 파일 내용은 비공개로 남깁니다. `installation_recover`는
실제 저널 복구를 수행하며 손상된 배치와 실행 패키지 자체의 무결성은 구분합니다.

`verification_builtin`은 내장 검사 종류, `verification_nodes`는 정확한 테스트 노드,
`verification_run`은 프로젝트에 연결된 검사 이름을 받습니다. `incident_*`는 기존 사고 처리와
회귀 결과를 보존하고, `review_*`는 기존 고정 리뷰 행렬과 결과 소비를 유지합니다.
`review_comments`는 limit·offset·since·last_seen으로 범위를 제한합니다. offset은 각 요청 시
현재 원격 목록에 적용되며 고정 스냅샷 커서가 아닙니다.

아래 예제의 `tool`과 `arguments`는 MCP 호출 이름과 인자를 표시하는 문서 표기입니다.
네이티브 결속 필드는 호스트가 넣으며 에이전트가 작성하지 않습니다.

```json
{"tool":"phase_current","arguments":{"workflow_id":"current-work"}}
```

```json
{"tool":"phase_evidence_prepare","arguments":{"workflow_id":"current-work","expected_revision":0,"labels":["git_status"],"notes":[{"label":"diff_review","text":"현재 변경의 목적과 범위를 검토했습니다."}],"key":"review-current-diff"}}
```
