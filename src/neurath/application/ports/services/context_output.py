"""호스트 출력 한도를 넘는 복원 내용을 손실 없이 보존하는 계약이다."""

from abc import ABC, abstractmethod


class IContextOutputService(ABC):
    """현재 맥락의 원문을 보존하고 호스트가 읽을 수 있는 경로를 반환한다."""

    @abstractmethod
    def preserve(self, content: str) -> str:
        """복원할 전체 내용을 저장해 다음 호스트 도구 읽기에 연결한다.

        Args:
            content: 잘라내지 않은 현재 복원 내용.

        Returns:
            str: 호스트에서 실제 읽을 수 있는 로컬 파일 경로.

        Raises:
            NotImplementedError: 추상 계약을 직접 호출한 경우.
        """
        raise NotImplementedError
