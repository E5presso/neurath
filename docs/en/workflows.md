# User workflows

[Documentation](index.md) · [한국어](../ko/workflows.md)

These are planned workflows under the [product specification](specification.md). The hook CLI is implemented; business CLI commands and installed host wiring remain subsequent work. Available internal APIs are documented in the [project/session foundation](core-foundation.md) and [task ledger](task-ledger.md).

## Request work and inspect progress

> Investigate and fix this problem, then verify that the original failure is resolved.

Installed rules guide the agent to an appropriate skill. Tasks link original instructions to required outcomes, and TODO displays the full current list. The runner manages selected skill phases and attempts. Simple questions and status reads do not create new work or workflows. See [skill selection](interfaces.md#2-skills).

## Correct or interrupt work

> Keep the API unchanged and modify only the screen.

Apply the affected correction while retaining other requirements and previous attempts. An explicit interruption uses the host's actual execution-control path. External waiting reports remaining work and its dependency without repeatedly invoking the agent for an unchanged state.

## Delegate and verify outcomes

> Ask another agent to review this result and fix the reported problems.

Recipients execute, check and report within the original request and assigned scope. Message delivery or a recipient report does not complete the parent task. Before finishing a body of work, a separate evaluator compares originals, current corrections, TODO and artifacts; the executor addresses confirmed gaps. See [execution and outcome evaluation](architecture.md#3-skills-and-phase-runner-contract).

## Continue retained work

> Continue the remaining work using the existing results.

After compaction, hooks automatically restore the latest enclave. Resume/adoption retains originals, unfinished tasks, runner state and current facts while coordinating against duplicate writers. Reading handoff context is distinct from adopting work. See [memory and handoff](architecture.md#5-enclave-memory-graphify-and-pull).

## Finish and choose a retrospective

The Stop hook deterministically checks current task state. Legitimate external waiting, user interruption and faults return control while retaining unfinished work. If issues surfaced, offer a retrospective once at session end. A user request or acceptance leads to improvement and validation based on a separate evaluator's retrospective. Decline or silence permits original-work completion without reflection. Follow the [retrospective procedure](interfaces.md#6-user-selected-retrospective).
