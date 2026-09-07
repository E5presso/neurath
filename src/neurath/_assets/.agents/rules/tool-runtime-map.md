# Tool Runtime Map

## Neurath 작업 도구

두 호스트 모두 현재 도구 목록에 노출된 구조화 MCP를 우선한다. 입력은 도구 스키마를 사용하며
CLI 옵션 문자열을 조립하지 않는다. 도구 응답은 현재 권한을 대신하거나 새로운 권한을 만들지 않는다.

| 작업 | 우선 도구 | 에이전트의 CLI 대체 경로 |
|---|---|---|
| 세션 설치·활성화·모드·소유권 진단 | `session_status` | `session-status` |
| 지원되는 네이티브 호스트 호출 준비 | `provider_capabilities`, `provider_route` | `provider capabilities/route` |
| 명시 모드의 새 Codex 작업 실행 | `provider_run` | MCP가 호출자 정책을 집행할 수 없으면 호스트 셸의 `provider run` |
| 프로젝트 기억 조회·인계 | `memory_recall`, `memory_checkpoint` | `memory recall/checkpoint` |
| 등록된 검사 | `verification_run` | MCP가 호스트 모드를 집행할 수 없으면 호스트 셸의 `verify` |
| 동료 찾기·메시지 수신·송신·답변 | `collaboration_discover/inbox/send/reply` | `agent discover/inbox/send/reply` |
| 뉴스 제목·본문 조회·발행 | `newsroom_headlines/read/publish` | `newsroom headlines/read/publish` |

설치 전 준비, 훅, 자동화와 아직 작업 도구가 없는 엔진 기능은 CLI를 유지한다.
기존 `agent(argv)` MCP는 업데이트 호환용이며 새 작업에서 명명된 도구보다 먼저 고르지 않는다.
대체 명령은 에이전트가 `.neurath/run`으로 실행한다. 사용자에게 실행이나 설정 편집을 맡기지 않는다.
설치·프로토콜 진단과 실제 활성화·관측된 모드·정식 소유권을 각각 확인한다.
검사 실패·중단의 상태를 읽고 복구한다. 같은 key의 쓰기는 같은 내용으로 재시도하며,
실행 결과가 불확실한 검사는 자동 재실행하지 않는다. 독립 검토와 사용자 승인은 그대로 필요하다.

Skill과 phase file은 아래 stable `tool:<key>`로 Claude Code와 Codex tool call을 참조합니다.

| key | claude code | codex |
|-----|-------------|-------|
| `read_file` | `Read` | `functions.exec_command` with `sed`, `nl`, or `cat` |
| `search_files` | `Glob`, `Grep`, or `Bash` with `rg` | `functions.exec_command` with `rg` or `rg --files` |
| `read_many` | multiple `Read` calls; 승인된 위임은 현재 `Agent` 또는 `Task` schema 확인 | parallel `functions.exec_command` reads |
| `edit_file` | `Edit`, `MultiEdit`, or `Write` | `functions.apply_patch`; formatter for mechanical edits |
| `run_shell` | `Bash` | `functions.exec_command` without `sandbox_permissions` |
| `ask_user` | question tool or direct message | concise commentary/final question |
| `spawn_agent` | 현재 호스트의 `Agent` 또는 `Task`; 실제 inventory/schema 확인 | 현재 multi-agent tool; unavailable이면 skill이 허용한 serial fallback만 사용 |
| `team_create` | 현재 `TeamCreate` 또는 지원되는 named agent 기능 | 현재 multi-agent tool 또는 worker boundary를 보존한 serial execution |
| `create_worktree` | `CreateWorkTree` or repo script | `/create-worktree` or `git worktree`; `.agents/worktrees/` 격리 유지 |
| `send_progress` | `SendMessage` | commentary update or phase runner JSON evidence |
| `send_message` | named `SendMessage` | commentary, phase evidence, or multi-agent message |
| `github` | GitHub MCP or `gh` | GitHub connector when available, otherwise `gh` |
| `source_research` | `WebSearch`, `WebFetch`, docs connector | web research tool or `find-docs` |
| `design_canvas` | native canvas MCP | native canvas MCP; 없으면 blocked |
| `browser` | Claude in Chrome (`--chrome`/`/chrome`) 등 native control | browser/chrome skill의 네이티브 브라우저 제어 |
| `native_mobile` | simulator용 native computer control | computer-use skill의 simulator control |
| `phase_runner` | `Bash` phase runner | `functions.exec_command` phase runner |
| `verify_repository` | `Bash` typed verification runner | `functions.exec_command` typed verification runner |
| `local_pr_monitor` | durable PR mailbox process | exact app-server wake process |

