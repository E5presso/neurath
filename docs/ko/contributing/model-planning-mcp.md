# 동적 모델 계획과 MCP 운용 계약

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

[English](../../en/contributing/model-planning-mcp.md) · **한국어**

[아키텍처](architecture.md) · [작업 도구](task-tools.md) · [Provider 전송](provider-transports.md) · [협업 계약](collaboration-contract.md)

상태: 승인된 구현 스펙. 사용자는 provider 또는 session을 시작할 때 작업 난이도에 따라
모델을 계획하고, 에이전트의 하네스 운용을 CLI에서 MCP로 확실하게 전환하도록 요청했다.
아래 내용은 목표 요구사항이며 구현 완료나 실제 호스트 검증을 뜻하지 않는다.

## 의도, 결정과 용어

에이전트는 승인된 새 provider/session마다 실제 작업, 현재 사용 가능 모델, 기존 제약으로
모델 선택을 계획한다. 사용자는 자연어로 결과를 요청하고 에이전트가 발견·계획·실행·검증을
수행한다. 계획만으로 세션 추가 생성, 현재 모델 변경, 권한 확대, 사용자가 지정한 모델/provider의
무시는 승인되지 않는다.

- D1(사용자): 작업 난이도에 따라 모델 선택을 동적으로 계획한다.
- D2(사용자): 하네스를 MCP로 운용하고 겹치는 세션과 범위를 조율한다.
- D3(파생): 상업 모델 순위를 코드에 고정하지 않고 현재 provider/host 목록을 사용한다.
- D4(소스): 요청/실제 모델 검사, 신원, 소유권, 실행 정책을 보존한다.
- D5(파생): 도구와 생성되는 지시를 함께 전환한다. CLI 안내가 MCP 우선 방침을 무력화할 수 있다.
- D6(파생): 호환성을 유지하고 남은 예외를 명시한다. 범용 argv 통로는 전환 완료가 아니다.
- 기각: 무조건 최저가/최대 모델, 조용한 provider 대체, 일괄 셸 금지, 프로토콜 테스트를 행동 증명으로 간주하는 해석.

모델 목록 관측은 provider/host, 출처, 관측 시점, 정확한 모델 ID와 확인된 기능을 기록한다.
접근·기능·비용의 미확인은 그대로 남긴다. 선택 계획은 작업 revision과 목록에 연결된 에이전트의
제안이다. 요청 선택은 생성 호출에 전달한 값이고 실제 선택은 provider 세션에서 관측한 값이다.
MCP 작업은 현재 호스트 정책을 유지한다. 집행할 수 없는 모드는 구체적인 미지원 상태이며,
CLI 우회나 추가 권한을 부여하지 않는다.

## 현재 구현 경계

현재 명명 도구와 입력은 [작업 도구 목록](task-tools.md)을 기준으로 합니다. 모델 목록·계획,
상태·소유권·단계·평가, 학습·업데이트·보고, 컨텍스트·설치 관리·리뷰·감시를 같은 MCP 표면으로 연결합니다.
`runtime/task_schema.py`가 현재 등록부이며 `runtime/*_tasks.py`가 기존 도메인 서비스에 연결합니다.
`install/mcp_guidance.py`는 설치 지침의 실제 작업을 대조합니다. 내부 CLI와 호스트 콜백은 실행 기반으로
남으며 에이전트가 도움말을 탐색하는 사용 경로가 아닙니다. 아래 수용 조건은 실제 호스트에서 별도로
검증해야 하며 소스 구현이나 도구 등록만으로 통과를 주장하지 않습니다.

## 모델 선택 요구사항

한 작업 안에서 나눌 수 있는 leaf 작업은 네이티브 직접 자식을 기본으로 사용합니다.
별도 세션 수명, 다른 provider 또는 기본 자식 도구가 제공하지 못하는 필수 격리가 필요할
때만 provider 실행을 선택하고 이유를 남깁니다. 일반 메시지는 기존 대화로 보내며 여러
메시지·수신자는 collaboration_send.messages로 한 번에 보낼 수 있습니다.

