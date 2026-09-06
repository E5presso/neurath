# Validation

Neurath checks four different boundaries: distribution integrity, installation behavior,
runtime contracts, and events emitted by real Codex and Claude Code hosts. A successful
`doctor` result covers local placement and protocol checks; it does not grant host trust.

## Latest checks — 2026-09-07

| Boundary | Result |
| --- | --- |
| Package and installer tests | 408 passed on macOS and Linux |
| Runtime contracts | 1,035 tests passed on each platform; Linux also reported 539 subtests |
| Runtime manifest | 243 files; source, wheel, and self-installed copy agree |
| External wheel | Empty, Python, and JavaScript repositories passed |
| Quick installer | Real uv/Python bootstrap, three repository types, and a fresh self-hosting checkout passed |
| Immutable runtime updates | Real uv bootstrap preserved another project's files and interpreter after successful, conflicting, and dry-run updates; warm-cache rebuilding, exact restoration, and no-op reuse passed |
| Shared instruction edits | Update and removal preserved user edits outside intact Neurath blocks; modified managed blocks remained conflicts |
| Native Codex and Claude Code | Fresh sessions on the tested wheel passed activation, command execution, canonical state read-back, and checkpoints |
| Codex steering and resume | Native commands and turn records verified mid-turn steering, interruption, and a fresh-process resume |
| Independent evaluator lifecycle | Both hosts rejected premature completion, consumed the actual child's evaluation for the exact candidate, completed the workflow, and released ownership |
| Cross-host collaboration | Both directions passed request, reply, acknowledgment, conversation closure, and newsroom article read-back |
| Learning lifecycle | Codex recovery reached trial guidance; a fresh Claude session reused and activated it; a later native failure automatically withdrew it |
| Protected-action denial | Claude rejected the protected capability action; Codex failed closed when its outer tool envelope omitted execution-directory metadata |
| Publication contents | Wheel and source archive checks passed for private-file exclusion, independent imports, NOTICE, and package metadata |
| Repeat self-installation | No changes; project bindings preserved |

The self-installation checks use the packaged tool environment, separate from the development
`.venv`. Linux checks run from the built source distribution in a disposable container.
Native checks use disposable projects with explicit project trust. Their results do not
grant trust to another installation. Codex's conservative rejection above proves the
missing-directory boundary; it is not evidence of a precise protected-glob match in that
outer tool envelope. Direct capability regression tests cover directory and shell-prefix
normalization separately.

The full native lifecycle, messaging, and learning matrix above used wheel SHA-256
`e4347d3d836313b7d61edce04a847f8731f5c7c52c0b436269542580a3e43609`.
The publication wheel is
`a6aea761286a3806b9ebc02beae54366a21e24696b7fd8dae14bf85acc7043f0`.
It changes the review instruction for retaining native tool-result evidence and its generated
audit and manifest metadata; executable modules are identical. Package checks, self-installation,
fresh host activation, and the final native review cover this instruction correction separately.
The complete macOS check preserved the same source fingerprint before and after execution.
Linux ran from the built source archive with Python 3.14. The development selector accepts
the 3.14 series so it also works with uv installations whose interpreter catalog predates
a particular patch release.

## Memory and learning regression boundaries

Tests cover shared worktree storage, concurrent writes, repository isolation, conflicting records for the same source event, bounded recall, credential redaction, and exclusion of private reasoning. Learning
tests reject unrelated passing tests, unknown results, incomplete check results, same-session
promotion, and unexposed successes. Autonomous-validation tests cover an already saved checkpoint,
failed-check retry suppression, scoped deferral, renewed recovery evidence, and unbound verifiers. They also cover changed verification contracts, failure
after trial use, repeated transcript synchronization, and exposure limited to delivered rules.

Native tests use actual process/tool-result metadata. The suite includes JSON stdout that
pretends to be a process exit result and Claude's different failure envelope. A normal checkpoint
Stop request is accepted by the native validator only when the same session actually saves
a checkpoint and a subsequent Stop succeeds. Arbitrary admission failures remain failures.

Cross-host recall was checked against visible assistant answers, excluding tool output and
thinking blocks. The interruption test confirmed that the source session had no checkpoint.
The command-learning test checked the persistent transition history, not just a model's
claim that it learned. The supported learning scope is described in [Memory and learning](memory.md).

## Reproduce the package checks

```sh
uv sync --locked
uv run --locked python tools/check.py
uv build
uv run --locked python tools/validate_distribution.py dist/neurath-0.1.0-py3-none-any.whl --output .validation/wheel.json
uv run --locked python tools/validate_setup.py --output .validation/setup.json
```

The check command validates the complete runtime manifest, Python diagnostics, package
and installer tests, and the isolated runtime contract suite. The wheel check installs into
empty, Python, and JavaScript repositories using an external environment. It checks
installation, repeat installation, local protocols, execution, preservation, and removal.

## Self-hosted development

```sh
./setup --self
.neurath/run doctor --protocol
.neurath/run verify check
```

The development repository binds `check` to the same complete check command in
`.neurath/project.json`. The installed harness uses a separate persistent tool environment;
the development environment remains reproducible from `uv.lock`.

Public instructions and project bindings belong in Git. Generated skills, host settings,
absolute interpreter launchers, installation records, execution results, verification records,
review results, raw host logs, and runtime state do not. A fresh
checkout reconstructs those files with `./setup --self`. Existing exact Neurath instruction
blocks are preserved without duplication; edited or unknown blocks remain conflicts.

## Historical memory and host evidence

Earlier live Codex and Claude Code runs exercised file writes,
interruption, resume, compaction, a separate evaluator, completion, ownership release, and
protected-action denial. Those checks passed on the independently packaged runtime.
Fresh Claude sessions also recovered Codex decisions after normal completion and after an
interrupted turn without a checkpoint. Ordinary task prompts exercised automatic checkpoint
requests and command recovery, trial guidance, cross-session activation, and withdrawal after
a native command failure. These are historical checks unless explicitly listed in the latest
results above; they do not imply that every previous scenario was rerun for every artifact.

For a changed distribution, rerun the applicable suite and record its package fingerprint.
Host activation requires fresh host events and canonical state read-back from that exact
installation. Trust is scoped to a project and its actual hooks; fixture trust does not
activate a different checkout. A stopped or completed subprocess alone is insufficient.

Detailed evidence remains in ignored local validation storage. Publication artifacts omit
private paths, session identifiers, process records, original-file backups, and old archives.
