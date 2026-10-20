"""태스크 원장을 유지하며 선택 절차의 개정·단계·시도 테이블을 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0004"
down_revision = "core_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 태스크를 변경하지 않고 그 태스크에 연결할 절차 테이블을 생성한다."""
    op.create_table(
        "core_workflows",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(), sa.ForeignKey("core_projects.id"), nullable=False),
        sa.Column("session_id", sa.String(), sa.ForeignKey("core_sessions.id"), nullable=False),
        sa.Column(
            "task_id", sa.String(), sa.ForeignKey("core_tasks.id"), unique=True, nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "task_id"], ["core_tasks.project_id", "core_tasks.id"]
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
    )
    op.create_table(
        "core_workflow_revisions",
        sa.Column("run_id", sa.String(), sa.ForeignKey("core_workflows.id"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("skill", sa.String(), nullable=False),
        sa.Column("definition_version", sa.String(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("task_definition_number", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
    )
    op.create_table(
        "core_workflow_phases",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("definition_number", sa.Integer(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("directory", sa.String(), nullable=False),
        sa.Column("target_revision", sa.String(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("skip_condition", sa.String(), nullable=True),
        sa.Column("timeout", sa.Float(), nullable=False),
        sa.Column("output_limit", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id", "definition_number"],
            ["core_workflow_revisions.run_id", "core_workflow_revisions.number"],
        ),
    )
    op.create_table(
        "core_workflow_attempts",
        sa.Column("run_id", sa.String(), sa.ForeignKey("core_workflows.id"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("definition_number", sa.Integer(), nullable=False),
        sa.Column("phase_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("skip_reason", sa.String(), nullable=True),
        sa.Column("result_target", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("output", sa.String(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id", "definition_number"],
            ["core_workflow_revisions.run_id", "core_workflow_revisions.number"],
        ),
    )


def downgrade() -> None:
    """절차 이력이 없는 경우에만 새 테이블을 제거한다.

    Raises:
        RuntimeError: 보존할 run과 정의·시도가 있는 경우.
    """
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM core_workflows)")):
        raise RuntimeError("Workflow history must be preserved")
    op.drop_table("core_workflow_attempts")
    op.drop_table("core_workflow_phases")
    op.drop_table("core_workflow_revisions")
    op.drop_table("core_workflows")