역할·난이도·사용자 제약에 충분한 가장 작은 관측 모델을 우선합니다. 계획의
selection.mode/model은 모델 선택이고 provider의 top-level mode=inherit는 실행 권한
상속입니다. 서로 다른 결정입니다. 중간 질문이나 진행 보고는 원래 작업을 완료하지 않으며,
SQLite의 태스크는 수행 근거에 따라 종결될 때까지 유지합니다.

| ID | 계약 |
| --- | --- |
| MP-01 | 승인된 provider/session을 새로 시작할 때마다 기본값의 명시적 상속까지 포함한 계획을 만든다. 모델 발견만을 위해 새 세션을 만들지 않는다. |
| MP-02 | 모호성, 변경 범위, 추론 깊이, 실패 영향, 도구/입출력 형식, 문맥 요구량, 검증 강도를 평가한다. 간결한 근거, 난이도(routine/standard/complex), 확신도를 기록한다. 토큰 수만으로 판단하거나 고정 숫자 점수를 게이트로 쓰지 않는다. |
| MP-03 | 명시 모델/provider, 허용 provider, 비용·지연 제약을 지킨다. 제약 안에서 충분한 기능이 확인된 모델을 고르고, 확인된 비용·지연은 그다음에 고려한다. 미확인 가격은 0이 아니다. 할당량 구매나 새 데이터 전송 대상은 계획으로 승인되지 않는다. |
| MP-04 | 작업 digest/revision, 목록 관측, provider, 정확한 모델 ID 또는 명시적 inherit, 지원되는 추론 설정, 선택 근거, 제외 대안, 제약, 재계획 조건을 기록한다. provider 간 추론 설정 대응을 추측하지 않는다. |
| MP-05 | 목록을 얻지 못하면 그 한계를 드러낸다. 호환성이 확인된 기존 기본값은 불확실성을 기록하고 상속할 수 있다. 명시 선택이나 필수 기능을 확인할 수 없으면 작업 전달 전 구조화된 차단을 반환하며, 모델 ID를 발명하거나 조용히 대체하지 않는다. |
| MP-06 | 생성 전에 계획과 요청의 결속을 검증한다. 불확실한 재시도는 같은 실행 키·계획·요청을 유지하고 기존 결과부터 대조한다. 모델 변경은 새 계획 revision이며, 이전 실행을 대조한 승인 범위 내 별도 시도다. |
| MP-07 | 본 작업 전달 전에 기존 adapter 검사로 요청 선택과 provider의 실제 선택을 비교한다. 별칭 동등성에는 provider의 공식 해석 근거가 필요하다. 미관측/불일치는 작업 전달을 막고 진단용 세션/실행 신원을 보존한다. |
| MP-08 | 작업 변경, 가용성 무효화, 기능 부족의 실제 근거가 있으면 재계획한다. 일반 resume/메시지 전달은 선택을 유지한다. 턴 종료만으로 살아 있는 세션을 바꾸거나 재시작하지 않는다. 기존 제약을 벗어나는 변경은 사용자 판단을 받는다. |

직접 diff로 확인할 수 있는 작은 문구 수정은 routine, 기존 테스트가 있는 여러 모듈 기능은
standard, 실제 동작이 불명확한 권한 경계 변경은 complex일 수 있다. 짧은 작업도 실패 영향
때문에 복잡할 수 있다. 난이도 구간은 판단의 설명이며 객관적 모델 품질 점수가 아니다.

