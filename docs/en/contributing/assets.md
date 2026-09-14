<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Change the assets that Neurath installs

[한국어](../../ko/contributing/assets.md) · [Contributor entry](index.md)

An asset change should reach a target project through a built Neurath distribution. Edit the independent source under `src/neurath/_assets`, regenerate its derived metadata, and verify the package and installation behavior appropriate to the change. Editing an installed `.agents/skills` or `.neurath/rules` file changes only that installation and may create an update conflict.

## Locate the source by its purpose

| Purpose | Source | Installed or runtime use |
| --- | --- | --- |
| Agent procedures | `_assets/.agents/skills` | Projected to public skill names in `.agents/skills`. |
| Shared operating rules | `_assets/.agents/rules` | Portable rules under `.neurath/rules`. |
| Workflow contracts and routing data | `_assets/.agents/skills/contracts.json` and related JSON | References under `.neurath/reference`; stable internal contract identities. |
| Runtime implementation | `_assets/scripts` | Imported by the isolated installed runtime. |
| Policy, host wiring, path rewriting | `install/projection.py` | Generates policy, hooks, references, launcher, and operation map. |
| Public naming | `skill_names.py` | Maps internal source names to public invocations. |

All source paths above are beneath `src/neurath`. Other repositories are not build inputs. The target project supplies its own product documents and verification commands through `.neurath/project.json`.

The current inventory has 31 public skills: 29 have phase contracts, while `explain-code` and `graphify` support work without those contracts. Public names describe the work a reader requests; internal identifiers keep persisted workflows stable. For example, source contract `investigate` is invoked as `debug`, and `monitor-pr` as `watch-pr`. A configured `neurath-` prefix changes the invocation to `/neurath-debug` without renaming its internal contract. See [skill reference](skills-reference.md) for the complete mapping.

## Follow a source change into its projection

Projection rewrites bundled paths, public skill names, and engine references for an installed project. It places project-specific document references behind the `documents` bindings and adds the installed policy boundary before skill instructions. Markdown command references are mapped to currently available named tools, with `.neurath/reference/task-operation-map.json` recording the mapping.

This matters when changing a procedure: a working source command is not enough if the generated skill tells an installed agent to use an unavailable operation. Check the source procedure, projected text, current tool schema, and relevant contract together. Current source discovers 128 named tools and retains 138 internal operations; compatibility operations are not automatically public tools. Ordinary edits and tests use native tools without duplicate material or verification bookkeeping. See [task tools](task-tools.md) for the public boundary.

For a saved-filter investigation, the skill should help the agent trace why the user's application loses state after refresh and keep that result in view. Product behavior and repository commands come from the target; the shared asset supplies the investigation procedure.

## Retain meaningful workflow evidence

A phase contract records what a requested procedure needs before advancing. Reading the procedure or writing “passed” does not complete a phase. The current public operations are `phase_start`, `phase_current`, `phase_evidence_prepare`, `phase_complete`, and `phase_finalize`; old `workflow_*` calls remain compatibility paths.

`phase_evidence_prepare` retains immutable evidence tied to the current phase and revision, distinguishing a source observation from an owner's report. Adaptive evaluation additionally needs an independently verified role, the exact candidate, and an authenticated consumed report. Changed source, intent, owner, or workflow revision invalidates stale candidate evidence. Some operational final phases finalize atomically using `terminal_state`; do not finalize the same phase again.

A native test result can support the user task directly. Only create explicit phase/review state where the selected procedure requires it. [Runtime lifecycle](runtime-lifecycle.md) and [skill reference](skills-reference.md) describe the detailed transitions; [collaboration contract](collaboration-contract.md) explains independent evaluation.

## Rebuild the derived metadata and package

For an executable asset change, use the development sequence:

```sh
uv sync --locked
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv build
./setup --self --json
```

The final command is a separate installation action when authorized. New installation behavior starts with a failing test before implementation. The manifest builder also regenerates the catalog's rule and audit indexes, then hashes independent package files. It excludes bytecode/cache files and refuses symlink payload dependencies. Hand-editing a digest to hide a changed asset defeats this check.

`tools/check.py` stops at the first failing stage; `NEURATH_CHECK_OK` appears only after integrity, static diagnostics, package tests, and runtime regressions succeed. A package build verifies a different surface from those source checks. A self-install changes the development project's installed files and still needs a later actual host event to establish activation. Use [validation](validation.md) to choose and report each required observation.

## Keep distribution contents portable

The wheel packages `src/neurath`, including its independent assets and manifest. The source distribution includes both documentation locales and development sources. Private validation output, environment state, Git data, installation records, and provenance stay outside the public payload. The declared runtime dependency belongs to Neurath's tool environment, not the target's dependencies.

Test import independence in a fresh installed wheel environment, including a target with its own `scripts` package. Test projection changes for public names, prefixes, host selections, and preservation of user configuration. A documentation-only edit instead uses publication and structural checks; it does not require rebuilding an unchanged executable payload.

Source: [projection](../../../src/neurath/install/projection.py), [public names](../../../src/neurath/skill_names.py), [manifest builder](../../../tools/build_manifest.py), [package configuration](../../../pyproject.toml). Tests: [independent package](../../../tests/test_independence.py), [skill import boundary](../../../tests/test_skill_import_boundary.py), [prefix behavior](../../../tests/test_skill_prefix.py), [tool guidance](../../../tests/test_mcp_guidance.py).
