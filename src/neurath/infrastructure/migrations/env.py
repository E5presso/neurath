"""초기화가 명시적으로 전달한 연결에서만 마이그레이션을 실행한다."""

from alembic import context
from spakky.plugins.sqlalchemy.orm.table import AbstractTable
from sqlalchemy.engine import Connection

from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel
from neurath.infrastructure.models.request_source import RequestSourceModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.models.task import (
    TaskAttemptModel,
    TaskDefinitionModel,
    TaskDependencyModel,
    TaskModel,
    TaskWaitModel,
)
from neurath.infrastructure.models.workflow import (
    PhaseAttemptModel,
    PhaseDefinitionModel,
    WorkflowModel,
    WorkflowRevisionModel,
)

# 모델을 import해야 공유 metadata에 테이블이 등록되어 Alembic이 전체 스키마를 볼 수 있다.
MODEL_TYPES = (
    WorkflowModel,
    WorkflowRevisionModel,
    PhaseDefinitionModel,
    PhaseAttemptModel,
    ProjectModel,
    ProjectLocationModel,
    SessionModel,
    RequestSourceModel,
    TaskModel,
    TaskDefinitionModel,
    TaskDependencyModel,
    TaskAttemptModel,
    TaskWaitModel,
)
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
