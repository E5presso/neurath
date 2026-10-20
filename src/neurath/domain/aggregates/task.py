"""태스크가 요구 개정·실행 시도·외부 대기 이력을 한 원장에서 관리한다."""

from collections.abc import Sequence
from dataclasses import replace
from typing import Self, override
from uuid import uuid4

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.aggregates.request_source import RequestSource
from neurath.domain.errors import ContextNotFound, InvalidTaskState, RevisionConflict
from neurath.domain.task_records import (
    ExternalWait,
    Outcome,
    SubmittedResult,
    TaskAttempt,
    TaskDefinition,
    TaskResult,
    TaskStatus,
)


@mutable
class Task(AbstractAggregateRoot[str]):
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
    """

    project_id: str
    owner_session_id: str
    definitions: Sequence[TaskDefinition]
    status: TaskStatus = TaskStatus.PENDING
    attempts: Sequence[TaskAttempt] = ()
    waits: Sequence[ExternalWait] = ()
    current_attempt_number: int | None = None
    follow_up_of: str | None = None
    invalidated_reason: str | None = None
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> str:
        """새 태스크 식별자를 생성한다.

        Returns:
            str: 새 작업의 안정적인 식별자.
        """
        return str(uuid4())

    @classmethod
    def create(
        cls,
        project_id: str,
        session_id: str,
        source: RequestSource,
        title: str,
        required_result: str,
        dependencies: Sequence[str] = (),
        follow_up_of: str | None = None,
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
            TaskDefinition: 가장 최근에 실제 정정한 요구.
        """
        return self.definitions[-1]

    def require_scope(self, project_id: str, session_id: str) -> None:
        """소유권을 이전하지 않고 현재 프로젝트·세션 범위를 검사한다.

        Args:
            project_id: 요청 프로젝트.
            session_id: 요청 세션.

        Raises:
            ContextNotFound: 요청 범위와 소유 범위가 다른 경우.
        """
        if self.project_id != project_id or self.owner_session_id != session_id:
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
        """독립 작업과 실제 성공한 의존을 기준으로 실행 가능 여부를 계산한다.

        Args:
            tasks: 같은 프로젝트의 현재 전체 작업.

        Returns:
            bool: 새 시도를 시작할 수 있는지 여부.
        """
        statuses = {task.uid: task.status for task in tasks}
        return self.status in (TaskStatus.PENDING, TaskStatus.FAILED) and all(
            statuses.get(uid) is TaskStatus.SUCCEEDED for uid in self.definition.dependencies
        )

    def start(self, tasks: Sequence[Self]) -> None:
        """현재 정의를 고정한 시도를 만들며 이전 외부 동작을 재제출하지 않는다.

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
        """후보 자료를 보존하되 태스크를 성공 처리하지 않는다.

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
        """관찰 결과를 보존하고 현재 요구의 시도인 경우에만 상태를 갱신한다.

        Args:
            number: 결과를 보고할 시도.
            result: 실제 관찰 및 남은 일.
            expected_revision: 호출자가 관찰한 태스크 버전.

        Raises:
            InvalidTaskState: 이미 보존한 확정 결과를 바꾸려 한 경우.
        """
        attempt = self.attempt(number)
        if attempt.result is not None:
            if attempt.result != result:
                raise InvalidTaskState("A recorded result cannot be overwritten")
            return
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

    def correct(
        self,
        source: RequestSource,
        title: str | None = None,
        required_result: str | None = None,
        dependencies: Sequence[str] | None = None,
    ) -> None:
        """지정한 필드만 정정하고 과거 정의·시도·결과를 유지한다.

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

    def wait(self, condition: ExternalWait) -> None:
        """현재 시도의 실제 외부 의존을 기록하고 독립 작업은 유지한다.

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
        """외부 의존 해소를 보존하고 같은 시도를 이어간다.

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

    def invalidate(self, source: RequestSource, reason: str) -> None:
        """실제 정정으로 무효화하되 성공으로 취급하거나 기록을 삭제하지 않는다.

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

    def validate_dependencies(
        self, tasks: Sequence[Self], dependencies: Sequence[str] | None = None
    ) -> None:
        """기존 프로젝트 그래프에 추가할 의존의 범위와 순환을 검사한다.

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
        visited: set[str] = set()
        while pending:
            uid = pending.pop()
            if uid == self.uid:
                raise InvalidTaskState("Task dependencies cannot contain a cycle")
            if uid not in visited:
                visited.add(uid)
                pending.extend(graph[uid])
