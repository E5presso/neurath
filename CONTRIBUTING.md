# Contributing

[Home](README.md) · [한국어](CONTRIBUTING.ko.md)

The fresh 0.3.0 candidate separates domain rules, application operations, persistence, and host integration. Read the [acceptance specification](docs/en/specification.md) before changing a lifecycle rule. Requirements are targets; describe a validation as passed only when you have the actual result.

## Structure

The domain owns entities and invariants without depending on the persistence adapter. Application operations coordinate repositories through a unit of work. SQLAlchemy implements persistence and Alembic owns schema evolution. MCP exposes the supported application surface under the single server name `neurath`. Host adapters are responsible for native context; caller-provided protocol arguments cannot establish independent host attestation.

## Changing behavior

Keep changes narrow and preserve unrelated local work. Add a meaningful test when changing ownership checks, stage ordering, evidence scope, delegation acceptance, transaction behavior, idempotency, lease fencing, or migration behavior. A test that merely duplicates a version string does not establish correctness.

For a new operation, document its actor, owned resource, legal starting state, expected revision, inputs, output, durable effects, and failure cases. Make retries explicit. Define whether a key replay returns the original result or rejects conflicting input. A failed transaction must leave no partial lifecycle change.

## Validation

Use distinct checks for:

1. Domain rules: reject unauthorized writes, out-of-order phases, unrelated evidence, and premature completion.
2. Storage: verify atomic rollback, competing revisions, repeated requests, released leases, and stale generations.
3. Migration: preserve complete original data, account for unfinished tasks, reject future schemas without writes, and verify repeatability.
4. Recovery: exercise bypass against an unusable operational database and verify restoration material.
5. Protocol: enumerate and call the actual exposed tools, including invalid inputs and recorded failures.
6. Native host: obtain an observation from the real integration using the intended installed distribution.

Report the exact checks run and their outcomes. Do not substitute a package test for protocol invocation or native activation. An unavailable host check must remain explicitly unverified.

## Development commands and catalog

From the repository root, synchronize the locked environment and run the required validation entrypoint:

```sh
uv sync --locked
uv run --locked python tools/check.py
```

The check entrypoint runs Ruff, pytest, and a wheel build in order. It emits `NEURATH_CHECK_OK` only after those commands succeed. This marker does not establish native host activation.

Prepare a local installation into this checkout or an explicitly selected project:

```sh
./setup --self
./setup /target/project
```

An installation provides a `.neurath/run` wrapper. The module entrypoint also supports explicit root and provider arguments:

```sh
uv run --locked python -m neurath --root . status
uv run --locked python -m neurath --root . mcp --provider codex
uv run --locked python -m neurath --root . hook --provider claude-code
```

`mcp` consumes newline-delimited JSON-RPC on standard input. `hook` consumes host hook input; invoking it without a real native event does not prove host activation. Both providers are accepted by each transport command.

The recovery switch can be inspected or changed without opening the operational database:

```sh
uv run --locked python -m neurath --root . bypass
uv run --locked python -m neurath --root . bypass --enabled true
uv run --locked python -m neurath --root . bypass --enabled false
```

The MCP tool `harness_bypass` provides the same worktree-local recovery function with an optional boolean `enabled`. It suspends Neurath hooks; it does not grant host permissions or complete tasks.

### Protocol catalog

MCP wire names use underscores; application commands use dots. For example, call `session_get`, `task_create`, `task_activate`, and `verification_prepare` through MCP for the conceptual commands `session.get`, `task.create`, `task.activate`, and `verification.prepare`. The table below uses conceptual command names; replace each dot with an underscore when calling MCP. `harness_bypass` already uses its wire name. The server name remains `neurath`.

Use MCP `tools/list` for the current closed input schemas. Each application tool and `verification.prepare` require a fresh `_call_id` to correlate the exact native invocation. Mutating application operations also require `request_id` for idempotency; verification preparation instead rejects a second pending execution of the same command by the same actor. Operations that update versioned records require the documented `expected_revision`; read the record before constructing a new mutation. Unknown fields are rejected.

