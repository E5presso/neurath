"""Implement get sources through explicit repository dependencies."""

from typing import override

from neurath.application.ports.repositories.request_source import ISourceRepository
from neurath.application.ports.usecases.get_sources import GetSourcesQuery, IGetSourcesUseCase
from neurath.domain.aggregates.request_source import RequestSource


class GetSourcesUseCase(IGetSourcesUseCase):
    """Read exact original text and corrections without turning observations into goals."""

    def __init__(self, sources: ISourceRepository) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.sources = sources

    @override
    def execute(self, request: GetSourcesQuery) -> tuple[RequestSource, ...]:
        """Read exact original text and corrections without turning observations into goals."""
        return self.sources.list(request.project_id, request.session_id)
