"""현재 호스트 실행과 중단 상태를 보존하고 반복된 종료 거절을 끊는다."""

from collections.abc import Sequence
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.aggregates.task import Task
from neurath.domain.errors import InvalidExecutionState
from neurath.domain.runtime_events import ExecutionCancellationRequested
from neurath.domain.runtime_records import ExecutionStatus, HookAction
from neurath.domain.task_records import TaskStatus


@mutable
class Execution(AbstractAggregateRoot[UUID]):
    """한 호스트 세션의 루트 또는 네이티브 자식의 현재 실행을 관리한다.

    Attributes:
        session_id: 실제 호스트 연결이 속하는 내부 세션 ID.
        agent_id: 호스트가 준 자식 ID이며 루트는 빈 문자열.
        start_source: 마지막 SessionStart에서 관찰한 startup·resume·fork 등의 원인.
        turn_id: 호스트가 준 턴 또는 prompt ID이며 미관찰이면 빈 문자열.
        status: 실행 중·일시 중지·취소·종료의 관찰 상태.
        reason: 마지막 중지나 취소 원인.
        stop_snapshot: 직전 Stop에서 계속하도록 요청했던 태스크 개정과 상태.
        revision: 저장소가 비교하는 낙관적 버전.
    """

    session_id: UUID
    agent_id: str
    start_source: str
    turn_id: str
    status: ExecutionStatus
    reason: str
    stop_snapshot: str
    revision: int

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """네이티브 식별자와 구분되는 내부 실행 ID를 만든다.

        Returns:
            UUID: 새 UUID 값.
        """
        return uuid7()

    @classmethod
    def create(cls, session_id: UUID, agent_id: str = "") -> Self:
        """아직 턴을 관찰하지 않은 실행 연결을 만든다.

        Args:
            session_id: 등록된 내부 호스트 세션.
            agent_id: 실제 관찰된 자식 ID이며 루트는 빈 문자열.

        Returns:
            Self: 기존 태스크를 변경하지 않는 새 실행 연결.
        """
        return cls(
            uid=cls.next_id(),
            session_id=session_id,
            agent_id=agent_id,
            start_source="",
            turn_id="",
            status=ExecutionStatus.RUNNING,
            reason="",
            stop_snapshot="",
            revision=1,
        )

    def observe_start(self, source: str) -> None:
        """시작·재개·포크·압축의 실제 원인을 보존하며 실행 정지를 해제하지 않는다.

        Args:
            source: 호스트 SessionStart가 전달한 원인.
        """
        self.start_source = source

    def begin_turn(self, turn_id: str) -> None:
        """새 사용자 턴을 기록하되 취소·일시 중지는 명시적인 재개까지 보존한다.

        Args:
            turn_id: 호스트에서 관찰한 새 턴 식별자.

        Raises:
            InvalidExecutionState: 턴 식별자를 관찰하지 못한 경우.
        """
        if not turn_id:
            raise InvalidExecutionState("Host turn identity is unavailable")
        if turn_id == self.turn_id:
            return
        self.turn_id = turn_id
        self.stop_snapshot = ""

    def resume(self, turn_id: str) -> None:
        """사용자가 요청한 재개를 현재 턴에 적용한다.

        Args:
            turn_id: 명시적인 재개가 적용될 현재 호스트 턴.
        """
        self.require_turn(turn_id)
        self.status = ExecutionStatus.RUNNING
        self.reason = ""
        self.stop_snapshot = ""

    def require_turn(self, turn_id: str) -> None:
        """다른 턴이나 식별 불명 사건을 현재 실행에 적용하지 않는다.

        Args:
            turn_id: 사건이 가리키는 네이티브 턴.

        Raises:
            InvalidExecutionState: 현재 턴과 다르거나 식별자가 없는 경우.
        """
        if not turn_id or turn_id != self.turn_id:
            raise InvalidExecutionState("Event does not identify the current turn")

    def pause(self, reason: str) -> None:
        """태스크를 그대로 둔 채 호스트에 제어권을 반환할 상태로 전이한다.

        Args:
            reason: 사용자에게 표시할 중지 원인.
        """
        if self.status in (ExecutionStatus.CANCELLED, ExecutionStatus.ENDED):
            return
        self.status = ExecutionStatus.PAUSED
        self.reason = reason

    def cancel(self, turn_id: str, reason: str) -> None:
        """실제 중단 사건을 같은 턴에만 기록하고 후속 도구 실행을 막는다.

        Args:
            turn_id: 중단이 확인된 네이티브 턴.
            reason: 호스트가 보고한 중단 원인.
        """
        self.require_turn(turn_id)
        self.status = ExecutionStatus.CANCELLED
        self.reason = reason

    def end(self, reason: str) -> None:
        """호스트 연결 종료를 기록하며 미완료 태스크와 작성 임대는 유지한다.

        Args:
            reason: 호스트가 전달한 종료 원인.
        """
        self.status = ExecutionStatus.ENDED
        self.reason = reason

    def decide_stop(
        self, tasks: Sequence[Task], *, repeated: bool, progress: Sequence[tuple[UUID, int]] = ()
    ) -> HookAction:
        """최신 태스크를 대조하고 진전 없는 같은 종료 거절에서는 실제로 양보한다.

        실패는 완료가 아니며 실행 가능한 일이 외부 대기보다 우선한다. 빈 목록은
        대화 종료를 허용하지만 목표 달성으로 기록하지 않는다. 자식의 배정은 호출자가
        선택한 목록으로 받으며 루트의 TODO를 자식에게 자동 전가하지 않는다.

        Args:
            tasks: 현재 실행에 적용되는 최신 태스크 목록.
            repeated: 호스트가 보고한 Stop 계속 수행 여부.
            progress: 현재 태스크에 연결된 절차의 ID와 저장 개정.

        Returns:
            HookAction: 정상 종료 허용, 작업 계속 또는 성공과 구별되는 일시 중지.
        """
        if self.status is not ExecutionStatus.RUNNING:
            return HookAction.PAUSE
        unfinished = tuple(
            t for t in tasks if t.status not in (TaskStatus.SUCCEEDED, TaskStatus.INVALIDATED)
        )
        if not unfinished:
            return HookAction.ALLOW
        snapshot = repr(
            (sorted((t.uid, t.revision, t.status.value) for t in unfinished), sorted(progress))
        )
        if repeated and snapshot == self.stop_snapshot:
            self.pause("No progress after Stop feedback; unfinished work is preserved")
            return HookAction.PAUSE
        self.stop_snapshot = snapshot
        if all(t.status is TaskStatus.WAITING for t in unfinished):
            self.pause("External dependencies remain; unfinished work is preserved")
            return HookAction.PAUSE
        return HookAction.CONTINUE

    def request_cancellation(self, turn_id: str) -> None:
        """현재 턴의 추가 쓰기를 중단하고 커밋 이후 호스트 종료를 요청한다.

        Args:
            turn_id: 사용자 중단 요청이 지정한 실제 턴.
        """
        self.require_turn(turn_id)
        self.pause("Cancellation requested; actual termination is pending")
        self.add_event(ExecutionCancellationRequested(execution_id=self.uid, turn_id=turn_id))

    def require_stopped(self) -> None:
        """진행 중인 실제 작업을 인수 완료로 취급하지 않는다.

        Raises:
            InvalidExecutionState: 종료 또는 결과가 아직 확인되지 않은 경우.
        """
        if self.status not in (ExecutionStatus.CANCELLED, ExecutionStatus.ENDED):
            raise InvalidExecutionState("Source execution has not stopped")
