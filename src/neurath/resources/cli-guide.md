# Neurath 0.4.0 CLI

Neurath preserves the current request, work, context and collaboration across host events. The host agent performs the actual reasoning, editing, tools and native delegation.
Use this installed command: `@NEURATH_COMMAND@`. The host session and project are resolved automatically. Never invent native identities or ask the user to re-enter existing instructions. No Neurath approval token is required.

## Default entry and skill selection

These installed rules are the default entry for ordinary requests. The user does not need to enable a Neurath mode, enter a special command, or choose a mode before you act. Choose a suitable procedure from the request's meaning and available skill descriptions; do not ask for information already present in the request or current context.
An explicitly named skill takes precedence over an inferred built-in choice. Read that selected skill's actual source, including a native, project, or user skill, and follow existing host/project instruction precedence. This built-in index does not replace those skills or grant authority to rewrite them. When the named specialist procedure needs runner tracking, pass its faithful definition through the existing custom-skill CLI path below.
Simple questions, explanations, and status requests do not require a skill, task, or workflow. Single host operations such as a commit or worktree creation use the host's own tools without an unrelated procedure. Use context queries only when current stored state is needed; do not create a run merely to answer a question.
For work needing a procedure, read the selected SKILL.md from the index below; do not load every skill. Reuse the task/run already handling the request. Create a task only for actual work missing from the ledger. Start a new selected built-in procedure with `@NEURATH_COMMAND@ workflow start --task-id ID --skill NAME`; inspect an existing run with `workflow show` and continue or revise it instead of creating duplicate work.
Reading a skill or mentioning its name is not a started run. Confirm the returned run ID and current phase, perform the actual work with host tools, and report the phase's verified checks and evidence through `workflow report`. The existing runner owns phase attempts, result evaluation and completion conditions. Skill selection never expands the user's requested scope or grants additional execution or publishing permission.

When current work context is needed, use `@NEURATH_COMMAND@ context show`. Read original sources with `context show --section sources`; select messages and work from `context show --section collaboration`. Use the host tools for actual work.
When preserved unfinished work or accepted evaluation would be affected by a status-only or explanatory response, interpret the current original with `session interpret --kind status --reason ...`. Add `--pause` when the current request excludes execution in this turn; Stop then returns control immediately while preserving tasks and phases. This is the agent's interpretation of the actual original, not a keyword classifier or a mode the user must select. A real new requirement or a mixed request remains `prompt`, including requirements missing from TODO. Never relabel an existing task requirement to avoid evaluation. Interpretation reasons are retained in memory and original text remains available to reviewers.
Do not represent a response-only turn as task cancellation, an external dependency wait, or success. The next actual work turn resumes the same preserved task/run; a current authorized resumption can use `session resume`. Simple conversation without affected work requires no task, workflow, or extra interpretation procedure.
An observed host address identifies its session even when a tool runs from another cwd. Context reports the original session directory and actual invocation directory separately. If that address has multiple observed project links, use the observed provider and returned project ID with `context show --provider/--project-id`; do not merge unrelated projects or invent a new session.

Context lists default to 20 items (maximum 100). Follow each non-null cursor with the same session, section and task filter plus `--after ID`; collect that cursor's named list independently until its cursor is null. The sources section returns `{sources, next_after_id}`. Memory search also returns `next_after_id`; a full final page may require one empty follow-up. A page is not the complete TODO or all original instructions. `--task-id` filters only the current section and retains session-wide original-source references.
Use `maintenance version` to inspect the invoked distribution without opening the store. JSON stdout is the result; successful command execution alone is not task success.