## 규칙

- Repository gate는 structured edit의 literal target만 다룹니다. Shell/web/browser/subagent/provider
  tool의 의미·승인·sandbox는 host 소유이며 harness는 grammar·option·allowlist를 복제하지 않습니다.
- 재사용 문서는 vendor-only 이름 대신 `tool:<key>`를 씁니다. Native research/browser/mobile
  capability는 shell·Playwright·web fetch로 가장하지 않고 없으면 blocked입니다. Chat에서 logic을
  복제하지 말고 repository command를 사용합니다.
- Effectful test/pre-commit/mise/frontend 검증은 closed `verification_runner`만 사용합니다. Runner가
  exact profile, index 포함 before/after, bounded diagnostic과 owned process를 검증합니다. Daemon survivor는
  실패이며 same-user hostile sandbox는 아닙니다. Explicit pyrefly/ruff check만 read-only입니다.
- Web/user/subagent 호출은 nonmaterial boundary이지 semantic evidence가 아닙니다.
  `write_stdin`은 host-owned control이며 owning-PTY, material, 완료, 효율 증거가 아닙니다.
- Claude와 Codex child event는 official `session_id+agent_id`를 권한을 저장하지 않는 같은
  lifecycle adapter(`state-free lifecycle adapter`)로
  정규화합니다. Repository config의 `SubagentStart`/`SubagentStop` 선언은 `DECLARED`일 뿐 host가 config를
  load했거나 event를 전달·재시도·차단한다는 증명이 아닙니다. 두 runtime 모두 parent가 없거나
  host가 바로 위 부모를 확인하지 못하면 same-session bounded context/no-op만 허용하고 actor,
  turn, outbox를 persist하지 않습니다. Raw `parent_agent_id` 자체도 authority가 아닙니다.
- Host가 바로 위 부모를 확인했을 때만(`host-attested exact parent`) registered actor와 독립적인
  바로 아래 자식 권한(`DIRECT_CHILD`)을 만들고,
  persisted child의 `SubagentStop`이 gate를 닫습니다. Codex의 current child schema에는 바로 위 부모 값
  (`immediate parent`)이 없습니다. 상태 제어·저장소 변경·검증자 지정·의미 보고서 승인은 사용 불가
  (`UNAVAILABLE`)입니다. 권한 없는 child(`state-free child`)를 root로 대신 쓰지 않으며 Team/message/task control은 nonmaterial입니다.
- Stateful command 예시는 한 physical line의 literal argv로 기록합니다. 실제 option grammar와
  authority는 각 CLI와 host runtime이 소유합니다. `UPPER_SNAKE_CASE`는 invocation 전에 실제 값으로
  치환하고 native `workdir`를 사용합니다.
- Stateful JSON은 literal read와 agent 해석을 분리하며 shell capture/JQ 대신 returned object와 hook digest를
  사용합니다. Contract evidence 이름은 runtime과 무관하게 유지합니다.
- Claude auto `PermissionDenied`는 UNKNOWN으로 닫습니다. Post event가 없으면 첫 Stop이 UNKNOWN/BLOCKED로
  terminalize하고 recovery turn을 강제합니다.
- Backend scaffold는 shared generated-file inventory 전체를 prepare하며 broad directory authority를 금지합니다.
- 독립 read-only 조사 둘 이상은 root가 병렬 위임하고 대조합니다.
  상한을 채우지 않으며 child 재위임·mutation·권위 위임은 금지합니다. `/review-code`는
  독립 single-subagent readback 없으면 blocked이고 serial fallback이 없습니다.
- Codex app의 기존 세션은 현재 `read_thread`로 상태를 확인하고 승인된 `send_message_to_thread`를 우선한다.
  Claude는 현재 `ListAgents`로 동료를 발견하고 정확한 반환 주소와 현재 schema로 `SendMessage`를 사용한다.
  수신 보류·거부·대기 상태를 보존하고, 비활성 동료를 임의로 깨우지 않는다.
  외부 app-server는 해당 adapter가 소유한 세션만 제어한다. CLI resume은 terminal이 소유한 실행에 한정하며,
  이미 실행 중인 app·Claude 세션을 다른 headless process로 대신하지 않는다.
