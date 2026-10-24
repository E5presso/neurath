"""파일 시스템과 Git을 읽기 전용으로 관찰하는 포트다."""

from abc import ABC, abstractmethod

from neurath.domain.values.directory_observation import DirectoryObservation


class IDirectoryObserverService(ABC):
    """프로젝트를 선택하거나 연결하지 않고 외부의 원시 사실을 관찰한다."""

    @abstractmethod
    def observe(self, working_directory: str) -> DirectoryObservation:
        """정규 디렉터리와 선택적 Git 메타데이터를 읽는다.

        Args:
            working_directory: 사용자가 선택한 조사 대상 기존 디렉터리.

        Returns:
            DirectoryObservation: 정규 디렉터리·Git 공통 디렉터리·기본 작업 트리 관찰 사실.

        Raises:
            NotImplementedError: 구현 없이 추상 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def workspace(self, working_directory: str) -> str:
        """공유 작성 충돌을 대조할 현재 Git 작업 트리 또는 일반 폴더를 조회한다.

        Args:
            working_directory: 호스트에서 관찰한 실제 작업 디렉터리.

        Returns:
            str: 현재 작업 트리의 정규 루트 또는 Git이 없는 작업 폴더.

        Raises:
            NotImplementedError: 구체 서비스가 작성 범위 조회를 구현하지 않은 경우.
        """
        raise NotImplementedError
