"""기존 Graphify의 보존 검증을 포함한 갱신를 DB 잠금 없이 실행한다."""

import asyncio
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.graph import IGraphService


@dataclass(frozen=True)
class UpdateGraphCommand(AbstractCommand):
    """Graphify 작업의 프로젝트 경로을 지정한다.

    Attributes:
        directory: 기존 그래프의 프로젝트 경로.
    """

    directory: str


@UseCase()
class UpdateGraphUseCase(IAsyncCommandUseCase[UpdateGraphCommand, str]):
    """전문 그래프 도구의 작업을 실행하고 검증된 결과만 호출자에게 반환한다."""

    def __init__(self, graph: IGraphService) -> None:
        """기존 그래프 도구의 실행 계약을 받는다.

        Args:
            graph: 외부 조회·갱신·문서 관계 보존 검사.
        """
        self.graph = graph

    @override
    async def run(self, command: UpdateGraphCommand) -> str:
        """Graphify 작업이 끝날 때까지 기다리며 실패를 성공으로 바꾸지 않는다.

        Args:
            command: 프로젝트 경로.

        Returns:
            str: 도구의 조회 결과 또는 검증된 그래프 참조.
        """
        return await asyncio.to_thread(self.graph.update, command.directory)
