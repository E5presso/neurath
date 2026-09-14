<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Give an agent a working Neurath installation

[한국어](../../ko/contributing/installation.md) · [Contributor entry](index.md)

A project is ready for Neurath work when the package is installed, the project's instructions and checks are connected, and the selected coding host has actually loaded the integration. This guide walks an onboarding agent through those steps. A user can request the same work in natural language; see the [user installation guide](../usage/installation.md).

**Installation** places the managed files and records their origin. **Activation** means Codex or Claude Code has loaded the hooks and tools in a real session. The **runtime** is the separate Python environment that executes Neurath. Keeping these terms separate makes a common failure understandable: correct files can coexist with a host that has not trusted or loaded them.

## Prepare the target and the tool environment

Read the target's instructions and inspect its current changes before choosing hosts or file names. The target must already be a Git worktree root; an empty Git repository is supported. On macOS or Linux, Git is required. The source bootstrap can obtain `uv` from its official installer and prepare Python 3.14. It leaves shell profiles and the target's dependency environment alone.

From the Neurath source checkout, an authorized onboarding agent can preview a target installation:

```sh
./setup /path/to/saved-filter-project --host codex --dry-run --json
```

The path is illustrative: substitute the user's actual Git root. This command may prepare an external tool environment, even though `--dry-run` leaves target files unchanged. Review the returned `changes`, selected `hosts`, `profile`, and `skill_prefix`. Apply the selected setup by omitting `--dry-run`:

```sh
./setup /path/to/saved-filter-project --host codex --json
```

A fresh installation defaults to the `generic` profile and both supported hosts when host selection is omitted. Repeated setup preserves recorded choices. If a project already owns a skill with a conflicting name, a new installation can use `--skill-prefix neurath-`, yielding names such as `/neurath-debug`. Existing project skills keep their names. Changing an installed prefix requires uninstalling first; a prefix does not settle competing harness instructions.

The bootstrap builds a content-addressed, persistent tool environment. Each project's launcher points at its selected interpreter, so preparing another version for another project does not silently replace the first project's runtime. The stable `neurath` command is published only after successful target setup. `NEURATH_NO_BOOTSTRAP=1` disables automatic `uv` download.

## Connect the project's meaning and its checks

Neurath installs `.neurath/project.json` with empty `documents` and `verification` objects when no binding exists. A binding tells the agent where this project's requirements live and how the project checks its work. The agent should inspect existing files and commands before filling these entries.

For example, suppose the user's web application loses its saved filter after a browser refresh. If that repository already has `SPEC.md` and an `npm test` command, an illustrative binding is:

```json
{
  "schema": 1,
  "documents": {"intent": "SPEC.md"},
  "verification": {
    "project-check": {
      "argv": ["npm", "test"],
      "cwd": ".",
      "success_codes": [0],
      "timeout_seconds": 300
    }
  }
}
```

This is a hypothetical application example, not a Neurath filter feature or a universal JavaScript setup. Substitute the repository's real document and verifier. `argv` is an argument array rather than shell text; `cwd` stays inside the repository. See [verification configuration](setup-reference.md#configure-a-project-verifier) for limits and result interpretation. User-edited project bindings survive update and uninstall.

## Check what was installed, then observe the host

The setup result includes a **receipt**, a retained record identifying the installation change, and a diagnostic report. Keep the record in private project state: it can identify the installation to restore. The report checks distribution integrity, owned file placement, and local hook protocol behavior. A successful protocol check still reports host activation as unverified.

For an installed native session, ask the diagnostic tool to include protocol checks:

```json
{"protocol": true}
```

The tool name is `diagnostics_project`. Read `.neurath/policy.md` and `.neurath/project.json`, then inspect the actual session and currently exposed tools as described in [contributor onboarding](index.md). In Codex, review project trust and the exact Neurath hooks in `/hooks`; in Claude Code, inspect hook loading in `/hooks`. Observe the next normal host event and confirm that the running integration belongs to the intended worktree and distribution. See [host integration](hosts.md) for native evidence.

Only then continue the saved-filter repair with a task whose result is visible in the application. Installation diagnostics establish the harness setup; the application's own reproduction and tests establish whether the filter survives refresh.

## Continue from an installation problem

If setup applied files but diagnostics failed, retain the receipt and inspect `diagnostics_project` with `protocol=true`. Do not describe that result as complete activation. A `stale plan` means the target changed after preparation: inspect those edits and prepare a new plan. A modified managed block or skill conflict means the installer cannot safely combine ownership; preserve the file and resolve that specific conflict.

An interrupted transaction has its own recovery route, `installation_recover`, followed by diagnostics and a fresh plan. [Installation design](installation-design.md) explains how originals are retained and why recovery stops on concurrent edits. [Setup reference](setup-reference.md) supplies the exact named-tool and bootstrap command forms.

## Develop Neurath itself

The development environment and the installed runtime serve different purposes:

```sh
uv sync --locked
./setup --self --json
```

The first prepares this checkout for development; the second explicitly installs this checkout into itself using a separate persistent runtime. Run self-installation only when it is part of the authorized work. For an executable asset change, follow the manifest, check, build, and installation sequence in [asset development](assets.md). A documentation change alone uses the focused documentation checks in [validation](validation.md).

Source: [setup bootstrap](../../../setup), [setup service](../../../src/neurath/install/setup.py), [runtime preparation](../../../tools/setup_runtime.py). Tests: [setup behavior](../../../tests/test_setup.py), [installer preservation](../../../tests/test_installer.py).