| Area | Operations |
| --- | --- |
| Session | `session.get` |
| Tasks | `task.create`, `task.get`, `task.list`, `task.adopt`, `task.activate`, `task.resume`, `task.wait`, `task.withdraw`, `task.revise`, `task.complete` |
| Ordered phases | `phase.start`, `phase.complete` |
| Criteria and evidence | `criterion.satisfy`, `evidence.record`, `evidence.list` |
| Delegation | `delegation.prepare`, `delegation.start`, `delegation.report`, `delegation.accept`, `delegation.reject`, `delegation.cancel`, `delegation.list` |
| Communication | `message.send`, `message.list`, `message.ack` |
| Checkpoints | `checkpoint.save`, `checkpoint.list` |
| Writer leases | `lease.acquire`, `lease.release`, `lease.check` |
| Native checks | `verification.prepare` |
| Recovery | `harness_bypass` |

`evidence.record` records an agent report. It cannot forge a native tool result or human approval. `message.ack` acknowledges delivery without accepting delegated work. `task.revise` requires a new user source and invalidates old verification. `task.withdraw` requires native approval linked to the task. Leases coordinate ledger writers; they do not grant permission to the host filesystem.

`task.adopt` resumes ownership of unfinished work from an ended session only with a new native user instruction. It preserves the original archived source. This is an explicit ownership change, not an implicit result of importing or reading the task.

### Native verification

Configure named checks in `.neurath/project.json` under `verification`. A check contains an `argv` list, optional `cwd` within the checkout, and optional `success_codes` list that defaults to `[0]`. For example:

```json
{
  "verification": {
    "project": {
      "argv": ["uv", "run", "--locked", "python", "tools/check.py"],
      "cwd": ".",
      "success_codes": [0]
    }
  }
}
```

For an active owned task, call the MCP tool `verification_prepare` with `task_id`, `check_name`, and optional `criterion_id` or `phase_id`, plus the native `_call_id`. The response contains `execution_id`, `state: prepared`, and a `native_action` naming `exec_command` with `cmd` and `workdir`. The returned command runs `.neurath/run check-run` with that execution identifier. Execute the returned action once through the native host.

The native pre-tool observation binds the prepared execution before the runner starts. The runner executes the stored argument list as a subprocess and records its actual return code directly. JSON-looking standard output or a printed success marker cannot forge that result. The runner persists evidence independently of rendered host tool output. Call the MCP tool `evidence_list` afterwards and use the applicable evidence in the phase or criterion transition.

Starting the runner does not itself establish success. Wait for persisted completion evidence before satisfying a criterion or completing a phase. If execution is interrupted, inspect its stored state and evidence before deciding how to continue; this design does not promise automatic recovery from every cancellation or process termination.

The protocol does not offer arbitrary shell execution or launch external agents. Native host tools perform actual work; an invocation or report is not a substitute for its observed outcome. See the [candidate verification record](docs/en/candidate-status.md) for observed tests and native lifecycle results.

### Stop and continuation

When unfinished work remains, the first Stop hook requests continuation. If the host reports `stop_hook_active: true` on a subsequent stop, the hook yields while retaining unfinished work. This prevents an endless loop of blocker reports. Yielding does not complete, withdraw, or cancel a task; resume it with its existing owner, phase, and evidence when continuation is possible.

### Trust changed Codex hooks

After installation or a hook definition change, open `/hooks` in the Codex CLI, review the current Neurath hook definitions, and explicitly trust the intended definitions. Codex binds trust to the exact definition hash and skips new or changed non-managed hooks until the user reviews them. See the [official hook trust instructions](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks).

After that user action, observe a real native event and a bound MCP call, then run a configured check and read its persisted evidence. Tool discovery alone does not complete these steps. Keep native activation pending until those observations exist; do not edit trust records or fabricate a receipt to satisfy this gate.

## Documentation

Maintain matching English and Korean pages under `docs/en/` and `docs/ko/`. Keep language-local navigation in the same language, with explicit translation links. Update both root README and contributing variants when their scope changes. Use natural-language workflows in user pages and keep agent-facing commands here.

Do not include private local paths or unrelated repository names in public documentation. Distinguish requirements, implemented capability, and observed validation. Never publish, push, deploy, install, or restart a host on the assumption that writing documentation authorizes it.
