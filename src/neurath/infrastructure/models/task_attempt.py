"""Declarative TaskAttempt persistence with explicit field-by-field domain conversion."""

from typing import Self

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.task_attempt import AttemptOutcome, TaskAttempt
from neurath.infrastructure.models.base import DatabaseModel


class AttemptModel(DatabaseModel):
    """Store scoped TaskAttempt records independently of their request's ORM lifecycle."""

    __tablename__ = "task_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        ForeignKeyConstraint(
            ["project_id", "session_id", "task_id"],
            ["tasks.project_id", "tasks.session_id", "tasks.id"],
        ),
        CheckConstraint("definition_revision >= 1", name="attempt_revision_positive"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('succeeded', 'failed', 'partial')",
            name="attempt_outcome",
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    definition_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    executor: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    remaining_work: Mapped[str] = mapped_column(Text, nullable=False)
    submission_summary: Mapped[str] = mapped_column(Text, nullable=False)
    submission_evidence: Mapped[str] = mapped_column(Text, nullable=False)

    @classmethod
    def from_domain(cls, value: TaskAttempt) -> Self:
        """Map each domain field explicitly into a new declarative record."""
        return cls(
            id=value.id,
            project_id=value.project_id,
            session_id=value.session_id,
            task_id=value.task_id,
            definition_revision=value.definition_revision,
            executor=value.executor,
            outcome=value.outcome.value if value.outcome is not None else None,
            summary=value.summary,
            evidence=value.evidence,
            remaining_work=value.remaining_work,
            submission_summary=value.submission_summary,
            submission_evidence=value.submission_evidence,
        )

    def to_domain(self) -> TaskAttempt:
        """Return an immutable domain value detached from the ORM session."""
        return TaskAttempt(
            id=self.id,
            project_id=self.project_id,
            session_id=self.session_id,
            task_id=self.task_id,
            definition_revision=self.definition_revision,
            executor=self.executor,
            outcome=AttemptOutcome(self.outcome) if self.outcome is not None else None,
            summary=self.summary,
            evidence=self.evidence,
            remaining_work=self.remaining_work,
            submission_summary=self.submission_summary,
            submission_evidence=self.submission_evidence,
        )
