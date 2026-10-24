"""평가의 관련 요구와 전체 원장·원문을 동일 읽기 범위에서 구성하는 계약이다."""

from abc import ABC, abstractmethod

from spakky.core.common.mutability import immutable

from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.values.workflow_definition import PhaseDefinition


@immutable
class EvaluationContext:
    """평가 대조에 사용할 지문과 검토자에게 전달할 실제 맥락이다.

    Attributes:
        candidate: 관련 요구·대상·자료만으로 만든 안정적인 지문.
        scope: 원문·정정·전체 TODO·산출물·검증 자료를 포함한 메시지.
        requirements: 외부 관찰 전에 읽은 요구·단계 정의 지문.
    """

    candidate: str
    scope: str
    requirements: str = ""


class IEvaluationContextService(ABC):
    """호출 유스케이스의 읽기 범위에서 평가 자료를 구성하며 저장·실행하지 않는다."""

    @abstractmethod
    async def load(self, run: WorkflowRun, phase: PhaseDefinition) -> EvaluationContext:
        """현재 관련 요구와 전체 원장을 읽어 독립 평가의 입력을 구성한다.

        Args:
            run: 작업 묶음을 소유한 실행.
            phase: 평가할 후보와 관련 작업 범위.

        Returns:
            EvaluationContext: 비교용 내용 지문과 실제 전달할 원문.

        Raises:
            NotImplementedError: 저장 어댑터가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError
