"""모델을 호출하지 않고 관찰하는 외부 대상 종류다."""

import re
from collections.abc import Sequence
from dataclasses import replace
from enum import StrEnum
from pathlib import PurePath
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject

from neurath.domain.enums.liveness import Liveness
from neurath.domain.errors import ContextNotFound, InvalidTaskState


class MonitorKind(StrEnum):
    """모델을 호출하지 않고 관찰하는 외부 대상 종류다.

    Attributes:
        PULL_REQUEST: 명시한 GitHub PR의 의미 있는 상태 필드.
        OUTPUT: 완결된 JSON 행의 state를 내보내는 출력 파일.
    """

    PULL_REQUEST = "pull_request"
    OUTPUT = "output"


class NoticeStatus(StrEnum):
    """알림 작성·제출·실패·실제 확인을 구분한다.

    Attributes:
        WRITTEN: 사건과 함께 알림 본문을 보존함.
        SUBMITTING: 제출 예산을 소비했지만 결과는 아직 미확인임.
        SUBMITTED: 출력 또는 호스트 제출이 반환됨.
        FAILED: 관찰한 제출 실패와 필요한 조작을 보존함.
        DELIVERED: 같은 제출에 대한 실제 전달 확인이 있음.
        DISCARDED: 취소로 더 이상 제출하지 않음.
    """

    WRITTEN = "written"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    FAILED = "failed"
    DELIVERED = "delivered"
    DISCARDED = "discarded"


@immutable
class MonitorEvent(AbstractValueObject):
    """정확한 변화 사건과 독립적인 ACK·해소·알림 시도를 기록한다.

    Attributes:
        number: 감시 안의 사건 순번.
        state: 실제 변화를 관찰한 완결 상태.
        reference: 관찰 근거.
        body: 원 조건과 허용 후속 범위가 담긴 알림 원문.
        acknowledged: 정확한 사건의 소비 확인.
        resolved: 이 사건으로 외부 대기를 해소했는지 여부.
        notice_status: 알림의 현재 제출·전달 상태.
        attempts: 이미 소비한 알림 제출 예산.
        error: 제출 실패 또는 결과 불명의 필요한 조작.
        delivery_errors: 재시도·성공 뒤에도 보존하는 실제 실패 이력.
    """

    number: int
    state: str
    reference: str
    body: str
    acknowledged: bool = False
    resolved: bool = False
    notice_status: NoticeStatus = NoticeStatus.WRITTEN
    attempts: int = 0
    error: str = ""
    delivery_errors: Sequence[str] = ()


