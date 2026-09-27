<!-- last_updated: 2026-09-27; synced_from: f35185774aa9f18d1f4f7f13c74b4287a0fac751 -->
# Stock Codex batch orchestration

[한국어](../../ko/contributing/codex-poll-hook.md)

Neurath uses the ordinary Codex installation and launch path. It does not require
a patched Codex binary, a custom launcher or a replacement code-mode host.
Verify the installed distribution and the host actually running using the checks
below. Source tests, standalone execution and desktop activation are distinct evidence.

## Host observation boundary

A hook can reject a wait only if the host sends the corresponding event.
The observed stock code-mode path did not send an outer `PreToolUse` event even
for a text-only `functions.exec` call. An outer-wrapper fence therefore cannot
provide the missing guarantee. Nested wait visibility also depends on the host.
Wrapper source text, declared hook settings and simulated hook tests do not
establish which events an actual running host delivers.

Batch scheduling moves the ready-work decision into Neurath's runtime. It does
not depend on intercepting every agent wait and does not claim to prevent every
wait in arbitrary stock Codex tool calls.

## Runtime-owned worktree batches

The root uses `provider_wave_run` for a DAG of bounded implementation assignments.
Each entry has an `entry_id`, `depends_on`, and a provider `request` with its
assignment, distinct installed issue worktree and exact model plan ID/revision.
The wave is bound to the current task ID/revision, observed capacity and, when
applicable, the owned workflow. Every entry is admitted before any launch:
targets must be isolated, clean and unclaimed, and the existing
`worktree-worker`, model and execution-policy checks still apply.

The runtime reserves the ready set up to `max_parallel` in one transaction and
persists pending launches before submitting them. Worker terminal events free
slots for independent ready entries. A dependent entry becomes ready only after
the root reads and accepts the exact successful predecessor result. Admission,
launch, worker completion and root acceptance are separate states.

These workers are independent provider sessions using the existing
`worktree-worker` route. They are neither native direct children nor independent
evaluators. Each worker must establish its own native readiness and worktree
claim before writing. The root retains task/workflow ownership, integration,
review and final acceptance.

After a result or recovery event, use `provider_wave_read` to inspect actual run
identities and result digests and reconcile durable pending launch work. Submit
`provider_wave_consume` with the exact entry ID, run ID, generation, digest and
an `accepted` or `rejected` verdict. Do not infer success from a terminal state or
retry an uncertain launch as a new execution. `provider_wave_cancel` prevents
future reservations and requests cancellation through each run's control
channel; retain the observed outcomes and unfinished user requirements.

Use `provider_wave_retry` only for an observed failed or cancelled implementation
attempt whose exact run has ended. The original assignment, provider and
worktree are immutable. Retry requires fresh model-plan and inherited-policy
admission, a finished generation-1 result, a released worker OS lease and, if
a native session was created, verified closure of that session's connection and
process. Accepted work, accepted descendants and a cancelled wave cannot retry.
The old attempt's request, result, digest and consumption remain immutable.

Every wave-associated run, including prior attempts, rejects `provider_recover`.
That operation restores an inbox connection and cannot satisfy an implementation
assignment. A new admitted implementation attempt is distinct from replaying a
durable pending launch with the same identity.

Crash reconciliation runs on authenticated owner read, identical-request replay
or exact result consumption, and on worker terminal callbacks. It uses the
durable launch records and lease checks. There is no startup scanner or periodic
polling, and no claim that an unobserved crash repairs itself without one of
those triggers.

Independent review still uses a separately prepared native child with
`role="review"`. Codex uses `fork_turns="none"`; the host must attest the fresh
context and lineage. A provider result cannot substitute for that proof.

## Verification boundary

Verify admission and scheduling in focused tests, then verify the installed
distribution and actual unmodified host separately. A live batch check must
observe ready workers launching, independent work filling a released slot,
dependents waiting for exact root acceptance, cancellation and retained failure
outcomes. Record the executable actually used and the events observed. An
installed package or successful standalone run does not prove the desktop's
current behavior. Preserve host trust, permissions and existing claims.

See [host boundaries](hosts.md) and the [collaboration contract](collaboration-contract.md).
