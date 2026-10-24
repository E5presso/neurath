"""원본 선택 조회를 끝낸 뒤 현재 관찰 세션의 기존 작업 경로로 이어간다."""

from dataclasses import asdict, replace
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.historical_store import IHistoricalStoreService
from neurath.application.usecases.adopt_historical_work import (
    AdoptHistoricalWorkCommand,
    AdoptHistoricalWorkUseCase,
)
from neurath.application.usecases.get_historical_archive import (
    GetHistoricalArchiveQuery,
    GetHistoricalArchiveUseCase,
)
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.domain.aggregates.task import Task


@immutable
class ResumeHistoricalWorkCommand(AbstractCommand):
    """기존 요청 범위에서 이어갈 원 작업을 선택한다.

    Attributes:
        archive_id: 등록된 보존 자료.
        key: 조회에서 확인한 과거 작업 식별자.
        workflow_key: 함께 이어갈 것으로 선택한 과거 절차.
    """

    archive_id: UUID
    key: str
    workflow_key: str | None = None


@UseCase()
class ResumeHistoricalWorkUseCase(IAsyncCommandUseCase[ResumeHistoricalWorkCommand, Task]):
    """새 인간 승인·신원 입력 없이 현재 호스트 관찰과 선택 자료를 연결한다."""

    def __init__(
        self,
        context: ResolveSessionContextUseCase,
        archives: GetHistoricalArchiveUseCase,
        store: IHistoricalStoreService,
        adopt: AdoptHistoricalWorkUseCase,
    ) -> None:
        """현재 관찰·외부 읽기·원자 저장을 분리한 작업 단위를 받는다.

        Args:
            context: 현재 실제 호스트 실행.
            archives: 등록된 사본.
            store: 원본 형식 읽기.
            adopt: 실제 선택 재개의 원자 저장.
        """
        self.context = context
        self.archives = archives
        self.store = store
        self.adopt = adopt

    @override
    async def run(self, command: ResumeHistoricalWorkCommand) -> Task:
        """현재 실행과 원 작업을 읽고 중복 없는 연결을 저장한다.

        Args:
            command: 에이전트가 선택한 과거 작업.

        Returns:
            Task: 현재 원장으로 연결한 실제 작업.

        Raises:
            ValueError: 현재 실행이나 선택 작업을 확인하지 못한 경우.
        """
        scope = await self.context.run(ResolveSessionContextQuery())
        if scope.execution is None:
            raise ValueError("Current host execution has not been observed")
        scope.execution.require_turn(scope.execution.turn_id)
        archive = await self.archives.run(GetHistoricalArchiveQuery(archive_id=command.archive_id))
        page = self.store.read(archive.snapshot_path, "tasks", key=command.key)
        record = next(iter(page.records), None)
        if record is None:
            raise ValueError("Historical task was not found; no current work was created")
        prerequisites = []
        for key in record.data.get("dependencies", []):
            if not isinstance(key, str):
                raise ValueError("Historical dependency identifier is unrecognized")
            candidates = self.store.read(archive.snapshot_path, "tasks", key=key)
            prerequisite = next(iter(candidates.records), None)
            if prerequisite is None:
                raise ValueError(
                    "Historical dependencies reference unavailable work; source remains preserved"
                )
            prerequisites.append(asdict(prerequisite))
        record = replace(record, data={**record.data, "prerequisites": prerequisites})
        if command.workflow_key is not None:
            workflows = self.store.read(
                archive.snapshot_path, "workflows", key=command.workflow_key
            )
            workflow = next(iter(workflows.records), None)
            if workflow is None:
                raise ValueError("Selected historical workflow was not found")
            phase_run = workflow.data.get("payload", {}).get("phase_run", {})
            phases = phase_run.get("phases", [workflow.data] if "name" in workflow.data else [])
            if not phases:
                raise ValueError(
                    "Selected workflow has no interpretable phases; its source remains preserved"
                )
            record = replace(
                record,
                data={
                    **record.data,
                    "phases": phases,
                    "selected_workflow": asdict(workflow),
                    "workflow_association": "explicit continuation selection; original links retained",
                },
            )
        return await self.adopt.run(
            AdoptHistoricalWorkCommand(
                archive_id=archive.uid,
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                record=record,
            )
        )
