"""Typed request and nominal contract for the record source operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.request_source import RequestSource, SourceKind


@dataclass(frozen=True)
class RecordSourceCommand:
    """Preserve original attributed text without automatically creating any task."""

    project_id: str
    session_id: str
    kind: SourceKind
    author: str
    reference: str
    text: str
    corrects_id: str | None = None


class IRecordSourceUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: RecordSourceCommand) -> RequestSource:
        """Preserve original attributed text without automatically creating any task."""
        raise NotImplementedError
