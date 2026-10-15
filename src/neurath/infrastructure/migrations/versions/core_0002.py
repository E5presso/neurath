"""Add attributed task requirements, execution attempts and immutable history."""

import sqlalchemy as sa
from alembic import op

revision: str = "core_0002"
down_revision: str | None = "core_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Extend the identity schema without altering existing projects or sessions."""
    op.create_table(
        "task_sources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("corrects_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        sa.UniqueConstraint("project_id", "id", name="uq_task_source_scope"),
        sa.ForeignKeyConstraint(
            ["project_id", "corrects_id"],
            ["task_sources.project_id", "task_sources.id"],
        ),
        sa.CheckConstraint(
            "kind IN ('instruction', 'correction', 'status_question', 'summary')",
            name="source_kind",
        ),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("expected_outcome", sa.Text(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("follows_task_id", sa.String(), nullable=True),
        sa.Column("correction_source_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("definition_revision", sa.Integer(), nullable=False),
        sa.Column("active_attempt_id", sa.String(), nullable=True),
        sa.Column("wait_target", sa.Text(), nullable=True),
        sa.Column("wait_condition", sa.Text(), nullable=True),
        sa.Column("wait_continuation", sa.Text(), nullable=True),
        sa.Column("wait_evidence", sa.Text(), nullable=True),
        sa.Column("remaining_work", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        sa.UniqueConstraint("project_id", "session_id", "id", name="uq_task_scope"),
        sa.ForeignKeyConstraint(
            ["project_id", "source_id"],
            ["task_sources.project_id", "task_sources.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "correction_source_id"],
            ["task_sources.project_id", "task_sources.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id", "follows_task_id"],
            ["tasks.project_id", "tasks.session_id", "tasks.id"],
        ),
        sa.CheckConstraint(
            "revision >= 1 AND definition_revision >= 1", name="task_revisions_positive"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'waiting', 'succeeded', 'failed', 'invalidated')",
            name="task_status",
        ),
    )
    op.create_table(
        "task_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("definition_revision", sa.Integer(), nullable=False),
        sa.Column("executor", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("remaining_work", sa.Text(), nullable=False),
        sa.Column("submission_summary", sa.Text(), nullable=False),
        sa.Column("submission_evidence", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id", "task_id"],
            ["tasks.project_id", "tasks.session_id", "tasks.id"],
        ),
        sa.CheckConstraint("definition_revision >= 1", name="attempt_revision_positive"),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('succeeded', 'failed', 'partial')",
            name="attempt_outcome",
        ),
    )
    op.create_table(
        "task_changes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("expected_outcome", sa.Text(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("follows_task_id", sa.String(), nullable=True),
        sa.Column("correction_source_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("definition_revision", sa.Integer(), nullable=False),
        sa.Column("active_attempt_id", sa.String(), nullable=True),
        sa.Column("wait_target", sa.Text(), nullable=True),
        sa.Column("wait_condition", sa.Text(), nullable=True),
        sa.Column("wait_continuation", sa.Text(), nullable=True),
        sa.Column("wait_evidence", sa.Text(), nullable=True),
        sa.Column("remaining_work", sa.Text(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id", "task_id"],
            ["tasks.project_id", "tasks.session_id", "tasks.id"],
        ),
        sa.UniqueConstraint("task_id", "revision", name="uq_task_history_revision"),
    )


def downgrade() -> None:
    """Refuse destructive removal of original sources and unfinished task history."""
    raise RuntimeError("Task history must be retained; destructive downgrade is unsupported")
