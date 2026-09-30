---
name: reconnect-host
description: 설치된 Neurath와 실행 중 MCP 배포본이 다를 때 승인된 Codex 호스트 재시작을 한 번 예약하고, 같은 작업에서 실제 활성화를 확인합니다. 일반 앱 재시작이나 Neurath 설치를 대신하지 않습니다.
intent-class: harness.host-reconnect
input-authority: live-session-diagnostic
not-for: [harness.update, unrelated-app.restart]
user-invocable: true
---

# Reconnect Neurath Host

`session_status`가 설치된 배포본과 실행 중인 MCP의 불일치를 확인했을 때 사용합니다.
설치 성공, 새 turn, 앱 창 표시만으로 활성화됐다고 판단하지 않습니다.

1. 현재 `session_status`, `task_list`, worktree claim과 미완료 workflow를 읽습니다.
   이전 검사·설치를 반복하지 말고 이어갈 정확한 작업과 배포본을 기록합니다.
2. 재시작에 대한 현재 사용자 지시가 있거나 이미 승인된 작업의 명시적 재시작 범위인지
   확인합니다. 관련 없는 활성 작업이 있다면 그 소유 상태를 보존합니다. 현재 actor가
   claim을 쥐고 있고 재시작 전에 풀어도 안전하면 정확한 lease/token으로 해제합니다.
3. Codex 데스크톱 macOS에서는 현재 앱의 실제 PID, 실행 파일, bundle ID와 현재 thread
   ID를 관측합니다. 앱 도구가 제공되면 **같은 thread**에 한시적 heartbeat continuation을
   먼저 만들거나 기존 것을 갱신합니다. 같은 목적의 heartbeat를 중복 생성하지 않습니다.
4. `scripts/relaunch_codex.py schedule --thread-id <실제 UUID> --pid <실제 PID>
   --key <안정된 작업 키> --execute`로 한 번만 예약합니다. Helper는 해당 PID가
   `com.openai.codex` 앱 실행 파일인지 확인하고, 정확한 PID만 종료한 뒤 앱과 원래
   thread를 다시 엽니다. 예약 결과와 LaunchAgent 실행 상태를 확인합니다.
   `scheduled-unverified`는 bootstrap 성공 후 LaunchAgent 표시가 아직 확인되지 않은
   상태입니다. 같은 key로 다시 예약하지 말고 해당 label의 `launchctl print`를 읽어
   실제 실행 또는 종료 상태를 확인합니다.
5. 돌아온 **새 호스트 이벤트**에서 앱 PID 변경과 `session_status`의 설치·활성화·정책을
   다시 읽습니다. 필요한 worktree는 정상 claim으로 다시 획득하고 기존 task/workflow를
   이어갑니다. 다른 worker의 활성화는 그 worker의 실제 세션에서 따로 확인합니다.
6. `scripts/relaunch_codex.py cleanup --thread-id <같은 UUID> --key <같은 키>`로
   자신이 만든 LaunchAgent와 로그만 정리합니다. 완료되면 한시적 heartbeat를 멈춥니다.

재시작 한 번 뒤에도 배포본이 다르면 재설치·재시작을 반복하거나 권한을 넓히지 않습니다.
관측한 blocker와 남은 작업을 보존합니다. macOS Codex 앱, heartbeat 연결 또는 안전한
PID 확인 경로가 없으면 지원되지 않는 조건을 정확히 보고하고 다른 호스트 프로세스를
추측해 종료하지 않습니다.
