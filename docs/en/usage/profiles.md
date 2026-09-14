<!-- updated: 2026-09-14 | synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Give the agent your project's definition of correct

The saved-filter investigation needs more than a plausible code change. The agent must know where your application describes saved preferences, how the repository is tested, and which existing behavior must remain intact.

> Connect Neurath to this repository's existing requirements, design decisions, and verification checks. For the saved-filter fix, use those checks and preserve the current interface. Tell me what is missing before treating the work as verified.

Neurath calls its shared installation arrangement a **profile**. The available profile is `generic`: it supplies common agent support without choosing an application framework or importing another project's conventions. There is no separate frontend or backend profile to select for the two sides of this investigation.

## Connect what already defines the project

The agent links the relevant document roles to the repository's existing documents. For example, a product requirement may explain whether a filter belongs to a user, while a design decision may explain where preferences are saved. Neurath does not create those decisions by assigning a document role.

The agent also registers the checks your project already uses, including where each check runs and how success is recognized. This lets subsequent verification use a known project standard. It does not prove that a passing check covers browser refresh: the agent still needs evidence for the behavior you requested.

These bindings are stored in the project's local Neurath configuration and are preserved during updates and removal when you have edited them. Domain-specific rules remain in the target repository's instructions. Neurath's packaged support and your application's conventions have different owners.

## Keep the outcome visible while the method changes

For this investigation, success means reproducing the disappearing filter, identifying and fixing its cause, and showing that the saved selection survives refresh while the interface remains intact. The recorded unit of requested work, with that observable acceptance, is a **task**. The host's TODO display reflects that task record.

If an API check passes but the browser still loses the selection, the task remains unfinished. A failed approach can change the next step without cancelling the original request. Supported host events remind the active primary agent of current requirements and unfinished work as the investigation proceeds. The reminders are delivered at eligible native activity events when their conditions are met, rather than by an independent background timer. They provide context for judgment; they do not decide whether the fix is correct or grant new permissions.

## Adjust the connection when the project changes

Ask the agent to update the bindings when document locations or verification procedures change. Missing checks should remain explicit gaps rather than invented substitutes. A change to the registered verification contract also affects whether a previously learned environment correction is still applicable; [memory and learning](memory.md) explains that boundary.

To proceed, [choose a work request](skills.md). Configuration details belong in the [setup reference](../contributing/setup-reference.md); how goals and acceptance are recorded is covered in the [task reference](../contributing/task-todo-contract.md).

[한국어](../../ko/usage/profiles.md)
