# User workflows

[Documentation](index.md) · [한국어](../ko/workflows.md)

Use natural language to describe the outcome you want. The connected agent translates that request into supported Neurath operations. If its host cannot perform an action, it must explain the limitation instead of recording an invented success.

## Start a task

> Investigate this problem, propose a fix, implement it, and verify the original failure no longer occurs. Keep the stages and success criteria visible.

The task should record its source and owner. The phases are an ordered list defined for the task, rather than a universal checklist. Each phase is pending, active, or completed. A later phase may start only after its predecessors complete. Evidence should identify the task and phase it supports.

Task states are pending, active, waiting, completed, and withdrawn. A waiting task still needs attention or input; a withdrawn task is not a successful completion.

## Resume unfinished work

> Show unfinished work owned by this session and explain the next step for each task. Continue the selected task using its existing evidence.

Check the owner and current revision before continuing. Recovering a stored task does not automatically transfer its ownership or reacquire a released lease. If migration could not determine a field, keep that uncertainty visible while resolving it.

## Delegate and review

> Have another agent review this result. Record its findings, then assess whether they satisfy this task before accepting them.

A delegation moves from preparation to active execution and then to a reported result. The owner may accept or reject that report. A rejected result may be worked on again. Open delegation can be cancelled by the owner. Reporting does not complete the parent task; reading a message does not accept the work.

The local lifecycle records do not themselves launch external agents. Actual dispatch requires a supported host integration. If none is available, the agent must explain that it can record a handoff but cannot execute it through this protocol alone.

## Decide whether to finish

> Check every success criterion against the evidence, identify unresolved delegations, and explain whether this task can be completed.

The owner makes an explicit completion decision. Every phase must be completed, each criterion must have applicable successful evidence beyond a report alone, and delegations must be accepted or cancelled. Evidence from an unrelated task or phase cannot silently satisfy the requirement.

## Understand what is supported

The fresh design provides local records for sessions, tasks, ordered phases, evidence, delegations, communication, checkpoints, receipts, invocations, and leases. The exact callable surface is described in the [contributing guide](../../CONTRIBUTING.md).

Do not infer automatic publication, remote deployment, external-agent execution, independent host attestation, or human approval from the existence of those records. A locally installed candidate is not a public release. See the [specification](specification.md) for the acceptance contract and [recovery guide](recovery.md) for preservation requirements.
