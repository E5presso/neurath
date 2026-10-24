"""선택한 과거 자료를 읽은 뒤 현재 기억과 맥락 참조로 연결한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.historical_store import IHistoricalStoreService
from neurath.application.usecases.get_historical_archive import (
    GetHistoricalArchiveQuery,
    GetHistoricalArchiveUseCase,
)
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.save_recalled_history import (
    SaveRecalledHistoryCommand,
    SaveRecalledHistoryUseCase,
)
from neurath.domain.aggregates.memory import Memory


@immutable
class RecallHistoricalRecordCommand(AbstractCommand):
    """현재 사용하려고 선택한 과거 자료를 지정한다.

    Attributes:
        archive_id: 등록한 사본.
        category: 과거 기능 영역.
        key: 해당 영역의 자료 식별자.
        task_id: 연결할 현재 작업 또는 None.
    """

    archive_id: UUID
    category: str
    key: str
    task_id: UUID | None = None


@UseCase()
class RecallHistoricalRecordUseCase(IAsyncCommandUseCase[RecallHistoricalRecordCommand, Memory]):
    """외부 자료 읽기 중 쓰기 잠금을 잡지 않고 기존 기억 경로를 사용한다."""

    def __init__(
        self,
        context: ResolveSessionContextUseCase,
        archives: GetHistoricalArchiveUseCase,
        store: IHistoricalStoreService,
        save: SaveRecalledHistoryUseCase,
    ) -> None:
        """실제 현재 범위·사본 읽기·기억 저장을 받는다.

        Args:
            context: 현재 관찰 세션.
            archives: 보존 사본의 등록 정보.
            store: 원본 형식 해석.
            save: 현재 기억과 명시적 참조 저장.
        """
        self.context = context
        self.archives = archives
        self.store = store
        self.save = save

    @override
    async def run(self, command: RecallHistoricalRecordCommand) -> Memory:
        """원래 상태를 보존해 현재 관련 작업에서 상세 읽기할 수 있게 한다.

        Args:
            command: 사용하려고 선택한 과거 자료.

        Returns:
            Memory: 현재 기억 경로에서 읽을 수 있는 원문.

        Raises:
            ValueError: 해당 자료가 없거나 작업을 기억으로 대신 재개하려는 경우.
        """
        if command.category in {"tasks", "unknown"}:
            raise ValueError("Use task resumption or inspect unrecognized data instead")
        scope = await self.context.run(ResolveSessionContextQuery())
        archive = await self.archives.run(GetHistoricalArchiveQuery(archive_id=command.archive_id))
        page = self.store.read(archive.snapshot_path, command.category, key=command.key)
        record = next(iter(page.records), None)
        if record is None:
            raise ValueError("Selected historical record was not found")
        return await self.save.run(
            SaveRecalledHistoryCommand(
                archive_id=archive.uid,
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                task_id=command.task_id,
                record=record,
            )
        )
