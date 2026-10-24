"""프로젝트를 식별하고 공급자·네이티브 ID가 같은 세션을 재사용하거나 등록한다."""

import asyncio
from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.record_session import RecordSessionCommand, RecordSessionUseCase
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import RevisionConflict
from neurath.domain.values.directory_observation import DirectoryObservation


@immutable
class RegisterSessionCommand(AbstractCommand):
    """관찰한 프로젝트 위치와 등록할 호스트의 네이티브 세션 식별자를 지정한다.

    Attributes:
        observation: 프로젝트 식별 규칙에 사용하는 정규화된 외부 관찰 사실.
        provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
        host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.
    """

    observation: DirectoryObservation
    provider: str
    host_session_id: str


@immutable
class RegisterSessionResult:
    """등록 위치의 프로젝트와 기존 또는 새 호스트 세션을 반환한다.

    Attributes:
        project: 세션이 속한 프로젝트와 소유 위치.
        session: 동일 네이티브 ID의 기존 세션 또는 새로 생성한 세션.
    """

    project: Project
    session: HostSession


@UseCase()
class RegisterSessionUseCase(IAsyncCommandUseCase[RegisterSessionCommand, RegisterSessionResult]):
    """같은 네이티브 주소 등록의 DB 경합만 짧게 재조회하며 원 식별자를 유지한다."""

    def __init__(self, record: RecordSessionUseCase) -> None:
        """등록 트랜잭션을 맡는 작업 단위를 받는다.

        Args:
            record: 기존 위치·세션 조회와 원자 저장.
        """
        self.record = record

    @override
    async def run(self, command: RegisterSessionCommand) -> RegisterSessionResult:
        """롤백된 등록 경합만 새 트랜잭션으로 반복하고 외부 작업을 재실행하지 않는다.

        Args:
            command: 실제 관찰한 위치와 네이티브 주소.

        Returns:
            RegisterSessionResult: 경합 뒤에도 같은 주소의 단일 세션.

        세 번의 짧은 재조회 뒤에도 경합이 계속되면 RevisionConflict를 전달한다.
        """
        for attempt in range(2):
            try:
                result = await self.record.run(
                    RecordSessionCommand(
                        observation=command.observation,
                        provider=command.provider,
                        host_session_id=command.host_session_id,
                    )
                )
                return RegisterSessionResult(project=result.project, session=result.session)
            except RevisionConflict:
                await asyncio.sleep(0.02 * (attempt + 1))
        result = await self.record.run(
            RecordSessionCommand(
                observation=command.observation,
                provider=command.provider,
                host_session_id=command.host_session_id,
            )
        )
        return RegisterSessionResult(project=result.project, session=result.session)
