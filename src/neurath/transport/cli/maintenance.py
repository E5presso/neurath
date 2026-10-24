"""업무 DB 요청이 실패해도 사용할 수 있는 읽기 진단·복구 기록 명령이다."""

import json
from dataclasses import asdict
from importlib.metadata import version
from typing import Annotated, Any
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Exit, Option, echo

from neurath.application.usecases.diagnose import DiagnoseQuery, DiagnoseUseCase
from neurath.application.usecases.escalate_incident import (
    EscalateIncidentCommand,
    EscalateIncidentUseCase,
)
from neurath.application.usecases.get_incident import GetIncidentQuery, GetIncidentUseCase
from neurath.application.usecases.initialize_store import (
    InitializeStoreCommand,
    InitializeStoreUseCase,
)
from neurath.application.usecases.install_host import InstallHostCommand, InstallHostUseCase
from neurath.application.usecases.list_incidents import ListIncidentsQuery, ListIncidentsUseCase
from neurath.application.usecases.reconcile_recovery_failures import (
    ReconcileRecoveryFailuresCommand,
    ReconcileRecoveryFailuresUseCase,
)
from neurath.application.usecases.record_incident_evidence import (
    RecordIncidentEvidenceCommand,
    RecordIncidentEvidenceUseCase,
)
from neurath.application.usecases.record_recovery_failure import (
    RecordRecoveryFailureCommand,
    RecordRecoveryFailureUseCase,
)
from neurath.application.usecases.refresh_incident import (
    RefreshIncidentCommand,
    RefreshIncidentUseCase,
)
from neurath.application.usecases.resolve_incident import (
    ResolveIncidentCommand,
    ResolveIncidentUseCase,
)
from neurath.application.usecases.supersede_incident import (
    SupersedeIncidentCommand,
    SupersedeIncidentUseCase,
)
from neurath.domain.aggregates.incident import Incident
from neurath.domain.enums.incident_evidence_kind import IncidentEvidenceKind
from neurath.domain.enums.provider_kind import ProviderKind
from neurath.domain.values.incident_evidence import IncidentEvidence
from neurath.serialization import encode_uuid


