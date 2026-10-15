"""Declarative Task persistence with explicit field-by-field domain conversion."""

from typing import Self

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.task import ExternalWait, Task, TaskStatus
from neurath.infrastructure.models.base import DatabaseModel


class TaskModel(DatabaseModel):
    """Store scoped Task records independently of their request's ORM lifecycle."""

    __tablename__ = "tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        UniqueConstraint("project_id", "session_id", "id", name="uq_task_scope"),
        ForeignKeyConstraint(
            ["project_id", "source_id"],
            ["task_sources.project_id", "task_sources.id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "correction_source_id"],
            ["task_sources.project_id", "task_sources.id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "session_id", "follows_task_id"],
            ["tasks.project_id", "tasks.session_id", "tasks.id"],
        ),
        CheckConstraint(
            "revision >= 1 AND definition_revision >= 1", name="task_revisions_positive"
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'waiting', 'succeeded', 'failed', 'invalidated')",
            name="task_status",
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
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

    @classmethod
    def from_domain(cls, value: Task) -> Self:
        """Map each domain field explicitly into a new declarative record."""
        return cls(
            id=value.id,
            project_id=value.project_id,
            session_id=value.session_id,
            source_id=value.source_id,
            title=value.title,
            expected_outcome=value.expected_outcome,
            dependencies=list(value.dependencies),
            follows_task_id=value.follows_task_id,
            correction_source_id=value.correction_source_id,
            status=value.status.value,
            revision=value.revision,
            definition_revision=value.definition_revision,
            active_attempt_id=value.active_attempt_id,
            wait_target=value.external_wait.target if value.external_wait else None,
            wait_condition=value.external_wait.condition if value.external_wait else None,
            wait_continuation=value.external_wait.continuation if value.external_wait else None,
            wait_evidence=value.external_wait.evidence if value.external_wait else None,
            remaining_work=value.remaining_work,
        )

    def to_domain(self) -> Task:
        """Return an immutable domain value detached from the ORM session."""
        return Task(
            id=self.id,
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
