<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/runtime-lifecycle.md)

# 호출 확인부터 복구까지의 실행 상태

모델 턴, 호스트 프로세스, 등록 작업, 워크트리 소유권은 서로 다른 시점에 끝날 수 있다. Neurath는 각각의 수명을 기록해 중단 시 작업이 사라지거나 프로세스 종료만으로 소유권이 풀리지 않게 한다.

## 상태 객체

| 객체 | 상태 또는 식별 정보 | 의미 |
| --- | --- | --- |
| 세션 | `active`, `ended` | 지속적으로 보관하는 네이티브 세션 기록이다. 명시적인 `ended`는 종료 상태다. |
| 참여자 | `root`, `subagent`; `active`, `idle`, `stopped`, `retired` | 참여자의 역할과 새 작업 할당 가능 여부를 나타낸다. |
| 실제 부모 관계 | `unattested`, `host-attested` | 호스트가 주장된 직접 부모 관계를 확인했는지 나타낸다. |
| 전면 턴 | `active`, `ready-to-stop`, `closed` | 참여자가 현재 요청의 제어권을 가진 상태다. |
| 턴 결과 | `completed`, `awaiting-input`, `failed`, `incomplete` | 해당 종료 계약에 따라 제어권을 반환하는 이유다. |
| 작업 | `pending`, `in_progress`, `succeeded`, `failed`, `invalidated` | 요청된 일과 소유자가 보고한 결과다. |
| 명시적인 워크플로 | `active`, `completed`, `failed` | 단계와 근거 계약이 있는 작업 절차다. |
| 위임 | `pending`, `reported`, `consumed`, `cancelled` | 할당 전달과 필요한 소유자의 결과 소비를 추적한다. |
| 워크트리 소유권 | 소유자, `lease_epoch`, `fencing_token`; `active` 또는 `cleanup-reserved` | 현재 변경 권한과 그 세대를 나타낸다. |

세션 커널이 상태를 전이하고, 상태 핸들이 호출자 접근을 연결하며, 레지스트리가 워크트리 변경을 통제한다. 요청에 식별자를 적는 것만으로 이 관계를 만들 수는 없다.

## 시작, 수행, Stop

실제 세션 시작과 프롬프트 이벤트가 호출자 및 현재 지시를 확인한다. 루트는 작업을 등록하고 요청 출처 근거를 보존한다. 작업 변경에는 활성 네이티브 루트 소유자와 활성 전면 턴이 필요하다. 인정된 참여자는 조회 허용 조건 아래 목록을 읽을 수 있다.

소유자는 정확한 목록·작업 리비전을 사용해 대기 작업을 시작하거나 종료 결과를 기록한다. 작업 시작과 `succeeded` 확정은 모두 의존 작업이 종료 상태여야 한다. 의존 작업이 미해결이어도 실패나 무효화는 기록할 수 있다. 의존 작업이 종료되었다는 조건은 모두 성공했다는 뜻이 아니다. 종속 작업에서 무엇을 성공이라고 주장할 수 있는지는 완료 조건으로 판단한다.

작업 목록이 있으면 Stop은 최신 목록을 읽고 같은 트랜잭션에서 루트 턴을 닫는다. 등록 작업은 모두 종료 상태여야 한다. 네이티브 TODO 갱신, 체크포인트, 추가 워크플로 보고는 별도의 완료 판단권을 갖지 않는다. 작업 목록을 등록하지 않은 세션은 기존 종료 규칙을 유지하지만 목록이 없다는 것이 요청 완료의 근거는 아니다.

일반 Stop은 완료 조건이 충족되지 않으면 계속 실행을 요청한다. Stop을 반복 호출하는 것으로 대기 작업을 해결할 수 없다. 에이전트가 만든 질문과 그 전달 확인은 원래 작업을 중단하거나 범위를 줄이겠다는 사용자 승인이 아니다. 원래 태스크와 완료 조건은 계속 유지한다.

## 원래 작업에 다시 주의를 돌린다

