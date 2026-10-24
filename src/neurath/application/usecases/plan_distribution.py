"""배포의 plan 요청을 외부 실행·파일 계약에 연결한다."""

import asyncio
from typing import Any, override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.distribution import IDistributionService


@immutable
class PlanDistributionCommand(AbstractCommand):
    """정확한 배포 대상과 범위를 전달한다.

    Attributes:
        candidate: 명시한 candidate 입력.
        provider: 명시한 provider 입력.
        directory: 명시한 directory 입력.
        data_home: 명시한 data_home 입력.
    """

    candidate: str
    provider: str
    directory: str
    data_home: str


@UseCase()
class PlanDistributionUseCase(IAsyncCommandUseCase[PlanDistributionCommand, dict[str, Any]]):
    """DB 트랜잭션을 유지하지 않고 실제 배포 결과를 반환한다."""

    def __init__(self, distribution: IDistributionService) -> None:
        """실제 배포 기술 계약을 받는다.

        Args:
            distribution: 후보·설정·복구의 기술 경계.
        """
        self.distribution = distribution

    @override
    async def run(self, command: PlanDistributionCommand) -> dict[str, Any]:
        """요청한 범위만 수행하고 파일 적용과 호스트 전달을 구분한다.

        Args:
            command: 정확한 배포 입력.

        Returns:
            dict[str, Any]: 실제 관찰·수행 결과.
        """
        return await asyncio.to_thread(
            self.distribution.plan,
            command.candidate,
            command.provider,
            command.directory,
            command.data_home,
        )
