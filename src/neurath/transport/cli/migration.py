"""원본 관찰·보존·선택 조회·현재 작업 재개를 기능별로 연결한다."""

import json
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.fence_historical_store import (
    FenceHistoricalStoreCommand,
    FenceHistoricalStoreUseCase,
)
from neurath.application.usecases.inspect_historical_store import (
    InspectHistoricalStoreQuery,
    InspectHistoricalStoreUseCase,
)
from neurath.application.usecases.prepare_historical_archive import (
    PrepareHistoricalArchiveCommand,
    PrepareHistoricalArchiveUseCase,
)
from neurath.application.usecases.read_historical_records import (
    ReadHistoricalRecordsQuery,
    ReadHistoricalRecordsUseCase,
)
from neurath.application.usecases.recall_historical_record import (
    RecallHistoricalRecordCommand,
    RecallHistoricalRecordUseCase,
)
from neurath.application.usecases.recover_historical_store import (
    RecoverHistoricalStoreCommand,
    RecoverHistoricalStoreUseCase,
)
from neurath.application.usecases.replay_transition_events import (
    ReplayTransitionEventsCommand,
    ReplayTransitionEventsUseCase,
)
from neurath.application.usecases.resume_historical_work import (
    ResumeHistoricalWorkCommand,
    ResumeHistoricalWorkUseCase,
)
from neurath.serialization import encode_historical, encode_uuid


