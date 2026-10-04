"""Real transactions, competing writers and immutable provenance in one store."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from neurath.core.domain import Condition, CoreError, Source, Task
from neurath.core.store import Store


def task():
    return Task(
        "task-1", "session-1", "actor-1", "User result", ("source-1",), (Condition("done"),)
    )


def test_task_round_trip_has_one_revision_and_embedded_skill_state(tmp_path):
    store = Store(tmp_path)
    with store.transaction() as tx:
        tx.create_task(task())
    with store.transaction() as tx:
        assert tx.task("task-1") == task()
        tx.save_task(task().start(), expected_revision=1)
    with store.transaction() as tx:
        assert tx.task("task-1").state == "running"
        with pytest.raises(CoreError, match="revision-conflict"):
            tx.save_task(task().start(), expected_revision=1)


def test_failed_transaction_does_not_leave_partial_work_or_poison_replay(tmp_path):
    store = Store(tmp_path)

    def fail(tx):
        tx.create_task(task())
        raise CoreError("observed-failure")

    with pytest.raises(CoreError, match="observed-failure"):
        store.command("actor-1", "once", "create", {"task": "task-1"}, fail)
    with store.transaction() as tx:
        assert tx.tasks() == ()
    result = store.command(
        "actor-1",
        "once",
        "create",
        {"task": "task-1"},
        lambda tx: tx.create_task(task()) or {"id": "task-1"},
    )
    assert result == {"id": "task-1"}


def test_same_request_replays_once_and_changed_input_is_rejected(tmp_path):
    store = Store(tmp_path)
    calls = []

    def create(tx):
        calls.append("executed")
        tx.create_task(task())
        return {"id": "task-1"}

    assert store.command("actor-1", "once", "create", {}, create) == {"id": "task-1"}
    assert store.command("actor-1", "once", "create", {}, create) == {"id": "task-1"}
    assert calls == ["executed"]
    with pytest.raises(CoreError, match="request-conflict"):
        store.command("actor-1", "once", "create", {"changed": True}, create)


def test_concurrent_checkout_claims_select_exactly_one_writer(tmp_path):
    store = Store(tmp_path)

    def claim(actor):
        try:
            with store.transaction() as tx:
                return tx.claim("/project/checkout", actor)
        except CoreError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("writer-a", "writer-b")))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("lease-conflict") == 1


def test_release_reclaim_fences_old_writer_and_preserves_new_owner(tmp_path):
    store = Store(tmp_path)
    with store.transaction() as tx:
        first = tx.claim("/project/checkout", "writer-a")
        assert tx.claim("/project/checkout", "writer-a") == first
        tx.release("/project/checkout", "writer-a", first["generation"])
        second = tx.claim("/project/checkout", "writer-b")
    assert second["generation"] == first["generation"] + 1
    with store.transaction() as tx:
        with pytest.raises(CoreError, match="stale-lease"):
            tx.release("/project/checkout", "writer-a", first["generation"])
        assert tx.lease("/project/checkout") == second


def test_source_cannot_change_under_same_identity_or_native_event(tmp_path):
    store = Store(tmp_path)
    source = Source.create("source-1", "user", "Publish this release", "host-event-1")
    with store.transaction() as tx:
        tx.put_source(source)
        tx.put_source(source)
        assert tx.source("source-1") == source
        with pytest.raises(CoreError, match="source-conflict"):
            tx.put_source(
                Source.create("source-1", "user", "Publish something else", "host-event-1")
            )
        with pytest.raises(CoreError, match="source-conflict"):
            tx.put_source(Source.create("different-id", "user", source.text, "host-event-1"))


def test_private_store_rejects_symlink_managed_path(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".neurath").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(CoreError, match="unsafe-store-path"):
        Store(tmp_path)
