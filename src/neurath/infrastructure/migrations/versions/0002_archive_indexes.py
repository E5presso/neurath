"""Add lossless source archives and query indexes without replacing existing data."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    if "source_archives" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "source_archives",
            sa.Column("id", sa.String(200), primary_key=True),
            sa.Column("digest", sa.String(64), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
        )
    if "source_archive_chunks" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "source_archive_chunks",
            sa.Column(
                "archive_id", sa.String(200), sa.ForeignKey("source_archives.id"), primary_key=True
            ),
            sa.Column("position", sa.Integer(), primary_key=True),
            sa.Column("data", sa.LargeBinary(), nullable=False),
        )
    for table, columns in [
        ("records", ["owner_id", "task_id", "status"]),
        ("tasks", ["owner_id", "source_id", "status"]),
    ]:
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    # Archives are application data: retain the additive table across downgrade.
    for table, columns in [
        ("records", ["owner_id", "task_id", "status"]),
        ("tasks", ["owner_id", "source_id", "status"]),
    ]:
        for column in columns:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