@CliController("migration")
class MigrationCliController:
    """과거 자료를 현재 신원·임대로 자동 승격하지 않는 이전 CLI다."""

    def __init__(
        self,
        inspect_store: InspectHistoricalStoreUseCase,
        prepare: PrepareHistoricalArchiveUseCase,
        read: ReadHistoricalRecordsUseCase,
        resume: ResumeHistoricalWorkUseCase,
        recover: RecoverHistoricalStoreUseCase,
        fence: FenceHistoricalStoreUseCase,
        replay: ReplayTransitionEventsUseCase,
        recall: RecallHistoricalRecordUseCase,
        connection: AsyncConnectionManager,
    ) -> None:
        """기존 작업 경로와 외부 원본 처리를 분리한 유스케이스를 받는다.

        Args:
            inspect_store: 원본 읽기 관찰.
            prepare: 사본 보존 후 등록.
            read: 기능별 과거 자료 조회.
            resume: 실제 현재 세션의 선택 재개.
            recover: 새 기록을 포함한 호환 복구 사본.
            fence: 실제 SQLite 원 접속 경로 퇴역.
            replay: 보존한 사건의 순서 있는 코어 반영.
            recall: 선택한 과거 자료의 현재 기억 연결.
            connection: 명령 이벤트 루프의 연결 정리.
        """
        self.inspect_store = inspect_store
        self.prepare = prepare
        self.read = read
        self.resume = resume
        self.recover = recover
        self.fence = fence
        self.replay = replay
        self.recall = recall
        self.connection = connection

    @command("inspect")
    async def inspect(self, source: Annotated[str, Option("--source")]) -> None:
        """원본을 변경하지 않고 형식·전체 행 수·WAL 유무를 읽는다.

        Args:
            source: 관찰할 원본 SQLite.
        """
        echo(
            json.dumps(
                asdict(await self.inspect_store.run(InspectHistoricalStoreQuery(source=source))),
                ensure_ascii=False,
            )
        )

    @command("prepare")
    async def prepare_archive(
        self,
        source: Annotated[str, Option("--source")],
        directory: Annotated[str, Option("--directory")],
        archive_directory: Annotated[str, Option("--archive-directory")],
        config: list[str] | None = None,
    ) -> None:
        """원본/WAL·설정과 일관된 사본을 보존하고 현재 저장소에 위치를 등록한다.

        Args:
            source: 복제할 원본 SQLite.
            directory: 명시한 대상 프로젝트.
            archive_directory: 사본 보관 폴더.
            config: 함께 보존할 설정 파일 목록.
        """
        try:
            result = await self.prepare.run(
                PrepareHistoricalArchiveCommand(
                    source=source,
                    directory=directory,
                    archive_directory=archive_directory,
                    configs=() if config is None else config,
                )
            )
            echo(
                json.dumps(
                    {
                        "id": result.uid,
                        "format": result.format,
                        "tables": result.tables,
                        "snapshot": result.snapshot_path,
                        "source_modified_by_migration": False,
                        "activated": False,
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()

    @command("read")
    async def read_archive(
        self,
        archive_id: Annotated[UUID, Option("--archive-id")],
        section: str = "tasks",
        offset: Annotated[int, Option(min=0)] = 0,
        limit: Annotated[int, Option(min=1, max=100)] = 20,
    ) -> None:
        """원문·미완료·절차·사실·메시지·학습·미인식 자료를 선택해 읽는다.

        Args:
            archive_id: 등록된 사본.
            section: 읽을 기능 영역.
            offset: 이전 페이지의 다음 위치.
            limit: 최대 출력 항목 수.
        """
        try:
            result = await self.read.run(
                ReadHistoricalRecordsQuery(
                    archive_id=archive_id, category=section, offset=offset, limit=limit
                )
            )
            echo(json.dumps(asdict(result), default=encode_historical, ensure_ascii=False))
        finally:
            await self.connection.dispose()

    @command("resume")
    async def resume_work(
        self,
        archive_id: Annotated[UUID, Option("--archive-id")],
        key: Annotated[str, Option("--key")],
        workflow_key: str | None = None,
    ) -> None:
        """선택한 과거 미완료 작업을 현재 관찰된 세션의 같은 원장으로 이어간다.

        Args:
            archive_id: 등록된 사본.
            key: 원문·상태를 확인한 원 작업.
            workflow_key: 함께 이어갈 과거 절차 식별자.
        """
        try:
            result = await self.resume.run(
                ResumeHistoricalWorkCommand(
                    archive_id=archive_id, key=key, workflow_key=workflow_key
                )
            )
            echo(
                json.dumps(
                    {
                        "task_id": result.uid,
                        "status": result.status,
                        "owner_session_id": result.owner_session_id,
                        "source_id": result.definition.source_id,
                    },
                    default=encode_uuid,
                )
            )
        finally:
            await self.connection.dispose()

    @command("recover")
    async def recover_store(
        self,
        source: Annotated[str, Option("--source")],
        destination: Annotated[str, Option("--destination")],
    ) -> None:
        """새 코어 기록을 유지한 호환 복구 사본을 만들고 구버전 rollback은 수행하지 않는다.

        Args:
            source: 새 기록을 포함한 현재 코어 파일.
            destination: 아직 없는 복구 파일 경로.
        """
        result = await self.recover.run(
            RecoverHistoricalStoreCommand(source=source, destination=destination)
        )
        echo(
            json.dumps(
                {
                    "recovery": result.path,
                    "digest": result.digest,
                    "tables": result.inspection.tables,
                    "activated": False,
                    "legacy_rollback": False,
                },
                ensure_ascii=False,
            )
        )

    @command("fence")
    async def fence_store(
        self,
        source: Annotated[str, Option("--source")],
        archive_directory: Annotated[str, Option("--archive-directory")],
    ) -> None:
        """실제 연결 정지와 SQLite 잠금 뒤 원 경로를 퇴역하고 새 기록·사건을 보존한다.

        Args:
            source: 전환 또는 무손실 복구를 위해 멈출 실제 SQLite 경로.
            archive_directory: 원본/WAL 일관된 사본 보관 위치.
        """
        result = await self.fence.run(
            FenceHistoricalStoreCommand(source=source, archive_directory=archive_directory)
        )
        echo(
            json.dumps(
                {**asdict(result), "activated": False, "legacy_rollback": False}, ensure_ascii=False
            )
        )

    @command("replay")
    async def replay_events(self, directory: Annotated[str, Option("--directory")]) -> None:
        """현재 호환 코어에 전환 사건을 원 순서로 한 번씩 반영한다.

        Args:
            directory: 원 접속 경로가 가리키는 실제 전환 폴더.
        """
        try:
            result = await self.replay.run(ReplayTransitionEventsCommand(directory=directory))
            echo(json.dumps(asdict(result)))
        finally:
            await self.connection.dispose()

    @command("recall")
    async def recall_record(
        self,
        archive_id: Annotated[UUID, Option("--archive-id")],
        section: Annotated[str, Option("--section")],
        key: Annotated[str, Option("--key")],
        task_id: UUID | None = None,
    ) -> None:
        """선택한 과거 맥락·협업·학습 자료를 현재 기억과 미검증 참조로 연결한다.

        Args:
            archive_id: 보존 사본.
            section: 과거 기능 영역.
            key: 해당 자료 식별자.
            task_id: 연결할 현재 작업 또는 None.
        """
        try:
            result = await self.recall.run(
                RecallHistoricalRecordCommand(
                    archive_id=archive_id, category=section, key=key, task_id=task_id
                )
            )
            echo(
                json.dumps(
                    {
                        "memory_id": result.uid,
                        "kind": result.kind,
                        "current_validity": "unverified",
                        "references": result.references,
                    },
                    default=encode_uuid,
                )
            )
        finally:
            await self.connection.dispose()
