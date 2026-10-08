"""Initial structured task and typed system-record schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "leases",
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(200), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("revision >= 0"),
        sa.CheckConstraint("generation >= 1"),
    )
    op.create_table(
        "records",
        sa.Column("kind", sa.String(40), primary_key=True),
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(200)),
        sa.Column("task_id", sa.String(200)),
        sa.Column("status", sa.String(50)),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.CheckConstraint("revision >= 0"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(200), nullable=False),
        sa.Column("source_id", sa.String(200), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("scope_version", sa.Integer(), nullable=False),
        sa.Column("wait_reason", sa.Text(), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.CheckConstraint("revision >= 0"),
        sa.CheckConstraint("scope_version >= 1"),
    )
    op.create_table(
        "task_criteria",
        sa.Column(
            "task_id",
            sa.String(200),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("satisfied", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "criterion_evidence",
        sa.Column(
            "task_id",
            sa.String(200),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("criterion_id", sa.String(200), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id", "criterion_id"],
            ["task_criteria.task_id", "task_criteria.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "task_phases",
        sa.Column(
            "task_id",
            sa.String(200),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
    )
    op.create_table(
        "phase_evidence",
        sa.Column("task_id", sa.String(200), primary_key=True),
        sa.Column("phase_id", sa.String(200), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id", "phase_id"], ["task_phases.task_id", "task_phases.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "task_sources",
        sa.Column(
            "task_id",
            sa.String(200),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(200), nullable=False),
    )
    op.create_table(
        "entity_versions",
        sa.Column("kind", sa.String(40), primary_key=True),
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_table(
        "task_delegations",
        sa.Column(
            "task_id",
            sa.String(200),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("delegation_id", sa.String(200), nullable=False),
    )


def downgrade():
    raise RuntimeError("Destructive downgrade to an empty database is unsupported")
