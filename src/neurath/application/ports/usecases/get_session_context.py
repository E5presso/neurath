"""Input and nominal contract for the get session context use case."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.session import SessionContext


@dataclass(frozen=True)
class GetSessionContextQuery:
    """Explicit immutable input for one get session context request."""

    project_id: str
    session_id: str


class IGetSessionContextUseCase(ABC):
    """Application boundary for get session context operations."""

    @abstractmethod
    def execute(self, request: GetSessionContextQuery) -> SessionContext:
        """Execute this request inside the caller's transaction and return domain values."""
        raise NotImplementedError
