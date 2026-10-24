# 호스트 훅과 실행 수명

[문서 목록](index.md) · [태스크 원장](task-ledger.md) · [단계 실행](workflow-runner.md) · [English](../en/host-runtime.md)

이 모듈은 #142의 요청별 런타임 라이브러리입니다. 현재 설치된 Codex·Claude 설정을 바꾸지 않습니다. 훅 진입점은 spakky-typer로 제공합니다. 관리 명령은 [복구 문서](recovery.md), 나머지 업무 CLI·설치 연결은 #148·#151에서 이어갑니다.

## 실행과 작성의 구분

`Execution`은 등록된 호스트 세션과 실제 `agent_id`를 연결합니다. 루트는 빈 자식 ID를 사용합니다. 다른 provider 루트는 기존 세션의 provider 범위로 구분합니다. `SessionStart.source`의 시작·재개·포크·압축 원인을 보존하되, 그 문자열이나 네이티브 ID를 권한 증명으로 사용하지 않습니다.

Codex의 `turn_id`, Claude의 `prompt_id`를 그대로 저장합니다. 식별자가 없는 구형 호스트도 읽기·진단은 가능하지만 현재 턴을 확정해야 하는 변경·종료는 미확인으로 중지합니다. 새 메시지는 턴만 갱신합니다. 취소·중지된 작업을 자동 재개하지 않으며, 실제 재개 지시는 `ResumeExecutionUseCase`가 처리합니다. 재개는 이전 작성의 종료를 대신하지 않습니다.

`Writer`는 공유 작업 폴더의 작성 실행·턴·도구 호출·세대를 관리합니다. 같은 Git 작업 트리의 하위 디렉터리는 하나의 작성 범위이며 서로 다른 worktree는 분리됩니다. 읽기·진단·자식의 조회에는 작성 임대를 요구하지 않습니다. 현재 작업 폴더 작성 도구로 해석하는 이름은 `Edit`·`Write`·`Bash`·`apply_patch`·`exec_command`입니다. 다른 작업 폴더 작성 도구를 연결할 때도 그 효과를 명시합니다. 작업 트리 생성·삭제·보관은 호스트 도구의 책임입니다.

두 요청의 동시 취득은 기존 SQLite 쓰기 트랜잭션과 저장소 버전 검사로 직렬화합니다. 같은 호출의 재전달은 동일 세대를 반환하며 다른 호출은 충돌합니다. 오래된 소유자·세대의 회수는 현재 임대를 해제하지 못합니다.

## 훅 계약

