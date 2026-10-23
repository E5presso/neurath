"""현재 enclave와 과거·삭제 이력을 분리하는 도메인 동작을 검증한다."""

import pytest

from neurath.domain.aggregates.enclave import Enclave
from neurath.domain.enclave_records import EnclaveFact, EnclaveKind
from neurath.domain.errors import ContextNotFound, RevisionConflict


def fact(value="current", kind=EnclaveKind.FACT, key="constraint"):
    return EnclaveFact(key=key, value=value, kind=kind, references=["source:original"])


def test_empty_enclave_and_scope_are_preserved():
    enclave = Enclave.create("project", "session")
    assert enclave.facts == enclave.history == ()
    assert (enclave.project_id, enclave.session_id, enclave.task_id) == ("project", "session", None)
    task = Enclave.create("project", "session", "task")
    assert task.task_id == "task"
    assert task.uid != enclave.uid


def test_correction_and_removal_keep_history_but_restore_only_current_facts():
    enclave = Enclave.create("project", "session")
    original = fact("unconfirmed", EnclaveKind.ASSUMPTION)
    corrected = fact("confirmed")
    other = fact("decision", EnclaveKind.DECISION, "approach")
    enclave.set(original, 1)
    enclave.set(other, 1)
    enclave.set(corrected, 1)
    assert enclave.facts == (other, corrected)
    assert [change.fact for change in enclave.history] == [original, other, corrected]
    enclave.remove("constraint", 1)
    assert enclave.facts == (other,)
    assert enclave.history[-1].fact is None
    assert enclave.history[-1].number == 4
    enclave.remove("approach", 1)
    assert enclave.facts == ()
    assert len(enclave.history) == 5


def test_stale_set_and_remove_do_not_change_current_state_or_history():
    enclave = Enclave.create("project", "session")
    enclave.set(fact(), 1)
    before = (enclave.revision, enclave.facts, enclave.history, enclave.version)
    with pytest.raises(RevisionConflict):
        enclave.set(fact("old update"), 0)
    with pytest.raises(RevisionConflict):
        enclave.remove("constraint", 0)
    assert (enclave.revision, enclave.facts, enclave.history, enclave.version) == before
    enclave.remove("constraint", 1)
    with pytest.raises(RevisionConflict):
        enclave.set(fact("revived"), 0)
    assert enclave.facts == ()


def test_same_value_is_noop_but_missing_remove_is_not_silent():
    enclave = Enclave.create("project", "session")
    enclave.set(fact(), 1)
    before = (enclave.revision, enclave.history, enclave.version)
    enclave.set(fact(), 1)
    assert (enclave.revision, enclave.history, enclave.version) == before
    with pytest.raises(ContextNotFound):
        enclave.remove("unknown", 1)
    assert (enclave.revision, enclave.history, enclave.version) == before


@pytest.mark.parametrize(
    "key,value,references",
    [
        ("", "value", ["source"]),
        ("key", " ", ["source"]),
        ("key", "value", []),
        ("key", "value", ["source", " "]),
    ],
)
def test_fact_requires_content_and_source(key, value, references):
    with pytest.raises(ValueError):
        EnclaveFact(key=key, value=value, kind=EnclaveKind.FACT, references=references)
