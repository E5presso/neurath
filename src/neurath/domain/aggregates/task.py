"""태스크가 요구 개정·실행 시도·외부 대기 이력을 한 원장에서 관리한다."""

from collections.abc import Sequence
from dataclasses import replace
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.aggregates.request_source import RequestSource
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.errors import ContextNotFound, InvalidTaskState, RevisionConflict
from neurath.domain.events.task_definition_changed import TaskDefinitionChanged
from neurath.domain.events.task_resumed import TaskResumed
from neurath.domain.values.external_wait import ExternalWait
from neurath.domain.values.task_attempt import Outcome, SubmittedResult, TaskAttempt, TaskResult
from neurath.domain.values.task_definition import TaskDefinition
from neurath.domain.values.task_monitor import MonitorKind, TaskMonitor


@mutable
class Task(AbstractAggregateRoot[UUID]):
    """사용자 요구와 현재 상태 및 이전 시도의 결과를 보존하는 aggregate다.

    Attributes:
        project_id: 태스크가 속하는 프로젝트.
        owner_session_id: 현재 작업을 소유한 세션.
        definitions: 최초 정의부터 이어지는 요구 개정.
        status: 현재 작업 상태.
        attempts: 이 태스크가 소유하는 모든 실행 시도.
        waits: 외부 대기와 해소 관찰의 이력.
        current_attempt_number: 현재 요구에 연결된 시도 번호.
        follow_up_of: 미달 요구를 이어받는 원래 태스크.
        invalidated_reason: 실제 정정으로 무효화한 이유.
        revision: 저장소의 정수 낙관적 버전.
        monitors: 명시적으로 요청한 외부 대기에 종속된 감시 이력.
    """

    project_id: UUID
    owner_session_id: UUID
    definitions: Sequence[TaskDefinition]
    status: TaskStatus = TaskStatus.PENDING
    attempts: Sequence[TaskAttempt] = ()
    waits: Sequence[ExternalWait] = ()
    current_attempt_number: int | None = None
    follow_up_of: UUID | None = None
    invalidated_reason: str | None = None
    revision: int = 1
    monitors: Sequence[TaskMonitor] = ()

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """새 태스크 식별자를 생성한다.

        Returns:
            UUID: 새 작업의 안정적인 식별자.
        """
        return uuid7()

    @classmethod
    def create(
        cls,
        project_id: UUID,
        session_id: UUID,
        source: RequestSource,
        title: str,
        required_result: str,
        dependencies: Sequence[UUID] = (),
        follow_up_of: UUID | None = None,
    ) -> Self:
        """기존 출처를 재사용하면서 최초 요구를 정의한다.

        Args:
            project_id: 관련 프로젝트.
            session_id: 작업 소유 세션.
            source: 보존된 원문.
            title: 작업 제목.
            required_result: 달성할 결과.
            dependencies: 먼저 성공해야 하는 태스크들.
            follow_up_of: 원래 미달 요구의 태스크.

        Returns:
            Self: 아직 실행하지 않은 새 태스크.
        """
        source.require_project(project_id)
        source.require_requirement()
        definition = TaskDefinition(
            number=1,
            source_id=source.uid,
            title=title,
            required_result=required_result,
            dependencies=tuple(sorted(dependencies)),
        )
        return cls(
            uid=cls.next_id(),
            project_id=project_id,
            owner_session_id=session_id,
            definitions=(definition,),
            follow_up_of=follow_up_of,
        )

    @override
    def validate(self) -> None:
        """원문으로 돌아갈 수 없는 빈 요구 이력을 거부한다.

        Raises:
            InvalidTaskState: 최초 정의가 없는 경우.
        """
        if not self.definitions:
            raise InvalidTaskState("A task requires its original definition")

    @property
    def definition(self) -> TaskDefinition:
        """현재 요구를 반환한다.

        Returns:
            TaskDefinition: 최초 정의 또는 마지막으로 추가한 정정·무효화 개정.
        """
        return self.definitions[-1]

    def require_project(self, project_id: UUID) -> None:
        """태스크가 요청한 프로젝트에 속하는지 검사한다.

        Args:
            project_id: 요청한 프로젝트 식별자.

        Raises:
            ContextNotFound: 태스크가 다른 프로젝트에 속하는 경우.
        """
        if self.project_id != project_id:
            raise ContextNotFound("Task does not belong to this project")

    def require_scope(self, project_id: UUID, session_id: UUID) -> None:
        """소유권을 이전하지 않고 현재 프로젝트·세션 범위를 검사한다.

        Args:
            project_id: 요청 프로젝트.
            session_id: 요청 세션.

        Raises:
            ContextNotFound: 요청 범위와 소유 범위가 다른 경우.
        """
        self.require_project(project_id)
        if self.owner_session_id != session_id:
            raise ContextNotFound("Task does not belong to this project and session")

    def require_revision(self, expected_revision: int) -> None:
        """오래된 관찰로 작업 상태를 바꾸지 못하게 한다.

        Args:
            expected_revision: 호출자가 관찰한 버전.

        Raises:
            RevisionConflict: 저장된 버전과 관찰 버전이 다른 경우.
        """
        if self.revision != expected_revision:
            raise RevisionConflict("Task changed; read its current state before updating")

    def ready(self, tasks: Sequence[Self]) -> bool:
        """pending·failed 상태이고 모든 선행 작업이 succeeded인지 확인한다.

        Args:
            tasks: 같은 프로젝트의 현재 전체 작업.

        Returns:
            bool: 새 시도를 시작할 수 있으면 True. 목록에 없는 선행 작업도 미충족으로 본다.
        """
        statuses = {task.uid: task.status for task in tasks}
        return self.status in (TaskStatus.PENDING, TaskStatus.FAILED) and all(
            statuses.get(uid) is TaskStatus.SUCCEEDED for uid in self.definition.dependencies
        )

    def start(self, tasks: Sequence[Self]) -> None:
        """현재 요구 개정에 새 시도를 연결하고 태스크를 active로 바꾼다.

        외부 실행을 시작하지는 않는다. 시작할 때의 요구 개정·소유 세션을 시도에
        고정하고 이전 시도 다음 번호를 부여한다.

        Args:
            tasks: 의존 성공을 판단할 같은 프로젝트의 작업들.

        Raises:
            InvalidTaskState: 실행 상태 또는 의존 성공 조건이 맞지 않는 경우.
        """
        if not self.ready(tasks):
            raise InvalidTaskState(
                "Task is not ready; active attempts and unresolved dependencies cannot restart"
            )
        attempt = TaskAttempt(
            number=len(self.attempts) + 1,
            definition_number=self.definition.number,
            session_id=self.owner_session_id,
        )
        self.attempts = tuple(self.attempts) + (attempt,)
        self.current_attempt_number = attempt.number
        self.status = TaskStatus.ACTIVE

    def attempt(self, number: int) -> TaskAttempt:
        """이 태스크에 속하는 시도만 찾는다.

        Args:
            number: 태스크 안에서 구분하는 시도 번호.

        Returns:
            TaskAttempt: 보존된 시도 기록.

        Raises:
            ContextNotFound: 지정한 시도가 없는 경우.
        """
        for attempt in self.attempts:
            if attempt.number == number:
                return attempt
        raise ContextNotFound("Task attempt does not exist")

    def submit(self, number: int, submission: SubmittedResult) -> None:
        """미확정 시도의 후보를 교체하며 태스크 상태는 유지한다.

        동일한 후보는 변경하지 않는다. 과거 요구 개정의 시도도 지정할 수 있지만
        확정 결과가 있는 시도는 거부한다. 시도가 없으면 ContextNotFound가 전파된다.

        Args:
            number: 후보를 제출할 시도.
            submission: 확정 전 보고와 참조.

        Raises:
            InvalidTaskState: 이미 확정한 시도를 다시 제출하려 한 경우.
        """
        attempt = self.attempt(number)
        if attempt.result is not None:
            raise InvalidTaskState("A resolved attempt cannot be submitted again")
        if attempt.submission != submission:
            updated = replace(attempt, submission=submission)
            self.attempts = tuple(
                updated if item.number == number else item for item in self.attempts
            )

    def report(self, number: int, result: TaskResult, expected_revision: int) -> None:
        """시도 결과를 확정하고 현재 요구 개정에 대응할 때 상태에 반영한다.

        이미 확정된 동일 결과는 revision 검사 없이 반환한다. 새 결과는 revision을
        검사하여 저장하고, 이전 요구 개정의 시도이면 현재 상태를 유지한다. 현재 개정의
        성공·실패·부분 수행은 각각 succeeded·failed·pending이 된다. 시도가 없으면
        ContextNotFound, 새 결과의 revision이 다르면 RevisionConflict가 전파된다.

        Args:
            number: 결과를 보고할 시도.
            result: 실제 관찰 및 남은 일.
            expected_revision: 호출자가 관찰한 태스크 버전.

        Raises:
            InvalidTaskState: 이미 보존한 확정 결과를 바꾸려 한 경우.
        """
        attempt = self.attempt(number)
        if attempt.result == result:
            return
        if attempt.result is not None:
            raise InvalidTaskState("A recorded result cannot be overwritten")
        self.require_revision(expected_revision)
        updated = replace(attempt, result=result)
        self.attempts = tuple(updated if item.number == number else item for item in self.attempts)
        if attempt.definition_number != self.definition.number:
            return
        statuses = {
            Outcome.SUCCEEDED: TaskStatus.SUCCEEDED,
            Outcome.FAILED: TaskStatus.FAILED,
            Outcome.PARTIAL: TaskStatus.PENDING,
        }
        self.status = statuses[result.outcome]
        self.cancel_monitors("Current task attempt reported a result")

    def correct(
        self,
        source: RequestSource,
        title: str | None = None,
        required_result: str | None = None,
        dependencies: Sequence[UUID] | None = None,
    ) -> None:
        """변경된 필드로 새 요구 개정을 추가하고 다음 시도를 준비한다.

        None인 필드는 유지한다. 제목·결과·정렬한 의존 목록이 기존과 같으면
        개정과 상태를 바꾸지 않는다. 변경 시 pending으로 돌아가 현재 시도 연결과
        무효화 사유를 지우되 이전 정의·시도는 보존한다. 출처는 같은 프로젝트의
        현재 요구를 정정해야 하며, 의존 그래프 검사는 호출 전에 별도로 수행한다.

        Args:
            source: 실제 정정 출처.
            title: 바꿀 제목이며 None이면 기존 값.
            required_result: 바꿀 결과이며 None이면 기존 값.
            dependencies: 바꿀 의존이며 None이면 기존 값.
        """
        source.require_project(self.project_id)
        source.require_correction(self.definition.source_id)
        current = self.definition
        updated = TaskDefinition(
            number=current.number + 1,
            source_id=source.uid,
            title=current.title if title is None else title,
            required_result=current.required_result if required_result is None else required_result,
            dependencies=current.dependencies
            if dependencies is None
            else tuple(sorted(dependencies)),
        )
        if (updated.title, updated.required_result, updated.dependencies) == (
            current.title,
            current.required_result,
            current.dependencies,
        ):
            return
        self.definitions = tuple(self.definitions) + (updated,)
        self.status = TaskStatus.PENDING
        self.current_attempt_number = None
        self.invalidated_reason = None
        self.cancel_monitors("Original task requirement changed")
        self.add_event(TaskDefinitionChanged(task_id=self.uid))

    def wait(self, condition: ExternalWait) -> None:
        """미해소 외부 대기를 이력에 추가하고 active에서 waiting으로 바꾼다.

        현재 시도 번호는 유지한다. 전달된 대기 값의 resolution이 None인지 확인하며
        외부 대상의 상태를 직접 조회하거나 감시를 시작하지 않는다.

        Args:
            condition: 대기 대상·해소 조건·후속 범위·관찰.

        Raises:
            InvalidTaskState: 활성 작업이 아니거나 이미 해소된 대기를 전달한 경우.
        """
        if self.status is not TaskStatus.ACTIVE or condition.resolution is not None:
            raise InvalidTaskState("Only an active attempt can enter an unresolved external wait")
        self.waits = tuple(self.waits) + (condition,)
        self.status = TaskStatus.WAITING

    def resume(self, resolution: str) -> None:
        """마지막 대기에 해소 관찰을 붙이고 waiting에서 active로 돌아간다.

        시도를 새로 만들지 않으며 앞선 대기 기록과 현재 시도 번호는 유지한다.

        Args:
            resolution: 해소됐다는 관찰 참조.

        Raises:
            InvalidTaskState: 외부 대기 상태가 아닌 경우.
            ValueError: 해소 관찰이 공백만 포함한 경우.
        """
        if not resolution.strip():
            raise ValueError("resolution must be non-empty")
        if self.status is not TaskStatus.WAITING:
            raise InvalidTaskState("Task is not waiting for an external dependency")
        self.waits = tuple(self.waits[:-1]) + (replace(self.waits[-1], resolution=resolution),)
        self.status = TaskStatus.ACTIVE
        self.cancel_monitors("Original external wait resolved")
        self.add_event(TaskResumed(task_id=self.uid))

    def invalidate(self, source: RequestSource, reason: str) -> None:
        """정정 출처를 새 개정에 연결하고 태스크를 invalidated로 바꾼다.

        현재 요구를 가리키는 같은 프로젝트의 정정 출처가 필요하다. 제목·결과·의존과
        과거 시도는 보존하고 현재 시도 연결만 해제한다. 외부 실행을 중단하지 않는다.

        Args:
            source: 현재 요구에 대응하는 실제 정정.
            reason: 무효화 이유.

        Raises:
            ValueError: 무효화 이유가 공백만 포함한 경우.
        """
        source.require_project(self.project_id)
        source.require_correction(self.definition.source_id)
        if not reason.strip():
            raise ValueError("reason must be non-empty")
        self.definitions = tuple(self.definitions) + (
            replace(self.definition, number=self.definition.number + 1, source_id=source.uid),
        )
        self.status = TaskStatus.INVALIDATED
        self.current_attempt_number = None
        self.invalidated_reason = reason
        self.cancel_monitors("Original task requirement changed")
        self.add_event(TaskDefinitionChanged(task_id=self.uid))

    def validate_dependencies(
        self, tasks: Sequence[Self], dependencies: Sequence[UUID] | None = None
    ) -> None:
        """현재 또는 제안한 의존을 프로젝트 그래프에 대조하여 중복·순환을 거부한다.

        목록에 없는 태스크 ID는 ContextNotFound로 거부한다. 호출자는 같은 프로젝트의
        전체 태스크를 제공해야 하며 이 메서드는 조회·저장이나 의존 목록 변경을 하지 않는다.

        Args:
            tasks: 같은 프로젝트에서 조회한 전체 현재 태스크.
            dependencies: 검증할 선행 작업이며 None이면 현재 정의의 의존 목록.

        Raises:
            ContextNotFound: 프로젝트에 없는 의존을 지정한 경우.
            InvalidTaskState: 중복·자기 의존·순환을 만들려는 경우.
        """
        dependencies = self.definition.dependencies if dependencies is None else dependencies
        graph = {task.uid: task.definition.dependencies for task in tasks}
        if len(set(dependencies)) != len(dependencies):
            raise InvalidTaskState("Duplicate dependency")
        if any(uid not in graph for uid in dependencies):
            raise ContextNotFound("Dependency does not belong to this project")
        pending = list(dependencies)
        visited: set[UUID] = set()
        while pending:
            uid = pending.pop()
            if uid == self.uid:
                raise InvalidTaskState("Task dependencies cannot contain a cycle")
            if uid not in visited:
                visited.add(uid)
                pending.extend(graph[uid])

    def transfer(self, source_session_id: UUID, target_session_id: UUID) -> None:
        """원 소유자가 일치할 때 현재 소유만 옮기고 과거 이력을 유지한다.

        Args:
            source_session_id: 인수 전 확인한 소유 세션.
            target_session_id: 같은 프로젝트로 확인된 후속 세션.

        Raises:
            ContextNotFound: 현재 소유자가 원 세션과 다른 경우.
        """
        if self.owner_session_id != source_session_id:
            raise ContextNotFound("Ownership changed before handoff")
        self.owner_session_id = target_session_id

    def require_delegatable(self) -> None:
        """종료한 요구를 새로운 수행 배정으로 다시 시작하지 못하게 한다.

        Raises:
            InvalidTaskState: 무효화됐거나 이미 성공한 작업인 경우.
        """
        if self.status in (TaskStatus.INVALIDATED, TaskStatus.SUCCEEDED):
            raise InvalidTaskState("Only unfinished current work can be delegated")

    def monitor(self, number: int) -> TaskMonitor:
        """태스크에 종속된 정확한 감시를 조회한다.

        Args:
            number: 태스크 안의 감시 순번.

        Returns:
            TaskMonitor: 관찰·사건·알림·자원 이력.

        Raises:
            ContextNotFound: 지정한 감시가 없는 경우.
        """
        for monitor in self.monitors:
            if monitor.number == number:
                return monitor
        raise ContextNotFound("Task monitor does not exist")

    def update_monitor(self, monitor: TaskMonitor) -> None:
        """기존 감시 하나만 교체하여 다른 대기와 사건을 보존한다.

        Args:
            monitor: 동일 순번의 최신 감시.
        """
        self.monitor(monitor.number)
        self.monitors = tuple(
            monitor if item.number == monitor.number else item for item in self.monitors
        )

    def register_monitor(
        self, execution_id: UUID, kind: MonitorKind, target: str, budget: int
    ) -> TaskMonitor:
        """현재 대기를 명시적으로 요청한 경우에만 유한한 감시를 등록한다.

        Args:
            execution_id: 같은 소유 세션에서 실제 확인한 실행.
            kind: 결정론적 외부 관찰 종류.
            target: 대기 대상과 정확히 같은 외부 주소.
            budget: 명시적으로 허용한 관찰 횟수.

        Returns:
            TaskMonitor: 원 요구·대기에 연결한 새 감시.

        Raises:
            InvalidTaskState: 대기 상태·대상이 다르거나 중복 감시를 만들려는 경우.
        """
        if self.status is not TaskStatus.WAITING or target != self.waits[-1].target:
            raise InvalidTaskState("Monitoring requires the exact requested external wait")
        if budget < 1 or any(
            item.wait_number == len(self.waits) and (item.active or item.poll_id is not None)
            for item in self.monitors
        ):
            raise InvalidTaskState("Monitoring requires positive budget and no existing resource")
        monitor = TaskMonitor(
            number=len(self.monitors) + 1,
            wait_number=len(self.waits),
            definition_number=self.definition.number,
            owner_execution_id=execution_id,
            kind=kind,
            target=target,
            remaining_polls=budget,
        )
        self.monitors = tuple(self.monitors) + (monitor,)
        return monitor

    def reconcile_monitor(self, number: int, *, cancelled: bool) -> TaskMonitor:
        """최신 요구·대기·실행 취소에 대조하여 오래된 감시를 중지한다.

        Args:
            number: 대조할 감시.
            cancelled: 현재 소유 실행에 취소가 기록됐는지 여부.

        Returns:
            TaskMonitor: 기존 상태 또는 새 관찰·알림을 금지한 감시.
        """
        monitor = self.monitor(number)
        if (
            cancelled
            or self.status is not TaskStatus.WAITING
            or monitor.definition_number != self.definition.number
            or monitor.wait_number != len(self.waits)
        ):
            monitor = monitor.cancel("Owner cancelled or original task dependency changed")
            self.update_monitor(monitor)
        return monitor

    def resolve_monitor(self, number: int, event_number: int, resolution: str) -> None:
        """현재 대기의 정확한 사건을 명시적으로 해소하며 작업 성공은 기록하지 않는다.

        Args:
            number: 현재 대기에 연결한 감시.
            event_number: 해소 판단에 실제 사용한 변화 사건.
            resolution: 원 해소 조건을 충족했다는 관찰 근거.

        Raises:
            InvalidTaskState: 현재 대기와 다른 감시나 이미 취소한 감시인 경우.
        """
        monitor = self.reconcile_monitor(number, cancelled=False)
        if not monitor.active:
            raise InvalidTaskState("Monitor cannot resolve a cancelled or changed dependency")
        event = monitor.event(event_number)
        if event.number != monitor.events[-1].number:
            raise InvalidTaskState("Only the latest observed event can resolve the current wait")
        self.resume(resolution)
        monitor = monitor.update_event(replace(event, acknowledged=True, resolved=True))
        self.update_monitor(monitor.cancel("External dependency explicitly resolved"))

    def cancel_monitors(self, reason: str, execution_id: UUID | None = None) -> None:
        """현재 범위의 새 감시·알림을 중지하고 미확인 자원은 보존한다.

        Args:
            reason: 요구 변경·해소·명시 취소 이유.
            execution_id: 지정하면 해당 실행이 소유한 감시만 취소함.
        """
        for monitor in self.monitors:
            if execution_id is not None and monitor.owner_execution_id != execution_id:
                continue
            self.update_monitor(monitor.cancel(reason))
