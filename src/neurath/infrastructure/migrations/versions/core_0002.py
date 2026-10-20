"""기존 ID와 revision을 보존하며 프레임워크 메타데이터와 위치 소유 제약을 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0002"
down_revision = "core_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 자료의 생성 시각을 추정하지 않고 미상 메타데이터로 확장한다."""
    for table in ("core_projects", "core_sessions"):
        op.add_column(
            table,
            sa.Column(
                "version",
                sa.Uuid(),
                nullable=False,
                server_default="00000000000000000000000000000000",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default="1970-01-01 00:00:00",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default="1970-01-01 00:00:00",
            ),
        )
    op.add_column(
        "core_projects", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.execute("""CREATE TRIGGER core_location_owner_immutable
        BEFORE UPDATE OF project_id ON core_project_locations
        WHEN OLD.project_id != NEW.project_id
        BEGIN SELECT RAISE(ABORT, 'Location already belongs to another project'); END""")


def downgrade() -> None:
    """추가한 메타데이터와 소유 제약만 제거하고 기존 자료를 유지한다."""
    op.execute("DROP TRIGGER core_location_owner_immutable")
    op.drop_column("core_projects", "revision")
    for table in ("core_sessions", "core_projects"):
        for column in ("updated_at", "created_at", "version"):
            op.drop_column(table, column)
