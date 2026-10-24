"""운영 DB를 읽기 전용으로 열어 손상·연결·현재 재개 경계를 진단한다."""

import asyncio
import os
from collections.abc import Sequence
from pathlib import Path
from typing import override
from urllib.parse import unquote
from uuid import UUID

from spakky.core.pod.annotations.pod import Pod
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection

from neurath.application.ports.services.diagnostics import DiagnosticFinding, IDiagnosticsService
from neurath.application.ports.services.directory_observer import IDirectoryObserverService
from neurath.domain.aggregates.project import Project
from neurath.infrastructure.database import (
    create_database_engine,
    user_database_path,
    verify_schema,
)
from neurath.infrastructure.models.execution import ExecutionModel
from neurath.infrastructure.models.project import ProjectLocationModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.models.task import TaskModel
from neurath.infrastructure.models.writer import WriterModel


@Pod()
class SQLAlchemyDiagnosticsService(IDiagnosticsService):
    """실제 저장소의 읽기 실패와 비어 있는 업무 상태를 구분한다."""

    def __init__(self, directories: IDirectoryObserverService) -> None:
        """폴더·Git 관찰 계약을 받으며 업무용 DB 연결에 의존하지 않는다.

        Args:
            directories: 조회만 수행하는 프로젝트 위치 관찰.
        """
        self.directories = directories

    @staticmethod
    def _configured_path() -> Path:
        """현재 SQLAlchemy 설정에서 파일 기반 비동기 SQLite 경로만 읽는다.

        Returns:
            Path: 현재 프로세스가 사용하도록 설정된 파일 경로.

        Raises:
            ValueError: 파일 기반 비동기 SQLite 설정이 아닌 경우.
        """
        configured = os.environ.get("SPAKKY_SQLALCHEMY__CONNECTION_STRING")
        if not configured:
            return user_database_path()
        url = make_url(configured)
        if url.drivername != "sqlite+aiosqlite" or not url.database or url.database == ":memory:":
            raise ValueError("Expected a file-backed sqlite+aiosqlite connection")
        return Path(unquote(url.database.removeprefix("file:")))

    @override
    async def inspect(
        self, database: str | None, directory: str | None, provider: str, host_session_id: str
    ) -> Sequence[DiagnosticFinding]:
        """설정을 먼저 관찰하고 DB·프로젝트·재개 범위를 각각 진단한다.

        Args:
            database: 별도로 선택할 저장 파일 또는 현재 설정.
            directory: 실제 프로젝트 폴더 또는 None.
            provider: 조회할 호스트 공급자.
            host_session_id: 현재 재개 경계를 읽을 실제 세션 ID.

        Returns:
            Sequence[DiagnosticFinding]: 확인한 사실과 실패·미확인 항목.
        """
        findings = []
        configured = None
        try:
            configured = self._configured_path()
            findings.append(
                DiagnosticFinding(area="configuration", status="ok", detail=str(configured))
            )
        except Exception as error:
            findings.append(
                DiagnosticFinding(
                    area="configuration",
                    status="failed",
                    detail=f"Invalid SQLite configuration: {type(error).__name__}; inspect SPAKKY_SQLALCHEMY__CONNECTION_STRING and XDG_DATA_HOME",
                )
            )
        path = Path(database) if database is not None else configured
        if path is None:
            return (
                *findings,
                *self._unavailable(
                    "unknown", "No usable database path; pass --database explicitly"
                ),
            )
        if not path.is_file():
            return (
                *findings,
                *self._unavailable("missing", f"Database is missing: {path}; no file was created"),
            )
        engine = create_database_engine(path, write=False)
        try:
            async with engine.connect() as connection:
                integrity = (
                    (await connection.exec_driver_sql("PRAGMA integrity_check")).scalars().all()
                )
                foreign_keys = (await connection.exec_driver_sql("PRAGMA foreign_key_check")).all()
                findings.append(
                    DiagnosticFinding(
                        area="integrity",
                        status="ok" if integrity == ["ok"] and not foreign_keys else "failed",
                        detail=f"integrity={integrity}; foreign_keys={foreign_keys}",
                    )
                )
                try:
                    await connection.run_sync(verify_schema)
                except Exception as error:
                    findings.append(
                        DiagnosticFinding(area="schema", status="failed", detail=str(error))
                    )
                    return (
                        *findings,
                        DiagnosticFinding(
                            area="project", status="unknown", detail="Schema is incompatible"
                        ),
                        DiagnosticFinding(
                            area="resume",
                            status="unknown",
                            detail="Schema is incompatible; unfinished state was not changed",
                        ),
                    )
                findings.append(
                    DiagnosticFinding(
                        area="schema", status="ok", detail="Stored Alembic heads match this package"
                    )
                )
                project_id = await self._project(connection, directory, findings)
                await self._resume(connection, project_id, provider, host_session_id, findings)
        except Exception as error:
            observed = {item.area for item in findings}
            findings.extend(
                item
                for item in self._unavailable("failed", f"{type(error).__name__}: {error}")
                if item.area not in observed
            )
        finally:
            await engine.dispose()
        return tuple(findings)

    @staticmethod
    def _unavailable(status: str, reason: str) -> Sequence[DiagnosticFinding]:
        """DB를 확인할 수 없는 항목에 실제 부재·실패를 표시한다.

        Args:
            status: 부재·실패·미확인 상태.
            reason: 재현할 수 있는 원인.

        Returns:
            Sequence[DiagnosticFinding]: DB에 의존하는 각 진단의 실패 결과.
        """
        return tuple(
            DiagnosticFinding(area=area, status=status, detail=reason)
            for area in ("integrity", "schema", "project", "resume")
        )

    async def _project(
        self, connection: AsyncConnection, directory: str | None, findings: list[DiagnosticFinding]
    ) -> UUID | None:
        """실제 폴더 별칭을 읽어 등록된 프로젝트 연결만 반환한다.

        Args:
            connection: 읽기 전용 진단 연결.
            directory: 관찰할 폴더 또는 미지정.
            findings: 이번 요청의 진단 결과.

        Returns:
            UUID | None: 확인한 프로젝트 ID이며 자료 부재·실패면 None.
        """
        if directory is None:
            findings.append(
                DiagnosticFinding(
                    area="project", status="missing", detail="No working directory supplied"
                )
            )
            return None
        observation = await asyncio.to_thread(self.directories.observe, directory)
        owners = set()
        for location in Project.identify(observation):
            owner = await connection.scalar(
                select(ProjectLocationModel.project_id).where(
                    ProjectLocationModel.kind == location.kind.value,
                    ProjectLocationModel.path == location.path,
                )
            )
            if owner is not None:
                owners.add(owner)
        if len(owners) != 1:
            findings.append(
                DiagnosticFinding(
                    area="project",
                    status="failed" if owners else "missing",
                    detail=f"Observed project owners: {sorted(str(x) for x in owners)}; no association was changed",
                )
            )
            return None
        owner = owners.pop()
        findings.append(DiagnosticFinding(area="project", status="ok", detail=str(owner)))
        return owner

    @staticmethod
    async def _resume(
        connection: AsyncConnection,
        project_id: UUID | None,
        provider: str,
        host_session_id: str,
        findings: list[DiagnosticFinding],
    ) -> None:
        """세션·현재 턴·미완료 태스크·작성 상태를 관찰만 하고 재개하지 않는다.

        Args:
            connection: 읽기 전용 진단 연결.
            project_id: 관찰된 프로젝트 ID.
            provider: 실제 호스트 공급자.
            host_session_id: 실제 호스트 세션 ID.
            findings: 이번 요청의 결과 목록.
        """
        if project_id is None or not provider or not host_session_id:
            findings.append(
                DiagnosticFinding(
                    area="resume",
                    status="missing",
                    detail="Project, provider and host session are required; liveness is unverified",
                )
            )
            return
        session = (
            await connection.execute(
                select(SessionModel.id, SessionModel.successor_id).where(
                    SessionModel.project_id == project_id,
                    SessionModel.provider == provider,
                    SessionModel.host_session_id == host_session_id,
                )
            )
        ).first()
        if session is None:
            findings.append(
                DiagnosticFinding(
                    area="resume",
                    status="missing",
                    detail="No stored native session matches this project and address",
                )
            )
            return
        executions = (
            await connection.execute(
                select(
                    ExecutionModel.id,
                    ExecutionModel.turn_id,
                    ExecutionModel.status,
                    ExecutionModel.reason,
                ).where(ExecutionModel.session_id == session.id)
            )
        ).all()
        tasks = (
            await connection.execute(
                select(TaskModel.id, TaskModel.status).where(
                    TaskModel.owner_session_id == session.id,
                    TaskModel.status.not_in(("succeeded", "invalidated")),
                )
            )
        ).all()
        writers = (
            await connection.execute(
                select(
                    WriterModel.resource, WriterModel.execution_id, WriterModel.generation
                ).where(WriterModel.execution_id.in_([row.id for row in executions]))
            )
        ).all()
        findings.append(
            DiagnosticFinding(
                area="resume",
                status="ok" if executions else "missing",
                detail=f"session={session.id}; successor={session.successor_id}; executions={executions}; unfinished={tasks}; writers={writers}; actual liveness unverified; no state was resumed or completed",
            )
        )
