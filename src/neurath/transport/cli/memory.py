"""기억 조회·검색·저장과 현재 맥락 갱신을 공식 Typer 명령으로 노출한다."""

import json
import sys
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Exit, Option, echo

from neurath.application.usecases.create_lesson import CreateLessonCommand, CreateLessonUseCase
from neurath.application.usecases.get_enclave import GetEnclaveQuery, GetEnclaveUseCase
from neurath.application.usecases.observe_lesson import ObserveLessonCommand, ObserveLessonUseCase
from neurath.application.usecases.query_graph import QueryGraphQuery, QueryGraphUseCase
from neurath.application.usecases.read_memory import ReadMemoryQuery, ReadMemoryUseCase
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
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
from neurath.domain.aggregates.memory import GraphUpdateStatus, MemoryKind
from neurath.domain.values.enclave_fact import EnclaveFact, EnclaveKind
from neurath.domain.values.lesson_observation import LessonObservation, LessonState
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
        context: ResolveSessionContextUseCase,
        enclave: GetEnclaveUseCase,
        create_lesson: CreateLessonUseCase,
        observe_lesson: ObserveLessonUseCase,
    ) -> None:
        """현재 맥락과 과거 기억을 조회·저장하는 작업 단위를 주입받는다.

        Args:
            update: 현재 맥락 변경.
            checkpoint: 보고 저장.
            read: 선택 기록 조회.
            search: 관련 기록 검색.
            connection: 같은 명령 루프에서 정리할 비동기 엔진.
            query_graph: 기존 Graphify 관계 조회.
            context: 실제 현재 호스트 범위 확인.
            enclave: 최신 사실·개정 조회.
            create_lesson: 요청된 회고의 독립 보고에서 교훈 후보 저장.
            observe_lesson: 실제 검증·적용·철회 결과 저장.
        """
        self.update = update
        self.checkpoint = checkpoint
        self.read = read
        self.search = search
        self.connection = connection
        self.query_graph = query_graph
        self.context = context
        self.enclave = enclave
        self.create_lesson = create_lesson
        self.observe_lesson = observe_lesson

    @command("update")
    async def update_enclave(
        self,
        *,
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
        session_id: Annotated[UUID | None, Option("--session-id")] = None,
        expected_revision: Annotated[int | None, Option("--expected-revision")] = None,
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
            scope = await self.context.run(
                ResolveSessionContextQuery(project_id=project_id, session_id=session_id)
            )
            project_id = scope.session.project_id
            session_id = scope.session.uid
            if expected_revision is None:
                current = await self.enclave.run(
                    GetEnclaveQuery(project_id=project_id, session_id=session_id, task_id=task_id)
                )
                expected_revision = 0 if current is None else current.revision
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
        *,
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
        session_id: Annotated[UUID | None, Option("--session-id")] = None,
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
            scope = await self.context.run(
                ResolveSessionContextQuery(project_id=project_id, session_id=session_id)
            )
            project_id = scope.session.project_id
            session_id = scope.session.uid
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
                        "lessons": [asdict(item) for item in result.lessons],
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
        *,
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
        text: str = "",
        session_id: UUID | None = None,
        task_id: UUID | None = None,
        limit: int = 20,
        graph_directory: str | None = None,
        kind: MemoryKind | None = None,
        lesson_state: LessonState | None = None,
    ) -> None:
        """관련 범위의 과거 자료를 검색해 상세 조회할 ID를 반환한다.

        Args:
            project_id: 프로젝트 ID.
            text: 본문 검색 문자열.
            session_id: 기록 작성 세션 제한.
            task_id: 관련 작업 제한.
            limit: 결과 개수.
            graph_directory: 함께 조회할 기존 Graphify 프로젝트 경로.
            kind: 선택할 기억 유형.
            lesson_state: 선택할 교훈의 현재 상태.
        """
        try:
            if project_id is None:
                scope = await self.context.run(
                    ResolveSessionContextQuery(project_id=project_id, session_id=session_id)
                )
                project_id = scope.session.project_id
            result = await self.search.run(
                SearchMemoryQuery(
                    project_id=project_id,
                    text=text,
                    session_id=session_id,
                    task_id=task_id,
                    limit=limit,
                    kind=kind,
                    lesson_state=lesson_state,
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
        *,
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
        memory_id: Annotated[UUID, Option("--memory-id")],
    ) -> None:
        """선택한 기억 기록의 원문과 출처를 읽는다.

        Args:
            project_id: 기억이 속한 프로젝트 ID.
            memory_id: 검색 또는 참조에서 선택한 과거 기록 ID.
        """
        try:
            if project_id is None:
                scope = await self.context.run(
                    ResolveSessionContextQuery(project_id=project_id, session_id=None)
                )
                project_id = scope.session.project_id
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
                        "lessons": [asdict(item) for item in result.lessons],
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

    @command("propose-lesson")
    async def propose_lesson(
        self,
        run_id: Annotated[UUID, Option("--run-id")],
        phase: Annotated[str, Option("--phase")],
        content: Annotated[str, Option("--content")],
        reference: Annotated[list[str], Option("--reference")],
    ) -> None:
        """요청되고 독립 평가된 회고에서 출처 있는 개선 후보를 보존한다.

        Args:
            run_id: 요청된 회고를 수행한 원 절차.
            phase: 실제 독립 회고 단계.
            content: 원인과 적용 범위의 본문이며 -는 stdin.
            reference: 원 지시·문제·검토의 근거.
        """
        try:
            body = sys.stdin.read() if content == "-" else content
            scope = await self.context.run(ResolveSessionContextQuery())
            memory = await self.create_lesson.run(
                CreateLessonCommand(
                    project_id=scope.session.project_id,
                    session_id=scope.session.uid,
                    run_id=run_id,
                    phase_key=phase,
                    content=body,
                    references=reference,
                )
            )
            echo(
                json.dumps(
                    {"id": memory.uid, "state": memory.lessons[-1].state}, default=encode_uuid
                )
            )
        finally:
            await self.connection.dispose()

    @command("observe-lesson")
    async def record_lesson_effect(
        self,
        memory_id: Annotated[UUID, Option("--memory-id")],
        state: Annotated[LessonState, Option("--state")],
        reason: Annotated[str, Option("--reason")],
        reference: Annotated[list[str], Option("--reference")],
        failure_case: str = "",
        normal_case: str = "",
        effective: Annotated[bool | None, Option("--effective/--ineffective")] = None,
    ) -> None:
        """호스트 도구로 실제 적용·검증한 교훈의 효과를 다음 작업에 연결한다.

        Args:
            memory_id: 기존 출처 있는 교훈.
            state: 관찰한 검증·적용·보류·철회 상태.
            reason: 실제 효과와 판단 이유.
            reference: 실제 변경·검증의 근거.
            failure_case: 원 실패를 재현·재검증한 근거.
            normal_case: 정상 동작을 재검증한 근거.
            effective: 후속 수행에서 확인한 개선 여부.
        """
        try:
            observation = LessonObservation(
                state=state,
                reason=reason,
                references=reference,
                failure_case=failure_case,
                normal_case=normal_case,
                effective=effective,
            )
            scope = await self.context.run(ResolveSessionContextQuery())
            memory = await self.observe_lesson.run(
                ObserveLessonCommand(
                    project_id=scope.session.project_id,
                    session_id=scope.session.uid,
                    memory_id=memory_id,
                    observation=observation,
                )
            )
            echo(
                json.dumps(
                    {"id": memory.uid, "state": memory.lessons[-1].state}, default=encode_uuid
                )
            )
        finally:
            await self.connection.dispose()
