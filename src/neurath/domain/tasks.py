"""Task ledger values and transitions, independent of hosts and storage."""

from dataclasses import dataclass
from typing import Literal

from neurath.domain.core import CoreError

TaskStatus = Literal["pending", "active", "waiting", "succeeded", "failed", "invalidated"]
SourceKind = Literal["request", "correction", "context", "question"]
Outcome = Literal["submitted", "succeeded", "failed", "partial"]


class InvalidTaskTransition(CoreError):
    pass


@dataclass(frozen=True)
class Source:
    id: str
    project_id: str
    session_id: str
    kind: SourceKind
    text: str
    reference: str
    author: str
    parent_id: str | None


@dataclass(frozen=True)
class Task:
    id: str
    project_id: str
    session_id: str
    title: str
    source_id: str
    status: TaskStatus
    revision: int
    definition_revision: int
    reason: str

    def require(self, *states: TaskStatus) -> None:
        if self.status not in states:
            raise InvalidTaskTransition(f"Cannot transition task in {self.status} state")


@dataclass(frozen=True)
class Attempt:
    id: str
    task_id: str
    definition_revision: int
    state: str


@dataclass(frozen=True)
class TaskResult:
    id: str
    attempt_id: str
    outcome: Outcome
    summary: str
    references: tuple[str, ...]
    remaining: str
    applied: bool


@dataclass(frozen=True)
class TaskList:
    tasks: tuple[Task, ...]
    ready_ids: tuple[str, ...]

    @property
    def all_terminal(self) -> bool:
        return all(t.status in {"succeeded", "failed", "invalidated"} for t in self.tasks)

    @property
    def all_successful(self) -> bool:
        return all(t.status == "succeeded" for t in self.tasks)

    @property
    def todo(self) -> tuple[dict, ...]:
        # A host may flatten statuses; text still preserves the actual result.
        return tuple(
            {
                "id": t.id,
                "status": t.status,
                "text": f"[{t.status}] {t.title}" + (f" — {t.reason}" if t.reason else ""),
            }
            for t in self.tasks
        )
