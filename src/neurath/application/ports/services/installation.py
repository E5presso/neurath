"""호스트 소유 설정을 보존하며 CLI·가이드·스킬·훅을 함께 연결하는 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence

from spakky.core.common.mutability import immutable

from neurath.domain.enums.provider_kind import ProviderKind


@immutable
class InstallationResult:
    """실제 파일 적용과 호스트의 활성화를 구분한 설치 결과다.

    Attributes:
        command: 현재 배포본과 저장소를 사용하는 실행 명령.
        database: 사용자 단위 SQLite 경로.
        changed_files: 실제 갱신한 Neurath 소유 파일/영역.
        backups: 변경 전 보존한 파일과 DB 스냅샷.
        host_action: 호스트가 별도로 요구하는 실제 활성화 안내.
        planned_files: 내부 배포 계획이 요청한 파일 본문이며 일반 적용은 None.
    """

    command: str
    database: str
    changed_files: Sequence[str]
    backups: Sequence[str]
    host_action: str
    planned_files: Mapping[str, str] | None = None


class IInstallationService(ABC):
    """설치와 저장소 초기화를 일반 업무 요청 밖에서 명시적으로 수행한다."""

    @abstractmethod
    async def initialize(self, database: str | None) -> str:
        """원본을 보존한 뒤 명시적으로 현재 스키마를 준비한다.

        Args:
            database: 선택한 파일이며 None이면 사용자 기본 저장소.

        Returns:
            str: 실제 준비한 파일 경로.

        Raises:
            NotImplementedError: 구현하지 않은 계약을 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def install(
        self,
        provider: ProviderKind,
        directory: str,
        data_home: str | None,
        *,
        preview: bool = False,
    ) -> InstallationResult:
        """지정 호스트 설정의 Neurath 소유 영역만 적용한다.

        Args:
            provider: 실제 설치 대상 호스트.
            directory: 사용자 홈 또는 명시한 프로젝트 루트.
            data_home: 격리 검증 등에 명시한 데이터 홈. None이면 사용자 기본 경로.
            preview: 파일·DB를 변경하지 않고 계획만 반환할지 여부.

        Returns:
            InstallationResult: 파일 적용 결과이며 hook trust·활성화 성공은 별도다.

        Raises:
            NotImplementedError: 구현하지 않은 계약을 호출한 경우.
        """
        raise NotImplementedError
