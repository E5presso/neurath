"""내부 스케줄러의 단일 감시 관찰과 요청한 감시 상세 조회를 제공한다."""

import json
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.get_monitor import GetMonitorQuery, GetMonitorUseCase
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.tick_monitor import TickMonitorCommand, TickMonitorUseCase
from neurath.serialization import encode_uuid


@CliController("monitor")
class MonitorCliController:
    """원래 요청의 감시를 조회하거나 내부 런타임에서 한 번만 관찰한다."""

    def __init__(
        self,
        tick: TickMonitorUseCase,
        status: GetMonitorUseCase,
        connection: AsyncConnectionManager,
        context: ResolveSessionContextUseCase,
    ) -> None:
        """실제 작업 단위와 명령 이벤트 루프의 정리 계약을 받는다.

        Args:
            tick: 커밋된 예약 뒤 외부 관찰·알림·결과 저장.
            status: 첫 관찰·사건·실패·필요한 조작 조회.
            connection: 명령 이벤트 루프에서 정리할 연결.
            context: 현재 호스트 범위를 자동 조회한다.
        """
        self.tick = tick
        self.status = status
        self.connection = connection
        self.context = context

    async def _scope(self, project_id: UUID | None, session_id: UUID | None) -> tuple[UUID, UUID]:
        """명시 범위가 없으면 현재 호스트의 실제 소유 범위를 사용한다.

        Args:
            project_id: 명시 프로젝트 또는 None.
            session_id: 명시 세션 또는 None.

        Returns:
            tuple[UUID, UUID]: 조회에 사용할 현재 프로젝트·세션.
        """
        if project_id is not None and session_id is not None:
            return project_id, session_id
        scope = await self.context.run(
            ResolveSessionContextQuery(project_id=project_id, session_id=session_id)
        )
        return scope.session.project_id, scope.session.uid

    @command("tick")
    async def tick_monitor(
        self,
        *,
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
        session_id: Annotated[UUID | None, Option("--session-id")] = None,
        task_id: Annotated[UUID, Option("--task-id")],
        monitor_number: Annotated[int, Option("--monitor-number")],
        execution_id: Annotated[UUID | None, Option("--execution-id")] = None,
        generation: Annotated[int | None, Option("--generation")] = None,
    ) -> None:
        """등록된 정확한 감시를 내부 런타임에서 한 번만 관찰한다.

        Args:
            project_id: 요청한 프로젝트.
            session_id: 현재 소유 세션.
            task_id: 외부 의존을 가진 태스크.
            monitor_number: 정확한 감시 순번.
            execution_id: 실제 소유 실행.
            generation: 조회한 현재 자원 세대.
        """
        try:
            project_id, session_id = await self._scope(project_id, session_id)
            if execution_id is None or generation is None:
                current = await self.status.run(
                    GetMonitorQuery(
                        project_id=project_id,
                        session_id=session_id,
                        task_id=task_id,
                        monitor_number=monitor_number,
                    )
                )
                execution_id = current.owner_execution_id if execution_id is None else execution_id
                generation = current.generation if generation is None else generation
            result = await self.tick.run(
                TickMonitorCommand(
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    monitor_number=monitor_number,
                    execution_id=execution_id,
                    generation=generation,
                )
            )
            echo(json.dumps(asdict(result), default=encode_uuid, ensure_ascii=False))
        finally:
            await self.connection.dispose()

    @command("status")
    async def read_monitor(
        self,
        *,
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
        session_id: Annotated[UUID | None, Option("--session-id")] = None,
        task_id: Annotated[UUID, Option("--task-id")],
        monitor_number: Annotated[int, Option("--monitor-number")],
    ) -> None:
        """실제 관찰과 정확한 사건·실패·잔여 예산을 부작용 없이 조회한다.

        Args:
            project_id: 조회할 프로젝트.
            session_id: 현재 소유 세션.
            task_id: 외부 의존을 가진 태스크.
            monitor_number: 조회할 정확한 감시 순번.
        """
        try:
            project_id, session_id = await self._scope(project_id, session_id)
            result = await self.status.run(
                GetMonitorQuery(
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    monitor_number=monitor_number,
                )
            )
            echo(json.dumps(asdict(result), default=encode_uuid, ensure_ascii=False))
        finally:
            await self.connection.dispose()
