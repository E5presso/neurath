# Installation development and MCP integration

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

**English** · [한국어](../../ko/contributing/installation.md)

[Contributing](index.md) · [Bootstrap reference](setup-reference.md) · [Task tools](task-tools.md)

This reference is for contributors developing installation behavior or validating agent integration.
Ordinary users request outcomes through the [installation guide](../usage/installation.md).

## Bootstrap and installed administration

Before first installation, the target has no Neurath MCP server. The source's
`./setup /target/Git-root` prepares the independent tool environment and installer as bootstrap infrastructure.
Use `./setup --self` for the Neurath development repository. Preserve project dependencies and development environments.

Once the server is installed and active, administer the harness through named MCP tools.

| Purpose | Tool | Observation |
| --- | --- | --- |
| Readiness | `session_status` | Installation, activation, actual mode and ownership separately |
| Plan | `installation_plan` | action, optional hosts/profile/skill_prefix, stable key; summary and plan reference |
| Apply | `installation_apply` | Returned plan_ref and key; actual application result |
| Recover interruption | `installation_recover` | Existing journal versus current files |
| Integrity and placement | `diagnostics_integrity`, `diagnostics_project` | Package contents versus installed locations |
| Protocol | `diagnostics_project` with protocol=true | Simulated host event checks |

Plan actions are install/update/uninstall/restore. Restore uses the installation_id of an existing application.
Only registered immutable plans can be applied, and original file contents are not exposed in tool responses.
Preserve conflicting files and inspect the cause. Do not ask again when existing user authorization already covers the action.

```json
{"tool":"installation_plan","arguments":{"action":"update","key":"inspect-current-update"}}
```

The native host may need to reload its catalog after installation. Source changes or successful installation
do not establish that new tools are available in the current conversation. Verify actual trust, authentication and hook loading.

## Distribution development

These commands develop and build Neurath itself; they are distinct from agent-facing harness operations.

```sh
uv sync --locked
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv run --locked python -m build
```

Execution asset sources live in `src/neurath/_assets`. `.agents/skills` and `.neurath/rules` are installed outputs.
Perform manifest generation, package checks, building and self-installation separately. Launchers use isolated
Python execution so target packages with matching names cannot shadow the bundled engine.

## Project bindings and checks

Only the `generic` profile is supplied. Bind documents and verification in `.neurath/project.json` to the actual
target's instructions. Do not invent missing documents or select a check merely because a tool exists.
To run exact pytest nodes, bind the project's test environment through verification.pytest.argv.
This internal configuration stores an executable array; agents do not reconstruct harness CLI options on every call.

`verification_run` accepts a bound project check name, `verification_builtin` a built-in check kind, and
`verification_nodes` an array of exact test nodes.

```json
{"tool":"verification_nodes","arguments":{"nodes":["tests/test_example.py::test_example"],"key":"check-example"}}
```

Metadata language, title conventions and branch rules belong to the target project. Give `worktree_cleanup`
actually verified `base_branch` and `remote_ref` values. Never edit generated state files or force ownership recovery.

Discover operation usage through the [named catalog and schemas](task-tools.md).
Distribution integrity, installed placement, protocol fixtures, live activation and model execution are distinct evidence scopes.
