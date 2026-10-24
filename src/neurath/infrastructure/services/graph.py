"""기존 Graphify CLI를 호출하며 원 그래프와 실패 산출물을 보존한다."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import cast, override
from uuid import uuid4

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.graph import IGraphService


@Pod()
class SubprocessGraphService(IGraphService):
    """기존 Graphify CLI를 호출하며 원 그래프와 실패 산출물을 보존한다."""

    @override
    def query(self, directory: str, question: str) -> str:
        """프로젝트의 기존 그래프에서 관련 문서·코드를 조회한다.

        Args:
            directory: Graphify 프로젝트 경로.
            question: 관계 조회 질문.

        Returns:
            str: Graphify 표준출력의 원래 조회 결과.
        """
        return subprocess.run(
            ["graphify", "query", question],
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout

    @override
    def update(self, directory: str) -> str:
        """원 그래프를 보관하고 문서 노드·관계·하이퍼엣지 손실을 검사한다.

        Args:
            directory: graphify-out/graph.json을 소유한 프로젝트 경로.

        Returns:
            str: 검증된 파일 URI와 SHA-256.

        Raises:
            ValueError: 문서 관계를 잃었거나 그래프 구조를 검증할 수 없는 경우.
            Exception: 도구 실행·검사 실패 시 원 그래프를 복원한 뒤 원래 오류를 전파한다.
        """
        graph = Path(directory).resolve() / "graphify-out" / "graph.json"
        original = graph.read_bytes()
        before = self._document_records(original)
        backup = graph.with_name(f"graph.before-{uuid4()}.json")
        backup.write_bytes(original)
        try:
            subprocess.run(
                ["graphify", "update", str(Path(directory).resolve())],
                cwd=directory,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            current = graph.read_bytes()
            if not before.issubset(self._document_records(current)):
                raise ValueError("Graphify update lost document relationships")
        except Exception:
            if graph.exists():
                graph.with_name(f"graph.failed-{uuid4()}.json").write_bytes(graph.read_bytes())
            graph.write_bytes(original)
            raise
        return f"{graph.as_uri()}#sha256={hashlib.sha256(current).hexdigest()}"

    @staticmethod
    def _document_records(content: bytes) -> set[str]:
        """문서 노드에 닿는 의미 관계의 안정적인 내용을 추출한다.

        커뮤니티 번호 같은 재계산 속성은 관계의 동일성에 포함하지 않는다.

        Args:
            content: Graphify JSON 원문.

        Returns:
            set[str]: 문서 노드·연결·하이퍼엣지의 정규화된 의미 기록.

        Raises:
            ValueError: 그래프 구조 또는 관계의 연결 대상이 잘못된 경우.
        """
        data: object = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("Graph must be an object")
        nodes = data.get("nodes")
        links = data.get("links")
        hyperedges = data.get("hyperedges", [])
        if not all(
            isinstance(items, list) and all(isinstance(item, dict) for item in items)
            for items in (nodes, links, hyperedges)
        ):
            raise ValueError("Graph nodes, links and hyperedges must be record lists")
        nodes = cast(list[dict[str, object]], nodes)
        links = cast(list[dict[str, object]], links)
        hyperedges = cast(list[dict[str, object]], hyperedges)
        docs = {
            str(node["id"])
            for node in nodes
            if "id" in node
            and Path(str(node.get("source_file", ""))).suffix.lower() in (".md", ".rst", ".txt")
        }
        identifiers = {str(node.get("id")) for node in nodes}
        records = {
            "node:" + SubprocessGraphService._semantic_record(node)
            for node in nodes
            if str(node.get("id")) in docs
        }
        for link in links:
            if (
                str(link.get("source")) not in identifiers
                or str(link.get("target")) not in identifiers
            ):
                raise ValueError("Graph contains a dangling relationship")
            if str(link.get("source")) in docs or str(link.get("target")) in docs:
                records.add("link:" + SubprocessGraphService._semantic_record(link))
        for edge in hyperedges:
            members = edge.get("nodes", edge.get("members", []))
            if not isinstance(members, list):
                raise ValueError("Hyperedge members must be a list")
            if any(str(member) not in identifiers for member in members):
                raise ValueError("Graph contains a dangling hyperedge")
            if any(str(member) in docs for member in members):
                records.add("hyperedge:" + SubprocessGraphService._semantic_record(edge))
        return records

    @staticmethod
    def _semantic_record(record: dict[str, object]) -> str:
        """원문·설명·근거를 유지하고 재계산되는 커뮤니티 통계만 비교에서 제외한다.

        Args:
            record: Graphify 노드 또는 의미 관계 레코드.

        Returns:
            str: 의미 속성을 보존한 정규 JSON.
        """
        derived = {"community", "community_name", "norm_label", "degree", "betweenness", "pagerank"}
        return json.dumps(
            {key: value for key, value in record.items() if key not in derived}, sort_keys=True
        )
