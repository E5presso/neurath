"""재실행할 수 없는 결과 불명을 호출 환경에 알린다."""

from abc import ABC, abstractmethod


class IWorkflowNotifierService(ABC):
    """재실행할 수 없는 결과 불명을 호출 환경에 알린다."""

    @abstractmethod
    def waiting(self, request_id: str, reason: str) -> None:
        """같은 결과 불명으로 실행자를 반복 호출하지 않고 대기 이유를 전달한다.

        Args:
            request_id: 결과 확인이 필요한 시도 ID.
            reason: 결과 불명과 필요한 관찰의 설명.

        Raises:
            NotImplementedError: 알림 전달이 구현되지 않은 경우.
        """
        raise NotImplementedError
