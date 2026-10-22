"""기존 원장을 유지하며 호스트 실행과 작업 폴더별 작성 임대를 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0005"
down_revision = "core_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """과거 세션에 현재 실행을 꾸며 넣지 않고 빈 실행·작성 테이블만 추가한다."""
    op.create_table(
        "core_executions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), sa.ForeignKey("core_sessions.id"), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("start_source", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("stop_snapshot", sa.String(), nullable=False),
        sa.UniqueConstraint("session_id", "agent_id"),
    )
    op.create_table(
        "core_writers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("resource", sa.String(), unique=True, nullable=False),
        sa.Column("execution_id", sa.String(), sa.ForeignKey("core_executions.id"), nullable=True),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("tool_use_id", sa.String(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    """실행 기록이 없는 경우에만 추가한 두 테이블을 제거한다.

    Raises:
        RuntimeError: 보존해야 할 실행 또는 작성 기록이 있는 경우.
    """
    for table in ("core_executions", "core_writers"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {table})")):
            raise RuntimeError("Runtime history must be preserved")
    op.drop_table("core_writers")
    op.drop_table("core_executions")
