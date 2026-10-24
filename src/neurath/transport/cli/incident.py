"""원 증상과 해결 근거를 보존하는 장애 관리 CLI를 제공한다."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Exit, Option, echo

from neurath.application.usecases.diagnose import DiagnoseQuery
from neurath.application.usecases.escalate_incident import (
    EscalateIncidentCommand,
    EscalateIncidentUseCase,
)
from neurath.application.usecases.get_incident import GetIncidentQuery, GetIncidentUseCase
from neurath.application.usecases.open_incident import OpenIncidentCommand, OpenIncidentUseCase
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
from neurath.domain.values.incident_evidence import IncidentEvidence
from neurath.serialization import encode_uuid


@CliController("incident")
class IncidentCliController:
    """장애 상태와 원래 작업의 완료·성공을 분리하는 명령 경계다."""

    def __init__(
        self,
        open_incident: OpenIncidentUseCase,
        get_incident: GetIncidentUseCase,
        record_incident_evidence: RecordIncidentEvidenceUseCase,
        escalate_incident: EscalateIncidentUseCase,
        supersede_incident: SupersedeIncidentUseCase,
        resolve_incident: ResolveIncidentUseCase,
        refresh_incident: RefreshIncidentUseCase,
        recovery: RecordRecoveryFailureUseCase,
        connection: AsyncConnectionManager,
    ) -> None:
        """장애 작업 단위와 실패 시 독립 복구 경로를 받는다.

        Args:
            open_incident: OpenIncident 작업 단위.
            get_incident: GetIncident 작업 단위.
            record_incident_evidence: RecordIncidentEvidence 작업 단위.
            escalate_incident: EscalateIncident 작업 단위.
            supersede_incident: SupersedeIncident 작업 단위.
            resolve_incident: ResolveIncident 작업 단위.
            refresh_incident: RefreshIncident 작업 단위.
            recovery: 코어 저장 실패의 독립 기록.
            connection: 명령 이벤트 루프에서 정리할 연결.
        """
        self.open_incident = open_incident
        self.get_incident = get_incident
        self.record_incident_evidence = record_incident_evidence
        self.escalate_incident = escalate_incident
        self.supersede_incident = supersede_incident
        self.resolve_incident = resolve_incident
        self.refresh_incident = refresh_incident
        self.recovery = recovery
        self.connection = connection

    @asynccontextmanager
    async def _request(self) -> AsyncIterator[None]:
        """실패 원인을 별도 경로에 남기고 연결을 같은 루프에서 정리한다.

        Yields:
            None: 명령 실행과 출력의 수명 범위.

        Raises:
            Exit: 명령 또는 출력이 실패한 경우.
        """
        try:
            yield
        except Exception as error:
            receipt = await self.recovery.run(
                RecordRecoveryFailureCommand(
                    detail=f"{type(error).__name__}: {error}", reference="incident-cli"
                )
            )
            echo(
                json.dumps({"error": str(error), "recovery": asdict(receipt)}, ensure_ascii=False),
                err=True,
            )
            raise Exit(1) from error
        finally:
            await self.connection.dispose()

    @staticmethod
    def _output(incident: Incident) -> None:
        """원 증상·이관·대체·근거와 실제 해결 여부를 명시적으로 출력한다.

        Args:
            incident: 실제로 저장되거나 조회된 장애.
        """
        echo(
            json.dumps(
                {
                    "id": incident.uid,
                    "project_id": incident.project_id,
                    "revision": incident.revision,
                    "status": incident.status,
                    "symptom": incident.symptom,
                    "references": incident.references,
                    "evidence": [asdict(item) for item in incident.evidence],
                    "transfers": incident.transfers,
                    "replacement_id": incident.replacement_id,
                    "resolution": incident.resolution,
                },
                default=encode_uuid,
                ensure_ascii=False,
            )
        )

    @command("open")
    async def create(
        self,
        symptom: Annotated[str, Option("--symptom")],
        references: Annotated[list[str], Option("--reference")],
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
    ) -> None:
        """근거가 있는 최초 증상을 미해결 장애로 등록한다.

        Args:
            symptom: 원래 증상 본문.
            references: 실제 근거의 참조 목록.
            project_id: 관련 프로젝트 또는 전역 장애의 None.
        """
        async with self._request():
            self._output(
                await self.open_incident.run(
                    OpenIncidentCommand(
                        symptom=symptom, references=references, project_id=project_id
                    )
                )
            )

    @command("show")
    async def show(self, incident_id: Annotated[UUID, Option("--incident-id")]) -> None:
        """장애 이력과 정확한 현재 개정을 변경 없이 읽는다.

        Args:
            incident_id: 조회할 장애 식별자.
        """
        async with self._request():
            self._output(await self.get_incident.run(GetIncidentQuery(incident_id=incident_id)))

    @command("record")
    async def record(
        self,
        incident_id: Annotated[UUID, Option("--incident-id")],
        revision: Annotated[int, Option("--revision")],
        kind: Annotated[IncidentEvidenceKind, Option("--kind")],
        detail: Annotated[str, Option("--detail")],
        references: Annotated[list[str], Option("--reference")],
        passed: Annotated[bool | None, Option("--passed/--failed")] = None,
    ) -> None:
        """재현·수정·회귀의 실제 근거를 추가하고 실패한 시험도 보존한다.

        Args:
            incident_id: 원래 장애.
            revision: 조회한 현재 개정.
            kind: 근거의 종류.
            detail: 실제 수행과 결과.
            references: 원문·결과 참조.
            passed: 회귀 시험만 명시해야 하는 성공 또는 실패.
        """
        async with self._request():
            self._output(
                await self.record_incident_evidence.run(
                    RecordIncidentEvidenceCommand(
                        incident_id=incident_id,
                        revision=revision,
                        evidence=IncidentEvidence(
                            kind=kind, detail=detail, references=references, passed=passed
                        ),
                    )
                )
            )

    @command("escalate")
    async def escalate(
        self,
        incident_id: Annotated[UUID, Option("--incident-id")],
        revision: Annotated[int, Option("--revision")],
        destination: Annotated[str, Option("--destination")],
    ) -> None:
        """미해결 장애의 이관 대상과 사유를 남긴다.

        Args:
            incident_id: 변경할 원래 장애.
            revision: 조회한 현재 개정.
            destination: 이번 요청의 근거 또는 연결 대상.
        """
        async with self._request():
            self._output(
                await self.escalate_incident.run(
                    EscalateIncidentCommand(
                        incident_id=incident_id, revision=revision, destination=destination
                    )
                )
            )

    @command("supersede")
    async def supersede(
        self,
        incident_id: Annotated[UUID, Option("--incident-id")],
        revision: Annotated[int, Option("--revision")],
        replacement_id: Annotated[UUID, Option("--replacement-id")],
    ) -> None:
        """원래 장애를 실제 대체 사건에 연결한다.

        Args:
            incident_id: 변경할 원래 장애.
            revision: 조회한 현재 개정.
            replacement_id: 이번 요청의 근거 또는 연결 대상.
        """
        async with self._request():
            self._output(
                await self.supersede_incident.run(
                    SupersedeIncidentCommand(
                        incident_id=incident_id, revision=revision, replacement_id=replacement_id
                    )
                )
            )

    @command("resolve")
    async def resolve(
        self,
        incident_id: Annotated[UUID, Option("--incident-id")],
        revision: Annotated[int, Option("--revision")],
        explanation: Annotated[str, Option("--explanation")],
    ) -> None:
        """최신 재현·수정·회귀 근거로 장애 해결을 요청한다.

        Args:
            incident_id: 변경할 원래 장애.
            revision: 조회한 현재 개정.
            explanation: 이번 요청의 근거 또는 연결 대상.
        """
        async with self._request():
            self._output(
                await self.resolve_incident.run(
                    ResolveIncidentCommand(
                        incident_id=incident_id, revision=revision, explanation=explanation
                    )
                )
            )

    @command("refresh")
    async def refresh(
        self,
        incident_id: Annotated[UUID, Option("--incident-id")],
        revision: Annotated[int, Option("--revision")],
        database: Annotated[str | None, Option("--database")] = None,
        directory: Annotated[str | None, Option("--directory")] = None,
        provider: Annotated[str, Option("--provider")] = "",
        host_session_id: Annotated[str, Option("--host-session-id")] = "",
    ) -> None:
        """실제 진단을 다시 수행해 새 관찰을 추가하며 사건을 해결하지 않는다.

        Args:
            incident_id: 재관찰할 장애.
            revision: 조회한 현재 개정.
            database: 실제 진단할 파일 또는 현재 설정.
            directory: 실제 폴더.
            provider: 호스트 공급자.
            host_session_id: 실제 세션 주소.
        """
        async with self._request():
            self._output(
                await self.refresh_incident.run(
                    RefreshIncidentCommand(
                        incident_id=incident_id,
                        revision=revision,
                        query=DiagnoseQuery(
                            database=database,
                            directory=directory,
                            provider=provider,
                            host_session_id=host_session_id,
                        ),
                    )
                )
            )
