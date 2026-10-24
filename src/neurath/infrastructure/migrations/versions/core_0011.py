"""기존 원장과 외부 대기를 보존하며 종속 감시·사건 이력을 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0011"
down_revision = "core_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """태스크에 종속된 감시·사건·알림 테이블을 추가한다."""
    op.create_table(
        "core_task_monitors",
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("core_tasks.id"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("wait_number", sa.Integer(), nullable=False),
        sa.Column("definition_number", sa.Integer(), nullable=False),
        sa.Column(
            "owner_execution_id", sa.Uuid(), sa.ForeignKey("core_executions.id"), nullable=False
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("remaining_polls", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("initial_state", sa.String(), nullable=True),
        sa.Column("current_state", sa.String(), nullable=True),
        sa.Column("poll_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.String(), nullable=False),
        sa.Column("stop_reason", sa.String(), nullable=False),
    )
    op.create_table(
        "core_monitor_events",
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("monitor_number", sa.Integer(), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("delivery_errors", sa.JSON(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("notice_status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id", "monitor_number"],
            ["core_task_monitors.task_id", "core_task_monitors.number"],
        ),
    )


def downgrade() -> None:
    """보존할 감시가 없을 때만 빈 스키마를 되돌린다.

    Raises:
        RuntimeError: 감시 원문·사건·실패·예산 이력이 있는 경우.
    """
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM core_task_monitors")):
        raise RuntimeError("Monitor history must be preserved; downgrade refused")
    op.drop_table("core_monitor_events")
    op.drop_table("core_task_monitors")
