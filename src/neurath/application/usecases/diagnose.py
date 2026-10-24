"""업무 저장소의 준비 여부와 무관하게 읽기 전용 진단을 실행한다."""

from collections.abc import Sequence
from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.services.diagnostics import DiagnosticFinding, IDiagnosticsService


@immutable
class DiagnoseQuery(AbstractQuery):
    """진단할 파일·폴더·호스트 주소를 선택한다.

    Attributes:
        database: 진단할 파일 경로이며 None이면 현재 설정을 읽는다.
        directory: 프로젝트 연결을 관찰할 실제 작업 폴더.
        provider: 재개 상태를 선택할 실제 호스트 공급자.
        host_session_id: 조회할 네이티브 세션 주소.
    """

    database: str | None = None
    directory: str | None = None
    provider: str = ""
    host_session_id: str = ""


@UseCase()
class DiagnoseUseCase(IAsyncQueryUseCase[DiagnoseQuery, Sequence[DiagnosticFinding]]):
    """업무 트랜잭션을 열거나 스키마를 이전하지 않고 각 경계를 관찰한다."""

    def __init__(self, diagnostics: IDiagnosticsService) -> None:
        """DB 장애에도 독립적으로 관찰할 진단 계약을 받는다.

        Args:
            diagnostics: 설정·저장 파일·프로젝트·재개 경계의 관찰.
        """
        self.diagnostics = diagnostics

    @override
    async def run(self, query: DiagnoseQuery) -> Sequence[DiagnosticFinding]:
        """자료 부재와 실패를 포함한 관찰 결과를 반환한다.

        Args:
            query: 읽기 전용 진단 대상.

        Returns:
            Sequence[DiagnosticFinding]: 항목별 실제 관찰 상태.
        """
        return await self.diagnostics.inspect(
            query.database, query.directory, query.provider, query.host_session_id
        )
