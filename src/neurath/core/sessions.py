"""Native actor lifecycle and projections of outstanding work."""

from hashlib import sha256

from neurath.core.codec import encode
from neurath.core.domain import Source, require, stop_reasons
from neurath.core.invocations import NativeInvocations


class SessionLifecycle:
    def __init__(self, store):
        self.store = store

    def observe_actor(
        self, actor_id, session_id, provider, *, parent=None, is_subagent=None, activate=True
    ):
        """Adapter entrypoint; deliberately absent from the public command map."""
        require(
            provider in {"codex", "claude-code"} and bool(actor_id and session_id), "native-actor"
        )
        value = {
            "id": actor_id,
            "session_id": session_id,
            "provider": provider,
            "parent": parent,
            "is_subagent": bool(parent) if is_subagent is None else is_subagent,
            "status": "active" if activate else "observed",
        }
        with self.store.transaction() as tx:
            previous = tx.record("actor", actor_id)
            if previous:
                require(
                    all(
                        previous["value"][key] == value[key]
                        for key in ("id", "session_id", "provider", "parent", "is_subagent")
                    ),
                    "actor-rebinding",
                )
                if not activate:
                    value["status"] = previous["value"]["status"]
            tx.put_record("actor", actor_id, value, 0 if previous is None else previous["revision"])

    def actor(self, tx, context):
        actor = tx.record("actor", context.actor_id)
        require(
            actor is not None and actor["value"]["session_id"] == context.session_id,
            "native-actor-required",
        )
        return actor["value"]

    def focus(self, tx, actor_id, task_id):
        previous = tx.record("focus", actor_id)
        tx.put_record(
            "focus", actor_id, {"task_id": task_id}, 0 if previous is None else previous["revision"]
        )

    def todo(self, tx, context, actor):
        rows = []
        focused = tx.record("focus", context.actor_id)
        focus = None if focused is None else focused["value"]["task_id"]
        for task in tx.tasks():
            if task.owner_actor == context.actor_id:
                rows.append(
                    (task.id, task.goal, task.state, task.state in {"completed", "withdrawn"})
                )
            else:
                for assignment in task.assignments:
                    if assignment.recipient == context.actor_id:
                        rows.append(
                            (
                                task.id,
                                assignment.scope,
                                assignment.state,
                                assignment.state in {"reported", "accepted", "rejected"},
                            )
                        )
        active = next((i for i, row in enumerate(rows) if row[0] == focus and not row[3]), None)
        if active is None:
            active = next((i for i, row in enumerate(rows) if not row[3]), None)
        if actor["provider"] == "codex":
            arguments = {
                "plan": [
                    {
                        "step": f"[Neurath] {goal} ({state}; {identifier})",
                        "status": "completed"
                        if done
                        else "in_progress"
                        if i == active
                        else "pending",
                    }
                    for i, (identifier, goal, state, done) in enumerate(rows)
                ]
            }
            tool = "update_plan"
        else:
            arguments = {
                "todos": [
                    {
                        "content": f"{goal} ({state}; {identifier})",
                        "activeForm": goal,
                        "status": "completed"
                        if done
                        else "in_progress"
                        if i == active
                        else "pending",
                    }
                    for i, (identifier, goal, state, done) in enumerate(rows)
                ]
            }
            tool = "TodoWrite"
        return {
            "tool": tool,
            "arguments": arguments,
            "instruction": "Display this projection through the native tool; it does not replace task or phase completion.",
        }

    def stop(self, context):
        with self.store.transaction() as tx:
            self.actor(tx, context)
            reasons = stop_reasons(context.session_id, context.actor_id, tx.tasks())
            return {"allowed": not reasons, "pending": reasons}

    def session_status(self, tx, context, actor, values):
        return {
            "actor": actor,
            "pending": stop_reasons(context.session_id, context.actor_id, tx.tasks()),
        }

    def collaboration_discover(self, tx, context, actor, values):
        return {
            "actors": [
                {**record["value"], "native_handle": tx.record("native-handle", record["id"])}
                for record in tx.records("actor")
            ]
        }

    def end(self, context, provider, receipt_id, *, child=False):
        with self.store.transaction() as tx:
            ended = {context.actor_id}
            if not child:
                ended.update(
                    record["id"]
                    for record in tx.records("actor")
                    if record["value"]["provider"] == provider
                    and record["value"]["session_id"] == context.session_id
                )
            for actor_id in ended:
                actor = tx.record("actor", actor_id)
                tx.put_record(
                    "actor",
                    actor_id,
                    {**actor["value"], "status": "stopped"},
                    actor["revision"],
                )
            for task in tx.tasks():
                sources = {}
                for assignment in task.assignments:
                    if assignment.recipient in ended and assignment.awaiting_result:
                        identity = (
                            "native-end:"
                            + context.actor_id
                            + ":"
                            + receipt_id
                            + ":"
                            + assignment.id
                        )
                        source = Source.create(
                            "source-" + sha256(identity.encode()).hexdigest(),
                            "tool",
                            encode(
                                {
                                    "event": "SessionEnd",
                                    "actor_id": context.actor_id,
                                    "ended_actor_id": assignment.recipient,
                                    "assignment_id": assignment.id,
                                }
                            ),
                            identity,
                        )
                        tx.put_source(source)
                        sources[assignment.id] = source.id
                updated = task.recipients_ended(sources)
                if updated != task:
                    tx.save_task(updated, expected_revision=task.revision)
            NativeInvocations.close_session(tx, provider, context, child=child)