소스에 등록된 도구인 provider_models는 모델 세션을 만들지 않고 모델 메타데이터를
관측하고, provider_plan은 에이전트가 작성한 계획을 검증·보존한다. 결정적 runtime은 구조·제약·
결속을 검증하며 주관적 난이도나 모델 품질을 판정했다고 주장하지 않는다. provider_route는 계획
참조와 정확한 선택을 소비하고 provider_run은 영속 실행에 그 참조를 보존한다. 낡거나 변조된
계획은 생성 전에 거부한다. 계획 ID는 호출자의 신원이 아니다.

### 기본값 상속과 계획 재검증

inherit는 대상 provider/host가 해당 생성에 적용할 기본값이며, 다른 provider를 쓰는 부모의
모델을 뜻하지 않는다. 계획에는 resolved_model_id(미확인 가능), default_source,
default_observation_revision을 보존한다. 가능하면 생성 전에 정확한 ID를 확정한다.
그렇지 않으면 같은 승인된 세션의 준비 단계까지만 진행한다. 네이티브 모델 metadata를 읽고
원래 기능·비용·지연 제약을 확인한 뒤 새 계획 revision을 결속해야 본 작업을 전달할 수 있다.
별도의 탐색 세션을 생성하지 않는다. 준비에 엄격한 제약 충족 여부를 확인할 수 없는 유료
모델 호출이 필요하다면 차단을 반환한다.

작업, 대상 provider/host, 제약, 실제 권한, 권한 대응 revision, 관측한 대상 기본값 또는 목록의 무효화 사실이
바뀌면 계획은 낡은 상태가 된다. assignment·target·정책·제약이 일치하는 계획만 재사용한다.
새 assignment나 target은 새 계획을 요구할 수 있지만 세션의 모델 목록은 턴·worktree에서
그대로 재사용한다. 명시적 요청이나 구체적인 목록 무효화 근거가 있을 때만 목록을 새로
관측한다. 시간 경과만으로 기존 작업이나 계획을 취소하지 않는다. 이미 접수된 같은 키로 기록된 결과를 읽는 것은 새
생성이 아니다. S2는 대상 기본값 해석과 변경을, S3는 무효화된 권한 대응과 시간 경과만 있는
경우를 검증한다. provider_plan 선택과 provider_run readback에 위 기본값 필드 세 개를 유지한다.

## MCP 운용 요구사항

| ID | 계약 |
| --- | --- |
| MC-01 | 모든 에이전트용 하네스 작업을 명명된 MCP 도구로 매핑한다. 정책·스킬·상태·검증·알림·오류를 포함하며 일반 작업의 미매핑은 전환 감사 실패다. |
| MC-02 | 동등한 명명 도구가 노출되고 정책을 보존하면 사용한다. 활성 지시·알림·프롬프트·next_action은 실행할 CLI 대신 MCP 작업을 명시한다. 개발자용 호환 참조는 분리한다. 범용 agent(argv)나 임의 engine/shell 통로는 전환 요건을 충족하지 않는다. |
| MC-03 | 기존 kernel API 위에 typed phase/state/evaluation과 worktree 작업을 제공한다. 네이티브 신원, 정확한 소유자 fencing, workflow revision, 검토 결과 소비와 완료 조건을 유지한다. 임의 모듈·Python 표현식·파일 쓰기·호출자 신원 입력을 받지 않는다. |
| MC-04 | typed 학습/업데이트/보고 작업에도 기존 미리보기·동의·복구, 개인정보 검토, 정확한 기여 초안 승인, 불확실한 결과 처리를 유지한다. MCP가 외부 제출을 자동 승인하지 않는다. 집행이 미완성이면 명시적 미지원 상태로 남긴다. |
| MC-05 | 설치 전 부트스트랩·서버 시작·호스트 콜백은 실행 인프라다. 일반 하네스 작업에 CLI 예외를 두지 않는다. 미노출 도구나 집행 불가 모드는 구체적인 상태와 복구 필요를 보고하며 다른 전송으로 우회하지 않는다. |
| MC-06 | 접수 전 실패와 접수된/불확실한 부수 효과를 구분한다. 기록된 결과나 관련 이벤트로 복구하며 불확실한 변경을 CLI로 반복하지 않는다. 전송 경로 변경으로 권한 거부를 우회하지 않는다. |
| MC-07 | 저장된 CLI/기존 MCP 호환은 보존하되 활성 에이전트 지시의 우선순위에서 제거한다. 원본 자산, manifest, 패키지/설치 검사를 갱신하고 자기 설치를 조율한다. 설치된 스킬을 직접 편집하지 않는다. |
| MC-08 | 새 Codex와 Claude의 자연어 시나리오에서 지원되는 일반 작업은 정당한 이유 없는 CLI/기존 argv 호출 0회로 완료해야 한다. 목록·실제 호출·결과·예외는 비공개로 보존한다. 미지원 사례는 명시적 누락으로 남긴다. |

