"""기존 기록을 유지하며 기사와 소유 이력의 저장 경계를 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0010"
down_revision = "core_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기사·개정·댓글·열람·작업 사용·활성 구독자 알림 테이블을 추가한다."""
    op.create_table(
        "core_articles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("core_projects.id"), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("core_peers.id"), nullable=False),
    )
    op.create_table(
        "core_article_revisions",
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("core_articles.id"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
    )
    op.create_table(
        "core_article_comments",
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("core_articles.id"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("peer_id", sa.Uuid(), sa.ForeignKey("core_peers.id"), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
    )
    op.create_table(
        "core_article_reads",
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("core_articles.id"), primary_key=True),
        sa.Column("peer_id", sa.Uuid(), sa.ForeignKey("core_peers.id"), primary_key=True),
        sa.Column("revision_number", sa.Integer(), primary_key=True),
    )
    op.create_table(
        "core_article_uses",
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("core_articles.id"), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("core_tasks.id"), primary_key=True),
        sa.Column("definition_number", sa.Integer(), primary_key=True),
        sa.Column("revision_number", sa.Integer(), primary_key=True),
        sa.Column("peer_id", sa.Uuid(), sa.ForeignKey("core_peers.id"), primary_key=True),
    )
    op.create_table(
        "core_article_notices",
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("core_articles.id"), primary_key=True),
        sa.Column("peer_id", sa.Uuid(), sa.ForeignKey("core_peers.id"), primary_key=True),
        sa.Column("revision_number", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
    )


def downgrade() -> None:
    """기사가 있으면 이력 삭제를 거부하고 빈 후보 스키마만 되돌린다.

    Raises:
        RuntimeError: 보존해야 할 기사 이력이 있는 경우.
    """
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM core_articles")):
        raise RuntimeError("Article history must be preserved; downgrade refused")
    op.drop_table("core_article_notices")
    op.drop_table("core_article_uses")
    op.drop_table("core_article_reads")
    op.drop_table("core_article_comments")
    op.drop_table("core_article_revisions")
    op.drop_table("core_articles")