Built-in skill definitions and installed SKILL.md instructions share the packaged catalog. Start a selected project/user procedure with `workflow start --task-id ID --skill NAME --definition @file.json` (or `--definition -` with stdin). The JSON object supplies version, phases with key/purpose/checks, optional string-valued inputs and optional source pointing to the selected SKILL.md; its source text is snapshotted without editing that file. Starting records the procedure, not completed work.
Read an existing run with `workflow show --run-id ID`; its definition and attempts survive catalog or source changes. Use `workflow revise` for method changes in the same run and retain required result evaluation. For nested or finishing work, reuse an unchanged valid evaluation instead of creating a new review task or recursive reviewer. Report only the current phase's actually verified checks.

## Built-in procedure index

- [define-spec](<@NEURATH_SKILLS@/define-spec/SKILL.md>) — 명세와 실행 계획을 함께 정한다. Use: 사용자 의도를 구현 가능한 명세로 정하거나 보완할 때. Exclude: 단순 질문; 이미 충분한 명세를 다시 정의하는 요청 아닌 경우.
- [implement-spec](<@NEURATH_SKILLS@/implement-spec/SKILL.md>) — 요청한 기능을 UI를 포함해 구현하고 검증한다. Use: 명세나 요청에 따른 기능 구현과 관련 수정이 필요할 때. Exclude: 단순 파일 수정; 명세 재작성·이슈 생성·별도 plan만을 위한 경우.
- [autopilot](<@NEURATH_SKILLS@/autopilot/SKILL.md>) — 허용된 여러 작업을 의존성에 맞춰 자율적으로 완수한다. Use: 여러 작업이나 티켓·의존성을 자율적으로 처리해 달라는 요청. Exclude: 한 번의 명령; 일반 질문·상태 조회.
- [review-spec](<@NEURATH_SKILLS@/review-spec/SKILL.md>) — 원문·명세·구현의 누락과 과잉을 감사한다. Use: 요구·명세·구현 전체의 일치 여부를 검토할 때. Exclude: 오탈자 수정; 코드 diff만의 일반 리뷰.
- [review-code](<@NEURATH_SKILLS@/review-code/SKILL.md>) — 변경 코드의 실제 실행 경로와 결함을 검토한다. Use: 코드 변경이나 PR의 정확성·회귀를 검토할 때. Exclude: 명세 논의; PR 생성·댓글 게시만 요청한 경우.
- [qa](<@NEURATH_SKILLS@/qa/SKILL.md>) — 여러 사용자 시나리오의 수락 여부를 실제 동작으로 검증한다. Use: UI·API·저장 상태를 포함한 여러 시나리오를 검증할 때. Exclude: 시험 명령 한 번 실행; 화면 설명만 요청한 경우.
- [debug](<@NEURATH_SKILLS@/debug/SKILL.md>) — 실패 원인을 구별하고 수정 효과를 확인한다. Use: 원인이 불명확한 실패를 조사하고 고칠 때. Exclude: 원인이 이미 정해진 작은 변경.
- [design-ui](<@NEURATH_SKILLS@/design-ui/SKILL.md>) — 사용자 목표와 상태·상호작용을 UI 방향으로 정한다. Use: 새 UI 방향이나 사용자 흐름을 설계할 때. Exclude: 단일 스타일 값 변경.
- [review-ui](<@NEURATH_SKILLS@/review-ui/SKILL.md>) — 실제 UI의 상태·동작·접근성을 검토한다. Use: 구현한 UI의 사용성·일관성·기준 충족을 검토할 때. Exclude: 스크린샷의 내용 설명만 요청한 경우.
- [sync-design](<@NEURATH_SKILLS@/sync-design/SKILL.md>) — 선택한 디자인 기준과 구현의 차이를 반영한다. Use: 디자인 원본과 구현의 변경을 동기화할 때. Exclude: 새 디자인 방향을 임의 선택하는 경우.
- [sync-docs](<@NEURATH_SKILLS@/sync-docs/SKILL.md>) — 변경 사실을 독자별 문서와 언어에 동기화한다. Use: 소스·명세 변경을 관련 문서·언어에 반영할 때. Exclude: 오탈자 하나 수정.
- [pr-feedback](<@NEURATH_SKILLS@/pr-feedback/SKILL.md>) — PR 피드백의 타당성을 판단하고 수정·검증한다. Use: 현재 PR의 피드백을 검토하고 대응할 때. Exclude: 댓글 게시 한 번; 무관한 변경 요청.
- [finish-session](<@NEURATH_SKILLS@/finish-session/SKILL.md>) — 남은 결과를 확인하고 인계 가능한 상태로 마무리한다. Use: 진행한 작업 묶음을 검증·인계하고 마무리할 때. Exclude: 일반 답변의 매 턴 종료; 커밋 하나.
- [update-neurath](<@NEURATH_SKILLS@/update-neurath/SKILL.md>) — 설치 자료를 보존하며 요청한 Neurath 버전을 적용한다. Use: Neurath 설치·업데이트를 요청한 경우. Exclude: 버전 조회; 다른 의존성 업데이트.

