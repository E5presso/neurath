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

# Append-only source/definition/result history; tasks are the current projection.
sources = Table(
    "core_sources",
    metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("core_projects.id"), nullable=False),
    Column("session_id", String, ForeignKey("core_sessions.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("text", String, nullable=False),
    Column("reference", String, nullable=False),
    Column("author", String, nullable=False),
    Column("parent_id", String, ForeignKey("core_sources.id")),
    CheckConstraint("kind IN ('request','correction','context','question')"),
)
tasks = Table(
    "core_tasks",
    metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("core_projects.id"), nullable=False),
    Column("session_id", String, ForeignKey("core_sessions.id"), nullable=False),
    Column("title", String, nullable=False),
    Column("source_id", String, ForeignKey("core_sources.id"), nullable=False),
    Column("status", String, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("definition_revision", Integer, nullable=False),
    Column("reason", String, nullable=False),
    CheckConstraint("status IN ('pending','active','waiting','succeeded','failed','invalidated')"),
    CheckConstraint("revision >= 1 AND definition_revision >= 1"),
)
task_definitions = Table(
    "core_task_definitions",
    metadata,
    Column("task_id", String, ForeignKey("core_tasks.id"), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("source_id", String, ForeignKey("core_sources.id"), nullable=False),
    Column("title", String, nullable=False),
    Column("reason", String, nullable=False),
)
task_attempts = Table(
    "core_task_attempts",
    metadata,
    Column("id", String, primary_key=True),
    Column("task_id", String, ForeignKey("core_tasks.id"), nullable=False),
    Column("definition_revision", Integer, nullable=False),
    Column("state", String, nullable=False),
)
task_results = Table(
    "core_task_results",
    metadata,
    Column("id", String, primary_key=True),
    Column("attempt_id", String, ForeignKey("core_task_attempts.id"), nullable=False),
    Column("outcome", String, nullable=False),
    Column("summary", String, nullable=False),
    Column("references_json", String, nullable=False),
    Column("remaining", String, nullable=False),
    Column("applied", Integer, nullable=False),
    CheckConstraint("outcome IN ('submitted','succeeded','failed','partial')"),
)
task_dependencies = Table(
    "core_task_dependencies",
    metadata,
    Column("task_id", String, ForeignKey("core_tasks.id"), primary_key=True),
    Column("depends_on", String, ForeignKey("core_tasks.id"), primary_key=True),
    CheckConstraint("task_id != depends_on"),
)
task_waits = Table(
    "core_task_waits",
    metadata,
    Column("id", String, primary_key=True),
    Column("task_id", String, ForeignKey("core_tasks.id"), nullable=False),
    Column("definition_revision", Integer, nullable=False),
    Column("target", String, nullable=False),
    Column("evidence", String, nullable=False),
    Column("resolution_condition", String, nullable=False),
    Column("resolved_by", String),
)
