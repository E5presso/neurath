"""기존 원문·작업을 보존하면서 피어·대화·메시지·배정 테이블을 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "core_0008"
down_revision = "core_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 행을 변경하지 않고 협업 상태의 외래 키와 중복 방지 제약을 만든다."""
    op.create_table(
        "core_peers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), sa.ForeignKey("core_sessions.id"), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("subscriptions", sa.JSON(), nullable=False),
        sa.Column("current_delegation_id", sa.String(), nullable=True),
        sa.UniqueConstraint("session_id", "agent_id"),
    )
    op.create_table(
        "core_conversations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("participants", sa.JSON(), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "core_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "conversation_id", sa.String(), sa.ForeignKey("core_conversations.id"), nullable=False
        ),
        sa.Column("sender_id", sa.String(), sa.ForeignKey("core_peers.id"), nullable=False),
        sa.Column("recipient_id", sa.String(), sa.ForeignKey("core_peers.id"), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("reply_to", sa.String(), sa.ForeignKey("core_messages.id"), nullable=True),
        sa.Column("topic", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("delivery_attempt", sa.Integer(), nullable=False),
        sa.Column("delivery_evidence", sa.String(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("sender_id", "recipient_id", "key"),
    )
    op.create_table(
        "core_delegations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), sa.ForeignKey("core_tasks.id"), nullable=False),
        sa.Column("definition_number", sa.Integer(), nullable=False),
        sa.Column(
            "source_id", sa.String(), sa.ForeignKey("core_request_sources.id"), nullable=False
        ),
        sa.Column("parent_id", sa.String(), sa.ForeignKey("core_delegations.id"), nullable=True),
        sa.Column("sender_id", sa.String(), sa.ForeignKey("core_peers.id"), nullable=False),
        sa.Column("recipient_id", sa.String(), sa.ForeignKey("core_peers.id"), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), sa.ForeignKey("core_messages.id"), nullable=True),
        sa.Column("execution_reference", sa.String(), nullable=True),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("stop_reason", sa.String(), nullable=True),
        sa.Column("stop_evidence", sa.String(), nullable=True),
        sa.Column("plan_provider", sa.String(), nullable=True),
        sa.Column("plan_model", sa.String(), nullable=True),
        sa.Column("plan_policy", sa.String(), nullable=True),
        sa.Column("plan_directory", sa.String(), nullable=True),
        sa.Column("plan_parent_session_id", sa.String(), nullable=True),
        sa.Column("provider_requested", sa.Boolean(), nullable=False),
        sa.Column("provider_status", sa.String(), nullable=True),
        sa.Column("provider_output", sa.String(), nullable=False),
        sa.Column("provider_error", sa.String(), nullable=True),
        sa.Column("native_session_id", sa.String(), nullable=True),
        sa.Column("report_summary", sa.String(), nullable=True),
        sa.Column("report_references", sa.JSON(), nullable=False),
        sa.Column("report_remaining_work", sa.String(), nullable=True),
        sa.UniqueConstraint("task_id", "definition_number", "sender_id", "role"),
    )

    op.create_index(
        "uq_core_root_delegation",
        "core_delegations",
        ["task_id", "definition_number", "role"],
        unique=True,
        sqlite_where=sa.text("parent_id IS NULL"),
    )


def downgrade() -> None:
    """협업 기록이 하나라도 있으면 파괴적 다운그레이드를 거부한다.

    Raises:
        RuntimeError: 보존해야 하는 피어·메시지·배정 기록이 있는 경우.
    """
    tables = ("core_delegations", "core_messages", "core_conversations", "core_peers")
    if any(
        op.get_bind().scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {table})")) for table in tables
    ):
        raise RuntimeError("Collaboration history must be preserved")
    for table in tables:
        op.drop_table(table)
