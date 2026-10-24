# Host hooks and execution lifecycle

[Documentation](index.md) · [Task ledger](task-ledger.md) · [Phase execution](workflow-runner.md) · [한국어](../ko/host-runtime.md)

The agent works inside an existing Codex or Claude conversation. Installed rules introduce the CLI and skills; hooks preserve actual host events. The stateless core reads the same user SQLite store for each request. Reasoning, shell commands, file edits, and native child creation remain host operations.

## From original instructions to work

`SessionStart` connects the project and actual host/child address and restores current context. `UserPromptSubmit` preserves original input independently of TODO entries. The agent reads `context show` and `context show --section sources`, then creates work and selects a skill only when the request calls for work. Simple questions require no task.

The adapter preserves Codex `turn_id` and Claude `prompt_id` when provided. Otherwise it assigns an internal `observed:` sequence to the received event. This is neither a fabricated native identity nor approval evidence. Tool events use the current observed turn and actual tool-call ID. Separate user utterances containing the same text remain separate sources.

CLI calls resolve project, session, and peer from the host environment, actual directory, and stored addresses. Claude receives its address through the official `CLAUDE_ENV_FILE`. Ambiguous addresses are not guessed; `--session` can select an already observed address. Humans do not manage internal UUIDs or optimistic revisions.

## File coordination and tool permissions

`Writer` coordinates concurrent writes only to actual file paths declared by `Edit`, `Write`, or `apply_patch`. Multi-file patches acquire all paths or roll back together. `Bash` and `exec_command` are not classified as writes by name, and no working-tree-wide lease is imposed. Reads, diagnostics, recovery, and ordinary shell commands need no separate Neurath permission procedure.

Only an actual competing file write returns `PreToolUse.permissionDecision: deny`. Historical paused/cancelled execution state does not veto ordinary tools. Native permissions and sandbox policy still apply. Redelivery of the same call uses the same generation; stale outcomes cannot release a newer owner.

Synchronous file-call completion is observed through `PostToolUse`, `PostToolUseFailure`, a subsequent actual user turn, or `SessionEnd`. Explicitly managed external processes need actual process observations. An empty request-local process map is not evidence about the native host. Neurath neither guesses PIDs nor terminates the whole host application.

## Stopping, waiting, and resuming

`Stop` and `SubagentStop` deterministically inspect applicable TODOs and phase progress without calling a model. Executable unfinished work receives `decision: block` and actionable feedback. Repeated rejection without progress yields instead of creating a model loop. External waits yield normally. Failure, cancellation, and waiting are never recorded as success.

Resolving a dependency emits a standard Task event that resumes the normally waiting execution and peer together. It does not clear cancellation or failure. A new actual user turn can start a new execution without reviving cancelled tasks, monitors, or transferred work. Closing a connection does not itself cancel an already requested external watch.

Selected skills delegate independent outcome evaluation through the runner to actual peers, native children, or providers. Evaluators receive original sources and the full TODO. The executor reads their report, addresses relevant findings, then reports the task result. Stop never creates another evaluator or imposes unrelated root work on a child.

## Output, failures, and validation

`neurath hook handle --provider codex|claude` reads one actual host JSON event and emits one JSON response. Message/article headlines and monitored changes are recorded as submitted only after stdout returns. Body reading, ACK, acceptance, and task success remain distinct. Output failure is journaled independently rather than recorded as successful delivery.

Ordinary hook or DB failures report unverified bookkeeping while retaining access to recovery tools. Stop failures and unchanged monitor callbacks end without repeatedly starting model work. `--bypass` suspends only harness enforcement, not native permissions or result verification. See [recovery](recovery.md).

`maintenance install` updates only managed areas. Native trust belongs to the host. File installation, JSON generation, and actual model-context delivery are separate evidence. Validate against the actual [Codex](https://learn.chatgpt.com/docs/hooks) and [Claude](https://code.claude.com/docs/en/hooks) contracts.

Ordinary requests start deferred transactions; reads do not reserve the SQLite writer. Only explicit schema migration reserves writing. External observations and model executions run outside DB transactions. Rolled-back session-registration and hook conflicts receive bounded rereads. Migration `core_0014` preserves runtime, writer, and delegation history.
