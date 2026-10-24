"""선택한 과거 맥락·협업·학습 자료를 현재 기억과 명시적 참조로 연결한다."""

import json
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.enclave import IEnclaveRepository
from neurath.application.ports.repositories.historical_archive import IHistoricalArchiveRepository
from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.historical_store import HistoricalRecord
from neurath.domain.aggregates.enclave import Enclave
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.values.enclave_fact import EnclaveFact, EnclaveKind
from neurath.serialization import encode_historical


@immutable
class SaveRecalledHistoryCommand(AbstractCommand):
    """현재 범위와 선택한 과거 자료를 지정한다.

    Attributes:
        archive_id: 보존 사본.
        project_id: 현재 프로젝트.
        session_id: 현재 실제 세션.
        record: 선택한 과거 원문과 상태.
        task_id: 연결할 현재 작업이며 공통 기억이면 None.
    """

    archive_id: UUID
    project_id: UUID
    session_id: UUID
    record: HistoricalRecord
    task_id: UUID | None = None


@UseCase()
class SaveRecalledHistoryUseCase(IAsyncCommandUseCase[SaveRecalledHistoryCommand, Memory]):
    """과거 사실·읽음·학습 효과를 현재에 자동 승격하지 않는다."""

    def __init__(
        self,
        archives: IHistoricalArchiveRepository,
        projects: IProjectRepository,
        sessions: ISessionRepository,
        tasks: ITaskRepository,
        memories: IMemoryRepository,
        enclaves: IEnclaveRepository,
    ) -> None:
        """선택 범위와 기존 기억·현재 맥락 저장 계약을 받는다.

        Args:
            archives: 명시한 사본 범위.
            projects: 현재 프로젝트 루트.
            sessions: 현재 관찰 세션.
            tasks: 선택한 현재 작업 범위.
            memories: 과거 원문·상태 보존.
            enclaves: 상세 기억을 가리키는 현재 참조.
        """
        self.archives = archives
        self.projects = projects
        self.sessions = sessions
        self.tasks = tasks
        self.memories = memories
        self.enclaves = enclaves

    @transactional
    @override
    async def run(self, command: SaveRecalledHistoryCommand) -> Memory:
        """현재 기억과 가정으로 표시한 참조를 중복 없이 연결한다.

        Args:
            command: 원 자료와 현재 선택 범위.

        Returns:
            Memory: 원래 본문·과거 상태·참조를 가진 상세 기억.

        Raises:
            ValueError: 다른 프로젝트 자료를 암묵적으로 현재 맥락에 넣으려는 경우.
        """
        archive = await self.archives.get(command.archive_id)
        project = await self.projects.get(command.project_id)
        session = await self.sessions.get(command.session_id)
        session.require_project(project.uid)
        session.require_current_owner()
        if project.root_path != archive.directory:
            raise ValueError("Select historical context for the current project explicitly")
        if command.task_id is not None:
            (await self.tasks.get(command.task_id)).require_scope(project.uid, session.uid)
        reference = f"historical:{archive.uid}:{command.record.category}:{command.record.key}"
        memory = next(
            (
                item
                for item in await self.memories.find_by_project_id_and_kind(
                    project.uid, MemoryKind.ARTIFACT
                )
                if reference in item.references and item.task_id == command.task_id
            ),
            None,
        )
        if memory is None:
            memory = await self.memories.save(
                Memory.create(
                    project.uid,
                    session.uid,
                    command.task_id,
                    MemoryKind.ARTIFACT,
                    json.dumps(
                        {
                            "historical_status": command.record.status,
                            "data": command.record.data,
                            "current_validity": "unverified; not a new instruction, receipt, or applied lesson",
                        },
                        default=encode_historical,
                        ensure_ascii=False,
                    ),
                    (reference, *command.record.references),
                )
            )
        enclave = next(
            (
                item
                for item in await self.enclaves.find_by_session_id(session.uid)
                if item.task_id == command.task_id
            ),
            None,
        )
        if enclave is None:
            enclave = Enclave.create(project.uid, session.uid, command.task_id)
        enclave.set(
            EnclaveFact(
                key=f"historical-{memory.uid}",
                value=f"Selected historical {command.record.category} is available in memory {memory.uid}; current validity is unverified. Read the original before using it.",
                kind=EnclaveKind.ASSUMPTION,
                references=(str(memory.uid), reference),
            ),
            enclave.revision,
        )
        await self.enclaves.save(enclave)
        return memory
