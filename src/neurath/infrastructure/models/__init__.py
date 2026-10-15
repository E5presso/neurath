"""Register all declarative tables whenever any request imports a repository."""

from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel
from neurath.infrastructure.models.request_source import SourceModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.models.task import TaskModel
from neurath.infrastructure.models.task_attempt import AttemptModel
from neurath.infrastructure.models.task_change import ChangeModel

__all__ = [
    "ProjectLocationModel",
    "ProjectModel",
    "SessionModel",
    "SourceModel",
    "TaskModel",
    "AttemptModel",
    "ChangeModel",
]
