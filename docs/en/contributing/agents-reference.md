<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/agents-reference.md)

# Give each participant a verifiable role

Neurath distinguishes the user's active agent, a native direct child, and a separately owned provider session. The distinction determines who may edit a worktree, accept an assignment, evaluate a candidate, and resume after interruption. A visible name or a message describing a role cannot establish that role.

## Select the collaboration shape

| Need | Participant | Authority and lifetime |
| --- | --- | --- |
| Bounded, independent work within the current task | Native leaf child | Verified direct lineage under its native host |
| A separate lifetime, another provider, or required isolation | Owned provider session | Its own recorded provider execution and worktree readiness |
| Information from an existing collaborator | Discovered peer | Authenticated message attribution; its own user's scope remains in force |
| An independent review required by an explicit contract | Bound evaluator | Exact candidate and assignment authority consumed by the owner |

Native leaf children are the default for divisible work already authorized by the task. Creating an independent provider run needs a reason and existing authorization. A received peer request does not authorize new sessions or expand the user's goal. A fork is a separate root with its own verified start and its own worktree claim.

## Establish the caller before state changes

Native hooks bind the actual host, session, foreground turn, worktree, and exact tool input. Caller-supplied IDs do not grant authority. The named MCP schemas are closed; their optional `_neurath_binding` field is host-provided authentication material, not a field to invent in examples or copy between callers.

`session_status` with `{"detail":"full"}` diagnoses installation, activation, policy, session state, and ownership. `session_inspect`, `turn_inspect`, and `worktree_inspect` provide focused state views. Keep their findings separate: installed files do not establish native activation, and a route proposal does not establish effective policy or an acquired claim.

For direct children, the parent calls `delegation_prepare` immediately before the native spawn, with the intended `delegation_id`, `assignment`, and stable `key`. The one-time intent must match actual native evidence. Codex checks the real spawn result and child transcript metadata; Claude checks the parent Agent call reference in the child transcript. A stale, reused, or copied reference cannot create lineage. Late transcript registration may be retried by the first state operation; until verified, child shell and write actions are blocked as `child-identity-unverified`.

Only native direct children are supported in this topology. A nested spawn does not become valid through copied parent identity. Once lineage exists, `delegation_assign` binds `workflow_id`, `delegation_id`, `assignment`, `target`, and `key` for the explicit workflow. Independent evaluation additionally requires the actual evaluation contract and authenticated report consumption.

## Keep one writer per worktree

An authenticated caller claims its worktree with `worktree_claim` using `{}`. Retain the returned lease epoch and fencing token. A lease identifies the current owner; the token prevents a previous owner from writing after ownership changes. Another agent's discovery record, task acceptance, checkpoint, or root identity is not a claim.

To release ownership, `worktree_release` requires `expected_lease_epoch` and `fencing_token` from the actual claim. If the values are stale, inspect the current owner rather than guessing a new token or taking over. A shared worktree can have several readers but must have one authorized writer. Independent provider editing must verify its own target's install, actual activation, effective policy, selected model, and claim first.

For isolated work, use the supported worktree preparation and cleanup procedures described in [the capability map](capability-map.md). Cleanup needs an independently verified base branch and remote reference; it must not assume repository conventions or force an existing owner out.

## Discover and assign existing peers

A peer registers a concise name and summary through `collaboration_register`; the runtime binds the actual identity. Search relevant peers without copying complete conversations:

```json
{"tool":"collaboration_discover","arguments":{"query":"API","limit":10}}
```

Use the exact returned address. A question or proposal uses `collaboration_send`; an ordinary work assignment uses `collaboration_assign` with `to`, `message`, and `key`. The receiver explicitly calls `collaboration_accept` with the returned task ID and reports `started`, `waiting`, `error`, `failed`, `cancelled`, or `completed` through `collaboration_report`. `collaboration_task` reads the assignment record.

Receipt acknowledgement and assignment acceptance are different events. A disconnected receiver must accept again in a fresh verified native turn before doing resumed work; an old unrelated turn cannot be reused. A completed report still needs the issuer's inspection of the requested effects. The [delivery contract](collaboration-contract.md) explains durable full-body reading, ACK, reply, and recovery.

## Resume the original work

Normal host `SessionEnd` preserves resumable session state, tasks, enclave, and claims. A verified `SessionStart` with resume evidence restores the native relationship. Explicit kernel `SessionEnded` is permanent and cannot be revived by another start string. A proper root prompt or native resume can close an interrupted previous foreground turn while preserving unfinished tasks and delegations.

When a task list exists, Stop checks and closes against the latest list atomically in the shared database. Ordinary tasks are resolved by their authenticated owner with direct references and a result summary. There is no additional mandatory checkpoint, learning, TODO, or independent-review completion vote. Explicit phase and review workflows retain their own requirements. See [task tools](task-tools.md) and [the task/TODO contract](task-todo-contract.md).

A verified root turn has one Stop continuation budget to avoid an endless loop. Remaining work is reported as incomplete; a later verified user turn has its own budget. A late Stop cannot close a newer verified turn. An unmatched Stop provides a nonblocking diagnostic without mutating state. Supported app peer delivery can continue an existing goal only with actual transcript and native-turn evidence; it creates no user approval.

## Where to inspect and test

[Host identity](../../../src/neurath/hosts/identity.py) and [hooks](../../../src/neurath/hosts/hooks.py) establish native callers. [SessionKernel](../../../src/neurath/_assets/scripts/agent_harness/session_kernel.py), [StateHandle](../../../src/neurath/_assets/scripts/agent_harness/state_handle.py), and [WorktreeRegistry](../../../src/neurath/_assets/scripts/agent_harness/worktree_registry.py) govern lifecycle, caller access, and ownership.

[Host-lifecycle tests](../../../tests/test_host_lifecycle.py), [prompt-delivery tests](../../../tests/test_prompt_delivery.py), and [worktree-registry tests](../../../tests/runtime/agent_harness/test_worktree_registry.py) exercise these boundaries. A native acceptance run must additionally observe fresh start, actual child lineage, interruption/resume, rejected premature completion, authenticated result consumption, and claim release. A passing simulated protocol or source test is evidence for its own scope.
