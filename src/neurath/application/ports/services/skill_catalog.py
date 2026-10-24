"""설치 지침과 실행 정의가 같은 스킬 계약을 읽게 한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from spakky.core.common.mutability import immutable

from neurath.domain.values.workflow_definition import WorkflowDefinition


@immutable
class SkillDescription:
    """선택 조건·결과와 실제 runner 정의를 함께 제공한다.

    Attributes:
        purpose: 스킬이 해결하는 일.
        use_when: 선택할 요청 조건.
        exclude: 선택하지 않을 요청 조건.
        required_inputs: 기존 요청과 자료에서 확인할 입력.
        outcomes: 최종 결과 기준.
        branches: 해당 상황에서만 적용할 분기.
        workflow: 설치 본문과 같은 단계·검사 정의.
    """

    purpose: str
    use_when: str
    exclude: str
    required_inputs: Sequence[str]
    outcomes: Sequence[str]
    branches: Sequence[str]
    workflow: WorkflowDefinition


class ISkillCatalogService(ABC):
    """배포 스킬과 명시적으로 선택한 전문 절차를 읽는다."""

    @abstractmethod
    def list(self, directory: str) -> Sequence[SkillDescription]:
        """기본 스킬의 선택 지침과 단계 정의를 읽는다.

        Args:
            directory: 단계가 수행될 실제 폴더.

        Returns:
            Sequence[SkillDescription]: 같은 배포본의 설치·실행 계약.

        Raises:
            NotImplementedError: 구현하지 않은 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def load(self, skill: str, directory: str, definition: str | None = None) -> WorkflowDefinition:
        """선택한 기본 스킬 또는 전달한 전문 절차를 고정한다.

        Args:
            skill: 에이전트가 선택한 스킬 이름.
            directory: 실제 작업 폴더.
            definition: 명시적 전문 절차 JSON 또는 기본 스킬을 고를 None.

        Returns:
            WorkflowDefinition: 호스트 수행 단계와 실제 결과 조건.

        Raises:
            NotImplementedError: 구현하지 않은 포트를 직접 호출한 경우.
        """
        raise NotImplementedError
