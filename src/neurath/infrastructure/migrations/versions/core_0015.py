"""원본 사본과 현재 작업의 선택 재개 연결을 보존한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0015"
down_revision = "core_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """현재 작업이나 과거 원문을 바꾸지 않고 보존 자료 표를 추가한다."""
    op.create_table(
        "core_historical_archives",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("directory", sa.String(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=False),
        sa.Column("snapshot_path", sa.String(), nullable=False),
        sa.Column("digest", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_path", "digest"),
    )
    op.create_table(
        "core_historical_adoptions",
        sa.Column(
            "archive_id", sa.Uuid(), sa.ForeignKey("core_historical_archives.id"), primary_key=True
        ),
        sa.Column("directory", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("core_tasks.id"), nullable=False),
        sa.UniqueConstraint("directory", "origin"),
    )


def downgrade() -> None:
    """보존 자료나 재개 연결이 있으면 제거하지 않는다.

    Raises:
        RuntimeError: 자료가 있어 손실 없는 제거를 할 수 없는 경우.
    """
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM core_historical_archives")):
        raise RuntimeError("Historical sources and resumed work must be preserved")
    op.drop_table("core_historical_adoptions")
    op.drop_table("core_historical_archives")
