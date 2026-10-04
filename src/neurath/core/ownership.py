"""Checkout writer leases and explicit edit participation."""

from pathlib import Path

from neurath.core.domain import require
from neurath.core.workspace import checkout


class WorkspaceOwnership:
    def __init__(self, store, sessions):
        self.store = store
        self.sessions = sessions

    def _path(self, values):
        path = Path(values["checkout"])
        require(path.is_absolute(), "absolute-checkout-required")
        return path

    def worktree_release(self, tx, context, actor, values):
        path = self._path(values)
        require(type(values["generation"]) is int, "invalid-generation")
        # Ownership can be returned after the checkout itself was removed.
        target = str(path) if tx.lease(str(path)) is not None else str(path.resolve())
        tx.release(target, context.actor_id, values["generation"])
        return {"released": True, "checkout": target}

    def worktree_read(self, tx, context, actor, values):
        path = self._path(values)
        lease = tx.lease(str(path))
        if lease is not None:
            return {"checkout": str(path), "lease": lease, "exists": path.exists()}
        target = checkout(self.store.root, str(path))
        return {"checkout": target, "lease": tx.lease(target), "exists": True}

    def worktree_claim(self, tx, context, actor, values):
        path = self._path(values)
        if values.get("create", False):
            require(values["create"] is True, "invalid-input")
            require(not path.exists() and not path.is_symlink(), "worktree-target-exists")
            target = str(path.resolve())
        else:
            target = checkout(self.store.root, str(path))
        task = tx.task(values["task_id"])
        require(task.state in {"open", "running", "waiting"}, "task-state")
        task.require_writer(context.actor_id)
        current = tx.lease(target)
        if current and current["writer"] != context.actor_id:
            previous = tx.record("actor", current["writer"])
            stopped = (previous is not None and previous["value"]["status"] == "stopped") or (
                previous is None and tx.record("retired-owner", current["writer"]) is not None
            )
            adopted = any(
                r["value"].get("operation") == "task_adopt"
                and r["value"].get("task_id") == task.id
                and r["value"].get("prior_owner") == current["writer"]
                and r["value"].get("assessor") == context.actor_id
                for r in tx.records("task-decision")
            )
            require(stopped and adopted, "lease-conflict", writer=current["writer"])
            tx.release(target, current["writer"], current["generation"])
        return {"lease": tx.claim(target, context.actor_id)}

    def admit_write(self, context, *, checkout_path, generation):
        """Coordinate an explicit editor write, without interpreting host commands."""
        with self.store.transaction() as tx:
            self.sessions.actor(tx, context)
            focus = tx.record("focus", context.actor_id)
            require(focus is not None, "task-focus-required")
            task = tx.task(focus["value"]["task_id"])
            require(task.state == "running", "task-state")
            task.require_writer(context.actor_id)
            target = checkout(self.store.root, checkout_path)
            lease = tx.lease(target)
            require(
                lease is not None and lease["writer"] == context.actor_id, "writer-lease-required"
            )
            require(type(generation) is int and generation == lease["generation"], "stale-lease")
            if context.actor_id not in task.implementation_actors:
                updated = task.record_implementation(context.actor_id)
                tx.save_task(updated, expected_revision=task.revision)
                task = updated
            return {"allowed": True, "task_id": task.id, "task_revision": task.revision}
