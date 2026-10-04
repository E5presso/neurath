"""Observed delegation transport, with assignment decisions owned by Task."""

from uuid import uuid4

from neurath.core.domain import Source, require, select_execution


class AssignmentCommands:
    def __init__(self, store, sessions, provenance):
        self.store = store
        self.sessions = sessions
        self.provenance = provenance

    def assignment_prepare(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        task.require_controller(context.actor_id)
        task.require_revision(values["expected_revision"])
        recipient = values.get("recipient", "")
        target = tx.record("actor", recipient) if recipient else None
        require(not recipient or target is not None, "recipient-unobserved")
        provider = (
            target["value"]["provider"] if target else values.get("provider", actor["provider"])
        )
        select_execution(values["execution"], actor["provider"], provider, values["reason"])
        if target:
            require(
                (values["execution"] == "subagent") == target["value"]["is_subagent"],
                "execution-target-mismatch",
            )
        if values["role"] == "reviewer" and recipient:
            self.provenance.require_reviewer(tx, task, recipient)
        review_target = None
        if values["role"] == "reviewer":
            from neurath.core.workspace import checkout, source_subject

            require(isinstance(values.get("checkout"), str), "review-checkout-required")
            target = checkout(self.store.root, values["checkout"])
            review_target = {
                "checkout": target,
                "subject": source_subject(target),
                "execution_scope": [list(item) for item in task.observation_scope()],
            }
        identifier = "assignment-" + uuid4().hex
        updated = task.issue_assignment(
            identifier,
            values["execution"],
            values["scope"],
            context.actor_id,
            recipient,
            values["subject"],
            values["role"],
        )
        assignment = updated.assignment(identifier)
        tx.put_record(
            "dispatch",
            identifier,
            {
                "provider": provider,
                "reason": values["reason"],
                "task_id": task.id,
                "issuer": context.actor_id,
                "state": "prepared",
                "review_target": review_target,
            },
        )
        return self._save(tx, context, task, updated, assignment.id)

    def assignment_read(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        assignment = task.assignment(values["assignment_id"])
        return {
            "assignment": assignment,
            "task_revision": task.revision,
            "review_target": tx.record("dispatch", assignment.id)["value"].get("review_target"),
        }

    def assignment_start(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        assignment = task.assignment(values["assignment_id"])
        updated = task.start_assignment(assignment.id, context.actor_id)
        return self._save(tx, context, task, updated, assignment.id)

    def assignment_report(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        assignment = task.assignment(values["assignment_id"])
        require(assignment.recipient == context.actor_id, "actor-mismatch")
        if assignment.role == "reviewer" and values["verdict"] == "pass":
            self.provenance.require_reviewer(tx, task, context.actor_id)
        source = Source.create(
            "source-" + uuid4().hex,
            "report",
            values["body"],
            "assignment-report:" + context.actor_id + ":" + context.invocation_id,
        )
        updated = task.report_assignment(
            assignment.id, context.actor_id, source.id, values["verdict"], values["subject"]
        )
        assignment = updated.assignment(assignment.id)
        tx.put_source(source)
        kind = "review" if assignment.role == "reviewer" else "report"
        review_target = tx.record("dispatch", assignment.id)["value"].get("review_target")
        evidence = self.provenance.record_evidence(
            tx,
            task.id,
            source,
            context.actor_id,
            kind,
            values["subject"],
            values["verdict"] == "pass",
            checkout_path=None if review_target is None else review_target["checkout"],
            checkout_subject=None if review_target is None else review_target["subject"],
            execution_scope=None if review_target is None else review_target["execution_scope"],
        )
        tx.save_task(updated, expected_revision=task.revision)
        return {"assignment": assignment, "evidence": evidence}

    def assignment_accept(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        assignment = task.assignment(values["assignment_id"])
        tx.source(values["source_id"])
        if assignment.role == "reviewer":
            self.provenance.require_reviewer(tx, task, assignment.recipient)
        updated = task.accept_assignment(
            assignment.id,
            context.actor_id,
            values["source_id"],
            values["subject"],
        )
        return self._save(tx, context, task, updated, assignment.id)

    def assignment_reject(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        assignment = task.assignment(values["assignment_id"])
        tx.source(values["source_id"])
        updated = task.reject_assignment(assignment.id, context.actor_id, values["source_id"])
        return self._save(tx, context, task, updated, assignment.id)

    def assignment_cancel(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        assignment = task.assignment(values["assignment_id"])
        task.require_assignment_canceller(assignment.id, context.actor_id)
        if assignment.state == "issued" and not assignment.recipient:
            dispatch = tx.record("dispatch", assignment.id)
            run = tx.record("provider-run", dispatch["value"].get("run_id", ""))
            if run and run["value"]["state"] != "prepared":
                assignment = assignment.cancel()
                updated = task.with_assignment(assignment)
                tx.save_task(updated, expected_revision=task.revision)
                return {"assignment": assignment, "task_revision": updated.revision}
            require(
                dispatch["value"]["state"] in {"prepared", "launch-prepared"},
                "dispatch-uncertain",
            )
            if run:
                tx.put_record(
                    "provider-run",
                    run["value"]["id"],
                    {**run["value"], "state": "cancelled"},
                    run["revision"],
                )
            source = Source.create(
                "source-" + uuid4().hex,
                "report",
                values["reason"],
                "cancel-unstarted:" + context.actor_id + ":" + values["key"],
            )
            tx.put_source(source)
            assignment = assignment.cancel_unstarted(source.id)
        else:
            assignment = assignment.cancel()
        updated = task.with_assignment(assignment)
        return self._save(tx, context, task, updated, assignment.id)

    def _save(self, tx, context, previous, updated, identifier):
        tx.save_task(updated, expected_revision=previous.revision)
        self.sessions.focus(tx, context.actor_id, previous.id)
        return {
            "assignment": updated.assignment(identifier),
            "task_revision": updated.revision,
            "dispatch_marker": f"[neurath-assignment:{identifier}]",
            "review_target": tx.record("dispatch", identifier)["value"].get("review_target"),
        }

    def bind_recipient(self, task_id, assignment_id, recipient):
        """An observed native spawn fills the reserved recipient exactly once."""
        with self.store.transaction() as tx:
            target = tx.record("actor", recipient)
            require(target is not None, "recipient-unobserved")
            task = tx.task(task_id)
            assignment = next((a for a in task.assignments if a.id == assignment_id), None)
            if assignment is not None and assignment.recipient == recipient:
                return
            require(assignment is not None and assignment.state == "issued", "assignment-state")
            require(
                not assignment.recipient or assignment.recipient == recipient, "recipient-rebinding"
            )
            if assignment.role == "reviewer":
                self.provenance.require_reviewer(tx, task, recipient)
            dispatch = tx.record("dispatch", assignment.id)
            require(dispatch["value"]["provider"] == target["value"]["provider"], "provider-choice")
            require(
                (assignment.execution == "subagent") == target["value"]["is_subagent"],
                "execution-target-mismatch",
            )
            updated = task.bind_recipient(assignment.id, recipient)
            tx.save_task(updated, expected_revision=task.revision)
            tx.put_record(
                "dispatch",
                assignment.id,
                {**dispatch["value"], "state": "bound"},
                dispatch["revision"],
            )