@immutable
class TaskMonitor(AbstractValueObject):
    """태스크가 소유하는 명시적 외부 의존 감시와 잔여 예산이다.

    Attributes:
        number: 태스크 안에서 구분하는 감시 순번.
        wait_number: 원래 외부 대기 이력의 순번.
        definition_number: 감시를 요청한 요구 개정.
        owner_execution_id: 현재 관찰·알림 자원을 소유한 실제 실행.
        kind: 지원하는 결정론적 관찰 종류.
        target: 요청한 PR 주소 또는 절대 출력 파일 경로.
        remaining_polls: 복구·인계에도 초기화하지 않는 관찰 예산.
        generation: 오래된 관찰·인계를 거부하는 자원 세대.
        active: 새 관찰과 제출을 허용하는지 여부.
        initial_state: 첫 완결 관찰이며 변화 사건과 구분함.
        current_state: 가장 최근 완결 상태.
        poll_id: 진행 중이거나 종료 미확인인 정확한 관찰 자원.
        error: 마지막 관찰 실패 또는 필요한 조작.
        stop_reason: 취소·예산 소진·요구 변경의 이유.
        events: 소비·해소·알림 상태를 포함한 모든 변화 사건.
    """

    number: int
    wait_number: int
    definition_number: int
    owner_execution_id: UUID
    kind: MonitorKind
    target: str
    remaining_polls: int
    generation: int = 1
    active: bool = True
    initial_state: str | None = None
    current_state: str | None = None
    poll_id: UUID | None = None
    error: str = ""
    stop_reason: str = ""
    events: Sequence[MonitorEvent] = ()

    @override
    def validate(self) -> None:
        """지원 대상 형식과 유한한 잔여 예산을 검사한다.

        Raises:
            ValueError: 대상·종류·예산이 지원 계약에 맞지 않는 경우.
        """
        if not 0 <= self.remaining_polls <= 10000:
            raise ValueError("Monitor poll budget must be between 0 and 10000")
        match self.kind:
            case MonitorKind.PULL_REQUEST:
                if re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/pull/[1-9]\d*", self.target):
                    return
            case MonitorKind.OUTPUT:
                if PurePath(self.target).is_absolute():
                    return
        raise ValueError("Unsupported monitor target or kind")

    def require_owner(self, execution_id: UUID, generation: int) -> None:
        """정확한 소유 실행과 세대가 아닌 작업을 거부한다.

        Args:
            execution_id: 실제 관찰한 소유 실행.
            generation: 조회 시 확인한 자원 세대.

        Raises:
            InvalidTaskState: 소유 실행이나 세대가 변경된 경우.
        """
        if (self.owner_execution_id, self.generation) != (execution_id, generation):
            raise InvalidTaskState("Monitor resource ownership changed")

    def begin_poll(self) -> Self:
        """관찰 전에 자원을 예약하고 예산을 한 번 소비한다.

        Returns:
            Self: 새 자원 ID를 가진 감시 또는 진행할 수 없는 현재 값.
        """
        if not self.active or self.poll_id is not None:
            return self
        if self.remaining_polls == 0:
            return replace(self, stop_reason="Poll budget exhausted; explicit action required")
        return replace(
            self,
            poll_id=uuid7(),
            remaining_polls=self.remaining_polls - 1,
            error="Observation in progress or outcome unknown; inspect exact resource before recovery",
        )

    def observe(
        self, poll_id: UUID, state: str | None, reference: str, error: str, body: str
    ) -> Self:
        """현재 자원의 결과만 반영하며 첫 관찰·동일 상태·출력 조각은 사건을 만들지 않는다.

        Args:
            poll_id: 실제 완료한 자원 ID.
            state: 완결된 대상 상태이며 출력 조각이면 None.
            reference: 실제 외부 관찰 근거.
            error: 관찰 실패와 필요한 조작.
            body: 기존 요청의 조건과 후속 범위를 포함한 알림 본문.

        Returns:
            Self: 관찰 결과 또는 취소·세대 변경으로 폐기한 늦은 결과.

        Raises:
            ValueError: 완결 상태나 근거가 비어 있거나 한도를 초과한 경우.
        """
        if self.poll_id != poll_id:
            return self
        current = replace(self, poll_id=None, error="")
        if not self.active:
            return current
        if error:
            return replace(current, error=error)
        if state is None:
            return current
        if not state.strip() or not reference.strip() or len(state) > 16384:
            raise ValueError("Observation requires bounded complete state and reference")
        if self.initial_state is None:
            return replace(current, initial_state=state, current_state=state, error="")
        if state == self.current_state:
            return replace(current, error="")
        return replace(
            current,
            current_state=state,
            error="",
            events=tuple(self.events)
            + (
                MonitorEvent(
                    number=len(self.events) + 1, state=state, reference=reference, body=body
                ),
            ),
        )

    def event(self, number: int) -> MonitorEvent:
        """지정한 정확한 변화 사건을 찾는다.

        Args:
            number: 감시 안의 사건 순번.

        Returns:
            MonitorEvent: 원문·관찰·소비·알림 이력.

        Raises:
            ContextNotFound: 해당 사건이 없는 경우.
        """
        for event in self.events:
            if event.number == number:
                return event
        raise ContextNotFound("Monitor event does not exist")

    def update_event(self, event: MonitorEvent) -> Self:
        """기존 사건 한 건의 소비·알림 상태만 교체한다.

        Args:
            event: 원래 순번을 유지한 갱신 사건.

        Returns:
            Self: 다른 사건과 잔여 예산을 보존한 감시.
        """
        self.event(event.number)
        return replace(
            self,
            events=tuple(event if item.number == event.number else item for item in self.events),
        )

    def acknowledge(self, number: int) -> Self:
        """정확한 사건만 소비하며 대기·태스크 성공·전달 상태를 바꾸지 않는다.

        Args:
            number: 소비한 사건 순번.

        Returns:
            Self: ACK가 기록된 감시.
        """
        return self.update_event(replace(self.event(number), acknowledged=True))

    def begin_notice(self, number: int) -> Self:
        """작성·실패 알림에 최대 세 번만 제출 예산을 부여한다.

        Args:
            number: 제출할 정확한 사건.

        Returns:
            Self: 제출 중인 알림 또는 추가 제출을 허용하지 않는 현재 값.
        """
        event = self.event(number)
        if (
            not self.active
            or event.notice_status not in (NoticeStatus.WRITTEN, NoticeStatus.FAILED)
            or event.attempts >= 3
        ):
            return self
        return self.update_event(
            replace(
                event,
                notice_status=NoticeStatus.SUBMITTING,
                attempts=event.attempts + 1,
                error="Submission outcome unknown; inspect this exact attempt before retry or handoff",
            )
        )

    def notice_result(self, number: int, attempt: int, status: NoticeStatus, error: str) -> Self:
        """같은 제출의 관찰만 반영하고 재전송이나 모델 실행은 만들지 않는다.

        Args:
            number: 제출한 사건.
            attempt: 실제 제출 시도 순번.
            status: 제출·실패 또는 실제 확인한 전달 상태.
            error: 실패 또는 필요한 조작.

        Returns:
            Self: 정확한 제출에 대한 결과를 보존한 감시.

        Raises:
            ValueError: 지원하지 않는 결과나 설명 없는 실패인 경우.
        """
        event = self.event(number)
        if event.attempts != attempt:
            return self
        if event.notice_status not in (NoticeStatus.SUBMITTING, NoticeStatus.SUBMITTED):
            return self
        if status not in (NoticeStatus.SUBMITTED, NoticeStatus.FAILED, NoticeStatus.DELIVERED):
            raise ValueError("Invalid notification result")
        if status is NoticeStatus.FAILED and not error.strip():
            raise ValueError("Failed notification requires reason and necessary action")
        return self.update_event(
            replace(
                event,
                notice_status=status,
                error=error,
                delivery_errors=tuple(event.delivery_errors) + (error,)
                if status is NoticeStatus.FAILED
                else event.delivery_errors,
            )
        )

    def cancel(self, reason: str) -> Self:
        """새 관찰·제출을 차단하되 종료 미확인 자원과 모든 사건은 보존한다.

        Args:
            reason: 명시적인 취소·요구 변경·해소 이유.

        Returns:
            Self: 자원 종료 대기와 원문을 보존한 감시.
        """
        if not self.active:
            return self
        return replace(
            self,
            active=False,
            stop_reason=reason,
            events=tuple(
                replace(event, notice_status=NoticeStatus.DISCARDED)
                if event.notice_status in (NoticeStatus.WRITTEN, NoticeStatus.FAILED)
                else event
                for event in self.events
            ),
        )

    def recover(self, poll_id: UUID, liveness: Liveness) -> Self:
        """정확한 자원의 실제 종료를 확인해야만 예약을 해제한다.

        Args:
            poll_id: 종료 관찰이 가리키는 자원.
            liveness: 자원의 실제 종료 상태.

        Returns:
            Self: 취소 상태·예산을 유지하며 오래된 결과를 차단한 감시.

        Raises:
            InvalidTaskState: 관찰 자원이 다르거나 실제 종료가 미확인인 경우.
        """
        if self.poll_id != poll_id or liveness is not Liveness.STOPPED:
            raise InvalidTaskState("Exact monitor resource termination must be observed")
        return replace(self, poll_id=None, generation=self.generation + 1)

    def transfer(self, execution_id: UUID) -> Self:
        """진행 자원이 없을 때 사건·취소·잔여 예산을 그대로 인계한다.

        Args:
            execution_id: 실제 확인한 후속 실행.

        Returns:
            Self: 새 소유 실행과 자원 세대를 가진 감시.

        Raises:
            InvalidTaskState: 종료 미확인 관찰이나 알림 제출이 있는 경우.
        """
        if self.poll_id is not None or any(
            event.notice_status is NoticeStatus.SUBMITTING for event in self.events
        ):
            raise InvalidTaskState("Reconcile actual monitor resources before handoff")
        return replace(self, owner_execution_id=execution_id, generation=self.generation + 1)
