"""Declarative host-session mapping with explicit named conversions."""

from typing import Self

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.session import HostSession
from neurath.infrastructure.models.base import DatabaseModel


class SessionModel(DatabaseModel):
    """Store the scoped native identifier and optimistic working-directory revision."""

    __tablename__ = "core_sessions"
    __table_args__ = (
        UniqueConstraint("project_id", "provider", "host_session_id", name="uq_core_host_session"),
        UniqueConstraint("project_id", "id", name="uq_core_session_scope"),
        CheckConstraint("revision >= 1", name="session_revision_positive"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("core_projects.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    host_session_id: Mapped[str] = mapped_column(String, nullable=False)
    working_directory: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    @classmethod
    def from_domain(cls, session: HostSession) -> Self:
        """Map every host-session field explicitly into a new ORM record."""
        return cls(
            id=session.id,
            project_id=session.project_id,
            provider=session.provider,
            host_session_id=session.host_session_id,
            working_directory=session.working_directory,
            revision=session.revision,
        )

    def to_domain(self) -> HostSession:
        """Detach the persisted observation from the ORM Session lifecycle."""
        return HostSession(
            id=self.id,
            project_id=self.project_id,
            provider=self.provider,
            host_session_id=self.host_session_id,
            working_directory=self.working_directory,
            revision=self.revision,
        )
