"""Application operations on Task; domain transitions own phase and completion rules."""

from dataclasses import replace
from uuid import uuid4

from neurath.core.domain import Condition, Task, quote, require


class TaskCommands:
    def __init__(self, sessions, provenance, skills=None):
        self.sessions = sessions
        self.provenance = provenance
        self.skills = dict(skills or {})
        self._load_installed_skills = skills is None

    def owned(self, tx, context, values, *, control=False):
        task = tx.task(values["task_id"])
        if control:
            task.require_controller(context.actor_id)
        else:
            task.require_owner(context.actor_id, task.ownership_generation)
        task.require_revision(values["expected_revision"])
        return task

    def task_list(self, tx, context, actor, values):
        current = tx.record("current-input", context.actor_id)
        all_project = values.get("all_project", False)
        require(type(all_project) is bool, "invalid-input")
        return {
            "tasks": tuple(
                task
                for task in tx.tasks()
                if all_project
                or task.owner_actor == context.actor_id
                or any(a.recipient == context.actor_id for a in task.assignments)
            ),
            "current_input": None if current is None else current["value"],
        }

    def task_read(self, tx, context, actor, values):
        return {"task": tx.task(values["task_id"])}

    def phase_read(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        return {
            "task_id": task.id,
            "revision": task.revision,
            "phase": task.current_phase,
            "run": task.skill_run,
        }

    def task_focus(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        task.require_participant(context.actor_id)
        self.sessions.focus(tx, context.actor_id, task.id)
        return {"task_id": task.id, "revision": task.revision}

    def task_define(self, tx, context, actor, values):
        require(not actor["is_subagent"], "task-owner-required")
        require(
            isinstance(values["source_ids"], list) and bool(values["source_ids"]),
            "instruction-source-required",
        )
        for reference in values["source_ids"]:
            self.provenance.instruction(tx, reference)
        require(isinstance(values["acceptance"], list), "acceptance-required")
        conditions = []
        dependencies = values.get("dependencies", [])
        require(isinstance(dependencies, list), "task-dependencies")
        for identifier in dependencies:
            require(isinstance(identifier, str), "task-dependencies")
            tx.task(identifier)
        for value in values["acceptance"]:
            require(
                isinstance(value, dict)
                and {"id"} <= set(value)
                and set(value) <= {"id", "kinds", "subject_key", "expected_pass", "operation"},
                "invalid-condition",
            )
            conditions.append(
                Condition(
                    value["id"],
                    frozenset(value.get("kinds", ["report"])),
                    value.get("subject_key"),
                    value.get("expected_pass", True),
                    value.get("operation"),
                )
            )
        task = Task(
            "task-" + uuid4().hex,
            context.session_id,
            context.actor_id,
            values["goal"],
            tuple(values["source_ids"]),
            tuple(conditions),
            dependencies=tuple(dependencies),
        )
        tx.create_task(task)
        return {"task": task}

    def task_withdraw(self, tx, context, actor, values):
        return self._decide(tx, context, actor, "task_withdraw", values)

    def task_adopt(self, tx, context, actor, values):
        return self._decide(tx, context, actor, "task_adopt", values)

    def _decide(self, tx, context, actor, name, values):
        require(not actor["is_subagent"], "task-owner-required")
        task = tx.task(values["task_id"])
        require(
            task.revision == values["expected_revision"],
            "revision-conflict",
            actual=task.revision,
        )
        source = self.provenance.instruction(tx, values["source_id"])
        excerpt = quote(source, values["start"], values["end"], values["digest"])
        if name == "task_withdraw":
            task.require_owner(context.actor_id, task.ownership_generation)
            updated = task.withdraw(source)
            assignments = []
            for assignment in updated.assignments:
                dispatch = tx.record("dispatch", assignment.id)
                if (
                    assignment.state == "cancel-requested"
                    and not assignment.recipient
                    and dispatch["value"]["state"] == "prepared"
                ):
                    assignment = assignment.cancel_unstarted(source.id)
                assignments.append(assignment)
            updated = replace(updated, assignments=tuple(assignments))
        else:
            previous = tx.record("actor", task.owner_actor)
            stopped = (previous is not None and previous["value"]["status"] == "stopped") or (
                previous is None and tx.record("retired-owner", task.owner_actor) is not None
            )
            updated = task.adopt(
                context.session_id, context.actor_id, source, previous_owner_stopped=stopped
            )
            self.sessions.focus(tx, context.actor_id, task.id)
        tx.save_task(updated, expected_revision=task.revision)
        tx.put_record(
            "task-decision",
            f"{task.id}:{updated.revision}",
            {
                "operation": name,
                "prior_owner": task.owner_actor,
                "task_id": task.id,
                "source_id": source.id,
                "quote": excerpt,
                "reason": values["reason"],
                "assessor": context.actor_id,
                "assurance": "agent-interpretation",
            },
        )
        return {"task": updated}

    def task_start(self, tx, context, actor, values):
        task = self.owned(tx, context, values, control=True)
        require(
            all(tx.task(identifier).state == "completed" for identifier in task.dependencies),
            "dependencies-unfinished",
        )
        updated = task.start()
        return self._save(tx, context.actor_id, task, updated)

    def skill_start(self, tx, context, actor, values):
        task = self.owned(tx, context, values, control=True)
        if self._load_installed_skills:
            from neurath.core.skills import load_skills

            self.skills = load_skills()
            self._load_installed_skills = False
        require(values["skill"] in self.skills, "skill-missing")
        updated = task.attach_skill(self.skills[values["skill"]])
        return self._save(tx, context.actor_id, task, updated)

    def task_wait(self, tx, context, actor, values):
        task = self.owned(tx, context, values, control=True)
        tx.source(values["source_id"])
        updated = task.wait(values["reason"], values["source_id"])
        return self._save(tx, context.actor_id, task, updated)

    def task_resume(self, tx, context, actor, values):
        task = self.owned(tx, context, values, control=True)
        require(
            all(tx.task(identifier).state == "completed" for identifier in task.dependencies),
            "dependencies-unfinished",
        )
        updated = task.resume()
        return self._save(tx, context.actor_id, task, updated)

    def phase_restart(self, tx, context, actor, values):
        task = self.owned(tx, context, values, control=True)
        tx.source(values["source_id"])
        changed = values.get("changed_inputs")
        require(
            changed is None
            or isinstance(changed, list)
            and all(isinstance(v, str) for v in changed),
            "invalid-inputs",
        )
        updated = task.restart(values["source_id"], changed)
        return self._save(tx, context.actor_id, task, updated)

    def phase_complete(self, tx, context, actor, values):
        task = self.owned(tx, context, values, control=True)
        require(
            isinstance(values["inputs"], dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in values["inputs"].items()),
            "invalid-inputs",
        )
        updated = task.complete_phase(
            values["phase_id"],
            self.provenance.outcomes(tx, task.id, values["outcomes"]),
            values["inputs"],
        )
        return self._save(tx, context.actor_id, task, updated)

    def task_complete(self, tx, context, actor, values):
        task = self.owned(tx, context, values, control=False)
        require(
            all(tx.task(identifier).state == "completed" for identifier in task.dependencies),
            "dependencies-unfinished",
        )
        updated = task.complete(self.provenance.outcomes(tx, task.id, values["outcomes"]))
        return self._save(tx, context.actor_id, task, updated)

    def _save(self, tx, actor_id, previous, updated):
        tx.save_task(updated, expected_revision=previous.revision)
        self.sessions.focus(tx, actor_id, previous.id)
        return {"task": updated}
