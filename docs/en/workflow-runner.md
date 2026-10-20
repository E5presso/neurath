# Skill procedures and phase execution

[Documentation](index.md) · [Execution architecture](architecture.md) · [한국어](../ko/workflow-runner.md)

#141 provides internal Python APIs connecting selected skill definitions and phase execution to the task ledger. It includes a real local-process adapter; public CLI, native hooks and provider delegation remain subsequent work.

## Definitions and outcomes

One `WorkflowRun` belongs to a task and owns `WorkflowDefinition` revisions and `PhaseAttempt` history. Each phase specifies a purpose, resolved arguments, working directory, target revision, required checks, optional skip condition and execution limits. Inputs retain the selected definition's input record; arguments are already resolved for execution.

The last attempt matching the current phase definition determines progression. Changed targets/conditions require new work; unchanged valid outcomes and waiting attempts are reused. Old-definition results remain in history without completing a replacement phase. Removing a required phase requires an actual task correction; optional skips record the defined condition and evidence.

A phase's max_attempts bounds actual executions for the same target and task requirement. Exhaustion retains unresolved work/history and rejects another unchanged attempt. A corrected target receives its own attempt budget.

## Internal use cases

Each use-case module defines its own Command/Query and Result.

| Use case | Behavior |
| --- | --- |
| StartWorkflow | Attach a selected procedure to the task's current attempt; start unstarted tasks after prerequisite checks; reuse an identical existing run |
| GetWorkflow | Read the definition, current phase and history without external execution |
| PreparePhase | Persist a running attempt before dispatch after commit |
| ExecutePhase | Commit reservation → execute/reconcile outside locks → persist results in another transaction |
| ReportPhase | Check target/checks/evidence and save the result with the task's wait/resolution |
| ReviseWorkflow | Attach a revised definition to current task requirements, retaining old definitions/failures and unaffected results |
| SkipPhase | Record a conditional skip of the current optional phase |

ExecutePhase owns its two storage boundaries through framework `AbstractTransaction`; **invoke it without an enclosing transaction.** Other use cases run inside the request's standard Transaction. The domain owns transitions; the use case coordinates execution, lookup and persistence.

This example operates on an already stored task. It does not recreate the request, and a completed run is distinct from a successful task-outcome report.

```python
from pathlib import Path
import sys

from spakky.plugins.sqlalchemy.persistency.transaction import Transaction
from neurath.application.usecases.get_task import GetTaskQuery, GetTaskUseCase
from neurath.application.usecases.start_workflow import StartWorkflowCommand, StartWorkflowUseCase
from neurath.application.usecases.execute_phase import ExecutePhaseCommand, ExecutePhaseResult, ExecutePhaseUseCase
from neurath.domain.workflow_records import PhaseDefinition, WorkflowDefinition
from neurath.infrastructure.providers import DatabaseSettings, request_container


def execute_check(database: Path, project_id: str, session_id: str,
                  task_id: str, directory: Path, target_revision: str) -> ExecutePhaseResult:
    phase = PhaseDefinition(
        key="check", purpose="프로그램 정상 종료 확인",
        arguments=(sys.executable, "-c", "print('ok')"),
        directory=str(directory), target_revision=target_revision,
    )
    definition = WorkflowDefinition(
        skill="qa", version="example-1", phases=(phase,), inputs=(),
    )
    with request_container(DatabaseSettings(database, write=True)) as scope:
        with scope.get(Transaction):
            task = scope.get(GetTaskUseCase).run(
                GetTaskQuery(project_id, session_id, task_id)
            ).task
            flow = scope.get(StartWorkflowUseCase).run(
                StartWorkflowCommand(project_id, session_id, task_id, task.revision, definition)
            ).run
        return scope.get(ExecutePhaseUseCase).run(
            ExecutePhaseCommand(project_id, session_id, flow.uid, flow.revision)
        )
```

## Execution, recovery and task state

The default `SubprocessPhaseExecutorService` runs a POSIX process group. It observes failure exit codes, timeout and interrupt signals, then terminates/reaps the group. It continuously drains the pipe while retaining only the configured byte limit in memory. It automatically satisfies only exit:0. Additional required checks leave even a successful process outcome waiting for a separate observation/review report.

External execution uses the run ID and attempt number. Resume performs lookup first and resubmits only when the executor guarantees deduplication for that same ID. The local-process adapter cannot guarantee post-restart lookup/deduplication. It retains the same attempt as waiting and reports the reason to stderr, without repeating execution/notification for unchanged uncertainty or claiming native UI receipt.

Uncertain current-phase results also place the task in an external wait. A confirmed result resolves only that wait; unrelated dependencies, corrections and cancellation remain intact. Independent tasks stay actionable. A new successful task report is rejected until the selected procedure completes the current requirement. Task outcomes are reported separately after all phases finish.

## Persistence and validation boundary

`core_0004` adds run/revision/phase/attempt tables while retaining projects, sessions, sources and tasks. Destructive downgrade is rejected when run history exists. Reuse default repository CRUD and declarative owned relationships; phases and attempts have no separate repositories.

Tests exercise real processes, external effects outside DB locks, concurrent reservation, separate-process resume reads, changed targets/late outcomes/required checks, waits/retry limits, migration and rollback. Codex/Claude hook enforcement, provider adapters, independent evaluation integration and actual user installation remain subsequent tickets.