[목표 환기](../../../src/neurath/runtime/goal_reminders.py)는 실제 참여 중인 네이티브 루트의 `UserPromptSubmit`, `PostToolUse`, `PostToolUseFailure`에 제한된 맥락을 추가한다. 성공하지 않은 작업 기록이 있을 때 첫 유효 이벤트, 프롬프트 출처 변경, 서로 다른 `tool_use_id`의 완료 12건, 또는 300초가 지난 뒤의 다음 유효한 새 이벤트에서 전달한다. 같은 호출의 성공·실패 콜백은 한 건으로 세며, 도구 이름이 서로 다른 12종이라는 뜻은 아니다. 5분 뒤 세션을 깨우는 백그라운드 타이머도 없다.

`task_define`·`task_start`·`task_resolve`의 인증된 `PreToolUse`에서도 호출별로 판단 맥락을 전달하며 주기적 전달을 늦추지 않는다. 도구 설명은 호출 선택 전 판단을 안내한다. 대상 태스크가 있으면 먼저 보여 준다.

추가 내용은 2,400 UTF-8 바이트 이내이고 작업 발췌는 최대 4개다. 진행 중인 작업을 실패·무효 등으로 종결된 작업보다 먼저 담으며, 기존 추가 맥락은 유지한다. 주기적 환기는 빈 목록과 모두 성공한 목록을 건너뛴다. 태스크 판단 시점의 전달은 최초 정의를 포함해 이런 목록도 다룬다. 자식이나 다른 신원, 승계된 원본 세션에는 두 종류 모두 전달하지 않는다.

기존 SQLite에는 전달 주기와 최근 64개 이벤트의 중복 억제 정보만 보존한다. 태스크 정의·리비전·결과·소유권·권한을 바꾸지 않고 관련성·기존 근거·범위를 판단해 필요한 후속 태스크를 단계적으로 등록하도록 안내한다. 별도 성찰 보고서·검토·완료 gate를 요구하지 않는다. [환기 테스트](../../../tests/test_goal_reminders.py)는 주기, 크기, 신원, 중복 억제, 상태 보존을 다룬다. 환기 이후 에이전트의 판단이 적절한지까지 기계적으로 인증하지는 않는다.

## 필요한 기간 동안 작업 공간을 소유한다

변경 전에 `worktree_inspect` 또는 `session_status`의 소유권 정보를 읽는다. `worktree_claim`은 실제 현재 신원으로 소유권을 얻는다. 반환된 세대와 토큰을 보관하고 해제할 때 `worktree_release`의 `expected_lease_epoch`, `fencing_token`에 그대로 전달한다.

새 소유권이나 지원되는 인계는 소유권 세대를 바꾼다. 파일 경로가 같아도 이전 토큰은 더 이상 유효하지 않다. 정리는 파괴적인 Git 작업 전에 정확한 소유권을 예약하며 예약 중에는 일반 변경, 인계, 해제를 거부한다. 정리의 `base_branch`, `remote_ref`는 저장소 관례를 추측하지 말고 실제로 확인해야 한다.

호스트 프로세스가 끝나거나 모델이 유휴 상태가 되어도 소유권은 이전되지 않는다. 체크포인트도 해제가 아니다. 재개 후 변경하기 전 현재 소유권을 확인하고 해당 마무리·정리 계약에 따라 해제한다.

## 이력을 유지하며 재개한다

호스트의 `SessionEnd`는 연결을 닫으면서 재개 가능한 세션 상태, 작업, enclave, 소유권을 보존한다. 검증된 실제 재개는 같은 세션에 다시 참여하게 한다. 커널의 명시적 `SessionEnded`는 영구 종료이므로 자동으로 되돌릴 수 없다.

검증된 중단·재개에서는 확인된 이전 전면 턴만 닫을 수 있다. 미완료 작업과 위임은 남는다. 늦은 Stop은 새 턴을 닫을 수 없고, 대응되는 상태가 없는 이벤트는 관련 없는 상태를 바꾸지 않고 진단만 남긴다. 프롬프트 이벤트가 없는 앱 동료 메시지로 기존 목표를 계속하려면 대화 기록과 네이티브 턴 근거가 필요하며 새 작업 승인을 만들 수 없다.

