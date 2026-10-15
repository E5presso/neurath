"""Implement record source through explicit repository dependencies."""

from typing import override
from uuid import uuid4

from neurath.application.ports.repositories.request_source import ISourceRepository
from neurath.application.ports.usecases.record_source import (
    IRecordSourceUseCase,
    RecordSourceCommand,
)
from neurath.domain.aggregates.request_source import RequestSource, SourceKind
from neurath.domain.errors import InvalidTaskOperation


class RecordSourceUseCase(IRecordSourceUseCase):
    """Preserve original attributed text without automatically creating any task."""

    def __init__(self, sources: ISourceRepository) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.sources = sources

    @override
    def execute(self, request: RecordSourceCommand) -> RequestSource:
        """Preserve original attributed text without automatically creating any task."""
        source = RequestSource(
            str(uuid4()),
            request.project_id,
            request.session_id,
            request.kind,
            request.author,
            request.reference,
            request.text,
            request.corrects_id,
        )
        if source.corrects_id is not None:
            original = self.sources.get(request.project_id, source.corrects_id)
            if original.kind not in (SourceKind.INSTRUCTION, SourceKind.CORRECTION):
                raise InvalidTaskOperation("A question or summary cannot authorize a correction")
        self.sources.add(source)
        return source
