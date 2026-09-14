<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/design-principles.md)

# Decisions that keep the harness understandable

A harness should make the user's requested outcome easier to reach and easier to verify. Every new state record, required transition or injected instruction should have one identifiable responsibility. A design that records the same completion decision several times needs a simpler authority model before it needs more automation.

## Begin with the user's outcome

Define work in terms of an observable result, its source and acceptance conditions. A repository fact, a current user decision and a reversible assumption are different inputs. The goal and gap models retain those differences so that the agent can continue independent work without converting an assumption into permission.

Current user instructions and current source take precedence over memory, peer suggestions and generated plans. A side question can refine an active task without cancelling it. A cancelled or superseded task is recorded explicitly with its reason; deleting it from a display loses the requested-work history.

## Support reflection without becoming the judge

Neurath's central strategy is to return the original task purpose and acceptance conditions to the agent's attention during work. The agent can then ask whether the next step advances an unmet user requirement or only improves its chosen method. A method may be replaced or dropped while the original task remains in force.

The reminder is context for metacognition, not a quantitative measure of semantic goal convergence. It creates no separate reflection report, task, evaluation loop, or completion gate. Time and token limits constrain waste; they do not authorize weaker acceptance or turn one failed attempt into task cancellation. A status question likewise does not authorize new scope.

Keep investigations proportional to the relevant acceptance conditions. The harness evaluation skill does not require unlimited inventory or generation merely to satisfy its own process. Other skills retain their applicable iteration contracts. Checks use the existing project runner. See [runtime reminders](runtime-lifecycle.md) for the delivery contract.

## Give each decision one owner

| Decision | Authority | Useful supporting information |
| --- | --- | --- |
| Is registered work settled at Stop? | Latest canonical task list, checked atomically with root-turn closure | Native TODO display, owner result references |
| May this participant change this worktree? | Verified caller plus current owner lease and fencing token | Session diagnostics and worktree identity |
| May a contracted workflow advance? | Its current phase contract and applicable evaluation authority | Evidence artifacts, findings and reports |
| Has a delegated result been accepted? | Authenticated report and the required owner's consumption | Transport status and peer discussion |
| Was an installation applied? | Transaction outcome and installed content verification | Plan preview and retained restoration material |
| May content be published externally? | Applicable user authorization and exact publication contract | Prepared draft and local validation |

For ordinary tasks, the owner records a terminal result once. A separate workflow, material batch, per-criterion acceptance report or independent task reviewer is not required. Explicit evaluation and review workflows continue to enforce their own contracts when invoked. Their evidence should not become an additional generic Stop vote for a session that has a task list.

## Use native authority at the boundary

The host supplies session identity, current turn and child lineage. Neurath validates those facts before it accepts a mutation. Neither a payload field, a copied environment value, an arbitrary process identifier nor a peer's claim can create this authority.

Keep admission tied to the exact operation and input. An approval for a concrete action cannot be expanded to another action by changing arguments after review. A native tool's completed test result also remains a completed observation when the user later asks a question; later turn state must not rewrite what the test actually did.

Failure should identify which boundary is unavailable: caller identity, active turn, worktree ownership, provider mode or external delivery. A rejected mode is a supported-limit result. Do not introduce a less constrained shell path to make the same request appear successful.

## Make concurrency and retries part of the contract

State changes use returned identifiers and expected revisions. A list revision protects a collection; a task revision protects a particular task. A fencing token protects the current generation of worktree ownership. These values cannot be inferred from a title, a previous session or a neighboring worktree.

An idempotency key names one exact request. Retry the same uncertain request with the same key. If the intended input changes, obtain current state and use a new key. Reusing a key with different input is a conflict, not an update mechanism.

Put read-and-decide operations that must agree in one transaction. The task Stop check and turn closure are the representative case: a concurrent append must either be visible to that closure or occur after it under valid admission. Checking an old snapshot and then closing separately permits lost work.

## Keep reporting proportional to assurance

| Observation | What it establishes |
| --- | --- |
| `accepted` or queued operation | Admission of a request |
| Native process start | An execution began |
| Check output and exit status | The observed check result within that execution's scope |
| Owner task result | The owner's authenticated account of the outcome |
| Independent evaluation consumed | The required evaluator assessed the exact candidate and the owner consumed that result |
| Remote readback | The external system contains the observed publication or update |

