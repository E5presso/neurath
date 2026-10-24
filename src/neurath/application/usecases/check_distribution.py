"""배포의 check 요청을 외부 실행·파일 계약에 연결한다."""

import asyncio
from typing import Any, override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.services.distribution import IDistributionService


@immutable
class CheckDistributionQuery(AbstractQuery):
    """정확한 배포 대상과 범위를 전달한다.

    Attributes:
        installed: 명시한 installed 입력.
    """

    installed: str | None = None


@UseCase()
class CheckDistributionUseCase(IAsyncQueryUseCase[CheckDistributionQuery, dict[str, Any]]):
    """DB 트랜잭션을 유지하지 않고 실제 배포 결과를 반환한다."""

    def __init__(self, distribution: IDistributionService) -> None:
        """실제 배포 기술 계약을 받는다.

        Args:
            distribution: 후보·설정·복구의 기술 경계.
        """
        self.distribution = distribution

    @override
    async def run(self, query: CheckDistributionQuery) -> dict[str, Any]:
        """요청한 범위만 수행하고 파일 적용과 호스트 전달을 구분한다.

        Args:
            query: 정확한 배포 입력.

        Returns:
            dict[str, Any]: 실제 관찰·수행 결과.
        """
        return await asyncio.to_thread(self.distribution.check, query.installed)
