"""Immutable attributed requests, corrections, and non-authoritative observations."""

from dataclasses import dataclass
from enum import StrEnum

from neurath.domain.errors import InvalidTaskOperation


class SourceKind(StrEnum):
    """Distinguish actionable requests from status questions and historical summaries."""

    INSTRUCTION = "instruction"
    CORRECTION = "correction"
    STATUS_QUESTION = "status_question"
    SUMMARY = "summary"


@dataclass(frozen=True)
class RequestSource:
    """Preserve exact text and attribution; corrections point to an earlier source."""

    id: str
    project_id: str
    session_id: str
    kind: SourceKind
    author: str
    reference: str
    text: str
    corrects_id: str | None = None

    def __post_init__(self) -> None:
        """Reject unattributed records and ambiguous correction chains."""
        if not self.author.strip() or not self.reference.strip() or not self.text.strip():
            raise InvalidTaskOperation("Source requires author, reference and original text")
        if (self.kind is SourceKind.CORRECTION) != (self.corrects_id is not None):
            raise InvalidTaskOperation("Only a correction must identify the corrected source")

    def require_instruction(self) -> None:
        """Prevent questions or old summaries from becoming fresh user goals."""
        if self.kind is not SourceKind.INSTRUCTION:
            raise InvalidTaskOperation("Task definition requires an instruction source")
