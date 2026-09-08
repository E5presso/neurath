# Codex와 Claude Code
<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

[사용 안내](../usage/index.md) · [기여자 안내](index.md)


[English](../../en/contributing/hosts.md) · **한국어**

공식 문서를 2026-09-06에 읽고 schema를 확인했습니다. Context7의 Claude Code 및
ChatGPT Learn 문서도 함께 대조했습니다.

| 대상 | 설치 위치 |
| --- | --- |
| 공통 지침 | 기존 `AGENTS.md`에 표시된 관리 블록 추가 |
| Codex 스킬 | `.agents/skills/<name>` |
| Codex 훅 | `.codex/hooks.json`에 command hook group 병합 |
| Claude 지침 | 새 파일은 `CLAUDE.md → AGENTS.md`; 기존 파일은 import 블록 추가 |
| Claude 스킬 | `.claude/skills/<name> → ../../.agents/skills/<name>` |
| Claude 훅 | `.claude/settings.json`의 hooks에 group 병합 |

공통 이벤트는 SessionStart, SessionEnd, SubagentStart, UserPromptSubmit, PreToolUse,
PostToolUse, PreCompact, Stop, SubagentStop입니다. Claude에는 PostToolUseFailure와
PermissionDenied를 추가합니다. SessionEnd의 Codex timeout은 공식 상한인 3초입니다.
한 이벤트의 Neurath 처리는 하나의 command 안에서 순서대로 실행하여 자체 gate끼리 경합하지 않습니다.
기존 다른 hook group은 그대로 남고, 호스트가 지정한 병렬 실행 의미를 따릅니다.

Codex의 `.codex/config.toml` inline hooks가 이미 있다면 파일을 보존합니다.
Codex는 같은 layer의 hooks.json과 inline 선언을 함께 로드하며 경고할 수 있으므로 doctor에서
이 상태를 표시합니다. `.codex/config.toml`에 개인 모델이나 권한을 추가하지 않습니다.

doctor의 `placement=passed`는 배치된 bytes/link가 설치 기록과 같다는 뜻입니다.
`protocol=passed`는 격리 Git 저장소의 subprocess에서 두 호스트의 startup JSON과 malformed
input 거부를 검증했다는 뜻입니다. 실제 호스트가 hook을 신뢰하고 호출했다는 증명이 아닙니다.
`host_activation=unverified`는 별도의 실제 호스트 실행 근거가 필요하다는 뜻입니다.
doctor는 외부 호스트 실행 기록을 읽지 않으며, 설치가 trust를 대신하지 않습니다.
2026-09-06의 Codex·Claude Code 기본 흐름과 보호 파일 삭제 차단 검증 결과는
[검증 범위](validation.md)를 참고하세요.
세션·턴·자식 에이전트의 출처를 확인할 수 없으면 미확인 상태(`UNATTESTED`)로 두고
실행 상태를 변경할 권한을 부여하지 않습니다.
원시 parent id 또는 agent id로 독립 검토자 완료 권한을 만들지 않습니다.

실제 자식 등록은 호스트의 생성 호출과 호스트 transcript를 대조해 수행합니다.
Codex는 생성 호출의 반환 경로와 자식 transcript의 부모·세션 metadata를 함께 검증합니다.
Claude는 부모의 실제 Agent 호출에 일회성 참조를 추가하고 자식 transcript에서 확인합니다.
원문 prompt만 복사하거나 다른 턴의 참조를 재사용해도 직계 자식 권한은 얻지 못합니다.
자식 transcript가 늦게 생성되면 첫 상태 도구 실행 전에 등록을 다시 시도합니다.
검증이 끝나지 않은 자식의 shell/write는 `child-identity-unverified`로 차단합니다.

Claude shell에는 해당 도구 호출에만 유효한 신원 참조를 전달합니다. Codex는 기본
`CODEX_THREAD_ID`와 등록된 실제 자식 기록을 대조합니다. 부모 신원으로 대체하지 않으며
호스트의 permissionDecision을 allow로 변경하지 않습니다. 직계 자식만 지원하며 중첩 생성은
명시적으로 거부합니다. 독립 평가 보고와 부모의 보고 소비는 별도의 typed 상태 전이입니다.

