"""일반 요청이 자동 이전하지 않는 저장소를 명시적인 관리 요청으로 준비한다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.installation import IInstallationService


@immutable
class InitializeStoreCommand(AbstractCommand):
    """초기화·현재 스키마 이전을 요청할 파일이다.

    Attributes:
        database: 선택한 저장 파일 또는 기본 경로.
    """

    database: str | None = None


@UseCase()
class InitializeStoreUseCase(IAsyncCommandUseCase[InitializeStoreCommand, str]):
    """마이그레이션의 자체 원자 경계를 사용하며 업무 트랜잭션을 중첩하지 않는다."""

    def __init__(self, installation: IInstallationService) -> None:
        """원본 보존과 실제 스키마 이전 계약을 받는다.

        Args:
            installation: 데이터 보존형 관리 경로.
        """
        self.installation = installation

    @override
    async def run(self, command: InitializeStoreCommand) -> str:
        """명시적으로 요청한 저장소를 준비한다.

        Args:
            command: 초기화할 실제 저장 파일.

        Returns:
            str: 준비한 파일 경로.
        """
        return await self.installation.initialize(command.database)
