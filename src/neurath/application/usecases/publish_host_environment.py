"""실제 SessionStart의 세션 주소를 호스트의 환경 전달 계약에 게시한다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.host_environment import IHostEnvironmentService


@immutable
class PublishHostEnvironmentCommand(AbstractCommand):
    """실제 시작 훅에서 관찰한 호스트 세션 주소다.

    Attributes:
        provider: 실제 공급자.
        session: 실제 네이티브 세션 주소.
    """

    provider: str
    session: str


@UseCase()
class PublishHostEnvironmentUseCase(IAsyncCommandUseCase[PublishHostEnvironmentCommand, None]):
    """사용자에게 내부 ID 전달을 요구하지 않고 공식 환경 파일로 연결한다."""

    def __init__(self, environment: IHostEnvironmentService) -> None:
        """호스트가 제공한 환경 전달 경로를 받는다.

        Args:
            environment: 현재 호스트의 환경 입출력 계약.
        """
        self.environment = environment

    @override
    async def run(self, command: PublishHostEnvironmentCommand) -> None:
        """실제 시작 사건의 주소만 호스트에 전달한다.

        Args:
            command: 관찰된 공급자와 세션.
        """
        self.environment.publish(command.provider, command.session)
