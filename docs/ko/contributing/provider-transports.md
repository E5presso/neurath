# Provider 세션과 네이티브 전송

**한국어** · [English](../../en/contributing/provider-transports.md)

<!-- date: 2026-09-07; synced_from: current provider source; English and Korean editions updated together -->

[기여 안내](index.md) · [에이전트 협업](agents-reference.md)

에이전트와 기여자를 위한 실행 참조입니다. Provider는 모델 서비스를 선택하고, 전송 경로는
호스트 세션을 조회·생성하거나 메시지를 보내고 중단하는 방식을 정합니다. 앱 설치, CLI 버전,
세션 생성 성공만으로 네이티브 활성화·worktree 소유권·독립 검토 권한이 성립하지 않습니다.

## 사용 가능한 경로 선택

| 경로 | 구현한 동작 | 관측과 제약 |
| --- | --- | --- |
| 실행 시간이 제한된 Codex/Claude CLI | 읽기 전용 실행, 소유한 실행의 상태·취소·종료 후 계속하기 | 기존 인증 사용, 실행 중 연결 불가, 요청 설정과 실제 관측 구분 |
| Codex 앱 도구 | 현재 노출된 생성·목록·조회·메시지 도구 사용 | 생성 도구가 모든 실행 모드 설정을 제공하지 않으므로 적용값 추정 금지 |
| Codex app-server | 생성·목록·메타데이터 조회, 소유 세션의 시작·조향·중단·idle 후 계속하기 | Desktop에 붙는 연결이 아닌 별도 JSON-RPC 프로세스, 프롬프트 전 실제 설정 확인 |
| Claude 네이티브 동료 도구 | ListAgents 조회 후 SendMessage 전송 | 실제 세션 도구가 필요하며 조회 결과의 정확한 수신 주소 사용 |
| Claude 백그라운드 작업 | Agent view JSON 목록·상태 | 짧은 작업 ID와 네이티브 세션 UUID가 다르며 목록은 실행 모드 증명이 아님 |
| Claude Desktop / Cowork | 외부 수명주기 어댑터 미구현 | UI 기능이 있다는 사실로 호출 가능한 외부 세션 API를 추정하지 않음 |
| Claude Agent SDK | 어댑터 미구현 | 공식 SDK는 네이티브 CLI·Desktop 전송과 별개 |

카탈로그는 `implemented`와 `available`을 구분합니다. 현재 도구 이름은 경로 선택의
단서이며 호출자 신원이나 권한의 증명이 아닙니다. 네이티브 경로가 없으면 인증된 Neurath
보관함에 메시지를 유지합니다. 실행 중인 대화를 별도 프로세스에서 resume하거나 표시 이름으로
주소를 추정하거나 문서화되지 않은 소켓 메시지를 쓰지 않습니다. 자식 프로세스는 부모의 동료
소켓 토큰을 물려받지 않습니다.

## 구현 전 준비 상태 확인

준비 상태는 설치 배포본과 배치, 네이티브 세션·actor·현재 턴의 활성화, 실제 실행 설정,
정확한 활성 worktree claim을 각각 보고합니다. 매번 새로 읽은 진단이며 재사용 가능한 권한이
아닙니다. 저장된 보고서, 외부에서 받은 세션 ID, 생성 성공 응답은 실행 권한을 주지 않습니다.

Codex 네이티브 턴에는 sandbox, 승인 정책, 승인 검토자가 협업 모드와 별도로 기록됩니다.
Claude의 `permission_mode`는 검증된 현재 네이티브 훅 호출에서 얻고 세션·actor·현재 턴·도구
호출에 결속해야 합니다. 관측이 없으면 `unobserved`를 유지합니다. Claude 권한 모드는 OS
sandbox 제한의 증명이 아닙니다. 계획 모드와 읽기 전용 모드는 구현을 허용하지 않습니다.
default나 dontAsk를 관측했다는 사실로 개별 도구 권한을 부여하거나 승인 대기를 해소하지 않습니다.

MCP 서버는 자신의 subprocess가 호출 호스트의 sandbox를 상속한다고 주장하면 안 됩니다.
제한을 유지하는 실행 어댑터가 필요합니다. 실제 호스트 승인은 서비스의 준비 상태 진단과
별개입니다. 검사를 통과시키려고 전역 권한을 바꾸지 않습니다.

## Codex app-server 계약

에이전트는 구조화된 `provider_capabilities`, `provider_route`, `provider_run` 도구를
사용하고 `session_status`로 현재 네이티브 준비 상태를 확인합니다. 같은 공통 서비스에
CLI 어댑터도 있습니다. `provider_route`는 앱 설정 제약과 실제 실행할 수 있는
`provider_run` 대안을 구분합니다. `provider_run`에는 `worktree`와 `assignment`를
전달하며 `model`을 생략하면 호스트 기본값을 유지합니다. 실행 서비스는 준비 턴의 정상
네이티브 도구 이벤트를 처리하고 준비 상태를 확인한 뒤에만 정확한 활성 턴에 작업을
전달합니다. 읽기 전용 준비는 다른 에이전트의 worktree를 claim하지 않습니다.
완료·시간 초과·중단 요청의 결과도 구분합니다.