A message acknowledgement does not consume an assignment result. A checkpoint preserves context and progress. Neither is a worktree ownership transfer. Keep these distinctions in result objects and in user-facing reports without repeating every boundary in every paragraph.

## Preserve the host and the project

The generic profile binds to real project documents and checks. It does not prescribe an application framework or replace existing dependencies. Installation preserves user instructions, hooks, host permissions and edited project settings. Immutable plans allow conflicts to be reviewed before applying exact replacements.

Host adapters should translate native events into the common model while retaining host-specific evidence. Codex and Claude Code need different child verification procedures; forcing identical payload shapes would conceal that difference. Runtime execution environments remain separate from the target application environment.

## Bound retained context

Memory should retain decisions and facts needed for future work, with provenance and size limits. It should not collect hidden reasoning or make every remembered preference an active rule. Keep recent-session facts, project history, learned strategies and approved repository rules distinct. Recheck mutable repository and runtime facts before relying on them.

Publish reusable behavior and source references. Keep installation originals, native transcripts, host identifiers, private paths and detailed validation receipts in private storage. Public documentation explains how to reproduce a verification dimension without presenting an old run as current acceptance.

## Review a proposed change

Ask whether it has a clear user-visible outcome, one completion authority, exact source and identity binding, bounded failure recovery and a relevant regression test. Remove duplicate help probes and redundant bookkeeping where the named schema already supplies the information. Claims of speed or token savings need measurements; schema simplicity alone establishes a design intention.

Use [architecture](architecture.md) for module boundaries, [task tools](task-tools.md) for operation contracts and [validation](validation.md) for the observations needed to substantiate a change.

## Sources for design review

Use these implementation references to test whether a change preserves the responsibilities described above. Compatibility code is relevant only when reviewing a retained saved-call path.

| Responsibility | Source and regression reference |
| --- | --- |
| Goals, phases and evaluation | [adaptive_control.py](../../../src/neurath/_assets/scripts/agent_harness/adaptive_control.py), [adaptive_control_authority.py](../../../src/neurath/_assets/scripts/agent_harness/adaptive_control_authority.py), [efficiency_assessment.py](../../../src/neurath/_assets/scripts/agent_harness/efficiency_assessment.py), [evaluation_loop.py](../../../src/neurath/_assets/scripts/agent_harness/evaluation_loop.py) |
| Host and exact-call admission | [harness_persona_policy.py](../../../src/neurath/_assets/scripts/harness_persona_policy.py), [mcp.py](../../../src/neurath/agents/mcp.py), [hooks.py](../../../src/neurath/hosts/hooks.py), [identity.py](../../../src/neurath/hosts/identity.py), [tasks.py](../../../src/neurath/runtime/tasks.py), [test_prompt_delivery.py](../../../tests/test_prompt_delivery.py) |
| Messages and provider lifetime | [delivery.py](../../../src/neurath/agents/delivery.py), [store.py](../../../src/neurath/agents/store.py), [permission_inheritance.py](../../../src/neurath/providers/permission_inheritance.py), [supervision.py](../../../src/neurath/providers/supervision.py) |
| Bounded retained context | [graphify](../../../src/neurath/_assets/.agents/skills/graphify/SKILL.md), [promote-memory](../../../src/neurath/_assets/.agents/skills/promote-memory/SKILL.md), [enclave_store.py](../../../src/neurath/_assets/scripts/agent_harness/enclave_store.py), [learning.py](../../../src/neurath/memory/learning.py), [store.py](../../../src/neurath/memory/store.py), [test_learning.py](../../../tests/test_learning.py) |
| Preserving installation and user choices | [projection.py](../../../src/neurath/install/projection.py), [transaction.py](../../../src/neurath/install/transaction.py), [release_install.py](../../../src/neurath/release_install.py), [reporting.py](../../../src/neurath/reporting.py), [maintenance_tasks.py](../../../src/neurath/runtime/maintenance_tasks.py), [user_choices.py](../../../src/neurath/runtime/user_choices.py) |
| Saved-call compatibility | [material_action.py](../../../src/neurath/_assets/scripts/agent_harness/material_action.py), [verification.py](../../../src/neurath/runtime/verification.py) |
