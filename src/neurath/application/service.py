"""Atomic application commands over a host-independent work ledger."""

import hashlib
import json
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

from neurath.domain import (
    AuthorizationError,
    Checkpoint,
    ConflictError,
    Criterion,
    Delegation,
    DomainError,
    Evidence,
    Lease,
    Message,
    NotFoundError,
    Phase,
    Receipt,
    Session,
    Source,
    Task,
    ValidationError,
)
from neurath.domain.models import Entity, nonempty
from neurath.domain.ports import UnitOfWork

from .catalog import CATALOG, validate


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def identifier(kind: str) -> str:
    return f"{kind}_{uuid4().hex}"


class Application:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]):
        self.uow_factory = uow_factory

    @staticmethod
    def _get(uow: UnitOfWork, kind: str, entity_id: str) -> Any:
        entity = uow.repo(kind).get(entity_id)
        if entity is None:
            raise NotFoundError(f"{kind} {entity_id} was not found")
        return entity

    def _session(self, uow: UnitOfWork, actor_id: str) -> Session:
        session = cast(Session, self._get(uow, "session", actor_id))
        if session.status != "active":
            raise AuthorizationError("Native session is not active")
        return session

    @staticmethod
    def _save(uow: UnitOfWork, entity: Entity) -> None:
        previous = entity.revision
        entity.changed()
        uow.repo(entity.kind).save(entity, previous)

    def _task(self, uow: UnitOfWork, actor_id: str, args: dict[str, Any]) -> Task:
        task = cast(Task, self._get(uow, "task", args["task_id"]))
        task.authorize(actor_id)
        task.check_revision(args["expected_revision"])
        return task

    def _source(self, uow: UnitOfWork, actor_id: str, source_id: str) -> Source:
        source = cast(Source, self._get(uow, "source", source_id))
        if source.session_id != actor_id or source.source_type != "user":
            raise AuthorizationError("Task intake requires this session's native user source")
        return source

    @staticmethod
    def _definition(args: dict[str, Any]) -> tuple[list[Criterion], list[Phase]]:
        criteria = [Criterion(**item) for item in args["criteria"]]
        phases = [Phase(**item) for item in args.get("phases", [])]
        if len({item.id for item in criteria}) != len(criteria) or len(
            {item.id for item in phases}
        ) != len(phases):
            raise ValidationError("Criterion and phase identifiers must be unique")
        return criteria, phases

    def _evidence(self, uow: UnitOfWork, task: Task, args: dict[str, Any]) -> list[Evidence]:
        result = []
        for evidence_id in args["evidence_ids"]:
            evidence = cast(Evidence, self._get(uow, "evidence", evidence_id))
            evidence.supports(
                task, criterion_id=args.get("criterion_id"), phase_id=args.get("phase_id")
            )
            result.append(evidence)
        return result

    def execute(self, command: str, actor_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute one command. actor_id must come from authenticated host context."""
        if command not in CATALOG:
            raise ValidationError(f"Unknown command: {command}")
        definition = CATALOG[command]
        validate(definition["inputSchema"], arguments)
        with self.uow_factory() as uow:
            self._session(uow, actor_id)
            if definition["mutation"]:
                receipt_id = digest([actor_id, arguments["request_id"]])
                body_hash = digest({"command": command, "arguments": arguments})
                receipt = uow.repo("receipt").get(receipt_id)
                if receipt:
                    if receipt.body_hash != body_hash:
                        raise ConflictError(
                            "Idempotency key was already used with another request body"
                        )
                    return receipt.result
            result = self._dispatch(uow, command, actor_id, arguments)
            if definition["mutation"]:
                uow.repo("receipt").add(
                    Receipt(
                        id=receipt_id,
                        actor_id=actor_id,
                        command=command,
                        body_hash=body_hash,
                        result=result,
                    )
                )
            uow.commit()
            return result

    def _dispatch(
        self, uow: UnitOfWork, command: str, actor: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        if command == "session.get":
            return self._get(uow, "session", actor).to_dict()
        if command == "task.get":
            return self._get(uow, "task", args["task_id"]).to_dict()
        if command == "task.list":
            return {"items": [item.to_dict() for item in uow.repo("task").list(**args)]}
        if command == "task.create":
            source = self._source(uow, actor, args["source_id"])
            criteria, phases = self._definition(args)
            task = Task(
                id=identifier("task"),
                owner_id=actor,
                source_id=source.id,
                goal=args["goal"],
                criteria=criteria,
                phases=phases,
                source_ids=[source.id],
            )
            uow.repo("task").add(task)
            return task.to_dict()
        if command == "task.adopt":
            task = self._get(uow, "task", args["task_id"])
            task.check_revision(args["expected_revision"])
            task.open()
            previous_owner = self._get(uow, "session", task.owner_id)
            if previous_owner.status != "ended":
                raise AuthorizationError("Adoption requires an ended previous owner session")
            self._source(uow, actor, args["source_id"])
            open_delegations = [
                item
                for item in uow.repo("delegation").list(task_id=task.id)
                if item.status not in {"accepted", "cancelled"}
            ]
            if any(item.recipient_id == actor for item in open_delegations):
                raise AuthorizationError(
                    "An open delegation recipient cannot adopt responsibility for accepting its own result"
                )
            if task.source_id not in task.source_ids:
                task.source_ids.append(task.source_id)
            if args["source_id"] not in task.source_ids:
                task.source_ids.append(args["source_id"])
            task.owner_id = actor
            for delegation in open_delegations:
                delegation.owner_id = actor
                self._save(uow, delegation)
            self._save(uow, task)
            return task.to_dict()
        if command in {
            "task.activate",
            "task.resume",
            "task.wait",
            "task.complete",
            "task.withdraw",
            "task.revise",
            "phase.start",
            "phase.complete",
            "criterion.satisfy",
        }:
            task = self._task(uow, actor, args)
            if command in {"task.activate", "task.resume"}:
                if command == "task.resume" and task.status != "waiting":
                    raise DomainError("Only a waiting task can resume")
                task.activate()
            elif command == "task.wait":
                task.wait(args["reason"])
            elif command == "task.complete":
                for criterion in task.criteria:
                    self._evidence(
                        uow,
                        task,
                        {"evidence_ids": criterion.evidence_ids, "criterion_id": criterion.id},
                    )
                for phase in task.phases:
                    self._evidence(
                        uow, task, {"evidence_ids": phase.evidence_ids, "phase_id": phase.id}
                    )
                delegations = [self._get(uow, "delegation", item) for item in task.delegation_ids]
                task.complete(delegations)
            elif command == "task.withdraw":
                task.open()
                approval = self._get(uow, "evidence", args["approval_id"])
                approval.supports(task)
                if approval.evidence_type != "approval" or approval.purpose != "task.withdraw":
                    raise AuthorizationError(
                        "Explicit native approval for task.withdraw is required"
                    )
                if any(
                    item.status not in {"accepted", "cancelled"}
                    for item in uow.repo("delegation").list(task_id=task.id)
                ):
                    raise DomainError("Resolve open delegations explicitly before withdrawing")
                task.status = "withdrawn"
            elif command == "task.revise":
                task.open()
                self._source(uow, actor, args["source_id"])
                if any(
                    item.status not in {"accepted", "cancelled"}
                    for item in uow.repo("delegation").list(task_id=task.id)
                ):
                    raise DomainError("Resolve open delegations before changing task scope")
                task.criteria, task.phases = self._definition(args)
                if task.source_id not in task.source_ids:
                    task.source_ids.append(task.source_id)
                if args["source_id"] not in task.source_ids:
                    task.source_ids.append(args["source_id"])
                task.goal, task.source_id = args["goal"], args["source_id"]
                task.scope_version += 1
                task.status, task.wait_reason = "pending", ""
            elif command == "phase.start":
                task.start_phase(args["phase_id"])
            elif command == "phase.complete":
                self._evidence(uow, task, args)
                task.complete_phase(args["phase_id"], args["evidence_ids"])
            elif command == "criterion.satisfy":
                self._evidence(uow, task, args)
                task.satisfy(args["criterion_id"], args["evidence_ids"])
            self._save(uow, task)
            return task.to_dict()
        if command == "evidence.record":
            task = self._get(uow, "task", args["task_id"])
            self._participant(uow, task, actor)
            self._targets(task, args.get("criterion_id"), args.get("phase_id"))
            evidence = Evidence(
                id=identifier("evidence"),
                task_id=task.id,
                actor_id=actor,
                evidence_type="report",
                content=args["content"],
                scope_version=task.scope_version,
                criterion_id=args.get("criterion_id"),
                phase_id=args.get("phase_id"),
            )
            uow.repo("evidence").add(evidence)
            return evidence.to_dict()
        if command in {"evidence.list", "delegation.list", "checkpoint.list"}:
            self._get(uow, "task", args["task_id"])
            return {
                "items": [
                    item.to_dict()
                    for item in uow.repo(command.split(".")[0]).list(task_id=args["task_id"])
                ]
            }
        if command == "delegation.prepare":
            task = self._task(uow, actor, args)
            task.open()
            self._session(uow, args["recipient_id"])
            if actor == args["recipient_id"]:
                raise ValidationError("Delegation requires a distinct recipient")
            delegation = Delegation(
                id=identifier("delegation"),
                task_id=task.id,
                owner_id=actor,
                recipient_id=args["recipient_id"],
                instruction=args["instruction"],
            )
            uow.repo("delegation").add(delegation)
            task.delegation_ids.append(delegation.id)
            self._save(uow, task)
            return {"delegation": delegation.to_dict(), "task": task.to_dict()}
        if command.startswith("delegation."):
            delegation = self._get(uow, "delegation", args["delegation_id"])
            delegation.check_revision(args["expected_revision"])
            task = self._get(uow, "task", delegation.task_id)
            task.open()
            if command == "delegation.report":
                for evidence_id in args.get("evidence_ids", []):
                    evidence = self._get(uow, "evidence", evidence_id)
                    if evidence.task_id != task.id or evidence.scope_version != task.scope_version:
                        raise ValidationError(
                            "Delegation report evidence belongs to another task or scope"
                        )
            delegation.transition(
                command.split(".")[1],
                actor,
                report=args.get("report", ""),
                evidence_ids=args.get("evidence_ids"),
                reason=args.get("reason", ""),
            )
            self._save(uow, delegation)
            return delegation.to_dict()
        if command == "message.send":
            self._session(uow, args["recipient_id"])
            if args.get("task_id"):
                self._get(uow, "task", args["task_id"])
            message = Message(
                id=identifier("message"),
                sender_id=actor,
                recipient_id=args["recipient_id"],
                content=args["content"],
                task_id=args.get("task_id"),
            )
            uow.repo("message").add(message)
            return message.to_dict()
        if command == "message.list":
            return {
                "items": [item.to_dict() for item in uow.repo("message").list(recipient_id=actor)]
            }
        if command == "message.ack":
            message = self._get(uow, "message", args["message_id"])
            if message.recipient_id != actor:
                raise AuthorizationError("Only the recipient can acknowledge a message")
            message.check_revision(args["expected_revision"])
            message.acknowledged = True
            self._save(uow, message)
            return message.to_dict()
        if command == "checkpoint.save":
            task = self._task(uow, actor, args)
            checkpoint = Checkpoint(
                id=identifier("checkpoint"),
                task_id=task.id,
                actor_id=actor,
                task_revision=task.revision,
                note=args["note"],
                state=args.get("state", {}),
            )
            uow.repo("checkpoint").add(checkpoint)
            return checkpoint.to_dict()
        if command.startswith("lease."):
            lease_id = digest(args["resource"])
            lease = uow.repo("lease").get(lease_id)
            if command == "lease.acquire":
                if lease is None:
                    lease = Lease(id=lease_id, resource=args["resource"], owner_id=actor)
                    uow.repo("lease").add(lease)
                elif lease.active:
                    if lease.owner_id != actor:
                        raise ConflictError("Resource already has an active writer")
                else:
                    lease.owner_id, lease.active = actor, True
                    lease.generation += 1
                    self._save(uow, lease)
            else:
                if lease is None:
                    raise NotFoundError("Resource has no writer lease")
                lease.check(actor, args["generation"])
                if command == "lease.release":
                    lease.check_revision(args["expected_revision"])
                    lease.active = False
                    self._save(uow, lease)
            return lease.to_dict()
        raise ValidationError("Command has no application handler")

    def _participant(self, uow: UnitOfWork, task: Task, actor: str) -> None:
        if task.owner_id != actor and not any(
            item.recipient_id == actor and item.status == "active"
            for item in uow.repo("delegation").list(task_id=task.id)
        ):
            raise AuthorizationError("Evidence requires task ownership or an active delegation")

    @staticmethod
    def _targets(task: Task, criterion_id: str | None, phase_id: str | None) -> None:
        if criterion_id is not None and not any(item.id == criterion_id for item in task.criteria):
            raise ValidationError("Unknown criterion")
        if phase_id is not None:
            task.phase(phase_id)

    def register_session(
        self,
        *,
        host: str,
        native_id: str,
        session_id: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Trusted adapter API; never expose native identity creation as a public tool."""
        nonempty(host, "host")
        nonempty(native_id, "native_id")
        session_id = session_id or f"session_{digest([host, native_id])}"
        with self.uow_factory() as uow:
            existing = uow.repo("session").get(session_id)
            if existing:
                if (existing.host, existing.native_id, existing.parent_id) != (
                    host,
                    native_id,
                    parent_id,
                ):
                    raise ConflictError("Native session identity cannot be rebound")
                return existing.to_dict()
            if uow.repo("session").list(host=host, native_id=native_id):
                raise ConflictError("Native session is already registered with another identity")
            if parent_id:
                self._session(uow, parent_id)
            session = Session(id=session_id, host=host, native_id=native_id, parent_id=parent_id)
            uow.repo("session").add(session)
            uow.commit()
            return session.to_dict()

    def activate_session(self, *, session_id: str, host: str, native_id: str) -> dict[str, Any]:
        """Trusted native SessionStart/UserPromptSubmit ingress only; never tool-side reactivation."""
        with self.uow_factory() as uow:
            session = self._get(uow, "session", session_id)
            if (session.host, session.native_id) != (host, native_id):
                raise AuthorizationError("Reactivation must match the original native identity")
            if session.status not in {"active", "ended"}:
                raise DomainError("Session cannot be reactivated from its current state")
            if session.status != "active":
                session.status = "active"
                self._save(uow, session)
            uow.commit()
            return session.to_dict()

    def register_source(
        self, *, session_id: str, event_id: str, text: str, source_type: str = "user"
    ) -> dict[str, Any]:
        """Persist an actual native event. Attribution must be checked by the adapter."""
        nonempty(event_id, "event_id")
        nonempty(text, "text")
        if source_type not in {"user", "tool", "report", "approval"}:
            raise ValidationError("Unsupported source type")
        source = Source(
            id=f"source_{digest([session_id, event_id])}",
            session_id=session_id,
            event_id=event_id,
            text=text,
            digest=digest(text),
            source_type=source_type,
        )
        with self.uow_factory() as uow:
            self._session(uow, session_id)
            existing = uow.repo("source").get(source.id)
            if existing:
                if existing.to_dict() != source.to_dict():
                    raise ConflictError("Native event id already has different source content")
                return existing.to_dict()
            uow.repo("source").add(source)
            uow.commit()
            return source.to_dict()

    def register_evidence(
        self,
        *,
        session_id: str,
        event_id: str,
        task_id: str,
        evidence_type: str,
        content: str,
        criterion_id: str | None = None,
        phase_id: str | None = None,
        source_id: str | None = None,
        success: bool | None = None,
        approved: bool | None = None,
        purpose: str | None = None,
        scope_version: int | None = None,
    ) -> dict[str, Any]:
        """Record authenticated host observations; booleans are observations, never inferred consent."""
        nonempty(event_id, "event_id")
        nonempty(content, "content")
        if evidence_type not in {"user", "tool", "report", "approval"}:
            raise ValidationError("Unsupported evidence type")
        if (
            success is not None
            and not isinstance(success, bool)
            or approved is not None
            and not isinstance(approved, bool)
        ):
            raise ValidationError("Observation flags must be booleans or null")
        if (
            evidence_type != "tool"
            and success is not None
            or evidence_type != "approval"
            and approved is not None
        ):
            raise ValidationError("Observation flags do not match evidence type")
        with self.uow_factory() as uow:
            self._session(uow, session_id)
            task = self._get(uow, "task", task_id)
            self._participant(uow, task, session_id)
            observed_scope = task.scope_version if scope_version is None else scope_version
            if type(observed_scope) is not int or not 1 <= observed_scope <= task.scope_version:
                raise ValidationError("Observation scope must be an existing task scope")
            if observed_scope == task.scope_version:
                self._targets(task, criterion_id, phase_id)
            if source_id:
                source = self._get(uow, "source", source_id)
                if source.session_id != session_id or source.source_type != evidence_type:
                    raise AuthorizationError("Source type and attribution must match evidence")
            if evidence_type in {"user", "approval"} and not source_id:
                raise ValidationError("Native human evidence requires its original source record")
            evidence = Evidence(
                id=f"evidence_{digest([session_id, event_id])}",
                task_id=task_id,
                actor_id=session_id,
                evidence_type=evidence_type,
                content=content,
                scope_version=observed_scope,
                criterion_id=criterion_id,
                phase_id=phase_id,
                source_id=source_id,
                native_event_id=event_id,
                success=success,
                approved=approved,
                purpose=purpose,
            )
            existing = uow.repo("evidence").get(evidence.id)
            if existing:
                if existing.to_dict() != evidence.to_dict():
                    raise ConflictError("Native observation id already has different content")
                return existing.to_dict()
            uow.repo("evidence").add(evidence)
            uow.commit()
            return evidence.to_dict()
