"""테스트에서 실제 유스케이스와 프레임워크 트랜잭션을 구동한다."""

from spakky.domain.application.command import IAsyncCommandUseCase
from spakky.plugins.sqlalchemy.persistency.transaction import AsyncTransaction

from tests.support.application import spakky_context


async def run(use_case, request, *, database_path=None):
    async with spakky_context(
        database_path, write=issubclass(use_case, IAsyncCommandUseCase)
    ) as scope:
        async with scope.get(AsyncTransaction):
            return await scope.get(use_case).run(request)
