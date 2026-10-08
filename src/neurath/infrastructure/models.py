"""Explicit SQLAlchemy persistence mappings, separate from domain objects."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RecordRow(Base):
    __tablename__ = "records"
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(200), index=True)
    task_id: Mapped[str | None] = mapped_column(String(200), index=True)
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (CheckConstraint("revision >= 0"),)


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scope_version: Mapped[int] = mapped_column(Integer, nullable=False)
    wait_reason: Mapped[str] = mapped_column(Text, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (CheckConstraint("revision >= 0"), CheckConstraint("scope_version >= 1"))


class CriterionRow(Base):
    __tablename__ = "task_criteria"
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    satisfied: Mapped[bool] = mapped_column(Boolean, nullable=False)


class CriterionEvidenceRow(Base):
    __tablename__ = "criterion_evidence"
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    criterion_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(200), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "criterion_id"],
            ["task_criteria.task_id", "task_criteria.id"],
            ondelete="CASCADE",
        ),
    )


class PhaseRow(Base):
    __tablename__ = "task_phases"
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class TaskDelegationRow(Base):
    __tablename__ = "task_delegations"
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    delegation_id: Mapped[str] = mapped_column(String(200), nullable=False)


class ArchiveRow(Base):
    __tablename__ = "source_archives"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class LeaseRow(Base):
    __tablename__ = "leases"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __table_args__ = (CheckConstraint("revision >= 0"), CheckConstraint("generation >= 1"))


class PhaseEvidenceRow(Base):
    __tablename__ = "phase_evidence"
    task_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    phase_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(200), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "phase_id"], ["task_phases.task_id", "task_phases.id"], ondelete="CASCADE"
        ),
    )


class TaskSourceRow(Base):
    __tablename__ = "task_sources"
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)


class ArchiveChunkRow(Base):
    __tablename__ = "source_archive_chunks"
    archive_id: Mapped[str] = mapped_column(ForeignKey("source_archives.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class EntityVersionRow(Base):
    __tablename__ = "entity_versions"
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
