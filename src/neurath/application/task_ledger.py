"""User requirements and TODO share one ledger, read afresh on every request.

Source kind/attribution are conversational metadata, not authentication. Adapters
supply observed results after host work, never while holding a write transaction.
Runner completion requirements are composed above this ledger in the runner ticket.
"""

from neurath.domain.core import ContextNotFound, RevisionConflict
from neurath.domain.tasks import InvalidTaskTransition, TaskList


def nonempty(**values):
    for name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty")


class TaskLedger:
    def __init__(self, database):
        self.database = database

    def record_source(
        self, project_id, session_id, *, kind, text, reference, author="", parent_id=None
    ):
        nonempty(text=text, reference=reference)
        if kind not in {"request", "correction", "context", "question"}:
            raise ValueError("Unknown source kind")
        with self.database.transaction(write=True) as work:
            work.identities.get_session(project_id, session_id)
            if parent_id:
                work.tasks.source(project_id, parent_id)
            return work.tasks.add_source(
                project_id=project_id,
                session_id=session_id,
                kind=kind,
                text=text,
                reference=reference,
                author=author,
                parent_id=parent_id,
            )

    def create_task(self, project_id, session_id, *, title, source_id):
        nonempty(title=title)
        with self.database.transaction(write=True) as work:
            work.identities.get_session(project_id, session_id)
            source = work.tasks.source(project_id, source_id)
            if source.kind not in {"request", "correction"}:
                raise InvalidTaskTransition("Questions and recalled context do not define new work")
            return work.tasks.create(
                project_id=project_id, session_id=session_id, title=title, source_id=source_id
            )

    def get_task(self, project_id, task_id):
        with self.database.transaction() as work:
            return work.tasks.get(project_id, task_id)

    def get_source(self, project_id, source_id):
        with self.database.transaction() as work:
            return work.tasks.source(project_id, source_id)

    def history(self, project_id, task_id):
        with self.database.transaction() as work:
            work.tasks.get(project_id, task_id)
            return {
                "definitions": work.tasks.definitions(task_id),
                "results": work.tasks.results(task_id),
            }

    @staticmethod
    def checked(work, project_id, task_id, expected_revision):
        task = work.tasks.get(project_id, task_id)
        if task.revision != expected_revision:
            raise RevisionConflict("Task changed; read current state")
        return task

    def revise_task(
        self, project_id, task_id, *, expected_revision, source_id, title, reason, cancel=False
    ):
        nonempty(title=title, reason=reason)
        with self.database.transaction(write=True) as work:
            task = self.checked(work, project_id, task_id, expected_revision)
            source = work.tasks.source(project_id, source_id)
            if source.kind != "correction":
                raise InvalidTaskTransition("A scope change needs a correction, not an old summary")
            task = work.tasks.change(
                task,
                expected_revision,
                title=title,
                source_id=source_id,
                definition_revision=task.definition_revision + 1,
                status="invalidated" if cancel else "pending",
                reason=reason,
            )
            work.tasks.definition(task)
            return task

    @staticmethod
    def blocked(work, task):
        return bool(work.tasks.waits(task)) or any(
            work.tasks.get(task.project_id, dependency).status != "succeeded"
            for dependency in work.tasks.dependencies(task.id)
        )

    def list_tasks(self, project_id, session_id):
        with self.database.transaction() as work:
            work.identities.get_session(project_id, session_id)
            tasks = work.tasks.list(project_id, session_id)
            ready = tuple(
                t.id
                for t in tasks
                if t.status in {"pending", "waiting", "failed"} and not self.blocked(work, t)
            )
            return TaskList(tasks, ready)

    def add_dependency(self, project_id, task_id, *, expected_revision, depends_on):
        with self.database.transaction(write=True) as work:
            task = self.checked(work, project_id, task_id, expected_revision)
            task.require("pending", "waiting", "failed")
            work.tasks.get(project_id, depends_on)
            pending, seen = [depends_on], set()
            while pending:
                candidate = pending.pop()
                if candidate == task_id:
                    raise InvalidTaskTransition("Task dependency cycle")
                if candidate not in seen:
                    seen.add(candidate)
                    pending.extend(work.tasks.dependencies(candidate))
            if depends_on in work.tasks.dependencies(task_id):
                return task
            work.tasks.add_dependency(task_id, depends_on)
            return work.tasks.change(task, expected_revision)

    def start_task(self, project_id, task_id, *, expected_revision):
        with self.database.transaction(write=True) as work:
            task = self.checked(work, project_id, task_id, expected_revision)
            task.require("pending", "waiting", "failed")
            if self.blocked(work, task):
                raise InvalidTaskTransition("Task has unresolved dependencies")
            task = work.tasks.change(task, expected_revision, status="active", reason="")
            return task, work.tasks.open_attempt(task) or work.tasks.new_attempt(task)

    def wait_for_external(
        self, project_id, task_id, *, expected_revision, target, evidence, resolution_condition
    ):
        # Evidence is an observed external condition/reference, not invented approval.
        nonempty(target=target, evidence=evidence, resolution_condition=resolution_condition)
        with self.database.transaction(write=True) as work:
            task = self.checked(work, project_id, task_id, expected_revision)
            task.require("pending", "active", "failed", "waiting")
            wait_id = work.tasks.add_wait(task, target, evidence, resolution_condition)
            task = work.tasks.change(
                task,
                expected_revision,
                status="waiting",
                reason=f"{target}: {resolution_condition}",
            )
            return task, wait_id

    def resolve_external(self, project_id, task_id, *, expected_revision, wait_id, observation):
        nonempty(observation=observation)
        with self.database.transaction(write=True) as work:
            task = self.checked(work, project_id, task_id, expected_revision)
            if wait_id not in {w["id"] for w in work.tasks.waits(task)}:
                raise ContextNotFound("No current unresolved external dependency")
            work.tasks.resolve_wait(wait_id, observation)
            return work.tasks.change(
                task,
                expected_revision,
                status="waiting" if self.blocked(work, task) else "pending",
                reason="" if not self.blocked(work, task) else task.reason,
            )

    def report_result(
        self, project_id, task_id, *, attempt_id, outcome, summary, references=(), remaining=""
    ):
        """Persist actual observations. Submission is never completion.

        A changed definition retains late results without applying them. A failed or
        partial outcome must describe remaining work/blocker; restarting the SAME task
        preserves the obligation and previous attempts. No status-setting API exists.
        References locate artifacts, commands, or reviews; adapters must obtain them
        from execution, since this layer cannot establish their semantic truth.
        """
        nonempty(summary=summary)
        if outcome not in {"submitted", "succeeded", "failed", "partial"}:
            raise ValueError("Unknown result outcome")
        if not references or any(not isinstance(r, str) or not r.strip() for r in references):
            raise ValueError("Result requires actual artifact/command/review references")
        if outcome in {"failed", "partial"}:
            nonempty(remaining=remaining)
        if outcome == "succeeded" and remaining:
            raise InvalidTaskTransition("Unfinished work cannot be reported as success")
        with self.database.transaction(write=True) as work:
            task = work.tasks.get(project_id, task_id)
            attempt = work.tasks.attempt(task_id, attempt_id)
            if attempt.state not in {"running", "submitted"}:
                raise InvalidTaskTransition("Attempt already has a final result")
            applicable = (
                task.definition_revision == attempt.definition_revision
                and task.status in {"pending", "active", "waiting"}
            )
            result = work.tasks.add_result(
                attempt_id, outcome, summary, references, remaining, applicable
            )
            work.tasks.end_attempt(attempt_id, outcome)
            if applicable and outcome != "submitted":
                if outcome == "succeeded" and any(
                    r.status != "completed" or r.task_definition_revision != task.definition_revision
                    for r in work.workflows.for_task(task.id)
                ):
                    raise InvalidTaskTransition("Selected workflow still has unfinished phases")
                if outcome == "succeeded" and self.blocked(work, task):
                    raise InvalidTaskTransition("Unresolved dependencies prevent success")
                task = work.tasks.change(
                    task,
                    task.revision,
                    status="succeeded" if outcome == "succeeded" else "failed",
                    reason=remaining,
                )
            return task, result
