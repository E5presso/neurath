"""Execution attempts preserve actual outcomes even when their task definition changes."""

from dataclasses import dataclass, replace
from enum import StrEnum

from neurath.domain.errors import InvalidTaskOperation


class AttemptOutcome(StrEnum):
    """Distinguish an observed submission from terminal success, failure or partial output."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    SUBMITTED = "submitted"


@dataclass(frozen=True)
class TaskAttempt:
    """Bind an executor and later evidence to one immutable definition revision."""

    id: str
    project_id: str
    session_id: str
    task_id: str
    definition_revision: int
    executor: str
    outcome: AttemptOutcome | None = None
    summary: str = ""
    evidence: str = ""
    remaining_work: str = ""
    submission_summary: str = ""
    submission_evidence: str = ""

    def report(
        self,
        executor: str,
        outcome: AttemptOutcome,
        summary: str,
        evidence: str,
        remaining_work: str,
    ) -> TaskAttempt:
        """Record one actual result by its executor with an explicit unresolved failure."""
        if self.outcome is not None:
            raise InvalidTaskOperation("Attempt already has an outcome")
        if executor != self.executor:
            raise InvalidTaskOperation("Only this attempt's executor may report its result")
        if not summary.strip() or not evidence.strip():
            raise InvalidTaskOperation("Actual result requires summary and evidence")
        if outcome is AttemptOutcome.SUBMITTED:
            if self.submission_evidence:
                raise InvalidTaskOperation("Submission is already recorded")
            return replace(self, submission_summary=summary, submission_evidence=evidence)
        if (
            outcome in (AttemptOutcome.FAILED, AttemptOutcome.PARTIAL)
            and not remaining_work.strip()
        ):
            raise InvalidTaskOperation("Failure must preserve remaining work or a concrete blocker")
        if outcome is AttemptOutcome.SUCCEEDED and remaining_work.strip():
            raise InvalidTaskOperation("Unfinished work cannot be reported as success")
        return replace(
            self, outcome=outcome, summary=summary, evidence=evidence, remaining_work=remaining_work
        )
