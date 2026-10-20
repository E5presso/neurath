"""선택한 절차의 현재 단계와 과거 정의·시도·결과를 조회한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun


@dataclass(frozen=True)
class GetWorkflowQuery(AbstractQuery):
    """소유 범위 안에서 조회할 run을 지정한다.

    Attributes:
        project_id: run이 속하는 프로젝트 ID.
        session_id: run을 소유한 세션 ID.
        run_id: 조회할 run ID.
    """

    project_id: str
    session_id: str
    run_id: str


@dataclass(frozen=True)
class GetWorkflowResult:
    """소유 범위가 확인된 run. current는 다음 단계이며 모두 끝났으면 None.

    Attributes:
        run: 소유 범위가 확인된 run. current는 다음 단계이며 모두 끝났으면 None.
    """

    run: WorkflowRun


@UseCase(scope=Pod.Scope.CONTEXT)
class GetWorkflowUseCase(IAsyncQueryUseCase[GetWorkflowQuery, GetWorkflowResult]):
    """선택한 절차의 현재 단계와 과거 정의·시도·결과를 조회한다.

    현재 단계뿐 아니라 과거 정의·시도·결과를 함께 반환한다. 조회로 외부 실행을
    제출하거나 태스크·단계 상태를 바꾸지 않는다.
    """

    def __init__(self, workflows: IWorkflowRepository) -> None:
        """태스크와 연결된 절차의 조회·저장 포트를 받는다.

        Args:
            workflows: run의 정의·시도를 조회하고 변경 전체를 저장한다.
        """
        self.workflows = workflows

    @override
    async def run(self, query: GetWorkflowQuery) -> GetWorkflowResult:
        """선택한 절차의 현재 단계와 과거 정의·시도·결과를 조회한다.

        Args:
            query: 조회할 run ID와 해당 run의 프로젝트·소유 세션.

        Returns:
            GetWorkflowResult: 소유 범위가 확인된 run. current는 다음 단계이며 모두 끝났으면 None.
        """
        run = await self.workflows.get(query.run_id)
        run.require_scope(query.project_id, query.session_id)
        return GetWorkflowResult(run=run)
