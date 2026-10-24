"""원래 태스크 요구에 연결된 배정과 실제 수신자의 수행 이력을 보존한다."""

from collections.abc import Sequence
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.aggregates.task import Task
from neurath.domain.enums.delegation_role import DelegationRole
from neurath.domain.enums.delegation_route import DelegationRoute
from neurath.domain.enums.delegation_status import DelegationStatus
from neurath.domain.enums.provider_status import ProviderStatus
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.errors import ContextNotFound, InvalidTaskState
from neurath.domain.events.provider_execution_requested import ProviderExecutionRequested
from neurath.domain.events.provider_stop_requested import ProviderStopRequested
from neurath.domain.values.delegation_report import DelegationReport
from neurath.domain.values.provider_plan import ProviderPlan


@mutable
class Delegation(AbstractAggregateRoot[UUID]):
    """한 요구 개정의 수행·검토 배정이며 정정 전 결과도 역사로 남긴다.

    Attributes:
        task_id: 원래 작업.
        definition_number: 맡긴 요구 개정.
        source_id: 원래 사용자 지시 또는 정정의 출처.
        sender_id: 배정 책임을 가진 피어.
        recipient_id: 수신 피어이며 독립 실행 준비 시 None.
        role: 수행자 또는 검토자.
        scope: 위임받은 명시적 범위.
        route: 피어·네이티브 자식·provider 경로.
        parent_id: 재위임의 원 배정이며 최초 배정이면 None.
        plan: provider 실행 계획이며 피어 경로면 None.
        status: 현재 배정·수행·중단 상태.
        message_id: 배정을 전달하는 원 메시지 ID.
        execution_reference: 실제 provider 실행 또는 네이티브 작업 참조.
        progress: 수신자의 진행 관찰 이력.
        report: 수신한 결과. 태스크 성공 확정은 아니다.
        stop_reason: 부모 정정·취소로 더 실행할 수 없는 이유.
        stop_evidence: 실제 중단 관찰. 없으면 중단 미확인.
        provider_requested: 외부 실행을 요청해 커밋한 사실이며 실제 시작과 구분한다.
        provider_status: 마지막 provider 실행 관찰.
        provider_output: 실제 실행의 결과 본문.
        provider_error: 실패·미확인 관찰의 설명.
        native_session_id: 실제 출력에서 관찰한 호스트 세션 ID.
        revision: 저장소 낙관적 버전.
        candidate: 독립 평가의 내용 지문이며 일반 배정은 빈 문자열.
    """

    task_id: UUID
    definition_number: int
    source_id: UUID
    sender_id: UUID
    recipient_id: UUID | None
    role: DelegationRole
    scope: str
    route: DelegationRoute
    parent_id: UUID | None = None
    plan: ProviderPlan | None = None
    status: DelegationStatus = DelegationStatus.PREPARED
    message_id: UUID | None = None
    execution_reference: str | None = None
    progress: Sequence[str] = ()
    report: DelegationReport | None = None
    stop_reason: str | None = None
    stop_evidence: str | None = None
    provider_requested: bool = False
    provider_status: ProviderStatus | None = None
    provider_output: str = ""
    provider_error: str | None = None
    native_session_id: str | None = None
    revision: int = 1
    candidate: str = ""

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """배정의 전달·복구에서 재사용할 ID를 생성한다.

        Returns:
            UUID: 새 배정 ID.
        """
        return uuid7()

    @override
    def validate(self) -> None:
        """계획·수신자·경로와 배정 범위의 일관성을 검사한다.

        Raises:
            ValueError: 요구 개정·범위가 없거나 경로별 필수 정보가 잘못된 경우.
        """
        if self.candidate and self.role is not DelegationRole.REVIEWER:
            raise ValueError("Evaluation candidates require a reviewer")
        if self.definition_number < 1 or not self.scope.strip():
            raise ValueError("Delegation requires a current definition and scope")
        if (self.route is DelegationRoute.PROVIDER) != (self.plan is not None):
            raise ValueError("Only an independent provider route requires a provider plan")
        if self.route is not DelegationRoute.PROVIDER and self.recipient_id is None:
            raise ValueError("Peer and native child routes require an observed recipient")

    def require_current(self, task: Task) -> None:
        """정정·취소된 배정이 수락·시작·재위임에 사용되지 않게 한다.

        Args:
            task: DB에서 읽은 현재 원 태스크.

        Raises:
            InvalidTaskState: 원 태스크·개정이 바뀌었거나 취소된 경우.
        """
        if (
            task.uid != self.task_id
            or task.definition.number != self.definition_number
            or task.status is TaskStatus.INVALIDATED
            or self.stop_reason is not None
        ):
            raise InvalidTaskState("Delegation no longer matches the current request")

    def require_recipient(self, peer_id: UUID) -> None:
        """수신자가 다른 배정에 수락·결과를 기록하지 못하게 한다.

        Args:
            peer_id: 실제 수신 피어.

        Raises:
            ContextNotFound: 배정 수신자가 다른 경우.
        """
        if peer_id != self.recipient_id:
            raise ContextNotFound("Delegation belongs to another recipient")

    def assign(self, message_id: UUID) -> None:
        """원 배정 메시지를 연결하며 반복 제출은 같은 ID만 허용한다.

        Args:
            message_id: 검증·저장할 배정 메시지.

        Raises:
            InvalidTaskState: 이미 다른 메시지로 배정했거나 중단 요청이 있는 경우.
        """
        if self.message_id == message_id:
            return
        if self.status is not DelegationStatus.PREPARED or self.stop_reason is not None:
            raise InvalidTaskState("Delegation has already been assigned or stopped")
        self.message_id = message_id
        self.status = DelegationStatus.ASSIGNED

    def accept(self, peer_id: UUID, task: Task) -> None:
        """최신 배정을 원 수신자가 수락한다. 추가 인간 입력을 요구하지 않는다.

        Args:
            peer_id: 수락하는 수신자.
            task: 최신 요구 확인용 원 태스크.

        Raises:
            InvalidTaskState: 아직 배정하지 않았거나 완료한 배정인 경우.
        """
        self.require_recipient(peer_id)
        self.require_current(task)
        if self.status in (DelegationStatus.ACCEPTED, DelegationStatus.RUNNING):
            return
        if self.status is not DelegationStatus.ASSIGNED:
            raise InvalidTaskState("Only an assigned task can be accepted")
        self.status = DelegationStatus.ACCEPTED

    def advance(self, peer_id: UUID, task: Task, observation: str) -> None:
        """수락된 최신 배정에 실제 진행 관찰을 추가한다.

        Args:
            peer_id: 수행을 보고하는 수신자.
            task: 현재 원 태스크.
            observation: 실제 시작·검사·진행의 근거.

        Raises:
            InvalidTaskState: 수락되지 않은 배정인 경우.
            ValueError: 진행 관찰이 빈 경우.
        """
        self.require_recipient(peer_id)
        self.require_current(task)
        if self.status not in (DelegationStatus.ACCEPTED, DelegationStatus.RUNNING):
            raise InvalidTaskState("Accept delegation before reporting progress")
        if not observation.strip():
            raise ValueError("Progress requires an observation")
        if observation not in self.progress:
            self.progress = (*self.progress, observation)
        self.status = DelegationStatus.RUNNING

    def complete(self, peer_id: UUID, report: DelegationReport) -> None:
        """옛 개정의 늦은 보고도 보존하되 취소·정정 상태는 되돌리지 않는다.

        Args:
            peer_id: 원 배정 수신자.
            report: 역할과 배정 개정에 연결할 결과.

        Raises:
            InvalidTaskState: 수락 전에 결과를 내거나 확정 보고를 덮어쓰려 한 경우.
        """
        self.require_recipient(peer_id)
        if self.report == report:
            return
        if self.report is not None or self.status in (
            DelegationStatus.PREPARED,
            DelegationStatus.ASSIGNED,
        ):
            raise InvalidTaskState("Report requires acceptance and cannot overwrite prior evidence")
        self.report = report
        if self.stop_reason is None:
            self.status = DelegationStatus.COMPLETED

    def reconcile(self, task: Task) -> None:
        """영향받은 요구 개정의 배정만 중단 요청으로 바꾼다.

        Args:
            task: 실제 정정·무효화가 반영된 원 태스크.
        """
        if (
            task.definition.number == self.definition_number
            and task.status is not TaskStatus.INVALIDATED
        ):
            return
        if self.stop_reason is not None:
            return
        self.stop_reason = (
            f"Task {task.uid} now uses definition {task.definition.number} ({task.status})"
        )
        self.status = DelegationStatus.STOP_REQUESTED
        if (
            self.provider_status
            in (ProviderStatus.COMPLETED, ProviderStatus.FAILED, ProviderStatus.STOPPED)
            and self.execution_reference is not None
        ):
            self.stop_evidence = self.execution_reference
            self.status = DelegationStatus.STOPPED
            return
        if self.provider_requested:
            self.add_event(ProviderStopRequested(delegation_id=self.uid, sender_id=self.sender_id))

    def confirm_stop(self, peer_id: UUID, evidence: str) -> None:
        """수신 경계의 중단 관찰이 있을 때만 실제 중단을 표시한다.

        Args:
            peer_id: 중단을 확인한 원 수신자.
            evidence: 실제 종료·중단의 관찰 참조.

        Raises:
            InvalidTaskState: 중단 요청이 없거나 관찰이 빈 경우.
        """
        self.require_recipient(peer_id)
        if self.stop_reason is None or not evidence.strip():
            raise InvalidTaskState("Stop confirmation requires a request and actual evidence")
        self.stop_evidence = evidence
        self.status = DelegationStatus.STOPPED

    def request_provider(self, task: Task, prompt: str) -> None:
        """최신 배정의 고정 계획을 한 번만 실행 요청 사건으로 보낸다.

        Args:
            task: 현재 원 태스크.
            prompt: 원 지시와 범위를 포함한 입력.

        Raises:
            InvalidTaskState: 독립 provider 실행 계획이 없는 경우.
        """
        self.require_current(task)
        if self.plan is None:
            raise InvalidTaskState("Provider execution requires a saved plan")
        if self.provider_requested:
            return
        self.provider_requested = True
        self.add_event(
            ProviderExecutionRequested(delegation_id=self.uid, plan=self.plan, prompt=prompt)
        )

    def observe_provider(
        self,
        reference: str,
        status: ProviderStatus,
        native_session_id: str | None,
        output: str,
        error: str | None,
    ) -> None:
        """원 실행 관찰을 보존하고 지연된 관찰로 종료 상태를 퇴행시키지 않는다.

        Args:
            reference: 실제 실행 자료 위치.
            status: 실제 관찰 상태.
            native_session_id: 출력에서 확인한 호스트 세션 ID.
            output: 실제 결과 원문.
            error: 실패 또는 불확실성의 설명.

        Raises:
            InvalidTaskState: 실행 요청 없이 결과를 기록하거나 원 실행과 다른 관찰인 경우.
        """
        if not self.provider_requested:
            raise InvalidTaskState("Provider observation requires a committed execution request")
        if not reference.strip():
            if status is not ProviderStatus.UNKNOWN or not error:
                raise InvalidTaskState("An unobserved execution requires a failure diagnostic")
            if self.provider_status in (
                ProviderStatus.COMPLETED,
                ProviderStatus.FAILED,
                ProviderStatus.STOPPED,
            ):
                return
            self.provider_status = ProviderStatus.UNKNOWN
            self.provider_error = error
            return
        if self.execution_reference is not None and self.execution_reference != reference:
            raise InvalidTaskState("Observation belongs to a different execution")
        if (
            self.native_session_id is not None
            and native_session_id is not None
            and native_session_id != self.native_session_id
        ):
            raise InvalidTaskState("Observed native session changed")
        if self.provider_status in (
            ProviderStatus.COMPLETED,
            ProviderStatus.FAILED,
            ProviderStatus.STOPPED,
        ):
            return
        self.execution_reference = reference
        self.provider_status = status
        if native_session_id is not None:
            self.native_session_id = native_session_id
        self.provider_output = output
        self.provider_error = error
        if (
            status in (ProviderStatus.COMPLETED, ProviderStatus.FAILED, ProviderStatus.STOPPED)
            and self.stop_reason is not None
        ):
            self.stop_evidence = reference
            self.status = DelegationStatus.STOPPED
        elif self.stop_reason is None and status in (
            ProviderStatus.RUNNING,
            ProviderStatus.COMPLETED,
            ProviderStatus.FAILED,
        ):
            self.status = (
                DelegationStatus.RUNNING
                if status is ProviderStatus.RUNNING
                else DelegationStatus.COMPLETED
            )

    def bind_provider_peer(self, provider: str, native_session_id: str, peer_id: UUID) -> None:
        """실제 호스트 관찰의 세션을 원 provider 배정의 수신자로 연결한다.

        Args:
            provider: 실제 관찰한 공급자.
            native_session_id: 호스트 출력 또는 훅이 전달한 원 세션 ID.
            peer_id: 해당 실제 주소로 등록한 피어.

        Raises:
            InvalidTaskState: 고정 계획이나 이미 확인한 실제 세션과 다른 경우.
        """
        if self.plan is None or self.plan.provider != provider or not native_session_id.strip():
            raise InvalidTaskState("Observed provider does not match the saved plan")
        if self.native_session_id not in (None, native_session_id) or self.recipient_id not in (
            None,
            peer_id,
        ):
            raise InvalidTaskState("Provider assignment is already bound to another receiver")
        self.native_session_id = native_session_id
        self.recipient_id = peer_id

    def evaluation_report(self) -> DelegationReport:
        """실제 완료한 독립 실행 또는 수신자의 원 보고만 평가 근거로 반환한다.

        Returns:
            DelegationReport: 원 보고 또는 실제 provider 출력과 실행 참조.

        Raises:
            InvalidTaskState: 완료·출력·실제 실행 관찰이 빠진 경우.
        """
        if self.status is not DelegationStatus.COMPLETED:
            raise InvalidTaskState("Evaluation has no completed report")
        if self.plan is None:
            if self.report is None:
                raise InvalidTaskState("Evaluation has no completed report")
            return self.report
        if (
            self.provider_status is not ProviderStatus.COMPLETED
            or not self.native_session_id
            or not self.execution_reference
            or not self.provider_output.strip()
        ):
            raise InvalidTaskState("Provider evaluation has not completed successfully")
        return DelegationReport(
            summary=self.provider_output, references=(self.execution_reference,)
        )

    def require_redelegation(self, task: Task, sender_id: UUID) -> None:
        """수락한 최신 배정의 수신자만 그 범위에서 다시 위임할 수 있게 한다.

        Args:
            task: 현재 원 태스크.
            sender_id: 재위임을 요청한 피어.

        Raises:
            InvalidTaskState: 아직 수락하지 않았거나 이미 끝낸 배정인 경우.
        """
        if self.candidate:
            raise InvalidTaskState("Evaluation assignments cannot recursively delegate evaluation")
        self.require_recipient(sender_id)
        self.require_current(task)
        if self.status not in (DelegationStatus.ACCEPTED, DelegationStatus.RUNNING):
            raise InvalidTaskState("Redelegation requires an accepted current assignment")

    def find_reusable(self, assignments: Sequence[Self]) -> Self | None:
        """같은 요구·역할의 배정을 재사용하고 다른 원문으로 덮어쓰는 재시도를 거부한다.

        Args:
            assignments: 같은 태스크에 이미 저장한 배정들.

        Returns:
            Self | None: 같은 요청의 기존 배정이며 최초 요청이면 None.

        Raises:
            InvalidTaskState: 루트 배정이 이미 있거나 같은 배정의 범위를 바꾸려 한 경우.
        """
        for existing in assignments:
            if (
                existing.candidate != self.candidate
                or existing.definition_number != self.definition_number
                or existing.role is not self.role
            ):
                continue
            if existing.sender_id != self.sender_id:
                if existing.parent_id is None and self.parent_id is None:
                    raise InvalidTaskState(
                        "This task revision already has a root assignment; recover it instead of duplicating execution"
                    )
                continue
            recipient_id = None if existing.plan is not None else existing.recipient_id
            if (
                recipient_id != self.recipient_id
                or (not self.candidate and existing.scope != self.scope)
                or existing.route is not self.route
                or existing.plan != self.plan
            ):
                raise InvalidTaskState("This definition and role already have an assignment")
            return existing
        return None
