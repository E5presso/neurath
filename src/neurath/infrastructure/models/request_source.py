"""Declarative RequestSource persistence with explicit field-by-field domain conversion."""

from typing import Self

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.request_source import RequestSource, SourceKind
from neurath.infrastructure.models.base import DatabaseModel


class SourceModel(DatabaseModel):
    """Store scoped RequestSource records independently of their request's ORM lifecycle."""

    __tablename__ = "task_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        UniqueConstraint("project_id", "id", name="uq_task_source_scope"),
        ForeignKeyConstraint(
            ["project_id", "corrects_id"],
            ["task_sources.project_id", "task_sources.id"],
        ),
        CheckConstraint(
            "kind IN ('instruction', 'correction', 'status_question', 'summary')",
            name="source_kind",
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    corrects_id: Mapped[str | None] = mapped_column(String, nullable=True)

    @classmethod
    def from_domain(cls, value: RequestSource) -> Self:
        """Map each domain field explicitly into a new declarative record."""
        return cls(
            id=value.id,
            project_id=value.project_id,
            session_id=value.session_id,
            kind=value.kind.value,
            author=value.author,
            reference=value.reference,
            text=value.text,
            corrects_id=value.corrects_id,
        )

    def to_domain(self) -> RequestSource:
        """Return an immutable domain value detached from the ORM session."""
        return RequestSource(
            id=self.id,
            project_id=self.project_id,
            session_id=self.session_id,
            kind=SourceKind(self.kind),
            author=self.author,
            reference=self.reference,
            text=self.text,
            corrects_id=self.corrects_id,
        )
