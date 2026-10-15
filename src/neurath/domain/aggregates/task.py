"""Task requirements and revision-aware transitions, independent of persistence."""

from dataclasses import dataclass, replace
from enum import StrEnum

from neurath.domain.errors import InvalidTaskOperation, RevisionConflict


class TaskStatus(StrEnum):
    """Keep actual success distinct from failure, cancellation and external waiting."""

    PENDING = "pending"
    ACTIVE = "active"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class ExternalWait:
    """An observable external dependency and the authorized continuation after it clears."""

    target: str
    condition: str
    continuation: str
    evidence: str

    def __post_init__(self) -> None:
        """Require a concrete target, release condition and bounded follow-up scope."""
        if not all(
            value.strip()
            for value in (self.target, self.condition, self.continuation, self.evidence)
        ):
            raise InvalidTaskOperation(
                "External wait requires target, condition, continuation and observation evidence"
            )


@dataclass(frozen=True)
class Task:
    """One current requirement with immutable provenance and explicit execution state."""

    id: str
    project_id: str
    session_id: str
    source_id: str
    title: str
    expected_outcome: str
    dependencies: tuple[str, ...] = ()
    follows_task_id: str | None = None
    correction_source_id: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    revision: int = 1
    definition_revision: int = 1
    active_attempt_id: str | None = None
    external_wait: ExternalWait | None = None
    remaining_work: str = ""

    def __post_init__(self) -> None:
        """Reject empty requirements and duplicate or self-referential dependencies."""
        if not self.title.strip() or not self.expected_outcome.strip():
            raise InvalidTaskOperation("Task requires a title and expected outcome")
        if self.id in self.dependencies or len(set(self.dependencies)) != len(self.dependencies):
            raise InvalidTaskOperation("Task dependencies must be unique and exclude itself")

    def check_revision(self, expected: int) -> None:
        """Fence updates made from an older view of this task."""
        if self.revision != expected:
            raise RevisionConflict("Task changed; read its current revision")

    def start(self, attempt_id: str, expected_revision: int) -> Task:
        """Start pending or failed work without erasing earlier failed attempts."""
        self.check_revision(expected_revision)
        if self.status not in (TaskStatus.PENDING, TaskStatus.FAILED):
            raise InvalidTaskOperation("Only pending or failed work can start")
        return replace(
            self,
            status=TaskStatus.ACTIVE,
            revision=self.revision + 1,
            active_attempt_id=attempt_id,
            remaining_work="",
        )

    def correct(
        self,
        source_id: str,
        title: str,
        outcome: str,
        dependencies: tuple[str, ...],
        expected_revision: int,
    ) -> Task:
        """Create a new definition while leaving old attempts available for late reports."""
        self.check_revision(expected_revision)
        return replace(
            self,
            title=title,
            expected_outcome=outcome,
            dependencies=dependencies,
            correction_source_id=source_id,
            status=TaskStatus.PENDING,
            revision=self.revision + 1,
            definition_revision=self.definition_revision + 1,
            active_attempt_id=None,
            external_wait=None,
            remaining_work="",
        )

    def invalidate(self, source_id: str, reason: str, expected_revision: int) -> Task:
        """Apply an attributed cancellation without claiming that execution was stopped."""
        self.check_revision(expected_revision)
        if not reason.strip():
            raise InvalidTaskOperation("Invalidation requires a reason")
        return replace(
            self,
            correction_source_id=source_id,
            status=TaskStatus.INVALIDATED,
            revision=self.revision + 1,
            definition_revision=self.definition_revision + 1,
            active_attempt_id=None,
            external_wait=None,
            remaining_work=reason,
        )

    def wait(self, dependency: ExternalWait, expected_revision: int) -> Task:
        """Suspend only unfinished work against an explicit external dependency."""
        self.check_revision(expected_revision)
        if self.status not in (TaskStatus.PENDING, TaskStatus.ACTIVE, TaskStatus.FAILED):
            raise InvalidTaskOperation("Only unfinished work can wait")
        return replace(
            self, status=TaskStatus.WAITING, external_wait=dependency, revision=self.revision + 1
        )

    def resume(self, evidence: str, expected_revision: int) -> Task:
        """Release an observed external wait, retaining any already running attempt."""
        self.check_revision(expected_revision)
        if self.status is not TaskStatus.WAITING or not evidence.strip():
            raise InvalidTaskOperation("Resume requires a waiting task and release evidence")
        status = TaskStatus.ACTIVE if self.active_attempt_id else TaskStatus.PENDING
        return replace(self, status=status, external_wait=None, revision=self.revision + 1)

    def apply_result(
        self, attempt_id: str, definition_revision: int, succeeded: bool, remaining_work: str
    ) -> Task:
        """Accept only the current attempt; stale reports cannot close a newer requirement."""
        if self.definition_revision != definition_revision or self.active_attempt_id != attempt_id:
            return self
        if self.status not in (TaskStatus.ACTIVE, TaskStatus.WAITING):
            return self
        return replace(
            self,
            status=TaskStatus.SUCCEEDED if succeeded else TaskStatus.FAILED,
            revision=self.revision + 1,
            active_attempt_id=None,
            external_wait=None,
            remaining_work=remaining_work,
        )
