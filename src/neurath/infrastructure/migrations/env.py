"""초기화가 명시적으로 전달한 연결에서만 마이그레이션을 실행한다."""

from alembic import context
from spakky.core.application.application import SpakkyApplication
from spakky.core.application.application_context import ApplicationContext
from spakky.plugins.sqlalchemy.orm.table import AbstractTable
from sqlalchemy.engine import Connection

# 애플리케이션과 같은 스캔 규칙으로 새 @Table 모델까지 metadata에 반영한다.
SpakkyApplication(ApplicationContext()).scan("neurath.infrastructure.models")
connection = context.config.attributes["connection"]
if not isinstance(connection, Connection):
    raise TypeError("Migration requires an explicit SQLAlchemy Connection")
context.configure(
    connection=connection,
    target_metadata=AbstractTable.metadata,
    version_table="core_schema_revision",
    transactional_ddl=True,
)
with context.begin_transaction():
    context.run_migrations()
