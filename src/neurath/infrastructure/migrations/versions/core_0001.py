"""Initial user-wide project/session identity foundation."""

import sqlalchemy as sa
from alembic import op

revision = "core_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the immutable first project/session schema."""
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
    """Refuse destructive rollback of preserved user records."""
    raise RuntimeError(
        "Destructive core downgrade is unsupported; preserve data for migration recovery"
    )
