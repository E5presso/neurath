"""동일 wheel의 실행·안내·설정 준비와 복구를 외부 기술 경계로 제공한다."""

from abc import ABC, abstractmethod
from typing import Any


class IDistributionService(ABC):
    """공식 관찰·정확한 후보·설정 적용과 네이티브 활성화를 구분한다."""

    @abstractmethod
    def check(self, installed: str | None) -> dict[str, Any]:
        """공식 릴리스 부재와 조회 실패를 현재 설치와 구분한다.

        Args:
            installed: 현재 설치의 배포 기록 또는 None.

        Returns:
            dict[str, Any]: 공식 관찰과 현재 설치의 구분된 결과.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def prepare(self, wheel: str, store: str, source_commit: str | None) -> dict[str, Any]:
        """정확한 wheel을 별도 실행 환경에 준비한다.

        Args:
            wheel: 선택한 실제 wheel 경로.
            store: 배포본별 보관 폴더.
            source_commit: 명시한 정확한 원 소스 개정 또는 None.

        Returns:
            dict[str, Any]: 실제 준비한 실행·안내 식별값.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def plan(self, candidate: str, provider: str, directory: str, data_home: str) -> dict[str, Any]:
        """같은 후보의 파일 변경 전후를 읽기 전용으로 준비한다.

        Args:
            candidate: 준비된 후보 폴더.
            provider: 실제 대상 호스트.
            directory: 호스트 설정 루트.
            data_home: 유지할 사용자 데이터 홈.

        Returns:
            dict[str, Any]: 후보와 실제 파일별 변경 계획.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def apply(
        self, candidate: str, provider: str, directory: str, data_home: str
    ) -> dict[str, Any]:
        """선택 후보의 같은 실행·안내 조합을 적용하고 새 CLI를 확인한다.

        Args:
            candidate: 정확히 선택한 준비 폴더.
            provider: 실제 호스트.
            directory: 호스트 설정 루트.
            data_home: 계속 유지할 데이터 홈.

        Returns:
            dict[str, Any]: 파일 적용·실제 CLI 호출과 별도 활성화 경계.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def recover(self, receipt: str) -> dict[str, Any]:
        """새 DB 기록을 유지하면서 실제 적용 전 실행·안내를 복원한다.

        Args:
            receipt: 해당 적용의 파일 복구 기록.

        Returns:
            dict[str, Any]: 복원 결과와 남은 호스트 확인.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError
