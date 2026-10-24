"""기존 작업·배정을 보존하며 평가 후보와 선택 회고·교훈 이력을 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0013"
down_revision = "core_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 배정은 빈 후보로 보존하고 독립 평가만 후보별 재사용을 허용한다."""
    op.add_column(
        "core_workflows",
        sa.Column("reflection", sa.String(), nullable=False, server_default="unasked"),
    )
    op.add_column(
        "core_workflows",
        sa.Column("reflection_context", sa.String(), nullable=False, server_default=""),
    )
    op.add_column("core_workflow_phases", sa.Column("evaluation", sa.JSON(), nullable=True))
    op.add_column(
        "core_memories", sa.Column("lessons", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column(
        "core_memories", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    with op.batch_alter_table(
        "core_delegations", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
    ) as batch:
        batch.add_column(sa.Column("candidate", sa.String(), nullable=False, server_default=""))
        batch.drop_constraint("uq_core_delegations_task_id", type_="unique")
        batch.create_unique_constraint(
            "uq_core_delegation_candidate",
            ["task_id", "definition_number", "sender_id", "role", "candidate"],
        )
        batch.drop_index("uq_core_root_delegation")
        batch.create_index(
            "uq_core_root_delegation",
            ["task_id", "definition_number", "role", "candidate"],
            unique=True,
            sqlite_where=sa.text("parent_id IS NULL"),
        )
    with op.batch_alter_table("core_workflow_attempts") as batch:
        batch.add_column(sa.Column("delegation_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("candidate", sa.String(), nullable=False, server_default=""))
        batch.create_foreign_key(
            "fk_phase_delegation", "core_delegations", ["delegation_id"], ["id"]
        )


def downgrade() -> None:
    """새 평가·회고·교훈 이력이 있으면 보존을 위해 이전 버전 복원을 거절한다.

    Raises:
        RuntimeError: 삭제될 평가·선택·교훈 이력이 있는 경우.
    """
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM core_delegations WHERE candidate != '') OR EXISTS(SELECT 1 FROM core_workflows WHERE reflection != 'unasked') OR EXISTS(SELECT 1 FROM core_workflow_phases WHERE evaluation IS NOT NULL AND evaluation != 'null') OR EXISTS(SELECT 1 FROM core_memories WHERE lessons != '[]')"
        )
    ):
        raise RuntimeError("Evaluation and lesson history must be preserved")
    with op.batch_alter_table("core_workflow_attempts") as batch:
        batch.drop_constraint("fk_phase_delegation", type_="foreignkey")
        batch.drop_column("delegation_id")
        batch.drop_column("candidate")
    with op.batch_alter_table("core_delegations") as batch:
        batch.drop_constraint("uq_core_delegation_candidate", type_="unique")
        batch.drop_index("uq_core_root_delegation")
        batch.drop_column("candidate")
        batch.create_unique_constraint(
            "uq_core_delegations_task_id", ["task_id", "definition_number", "sender_id", "role"]
        )
        batch.create_index(
            "uq_core_root_delegation",
            ["task_id", "definition_number", "role"],
            unique=True,
            sqlite_where=sa.text("parent_id IS NULL"),
        )
    op.drop_column("core_workflows", "reflection")
    op.drop_column("core_workflows", "reflection_context")
    op.drop_column("core_workflow_phases", "evaluation")
    op.drop_column("core_memories", "lessons")
    op.drop_column("core_memories", "revision")
