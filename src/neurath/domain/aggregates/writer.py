"""공유 작업 폴더의 실제 작성 구간만 소유자와 세대로 배타 관리한다."""

from typing import Self, override
from uuid import uuid4

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.errors import InvalidExecutionState
from neurath.domain.runtime_records import Liveness


@mutable
class Writer(AbstractAggregateRoot[str]):
    """읽기를 막지 않는 작업 폴더별 작성 임대다.

    Attributes:
        resource: 실제 실행 어댑터가 정규화한 공유 작업 폴더.
        execution_id: 현재 작성 실행이며 해제됐으면 None.
        turn_id: 작성이 속한 호스트 턴.
        tool_use_id: 작성이 속한 실제 호스트 도구 호출.
        generation: 매 취득마다 증가하여 오래된 해제를 막는 세대.
        revision: 저장소가 검사하는 낙관적 버전.
    """

    resource: str
    execution_id: str | None
    turn_id: str
    tool_use_id: str
    generation: int
    revision: int

    @classmethod
    @override
    def next_id(cls) -> str:
        """작업 폴더 경로와 구분되는 내부 임대 레코드 ID를 만든다.

        Returns:
            str: 새 UUID 문자열.
        """
        return str(uuid4())

    @classmethod
    def create(cls, resource: str) -> Self:
        """소유자가 없는 작업 폴더 레코드를 만든다.

        Args:
            resource: 정규화된 실제 작업 폴더.

        Returns:
            Self: 세대가 0인 미취득 레코드.
        """
        return cls(
            uid=cls.next_id(),
            resource=resource,
            execution_id=None,
            turn_id="",
            tool_use_id="",
            generation=0,
            revision=1,
        )

    def acquire(self, execution_id: str, turn_id: str, tool_use_id: str) -> int:
        """다른 실제 작성이 없을 때 취득하고 같은 호출 재전달은 같은 세대로 돌려준다.

        Args:
            execution_id: 현재 작성 실행의 내부 ID.
            turn_id: 호스트가 준 턴 식별자.
            tool_use_id: 호스트가 준 도구 호출 식별자.

        Returns:
            int: 취득한 세대.

        Raises:
            InvalidExecutionState: 호출 식별자가 없거나 다른 작성이 남아 있는 경우.
        """
        if not execution_id or not turn_id or not tool_use_id:
            raise InvalidExecutionState("Writer requires an observed execution, turn and call")
        if self.execution_id is not None:
            if (self.execution_id, self.turn_id, self.tool_use_id) == (
                execution_id,
                turn_id,
                tool_use_id,
            ):
                return self.generation
            raise InvalidExecutionState("Another write is still active")
        self.execution_id = execution_id
        self.turn_id = turn_id
        self.tool_use_id = tool_use_id
        self.generation += 1
        return self.generation

    def release(self, execution_id: str, generation: int, liveness: Liveness) -> None:
        """일치하는 소유자·세대의 실제 작성 종료가 확인돼야 임대를 해제한다.

        Args:
            execution_id: 종료를 관찰한 작성 실행.
            generation: 종료를 관찰하기 전에 읽은 작성 세대.
            liveness: 해당 작성 구간의 실제 생존 관찰.

        Raises:
            InvalidExecutionState: 소유자·세대가 바뀌었거나 실제 종료가 확인되지 않은 경우.
        """
        if (self.execution_id, self.generation) != (execution_id, generation):
            raise InvalidExecutionState("Writer owner or generation changed")
        if liveness is not Liveness.STOPPED:
            raise InvalidExecutionState("Write termination is not confirmed")
        self.execution_id = None
