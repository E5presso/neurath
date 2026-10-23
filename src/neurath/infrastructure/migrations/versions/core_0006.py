"""원문·미완료 작업을 보존하며 enclave·기억·세션 인수 연결을 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0006"
down_revision = "core_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 자료를 바꾸지 않고 빈 기억 테이블과 선택적 후속 세션을 추가한다."""
    op.add_column("core_sessions", sa.Column("successor_id", sa.String(), nullable=True))
    for table in ("core_enclaves", "core_memories"):
        op.create_table(
            table,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("version", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("project_id", sa.String(), sa.ForeignKey("core_projects.id"), nullable=False),
            sa.Column("session_id", sa.String(), sa.ForeignKey("core_sessions.id"), nullable=False),
            sa.Column("task_id", sa.String(), sa.ForeignKey("core_tasks.id"), nullable=True),
        )
    op.add_column("core_enclaves", sa.Column("revision", sa.Integer(), nullable=False))
    op.create_index(
        "uq_core_enclave_task",
        "core_enclaves",
        ["session_id", "task_id"],
        unique=True,
        sqlite_where=sa.text("task_id IS NOT NULL"),
    )
    op.create_index(
        "uq_core_enclave_session",
        "core_enclaves",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("task_id IS NULL"),
    )
    op.add_column("core_memories", sa.Column("kind", sa.String(), nullable=False))
    op.add_column("core_memories", sa.Column("content", sa.String(), nullable=False))
    op.add_column("core_memories", sa.Column("references", sa.JSON(), nullable=False))
    op.create_table(
        "core_enclave_changes",
        sa.Column("enclave_id", sa.String(), sa.ForeignKey("core_enclaves.id"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    """기억이나 인수 기록이 없을 때만 새 구조를 제거한다.

    Raises:
        RuntimeError: 보존해야 할 기억·현재 맥락·인수 연결이 있는 경우.
    """
    if any(
        op.get_bind().scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {table})"))
        for table in ("core_enclaves", "core_memories")
    ):
        raise RuntimeError("Memory and enclave history must be preserved")
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM core_sessions WHERE successor_id IS NOT NULL)")
    ):
        raise RuntimeError("Session handoff history must be preserved")
    op.drop_table("core_enclave_changes")
    op.drop_table("core_memories")
    op.drop_table("core_enclaves")
    op.drop_column("core_sessions", "successor_id")