## Commands

- `collaboration delegate` — 원 작업의 수행 또는 현재 후보의 독립 평가를 실제 수신 경로에 연결한다.
  - `--task-id`: required
  - `--scope`: required
  - `--role`: optional choices=executor,reviewer
  - `--recipient`: optional
  - `--provider`: optional choices=codex,claude
  - `--model`: optional
  - `--policy`: optional
  - `--artifact`: optional repeatable
  - `--verification`: optional repeatable
  - `--retry-of`: optional
  - `--auth-token`: optional
- `collaboration observe` — 기존 provider의 실제 관찰 결과를 저장하며 새 모델 실행을 만들지 않는다.
  - `--delegation-id`: required
  - `--wait`: optional
  - `--auth-token`: optional
- `collaboration read` — 원 메시지 전체를 출력한 뒤에만 읽음 기록을 반영한다.
  - `--message-id`: required
  - `--auth-token`: optional
- `collaboration send` — 원문 메시지를 지정 동료에게 전달하도록 저장한다.
  - `--recipient`: required
  - `--title`: required
  - `--body`: required
  - `--key`: optional
  - `--auth-token`: optional
- `context show` — 현재 호스트의 실제 원문과 다음 작업을 필요한 영역별로 반환한다.
  - `--session`: optional
  - `--section`: optional choices=current,sources,collaboration,memory
  - `--provider`: optional choices=codex,claude
  - `--project-id`: optional
  - `--task-id`: optional
  - `--limit`: optional
  - `--after`: optional
  - `--auth-token`: optional
- `distribution apply` — 명시적으로 선택한 후보를 적용하고 실제 새 CLI 호출을 검증한다.
  - `--candidate`: required
  - `--provider`: required choices=codex,claude
  - `--directory`: required
  - `--data-home`: required
  - `--auth-token`: optional
- `distribution check` — 공식 릴리스 없음·조회 실패·관찰과 현재 artifact 일치를 구분한다.
  - `--installed`: optional
  - `--auth-token`: optional
- `distribution guide` — 진행 중 세션이 현재 호출 배포본의 실제 안내 본문을 다시 읽도록 반환한다.
  - `--auth-token`: optional
- `distribution plan` — 선택 후보와 파일 변경 전후를 개인 계획 파일에 연결한다.
  - `--candidate`: required
  - `--provider`: required choices=codex,claude
  - `--directory`: required
  - `--data-home`: required
  - `--auth-token`: optional
- `distribution prepare` — 정확한 wheel을 별도 환경에 준비하며 현재 호스트 설정은 바꾸지 않는다.
  - `--wheel`: required
  - `--store`: required
  - `--source-commit`: optional
  - `--auth-token`: optional
- `distribution recover` — 새 DB 기록·사건을 유지하고 해당 설치 전 실행·가이드만 복원한다.
  - `--receipt`: required
  - `--auth-token`: optional
- `distribution verify` — 현재 실행의 실제 명령과 패키지 가이드를 대조하고 내용 식별을 반환한다.
  - `--auth-token`: optional
