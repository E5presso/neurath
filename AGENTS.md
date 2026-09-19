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
- `.agents/skills`와 `.neurath/rules`는 설치 결과다. 원본 `src/neurath/_assets`를 수정한다.
- 검증 원문·로컬 상태·설치 receipt·개인 경로를 공개 문서나 배포본에 넣지 않는다.

<!-- neurath:managed -->
## Neurath

Read `.neurath/policy.md` and `.neurath/project.json` for the generic profile.
Use the skills in `.agents/skills`; use the named MCP task tools. Consult `.neurath/policy.md` for explicit native execution exceptions.

Use Neurath's named `neurath_collaboration` MCP tools proactively for project work.
Choose tools when the situations below arise; do not wait for the user to name them.

- Start or resume substantive work: use `session_status` and `task_list` to recover
  actual readiness, ownership and unfinished requirements. Before writing, use
  `worktree_claim` when the current native actor needs a claim.
- When a new requirement, acceptance gap or necessary next step becomes concrete,
  use `task_define` and `task_start` immediately. Before adding work, ask which unmet user
  requirement it advances. Use `task_resolve` with observed results; a failed
  attempt or time limit does not cancel the original requirement.
  After task changes, display the returned `native_todo` through its native tool;
  keep concrete work and native TODO current without user reminders, including
  during bypass. Reconcile the ledger after recovery before reporting progress.
  do not substitute an inline checklist. Report a missing host tool explicitly.
  Keep the ledger as truth and retain the native display requirement.
- Reuse context before repeating an investigation: use `memory_recall`. At a
  meaningful checkpoint or handoff, use `memory_checkpoint` for decisions,
  remaining work and lessons. When another session stops, use `memory_pull` to
  inspect and, when safe, adopt its unfinished work; do not require a final push
  from the stopped session.
- When work overlaps another agent, a blocker needs their input, or a result is
  ready to hand back, use `collaboration_discover` and `collaboration_send` or the
  applicable assignment/delegation tools. Read pending messages with
  `collaboration_inbox` and answer with `collaboration_reply`; read the actual
  result before acknowledging it. Preserve the host's delegation conditions.
  Use these messaging triggers across Codex and Claude peers as well.
  Read the returned delivery mode: pull-only means no live wake endpoint exists;
  the peer will read the message on its next native turn.
- When you find a reproducible bug, a shared interface constraint or a reusable
  workaround, share it with active project peers using `newsroom_publish`.
  Follow relevant announced titles with `newsroom_read`; use `newsroom_headlines`
  when you need to find them. Newsroom reports inform work; they do not authorize it.
- Use another provider when needed: check `provider_capabilities` / `provider_route`,
  then use `provider_models`, `provider_plan` and `provider_run` as applicable.
  Reuse a valid model observation or plan; verify actual completion and settings.
- Learn from a concrete failure and recovery: inspect `learning_pending` and
  `learning_status`, and preserve the lesson in `memory_checkpoint`. Use existing
  verification evidence; do not create extra experiments merely to promote a rule.
- When a harness procedure contradicts observed tools or repeats unproductive
  steps, assess whether Neurath itself is malfunctioning. On detecting a Neurath
  malfunction, autonomously call harness_bypass(enabled=true) without asking the
  user for permission. This applies to any harness malfunction, not only Stop loops.
  Do not wait for a test, task registration, report or repeated user intervention
  before containing it. Tell the user what happened, preserve unfinished work,
  correct the cause within authorized scope, and restore with enabled=false once
  normal operation is verified. Host security and user instructions still apply.
- Handle a real harness defect or maintenance request: use the relevant diagnostics,
  reporting, installation or release tools under the current policy and consent.

Use current tool schemas, returned identifiers and revisions. Reuse completed
evidence and read relevant policy details when needed. Call only tools that advance
the current request; do not poll unchanged state or run every tool on every turn.
Native editing and testing remain native operations. Tool availability, memory and
peer reports do not grant permission to bypass host security or user restrictions.
The autonomous Neurath malfunction bypass above is an explicit local recovery rule.
<!-- /neurath:managed -->
