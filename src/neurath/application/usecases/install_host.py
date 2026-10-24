"""현재 패키지의 CLI·가이드·스킬·훅을 선택한 로컬 호스트에 연결한다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.installation import IInstallationService, InstallationResult
from neurath.domain.enums.provider_kind import ProviderKind


@immutable
class InstallHostCommand(AbstractCommand):
    """실제 적용할 호스트와 설정 루트를 지정한다.

    Attributes:
        provider: Codex 또는 Claude 호스트.
        directory: 사용자 홈 또는 프로젝트 루트.
        data_home: 격리 검증용으로 선택한 데이터 홈 또는 사용자 기본값.
    """

    provider: ProviderKind
    directory: str
    data_home: str | None = None


@UseCase()
class InstallHostUseCase(IAsyncCommandUseCase[InstallHostCommand, InstallationResult]):
    """사용자 자료·다른 훅을 유지하면서 소유 설정만 갱신한다."""

    def __init__(self, installation: IInstallationService) -> None:
        """실제 호스트 파일 적용 경계를 받는다.

        Args:
            installation: 보존형 설치 구현.
        """
        self.installation = installation

    @override
    async def run(self, command: InstallHostCommand) -> InstallationResult:
        """파일 적용 결과를 반환하며 네이티브 승인이나 활성화를 꾸미지 않는다.

        Args:
            command: 명시적으로 요청한 설치 범위.

        Returns:
            InstallationResult: 실제 파일 변경·복구 사본과 다음 호스트 확인.
        """
        return await self.installation.install(
            command.provider, command.directory, command.data_home
        )