- `hook handle` — 표준입력의 네이티브 훅 JSON을 처리합니다.
  - `--provider`: required choices=codex,claude
  - `--bypass`: optional
  - `--auth-token`: optional
- `hook verify` — 복원 후 실제 Stop·작성 선행 훅의 차단 경로를 우회 없이 다시 실행한다.
  - `--provider`: required choices=codex,claude
  - `--auth-token`: optional
- `maintenance diagnose` — 무결성·설정·프로젝트·재개 경계를 각각 진단한다.
  - `--database`: optional
  - `--directory`: optional
  - `--provider`: optional
  - `--host-session-id`: optional
  - `--auth-token`: optional
- `maintenance initialize` — 원본을 보존하고 명시적으로 현재 저장소 스키마를 준비한다.
  - `--database`: optional
  - `--auth-token`: optional
- `maintenance install` — 지정한 실제 호스트의 지침·스킬·훅을 다른 설정과 함께 설치한다.
  - `--provider`: required choices=codex,claude
  - `--directory`: required
  - `--data-home`: optional
  - `--preview`: optional
  - `--auth-token`: optional
- `maintenance record-failure` — 업무 명령을 실행할 수 없어도 원인과 남은 일을 복구 기록에 남긴다.
  - `--detail`: required
  - `--reference`: required
  - `--auth-token`: optional
- `maintenance version` — DB를 열지 않고 현재 호출된 배포본의 설치 버전을 반환한다.
  - `--auth-token`: optional
- `memory checkpoint` — 원문 참조와 결과·남은 일·다음 행동의 보고를 저장한다.
  - `--project-id`: optional
  - `--session-id`: optional
  - `--content`: required
  - `--reference`: required repeatable
  - `--task-id`: optional
  - `--graph-directory`: optional
  - `--auth-token`: optional
- `memory observe-lesson` — 호스트 도구로 실제 적용·검증한 교훈의 효과를 다음 작업에 연결한다.
  - `--memory-id`: required
  - `--state`: required choices=proposed,validated,applied,deferred,withdrawn
  - `--reason`: required
  - `--reference`: required repeatable
  - `--failure-case`: optional
  - `--normal-case`: optional
  - `--effective`: optional
  - `--auth-token`: optional
- `memory propose-lesson` — 요청되고 독립 평가된 회고에서 출처 있는 개선 후보를 보존한다.
  - `--run-id`: required
  - `--phase`: required
  - `--content`: required
  - `--reference`: required repeatable
  - `--auth-token`: optional
- `memory read` — 선택한 기억 기록의 원문과 출처를 읽는다.
  - `--project-id`: optional
  - `--memory-id`: required
  - `--auth-token`: optional
- `memory search` — 관련 범위의 과거 자료를 검색해 상세 조회할 ID를 반환한다.
  - `--project-id`: optional
  - `--text`: optional
  - `--session-id`: optional
  - `--task-id`: optional
  - `--limit`: optional
  - `--after`: optional
  - `--graph-directory`: optional
  - `--kind`: optional choices=artifact,checkpoint,handoff,lesson
  - `--lesson-state`: optional choices=proposed,validated,applied,deferred,withdrawn
  - `--auth-token`: optional
- `memory update` — JSON 변경 목록을 같은 개정의 현재 맥락에 원자적으로 적용한다.
  - `--project-id`: optional
  - `--session-id`: optional
  - `--expected-revision`: optional
  - `--changes`: required
  - `--task-id`: optional
  - `--auth-token`: optional
- `migration fence` — 실제 연결 정지와 SQLite 잠금 뒤 원 경로를 퇴역하고 새 기록·사건을 보존한다.
  - `--source`: required
  - `--archive-directory`: required
  - `--auth-token`: optional
- `migration inspect` — 원본을 변경하지 않고 형식·전체 행 수·WAL 유무를 읽는다.
  - `--source`: required
  - `--auth-token`: optional
