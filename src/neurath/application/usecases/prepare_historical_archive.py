"""원본 읽기·파일 사본을 끝낸 뒤 현재 저장소에 보존 위치를 연결한다."""

from collections.abc import Sequence
from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.directory_observer import IDirectoryObserverService
from neurath.application.ports.services.historical_store import IHistoricalStoreService
from neurath.application.usecases.register_historical_archive import (
    RegisterHistoricalArchiveCommand,
    RegisterHistoricalArchiveUseCase,
)
from neurath.domain.aggregates.historical_archive import HistoricalArchive
from neurath.domain.aggregates.project import Project


@immutable
class PrepareHistoricalArchiveCommand(AbstractCommand):
    """명시한 원본·대상 프로젝트와 사본 보관 위치를 지정한다.

    Attributes:
        source: 읽을 원본 SQLite.
        directory: 대상 프로젝트 폴더.
        archive_directory: 새 사본을 보관할 폴더.
        configs: 함께 보존할 명시적 설정 파일.
    """

    source: str
    directory: str
    archive_directory: str
    configs: Sequence[str] = ()


@UseCase()
class PrepareHistoricalArchiveUseCase(
    IAsyncCommandUseCase[PrepareHistoricalArchiveCommand, HistoricalArchive]
):
    """원본 파일·설정·현재 작업을 바꾸지 않는 준비 경로다."""

    def __init__(
        self,
        store: IHistoricalStoreService,
        directories: IDirectoryObserverService,
        register: RegisterHistoricalArchiveUseCase,
    ) -> None:
        """외부 관찰과 짧은 저장 작업 단위를 받는다.

        Args:
            store: 실제 SQLite 사본 생성.
            directories: 대상 프로젝트 위치 관찰.
            register: 사본 생성 뒤 원장 연결 저장.
        """
        self.store = store
        self.directories = directories
        self.register = register

    @override
    async def run(self, command: PrepareHistoricalArchiveCommand) -> HistoricalArchive:
        """쓰기 트랜잭션 밖에서 원본을 복제하고 결과만 등록한다.

        Args:
            command: 원본·프로젝트·사본 위치.

        Returns:
            HistoricalArchive: 아직 현재 작업을 생성하지 않은 보존 자료.
        """
        directory = Project.root_for(self.directories.observe(command.directory))
        snapshot = self.store.snapshot(command.source, command.archive_directory, command.configs)
        return await self.register.run(
            RegisterHistoricalArchiveCommand(
                archive=HistoricalArchive(
                    uid=HistoricalArchive.next_id(),
                    directory=directory,
                    source_path=snapshot.inspection.source_path,
                    snapshot_path=snapshot.path,
                    digest=snapshot.digest,
                    format=snapshot.inspection.format,
                    tables=snapshot.inspection.tables,
                )
            )
        )
