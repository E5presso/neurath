"""Task ledger, original sources and persisted result history."""

import sqlalchemy as sa
from alembic import op

revision = "core_0002"
down_revision = "core_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "core_sources",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("core_projects.id"), nullable=False),
        sa.Column("session_id", sa.String, sa.ForeignKey("core_sessions.id"), nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("text", sa.String, nullable=False),
        sa.Column("reference", sa.String, nullable=False),
        sa.Column("author", sa.String, nullable=False),
        sa.Column("parent_id", sa.String, sa.ForeignKey("core_sources.id")),
        sa.CheckConstraint("kind IN ('request','correction','context','question')"),
    )
    op.create_table(
        "core_tasks",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("core_projects.id"), nullable=False),
        sa.Column("session_id", sa.String, sa.ForeignKey("core_sessions.id"), nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("source_id", sa.String, sa.ForeignKey("core_sources.id"), nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("definition_revision", sa.Integer, nullable=False),
        sa.Column("reason", sa.String, nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','active','waiting','succeeded','failed','invalidated')"
        ),
        sa.CheckConstraint("revision >= 1 AND definition_revision >= 1"),
    )
    op.create_table(
        "core_task_definitions",
        sa.Column("task_id", sa.String, sa.ForeignKey("core_tasks.id"), primary_key=True),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.String, sa.ForeignKey("core_sources.id"), nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("reason", sa.String, nullable=False),
    )
    op.create_table(
        "core_task_attempts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("task_id", sa.String, sa.ForeignKey("core_tasks.id"), nullable=False),
        sa.Column("definition_revision", sa.Integer, nullable=False),
        sa.Column("state", sa.String, nullable=False),
    )
    op.create_table(
        "core_task_results",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("attempt_id", sa.String, sa.ForeignKey("core_task_attempts.id"), nullable=False),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("summary", sa.String, nullable=False),
        sa.Column("references_json", sa.String, nullable=False),
        sa.Column("remaining", sa.String, nullable=False),
        sa.Column("applied", sa.Integer, nullable=False),
        sa.CheckConstraint("outcome IN ('submitted','succeeded','failed','partial')"),
    )
    op.create_table(
        "core_task_dependencies",
        sa.Column("task_id", sa.String, sa.ForeignKey("core_tasks.id"), primary_key=True),
        sa.Column("depends_on", sa.String, sa.ForeignKey("core_tasks.id"), primary_key=True),
        sa.CheckConstraint("task_id != depends_on"),
    )
    op.create_table(
        "core_task_waits",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("task_id", sa.String, sa.ForeignKey("core_tasks.id"), nullable=False),
        sa.Column("definition_revision", sa.Integer, nullable=False),
        sa.Column("target", sa.String, nullable=False),
        sa.Column("evidence", sa.String, nullable=False),
        sa.Column("resolution_condition", sa.String, nullable=False),
        sa.Column("resolved_by", sa.String),
    )


def downgrade():
    raise RuntimeError("Destructive task ledger downgrade is unsupported; preserve task history")