@CliController("maintenance")
class MaintenanceCliController:
    """일반 진단은 읽기만 하고 명시한 수리·이관을 기존 장애 이력으로 연결한다."""

    def __init__(
        self,
        diagnose: DiagnoseUseCase,
        recovery: RecordRecoveryFailureUseCase,
        install: InstallHostUseCase,
        initialize: InitializeStoreUseCase,
        incidents: ListIncidentsUseCase,
        incident: GetIncidentUseCase,
        reconcile: ReconcileRecoveryFailuresUseCase,
        evidence: RecordIncidentEvidenceUseCase,
        resolve: ResolveIncidentUseCase,
        refresh: RefreshIncidentUseCase,
        escalate: EscalateIncidentUseCase,
        supersede: SupersedeIncidentUseCase,
        connection: AsyncConnectionManager,
    ) -> None:
        """독립 진단·journal과 정상 코어의 장애 처리 경계를 받는다.

        Args:
            diagnose: 읽기 전용 관찰.
            recovery: 저장소와 알림이 고장나도 시도할 기록.
            install: 보존형 호스트 설정 적용.
            initialize: 명시적 DB 초기화·이전.
            incidents: 읽기 전용 장애 목록.
            incident: 원 사건의 상세 조회.
            reconcile: 명시적 복구에서 journal 원문 연결.
            evidence: 실제 재현·수정·회귀 근거 저장.
            resolve: 도메인이 검증하는 해결.
            refresh: 실제 진단 재관찰.
            escalate: 미해결 이관.
            supersede: 대체 사건 연결.
            connection: 요청 이벤트 루프 연결 정리.
        """
        self.diagnose = diagnose
        self.recovery = recovery
        self.install = install
        self.initialize = initialize
        self.incidents = incidents
        self.incident = incident
        self.reconcile = reconcile
        self.evidence = evidence
        self.resolve = resolve
        self.refresh = refresh
        self.escalate = escalate
        self.supersede = supersede
        self.connection = connection

    @command("version")
    async def show_version(self) -> None:
        """DB를 열지 않고 현재 호출된 배포본의 설치 버전을 반환한다."""
        echo(json.dumps({"name": "neurath", "version": version("neurath")}))

    @command("diagnose")
    async def inspect(
        self,
        database: Annotated[str | None, Option("--database")] = None,
        directory: Annotated[str | None, Option("--directory")] = None,
        provider: Annotated[str, Option("--provider")] = "",
        host_session_id: Annotated[str, Option("--host-session-id")] = "",
        incident_id: UUID | None = None,
    ) -> None:
        """무결성·설정·프로젝트·재개 경계를 각각 진단한다.

        Args:
            database: 명시한 파일 또는 현재 설정의 None.
            directory: 프로젝트를 관찰할 실제 폴더.
            provider: 재개 경계를 조회할 호스트.
            host_session_id: 실제 호스트 세션 주소.
            incident_id: 명시하면 원 장애에 이번 실제 재관찰을 추가한다.

        Raises:
            Exit: 실패·부재·미확인 항목이 남은 경우.
        """
        query = DiagnoseQuery(
            database=database,
            directory=directory,
            provider=provider,
            host_session_id=host_session_id,
        )
        if incident_id is not None:
            try:
                current = await self.incident.run(GetIncidentQuery(incident_id=incident_id))
                result = await self.refresh.run(
                    RefreshIncidentCommand(
                        incident_id=incident_id, revision=current.revision, query=query
                    )
                )
                echo(
                    json.dumps(
                        self._incident_document(result), default=encode_uuid, ensure_ascii=False
                    )
                )
            finally:
                await self.connection.dispose()
            return
        findings = await self.diagnose.run(query)
        echo(json.dumps([asdict(item) for item in findings], ensure_ascii=False))
        if any(item.status != "ok" for item in findings):
            raise Exit(1)

    @command("record-failure")
    async def record_failure(
        self,
        detail: Annotated[str, Option("--detail")],
        reference: Annotated[str, Option("--reference")],
    ) -> None:
        """업무 명령을 실행할 수 없어도 원인과 남은 일을 복구 기록에 남긴다.

        Args:
            detail: 실제 실패 원인과 미완료 내용.
            reference: 원 호출·보고·오류 참조.

        Raises:
            Exit: 독립 복구 파일도 기록할 수 없는 경우.
        """
        result = await self.recovery.run(
            RecordRecoveryFailureCommand(detail=detail, reference=reference)
        )
        echo(json.dumps(asdict(result), ensure_ascii=False))
        if result.record_path is None:
            raise Exit(1)

    @command("initialize")
    async def initialize_store(self, database: str | None = None) -> None:
        """원본을 보존하고 명시적으로 현재 저장소 스키마를 준비한다.

        Args:
            database: 별도로 선택한 저장 파일 또는 사용자 기본 경로.
        """
        result = await self.initialize.run(InitializeStoreCommand(database=database))
        echo(json.dumps({"database": result, "initialized": True}))

    @command("install")
    async def install_host(
        self,
        provider: Annotated[ProviderKind, Option("--provider")],
        directory: Annotated[str, Option("--directory")],
        data_home: str | None = None,
        preview: bool = False,
    ) -> None:
        """지정한 실제 호스트의 지침·스킬·훅을 다른 설정과 함께 설치한다.

        Args:
            provider: 설치할 호스트.
            directory: 사용자 홈 또는 프로젝트 루트.
            data_home: 격리 검증용 데이터 홈 또는 사용자 기본 경로.
            preview: 파일·DB를 바꾸지 않고 변경 대상만 조회할지 여부.
        """
        result = await self.install.run(
            InstallHostCommand(
                provider=provider, directory=directory, data_home=data_home, preview=preview
            )
        )
        echo(json.dumps(asdict(result), ensure_ascii=False))

    @staticmethod
    def _incident_document(incident: Incident) -> dict[str, Any]:
        """원 증상·근거·이관을 해결이나 작업 성공과 구분해 출력한다.

        Args:
            incident: 기존 도메인에서 읽거나 변경한 사건.

        Returns:
            dict[str, Any]: 원문과 현재 상태의 JSON 표현.
        """
        return {
            "id": incident.uid,
            "project_id": incident.project_id,
            "revision": incident.revision,
            "symptom": incident.symptom,
            "references": incident.references,
            "evidence": [asdict(item) for item in incident.evidence],
            "status": incident.status,
            "transfers": incident.transfers,
            "replacement_id": incident.replacement_id,
            "resolution": incident.resolution,
        }

    @command("failures")
    async def list_failures(
        self, after: UUID | None = None, limit: Annotated[int, Option(min=1, max=100)] = 20
    ) -> None:
        """기존 장애를 읽기만 하며 journal 연결은 명시적 repair로 수행한다.

        Args:
            after: 이전 페이지의 마지막 사건 ID.
            limit: 한 번에 조회할 개수.
        """
        try:
            result = await self.incidents.run(ListIncidentsQuery(after_id=after, limit=limit))
            echo(
                json.dumps(
                    {
                        "incidents": [self._incident_document(item) for item in result],
                        "next_after_id": result[-1].uid if len(result) == limit else None,
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()

    @command("failure")
    async def show_failure(self, incident_id: Annotated[UUID, Option("--incident-id")]) -> None:
        """원 장애의 증상·재현·수정·회귀·이관 이력을 변경 없이 읽는다.

        Args:
            incident_id: 조회할 실제 사건.
        """
        try:
            result = await self.incident.run(GetIncidentQuery(incident_id=incident_id))
            echo(
                json.dumps(self._incident_document(result), default=encode_uuid, ensure_ascii=False)
            )
        finally:
            await self.connection.dispose()

    @command("repair")
    async def repair_failure(
        self,
        journal: str | None = None,
        incident_id: UUID | None = None,
        kind: IncidentEvidenceKind | None = None,
        detail: str = "",
        reference: list[str] | None = None,
        passed: Annotated[bool | None, Option("--passed/--failed")] = None,
        resolve: str | None = None,
    ) -> None:
        """journal을 코어에 복원하거나 기존 장애에 실제 수리 근거·해결을 기록한다.

        Args:
            journal: 원문을 다시 입력하지 않고 연결할 journal이며 기본 파일은 None.
            incident_id: 실제 재현·수정·회귀를 보고할 기존 사건.
            kind: 실제로 확인한 근거의 종류.
            detail: 이번 실제 확인 내용.
            reference: 해당 절차·출력·수정의 출처.
            passed: 회귀 시험의 실제 성공 또는 실패.
            resolve: 순서가 맞는 성공 근거 후 해결 설명.

        Raises:
            ValueError: journal 연결과 사건 변경을 혼합하거나 필요한 근거가 없는 경우.
        """
        try:
            if incident_id is None:
                if (
                    kind is not None
                    or detail
                    or reference
                    or passed is not None
                    or resolve is not None
                ):
                    raise ValueError(
                        "Evidence requires an existing incident ID; repair without evidence connects the original journal"
                    )
                result = await self.reconcile.run(ReconcileRecoveryFailuresCommand(journal=journal))
                echo(
                    json.dumps(
                        {
                            "incidents": [self._incident_document(item) for item in result],
                            "journal_preserved": True,
                        },
                        default=encode_uuid,
                        ensure_ascii=False,
                    )
                )
                return
            if journal is not None or kind is None:
                raise ValueError("Select either journal recovery or existing incident evidence")
            item = IncidentEvidence(
                kind=kind,
                detail=detail,
                references=() if reference is None else reference,
                passed=passed,
            )
            current = await self.incident.run(GetIncidentQuery(incident_id=incident_id))
            result = await self.evidence.run(
                RecordIncidentEvidenceCommand(
                    incident_id=incident_id, revision=current.revision, evidence=item
                )
            )
            if resolve is not None:
                result = await self.resolve.run(
                    ResolveIncidentCommand(
                        incident_id=incident_id, revision=result.revision, explanation=resolve
                    )
                )
            echo(
                json.dumps(self._incident_document(result), default=encode_uuid, ensure_ascii=False)
            )
        finally:
            await self.connection.dispose()

    @command("handoff-failure")
    async def handoff_failure(
        self,
        incident_id: Annotated[UUID, Option("--incident-id")],
        destination: str | None = None,
        replacement_id: UUID | None = None,
    ) -> None:
        """미해결 사건을 이관하거나 기존 대체 사건에 연결하고 해결로 기록하지 않는다.

        Args:
            incident_id: 처리 중인 원 사건.
            destination: 이관 대상과 남은 이유.
            replacement_id: 같은 범위의 실제 대체 사건.

        Raises:
            ValueError: 이관 대상과 대체 사건 중 하나를 선택하지 않은 경우.
        """
        try:
            if (destination is None) == (replacement_id is None):
                raise ValueError("Choose one unresolved destination or one replacement incident")
            current = await self.incident.run(GetIncidentQuery(incident_id=incident_id))
            if destination is not None:
                result = await self.escalate.run(
                    EscalateIncidentCommand(
                        incident_id=incident_id, revision=current.revision, destination=destination
                    )
                )
            else:
                assert replacement_id is not None
                result = await self.supersede.run(
                    SupersedeIncidentCommand(
                        incident_id=incident_id,
                        revision=current.revision,
                        replacement_id=replacement_id,
                    )
                )
            echo(
                json.dumps(self._incident_document(result), default=encode_uuid, ensure_ascii=False)
            )
        finally:
            await self.connection.dispose()
