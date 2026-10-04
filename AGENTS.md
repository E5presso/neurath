# Neurath 개발 지침

Neurath는 기술 스택과 독립적인 Claude Code/Codex 하네스 설치 패키지다.
현재 사용자 지시와 현재 소스를 기준으로 구현한다.

- `src/neurath/_assets`은 Neurath가 직접 관리하는 독립 실행 자산이다.
- 다른 저장소는 빌드 입력이 아니다. 비공개 프로젝트명·경로·출처 기록은 공개 문서와 배포본에 포함하지 않는다.
- 공개 독자용 상세 문서는 `docs/en`과 `docs/ko`에 같은 상대 경로로 유지하고 함께 갱신한다. 각 로케일의 `usage`는 설치·사용·운영, `contributing`은 Neurath 자체 개발·검증을 설명한다. 루트 README와 CONTRIBUTING 진입점만 `.md`·`.ko.md` 쌍을 사용한다. 언어 전환 링크 외에는 같은 언어의 문서를 연결한다.
- README와 `usage`는 자연어 요청과 에이전트가 수행할 작업·확인할 결과를 설명한다. 사용자가 Neurath CLI를 직접 실행하거나 설정 파일을 편집하도록 안내하지 않는다. 명령·설정 예제는 `contributing`의 에이전트 실행 참조에 둔다.
- 새 설치 동작은 먼저 실패하는 테스트로 정의한다.
- 설치는 기존 지침, 훅, 권한, 프로젝트 의존성을 보존한다.
- 검증은 원문 무결성, 패키지 실행, 설치 동작, 실제 호스트 활성화를 구분한다.
- GitHub 생성, push, 공개 배포는 별도 요청 없이는 하지 않는다.

## 개발과 자기 설치

- 개발 환경은 `uv sync --locked`로 준비하고 `uv run --locked python tools/check.py`로 검사한다.
- 자기 설치는 `./setup --self`를 사용한다. 개발 `.venv`와 설치된 하네스의 도구 환경은 분리한다.
- 실행 자산을 바꾸면 `uv run --locked python tools/build_manifest.py`를 실행한 뒤 검사·빌드·자기 설치 업데이트를 수행한다.
- 매니페스트 생성은 HEAD 이후 실행 자산이 바뀌고 버전이 그대로일 때 patch 버전을 한 번 올리고 패키지·런타임·lockfile을 함께 갱신한다. 반복 실행은 같은 작업의 버전을 다시 올리지 않는다. 명시적으로 올린 더 높은 버전은 유지한다. 필수 검사는 실행 자산 변경에 버전 갱신이 없거나 세 버전이 불일치하면 실패한다.
- 소스 수정·자기 설치와 공개 릴리스는 별개다. `update-neurath`가 사용할 공개 릴리스에는 새 버전의 정확한 wheel 게시가 필요하며, 공개 배포는 별도 사용자 요청을 따른다. 공개 릴리스가 없으면 최신이라고 보고하지 않는다.
- `.agents/skills`와 `.neurath/rules`는 설치 결과다. 원본 `src/neurath/_assets`를 수정한다.
- 검증 원문·로컬 상태·설치 receipt·개인 경로를 공개 문서나 배포본에 넣지 않는다.

<!-- neurath:managed -->
## Neurath

Read `.neurath/policy.md` and `.neurath/project.json` for the generic profile.
Use the skills in `.agents/skills`; use the named MCP task tools. Consult `.neurath/policy.md` for explicit native execution exceptions.

Use the named `neurath_collaboration` MCP tools for work state and the host's native
editing and command tools for actual changes and checks.

- Recover `session_status` and `task_list`; retain the original user's goal. Define
  concrete required work once with `task_define`, use `task_start`, and display returned `native_todo`.
- Start the applicable skill on that Task. Follow `phase_read` and satisfy every
  `phase_complete` condition in order. Only fulfilled user acceptance permits
  `task_complete`. A failure, blocker, timeout or worker return never cancels work.
- Use `worktree_read`, `worktree_claim` and `worktree_release` for actual writer ownership. Reads and failure
  reports require no writer lease. Never force another actor's lease or impersonate it.
- Choose `subagent`, `session` or `cross-provider` by scope, difficulty and need.
  A worker is a role; a different checkout does not require a new session or project.
  Use `assignment_prepare`, native dispatch or `provider_prepare`, actual recipient
  reports and owner acceptance.
- Keep source kinds honest. Quote retained original input with `source_read/quote`.
  `approval_record` records an interpretation of exact input, never new host permissions.
- Reuse relevant `memory_recall`; record decisions and remaining work with
  `memory_checkpoint`. `memory_pull` is reference-only; actual adoption is explicit.
- Use `collaboration_discover`, `collaboration_inbox`, `collaboration_send` and
  `collaboration_reply` for authorized coordination. Read
  before acknowledging. Mailbox delivery alone does not wake a peer or authorize work.
  Share concrete reusable findings through `newsroom_publish`; use
  `newsroom_headlines` and `newsroom_read` for relevant findings.
- On a real harness malfunction, preserve unfinished tasks and explain the actual
  state error. Repair within the authorized scope using native tools. Native host
  permissions remain authoritative; task and phase completion still require evidence.
<!-- /neurath:managed -->
