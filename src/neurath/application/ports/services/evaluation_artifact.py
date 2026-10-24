"""평가 후보가 참조하는 실제 파일과 Git 개정의 읽기 전용 관찰 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence


class IEvaluationArtifactService(ABC):
    """원문 참조와 실제 파일·현재 HEAD를 평가 시점마다 대조한다."""

    @abstractmethod
    async def observe(self, directory: str, references: Sequence[str]) -> Sequence[str]:
        """로컬 파일 내용과 현재 Git HEAD의 관찰 지문을 반환한다.

        Args:
            directory: 산출물의 기준 작업 폴더.
            references: 실제 경로 또는 외부 불변 산출물 참조.

        Returns:
            Sequence[str]: 순서가 보존된 실제 관찰과 외부 참조.

        Raises:
            NotImplementedError: 어댑터가 실제 관찰 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError
