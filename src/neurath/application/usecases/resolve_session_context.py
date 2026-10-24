"""환경·Git 관찰을 DB 조회 밖에서 수행하고 현재 명령의 세션을 결정한다."""

import asyncio
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.services.directory_observer import IDirectoryObserverService
from neurath.application.ports.services.host_environment import IHostEnvironmentService
from neurath.application.usecases.read_session_scope import (
    ReadSessionScopeQuery,
    ReadSessionScopeUseCase,
    SessionScope,
)
from neurath.domain.aggregates.project import Project


@immutable
class ResolveSessionContextQuery(AbstractQuery):
    """기본은 현재 호스트이며 다른 세션 조회만 명시적으로 지정한다.

    Attributes:
        session: 실제 호스트 주소 또는 미지정.
        project_id: 기존 명시 범위 호출과 호환되는 프로젝트.
        session_id: 기존 명시 범위 호출과 호환되는 세션.
        directory: 네이티브 훅이 직접 전달한 작업 폴더이며 미지정이면 현재 환경.
        provider: 네이티브 훅의 실제 공급자이며 미지정이면 현재 환경.
    """

    session: str = ""
    project_id: UUID | None = None
    session_id: UUID | None = None
    directory: str = ""
    provider: str = ""


@UseCase()
class ResolveSessionContextUseCase(IAsyncQueryUseCase[ResolveSessionContextQuery, SessionScope]):
    """호스트 맥락으로 내부 ID를 찾고 모델의 수작업 식별자 관리 부담을 없앤다."""

    def __init__(
        self,
        environment: IHostEnvironmentService,
        directories: IDirectoryObserverService,
        read: ReadSessionScopeUseCase,
    ) -> None:
        """외부 관찰과 짧은 DB 조회의 경계를 받는다.

        Args:
            environment: 현재 호스트 환경.
            directories: 파일 시스템·Git 관찰.
            read: 관찰값으로 저장된 세션을 조회한다.
        """
        self.environment = environment
        self.directories = directories
        self.read = read

    @override
    async def run(self, query: ResolveSessionContextQuery) -> SessionScope:
        """실제 환경을 관찰한 뒤 읽기 요청으로 범위를 결정한다.

        Args:
            query: 선택적으로 지정한 다른 조회 범위.

        Returns:
            SessionScope: 현재 호스트의 실제 저장 상태.
        """
        environment = self.environment.read()
        observation = await asyncio.to_thread(
            self.directories.observe, query.directory or environment.directory
        )
        native = query.session or environment.session
        if query.session_id is not None:
            native = ""
        return await self.read.run(
            ReadSessionScopeQuery(
                directory=Project.root_for(observation),
                native_session=native,
                provider=query.provider
                or ("" if query.session_id is not None or query.session else environment.provider),
                project_id=query.project_id,
                session_id=query.session_id,
            )
        )