- `migration prepare` — 원본/WAL·설정과 일관된 사본을 보존하고 현재 저장소에 위치를 등록한다.
  - `--source`: required
  - `--directory`: required
  - `--archive-directory`: required
  - `--config`: optional repeatable
  - `--auth-token`: optional
- `migration read` — 원문·미완료·절차·사실·메시지·학습·미인식 자료를 선택해 읽는다.
  - `--archive-id`: required
  - `--section`: optional
  - `--offset`: optional
  - `--limit`: optional
  - `--auth-token`: optional
- `migration recall` — 선택한 과거 맥락·협업·학습 자료를 현재 기억과 미검증 참조로 연결한다.
  - `--archive-id`: required
  - `--section`: required
  - `--key`: required
  - `--task-id`: optional
  - `--auth-token`: optional
- `migration recover` — 새 코어 기록을 유지한 호환 복구 사본을 만들고 구버전 rollback은 수행하지 않는다.
  - `--source`: required
  - `--destination`: required
  - `--auth-token`: optional
- `migration replay` — 현재 호환 코어에 전환 사건을 원 순서로 한 번씩 반영한다.
  - `--directory`: required
  - `--auth-token`: optional
- `migration resume` — 선택한 과거 미완료 작업을 현재 관찰된 세션의 같은 원장으로 이어간다.
  - `--archive-id`: required
  - `--key`: required
  - `--workflow-key`: optional
  - `--auth-token`: optional
- `monitor status` — 실제 관찰과 정확한 사건·실패·잔여 예산을 부작용 없이 조회한다.
  - `--project-id`: optional
  - `--session-id`: optional
  - `--task-id`: required
  - `--monitor-number`: required
  - `--auth-token`: optional
- `monitor tick` — 등록된 정확한 감시를 내부 런타임에서 한 번만 관찰한다.
  - `--project-id`: optional
  - `--session-id`: optional
  - `--task-id`: required
  - `--monitor-number`: required
  - `--execution-id`: optional
  - `--generation`: optional
  - `--auth-token`: optional
- `newsroom comment` — 실제 읽은 개정에 댓글을 남기고 작업 결과의 성공은 변경하지 않는다.
  - `--peer-id`: optional
  - `--article-id`: required
  - `--revision-number`: required
  - `--body`: required
  - `--auth-token`: optional
- `newsroom list` — 제목과 현재 개정·열람·실제 사용 작업의 정정 영향을 제한 조회한다.
  - `--peer-id`: optional
  - `--text`: optional
  - `--after-id`: optional
  - `--limit`: optional
  - `--auth-token`: optional
- `newsroom publish` — 기사와 근거를 저장하고 활성 구독자에게 제목 알림을 예약한다.
  - `--peer-id`: optional
  - `--title`: required
  - `--body`: required
  - `--reference`: required repeatable
  - `--auth-token`: optional
- `newsroom read` — 선택 개정의 본문·댓글 전체를 반환하고 그 개정만 열람으로 남긴다.
  - `--peer-id`: optional
  - `--article-id`: required
  - `--revision-number`: required
  - `--task-id`: optional
  - `--auth-token`: optional
- `newsroom revise` — 원 작성자의 기사 정정과 이전 본문을 함께 보존한다.
  - `--peer-id`: optional
  - `--article-id`: required
  - `--expected-revision`: required
  - `--title`: required
  - `--body`: required
  - `--reference`: required repeatable
  - `--reason`: required
  - `--auth-token`: optional
- `newsroom subscribe` — 현재 대화의 뉴스룸 제목 알림을 설정하고 다른 주제 구독은 유지한다.
  - `--enabled`: optional
  - `--auth-token`: optional
- `session interpret` — 현재 원문에 대한 판단을 연결하고 필요한 경우 이번 턴만 제어권을 반환한다.
  - `--kind`: required choices=prompt,status
  - `--reason`: required
  - `--pause`: optional
  - `--source-id`: optional
  - `--auth-token`: optional
