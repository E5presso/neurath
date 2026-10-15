"""Run migrations only on the connection explicitly supplied by initialization."""

from alembic import context
from sqlalchemy.engine import Connection

from neurath.infrastructure.models.base import DatabaseModel
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel
from neurath.infrastructure.models.request_source import SourceModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.models.task import TaskModel
from neurath.infrastructure.models.task_attempt import AttemptModel
from neurath.infrastructure.models.task_change import ChangeModel

# Importing these declarative models registers their tables on the shared metadata.
MODEL_TYPES = (
    ProjectModel,
    ProjectLocationModel,
    SessionModel,
    SourceModel,
    TaskModel,
    AttemptModel,
    ChangeModel,
)
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
