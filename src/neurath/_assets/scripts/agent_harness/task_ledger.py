"""Immutable measurable tasks; runtime adapters admit sources and resolve evidence.

No MCP input can supply a derived outcome. Resolution uses an internal resolver
bound to canonical evidence in the caller's SQLite transaction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class TaskLedgerError(ValueError):
    """Task input, stored state or evidence violates the task contract."""


class TaskRevisionConflict(TaskLedgerError):
    """The observed list or task revision is stale."""


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALIDATED = "invalidated"

    @property
    def terminal(self):
        return self in {self.SUCCEEDED, self.FAILED, self.INVALIDATED}


def _text(value, limit=16384):
    if not isinstance(value, str) or not value.strip() or "\0" in value or len(value.encode()) > limit:
        raise TaskLedgerError("expected nonempty bounded text")
    return value


def _revision(value):
    if type(value) is not int or not 0 <= value < 2**53 - 1:
        raise TaskLedgerError("expected nonnegative revision")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _sha(value):
    _text(value, 64)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise TaskLedgerError("expected SHA-256 identity")


def _tuple(value, kind, minimum=0, maximum=64):
    if not isinstance(value, tuple) or not minimum <= len(value) <= maximum:
        raise TaskLedgerError("expected bounded immutable sequence")
    if any(not isinstance(item, kind) for item in value):
        raise TaskLedgerError("sequence contains an invalid item")


def task_id(session, key):
    return "task-" + _digest([_text(session, 512), _text(key, 512)])[:32]


@dataclass(frozen=True)
class TaskSource:
    kind: str
    reference: str
    revision: str

    def __post_init__(self):
        if self.kind not in {"prompt", "ticket", "spec"}:
            raise TaskLedgerError("unsupported instruction source")
        _text(self.reference, 4096)
        _text(self.revision, 4096)


@dataclass(frozen=True)
class TaskDefinition:
    key: str
    title: str
    goal: str
    sources: tuple[TaskSource, ...]
    acceptance: tuple[str, ...]
    producer: str
    evidence_contract: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self):
        for value in (self.key, self.title, self.producer):
            _text(value, 512)
        _text(self.goal)
        _text(self.evidence_contract, 4096)
        _tuple(self.sources, TaskSource, 1, 32)
        _tuple(self.acceptance, str, 1, 32)
        _tuple(self.dependencies, str)
        for value in self.acceptance:
            _text(value)
        for value in self.dependencies:
            _text(value, 128)
        if len(set(self.dependencies)) != len(self.dependencies):
            raise TaskLedgerError("duplicate dependency")
        if len(set(self.acceptance)) != len(self.acceptance):
            raise TaskLedgerError("duplicate acceptance condition")

    @property
    def digest(self):
        # Acceptance and source revisions are part of the evidence subject.
        return _digest(asdict(self))


@dataclass(frozen=True)
class TaskEvidence:
    status: TaskStatus
    subject: str
    owner: str
    definition_digest: str
    producer: str
    references: tuple[str, ...]
    source_basis: str
    payload_digest: str
    reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.status, TaskStatus) or not self.status.terminal:
            raise TaskLedgerError("evidence must derive a terminal result")
        for value in (self.subject, self.owner, self.producer):
            _text(value, 512)
        _text(self.source_basis, 4096)
        _sha(self.definition_digest)
        _sha(self.payload_digest)
        _tuple(self.references, str, 1, 32)
        for value in self.references:
            _text(value, 4096)
        if len(set(self.references)) != len(self.references):
            raise TaskLedgerError("duplicate evidence reference")
        if self.status is not TaskStatus.SUCCEEDED or self.reason is not None:
            _text(self.reason, 4096)


@dataclass(frozen=True)
class TaskRecord:
    id: str
    definition: TaskDefinition
    status: TaskStatus = TaskStatus.PENDING
    revision: int = 1
    evidence: TaskEvidence | None = None

    def __post_init__(self):
        _text(self.id, 128)
        _revision(self.revision)
        if self.revision < 1 or not isinstance(self.definition, TaskDefinition):
            raise TaskLedgerError("invalid task definition or revision")
        if not isinstance(self.status, TaskStatus):
            raise TaskLedgerError("invalid task status")
        if self.status.terminal != (self.evidence is not None):
            raise TaskLedgerError("terminal task requires evidence")
        if self.evidence is not None:
            if not isinstance(self.evidence, TaskEvidence) or self.evidence.status is not self.status:
                raise TaskLedgerError("task and evidence outcomes differ")
            if (self.evidence.subject != self.id
                    or self.evidence.definition_digest != self.definition.digest
                    or self.evidence.producer != self.definition.producer):
                raise TaskLedgerError("evidence does not identify this task definition")


@dataclass(frozen=True)
class TaskLedger:
    session: str
    owner: str
    revision: int = 0
    tasks: tuple[TaskRecord, ...] = ()
    operations: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        _text(self.session, 512)
        _text(self.owner, 512)
        _revision(self.revision)
        _tuple(self.tasks, TaskRecord, maximum=1024)
        if not isinstance(self.operations, Mapping) or len(self.operations) > 8192:
            raise TaskLedgerError("invalid operation history")
        for key, value in self.operations.items():
            _text(key, 512)
            _sha(value)
        object.__setattr__(self, "operations", MappingProxyType(dict(self.operations)))
        by_id = {task.id: task for task in self.tasks}
        if len(by_id) != len(self.tasks):
            raise TaskLedgerError("duplicate task id")
        for task in self.tasks:
            if task.id != task_id(self.session, task.definition.key):
                raise TaskLedgerError("task id does not match its session and definition key")
            if task.evidence is not None and task.evidence.owner != self.owner:
                raise TaskLedgerError("task evidence belongs to another owner")
        remaining = {identity: len(task.definition.dependencies) for identity, task in by_id.items()}
        dependents = {identity: [] for identity in by_id}
        for identity, task in by_id.items():
            for dependency in task.definition.dependencies:
                if dependency not in by_id:
                    raise TaskLedgerError("missing or cyclic task dependency")
                dependents[dependency].append(identity)
        ready = [identity for identity, count in remaining.items() if count == 0]
        visited = 0
        while ready:
            identity = ready.pop()
            visited += 1
            for dependent in dependents[identity]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    ready.append(dependent)
        if visited != len(by_id):
            raise TaskLedgerError("missing or cyclic task dependency")

    @classmethod
    def empty(cls, session, owner):
        return cls(session, owner)

    @property
    def all_terminal(self):
        return bool(self.tasks) and all(task.status.terminal for task in self.tasks)

    def _operation(self, key, request, expected_revision):
        _text(key, 512)
        _revision(expected_revision)
        digest = _digest(request)
        previous = self.operations.get(key)
        if previous is not None:
            if previous != digest:
                raise TaskLedgerError("operation key reused for different input")
            return digest, True
        if self.revision != expected_revision:
            raise TaskRevisionConflict("task list revision changed")
        return digest, False

    def _changed(self, tasks, key, digest):
        return replace(self, tasks=tuple(tasks), revision=self.revision + 1,
                       operations={**self.operations, key: digest})

    def define(self, definitions, *, expected_revision, key):
        _tuple(definitions, TaskDefinition, 1, 64)
        if len({item.key for item in definitions}) != len(definitions):
            raise TaskLedgerError("duplicate definition in batch")
        digest, replay = self._operation(key,
            ["define", expected_revision, sorted((asdict(item) for item in definitions),
                                                key=lambda item: item["key"])], expected_revision)
        if replay:
            return self
        tasks = list(self.tasks)
        existing = {task.definition.key: task for task in tasks}
        for definition in definitions:
            old = existing.get(definition.key)
            if old is not None:
                if old.definition != definition:
                    raise TaskLedgerError("definition key reused for different input")
            else:
                tasks.append(TaskRecord(task_id(self.session, definition.key), definition))
        return self._changed(tasks, key, digest)

    def _task(self, identity, expected_revision):
        _revision(expected_revision)
        task = next((item for item in self.tasks if item.id == identity), None)
        if task is None:
            raise TaskLedgerError("task is missing")
        if task.revision != expected_revision:
            raise TaskRevisionConflict("task revision changed")
        if task.status.terminal:
            raise TaskLedgerError("terminal task history is immutable")
        return task

    def start(self, identity, *, expected_revision, expected_task_revision, key):
        digest, replay = self._operation(key,
            ["start", identity, expected_revision, expected_task_revision], expected_revision)
        if replay:
            return self
        task = self._task(identity, expected_task_revision)
        if task.status is not TaskStatus.PENDING:
            raise TaskLedgerError("only pending tasks may start")
        if any(not item.status.terminal for item in self.tasks
               if item.id in task.definition.dependencies):
            raise TaskLedgerError("task dependencies are unsettled")
        changed = replace(task, status=TaskStatus.IN_PROGRESS, revision=task.revision + 1)
        return self._changed((changed if item.id == identity else item for item in self.tasks), key, digest)

    def resolve(self, identity, *, expected_revision, expected_task_revision, key, references, resolver):
        _tuple(references, str, 1, 32)
        for reference in references:
            _text(reference, 4096)
        if len(set(references)) != len(references):
            raise TaskLedgerError("duplicate resolution reference")
        digest, replay = self._operation(key,
            ["resolve", identity, expected_revision, expected_task_revision, sorted(references)], expected_revision)
        if replay:
            return self
        task = self._task(identity, expected_task_revision)
        proof = resolver(task, references)
        if not isinstance(proof, TaskEvidence) or proof.owner != self.owner:
            raise TaskLedgerError("resolver did not return owned canonical evidence")
        if set(proof.references) != set(references):
            raise TaskLedgerError("resolver substituted evidence references")
        changed = replace(task, status=proof.status, evidence=proof, revision=task.revision + 1)
        return self._changed((changed if item.id == identity else item for item in self.tasks), key, digest)

    def encode(self):
        return _json({"schema": "neurath.task-ledger.v1", "session": self.session,
                      "owner": self.owner, "revision": self.revision,
                      "tasks": [asdict(task) for task in self.tasks], "operations": dict(self.operations)})

    @classmethod
    def decode(cls, payload):
        def exact(value, names):
            if not isinstance(value, dict) or set(value) != set(names):
                raise TaskLedgerError("unexpected persisted task fields")
            return value

        def members(value):
            if not isinstance(value, list):
                raise TaskLedgerError("persisted task sequence must be an array")
            return value

        def shape(value, kind):
            return exact(value, [item.name for item in fields(kind)])

        try:
            if not isinstance(payload, bytes) or len(payload) > 16 * 1024 * 1024:
                raise TaskLedgerError("invalid task ledger payload")
            raw = exact(json.loads(payload), ("schema", "session", "owner", "revision", "tasks", "operations"))
            if raw["schema"] != "neurath.task-ledger.v1":
                raise TaskLedgerError("unsupported task ledger schema")
            tasks = []
            for item in members(raw["tasks"]):
                item = shape(item, TaskRecord)
                definition = shape(item["definition"], TaskDefinition)
                definition = TaskDefinition(**{**definition,
                    "sources": tuple(TaskSource(**shape(source, TaskSource)) for source in members(definition["sources"])),
                    "acceptance": tuple(members(definition["acceptance"])),
                    "dependencies": tuple(members(definition["dependencies"]))})
                proof = item["evidence"]
                if proof is not None:
                    proof = shape(proof, TaskEvidence)
                    proof = TaskEvidence(**{**proof, "status": TaskStatus(proof["status"]),
                                            "references": tuple(members(proof["references"]))})
                tasks.append(TaskRecord(item["id"], definition, TaskStatus(item["status"]), item["revision"], proof))
            return cls(raw["session"], raw["owner"], raw["revision"], tuple(tasks), raw["operations"])
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            if isinstance(error, TaskLedgerError):
                raise
            raise TaskLedgerError("invalid persisted task ledger") from error
