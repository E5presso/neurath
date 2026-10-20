"""원장에서 직접 생성하는 불변 출처·태스크·TODO 응답이다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from neurath.domain.aggregates.request_source import RequestSource, SourceKind
from neurath.domain.aggregates.task import Task
from neurath.domain.task_records import ExternalWait, TaskAttempt, TaskDefinition, TaskStatus


@dataclass(frozen=True)
class SourceDTO:
    """원문과 최초 발신 맥락을 반환한다.

    Attributes:
        id: 출처 식별자.
        project_id: 원래 프로젝트.
        session_id: 최초 기록 세션.
        kind: 원문의 용도.
        body: 보존한 원문.
        author: 제공된 발신 맥락.
        reference: 티켓·문서·호스트 사건 참조.
        corrects_id: 정정 대상 출처.
    """

    id: str
    project_id: str
    session_id: str
    kind: SourceKind
    body: str
    author: str | None
    reference: str | None
    corrects_id: str | None

    @classmethod
    def from_entity(cls, source: RequestSource) -> Self:
        """출처를 불변 응답으로 복사한다.

        Args:
            source: 저장된 원문.

        Returns:
            Self: 원본을 덮어쓰지 않는 응답.
        """
        return cls(
            source.uid,
            source.project_id,
            source.session_id,
            source.kind,
            source.body,
            source.author,
            source.reference,
            source.corrects_id,
        )


@dataclass(frozen=True)
class TaskDTO:
    """태스크의 현재 요구·상태·시도를 그대로 표시한다.

    Attributes:
        id: 태스크 식별자.
        project_id: 프로젝트.
        owner_session_id: 작업 소유 세션.
        revision: 현재 저장 버전.
        definition: 현재 원문 개정과 달성할 결과.
        status: 현재 상태.
        attempt: 현재 요구의 시도와 제출·관찰 결과.
        external_wait: 현재 외부 의존.
        follow_up_of: 미달 요구의 원래 태스크.
        invalidated_reason: 실제 정정에 따른 무효화 이유.
    """

    id: str
    project_id: str
    owner_session_id: str
    revision: int
    definition: TaskDefinition
    status: TaskStatus
    attempt: TaskAttempt | None
    external_wait: ExternalWait | None
    follow_up_of: str | None
    invalidated_reason: str | None

    @classmethod
    def from_entity(cls, task: Task) -> Self:
        """제출과 성공을 합치지 않고 현재 태스크 상태를 복사한다.

        Args:
            task: 현재 태스크 도메인 객체.

        Returns:
            Self: ORM이나 가변 엔티티와 독립적인 응답.
        """
        attempt = None
        if task.current_attempt_number is not None:
            attempt = task.attempt(task.current_attempt_number)
        wait = None
        if task.status is TaskStatus.WAITING:
            wait = task.waits[-1]
        return cls(
            task.uid,
            task.project_id,
            task.owner_session_id,
            task.revision,
            task.definition,
            task.status,
            attempt,
            wait,
            task.follow_up_of,
            task.invalidated_reason,
        )


@dataclass(frozen=True)
class TaskHistoryDTO:
    """현재 표시와 보존된 과거 정의·시도·대기를 함께 조회한다.

    Attributes:
        task: 현재 요구와 상태.
        definitions: 과거 원문과 모든 정정.
        attempts: 실패·부분 수행·늦은 보고를 포함한 시도.
        waits: 대기·해소 관찰 이력.
    """

    task: TaskDTO
    definitions: Sequence[TaskDefinition]
    attempts: Sequence[TaskAttempt]
    waits: Sequence[ExternalWait]

    @classmethod
    def from_entity(cls, task: Task) -> Self:
        """현재 상태와 불변 역사 기록을 반환한다.

        Args:
            task: 조회한 태스크.

        Returns:
            Self: 재개와 회고에 사용할 실제 이력.
        """
        return cls(TaskDTO.from_entity(task), task.definitions, task.attempts, task.waits)


@dataclass(frozen=True)
class TaskBoardDTO:
    """전체 현재 목록을 TODO로 투영하며 별도 완료 원장을 만들지 않는다.

    Attributes:
        tasks: 해당 세션의 전체 현재 태스크.
        ready_task_ids: 독립적으로 시작 가능한 작업들.
        all_terminal: 비어 있지 않은 목록의 모든 상태가 종료인지 여부.
        all_succeeded: 비어 있지 않은 목록의 모든 요구가 성공했는지 여부.
    """

    tasks: Sequence[TaskDTO]
    ready_task_ids: Sequence[str]
    all_terminal: bool
    all_succeeded: bool

    @classmethod
    def from_entities(cls, tasks: Sequence[Task], session_id: str) -> Self:
        """현재 원장과 같은 태스크 목록에서 상태와 준비 여부를 계산한다.

        Args:
            tasks: 의존 관계를 포함한 프로젝트의 전체 작업.
            session_id: 현재 TODO를 표시할 소유 세션.

        Returns:
            Self: 실패·무효·대기를 구분하는 원장의 표시.
        """
        selected = tuple(task for task in tasks if task.owner_session_id == session_id)
        terminal = (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.INVALIDATED)
        return cls(
            tuple(TaskDTO.from_entity(task) for task in selected),
            tuple(task.uid for task in selected if task.ready(tasks)),
            bool(selected) and all(task.status in terminal for task in selected),
            bool(selected) and all(task.status is TaskStatus.SUCCEEDED for task in selected),
        )
