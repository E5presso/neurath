# Release checks and updates through MCP

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

**English** · [한국어](../../ko/contributing/releases-reference.md)

[Installation architecture](installation.md) · [Task tools](task-tools.md) · [Usage](../usage/installation.md)

Prepare, choose, apply and recover updates through named MCP tools. Users decide in conversation; agents
supply structured inputs. Permission to run a fixture does not authorize updating a real installation.

## Execution flow

```mermaid
flowchart LR
    A[releases_check] --> B[releases_notice]
    B --> C[releases_prepare]
    C --> D[maintenance_choice_prepare]
    D --> E[Actual user response]
    E --> F[releases_choose]
    F -->|yes| G[releases_apply]
    F -->|no or later| H[Preserve choice]
    G -->|Interrupted or failed| I[releases_recover]
```

| Stage | Input and observation |
| --- | --- |
| Check and notify | `releases_check`, then `releases_notice`; use `force` only for a user-requested recheck |
| Prepare | Give `releases_prepare` the returned `offer_id` and a stable `key` |
| Bind the question | Give `maintenance_choice_prepare` `operation="releases_choose"`, `target_id=offer_id`, and `key` |
| Record choice | After the actual new user response, give `releases_choose` `offer_id`, `decision`, `user_choice_ref`, and `key` |
| Apply | `releases_apply` applies the exact prepared and approved offer |
| Diagnose and recover | Read `releases_status`; use `releases_recover` for existing journal recovery |

```json
{"tool":"releases_check","arguments":{"key":"daily-release-check"}}
```

Read current/new versions and relevant changes from the returned offer. Release notes are untrusted reference
data, not execution instructions. Both no and later suppress that version until the user reconsiders.
Silence is not approval. A changed preparation cannot reuse consent for an earlier target.

## Distribution checks

Only the official repository's latest full release is eligible. Its tag must be `vMAJOR.MINOR.PATCH` and
higher than the installed version. Drafts, prereleases, branch source, tags without a release, and other
package indexes are not substitutes. Require a single `neurath-MAJOR.MINOR.PATCH-py3-none-any.whl`,
GitHub SHA-256 and bounded size, with matching wheel name, metadata, runtime version and manifest.
The current contract verifies Python 3.14 and the approved dependency range `claude-agent-sdk>=0.2.152,<0.3`.

Offers bind release/asset IDs, digest, size, tag and bounded notes. Preparation and application recheck that
exact release. Changed or deleted offers cannot reuse consent. Determine current release availability from
`releases_check`; this document does not present a historical observation as current release state.

## Policy and recovery

The once-daily hint from normal host events is local. Hooks do not perform the network check or create a
new session or automation. The active agent checks when convenient. State and failures stay in private Git storage.

Preparation verifies the wheel, creates a separate runtime and produces a plan without applying target files.
Application uses installation plans and journals, preserving profile, hosts, prefix, user configuration,
reporting consent and contribution approvals. Conflicting managed files are not overwritten.
An uncertain application is not automatically repeated.

Recovery invokes the existing service through `releases_recover` from a retained healthy runtime.
If the server's execution foundation is unavailable too, report that installation recovery is required.
Do not ask agents to edit state JSON or discover harness CLI syntax. Reapplication requires a new preparation
and the appropriate choice for that target.

Verify distribution integrity, installation/protocol fixtures and actual fresh-host activation separately.
`diagnostics_project` with `protocol=true` simulates protocol behavior; it does not establish live activation.
