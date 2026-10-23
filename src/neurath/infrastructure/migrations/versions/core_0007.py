"""기존 보고를 보존하며 선택적인 그래프 갱신 요청과 결과를 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0007"
down_revision = "core_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 기억에는 갱신 요청을 꾸미지 않고 세 선택 필드를 추가한다."""
    op.add_column("core_memories", sa.Column("graph_directory", sa.String(), nullable=True))
    op.add_column("core_memories", sa.Column("graph_reference", sa.String(), nullable=True))
    op.add_column("core_memories", sa.Column("graph_error", sa.String(), nullable=True))


def downgrade() -> None:
    """외부 갱신 요청이나 결과가 없을 때만 추가 필드를 제거한다.

    Raises:
        RuntimeError: 보존할 요청·성공·실패 기록이 있는 경우.
    """
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM core_memories "
            "WHERE graph_directory IS NOT NULL OR graph_reference IS NOT NULL "
            "OR graph_error IS NOT NULL)"
        )
    ):
        raise RuntimeError("Checkpoint graph requests and outcomes must be preserved")
    op.drop_column("core_memories", "graph_error")
    op.drop_column("core_memories", "graph_reference")
    op.drop_column("core_memories", "graph_directory")
