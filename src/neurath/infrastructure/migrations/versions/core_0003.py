"""기존 프로젝트·세션과 원본 자료를 보존하며 태스크 원장을 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0003"
down_revision = "core_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """명시적 이전에서만 출처와 태스크의 소유 이력을 추가한다."""
    op.create_table(
        "core_request_sources",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("version", sa.Uuid(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("project_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("session_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("kind", sa.String(), primary_key=False, nullable=False),
        sa.Column("body", sa.String(), primary_key=False, nullable=False),
        sa.Column("author", sa.String(), primary_key=False, nullable=True),
        sa.Column("reference", sa.String(), primary_key=False, nullable=True),
        sa.Column("corrects_id", sa.String(), primary_key=False, nullable=True),
        sa.CheckConstraint(
            "kind IN ('prompt','ticket','spec','correction','status','summary')", name="source_kind"
        ),
        sa.CheckConstraint("revision >= 1", name="source_revision_positive"),
        sa.ForeignKeyConstraint(["project_id"], ["core_projects.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        sa.ForeignKeyConstraint(["corrects_id"], ["core_request_sources.id"]),
        sa.UniqueConstraint("project_id", "id", name="uq_core_source_scope"),
    )
    op.create_table(
        "core_tasks",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("version", sa.Uuid(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("project_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("owner_session_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(), primary_key=False, nullable=False),
        sa.Column("current_attempt_number", sa.Integer(), primary_key=False, nullable=True),
        sa.Column("follow_up_of", sa.String(), primary_key=False, nullable=True),
        sa.Column("invalidated_reason", sa.String(), primary_key=False, nullable=True),
        sa.CheckConstraint("revision >= 1", name="task_revision_positive"),
        sa.CheckConstraint(
            "status IN ('pending','active','waiting','succeeded','failed','invalidated')",
            name="task_status",
        ),
        sa.ForeignKeyConstraint(["follow_up_of"], ["core_tasks.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["core_projects.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "owner_session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        sa.UniqueConstraint("project_id", "id", name="uq_core_task_scope"),
    )
    op.create_table(
        "core_task_definitions",
        sa.Column("task_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("number", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("source_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("title", sa.String(), primary_key=False, nullable=False),
        sa.Column("required_result", sa.String(), primary_key=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "source_id"],
            ["core_request_sources.project_id", "core_request_sources.id"],
        ),
        sa.ForeignKeyConstraint(["task_id"], ["core_tasks.id"]),
    )
    op.create_table(
        "core_task_dependencies",
        sa.Column("task_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("definition_number", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("prerequisite_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(), primary_key=False, nullable=False),
        sa.CheckConstraint("task_id != prerequisite_id", name="task_not_self_dependent"),
        sa.ForeignKeyConstraint(
            ["project_id", "prerequisite_id"], ["core_tasks.project_id", "core_tasks.id"]
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "definition_number"],
            ["core_task_definitions.task_id", "core_task_definitions.number"],
        ),
    )
    op.create_table(
        "core_task_attempts",
        sa.Column("task_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("number", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("definition_number", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("session_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("submission_summary", sa.String(), primary_key=False, nullable=True),
        sa.Column("submission_references", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("outcome", sa.String(), primary_key=False, nullable=True),
        sa.Column("summary", sa.String(), primary_key=False, nullable=False),
        sa.Column("observations", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("remaining_work", sa.String(), primary_key=False, nullable=True),
        sa.Column("exit_code", sa.Integer(), primary_key=False, nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["core_tasks.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["core_sessions.id"]),
        sa.ForeignKeyConstraint(
            ["task_id", "definition_number"],
            ["core_task_definitions.task_id", "core_task_definitions.number"],
        ),
    )
    op.create_table(
        "core_task_waits",
        sa.Column("task_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("number", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("target", sa.String(), primary_key=False, nullable=False),
        sa.Column("condition", sa.String(), primary_key=False, nullable=False),
        sa.Column("resume_scope", sa.String(), primary_key=False, nullable=False),
        sa.Column("observation", sa.String(), primary_key=False, nullable=False),
        sa.Column("resolution", sa.String(), primary_key=False, nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["core_tasks.id"]),
    )


def downgrade() -> None:
    """원장이 비어 있을 때만 되돌리고 원문·작업이 있으면 전체 이전을 거부한다.

    Raises:
        RuntimeError: 보존할 출처 또는 태스크가 있는 경우.
    """
    connection = op.get_bind()
    populated = connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM core_tasks) OR EXISTS(SELECT 1 FROM core_request_sources)"
        )
    )
    if populated:
        raise RuntimeError("Task sources and unfinished records must be preserved")
    op.drop_table("core_task_waits")
    op.drop_table("core_task_attempts")
    op.drop_table("core_task_dependencies")
    op.drop_table("core_task_definitions")
    op.drop_table("core_tasks")
    op.drop_table("core_request_sources")
