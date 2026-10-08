# Local candidate verification record

[Documentation](index.md) · [한국어](../ko/candidate-status.md)

This record describes the local 0.3.0 candidate as of 2026-10-08. No public release, push, or deployment is reported here.

| Area | Observed result |
| --- | --- |
| Automated tests | 94 tests passed; the required check entrypoint emitted `NEURATH_CHECK_OK`. |
| Installed distribution | Local version 0.3.0; wheel SHA-256 `7656c4c6eb814f26dc7e3550725c1dc0e5ccfb0c82a1541c8f14d481ab1c35ca`. Runtime `installed_version` also reports 0.3.0. |
| Data preservation | 10 databases, 212 tables, and 147,638 rows migrated and verified. The original runtime database remained byte-for-byte unchanged. |
| Unfinished work | 30 waiting tasks retained with original ownership; 21 owner sessions are marked `legacy-unknown`. |
| Worktree cleanup | 47 extra worktrees removed after verified recoverable archival. |
| Codex native activation | The user approved hook trust. A fresh native Codex session ran with hooks enabled and bypass disabled, and successfully invoked `session_get` and `task_list`. The native result identified `neurath` 0.3.0 and returned exactly 30 preserved waiting tasks. |
| Codex session shutdown | `SessionEnd` timeout is 3 seconds; the actual run produced no timeout-clamping warning. |
| Native mutation and check lifecycle | Actual Codex resumed the same verification task. The runner executed the stored argument list after native pre-tool observation, recorded subprocess return code 0 and 94 passing tests, and persisted successful evidence. The criterion was satisfied and the task completed at revision 3. |
| Writer release | The verification task's writer lease was released: `active: false`, generation 1, revision 1. |
| Claude native activation | An actual Claude session successfully invoked `session_get` against the final installed wheel. An earlier native run also passed `session_get` and `task_list`, returning 30 preserved waiting tasks. |

`legacy-unknown` does not mean a session has ended. Task adoption still requires its explicit native user source and the previous owner's confirmed ended state. Migration did not promote historical reports, claims, or approvals into current authority.

These observations establish Codex activation, a real configured-check and task-completion lifecycle, writer release, and Claude activation with a read-only call against the final wheel. They do not establish a Claude mutation lifecycle. The preserved-task count comes from the original structured event log rather than a shortened model summary.

The earlier failed verification evidence remained unchanged when the same verification task resumed. Existing user tasks were not modified. The new successful evidence records the runner's actual subprocess result, independently of how a host renders tool output.

Keep the [hook trust procedure](../../CONTRIBUTING.md#trust-changed-codex-hooks) in the installation workflow: future changes to a hook definition may require fresh user review. New host or lifecycle claims still require their own observations.

After final formatting, import sorting, and annotation normalization, the required checks passed again and both real hosts read back the final wheel hash above. The original complete-lifecycle evidence is retained separately.
