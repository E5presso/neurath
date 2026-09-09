"""Task identity, dynamic scope and evidence bindings survive durable replay."""
from dataclasses import replace

import pytest


@pytest.fixture
def domain():
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness import task_ledger
    return task_ledger


def definition(d, key="first", **changes):
    return d.TaskDefinition(key=key, title="Resolve " + key, goal="Measurable result " + key,
        sources=(d.TaskSource("prompt", "prompt:original", "revision-1"),),
        acceptance=("Exact observable outcome is verified",), producer="workflow",
        evidence_contract="workflow-" + key, **changes)


def defined(d):
    return d.TaskLedger.empty("session", "owner").define((definition(d),),
        expected_revision=0, key="define")


def evidence(d, task, status=None):
    return d.TaskEvidence(status=status or d.TaskStatus.SUCCEEDED, subject=task.id,
        owner="owner", definition_digest=task.definition.digest, producer="workflow",
        references=("workflow:finished:4",), source_basis="revision-1",
        payload_digest="a" * 64, reason="Canonical result")


def test_task_ids_and_mutation_replay_survive_reordering_and_append(domain):
    d = domain
    a, b = definition(d), definition(d, "second")
    initial = d.TaskLedger.empty("session", "owner")
    first = initial.define((a, b), expected_revision=0, key="batch")
    assert first.define((b, a), expected_revision=0, key="batch") is first
    updated = first.define((definition(d, "third"),), expected_revision=1, key="append")
    assert updated.tasks[:2] == first.tasks
    assert len({task.id for task in updated.tasks}) == 3
    assert d.TaskLedger.decode(updated.encode()) == updated
    assert not updated.all_terminal


def test_changed_definition_and_late_batch_failure_leave_original_unchanged(domain):
    d = domain
    current = defined(d)
    before = current.encode()
    with pytest.raises(d.TaskLedgerError):
        current.define((definition(d, "new"), replace(definition(d), goal="different")),
                       expected_revision=1, key="new-batch")
    with pytest.raises(d.TaskLedgerError):
        current.define((definition(d, "different"),), expected_revision=1, key="define")
    assert current.encode() == before


def test_task_resolution_requires_exact_subject_owner_goal_and_reference(domain):
    d = domain
    current = defined(d)
    task = current.tasks[0]
    good = evidence(d, task)
    for bad in (replace(good, subject="other"), replace(good, owner="other"),
                replace(good, definition_digest="b" * 64), replace(good, producer="other"),
                replace(good, references=("another",))):
        with pytest.raises(d.TaskLedgerError):
            current.resolve(task.id, expected_revision=1, expected_task_revision=1,
                key="resolve", references=good.references, resolver=lambda *_: bad)
    assert current.tasks[0].status is d.TaskStatus.PENDING


def test_terminal_outcomes_are_derived_and_survive_dynamic_expansion(domain):
    d = domain
    for status in (d.TaskStatus.SUCCEEDED, d.TaskStatus.FAILED, d.TaskStatus.INVALIDATED):
        current = defined(d)
        task = current.tasks[0]
        proof = evidence(d, task, status)
        terminal = current.resolve(task.id, expected_revision=1, expected_task_revision=1,
            key="resolve", references=proof.references, resolver=lambda *_: proof)
        assert terminal.all_terminal
        assert terminal.tasks[0].status is status
        restored = d.TaskLedger.decode(terminal.encode())
        assert restored == terminal
        extended = restored.define((definition(d, "new"),), expected_revision=2, key="append")
        assert not extended.all_terminal
        assert extended.tasks[0] == terminal.tasks[0]
        with pytest.raises(d.TaskLedgerError):
            extended.start(task.id, expected_revision=3, expected_task_revision=2, key="restart")


def test_maximum_size_dependency_chain_is_supported_and_cycle_rejected(domain):
    d = domain
    tasks = tuple(d.TaskRecord(d.task_id("session", str(index)), definition(d, str(index),
        dependencies=() if index == 1023 else (d.task_id("session", str(index + 1)),)))
        for index in range(1024))
    assert len(d.TaskLedger("session", "owner", tasks=tasks).tasks) == 1024
    last = replace(tasks[-1], definition=replace(tasks[-1].definition, dependencies=(tasks[0].id,)))
    with pytest.raises(d.TaskLedgerError, match="cyclic"):
        d.TaskLedger("session", "owner", tasks=(*tasks[:-1], last))


def test_task_dependency_and_revision_conflicts_are_atomic(domain):
    d = domain
    current = defined(d)
    task = current.tasks[0]
    with pytest.raises(d.TaskLedgerError):
        current.define((definition(d, "child", dependencies=("missing",)),),
                       expected_revision=1, key="child")
    with pytest.raises(d.TaskLedgerError):
        current.define((definition(d, "cycle", dependencies=(d.task_id("session", "cycle"),)),),
                       expected_revision=1, key="cycle")
    with pytest.raises(d.TaskRevisionConflict):
        current.start(task.id, expected_revision=0, expected_task_revision=1, key="start")
    active = current.start(task.id, expected_revision=1, expected_task_revision=1, key="start")
    assert active.tasks[0].status is d.TaskStatus.IN_PROGRESS
    assert active.start(task.id, expected_revision=1, expected_task_revision=1, key="start") is active


def test_task_codec_rejects_corrupt_evidence_and_unknown_fields(domain):
    import json
    d = domain
    current = defined(d)
    payload = json.loads(current.encode())
    payload["tasks"][0]["definition"]["unknown"] = True
    with pytest.raises(d.TaskLedgerError):
        d.TaskLedger.decode(json.dumps(payload).encode())
    assert not d.TaskLedger.empty("session", "owner").all_terminal