`neurath hook handle --provider codex` 또는 `--provider claude`는 stdin의 호스트 JSON을 읽고 stdout에 제어 JSON 하나를 반환합니다. `HookCliController`는 `@CliController`·`@command`로 스캔되며 비동기 `ReceiveHookUseCase`를 직접 주입받습니다. 세션 등록·훅 적용은 유스케이스의 `AsyncTransaction`에서 수행합니다. 지원 계약은 [Codex 훅 스키마](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/schema.rs)와 [Claude 훅 문서](https://code.claude.com/docs/en/hooks)에 근거합니다.

| 사건 | 처리 |
| --- | --- |
| `SessionStart`, `SubagentStart` | 실제 세션·자식 연결과 시작 원인을 보존. 기존 중지를 자동 해제하지 않음 |
| `UserPromptSubmit` | 실제 턴을 기록. 같은 턴의 재전달은 취소를 되돌리지 않음 |
| `PreToolUse` | 읽기는 임대 없이 통과. 쓰기는 현재 실행 상태와 작성 소유자를 검사 |
| `PostToolUse`, `PostToolUseFailure` | 동일 실행·턴·호출의 확인된 작성 종료만 해제. 실제 중단 표시는 취소로 구분 |
| `Interrupt` | Codex의 실제 중단 사건을 해당 턴에 기록 |
| `StopFailure` | 장애로 일시 중지하고 미완료 작업을 유지 |
| `Stop`, `SubagentStop` | 최신 적용 태스크와 phase 진행으로 계속·대기·종료를 결정 |
| `SessionEnd` | 연결 종료를 기록. 태스크 성공이나 미확인 작성 해제로 바꾸지 않음 |

허용 결과 `{}`는 호스트의 네이티브 권한 판단을 그대로 거칩니다. 미완료 수행에는 `decision:block`과 TODO를 반환합니다. 같은 태스크·phase 상태에서 Stop 거절이 반복되면 `continue:false`와 `stopReason`을 반환합니다. 외부 대기만 남거나 실행이 취소·중지된 경우도 제어권을 반환하며 성공을 기록하지 않습니다. 독립적인 실행 가능 작업이 남으면 대기보다 계속 수행이 우선합니다. 빈 TODO는 대화 종료를 허용하지만 목표 달성 증명으로 쓰지 않습니다.

Stop은 평가자를 새로 생성하지 않습니다. 제3자 결과 평가 phase의 구성은 #138에서 담당하며, 연결된 필수 phase가 끝나기 전 태스크 성공을 막는 기존 runner 계약을 사용합니다. 자식에게 루트 TODO를 자동 전가하지 않습니다. 위임 태스크 연결은 #144에서 실제 배정을 기준으로 확장합니다.

## 실제 종료와 불명 결과

Codex unified-exec는 도구를 `Bash`로 정규화하고 프로세스가 종료된 뒤에만 해당 `PostToolUse`를 발생시킵니다. 그 문자열 결과는 종료 사건으로만 사용합니다. 출력이 잘렸거나 실패했을 수 있으므로 성공·전체 읽음 근거로 바꾸지 않습니다. 근거는 [현재 실행 결과 구현](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/context.rs)입니다.

Claude의 동기 `Bash` 결과는 `stdout`·`stderr`·`interrupted` 계약을 확인합니다. 백그라운드 핸들, 실행 중 세션 ID, 종료를 알 수 없는 결과에서는 임대를 유지합니다. 이런 실행의 회수에는 해당 실행기가 제공하는 `IWriterObserverService`의 실제 종료 관찰이 필요합니다. 현재 포함한 구체 어댑터는 실행기가 `Popen(start_new_session=True)`로 직접 생성한 POSIX 프로세스 그룹용 `PosixWriterObserverService`입니다. 외부 호스트 실행을 PID 추측으로 인수하거나 호스트 앱 전체를 종료하지 않습니다.

`CancelExecutionUseCase`는 추가 쓰기를 중지하고 `ExecutionCancellationRequested`를 기록합니다. `RecoverWriterUseCase`는 현재 임대 세대를 검사하고 `WriterRecoveryRequested`를 기록합니다. 커밋 뒤 이벤트 어댑터가 InterruptExecution 또는 ObserveWriter 유스케이스를 호출합니다. 해당 유스케이스가 DB 잠금 없이 호스트를 관찰하고 결과 이벤트를 발행합니다. 이벤트 어댑터는 그 결과를 ConfirmCancellation 또는 ReleaseWriter의 입력으로 변환하여 호출합니다. 이때 턴·소유자·세대를 다시 대조합니다. 요청의 반환값은 관찰 완료를 뜻하지 않으며 최신 DB 상태가 종료·회수의 근거입니다. 핸들러 실패 시 paused/활성 임대를 보존합니다.

DB·훅 장애는 `continue:false`와 복구 안내로 반환합니다. 명시적 `--bypass`는 차단만 중지하고 가능한 턴·중단·종료 관찰을 유지합니다. DB 장애에서는 기록 미확인을 표시하며 독립 복구 기록을 시도합니다. 이 인자를 네이티브 승인으로 사용하지 않습니다. 반환된 `stopReason`·TODO는 호스트에 전달할 본문이며 JSON 생성만으로 사용자가 알림을 수신했다고 기록하지 않습니다. 운영 진단과 복원 검증은 [복구 명령](recovery.md), 설치 연결은 #151의 범위입니다.

## 저장과 검증

`core_0005`는 실행과 작성 임대 테이블을 추가합니다. 이전 세션에서 현재 실행·승인·성공을 추정해 채우지 않습니다. 실행 또는 임대 기록이 있으면 파괴적인 downgrade를 거부합니다.

회귀 시험은 실제 SQLite 동시 취득·재시작·늦은 결과·취소·명시적 재개·자식 읽기·phase 진전·외부 대기·DB 장애·우회를 확인합니다. 실제 프로세스로 중단 대상 분리와 종료 관찰을 검증합니다. 이 시험을 통과한 것을 사용자 호스트에 설치·활성화됐다는 증거로 보고하지 않습니다.

SQLite 기본 URL은 `sqlite+aiosqlite`입니다. 명시적 연결 설정은 Spakky의 `SPAKKY_SQLALCHEMY__CONNECTION_STRING`을 사용하며, Spakky의 기본 비동기 지원을 끄지 않습니다. 도움말은 DB 트랜잭션을 열지 않습니다. `--bypass`는 가능한 수명 관찰을 저장하지만 저장 실패가 우회를 막지 않습니다. 설치 스크립트가 사용자 훅에 이 명령을 연결하는 작업은 아직 수행하지 않았습니다.

CLI 진입점은 공식 Typer 가이드에 따라 `neurath.cli:cli`입니다. 모듈 전역의 Typer 객체를 컨테이너에서 가져오며 프로세스 종료 시 앱을 정리합니다. 비동기 엔진은 명령의 이벤트 루프에서 정리합니다. 호스트 JSON의 사건 문자열은 transport에서 `HookEvent`로 변환하며 지원하지 않는 사건은 DB 작업 전에 거절합니다.
