"""기억 조회·검색·저장과 현재 맥락 갱신을 공식 Typer 명령으로 노출한다."""

import json
import sys
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Exit, Option, echo

from neurath.application.usecases.query_graph import QueryGraphQuery, QueryGraphUseCase
from neurath.application.usecases.read_memory import ReadMemoryQuery, ReadMemoryUseCase
from neurath.application.usecases.save_checkpoint import (
    SaveCheckpointCommand,
    SaveCheckpointUseCase,
)
from neurath.application.usecases.search_memory import SearchMemoryQuery, SearchMemoryUseCase
from neurath.application.usecases.update_enclave import (
    RemoveEnclaveFact,
    SetEnclaveFact,
    UpdateEnclaveCommand,
    UpdateEnclaveUseCase,
)
from neurath.domain.aggregates.memory import GraphUpdateStatus
from neurath.domain.values.enclave_fact import EnclaveFact, EnclaveKind
from neurath.serialization import encode_uuid


@CliController("memory")
class MemoryCliController:
    """memory 하위 명령에서 입력을 해석하고 유스케이스의 결과를 JSON으로 반환한다."""

    def __init__(
        self,
        update: UpdateEnclaveUseCase,
        checkpoint: SaveCheckpointUseCase,
        read: ReadMemoryUseCase,
        search: SearchMemoryUseCase,
        connection: AsyncConnectionManager,
        query_graph: QueryGraphUseCase,
    ) -> None:
        """현재 맥락과 과거 기억을 조회·저장하는 작업 단위를 주입받는다.

        Args:
            update: 현재 맥락 변경.
            checkpoint: 보고 저장.
            read: 선택 기록 조회.
            search: 관련 기록 검색.
            connection: 같은 명령 루프에서 정리할 비동기 엔진.
            query_graph: 기존 Graphify 관계 조회.
        """
        self.update = update
        self.checkpoint = checkpoint
        self.read = read
        self.search = search
        self.connection = connection
        self.query_graph = query_graph

    @command("update")
    async def update_enclave(
        self,
        project_id: Annotated[UUID, Option("--project-id")],
        session_id: Annotated[UUID, Option("--session-id")],
        expected_revision: Annotated[int, Option("--expected-revision")],
        changes: Annotated[str, Option("--changes")],
        task_id: UUID | None = None,
    ) -> None:
        """JSON 변경 목록을 같은 개정의 현재 맥락에 원자적으로 적용한다.

        Args:
            project_id: 프로젝트 ID.
            session_id: 현재 세션 ID.
            expected_revision: 최초 생성 0 또는 조회한 개정.
            changes: op=set/remove와 key를 가진 JSON 배열. set은 value·kind·references와 선택적 details를 포함한다.
            task_id: 선택한 작업 ID.
        """
        try:
            result = await self.update.run(
                UpdateEnclaveCommand(
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    expected_revision=expected_revision,
                    changes=self._changes(changes),
                )
            )
            echo(
                json.dumps(
                    {
                        "id": result.uid,
                        "revision": result.revision,
                        "facts": [asdict(fact) for fact in result.facts],
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()

    @staticmethod
    def _changes(value: str) -> list[SetEnclaveFact | RemoveEnclaveFact]:
        """외부 JSON의 형식과 구분을 확인해 타입이 있는 변경 목록으로 변환한다.

        Args:
            value: CLI가 받은 변경 배열 JSON이며 -는 표준입력을 뜻한다.

        Returns:
            list[SetEnclaveFact | RemoveEnclaveFact]: 형식을 확인한 변경 목록.

        Raises:
            ValueError: 배열·항목·문자열·출처·변경 종류의 형식이 잘못된 경우.
        """
        data: object = json.load(sys.stdin) if value == "-" else json.loads(value)
        if not isinstance(data, list):
            raise ValueError("changes must be an array")
        changes: list[SetEnclaveFact | RemoveEnclaveFact] = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                raise ValueError("Each change requires a string key")
            if item.get("op") == "remove":
                changes.append(RemoveEnclaveFact(key=item["key"]))
                continue
            references = item.get("references")
            if (
                item.get("op") != "set"
                or not isinstance(item.get("value"), str)
                or not isinstance(item.get("kind"), str)
                or not isinstance(references, list)
                or not all(isinstance(reference, str) for reference in references)
            ):
                raise ValueError("set requires value, kind and string references")
            details = item.get("details")
            if details is not None and not isinstance(details, str):
                raise ValueError("details must be a string")
            changes.append(
                SetEnclaveFact(
                    fact=EnclaveFact(
                        key=item["key"],
                        value=item["value"],
                        kind=EnclaveKind(item["kind"]),
                        references=references,
                    ),
                    details=details,
                )
            )
        return changes

    @command("checkpoint")
    async def save_checkpoint(
        self,
        project_id: Annotated[UUID, Option("--project-id")],
        session_id: Annotated[UUID, Option("--session-id")],
        content: Annotated[str, Option("--content")],
        reference: Annotated[list[str], Option("--reference")],
        task_id: UUID | None = None,
        graph_directory: str | None = None,
    ) -> None:
        """원문 참조와 결과·남은 일·다음 행동의 보고를 저장한다.

        Args:
            project_id: 프로젝트 ID.
            session_id: 보고 세션 ID.
            content: 보고 본문. -를 지정하면 표준입력 전체를 읽는다.
            reference: 반복 지정하는 출처·산출물 참조.
            task_id: 관련 작업 ID.
            graph_directory: 명시적으로 갱신·검증할 Graphify 프로젝트 경로.

        Raises:
            Exit: 외부 갱신이 실패했거나 결과가 저장되지 않아 성공을 확인할 수 없는 경우.
        """
        try:
            content = sys.stdin.read() if content == "-" else content
            result = await self.checkpoint.run(
                SaveCheckpointCommand(
                    project_id=project_id,
                    session_id=session_id,
                    content=content,
                    references=reference,
                    task_id=task_id,
                    graph_directory=graph_directory,
                )
            )
            if graph_directory is not None:
                result = await self.read.run(
                    ReadMemoryQuery(project_id=project_id, memory_id=result.uid)
                )
            echo(
                json.dumps(
                    {
                        "id": result.uid,
                        "kind": result.kind.value,
                        "graph_status": result.graph_status,
                        "graph_reference": result.graph_reference,
                        "graph_error": result.graph_error,
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
            if result.graph_status not in (None, GraphUpdateStatus.SUCCEEDED):
                raise Exit(code=1)
        finally:
            await self.connection.dispose()

    @command("search")
    async def search_memory(
        self,
        project_id: Annotated[UUID, Option("--project-id")],
        text: str = "",
        session_id: UUID | None = None,
        task_id: UUID | None = None,
        limit: int = 20,
        graph_directory: str | None = None,
    ) -> None:
        """관련 범위의 과거 자료를 검색해 상세 조회할 ID를 반환한다.

        Args:
            project_id: 프로젝트 ID.
            text: 본문 검색 문자열.
            session_id: 기록 작성 세션 제한.
            task_id: 관련 작업 제한.
            limit: 결과 개수.
            graph_directory: 함께 조회할 기존 Graphify 프로젝트 경로.
        """
        try:
            result = await self.search.run(
                SearchMemoryQuery(
                    project_id=project_id,
                    text=text,
                    session_id=session_id,
                    task_id=task_id,
                    limit=limit,
                )
            )
            graph_result = (
                None
                if graph_directory is None
                else await self.query_graph.run(
                    QueryGraphQuery(directory=graph_directory, question=text)
                )
            )
            echo(
                json.dumps(
                    {"memory_ids": result, "graph": graph_result},
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()

    @command("read")
    async def read_memory(
        self,
        project_id: Annotated[UUID, Option("--project-id")],
        memory_id: Annotated[UUID, Option("--memory-id")],
    ) -> None:
        """선택한 기억 기록의 원문과 출처를 읽는다.

        Args:
            project_id: 기억이 속한 프로젝트 ID.
            memory_id: 검색 또는 참조에서 선택한 과거 기록 ID.
        """
        try:
            result = await self.read.run(
                ReadMemoryQuery(project_id=project_id, memory_id=memory_id)
            )
            echo(
                json.dumps(
                    {
                        "id": result.uid,
                        "kind": result.kind.value,
                        "content": result.content,
                        "references": result.references,
                        "session_id": result.session_id,
                        "task_id": result.task_id,
                        "graph_status": result.graph_status,
                        "graph_reference": result.graph_reference,
                        "graph_error": result.graph_error,
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()
