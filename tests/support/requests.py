"""테스트에서 실제 유스케이스와 프레임워크 트랜잭션을 구동한다."""

from spakky.domain.application.command import ICommandUseCase
from spakky.plugins.sqlalchemy.persistency.transaction import Transaction

from neurath.infrastructure.providers import DatabaseSettings, request_container


def run(use_case, request, *, database_path=None):
    with request_container(
        DatabaseSettings(database_path, write=issubclass(use_case, ICommandUseCase))
    ) as scope:
        with scope.get(Transaction):
            return scope.get(use_case).run(request)
