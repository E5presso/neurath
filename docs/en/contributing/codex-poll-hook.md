# Codex polling hook compatibility

[한국어](../../ko/contributing/codex-poll-hook.md)

Neurath's wave guard needs a host event before a blocking wait. Codex's code mode
normally applies hooks to nested tools, but releases that opt `write_stdin` out
of `PreToolUse` leave polling outside that boundary. Rejecting every JavaScript
wrapper also rejects ordinary nonwaiting work and does not repair the transport.

The contributor patch in `tools/compat/codex-write-stdin-pretooluse.patch` removes
that opt-out. The common dispatcher then emits the actual `write_stdin` name and
JSON arguments before accessing the process. Existing stdin approval and process
identity checks remain in place. The original command still receives its one
matching Bash `PostToolUse` when it completes.

The adjacent JSON records the exact upstream tag, commit, patch digest and tests.
Apply it only to that source revision, or independently re-review a port. This is
a separate host build: the Neurath wheel neither bundles Codex nor uses another
repository as a package build input.

## Agent execution reference

Follow the upstream repository's development instructions and pinned toolchain.
Apply the patch in an isolated Codex checkout and run:

```sh
just fmt
just test --cargo-profile dev-small -p codex-core --test all -E 'test(suite::hooks::pre_tool_use_blocks_nested_write_stdin_before_input) | test(suite::hooks::post_tool_use_blocks_when_exec_session_completes_via_write_stdin)'
cargo build --profile dev-small -p codex-cli --bin codex
```

Provide the matching `codex-code-mode-host` next to the executable, preserving its
existing isolation settings. The regression uses a real yielded process ID for
both empty polling and input delivery; it also verifies ordinary nested work and
the original command's completion event.

Run `tools/native_stop_probe.py` and `tools/native_wave_probe.py` with an explicit
`--codex-bin`, `--model`, already trusted `--project` and local `--output`. The Stop
probe checks the same native turn's attempted final response, blocked Stop, task
resolution and successful Stop in order. The wave probe requires the project's
claim to be released first, acquires its own read-only diagnostic claim, and
returns it after both children report and their results are consumed. Never
force another session's claim or change trust to make the probe pass.

The SDK's `codex_bin` setting selects a standalone app-server executable. Desktop
activation is a separate observation: verify the actual executable and native
event after reconnecting. A local compatibility binary or successful standalone
probe does not by itself replace a running desktop process.

See [host boundaries](hosts.md) and the [collaboration contract](collaboration-contract.md).
