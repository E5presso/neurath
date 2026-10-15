"""초기화가 명시적으로 전달한 연결에서만 마이그레이션을 실행한다."""

from alembic import context
from sqlalchemy.engine import Connection

from neurath.infrastructure.models.base import DatabaseModel
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel
from neurath.infrastructure.models.session import SessionModel

# Importing these declarative models registers their tables on the shared metadata.
MODEL_TYPES = (ProjectModel, ProjectLocationModel, SessionModel)
connection = context.config.attributes["connection"]
if not isinstance(connection, Connection):
    raise TypeError("Migration requires an explicit SQLAlchemy Connection")
context.configure(
    connection=connection,
    target_metadata=DatabaseModel.metadata,
    version_table="core_schema_revision",
    transactional_ddl=True,
)
with context.begin_transaction():
    context.run_migrations()