중단 후에는 대화 요약에서 상태를 추측하지 않고 해당 객체를 읽는다. 요청 작업은 `task_list`, 명시적 워크플로는 `phase_current`, 소유권은 `worktree_inspect`, 실행 문제는 전달·제공자 진단으로 확인한다.

## 명시적인 단계와 독립 평가

계약이 있는 스킬은 `phase_start`로 시작하며 `phase_current`가 현재 단계와 리비전을 반환한다. 적응형 워크플로는 초기화 전에 실제 독립 평가 권한이 있어야 한다. 후보 준비는 목표, 의도, 소스, 워크플로 리비전과 내용 해시를 함께 고정한다.

평가자는 그 정확한 후보와 근거를 읽어야 한다. 발견 사항을 수정하면 새 후보를 평가한다. 부모는 인증된 보고를 검증하고 소비한다. 동료 제공자의 유용한 보고라도 독립적이라고 표현하는 것만으로 직접 자식 평가 권한을 얻지는 않는다.

`phase_evidence_prepare`는 현재 레이블과 리비전을 확인하고 불변 근거 참조를 등록한다. Git 관찰과 에이전트 보고는 보증 수준이 다르다. 반환된 참조를 `phase_complete`에 전달해야 하며 임의의 자료 문자열로 단계 계약을 충족할 수 없다. 소스, 소유자, 워크플로가 바뀌면 기존 근거를 그대로 재사용할 수 없다.

운영형 마지막 단계에서는 `phase_complete`에 `terminal_state`를 전달해 단계와 워크플로를 원자적으로 끝낼 수 있다. 그 뒤 다시 종료하지 않는다. 별도 권한 전이가 필요한 계약은 `phase_finalize`를 유지한다. 고정 검토 도구인 `review_begin`, `review_report`, `review_consume`, `review_abort`도 자체 검토 기준을 유지한다. `review_publish`는 정확한 현재 PR head를 가리켜야 한다.

## 제공자 실행과 결과 전달

`provider_run`은 실행 요청을 지속적으로 기록하고 ID를 신속히 반환한다. 분리된 작업자는 소유한 네이티브 연결을 통해 시작, 대기, 실패, 연결 해제, 취소, 완료를 보고한다. 발행자는 모델 턴이 끝난 뒤에도 완료 수락, 취소 또는 검증된 인계까지 후속 처리를 책임진다.

일반 작업 전체에 일괄 수명 제한 시간을 두지 않는다. 개별 연결, 쓰기, 응답에는 제한 시간이 있으며 네이티브 실행을 기다리는 중에도 메시지와 취소를 처리해야 한다. `provider_status`는 이벤트나 오류 이후 진단에 사용한다. 완료는 주기적인 상태 조회가 아니라 이벤트로 전달한다.

발행한 작업이나 미확인 의무가 남으면 발행자 연결을 유지한다. 유휴 Codex는 새 턴을 받고 실행 중인 턴은 추가 지시를 받는다. Claude Code는 현재 결과와 반복자가 끝날 때까지 알림을 보존하며 스트림 중간 입력을 별도 수신 확인된 턴으로 취급하지 않는다. 연결을 닫을 때도 늦은 알림을 보존하고 이미 시작한 입력 쓰기는 끝낼 수 있게 한다.

발행자 종료가 다른 인스턴스의 승인된 작업을 취소하지는 않는다. `provider_recover(run_id, key)`에는 현재 발행자의 실행 기록, 이전 작업자 세대, 프로세스와 연결 종료 근거가 필요하다. 작업자 소유권이 중복 복구를 막는다. 복구는 기록된 네이티브 세션을 되살리고 현재 정책을 확인하며 원래 할당을 다시 실행하지 않고 대기 전달을 연결한다. 복구 접수와 실제 복구 완료는 구분해 보고한다. 전원이 꺼진 호스트나 디스크 손실에서의 실행 복구는 보장하지 않는다.

## 메시지와 백그라운드 감시

