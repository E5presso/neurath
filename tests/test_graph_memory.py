"""전문 그래프 도구의 실행 결과와 문서 의미 관계 보존을 독립적으로 검증한다."""

import json
import subprocess

import pytest

from neurath.application.ports.services.graph import IGraphService
from neurath.application.usecases.query_graph import QueryGraphQuery, QueryGraphUseCase
from neurath.infrastructure.services.graph import SubprocessGraphService


def document_graph():
    return {
        "nodes": [
            {"id": "doc", "label": "Requirement", "source_file": "docs/spec.md"},
            {"id": "code", "source_file": "main.py"},
        ],
        "links": [
            {"source": "code", "target": "code", "relation": "calls"},
            {
                "source": "doc",
                "target": "code",
                "relation": "requires",
                "confidence": "INFERRED",
                "source_file": "docs/spec.md",
            },
        ],
        "hyperedges": [{"nodes": ["doc", "code"], "relation": "implements"}, {"nodes": ["code"]}],
    }


@pytest.fixture
def graph(tmp_path):
    file = tmp_path / "graphify-out" / "graph.json"
    file.parent.mkdir()
    file.write_text(json.dumps(document_graph()))
    return file


async def test_existing_graphify_is_called_and_semantic_records_survive(graph, monkeypatch):
    calls = []

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == "update":
            data = document_graph()
            data["nodes"][0]["community"] = 42
            data["nodes"][0]["norm_label"] = "requirement"
            graph.write_text(json.dumps(data))
        return subprocess.CompletedProcess(args, 0, "related doc and code", "")

    monkeypatch.setattr(subprocess, "run", execute)
    service = SubprocessGraphService()
    assert (
        await QueryGraphUseCase(service).run(
            QueryGraphQuery(directory=str(graph.parent.parent), question="requirement")
        )
        == "related doc and code"
    )
    reference = service.update(str(graph.parent.parent))
    assert reference.startswith(graph.as_uri() + "#sha256=")
    assert calls[0][0] == ["graphify", "query", "requirement"]
    assert calls[1][0][1] == "update"
    assert list(graph.parent.glob("graph.before-*.json"))


@pytest.mark.parametrize(
    "failure", ["relation", "node", "hyperedge", "process", "missing", "description"]
)
def test_graph_update_failure_restores_original_and_preserves_failed_output(
    graph, monkeypatch, failure
):
    original = graph.read_bytes()

    def execute(args, **kwargs):
        data = document_graph()
        if failure == "process":
            raise subprocess.CalledProcessError(2, args)
        if failure == "missing":
            graph.unlink()
            return
        if failure == "relation":
            data["links"] = []
        if failure == "node":
            data["nodes"][0]["label"] = "lost meaning"
        if failure == "description":
            data["links"][1]["description"] = "changed semantics"
        if failure == "hyperedge":
            data["hyperedges"] = []
        graph.write_text(json.dumps(data))

    monkeypatch.setattr(subprocess, "run", execute)
    with pytest.raises((ValueError, subprocess.CalledProcessError, FileNotFoundError)):
        SubprocessGraphService().update(str(graph.parent.parent))
    assert graph.read_bytes() == original
    assert list(graph.parent.glob("graph.before-*.json"))


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {
            "nodes": [],
            "links": [
                {"source": "code", "target": "code", "relation": "calls"},
            ],
        },
        {
            "nodes": [{"id": "doc", "source_file": "doc.md"}],
            "links": [
                {"source": "code", "target": "code", "relation": "calls"},
            ],
            "hyperedges": [{"nodes": "bad"}],
        },
    ],
)
def test_graph_validation_rejects_malformed_records_and_dangling_links(data):
    with pytest.raises(ValueError):
        SubprocessGraphService._document_records(json.dumps(data).encode())


def test_abstract_graph_contract_fails_explicitly():
    with pytest.raises(NotImplementedError):
        IGraphService.query(None, "/work", "question")
    with pytest.raises(NotImplementedError):
        IGraphService.update(None, "/work")


@pytest.mark.parametrize("kind", ["link", "hyperedge"])
def test_dangling_document_relationship_is_rejected(kind):
    data = document_graph()
    if kind == "link":
        data["links"][1]["target"] = "missing"
    else:
        data["hyperedges"][0]["nodes"].append("missing")
    with pytest.raises(ValueError, match="dangling"):
        SubprocessGraphService._document_records(json.dumps(data).encode())


def test_malformed_hyperedge_members_are_rejected_before_semantic_comparison():
    data = document_graph()
    data["hyperedges"][0]["nodes"] = "not a member list"
    with pytest.raises(ValueError, match="members must be a list"):
        SubprocessGraphService._document_records(json.dumps(data).encode())


@pytest.mark.parametrize(
    "data",
    [
        {"nodes": [], "links": []},
        {
            "nodes": [{"id": "code", "source_file": "main.py"}],
            "links": [{"source": "code", "target": "code", "relation": "calls"}],
        },
    ],
)
def test_document_preservation_does_not_require_every_project_to_have_documents(data):
    assert SubprocessGraphService._document_records(json.dumps(data).encode()) == set()
