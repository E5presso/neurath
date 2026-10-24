"""업무 DB가 열리지 않아도 각 진단의 실패·부재를 구분하는 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from spakky.core.common.mutability import immutable


@immutable
class DiagnosticFinding:
    """관찰 항목과 실제 확인 상태를 표현한다.

    Attributes:
        area: 설정·무결성·스키마·프로젝트·재개 진단 항목.
        status: ok·missing·failed·unknown 중 실제 관찰 상태.
        detail: 재현 가능한 원인과 다음 조치이며 성공을 추정하지 않는다.
    """

    area: str
    status: str
    detail: str


class IDiagnosticsService(ABC):
    """설정과 원장을 덮어쓰지 않는 운영 진단 포트다."""

    @abstractmethod
    async def inspect(
        self, database: str | None, directory: str | None, provider: str, host_session_id: str
    ) -> Sequence[DiagnosticFinding]:
        """독립적으로 확인할 항목을 읽기 전용으로 관찰한다.

        Args:
            database: 명시한 DB 경로 또는 현재 설정의 None.
            directory: 프로젝트 연결을 관찰할 폴더 또는 None.
            provider: 재개 경계를 조회할 호스트 공급자.
            host_session_id: 조회할 실제 호스트 세션 ID.

        Returns:
            Sequence[DiagnosticFinding]: 실패·자료 부재도 항목별로 반환한 진단.

        Raises:
            NotImplementedError: 구현체가 추상 계약에 잘못 위임한 경우.
        """
        raise NotImplementedError
