"""Execute one exact host-authorized check and persist process-derived evidence.

This entry point accepts only an existing execution identifier. Native PreToolUse
must have changed that record to ``running`` before this adapter may launch it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from neurath.application.service import digest
from neurath.domain.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from neurath.domain.models import Evidence
from neurath.transport.runtime import database

TAIL_LENGTH = 4096


def _lease(uow, resource: str, actor: str):
    lease = uow.repo("lease").get(digest(resource))
    if lease is None or lease.resource != resource or not lease.active or lease.owner_id != actor:
        raise AuthorizationError("The native check requires the current checkout writer lease")
    return lease


def _save(uow, entity):
    previous = entity.revision
    entity.changed()
    uow.repo(entity.kind).save(entity, previous)


def _output(text: str) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "tail": text[-TAIL_LENGTH:],
        "characters": len(text),
    }


def run(root, execution_id: str) -> dict[str, Any]:
    """Run stored argv once; output text can never attest its own exit status."""
    if not isinstance(execution_id, str) or not execution_id:
        raise ValidationError("An execution identifier is required")
    root = Path(root).resolve()
    resource = str(root)
    store = database(root)
    with store.uow() as uow:
        record = uow.repo("execution").get(execution_id)
        if record is None:
            raise NotFoundError("Prepared execution was not found")
        if record.status != "running" or not record.tool_use_id:
            raise ConflictError("Execution must have one unconsumed native PreToolUse observation")
        session = uow.repo("session").get(record.actor_id)
        task = uow.repo("task").get(record.task_id)
        if session is None or session.status != "active":
            raise AuthorizationError("Execution actor must be an active native session")
        if (
            task is None
            or task.owner_id != record.actor_id
            or task.status != "active"
            or task.scope_version != record.scope_version
        ):
            raise AuthorizationError(
                "Execution requires its original active task ownership and scope"
            )
        lease = _lease(uow, resource, record.actor_id)
        lease_generation = lease.generation
        if (
            not isinstance(record.argv, list)
            or not record.argv
            or not all(isinstance(value, str) and value for value in record.argv)
        ):
            raise ValidationError("Stored check argv is invalid")
        if (
            not isinstance(record.expected_codes, list)
            or not record.expected_codes
            or not all(type(value) is int for value in record.expected_codes)
        ):
            raise ValidationError("Stored expected exit codes are invalid")
        if not Path(record.cwd).is_absolute() or not Path(record.cwd).resolve().is_relative_to(
            root
        ):
            raise ValidationError(
                "Stored check working directory must remain within the authorized checkout"
            )
        record.status = "executing"
        _save(uow, record)
        uow.commit()

    # The transaction ends before process execution. Another runner can observe
    # ``executing`` but cannot claim this identifier or launch a duplicate process.
    launch_error = None
    try:
        result = subprocess.run(
            record.argv,
            cwd=record.cwd,
            capture_output=True,
            text=True,
            errors="replace",
            shell=False,
        )
        exit_code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except OSError as error:
        # No process exit code exists when launch itself failed. Preserve that
        # distinction instead of manufacturing an exit code or dropping the task.
        exit_code, stdout, stderr = None, "", ""
        launch_error = {"type": type(error).__name__, "errno": error.errno, "message": str(error)}

    with store.uow() as uow:
        current = uow.repo("execution").get(execution_id)
        if current is None or current.status != "executing" or current.revision != record.revision:
            raise ConflictError("Claimed execution changed while its native process was running")
        task = uow.repo("task").get(record.task_id)
        session = uow.repo("session").get(record.actor_id)
        current_lease = uow.repo("lease").get(digest(resource))
        validity = {
            "session_active": session is not None and session.status == "active",
            "owner_current": task is not None and task.owner_id == record.actor_id,
            "scope_current": task is not None and task.scope_version == record.scope_version,
            "task_active": task is not None and task.status == "active",
            "writer_current": current_lease is not None
            and current_lease.resource == resource
            and current_lease.active
            and current_lease.owner_id == record.actor_id
            and current_lease.generation == lease_generation,
        }
        success = (
            launch_error is None and exit_code in record.expected_codes and all(validity.values())
        )
        observation = {
            "execution_id": execution_id,
            "native_tool_use_id": record.tool_use_id,
            "argv": record.argv,
            "cwd": record.cwd,
            "returncode": exit_code,
            "stdout": _output(stdout),
            "stderr": _output(stderr),
            "launch_error": launch_error,
            "writer_generation": lease_generation,
            **validity,
        }
        native_event_id = "check:" + execution_id
        evidence = Evidence(
            id="evidence_" + digest([record.actor_id, native_event_id]),
            task_id=record.task_id,
            actor_id=record.actor_id,
            evidence_type="tool",
            content=json.dumps(observation, sort_keys=True, ensure_ascii=False, allow_nan=False),
            scope_version=record.scope_version,
            criterion_id=record.criterion_id,
            phase_id=record.phase_id,
            native_event_id=native_event_id,
            success=success,
        )
        # This adapter owns the claimed process observation. It records failures
        # even after the former owner ends or the task scope changes; neither
        # grants the former actor authority to mutate the task.
        uow.repo("evidence").add(evidence)
        current.status, current.exit_code, current.evidence_id = "finished", exit_code, evidence.id
        _save(uow, current)
        uow.commit()
    return {
        "execution_id": execution_id,
        "state": "finished",
        "exit_code": exit_code,
        "evidence_id": evidence.id,
        "success": success,
        "observation": observation,
    }