명명 도구가 네이티브 실행을 준비했다고 실행된 것은 아니다. 호스트 정책 아래 실제 실행하고
결과를 다시 확인해야 한다. 여전히 에이전트가 Neurath CLI 명령을 조립해야 하는 경로는 예외이며
남은 전환 작업이다. 소스 편집·테스트용 셸은 저장소 개발이므로 하네스 운용 측정과 구분한다.

메시지 전송은 협업 계약을 따른다. 미확인 동료 메시지는 같은 ID·내용으로 at-least-once 재전달
대상에 남는다. MC-06은 대체 도구를 통한 부수 효과 중복 실행을 막으며 불확실한 메시지 전달을
영구 봉인하지 않는다. polling, heartbeat, 수신 전용 모델 세션, 일반 작업 수명 timeout을 추가하지 않는다.

## 제안하는 명명 작업 표면

이 절은 목표 작업 계약을 설명한다. 현재 호출 범위와 정확한 입력은
[작업 도구](task-tools.md)의 등록 이름과 설치된 호스트의 현재 스키마로 확인한다.
아래 이름과 핵심 입력이 구현 경계를 정의한다.
구현은 닫힌 버전별 입출력 schema를 공개해야 하며, 임의 상태나 CLI argv로 해석되는 JSON 문자열을 받지 않는다.

응답은 기존 ok/operation/result 또는 구조화된 error 형식을 따른다. 조회 결과는 변경 권한이
아니다. 변경에는 현재 네이티브 호출자와 기존 소유권·revision·승인 검사가 필요하다. key는
동일 요청 식별자이며 호출자의 신원이 아니다. 대상 참조는 자원을 가리킬 수 있지만
actor/session/turn 권위는 네이티브 근거에서만 도출한다.

