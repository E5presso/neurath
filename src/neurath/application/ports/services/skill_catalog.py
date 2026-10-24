"""설치된 스킬의 절차 정의를 현재 작업 폴더에 연결하는 계약이다."""

from abc import ABC, abstractmethod

from neurath.domain.values.workflow_definition import WorkflowDefinition


class ISkillCatalogService(ABC):
    """프롬프트와 동일한 배포본의 단계 정의를 읽는다."""

    @abstractmethod
    def load(self, skill: str, directory: str) -> WorkflowDefinition:
        """선택한 스킬의 에이전트 수행 단계를 읽는다.

        Args:
            skill: 선택한 기본 스킬 이름.
            directory: 실제 작업 폴더.

        Returns:
            WorkflowDefinition: 실행 프로그램을 꾸며 넣지 않은 단계 정의.

        Raises:
            NotImplementedError: 구현하지 않은 포트를 직접 호출한 경우.
        """
        raise NotImplementedError
