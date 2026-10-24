"""업무 DB 요청이 실패해도 사용할 수 있는 읽기 진단·복구 기록 명령이다."""

import json
from dataclasses import asdict
from typing import Annotated

from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Exit, Option, echo

from neurath.application.usecases.diagnose import DiagnoseQuery, DiagnoseUseCase
from neurath.application.usecases.initialize_store import (
    InitializeStoreCommand,
    InitializeStoreUseCase,
)
from neurath.application.usecases.install_host import InstallHostCommand, InstallHostUseCase
from neurath.application.usecases.record_recovery_failure import (
    RecordRecoveryFailureCommand,
    RecordRecoveryFailureUseCase,
)
from neurath.domain.enums.provider_kind import ProviderKind


@CliController("maintenance")
class MaintenanceCliController:
    """진단은 설정·원장을 바꾸지 않고 복구 기록은 코어 DB와 독립적으로 남긴다."""

    def __init__(
        self,
        diagnose: DiagnoseUseCase,
        recovery: RecordRecoveryFailureUseCase,
        install: InstallHostUseCase,
        initialize: InitializeStoreUseCase,
    ) -> None:
        """업무용 DB 연결을 열지 않는 유스케이스를 받는다.

        Args:
            diagnose: 읽기 전용 관찰.
            recovery: 저장소와 알림이 고장나도 시도할 기록.
            install: 보존형 호스트 설정 적용.
            initialize: 명시적 DB 초기화·이전.
        """
        self.diagnose = diagnose
        self.recovery = recovery
        self.install = install
        self.initialize = initialize

    @command("diagnose")
    async def inspect(
        self,
        database: Annotated[str | None, Option("--database")] = None,
        directory: Annotated[str | None, Option("--directory")] = None,
        provider: Annotated[str, Option("--provider")] = "",
        host_session_id: Annotated[str, Option("--host-session-id")] = "",
    ) -> None:
        """무결성·설정·프로젝트·재개 경계를 각각 진단한다.

        Args:
            database: 명시한 파일 또는 현재 설정의 None.
            directory: 프로젝트를 관찰할 실제 폴더.
            provider: 재개 경계를 조회할 호스트.
            host_session_id: 실제 호스트 세션 주소.

        Raises:
            Exit: 실패·부재·미확인 항목이 남은 경우.
        """
        findings = await self.diagnose.run(
            DiagnoseQuery(
                database=database,
                directory=directory,
                provider=provider,
                host_session_id=host_session_id,
            )
        )
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
    ) -> None:
        """지정한 실제 호스트의 지침·스킬·훅을 다른 설정과 함께 설치한다.

        Args:
            provider: 설치할 호스트.
            directory: 사용자 홈 또는 프로젝트 루트.
            data_home: 격리 검증용 데이터 홈 또는 사용자 기본 경로.
        """
        result = await self.install.run(
            InstallHostCommand(provider=provider, directory=directory, data_home=data_home)
        )
        echo(json.dumps(asdict(result), ensure_ascii=False))
