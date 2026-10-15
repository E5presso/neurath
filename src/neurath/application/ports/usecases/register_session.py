"""Input and nominal contract for the register session use case."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.project import ProjectLocation
from neurath.domain.aggregates.session import SessionContext


@dataclass(frozen=True)
class RegisterSessionCommand:
    """Explicit immutable input for one register session request."""

    location: ProjectLocation
    provider: str
    host_session_id: str


class IRegisterSessionUseCase(ABC):
    """Application boundary for register session operations."""

    @abstractmethod
    def execute(self, request: RegisterSessionCommand) -> SessionContext:
        """Execute this request inside the caller's transaction and return domain values."""
        raise NotImplementedError
