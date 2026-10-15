"""Declarative TaskChange persistence with explicit field-by-field domain conversion."""

from typing import Self

from sqlalchemy import (
    JSON,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.task import ExternalWait, Task, TaskStatus
from neurath.domain.aggregates.task_change import TaskAction, TaskChange
from neurath.infrastructure.models.base import DatabaseModel


class ChangeModel(DatabaseModel):
    """Store scoped TaskChange records independently of their request's ORM lifecycle."""

    __tablename__ = "task_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        ForeignKeyConstraint(
            ["project_id", "session_id", "task_id"],
            ["tasks.project_id", "tasks.session_id", "tasks.id"],
        ),
        UniqueConstraint("task_id", "revision", name="uq_task_history_revision"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    expected_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    dependencies: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    follows_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    correction_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    active_attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    wait_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    wait_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    wait_continuation: Mapped[str | None] = mapped_column(Text, nullable=True)
    wait_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    remaining_work: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    @classmethod
    def from_domain(cls, value: TaskChange) -> Self:
        """Map each domain field explicitly into a new declarative record."""
        return cls(
            id=value.id,
            task_id=value.task.id,
            project_id=value.task.project_id,
            session_id=value.task.session_id,
            source_id=value.task.source_id,
            title=value.task.title,
            expected_outcome=value.task.expected_outcome,
            dependencies=list(value.task.dependencies),
            follows_task_id=value.task.follows_task_id,
            correction_source_id=value.task.correction_source_id,
            status=value.task.status.value,
            revision=value.task.revision,
            definition_revision=value.task.definition_revision,
            active_attempt_id=value.task.active_attempt_id,
            wait_target=value.task.external_wait.target if value.task.external_wait else None,
            wait_condition=value.task.external_wait.condition if value.task.external_wait else None,
            wait_continuation=value.task.external_wait.continuation
            if value.task.external_wait
            else None,
            wait_evidence=value.task.external_wait.evidence if value.task.external_wait else None,
            remaining_work=value.task.remaining_work,
            action=value.action.value,
            reason=value.reason,
        )

    def to_domain(self) -> TaskChange:
        """Return an immutable domain value detached from the ORM session."""
        return TaskChange(
            id=self.id,
            action=TaskAction(self.action),
            reason=self.reason,
            task=Task(
                id=self.task_id,
                project_id=self.project_id,
                session_id=self.session_id,
                source_id=self.source_id,
                title=self.title,
                expected_outcome=self.expected_outcome,
                dependencies=tuple(self.dependencies),
                follows_task_id=self.follows_task_id,
                correction_source_id=self.correction_source_id,
                status=TaskStatus(self.status),
                revision=self.revision,
                definition_revision=self.definition_revision,
                active_attempt_id=self.active_attempt_id,
                remaining_work=self.remaining_work,
                external_wait=self._external_wait(),
            ),
        )

    def _external_wait(self) -> ExternalWait | None:
        """Reconstruct the explicit dependency only when all persisted fields exist."""
        if (
            self.wait_target is None
            or self.wait_condition is None
            or self.wait_continuation is None
            or self.wait_evidence is None
        ):
            return None
        return ExternalWait(
            self.wait_target, self.wait_condition, self.wait_continuation, self.wait_evidence
        )
