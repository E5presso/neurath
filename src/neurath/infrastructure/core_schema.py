"""New core schema; legacy runtime metadata is deliberately not imported."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

metadata = MetaData()
projects = Table(
    "core_projects",
    metadata,
    Column("id", String, primary_key=True),
    Column("root_path", String, nullable=False),
)
project_locations = Table(
    "core_project_locations",
    metadata,
    Column("kind", String, primary_key=True),
    Column("path", String, primary_key=True),
    Column("project_id", String, ForeignKey("core_projects.id"), nullable=False),
    CheckConstraint("kind IN ('git', 'folder')", name="location_kind"),
)
sessions = Table(
    "core_sessions",
    metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("core_projects.id"), nullable=False),
    Column("provider", String, nullable=False),
    Column("host_session_id", String, nullable=False),
    Column("working_directory", String, nullable=False),
    Column("revision", Integer, nullable=False),
    UniqueConstraint("project_id", "provider", "host_session_id", name="uq_core_host_session"),
    UniqueConstraint("project_id", "id", name="uq_core_session_scope"),
    CheckConstraint("revision >= 1", name="session_revision_positive"),
)
