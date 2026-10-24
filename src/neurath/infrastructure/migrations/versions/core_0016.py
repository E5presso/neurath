"""이번 턴 제어 반환 원인을 읽을 수 있는 실행 형식의 호환 경계를 올린다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0016"
down_revision = "core_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 컬럼과 원문을 유지하고 새 실행 원인을 구분하는 Alembic 개정만 올린다."""


def downgrade() -> None:
    """새 제어 원인을 읽지 못하는 구버전으로 진행 상태를 넘기지 않는다.

    Raises:
        RuntimeError: 현재 턴 제어 반환이 보존된 실행이 있는 경우.
    """
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM core_executions WHERE pause_cause='turn_control'")
    ):
        raise RuntimeError(
            "Current turn-control state must remain readable; use a compatible runtime"
        )
