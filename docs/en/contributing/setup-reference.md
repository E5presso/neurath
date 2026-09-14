<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Bootstrap and setup execution reference

[한국어](../../ko/contributing/setup-reference.md)

Bootstrap prepares Neurath's own execution environment and then invokes its transactional installer. An active installation uses named MCP operations for routine administration. This reference covers the source launcher and CLI used before that integration exists, by setup fixtures, and for the explicit diagnostic recovery paths.

## Runtime selection and prerequisites

Run source setup from the Neurath checkout with an explicit target:

```sh
./setup /absolute/path/to/your-project
```

On macOS or Linux, the launcher requires Git and can obtain `uv` from its official installer when it is unavailable. It provisions Python 3.14, builds the bundled distribution, and installs a persistent content-addressed tool environment. The global `neurath` entry point switches only after target installation succeeds. Reusing identical distribution content verifies and reuses the existing tool environment.

The project `.venv`, dependency declarations, lockfiles, and shell startup files are preserved. Neurath's developer `.venv`, its installed tool environment, and the target application's runtime are separate environments. Updating one project's integration does not repoint every other project's installed launcher. Retained prior tool environments support recorded restoration.

```sh
NEURATH_NO_BOOTSTRAP=1 ./setup /absolute/path/to/your-project
```

This disables the fallback `uv` download; it does not make missing prerequisites available. If Git is absent or the target is not a Git worktree root, resolve that prerequisite before retrying. A newly requested target can be initialized with `git init` as part of setup.

## Supported setup forms

| Invocation | Effect |
| --- | --- |
| `./setup /absolute/path/to/your-project` | Bootstrap the tool runtime and install the target |
| `./setup --self` | Install this source checkout using the built tool runtime |
| `neurath setup` | Install or reconcile the current project using the available distribution |
| `neurath setup /absolute/path/to/another-project` | Install the selected target |
| `neurath setup --dry-run` | Return target path/action changes without writing target files |
| `neurath setup --json` | Return the structured setup result |
| `./setup /path/to/project --host codex` | Select the Codex integration |
| `./setup /path/to/project --host claude-code` | Select the Claude Code integration |
| `./setup /path/to/project --skill-prefix neurath-` | Place Neurath skills under prefixed public names |

The first default is `generic` with both hosts. `--host` can be repeated. Subsequent omitted profile, hosts, and prefix retain installed values. Only `generic` is supported. The prefix is empty or matches `[a-z][a-z0-9-]*-`; `neurath-` maps `debug` to `neurath-debug`. Setup, plan, install, update, and wizard support prefix selection. An installed prefix cannot be changed in place; uninstall first. A default or prefixed name already owned by a user skill remains a conflict.

A source `./setup --dry-run` may still prepare the separate tool environment before computing the target preview. The installed `neurath setup --dry-run` writes no target files. The preview contains paths and actions, rather than exposing original file contents.

`--auto-report yes|no` records an explicit user reporting choice when supplied. Omitting it preserves the current choice. Setup authorization alone does not establish reporting consent; the [reporting guide](../usage/reporting.md) explains its scope.

## Interpret structured output

A setup preview has `status: planned`, `root`, `profile`, `hosts`, `skill_prefix`, reporting status, and `changes` entries containing `path` and `action`. Applied setup additionally returns `receipt` with the installation ID and changed count, `doctor`, and next steps. Its final `status` is `passed` or `failed` according to local diagnostics. A failed diagnostic can follow a completed file application, so retain the installation ID for investigation.

The diagnostics separate distribution, placement, protocol, and host activation. Startup JSON accepted by an isolated hook subprocess and malformed input rejected by it establish protocol compatibility. Native host activation remains unverified until observed in the actual host. A user may still need to trust the project, authenticate the provider, or reload the session. These are specific host interactions, not configuration chores to delegate back to the user.

## Save a plan without applying it

The interactive wizard uses the same `make_plan` and `apply_plan` engine and supports a plan-only result:

```sh
neurath --root /absolute/path/to/project wizard --output /private/path/neurath-plan.json
```

A private explicit plan can also be created and then applied by the bootstrap CLI:

```sh
neurath --root /absolute/path/to/project plan --action update --output /private/path/neurath-plan.json
neurath --root /absolute/path/to/project apply /private/path/neurath-plan.json
```

The output must be new and must not be a symlink. The default wizard storage is a mode-`0600` plan under the Git administrative `neurath-plans` directory. Plans contain original file information; retain them privately. Applying them rechecks the target and distribution. Do not edit a plan to work around a conflict.

For restore planning, pass `--action restore --installation-id INSTALLATION_ID`; `--receipt` is a compatibility alias for that same identifier. The ID names the completed operation to reverse. The [transaction reference](installation-design.md) explains how restore differs from interrupted-operation recovery.

## Bind the real application procedures

Agents maintain `.neurath/project.json` from the project's actual instructions. This illustrative generic binding connects document roles and a real check; substitute only verified project paths and commands:

```json
{
  "schema": 1,
  "documents": {
    "intent": "docs/product.md",
    "glossary": "docs/glossary.md",
    "decisions": "docs/decisions/"
  },
  "verification": {
    "check": {
      "argv": ["npm", "test", "--", "--run"],
      "cwd": ".",
      "success_codes": [0],
      "timeout_seconds": 300
    }
  },
  "protected_capabilities": {
    "connectors": [],
    "paths": ["docs/product.md"]
  }
}
```

`argv` is an argument array, not shell text. `stdout_contains` can add a required output condition. For exact pytest selection, use the actual project environment through `verification.pytest.argv`, such as `uv run --locked pytest`, and preserve the requested selector, for example `tests/test_example.py::test_example`. Missing checks remain unverified; empty document roles must not be filled with unrelated files.

The internal registered verification path compares repository fingerprints before and after and rejects changes even if the process exit code is accepted. Running a normal native command does not automatically create that compatibility verification record. A `worktree_cleanup` binding requires an independently checked `base_branch` and `remote_ref`; do not infer them from a naming convention.

To copy the independent packaged corpus for inspection, use `neurath corpus /path/to/new-directory`. It requires a new directory and reads bundled resources, without importing another project's files.

Sources: [bootstrap launcher](../../../setup), [CLI parser](../../../src/neurath/cli.py), [setup service](../../../src/neurath/install/setup.py), [transaction engine](../../../src/neurath/install/transaction.py), [bootstrap fixture](../../../tools/validate_setup.py).