메시지는 알리기 전에 지속적으로 저장한다. `queued`, `submitted`, `received`, `replied`는 저장, 호스트 접수, 수신자 확인, 응답을 구분한다. 수신자는 본문 전체를 읽은 뒤 확인해야 하며 ID만 받은 알림은 충분하지 않다. 수신 확인은 재시도를 멈추지만 작업 수락이나 완료를 뜻하지 않는다.

전송 결과가 불확실하거나 수신 확인이 없으면 같은 식별자, 내용, 키로 재시도할 수 있다. 연결 세대는 오래된 시도의 늦은 결과를 차단한다. 제한 시간이 지나도 접수된 대기 메시지를 조용히 지우지 않는다. 복구가 필요한 기록은 본문과 실패 이력을 보존하며 `delivery_redrive`는 현재 리비전과 실제 복구된 전송을 검증한 뒤 전달을 재개한다. 자세한 내용은 [협업](collaboration-contract.md)에 있다.

감시도 접수와 관찰을 구분한다. `monitor_start`는 실행 ID를 반환하고 실제 프로세스 세대 및 코드에 연결된 일회용 실행 권한을 준다. `started`에는 최초 외부 관찰과 재조회가 필요하다. `monitor_cancel`은 지속적으로 남는 취소 요청이며 실제 종료는 따로 확인한다. 복구에는 이전 종료와 해당 소유권이 필요하다. `monitor_ack`, `monitor_external_wait`, `monitor_handoff`는 이벤트 소비, 외부 대기, 담당 종료 계약을 보존한다. 관찰 전용 모드는 소유자를 재개하지 않는다.

PR 감시는 소유자를 재개하기 직전에 소유자의 최신 네이티브 정책을 읽는다. 정책을 관찰할 수 없거나 바뀌었다면 `monitor_recover`로 지원되는 경로를 복구하며, 재개 인자로 권한을 덮어쓰지 않는다. 이 확인은 [감시 재개 정책 검사](../../../src/neurath/runtime/monitor_runtime.py)에 있다.

## 이전 상태 저장소를 안전하게 정리한다

현재 기준 저장소는 Git 공통 정보에서 구한 제어 루트 아래 `.neurath/local/runtime.sqlite3`다. 이전 상태를 가져오는 작업은 자료 준비이며 이전 쓰기 주체 종료나 새 호스트 활성화를 뜻하지 않는다. 사용하지 않는 연결 워크트리에도 이전 실행기가 남을 수 있으므로 모든 연결 실행기를 확인해야 한다.

이전 쓰기 주체를 조사하고 종료시키는 초기화 인터페이스는 다음과 같다.

```sh
neurath --root TARGET cutover inspect
neurath --root TARGET cutover prepare
neurath --root TARGET cutover apply --expected-token TOKEN_FROM_INSPECTION
neurath --root TARGET cutover recover
```

무조건 순서대로 실행하는 명령 묶음이 아니라 각각 별도 작업이다. `inspect`는 선언된 SQLite 원본 네 곳, 가져오기 보호 정보, 연결 실행기를 비교한다. `prepare`는 기준 데이터베이스가 없을 때만 가져온다. `apply` 전에 관련 쓰기 프로세스를 멈추고 검토한 조사 결과의 정확한 토큰을 사용한다. Unix `lsof`와 닫힌 SQLite 핸들이 필요하다. 열린 핸들·저널, 바뀐 보호 정보, 알 수 없는 실행기나 뒤늦은 행이 있으면 정리를 차단한다.

적용은 알려진 생성 실행기를 임시 차단하고 원본을 비공개로 백업한 뒤 이전 SQLite 파일 경로를 디렉터리 차단 표식으로 바꾼다. 기준 자료를 유지하며 보호 정보와 감사 상태를 트랜잭션으로 갱신한다. 새 메시지 본문이나 수신자는 거부하고, 기준 기록이 이미 종료된 경우 지원되는 수명주기 차이만 조정한다. 경로 차단이 확정되면 실행기를 복원하고 업데이트할 워크트리를 알려 준다.

