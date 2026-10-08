"""Host-independent records and lifecycle rules for a durable work ledger."""
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

from .errors import AuthorizationError, ConflictError, DomainError, ValidationError


def nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a nonempty string")


@dataclass(kw_only=True)
class Entity:
    id: str
    revision: int = 0
    kind: ClassVar[str] = "entity"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def check_revision(self, expected: int) -> None:
        if type(expected) is not int or expected != self.revision:
            raise ConflictError(f"Expected revision {expected}; current revision is {self.revision}")

    def changed(self) -> None:
        self.revision += 1


@dataclass(kw_only=True)
class Session(Entity):
    kind: ClassVar[str] = "session"
    host: str
    native_id: str
    parent_id: str | None = None
    status: str = "active"


@dataclass(kw_only=True)
class Source(Entity):
    kind: ClassVar[str] = "source"
    session_id: str
    event_id: str
    text: str
    digest: str
    source_type: str = "user"


@dataclass
class Criterion:
    id: str
    description: str
    evidence_ids: list[str] = field(default_factory=list)
    satisfied: bool = False


@dataclass
class Phase:
    id: str
    name: str
    status: str = "pending"
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class Task(Entity):
    kind: ClassVar[str] = "task"
    owner_id: str
    source_id: str
    goal: str
    criteria: list[Criterion]
    phases: list[Phase] = field(default_factory=list)
    status: str = "pending"
    scope_version: int = 1
    wait_reason: str = ""
    delegation_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)

    def authorize(self, actor_id: str) -> None:
        if actor_id != self.owner_id:
            raise AuthorizationError("Only the task owner may change this task")

    def open(self) -> None:
        if self.status in {"completed", "withdrawn"}:
            raise DomainError("The task is terminal")

    def activate(self) -> None:
        if self.status not in {"pending", "waiting"}:
            raise DomainError("Only pending or waiting tasks can become active")
        self.status, self.wait_reason = "active", ""

    def wait(self, reason: str) -> None:
        self.open()
        nonempty(reason, "reason")
        self.status, self.wait_reason = "waiting", reason

    def phase(self, phase_id: str) -> Phase:
        for phase in self.phases:
            if phase.id == phase_id:
                return phase
        raise ValidationError("Unknown phase")

    def start_phase(self, phase_id: str) -> None:
        if self.status != "active":
            raise DomainError("Task must be active to start a phase")
        phase = self.phase(phase_id)
        index = self.phases.index(phase)
        if any(previous.status != "completed" for previous in self.phases[:index]):
            raise DomainError("Earlier phases must complete first")
        if phase.status != "pending":
            raise DomainError("Phase is not pending")
        phase.status = "active"

    def complete_phase(self, phase_id: str, evidence_ids: list[str]) -> None:
        if self.status != "active":
            raise DomainError("Task must be active")
        phase = self.phase(phase_id)
        if phase.status != "active" or not evidence_ids:
            raise DomainError("An active phase and evidence are required")
        phase.status, phase.evidence_ids = "completed", list(dict.fromkeys(evidence_ids))

    def satisfy(self, criterion_id: str, evidence_ids: list[str]) -> None:
        self.open()
        if not evidence_ids:
            raise ValidationError("Criterion satisfaction requires evidence")
        criterion = next((item for item in self.criteria if item.id == criterion_id), None)
        if criterion is None:
            raise ValidationError("Unknown criterion")
        criterion.satisfied, criterion.evidence_ids = True, list(dict.fromkeys(evidence_ids))

    def complete(self, delegations: list["Delegation"]) -> None:
        if self.status != "active":
            raise DomainError("Only an active task can complete")
        if not self.criteria or not all(item.satisfied and item.evidence_ids for item in self.criteria):
            raise DomainError("Every acceptance criterion requires supporting evidence")
        if any(phase.status != "completed" for phase in self.phases):
            raise DomainError("Every ordered phase must complete")
        if any(item.status not in {"accepted", "cancelled"} for item in delegations):
            raise DomainError("Every delegation requires explicit acceptance or cancellation")
        self.status = "completed"


