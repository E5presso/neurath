"""내부 UUID와 참조를 보존하며 SQLAlchemy Uuid의 SQLite 저장 형식으로 이전한다."""

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "core_0009"
down_revision = "core_0008"
branch_labels = None
depends_on = None

# 이 revision의 열 목록은 이후 ORM 변경과 독립적으로 유지한다.
_UUID_COLUMNS = {
    "core_conversations": ("id",),
    "core_delegations": (
        "id",
        "task_id",
        "source_id",
        "parent_id",
        "sender_id",
        "recipient_id",
        "message_id",
        "plan_parent_session_id",
    ),
    "core_enclave_changes": ("enclave_id",),
    "core_enclaves": ("id", "project_id", "session_id", "task_id"),
    "core_executions": ("id", "session_id"),
    "core_memories": ("id", "project_id", "session_id", "task_id"),
    "core_messages": ("id", "conversation_id", "sender_id", "recipient_id", "reply_to"),
    "core_peers": ("id", "session_id", "current_delegation_id"),
    "core_project_locations": ("project_id",),
    "core_projects": ("id",),
    "core_request_sources": ("id", "project_id", "session_id", "corrects_id"),
    "core_sessions": ("id", "project_id", "successor_id"),
    "core_task_attempts": ("task_id", "session_id"),
    "core_task_definitions": ("task_id", "project_id", "source_id"),
    "core_task_dependencies": ("task_id", "prerequisite_id", "project_id"),
    "core_task_waits": ("task_id",),
    "core_tasks": ("id", "project_id", "owner_session_id", "follow_up_of"),
    "core_workflow_attempts": ("run_id",),
    "core_workflow_phases": ("run_id",),
    "core_workflow_revisions": ("run_id",),
    "core_workflows": ("id", "project_id", "session_id", "task_id"),
    "core_writers": ("id", "execution_id"),
}


def upgrade() -> None:
    """기존 UUID 값과 JSON·원문은 유지하고 관계형 키의 저장 표현만 압축한다."""
    _convert_uuid_columns(compact=True)


def downgrade() -> None:
    """식별자와 참조를 재발급하지 않고 이전 문자열 스키마로 복원한다."""
    _convert_uuid_columns(compact=False)


def _referencing_columns(connection: Connection) -> dict[str, set[str]]:
    """코어 키를 참조하는 기존 외부 테이블의 열도 같은 저장 표현으로 연결한다.

    복합 외래 키에서 정수 순번·외부 문자열은 UUID 열과 구분한다. 원본 본문이나
    JSON에 담긴 식별자는 관계형 키가 아니므로 변환하지 않는다.

    Args:
        connection: 명시적 이전 트랜잭션의 연결.

    Returns:
        dict[str, set[str]]: UUID 형식을 함께 바꿔야 하는 테이블별 열 이름.
    """
    metadata = sa.MetaData()
    metadata.reflect(connection)
    references: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for table in metadata.tables.values():
        for foreign_key in table.foreign_keys:
            target = (foreign_key.column.table.name, foreign_key.column.name)
            references.setdefault(target, []).append((table.name, foreign_key.parent.name))
    columns = {table: set(names) for table, names in _UUID_COLUMNS.items()}
    pending = [(table, name) for table, names in columns.items() for name in names]
    while pending:
        for table, name in references.get(pending.pop(), ()):
            names = columns.setdefault(table, set())
            if name in names:
                continue
            names.add(name)
            pending.append((table, name))
    return columns


def _convert_uuid_columns(*, compact: bool) -> None:
    """외래 키와 트리거를 보존하며 자료·타입을 하나의 이전 트랜잭션으로 바꾼다.

    SQLite batch 재생성은 외래 키 집행이 해제된 이전 전용 연결에서 실행한다.
    Alembic 환경은 이전 전후 foreign_key_check를 수행하고 실패하면 전체를 롤백한다.
    트리거는 이전 UPDATE에 반응하지 않게 같은 트랜잭션에서 보관·복원한다.
    해석할 수 없는 기존 식별자는 UUID 파서의 오류로 이전 전체를 중단한다.

    Args:
        compact: Uuid의 hex 형식으로 이전하면 True, 정규 문자열로 복원하면 False.

    Raises:
        RuntimeError: 일반 요청 연결에서 테이블 재생성을 요청한 경우.
    """
    connection = op.get_bind()
    if connection.scalar(sa.text("PRAGMA foreign_keys")):
        raise RuntimeError("UUID migration requires a migration connection before BEGIN")
    columns = _referencing_columns(connection)
    # 다른 테이블의 트리거도 재생성 중인 테이블을 참조할 수 있다.
    triggers = connection.exec_driver_sql(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
    ).all()
    quote = connection.dialect.identifier_preparer.quote
    for name, _ in triggers:
        connection.exec_driver_sql(f"DROP TRIGGER {quote(name)}")
    for table_name, names in columns.items():
        table = sa.table(table_name, *(sa.column(name, sa.String()) for name in sorted(names)))
        for name in sorted(names):
            column = table.c[name]
            values = connection.scalars(sa.select(column).distinct().where(column.is_not(None)))
            parameters = [
                {"old_value": value, "new_value": UUID(value).hex if compact else str(UUID(value))}
                for value in values
            ]
            if parameters:
                connection.execute(
                    table.update()
                    .where(column == sa.bindparam("old_value"))
                    .values({name: sa.bindparam("new_value")}),
                    parameters,
                )
        # Alembic은 이름 없는 CHECK를 자동 복사하지 않으므로 명시적으로 보존한다.
        with op.batch_alter_table(
            table_name,
            recreate="always",
            table_args=tuple(
                sa.CheckConstraint(check["sqltext"])
                for check in sa.inspect(connection).get_check_constraints(table_name)
                if check["name"] is None
            ),
        ) as batch:
            for name in sorted(names):
                batch.alter_column(name, type_=sa.Uuid() if compact else sa.String())
    for _, sql in triggers:
        connection.exec_driver_sql(sql)
