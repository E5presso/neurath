"""기존 원장에 손대지 않고 장애와 소유 근거의 저장 경계를 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0012"
down_revision = "core_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """원문·미완료 작업을 그대로 두고 유지보수 이력을 저장할 테이블을 만든다."""
    op.create_table(
        "core_incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("core_projects.id")),
        sa.Column("symptom", sa.String(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("transfers", sa.JSON(), nullable=False),
        sa.Column("replacement_id", sa.Uuid(), sa.ForeignKey("core_incidents.id")),
        sa.Column("resolution", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "core_incident_evidence",
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("core_incidents.id"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("passed", sa.Boolean()),
    )


def downgrade() -> None:
    """장애 이력이 있으면 손실을 거절하고 빈 스키마만 되돌린다.

    Raises:
        RuntimeError: 보존해야 할 장애 이력이 있는 경우.
    """
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM core_incidents")):
        raise RuntimeError("Incident history must be preserved; downgrade refused")
    op.drop_table("core_incident_evidence")
    op.drop_table("core_incidents")
