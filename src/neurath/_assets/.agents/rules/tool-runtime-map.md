# Tool Runtime Map

Skill과 phase file은 아래 stable `tool:<key>`로 Claude Code와 Codex tool call을 참조합니다.

| key | claude code | codex |
|-----|-------------|-------|
| `read_file` | `Read` | `functions.exec_command` with `sed`, `nl`, or `cat` |
| `search_files` | `Glob`, `Grep`, or `Bash` with `rg` | `functions.exec_command` with `rg` or `rg --files` |
| `read_many` | multiple `Read` calls or `Task` | parallel `functions.exec_command` reads |
| `edit_file` | `Edit`, `MultiEdit`, or `Write` | `functions.apply_patch`; formatter for mechanical edits |
| `run_shell` | `Bash` | `functions.exec_command` without `sandbox_permissions` |
| `ask_user` | question tool or direct message | concise commentary/final question |
| `spawn_agent` | `Task` | multi-agent tool; unavailable이면 skill이 허용한 serial fallback만 사용 |
| `team_create` | `TeamCreate` or named `Task` | multi-agent tool 또는 worker boundary를 보존한 serial execution |
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
- Codex app-server만 live session을 깨웁니다. Claude command resume은 새 headless process이고 없으면 blocked입니다.