@dataclass(kw_only=True)
class Evidence(Entity):
    kind: ClassVar[str] = "evidence"
    task_id: str
    actor_id: str
    evidence_type: str
    content: str
    scope_version: int
    criterion_id: str | None = None
    phase_id: str | None = None
    source_id: str | None = None
    native_event_id: str | None = None
    success: bool | None = None
    approved: bool | None = None
    purpose: str | None = None

    def supports(self, task: Task, *, criterion_id: str | None = None, phase_id: str | None = None) -> None:
        if self.task_id != task.id or self.scope_version != task.scope_version:
            raise DomainError("Evidence belongs to another task or an obsolete scope")
        if criterion_id is not None and self.criterion_id != criterion_id:
            raise DomainError("Evidence does not address this criterion")
        if phase_id is not None and self.phase_id != phase_id:
            raise DomainError("Evidence does not address this phase")
        if self.evidence_type not in {"user", "tool", "report", "approval"}:
            raise DomainError("Unknown evidence types cannot establish verification")
        if self.evidence_type == "report":
            raise DomainError("An agent report alone cannot establish successful verification")
        if self.evidence_type == "tool" and self.success is not True:
            raise DomainError("Failed or unknown tool results cannot establish success")
        if self.evidence_type == "approval" and self.approved is not True:
            raise DomainError("Approval must be explicitly granted")


@dataclass(kw_only=True)
class Delegation(Entity):
    kind: ClassVar[str] = "delegation"
    task_id: str
    owner_id: str
    recipient_id: str
    instruction: str
    status: str = "prepared"
    report: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    decision_reason: str = ""

    def transition(self, action: str, actor_id: str, *, report: str = "", evidence_ids: list[str] | None = None, reason: str = "") -> None:
        required_actor = self.recipient_id if action in {"start", "report"} else self.owner_id
        if actor_id != required_actor:
            raise AuthorizationError("Actor does not own this delegation action")
        allowed = {"start": {"prepared", "rejected"}, "report": {"active"}, "accept": {"reported"}, "reject": {"reported"}, "cancel": {"prepared", "active", "reported", "rejected"}}
        if action not in allowed or self.status not in allowed[action]:
            raise DomainError("Delegation action is invalid in its current state")
        if action == "report":
            nonempty(report, "report")
            self.report, self.evidence_ids = report, list(evidence_ids or [])
        if action in {"reject", "cancel"}:
            nonempty(reason, "reason")
        self.decision_reason = reason
        self.status = {"start": "active", "report": "reported", "accept": "accepted", "reject": "rejected", "cancel": "cancelled"}[action]


@dataclass(kw_only=True)
class Message(Entity):
    kind: ClassVar[str] = "message"
    sender_id: str
    recipient_id: str
    content: str
    task_id: str | None = None
    acknowledged: bool = False


@dataclass(kw_only=True)
class Checkpoint(Entity):
    kind: ClassVar[str] = "checkpoint"
    task_id: str
    actor_id: str
    task_revision: int
    note: str
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class Lease(Entity):
    kind: ClassVar[str] = "lease"
    resource: str
    owner_id: str
    generation: int = 1
    active: bool = True

    def check(self, actor_id: str, generation: int) -> None:
        if type(generation) is not int or not self.active or self.owner_id != actor_id or self.generation != generation:
            raise ConflictError("Writer lease is inactive, foreign, or fenced by a newer generation")


@dataclass(kw_only=True)
class Receipt(Entity):
    kind: ClassVar[str] = "receipt"
    actor_id: str
    command: str
    body_hash: str
    result: dict[str, Any]


ENTITY_TYPES = {cls.kind: cls for cls in (Session, Source, Task, Evidence, Delegation, Message, Checkpoint, Lease, Receipt)}


@dataclass(kw_only=True)
class Invocation(Entity):
    kind: ClassVar[str] = "invocation"
    actor_id: str
    session_id: str
    provider: str
    command: str
    args_hash: str
    observed_at: str
    status: str = "pending"


ENTITY_TYPES[Invocation.kind] = Invocation


@dataclass(kw_only=True)
class Execution(Entity):
    kind: ClassVar[str] = "execution"
    actor_id: str
    task_id: str
    scope_version: int
    argv: list[str]
    cwd: str
    expected_codes: list[int]
    criterion_id: str | None = None
    phase_id: str | None = None
    status: str = "prepared"
    tool_use_id: str | None = None
    exit_code: int | None = None
    evidence_id: str | None = None


ENTITY_TYPES[Execution.kind] = Execution
