"""Typed request and nominal contract for the get sources operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.request_source import RequestSource


@dataclass(frozen=True)
class GetSourcesQuery:
    """Read exact original text and corrections without turning observations into goals."""

    project_id: str
    session_id: str


class IGetSourcesUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: GetSourcesQuery) -> tuple[RequestSource, ...]:
        """Read exact original text and corrections without turning observations into goals."""
        raise NotImplementedError
