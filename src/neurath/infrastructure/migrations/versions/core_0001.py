"""사용자 단위 프로젝트·세션 동일성의 최초 기반 스키마다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """변경하지 않을 첫 프로젝트·세션 스키마를 생성한다."""
    op.create_table(
        "core_projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("root_path", sa.String(), nullable=False),
    )
    op.create_table(
        "core_project_locations",
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("path", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("core_projects.id"), nullable=False),
        sa.CheckConstraint("kind IN ('git', 'folder')", name="location_kind"),
    )
    op.create_table(
        "core_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("core_projects.id"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("host_session_id", sa.String(), nullable=False),
        sa.Column("working_directory", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "provider", "host_session_id", name="uq_core_host_session"
        ),
        sa.UniqueConstraint("project_id", "id", name="uq_core_session_scope"),
        sa.CheckConstraint("revision >= 1", name="session_revision_positive"),
    )


def downgrade() -> None:
    """보존한 사용자 기록을 파괴하는 되돌리기를 거부한다.

    Raises:
        RuntimeError: 기존 설정을 덮어쓰거나 보존된 기록을 파괴하는 작업인 경우.
    """
    raise RuntimeError(
        "Destructive core downgrade is unsupported; preserve data for migration recovery"
    )
