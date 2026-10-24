"""일관된 사본을 등록하고 같은 원본 자료를 중복 등록하지 않는다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.historical_archive import IHistoricalArchiveRepository
from neurath.domain.aggregates.historical_archive import HistoricalArchive


@immutable
class RegisterHistoricalArchiveCommand(AbstractCommand):
    """외부 사본 저장이 끝난 자료를 지정한다.

    Attributes:
        archive: 실제 생성한 사본의 내용과 위치.
    """

    archive: HistoricalArchive


@UseCase()
class RegisterHistoricalArchiveUseCase(
    IAsyncCommandUseCase[RegisterHistoricalArchiveCommand, HistoricalArchive]
):
    """외부 파일 작업 없이 사본의 원장 연결만 원자적으로 저장한다."""

    def __init__(self, archives: IHistoricalArchiveRepository) -> None:
        """보존 자료 저장 계약을 받는다.

        Args:
            archives: 같은 원본 사본 조회와 저장.
        """
        self.archives = archives

    @transactional
    @override
    async def run(self, command: RegisterHistoricalArchiveCommand) -> HistoricalArchive:
        """이미 등록된 같은 사본은 기존 연결을 반환한다.

        Args:
            command: 보존된 사본.

        Returns:
            HistoricalArchive: 최초 또는 기존 보존 연결.

        Raises:
            ValueError: 같은 사본을 다른 프로젝트 범위로 암묵 변경하려는 경우.
        """
        existing = await self.archives.find_by_source_path_and_digest(
            command.archive.source_path, command.archive.digest
        )
        if existing is not None:
            if existing.directory != command.archive.directory:
                raise ValueError("Historical source is already registered for another project")
            return existing
        return await self.archives.save(command.archive)