| 제안 작업 | 핵심 구조화 입력 | 기존 담당 / 효과와 권한 |
| --- | --- | --- |
| provider_models | provider, 대상 worktree | Provider adapter의 메타데이터 관측과 저장이며 순수 조회 작업은 아니다. 출처·시점·지원 ID·미확인을 기록하고 모델 질의는 하지 않는다. |
| provider_plan | 작업 revision/digest, 목록 관측 ID, 난이도/근거/확신도, 선택, 제약, 이유, key | 새 계획 계약이 제안을 검증·보존한다. 선택에는 provider, 모델 ID 또는 inherit, 지원되는 추론 설정을 담는다. 호출자의 설명으로 모델 가용성이 증명되지 않는다. |
| session_inspect, turn_inspect | 없음 | StateHandle/state_cli의 현재 호출자 kernel/turn 읽기 전용 진단. session_status는 설치/정책/소유권 요약으로 유지한다. |
| session_recover | 예상 session revision | 현재 루트가 신뢰할 수 있는 새 네이티브 턴 근거로만 복구한다. 턴 발명이나 다른 세션 연결은 불가하다. |
| workflow_start | workflow_id, 등록된 kind, goal, schema 검증된 초기 상태, key | 기존 workflow 서비스. 정상 소유자와 workflow별 schema를 요구한다. |
| workflow_advance, workflow_finalize | workflow_id, expected_revision, schema 검증된 전이, key, finalize의 최종 상태 | 기존 전이/종료 조건을 적용한다. 임의 payload 수정이나 자기 주장으로 완료하지 않는다. |
| phase_start | workflow_id, 등록된 skill, run_id, north_star, key | PhaseRunner.initialize. 네이티브 검토자 등록 등 기존 전제 조건을 유지한다. |
| phase_current | workflow_id | PhaseRunner.current의 읽기 전용 요구사항과 revision. |
| phase_complete, phase_finalize | workflow_id, expected_revision, complete의 phase_id/status/summary/evidence 참조, finalize의 terminal_state, key | PhaseRunner가 진정한 근거를 소비하고 종료 검사를 강제한다. 근거 참조는 실제로 조회·인증하며 문자열 자체를 신뢰하지 않는다. |
| adaptive_read, adaptive_preflight | workflow_id, preflight에서만 생략 가능 | 기존 adaptive-control 조회/사전 점검. 상태를 변경하지 않는다. |
| adaptive_replace, adaptive_override_goal | workflow_id, expected_revision, 닫힌 AdaptiveControlState, key | 기존 adaptive 서비스가 모든 typed 절과 source/goal revision을 검증한다. goal override에는 현재 사용자 의도 근거도 필요하다. |
| material_prepare | batch_id, 닫힌 MaterialActionKind, targets, typed expectations, 선택적 workflow_id, key | 기존 action 준비. 정확한 대상 권한과 기대값을 결속하며 파일 편집이나 명령 실행은 하지 않는다. |
| material_read, material_resolve, material_abandon | read는 현재 batch, 나머지는 batch_id/expected_revision/닫힌 resolution 또는 중단된 invocation 참조/key | 기존 material 서비스. 호출자의 성공 선언이 아니라 실제 호스트 실행과 readback으로 해결한다. 임의 실행 통로가 아니다. |
| worktree_inspect, worktree_claim, worktree_release | inspect/claim은 없음, release는 예상 claim revision/token 참조 | WorktreeRegistry가 네이티브 cwd와 정확한 actor로 최초 claim 및 CAS release를 수행한다. 강제 회수, PID 기반 소유권, 호출자 지정 actor는 불가하다. |
| delegation_prepare, delegation_assign | delegation_id, assignment, key, assign에는 발견된 대상 참조와 workflow_id 추가 | 기존 위임 계약과 상태 서비스. 준비는 직계 자식 관계를 부여하지 않는다. 실제 네이티브 관계 또는 별도의 동료 작업 계약을 검사한다. |
| evaluation_prepare, evaluation_read, evaluation_execute | workflow_id, typed adaptive 상태 또는 준비된 assignment 참조, execute에는 criterion_id/닫힌 evidence kind/등록된 test 참조 추가 | 기존 adaptive evaluation API. execute는 네이티브 실행 정책을 유지하며 임의 셸이나 평가 결과 발명을 허용하지 않는다. |
| evaluation_report, evaluation_consume | delegation_id, key, report에는 verdict/summary/outcome 참조/findings | 기존 delegation report/consume. 실제 지정 검토자만 보고하고 부모는 인증된 독립 근거를 소비한다. |
| learning_status, learning_history, learning_pending, learning_defer | 없음, history는 strategy_id, defer는 reason/key | memory/learning.py가 현재 네이티브 결속을 사용한다. candidate/trial/active/reverted를 수동 지정하는 도구는 없다. observe/verified 훅과 검증된 실행 근거가 승격·철회를 소유한다. |
| releases_status, releases_check, releases_notice | 없음, check의 force는 명시적 새 확인 요청에만 허용 | updates.py. check는 정책을 적용하는 네트워크/로컬 상태 작업이고 notice는 소비를 기록하므로 둘 다 순수 조회가 아니다. |
| releases_prepare, releases_choose, releases_apply, releases_recover | recover 외 offer_id, choose는 닫힌 decision과 네이티브 사용자 선택 참조, 안정적 요청 key | updates.py의 정확한 미리보기/동의/버전/digest/복구 조건. 준비는 설치가 아니며 apply가 동의를 만들 수 없다. |
| reporting_status, reporting_list, reporting_read | 없음, read는 draft_id | reporting.py 조회 메서드. 정확한 초안과 상태를 공개 제출 없이 읽는다. |
| reporting_prepare | 기존 닫힌 보고 필드 8개, 개인정보 검토 확인, key | Reporting.prepare의 manifest/공통 범위 및 의미상 개인정보 검사. 검토 확인은 공개 제출 승인이 아니다. |
| reporting_consent, reporting_approve | decision, 네이티브 사용자 선택 참조, approve는 정확한 draft_id 추가 | 기존 consent/approve 의미. 과거 기억이나 모델의 boolean 값으로 승인을 추론하지 않는다. |
| reporting_submit, reporting_reconcile | draft_id, reconcile에는 정확한 이슈 URL, key | 기존 고정 목적지 submit/readback/reconcile. 공통보고 동의 또는 정확한 기여 승인, 소유권/네트워크 정책, 불확실한 송신 처리를 강제한다. 현재 모드에서 집행할 수 없으면 미지원 상태를 반환한다. |