- `session preview` — 원문·작업·runner·현재 맥락을 소유권 변경 없이 인수 전에 미리 본다.
  - `--project-id`: optional
  - `--session-id`: optional
  - `--auth-token`: optional
- `session resume` — 종료·작성 해제 확인 뒤 미완료 작업과 현재 맥락을 이어받는다.
  - `--project-id`: optional
  - `--source-session-id`: optional
  - `--target-session-id`: optional
  - `--expected-revision`: optional
  - `--turn-id`: optional
  - `--auth-token`: optional
- `task create` — 현재 원문에서 수행할 결과를 등록한다. 외부 코드는 실행하지 않는다.
  - `--title`: required
  - `--result`: required
  - `--source-id`: optional
  - `--dependency`: optional repeatable
  - `--start`: optional
  - `--auth-token`: optional
- `task report` — 실제 수행 결과를 원 작업 또는 수신한 배정에 연결한다.
  - `--summary`: required
  - `--reference`: required repeatable
  - `--task-id`: optional
  - `--delegation-id`: optional
  - `--outcome`: optional choices=succeeded,failed,partial
  - `--remaining`: optional
  - `--exit-code`: optional
  - `--auth-token`: optional
- `task update` — 현재 조회한 개정으로 실제 수행·외부 대기·사용자 정정을 기록한다.
  - `--action`: required choices=start,wait,resume,correct,cancel,accept
  - `--task-id`: optional
  - `--delegation-id`: optional
  - `--reason`: optional
  - `--target`: optional
  - `--condition`: optional
  - `--resume-scope`: optional
  - `--title`: optional
  - `--result`: optional
  - `--source-id`: optional
  - `--monitor`: optional choices=pull_request,output
  - `--poll-budget`: optional
  - `--monitor-event`: optional
  - `--auth-token`: optional
- `workflow report` — 호스트에서 실제 수행한 현재 단계 또는 독립 평가의 판단을 보고한다.
  - `--run-id`: required
  - `--summary`: required
  - `--reference`: required repeatable
  - `--check`: optional repeatable
  - `--status`: optional choices=pending,running,waiting,succeeded,failed,skipped
  - `--accepted`: optional
  - `--auth-token`: optional
- `workflow revise` — 원 목표를 바꾸지 않는 방법 변경 또는 사용자의 회고 선택을 반영한다.
  - `--run-id`: required
  - `--reason`: required
  - `--definition`: optional
  - `--reflection`: optional choices=unasked,offered,requested,declined,unanswered
  - `--auth-token`: optional
- `workflow show` — 패키지·스킬 파일이 바뀌어도 기존 고정 정의와 시도를 변경 없이 읽는다.
  - `--run-id`: required
  - `--auth-token`: optional
- `workflow start` — 현재 작업에 요청에 맞게 선택한 실제 스킬 절차를 연결한다.
  - `--task-id`: required
  - `--skill`: required
  - `--definition`: optional
  - `--auth-token`: optional

## Execution and recovery

Reuse work linked to the observed original source; create only missing work, select a matching skill when needed, perform its steps with host tools, and report actual evidence. Independent evaluation reads original sources and the full TODO; delivery is not task success. A changed method does not require a new user goal. Preserve required result evaluation.

The Stop hook checks the latest tasks without running a model. Cancellation, external waiting and errors are not success. Ordinary shell tools and recovery remain available. Resolve only the actual dependency; do not ask the user to repair internal revisions or repeat approvals.

Use `memory update` for current facts and `memory checkpoint` for reports. After compaction the hook restores current context; if it provides a complete-context file, read it before continuing. Requested reflection is optional and retractable. Prior lessons do not override current instructions.

Installations preserve unrelated instructions and hooks. Hook trust and sandbox permissions belong to the host. File installation alone does not prove activation. Never edit trust hashes or fabricate a successful native connection.