부모에서 `명명 MCP 도구 delegation_prepare (현재 입력 스키마 사용)`를 실행하고
바로 다음 기본 자식 생성 도구를 호출하면, 확인된 실제 자식에게 그 위임을 연결합니다.
위임 의도는 현재 foreground에 결속되며 오래된 의도나 중복 자식에 재사용되지 않습니다.

가변 상태와 작업 공간 소유권은 공통 control root의 `.neurath/local/runs`와
`.neurath/local/resources`에 저장합니다. Codex workspace-write가 보호하는 `.agents`에는
스킬과 지침을 배치하며, 설치기가 샌드박스·모델·승인 설정을 바꾸지 않습니다.

호스트의 `SessionEnd`는 재개 가능한 대화의 프로그램 종료로 처리합니다. 저장된 세션,
세션 작업 상태, 소유권, 진행 중 작업을 보존하고 다음 `SessionStart(source=resume)`에서 원래
typed 복구 절차를 실행합니다. 명시적 kernel `SessionEnded`는 여전히 영구 종료이며 자동으로
되살리지 않습니다. 이전 후보 패키지에서 이미 영구 종료된 테스트 세션도 자동 복구하지 않습니다.
중단된 foreground를 재개한 경우에는 호스트의 resume와 다음 root prompt를 확인하고
이전 턴만 닫습니다. 미완료 workflow·delegation·소유권은 그대로 보존하여 typed 복구를
이어갑니다. 영구 종료된 session은 새 SessionStart로 되살리지 않습니다.
최신 실제 실행 결과는 [검증 기록](validation.md)에 있습니다.

Codex 앱에서 다른 작업의 메시지가 새 턴으로 들어오고 UserPromptSubmit이 생략되는 경우,
등록된 루트 transcript의 실제 메시지 전달·완료 기록과 현재 native 턴을 함께 확인합니다.
이때 기존 사용자 목표를 이어갈 foreground만 열고 사용자 승인 기록은 만들지 않습니다.
메시지 본문, 일반 도구 출력 또는 오래된 전달 기록만으로는 이 경로를 사용할 수 없습니다.
이전 턴의 Stop이 늦게 도착해도 현재 턴의 출처가 확인되면 상태를 보존한 채 처리합니다.
출처를 확인할 수 없는 불일치 Stop은 상태를 보존하고 재실행을 요청하지 않는 오류로 보고합니다.
명시적으로 영구 종료된 루트의 반복 Stop은 무변경 처리하며 실행 권한을 되살리지 않습니다.

호스트가 멈추는 것과 작업이 완료되는 것은 별개입니다. 출처가 확인된 루트 Stop은 완료 조건을
충족하기 위한 후속 실행을 한 번 요청할 수 있습니다. 조건이 여전히 충족되지 않으면 미완료
안내와 함께 제어를 반환합니다. 호스트의 `stop_hook_active`와 턴별 후속 실행 기록을 함께 확인하여
반복 Stop이 재실행을 무한히 유발하지 않게 합니다. 상태 누락이나 내부 오류로 재시도 권한을
만들거나 작업을 완료하거나 소유권을 이전하지 않습니다. 이후 확인된 새 사용자 턴은 남은 작업을
재개하고 자체 후속 실행 기회를 가집니다. 정상 완료에는 기존 작업·증거 검사를 그대로 적용합니다.

Codex 앱에서 포크한 대화는 독립 루트로 시작합니다. 실제 호스트의 포크 정보와 SessionStart로
신원을 확인하며, 복사된 대화 내용으로 신원이나 작업 공간 소유권을 얻지 않습니다. 수정에 앞서
포크 자신이 해당 워크트리의 소유권을 획득해야 합니다. 호스트 실행 모드·승인은 이 소유권과
별도로 확인합니다. 세션 생성 성공만으로 배정된 작업을 실행할 수 있다고 판단하지 않습니다.

관련 공식 문서:

- [Codex hooks와 trust](https://learn.chatgpt.com/docs/hooks)
- [Codex skill discovery와 symlink](https://learn.chatgpt.com/docs/build-skills)
- [AGENTS.md](https://developers.openai.com/codex/guides/agents-md)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code 지침 import](https://code.claude.com/docs/en/memory)
- [Claude Code skills](https://code.claude.com/docs/en/skills)

macOS/Linux의 POSIX process group, fcntl, Bash를 사용합니다. Windows 지원은 제공하지 않습니다.
