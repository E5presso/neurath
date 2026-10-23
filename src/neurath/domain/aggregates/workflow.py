"""스킬 정의와 실제 단계 시도의 이력을 소유하며 순서·재개·검증을 판단한다."""

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import replace
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.aggregates.task import Task
from neurath.domain.errors import ContextNotFound, InvalidWorkflowState, RevisionConflict
from neurath.domain.task_records import TaskStatus
from neurath.domain.workflow_events import PhaseExecutionRequested, PhaseWaitingRecorded
from neurath.domain.workflow_records import (
    PhaseAttempt,
    PhaseDefinition,
    PhaseResult,
    PhaseStatus,
    WorkflowDefinition,
    WorkflowRevision,
)


@mutable
class WorkflowRun(AbstractAggregateRoot[UUID]):
    """한 태스크의 선택 절차와 그 정의 개정·실행 결과를 보존한다.

    Attributes:
        project_id: 연결된 태스크의 프로젝트.
        session_id: 실행을 소유하는 세션.
        task_id: 이 절차로 수행할 태스크.
        revisions: 최초 정의와 후속 수정의 순서 있는 이력.
        attempts: 실제 실행·선택 단계 생략·결과 불명 이력.
        revision: 저장소가 갱신하는 낙관적 잠금 버전.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    revisions: Sequence[WorkflowRevision]
    attempts: Sequence[PhaseAttempt] = ()
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """외부 실행의 중복 식별에도 사용할 run UUID를 생성한다.

        Returns:
            UUID: 새 run의 독립적인 식별자.
        """
        return uuid7()

    @classmethod
    def create(
        cls,
        project_id: UUID,
        session_id: UUID,
        task_id: UUID,
        definition_number: int,
        definition: WorkflowDefinition,
    ) -> Self:
        """태스크의 현재 요구에 선택한 정의를 복사해 아직 실행하지 않은 run을 만든다.

        Args:
            project_id: 태스크의 프로젝트.
            session_id: 소유 세션.
            task_id: 연결할 태스크 ID.
            definition_number: 시작 시 태스크의 요구 개정.
            definition: 호출자가 선택한 스킬 버전과 입력·단계.

        Returns:
            Self: 정의만 보존하고 시도는 아직 없는 run.
        """
        return cls(
            uid=cls.next_id(),
            project_id=project_id,
            session_id=session_id,
            task_id=task_id,
            revisions=(
                WorkflowRevision(
                    definition=deepcopy(definition),
                    task_definition_number=definition_number,
                    reason="start",
                ),
            ),
        )

    @override
    def validate(self) -> None:
        """최초 정의가 없는 run을 거부한다.

        Raises:
            InvalidWorkflowState: 시작 시 선택한 정의 개정이 없는 경우.
        """
        if not self.revisions:
            raise InvalidWorkflowState("A workflow requires its initial definition")

    @property
    def definition(self) -> WorkflowDefinition:
        """현재 실행에 적용되는 마지막 절차 정의를 반환한다.

        Returns:
            WorkflowDefinition: 마지막 개정의 스킬·단계·입력.
        """
        return self.revisions[-1].definition

    def require_scope(self, project_id: UUID, session_id: UUID) -> None:
        """요청 프로젝트와 소유 세션이 이 run에 일치하는지 확인한다.

        Args:
            project_id: 요청한 프로젝트.
            session_id: 호출한 소유 세션.

        Raises:
            ContextNotFound: 요청 범위가 run의 소유 범위와 다른 경우.
        """
        if (project_id, session_id) != (self.project_id, self.session_id):
            raise ContextNotFound("Workflow does not belong to this project and session")

    def require_task(self, task: Task, *, recovering: bool = False) -> None:
        """실행할 태스크가 이 run의 현재 요구와 소유 범위에 맞는지 확인한다.

        Args:
            task: 저장소에서 조회한 연결 태스크의 현재 상태.
            recovering: 새 실행 대신 보존된 시도의 결과를 조회하는지 여부.

        Raises:
            InvalidWorkflowState: 다른 태스크·미활성 상태·정정 전 절차인 경우.
        """
        task.require_scope(self.project_id, self.session_id)
        recovering_wait = (
            recovering
            and task.status is TaskStatus.WAITING
            and bool(task.waits)
            and any(
                task.waits[-1].target == f"{self.uid}:{attempt.number}"
                for attempt in self.attempts
                if attempt.status in (PhaseStatus.RUNNING, PhaseStatus.WAITING)
            )
        )
        allowed = (
            (TaskStatus.ACTIVE, TaskStatus.WAITING) if recovering_wait else (TaskStatus.ACTIVE,)
        )
        if (
            task.uid != self.task_id
            or task.status not in allowed
            or task.definition.number != self.revisions[-1].task_definition_number
        ):
            raise InvalidWorkflowState("Current task must be active and match the workflow")

    def require_revision(self, revision: int) -> None:
        """읽은 저장 버전 이후 다른 변경이 있으면 수정을 거부한다.

        Args:
            revision: 호출자가 읽은 run 저장 버전.

        Raises:
            RevisionConflict: 현재 저장 버전과 다른 경우.
        """
        if self.revision != revision:
            raise RevisionConflict("Workflow changed; read it before updating")

    def phase_for(self, attempt: PhaseAttempt) -> PhaseDefinition:
        """시도를 시작할 때 고정한 단계 정의를 찾는다.

        Args:
            attempt: 이 run에 보존된 시도.

        Returns:
            PhaseDefinition: 당시 정의 버전의 단계.
        """
        return next(
            phase
            for phase in self.revisions[attempt.definition_number - 1].definition.phases
            if phase.key == attempt.phase_key
        )

    def latest(self, phase: PhaseDefinition) -> PhaseAttempt | None:
        """현재 단계와 대상·조건이 같은 마지막 시도만 재사용 후보로 선택한다.

        Args:
            phase: 현재 절차의 단계.

        Returns:
            PhaseAttempt | None: 현재 정의에 적용할 마지막 시도. 없으면 None.
        """
        return next(
            (
                attempt
                for attempt in reversed(self.attempts)
                if attempt.phase_key == phase.key and self.phase_for(attempt) == phase
            ),
            None,
        )

    def status_for(self, phase: PhaseDefinition) -> PhaseStatus:
        """단계 정의에 맞는 마지막 시도의 상태를 반환한다.

        Args:
            phase: 상태를 조회할 현재 단계 정의.

        Returns:
            PhaseStatus: 같은 정의의 시도가 없으면 pending, 있으면 그 시도의 상태.
        """
        attempt = self.latest(phase)
        return PhaseStatus.PENDING if attempt is None else attempt.status

    @property
    def current(self) -> PhaseDefinition | None:
        """아직 성공하거나 정당하게 생략하지 않은 첫 단계를 찾는다.

        Returns:
            PhaseDefinition | None: 다음 처리할 단계. 모두 끝났으면 None.
        """
        for phase in self.definition.phases:
            if self.status_for(phase) not in (PhaseStatus.SUCCEEDED, PhaseStatus.SKIPPED):
                return phase
        return None

    def begin(self) -> PhaseAttempt:
        """다음 단계의 실행을 예약하고 변경 명령의 중복 제출을 막는다.

        Returns:
            PhaseAttempt: 외부 실행 전에 저장해야 하는 새 running 시도.

        Raises:
            InvalidWorkflowState: 완료 상태·미확정 실행·소진된 재시도 한도인 경우.
        """
        phase = self.current
        if phase is None:
            raise InvalidWorkflowState("Workflow is already complete")
        previous = next(
            (
                item
                for item in self.attempts
                if item.phase_key == phase.key
                and item.status in (PhaseStatus.RUNNING, PhaseStatus.WAITING)
            ),
            None,
        )
        if previous is not None:
            raise InvalidWorkflowState("Reconcile the existing attempt before executing again")
        if (
            sum(
                attempt.phase_key == phase.key
                and attempt.status is not PhaseStatus.SKIPPED
                and self.phase_for(attempt).target_revision == phase.target_revision
                and self.revisions[attempt.definition_number - 1].task_definition_number
                == self.revisions[-1].task_definition_number
                for attempt in self.attempts
            )
            >= phase.max_attempts
        ):
            raise InvalidWorkflowState("Phase attempt limit reached; retain unresolved work")
        attempt = PhaseAttempt(
            number=len(self.attempts) + 1,
            definition_number=len(self.revisions),
            phase_key=phase.key,
            status=PhaseStatus.RUNNING,
        )
        self.attempts = tuple(self.attempts) + (attempt,)
        return attempt

    def report(self, number: int, result: PhaseResult, *, notify_waiting: bool = False) -> None:
        """시도 당시 대상과 조건을 대조하여 결과를 보존한다.

        현재 정의와 달라진 옛 시도도 이력에 남기지만 current 판정에는 쓰지 않는다.
        확정된 동일 결과는 재사용하고, 결과 불명은 조회로 확인한 결과로 바꿀 수 있다.

        Args:
            number: 보고할 시도 번호.
            result: 실행자 또는 검토자가 관찰한 결과.
            notify_waiting: 새 외부 대기 결과를 저장한 뒤 알림 사건을 남길지 여부.

        Raises:
            ContextNotFound: 해당 시도가 없는 경우.
            InvalidWorkflowState: 대상·검사·출력 한도가 다르거나 확정 결과를 덮어쓰는 경우.
        """
        attempt = next((item for item in self.attempts if item.number == number), None)
        if attempt is None:
            raise ContextNotFound("Workflow attempt does not exist")
        settled = attempt.status in (PhaseStatus.SUCCEEDED, PhaseStatus.FAILED, PhaseStatus.SKIPPED)
        if settled and attempt.result == result:
            return
        if settled:
            raise InvalidWorkflowState("A settled phase result cannot be overwritten")
        phase = self.phase_for(attempt)
        if result.target_revision != phase.target_revision:
            raise InvalidWorkflowState("Result belongs to another target revision")
        if len(result.output.encode()) > phase.output_limit:
            raise InvalidWorkflowState("Result output exceeds the phase limit")
        if result.status is PhaseStatus.SUCCEEDED and not set(phase.checks).issubset(result.checks):
            raise InvalidWorkflowState("Required checks are missing")
        updated = replace(attempt, status=result.status, result=deepcopy(result))
        self.attempts = tuple(updated if item.number == number else item for item in self.attempts)

        if notify_waiting and result.status is PhaseStatus.WAITING and result != attempt.result:
            self.add_event(
                PhaseWaitingRecorded(request_id=f"{self.uid}:{number}", reason=result.summary)
            )

    def applies_to_current(self, number: int) -> bool:
        """지정 시도가 현재 정의의 해당 단계에서 사용하는 마지막 시도인지 판단한다.

        Args:
            number: 결과를 반영한 시도 번호.

        Returns:
            bool: 현재 정의·대상·조건에서 재사용하는 마지막 시도이면 True.
        """
        return any(
            (attempt := self.latest(phase)) is not None and attempt.number == number
            for phase in self.definition.phases
        )

    def skip(self, condition: str, reason: str) -> None:
        """선택 단계의 정의된 조건에 맞는 생략만 이력으로 기록한다.

        Args:
            condition: 현재 정의에 명시된 생략 조건.
            reason: 그 조건이 충족됐다는 근거.

        Raises:
            InvalidWorkflowState: 필수·실행 중·완료 단계이거나 조건·근거가 없는 경우.
        """
        phase = self.current
        if (
            phase is None
            or phase.skip_condition is None
            or phase.skip_condition != condition
            or not reason.strip()
        ):
            raise InvalidWorkflowState("Only a defined optional branch may be skipped")
        previous = next(
            (
                item
                for item in self.attempts
                if item.phase_key == phase.key
                and item.status in (PhaseStatus.RUNNING, PhaseStatus.WAITING)
            ),
            None,
        )
        if previous is not None:
            raise InvalidWorkflowState("An unresolved execution cannot be skipped")
        self.attempts = tuple(self.attempts) + (
            PhaseAttempt(
                number=len(self.attempts) + 1,
                definition_number=len(self.revisions),
                phase_key=phase.key,
                status=PhaseStatus.SKIPPED,
                skip_reason=reason,
            ),
        )

    def revise(
        self, definition: WorkflowDefinition, task_definition_number: int, reason: str
    ) -> None:
        """새 절차를 보존하고 내용이 같은 단계의 시도와 결과를 재사용한다.

        Args:
            definition: 수정한 스킬·단계·입력 정의.
            task_definition_number: 현재 태스크의 요구 개정.
            reason: 방법 변경 또는 사용자 정정의 이유.

        Raises:
            InvalidWorkflowState: 이유가 없거나 요구 정정 없이 필수 단계를 삭제한 경우.
        """
        if not reason.strip():
            raise InvalidWorkflowState("Workflow revision requires a reason")
        if (
            definition == self.definition
            and task_definition_number == self.revisions[-1].task_definition_number
        ):
            return
        required = {phase.key for phase in self.definition.phases if phase.skip_condition is None}
        retained = {phase.key for phase in definition.phases if phase.skip_condition is None}
        if task_definition_number == self.revisions[
            -1
        ].task_definition_number and not required.issubset(retained):
            raise InvalidWorkflowState(
                "Required phases need an actual task correction before removal"
            )
        self.revisions = tuple(self.revisions) + (
            WorkflowRevision(
                definition=deepcopy(definition),
                task_definition_number=task_definition_number,
                reason=reason,
            ),
        )

    def require_complete(self, task_definition_number: int) -> None:
        """연결 태스크를 성공 처리하기 전에 현재 요구의 절차가 끝났는지 확인한다.

        Args:
            task_definition_number: 결과를 보고하는 태스크의 현재 요구 개정.

        Raises:
            InvalidWorkflowState: 현재 요구에 맞춰 수정하지 않았거나 남은 단계가 있는 경우.
        """
        if (
            task_definition_number != self.revisions[-1].task_definition_number
            or self.current is not None
        ):
            raise InvalidWorkflowState("Current workflow phases are not complete")

    def request_execution(self, attempt: PhaseAttempt, *, fresh: bool) -> None:
        """현재 저장할 시도를 커밋 후 실행할 도메인 이벤트로 기록한다.

        Args:
            attempt: 새로 예약했거나 결과를 조정할 기존 시도.
            fresh: 새 실행이면 True이며 기존 시도는 먼저 결과를 조회한다.
        """
        self.add_event(
            PhaseExecutionRequested(
                project_id=self.project_id,
                session_id=self.session_id,
                run_id=self.uid,
                phase=self.phase_for(attempt),
                attempt=attempt,
                fresh=fresh,
            )
        )

    def transfer(self, source_session_id: UUID, target_session_id: UUID) -> None:
        """원 소유자가 일치할 때 현재 소유만 옮기고 과거 이력을 유지한다.

        Args:
            source_session_id: 인수 전 확인한 소유 세션.
            target_session_id: 같은 프로젝트로 확인된 후속 세션.

        Raises:
            ContextNotFound: 현재 소유자가 원 세션과 다른 경우.
        """
        if self.session_id != source_session_id:
            raise ContextNotFound("Ownership changed before handoff")
        self.session_id = target_session_id

    def require_transferable(self) -> None:
        """진행 중인 실제 작업을 인수 완료로 취급하지 않는다.

        Raises:
            InvalidWorkflowState: 종료 또는 결과가 아직 확인되지 않은 경우.
        """
        if any(attempt.status is PhaseStatus.RUNNING for attempt in self.attempts):
            raise InvalidWorkflowState("Observe outstanding phase execution before handoff")
