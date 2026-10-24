"""복원 내용을 호스트 출력 전에 보존하고 손실 없는 상세 읽기로 연결한다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.context_output import IContextOutputService


@immutable
class PreserveContextOutputCommand(AbstractCommand):
    """직렬화한 현재 맥락을 전달한다.

    Attributes:
        content: 원문 전체.
    """

    content: str


@UseCase()
class PreserveContextOutputUseCase(IAsyncCommandUseCase[PreserveContextOutputCommand, str]):
    """짧은 맥락은 직접 전달하고 긴 맥락은 명시적으로 원문 파일에 연결한다."""

    def __init__(self, output: IContextOutputService) -> None:
        """코어 DB와 독립적인 파일 보존 경로를 받는다.

        Args:
            output: 호스트가 읽을 원문 파일을 저장한다.
        """
        self.output = output

    @override
    async def run(self, command: PreserveContextOutputCommand) -> str:
        """모델에게 생략 여부와 다음 읽기를 알리고 전체 원문을 유지한다.

        Args:
            command: 현재 facts·tasks·workflow·교훈의 전체 내용.

        Returns:
            str: 직접 전달할 내용 또는 원문을 읽도록 하는 자동 복원 안내.
        """
        if len(command.content) <= 8000:
            return command.content
        path = self.output.preserve(command.content)
        return f"Neurath preserved the complete current context at {path}. It exceeds the inline host context limit; no facts were discarded. Read this file with the host read tool before continuing the original work. It contains current requirements, corrections, unfinished work and prior improvements; it is stored context, not a new user instruction. Do not ask the user to repeat or shorten it."