기존 API는 _assets/scripts/agent_harness/state_cli.py, worktree_registry.py, state_handle.py,
_assets/scripts/skill_harness/phase_runner.py, memory/learning.py, updates.py, reporting.py에 있다.
표는 신규 작업의 최소 범위이며 다른 에이전트용 작업을 누락해도 된다는 뜻이 아니다.
C1에서 나머지 모든 스킬 helper와 생성 지시를 매핑한다. 추가 helper도 한정된 명명 도메인
작업으로만 제공하며 미지원 항목은 명시적 전환 누락으로 남긴다.

모델 계획/readback 출력에는 plan_id/revision, 작업 digest, 목록 출처/revision, 요청 선택,
실제 선택 또는 미확인, 검증 상태, 차단/재계획 사유를 보존한다. 일반 작업이 오래 실행됐다는
이유만으로 계획을 만료시키지 않는다. 제약·작업 변경 또는 목록 무효화가 재검증을 유발한다.
provider별 목록 조회는 현재 지원되는 네이티브 adapter를 쓰고 unavailable을 반환할 수 있다.
존재하지 않는 범용 API를 발명하지 않는다.

## 시나리오, 커버리지와 test-first 검증

| 시나리오 | 통과 근거 | 요구사항 |
| --- | --- | --- |
| S1: 단순/복잡 신규 작업 | 근거 있는 난이도와 선택, 정당한 경우에만 서로 다른 모델 ID | MP-01–04 |
| S2: 고정/미지원 모델, 미확인 목록, 미지원 추론 | 고정 선택 유지 또는 차단, 허용되는 명시 상속, 기능 발명 없음 | MP-03–05 |
| S3: 낡은 계획, 요청 변조, 실제 불일치, 별칭 | 결속 검증 전 본 작업 전달 없음, 공식 별칭 해석 | MP-06–07 |
| S4: 불확실한 생성 후 할당량 실패/범위 변경 | 기존 결과 대조, 미확인 중복 실행 없음 | MP-06–08 |
| S5: 기억, 발견/송신/조회/답장, Newsroom, 상태 | 알림/오류 복구까지 명명 MCP 호출 | MC-01–02, MC-08 |
| S6: phase 전이, claim 충돌, 학습 롤백, 업데이트/보고 준비 | typed 상태와 기존 권한 유지, 실제 명명 호출 또는 명시적 미지원 상태 | MC-03–05 |
| S7: MCP 부재, 제한 정책, 접수 후 중단 | 근거 있는 예외, 권한 확대/중복 변경 없음 | MC-05–06 |
| S8: 저장된 구 호출과 새 설치 호스트 | 하위 호환, 새 도구의 올바른 선택, 기존 설정 보존 | MC-07–08 |