`CodexSessions`는 연결된 전송을 받고 자신이 생성한 세션 핸들만 제어합니다. `create`는
프롬프트를 보내지 않습니다. 설정이나 모델이 다르면 생성된 네이티브 ID와
`prompt_submitted: false`를 포함한 `CreationRejected` 결과로 복구 단서를 보존합니다.
stdio 경로는 `never`를 지원하며 대화형 승인을 처리할 수 없는 모드는 생성 전에 거부합니다.
승인 검토자·sandbox·협업 모드는 별도 요청값입니다. 명시적인 Default/Plan 설정은 공식
실험 API에 연결을 등록한 경우에만 `turn/start.collaborationMode`로 전달합니다.
생성 시점에는 해당 적용값을 미관측으로 유지하고, 작업 전달 전에 실제 네이티브 턴에서
요청과 일치하는지 확인합니다. Plan에는 쓰기 작업을 전달할 수 없습니다.
`bootstrap`은 설치·활성화·claim만 요청하는 고정 프롬프트를 보냅니다. 쓰기 메시지는 새로 읽은
네이티브 준비 상태를 요구합니다. SessionStart를 꾸미거나 다른 소유자의 claim을 빼앗지 않습니다.

메타데이터 조회는 `includeTurns: false`를 사용합니다. 현재 페이지 단위 이력 호스트는 전체
턴 조회를 거부할 수 있습니다. 자신이 시작한 `turn/start` 응답의 정확한 턴 ID로 조향·중단을
요청합니다. 승인 대기와 입력 대기를 구분하고, 제출·네이티브 완료 이벤트·idle 상태 확인도
각각 보고합니다. idle 이후 계속하기는 같은 연결을 사용하며 다른 실행 중 프로세스에 붙으려고
`thread/resume`을 사용하지 않습니다.
idle 이후 쓰기 작업을 계속하려면 `preparation-required` 결과에 따라 새 bootstrap 턴을
시작하고 현재 준비 상태를 다시 확인합니다. 닫힌 턴을 새 작업의 권한으로 재사용하지 않습니다.

stdio 클라이언트는 프레임·미소비 이벤트·진단 크기를 제한합니다. 지원하지 않는 대화형 요청을
자동 승인하지 않습니다. 시간 초과로 결과가 불확실해지면 그 연결의 새 요청을 거부합니다.
변경 요청을 반복하기 전에 실제 네이티브 상태를 확인합니다. 클라이언트 종료는 자신이 만든
서버 프로세스를 정리하며 Desktop 앱을 종료하지 않습니다.

## Claude 네이티브·백그라운드 동작

공식 [세션 간 메시지 문서](https://code.claude.com/docs/en/cross-session-messaging)는
ListAgents·SendMessage와 delivered·held·refused를 구분합니다. 권한 등급과 수신 설정을
유지합니다. 도구 제출은 수신 확인이나 답변이 아닙니다. Claude 루트에 대한 `agent forward`는
찾아야 할 네이티브 세션과 `discovery-required`를 반환하며 SendMessage 인자를 꾸미지 않습니다.
현재 호스트가 제공하는 도구 스키마를 사용합니다.

[Agent view](https://code.claude.com/docs/en/agent-view)는
`claude agents --json --cwd PATH [--all]`을 제공합니다. Neurath는 `id`, `sessionId`,
`state`, `status`, `waitingFor`를 각각 보존합니다. 빈 배열은 일치하는 세션이 없는 정상 조회입니다.
네이티브 attach는 대화형입니다. 백그라운드 resume은 실행 중인 세션의 복사본을 만들 수 있으므로
메시지 전송에 쓰지 않습니다. CLI 스트림의 `system.init`에서 보고한 모델·권한 모드·작업 경로·도구
목록은 최종 응답·사용량과 별도로 보존합니다.

2026-09-07에 검토한 공식 문서는 macOS/Linux/WSL2의 네이티브 메시지를 Claude Code
2.1.224부터, Windows는 2.1.234부터 설명합니다. 타사 provider나 기능 플래그 조회를 끈 환경의
동일 기기 메시지는 2.1.248부터입니다. 이는 문서상의 최소 버전이며 실제 도구 발견을 대신하지
않습니다. [8월 17–21일 릴리스 노트](https://code.claude.com/docs/en/whats-new/2026-w34)는
Windows 메시지와 idle 알림을 설명합니다. [Desktop](https://code.claude.com/docs/en/desktop),
[Remote Control](https://code.claude.com/docs/en/remote-control),
[agent teams](https://code.claude.com/docs/en/agent-teams)는 서로 다른 호스트 경로입니다.

실제 네이티브 ID, 원시 transcript, 개인 경로, 설치 기록은 비공개 검증 자료에 둡니다.
회귀 테스트·패키지 검사·네이티브 활성화·메시지 답변·구현 준비 상태를 별도 결과로 보고합니다.
