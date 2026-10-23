"""기존 Graphify 도구의 조회·갱신을 연결하는 기술 독립 계약이다."""

from abc import ABC, abstractmethod


class IGraphService(ABC):
    """그래프 엔진을 복제하지 않고 외부 도구의 결과와 관계 보존을 확인한다."""

    @abstractmethod
    def query(self, directory: str, question: str) -> str:
        """관련 코드·문서 관계를 조회한다.

        Args:
            directory: 기존 그래프가 있는 프로젝트 경로.
            question: 관계 검색어.

        Returns:
            str: 기존 도구가 반환한 조회 결과.

        Raises:
            NotImplementedError: 추상 계약 본문을 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def update(self, directory: str) -> str:
        """문서 관계를 보존하는 경우에만 갱신 결과를 반환한다.

        Args:
            directory: 기존 그래프가 있는 프로젝트 경로.

        Returns:
            str: 검증된 그래프 파일과 해시 참조.

        Raises:
            NotImplementedError: 추상 계약 본문을 호출한 경우.
        """
        raise NotImplementedError