실패하는 계획/schema/결속 테스트부터 작성하고 adapter fixture, 지시 회귀, 설치 fixture 순으로
확인한다. 적용 가능한 S1–S8을 실제 Codex와 Claude에서 실행한다. 프로토콜 동작, 설치, 에이전트
도구 선택, 모델의 작업 품질은 별도 근거다. 계획의 설명 자체를 품질 판정 근거로 쓰지 않는다.
기존 전체 검사 성공은 이 새 인수 기준 통과가 아니다.

## 구현 단위, 소유권과 재개

아래는 로컬 구현 초안이며 GitHub 객체는 생성하지 않는다. 각 child는 한 세션, 주요 파일 5개
이하를 목표로 한다. 신규 코드 300줄 또는 변경 200줄을 넘거나 독립 kernel 영역을 함께 다루면
분리한다. 계약 변경이 adapter 변경보다 선행한다.

| 작업 | 범위 / 먼저 실패시킬 테스트 | 의존성 |
| --- | --- | --- |
| M1 | 목록/선택 계약, 잘못된/낡은 계획 거부 | 없음 |
| M2 | Codex 목록과 요청/실제 결속 fixture | M1 |
| M3 | Claude 목록과 요청/실제 결속 fixture | M1, M2 계약 패턴 참조 |
| M4 | 명명 모델 도구와 route/run 계획 결속, 요청/키 불일치 | M2, M3, 실행 소유자 통합 |
| C1 | 전체 작업/지시 목록, 알림의 MCP 회귀 | 없음, 알림 소유자 조율 |
| C2 | typed phase/소유권 작업, 신원/fencing/검토자 실패 | C1, 필요하면 kernel 영역별 분리 |
| C3 | typed 학습 작업, trial/승격/롤백 권한 | C2 |
| C4 | typed 업데이트 작업, 정확한 동의와 중단 복구 | C1 |
| C5 | typed 보고 작업, 개인정보/정확한 승인/불확실한 제출 | C1 |
| C6 | 배포 지시 전환, 낡은 CLI 안내 실패 | C2–C5, M4 |
| V1 | 배포/설치 검사와 새 호스트 S1–S8 | C6 |

각 child의 인수 기준은 연결된 요구사항 구현, 명시한 회귀의 변경 전 실패/변경 후 통과, 한계
보존의 세 가지다. M1은 MP-01–06, M2/M3는 MP-05–07, M4는 MP-06–08, C1은 MC-01–02,
C2는 MC-03, C3–C5는 MC-04–06, C6는 MC-02/07, V1은 MC-07–08과 S1–S8을 담당한다.

M1 뒤 M2/M3는 독립 진행 가능하며 C3/C4/C5는 각 선행 작업 뒤 진행한다. 공유 runtime/task_schema.py,
runtime/tasks.py, providers/operations.py, policy, manifest와 자기 설치는 한 통합 작성자가
관리한다. 전달/ACK/재시도, 권한 승계, 프로세스 수명은 병행 전달 작업이 담당하며 해당 파일 수정
전에 정확한 계약/패치를 교환한다. 필수 경로는 M1 → M2/M3 → M4 → C6 → V1 및
C1 → C2–C5 → C6 → V1이다. 전부 병렬인 계획이 아니다.

이 파일과 연결된 소스/참조 문서에서 재개한다. Provider별 목록 adapter는 현재 네이티브 기능으로
확정하고 위 명명 작업 표면을 기존 typed API 위에 구현한다. 고정 가격표, 상업 모델 순위, 구현 완료, 실제 호스트
인수 통과를 이 문서로 주장하지 않는다.
