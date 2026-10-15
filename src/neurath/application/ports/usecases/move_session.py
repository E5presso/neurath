"""Input and nominal contract for the move session use case."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.project import ProjectLocation
from neurath.domain.aggregates.session import SessionContext


@dataclass(frozen=True)
class MoveSessionCommand:
    """Explicit immutable input for one move session request."""

    project_id: str
    session_id: str
    location: ProjectLocation
    expected_revision: int


class IMoveSessionUseCase(ABC):
    """Application boundary for move session operations."""

    @abstractmethod
    def execute(self, request: MoveSessionCommand) -> SessionContext:
        """Execute this request inside the caller's transaction and return domain values."""
        raise NotImplementedError
