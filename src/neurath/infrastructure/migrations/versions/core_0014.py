"""기존 배정 이력을 보존하고 서로 다른 정당한 요청의 중복 키를 분리한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0014"
down_revision = "core_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """과거 배정은 기존 ID로 유지하고 새 요청별 고유 키만 추가한다."""
    op.add_column("core_executions", sa.Column("pause_cause", sa.String(), nullable=True))
    op.add_column(
        "core_writers",
        sa.Column("native_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.batch_alter_table("core_delegations") as batch:
        batch.add_column(sa.Column("request_key", sa.String(), nullable=False, server_default=""))
        batch.drop_constraint("uq_core_delegation_candidate", type_="unique")
        batch.drop_index("uq_core_root_delegation")
    op.execute("UPDATE core_delegations SET request_key = 'legacy:' || id")
    with op.batch_alter_table("core_delegations") as batch:
        batch.create_unique_constraint("uq_core_delegation_request", ["task_id", "request_key"])


def downgrade() -> None:
    """여러 검토 요청이 있는 자료를 옛 단일 배정 제약으로 손실 변환하지 않는다.

    Raises:
        RuntimeError: 새 요청 식별값이나 옛 제약과 충돌하는 배정이 있는 경우.
    """
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM core_delegations WHERE request_key LIKE '%:retry:%') "
            "OR EXISTS(SELECT 1 FROM core_delegations GROUP BY task_id,definition_number,sender_id,role,candidate HAVING count(*)>1) "
            "OR EXISTS(SELECT 1 FROM core_delegations WHERE parent_id IS NULL GROUP BY task_id,definition_number,role,candidate HAVING count(*)>1) "
            "OR EXISTS(SELECT 1 FROM core_executions WHERE pause_cause IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM core_writers WHERE native_sync = 1)"
        )
    ):
        raise RuntimeError("Request history must be preserved; downgrade refused")
    with op.batch_alter_table("core_executions") as batch:
        batch.drop_column("pause_cause")
    with op.batch_alter_table("core_writers") as batch:
        batch.drop_column("native_sync")
    with op.batch_alter_table("core_delegations") as batch:
        batch.drop_constraint("uq_core_delegation_request", type_="unique")
        batch.drop_column("request_key")
        batch.create_unique_constraint(
            "uq_core_delegation_candidate",
            ["task_id", "definition_number", "sender_id", "role", "candidate"],
        )
        batch.create_index(
            "uq_core_root_delegation",
            ["task_id", "definition_number", "role", "candidate"],
            unique=True,
            sqlite_where=sa.text("parent_id IS NULL"),
        )
