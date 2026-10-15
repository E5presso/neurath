"""Versioned workflow definitions, execution attempts and deduplicated results."""

import sqlalchemy as sa
from alembic import op

revision = "core_0003"
down_revision = "core_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "core_workflow_runs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("core_projects.id"), nullable=False),
        sa.Column("task_id", sa.String, sa.ForeignKey("core_tasks.id"), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("payload", sa.String, nullable=False),
    )
    op.create_table(
        "core_workflow_definitions",
        sa.Column("run_id", sa.String, sa.ForeignKey("core_workflow_runs.id"), primary_key=True),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("payload", sa.String, nullable=False),
        sa.Column("reason", sa.String, nullable=False),
        sa.Column("source_id", sa.String, sa.ForeignKey("core_sources.id")),
    )
    op.create_table(
        "core_workflow_attempts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("run_id", sa.String, sa.ForeignKey("core_workflow_runs.id"), nullable=False),
        sa.Column("payload", sa.String, nullable=False),
    )
    op.create_table(
        "core_workflow_results",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "attempt_id", sa.String, sa.ForeignKey("core_workflow_attempts.id"), nullable=False
        ),
        sa.Column("event_key", sa.String, nullable=False),
        sa.Column("payload", sa.String, nullable=False),
        sa.Column("applied", sa.Integer, nullable=False),
        sa.UniqueConstraint("attempt_id", "event_key", name="uq_core_workflow_result"),
    )


def downgrade():
    raise RuntimeError("Destructive workflow downgrade is unsupported; preserve execution history")
