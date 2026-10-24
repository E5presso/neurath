"""모델을 실행하지 않고 설치된 provider의 실제 모델·정책을 조회한다."""

import asyncio
from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.services.provider import IProviderService, ProviderCapabilities
from neurath.domain.enums.provider_kind import ProviderKind


@immutable
class DiscoverProviderQuery(AbstractQuery):
    """지원 정보를 확인할 호스트를 지정한다.

    Attributes:
        provider: 설치된 공급자 이름.
    """

    provider: ProviderKind


@UseCase()
class DiscoverProviderUseCase(IAsyncQueryUseCase[DiscoverProviderQuery, ProviderCapabilities]):
    """외부 초기화 응답만 조회하며 DB 쓰기 잠금이나 추론 요청을 만들지 않는다."""

    def __init__(self, provider: IProviderService) -> None:
        """실제 호스트 조회 계약을 받는다.

        Args:
            provider: 현재 모델과 명시적 정책을 조회하는 어댑터.
        """
        self.provider = provider

    @override
    async def run(self, query: DiscoverProviderQuery) -> ProviderCapabilities:
        """실제 지원 모델과 정책을 반환한다.

        Args:
            query: 조회할 공급자.

        Returns:
            ProviderCapabilities: 추론 없이 확인한 모델·정책 목록.
        """
        return await asyncio.to_thread(self.provider.discover, query.provider)
