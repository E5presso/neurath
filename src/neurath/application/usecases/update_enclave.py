"""현재 맥락의 변경 목록을 하나의 트랜잭션으로 적용한다."""

from collections.abc import Sequence
from dataclasses import replace
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.enclave import IEnclaveRepository
from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.enclave import Enclave
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.errors import RevisionConflict
from neurath.domain.values.enclave_fact import EnclaveFact


@immutable
class SetEnclaveFact:
    """현재 내용과 선택적 상세 자료를 저장한다.

    Attributes:
        fact: 현재 복원할 짧은 내용과 출처.
        details: 별도 기억으로 보존할 전체 상세 본문 또는 None.
    """

    fact: EnclaveFact
    details: str | None = None


@immutable
class RemoveEnclaveFact:
    """현재 항목의 명시적 삭제를 요청한다.

    Attributes:
        key: 삭제할 키.
    """

    key: str


@immutable
class UpdateEnclaveCommand(AbstractCommand):
    """같은 예상 개정을 기준으로 적용할 변경을 지정한다.

    Attributes:
        project_id: 대상 프로젝트.
        session_id: 소유 세션.
        task_id: 작업 범위 또는 세션 공통의 None.
        expected_revision: 최초 생성은 0, 이후에는 조회한 개정.
        changes: 순서대로 원자 적용할 저장·삭제 목록.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID | None
    expected_revision: int
    changes: Sequence[SetEnclaveFact | RemoveEnclaveFact]


@UseCase()
class UpdateEnclaveUseCase(IAsyncCommandUseCase[UpdateEnclaveCommand, Enclave]):
    """범위와 개정을 확인하고 상세 자료·현재 내용·변경 이력을 함께 저장한다."""

    def __init__(
        self,
        sessions: ISessionRepository,
        tasks: ITaskRepository,
        enclaves: IEnclaveRepository,
        memories: IMemoryRepository,
    ) -> None:
        """범위와 aggregate 저장 계약을 주입받는다.

        Args:
            sessions: 소유 세션 확인.
            tasks: 작업 소유 범위 확인.
            enclaves: 현재 맥락과 변경 이력 저장.
            memories: 큰 상세 자료 저장.
        """
        self.sessions = sessions
        self.tasks = tasks
        self.enclaves = enclaves
        self.memories = memories

    @transactional
    @override
    async def run(self, command: UpdateEnclaveCommand) -> Enclave:
        """오래된 쓰기와 다른 작업 변경을 거절하며 전체 변경 목록을 저장한다.

        Args:
            command: 범위·개정·변경 목록.

        Returns:
            Enclave: 저장 후의 현재 개정과 이력.

        Raises:
            ValueError: 변경 목록이 비어 있는 경우.
            RevisionConflict: 생성 또는 수정 예상 개정이 현재와 다른 경우.
        """
        session = await self.sessions.get(command.session_id)
        session.require_project(command.project_id)
        session.require_current_owner()
        if command.task_id is not None:
            (await self.tasks.get(command.task_id)).require_scope(
                command.project_id, command.session_id
            )
        if not command.changes:
            raise ValueError("At least one enclave change is required")
        enclave = next(
            (
                item
                for item in await self.enclaves.find_by_session_id(command.session_id)
                if item.task_id == command.task_id
            ),
            None,
        )
        actual = 0 if enclave is None else enclave.revision
        if actual != command.expected_revision:
            raise RevisionConflict("Enclave revision changed")
        if enclave is None:
            enclave = Enclave.create(command.project_id, command.session_id, command.task_id)
        for change in command.changes:
            if isinstance(change, RemoveEnclaveFact):
                enclave.remove(change.key, enclave.revision)
                continue
            fact = change.fact
            if change.details is not None:
                memory = await self.memories.save(
                    Memory.create(
                        command.project_id,
                        command.session_id,
                        command.task_id,
                        MemoryKind.ARTIFACT,
                        change.details,
                        fact.references,
                    )
                )
                fact = replace(fact, references=(*fact.references, f"memory:{memory.uid}"))
            enclave.set(fact, enclave.revision)
        return await self.enclaves.save(enclave)
