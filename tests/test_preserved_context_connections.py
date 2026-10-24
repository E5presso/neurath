"""맥락 인수와 그래프 정정에서 충돌만 거절하고 정상 변경·원 이력은 보존한다."""

import json
import subprocess
from uuid import uuid7

import pytest

from neurath.application.usecases.update_enclave import SetEnclaveFact
from neurath.domain.aggregates.enclave import Enclave
from neurath.domain.enums.delegation_status import DelegationStatus
from neurath.domain.enums.provider_status import ProviderStatus
from neurath.infrastructure.services.graph import SubprocessGraphService
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_evaluation_domain import assignment
from tests.test_graph_memory import document_graph
from tests.test_memory_requests import fact, native, preview, update


def test_enclave_merges_disjoint_current_facts_but_not_conflicting_values():
    project = uuid7()
    source = Enclave.create(project, uuid7())
    target = Enclave.create(project, uuid7())
    source.set(fact("preserved source", "source"), source.revision)
    target.set(fact("retained target", "target"), target.revision)
    history = source.history
    target.merge_from(source)
    assert {item.key for item in target.facts} == {"source", "target"}
    assert source.history == history
    target.merge_from(source)
    assert len(target.facts) == 2
    source.set(fact("conflict", "target"), source.revision)
    before = target.history
    with pytest.raises(ValueError, match="conflict"):
        target.merge_from(source)
    assert target.history == before
    with pytest.raises(ValueError, match="unrelated"):
        target.merge_from(Enclave.create(uuid7(), uuid7()))


async def test_handoff_merges_current_facts_preserves_source_history_and_is_idempotent(
    database, tmp_path
):
    from neurath.application.usecases.resume_session import (
        ResumeSessionCommand,
        ResumeSessionUseCase,
    )

    source = await register_session(str(tmp_path), "codex", "source", database_path=database)
    target = await register_session(str(tmp_path), "claude", "target", database_path=database)
    await native(database, source, "UserPromptSubmit")
    await native(database, target, "UserPromptSubmit")
    original = await update(
        database,
        source,
        changes=[SetEnclaveFact(fact=fact("source fact", "source"))],
    )
    await update(database, target)
    await native(database, source, "SessionEnd")
    command = ResumeSessionCommand(
        project_id=source.project.uid,
        source_session_id=source.session.uid,
        target_session_id=target.session.uid,
        expected_revision=source.session.revision,
        turn_id="turn",
    )
    transferred = await run(ResumeSessionUseCase, command, database_path=database)
    assert transferred.uid == target.session.uid
    assert (
        await run(ResumeSessionUseCase, command, database_path=database)
    ).uid == target.session.uid
    current = await preview(database, target)
    assert {item.key for item in current.enclaves[0].facts} == {"source", "rule"}
    previous = await preview(database, source)
    assert previous.enclaves[0].history[0] == original.history[0]
    assert previous.enclaves[0].facts == ()
    # 같은 이전 턴의 늦은 사건은 인수한 작업을 되돌리지 않는다.
    late = await native(database, source, "UserPromptSubmit")
    assert "handed off" in late["hookSpecificOutput"]["additionalContext"]
    from tests.support.hook_cli import HookCliClient

    response = await HookCliClient("codex", database).handle(
        {
            "session_id": "source",
            "cwd": str(tmp_path),
            "hook_event_name": "UserPromptSubmit",
            "turn_id": "new-actual-turn",
            "prompt": "New work, keep transferred work with its owner",
        }
    )
    assert response == {}
    assert (await preview(database, source)).session.successor_id is None
    assert {item.key for item in (await preview(database, target)).enclaves[0].facts} == {
        "source",
        "rule",
    }


def test_graph_source_revision_allows_relationship_change_and_preserves_backup(
    tmp_path, monkeypatch
):
    source = tmp_path / "docs/spec.md"
    source.parent.mkdir()
    source.write_text("original requirement")
    graph = tmp_path / "graphify-out/graph.json"
    graph.parent.mkdir()
    graph.write_text(json.dumps(document_graph()))
    replacement = document_graph()

    def update_graph(args, **kwargs):
        graph.write_text(json.dumps(replacement))
        return subprocess.CompletedProcess(args, 0, "updated", "")

    monkeypatch.setattr(subprocess, "run", update_graph)
    service = SubprocessGraphService()
    service.update(str(tmp_path))
    original = graph.read_bytes()
    source.write_text("corrected requirement")
    replacement["nodes"][0]["label"] = "Corrected requirement"
    replacement["links"][1]["relation"] = "corrects"
    replacement["hyperedges"][0]["relation"] = "revised implementation"
    service.update(str(tmp_path))
    assert json.loads(graph.read_text())["links"][1]["relation"] == "corrects"
    assert any(path.read_bytes() == original for path in graph.parent.glob("graph.before-*.json"))
    assert SubprocessGraphService._document_records(graph.read_bytes(), {"docs/spec.md"}) == set()


def test_stop_request_preserves_finished_work_and_only_targets_running_provider():
    current = assignment()
    with pytest.raises(ValueError):
        current.request_stop(" ")
    current.request_stop("user withdrew")
    assert current.status is DelegationStatus.STOP_REQUESTED
    current.request_stop("duplicate")
    assert current.stop_reason == "user withdrew"
    finished = assignment(status=DelegationStatus.COMPLETED)
    finished.request_stop("do not restart already finished work")
    assert finished.status is DelegationStatus.COMPLETED and finished.stop_reason is None
    provider = assignment(provider_requested=True, provider_status=ProviderStatus.RUNNING)
    provider.request_stop("user withdrew this running request")
    assert provider.status is DelegationStatus.STOP_REQUESTED
    assert any(type(item).__name__ == "ProviderStopRequested" for item in provider.events)
