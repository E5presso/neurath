"""Project knowledge is reference data; it neither completes work nor grants authority."""

from neurath.core.domain import require
from neurath.memory.learning import Learning
from neurath.memory.store import ProjectMemory

COMMANDS = {
    "memory_recall": (set(), {"query", "limit"}, True),
    "memory_checkpoint": ({"summary"}, {"decisions", "next_steps", "lessons", "status"}, False),
    "memory_pull": ({"source_actor"}, set(), True),
    "learning_status": (set(), set(), True),
    "learning_pending": (set(), set(), True),
}


class MemoryCommands:
    def __init__(self, root, store):
        self.memory = ProjectMemory(root, store=store)
        self.learning = Learning(self.memory)

    def call(self, tx, context, actor, name, values):
        if name == "memory_recall":
            require(isinstance(values.get("query", ""), str), "invalid-query")
            require(
                type(values.get("limit", 12)) is int and 1 <= values.get("limit", 12) <= 100,
                "invalid-limit",
            )
            return self.memory.recall(
                values.get("query", ""),
                host=actor["provider"],
                session=context.session_id,
                limit=values.get("limit", 12),
                _db=tx.db,
            )
        if name == "memory_checkpoint":
            require(
                isinstance(values["summary"], str) and bool(values["summary"].strip()),
                "checkpoint-summary",
            )
            for field in ("decisions", "next_steps", "lessons"):
                require(
                    isinstance(values.get(field, []), list)
                    and all(
                        isinstance(item, str) and item.strip() for item in values.get(field, [])
                    ),
                    "checkpoint-items",
                    field=field,
                )
            reference = self.memory.checkpoint(
                actor["provider"],
                context.session_id,
                "checkpoint:" + context.actor_id + ":" + values["key"],
                summary=values["summary"],
                decisions=values.get("decisions", []),
                next_steps=values.get("next_steps", []),
                lessons=values.get("lessons", []),
                status=values.get("status", "active"),
                _db=tx.db,
            )
            return {"reference": reference, "authority": "agent-report"}
        if name == "learning_status":
            return {"lessons": self.learning.status(_db=tx.db), "authority": "guidance-only"}
        if name == "learning_pending":
            return {
                "pending": self.learning.pending(actor["provider"], context.session_id, _db=tx.db),
                "authority": "guidance-only",
            }
        source = tx.record("actor", values["source_actor"])
        require(source is not None, "source-actor-unobserved")
        owner = source["value"]
        return {
            "authority": "reference-only",
            "actor": owner,
            "events": self.memory.history(owner["provider"], owner["session_id"], _db=tx.db),
            "unfinished_tasks": [
                task
                for task in tx.tasks()
                if task.owner_actor == owner["id"] and task.state not in {"completed", "withdrawn"}
            ],
            "next_action": "Inspect the retained work. Use task_adopt only for an authorized transfer after observed owner termination.",
        }
