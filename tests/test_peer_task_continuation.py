"""Retained user instructions survive peer ingress without becoming fresh prompts."""
import pytest

from tests.test_task_ledger_service import item

pytest_plugins = ["tests.test_task_ledger_service"]


def peer_turn(service):
    store, kernel, sk = service
    first = store.define([item()], expected_revision=0, key="original")
    source = first["tasks"][0]["definition"]["sources"][0]
    store.resolve(first["tasks"][0]["id"], expected_revision=1, expected_task_revision=1,
        key="original-result", references=["test:original"], status="succeeded", summary="Original work")
    turn = kernel.inspect(sk.SessionId("one")).foreground_turns[sk.ActorId("owner")]
    kernel.apply(sk.ForegroundTurnClosed(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        expected_turn_revision=turn.revision, idempotency_key="old-close"))
    kernel.apply(sk.ForegroundTurnPrompted(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        vendor_turn_id="peer-turn", prompt_digest=None, idempotency_key="peer"))
    assert store.list()["current_prompt_source"] is None
    return source


def test_peer_continuation_preserves_explicit_user_source_without_creating_prompt(service):
    store, _, _ = service
    source = peer_turn(service)
    continuation = item("continue")
    continuation["sources"] = [source]
    result = store.define([continuation], expected_revision=2, key="continue")
    assert result["current_prompt_source"] is None
    assert result["tasks"][-1]["definition"]["sources"] == [source]
    assert store.define([continuation], expected_revision=2, key="continue")["revision"] == 3


@pytest.mark.parametrize("invalid", ["empty", "spec-only", "wrong-digest", "foreign", "mixed"])
def test_peer_continuation_rejects_missing_or_forged_sources_atomically(service, invalid):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    store, _, _ = service
    source = peer_turn(service)
    tasks = [item("continue")]
    tasks[0]["sources"] = [source]
    if invalid == "empty":
        tasks[0]["sources"] = []
    elif invalid == "spec-only":
        tasks[0]["sources"] = [{"kind": "spec", "reference": "approved.md", "revision": "one"}]
    elif invalid == "wrong-digest":
        tasks[0]["sources"] = [{**source, "revision": "b" * 64}]
    elif invalid == "foreign":
        tasks[0]["sources"] = [{**source, "reference": "user-prompt:foreign"}]
    else:
        tasks.append(item("implicit-extra"))
    with pytest.raises(TaskLedgerError):
        store.define(tasks, expected_revision=2, key="rejected")
    assert store.list()["revision"] == 2
    assert len(store.list()["tasks"]) == 1