저널 처리 중 중단되면 `recover`가 커밋 전 경로를 되돌리거나 커밋 후 실행기 복원을 마친다. 충돌한 파일과 손상된 백업은 보존하고 보고한다. 정리 저널이 남아 있으면 설치를 차단한다. 대상 워크트리를 업데이트한 뒤 설치 위치, 프로토콜, 실제 호스트 활성화를 각각 검증한다.

관련 구현과 검사는 [기능 지도](capability-map.md)에 있다. 호출 입력은 [작업 도구](task-tools.md), 상태 전이의 네이티브 근거는 [호스트 통합](hosts.md)을 참고한다.

## 설계 검토의 소스 근거

변경이 앞서 설명한 책임을 유지하는지 다음 구현에서 확인한다. 호환 코드는 저장된 기존 호출 경로를 검토할 때 참고한다.

| 책임 | 소스와 회귀 검사 |
| --- | --- |
| 목표·단계·평가 | [adaptive_control_authority.py](../../../src/neurath/_assets/scripts/agent_harness/adaptive_control_authority.py), [phase_runner.py](../../../src/neurath/_assets/scripts/skill_harness/phase_runner.py), [task_ledger_tasks.py](../../../src/neurath/runtime/task_ledger_tasks.py), [workflow_tasks.py](../../../src/neurath/runtime/workflow_tasks.py) |
| 호스트와 정확한 호출 확인 | [mcp.py](../../../src/neurath/agents/mcp.py), [hooks.py](../../../src/neurath/hosts/hooks.py), [identity.py](../../../src/neurath/hosts/identity.py) |
| 메시지와 제공자 수명 | [delivery.py](../../../src/neurath/agents/delivery.py), [delivery_recovery.py](../../../src/neurath/agents/delivery_recovery.py), [newsroom.py](../../../src/neurath/agents/newsroom.py), [store.py](../../../src/neurath/agents/store.py), [jobs.py](../../../src/neurath/providers/jobs.py), [model_planning.py](../../../src/neurath/providers/model_planning.py), [supervision.py](../../../src/neurath/providers/supervision.py), [provider_execution.py](../../../src/neurath/runtime/provider_execution.py) |
| 제한된 맥락 보존 | [hooks.py](../../../src/neurath/memory/hooks.py), [learning.py](../../../src/neurath/memory/learning.py), [transcript.py](../../../src/neurath/memory/transcript.py) |
| 설치 및 사용자 선택 보존 | [transaction.py](../../../src/neurath/install/transaction.py), [release_install.py](../../../src/neurath/release_install.py), [user_choices.py](../../../src/neurath/runtime/user_choices.py), [updates.py](../../../src/neurath/updates.py) |
| 저장된 호출의 호환성 | [verification.py](../../../src/neurath/runtime/verification.py) |

### 예약된 작업 재개

Codex 예약 메시지는 실제 호스트가 남긴 `codex_app.automation_update` 전달 기록 쌍으로 확인합니다. 동료 메시지와 마찬가지로 현재 루트·턴·출력 ID·도구 이름·출력 해시를 대조하며, heartbeat 문구를 신뢰하거나 사용자 입력 증명을 새로 만들지 않습니다. 일반 도구 호출의 결과, 서로 다른 전달 기록, 아직 처리되지 않은 사용자 입력은 이 경로로 실행을 다시 열 수 없습니다. 기존 지시 출처와 태스크 상태를 유지해 작업을 이어갑니다.

### 앱에서 생성한 독립 작업

Codex 앱은 `thread_source="agent_created_thread"`로 독립 루트를 표시하고, 초기 요청을 `codex_app.create_thread` 전달 기록 쌍으로 보냅니다. 같은 루트·전달 검사를 적용합니다. 함께 붙는 컨텍스트는 호스트 메타데이터의 `plugins.recommendations`, `agents_md.instructions`, `environments.environment_context` 분류로 확인하며, 알 수 없거나 사용자 입력이 섞인 컨텍스트를 건너뛰지 않습니다. 검증된 네이티브 턴을 활성화해도 사용자 입력 증명이나 생성자의 권한을 새로 만들지 않습니다. 실제 작업에는 승인된 지시 또는 작업 위임 범위가 필요합니다.
