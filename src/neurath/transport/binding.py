"""Exact native invocation correlation without public caller-supplied identity."""

import hashlib
import json
import time
from pathlib import Path

from neurath.domain.errors import AuthorizationError, ConflictError, ValidationError
from neurath.domain.models import Invocation
from neurath.transport.runtime import application, database


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def observe_session(root, provider, payload):
    native_id = payload.get("session_id")
    if not isinstance(native_id, str) or not native_id:
        raise AuthorizationError("Native session identity is required")
    if payload.get("agent_id"):
        native_id += "/agent/" + str(payload["agent_id"])
    app = application(root)
    session = app.register_session(host=provider, native_id=native_id)
    if payload.get("hook_event_name") in {"SessionStart", "UserPromptSubmit"}:
        return app.activate_session(session_id=session["id"], host=provider, native_id=native_id)
    return session


def bind(root, provider, payload):
    arguments = payload.get("tool_input")
    if not isinstance(arguments, dict):
        raise ValidationError("Native tool arguments are required")
    call_id = arguments.get("_call_id")
    if not isinstance(call_id, str) or not call_id:
        raise ValidationError("A fresh _call_id is required")
    command = payload["tool_name"].removeprefix("mcp__neurath__")
    session = observe_session(root, provider, payload)
    record = Invocation(
        id=call_id,
        actor_id=session["id"],
        session_id=session["id"],
        provider=provider,
        command=command,
        args_hash=digest({k: v for k, v in arguments.items() if k != "_call_id"}),
        observed_at=str(time.time()),
    )
    with database(root).uow() as uow:
        if uow.repo("invocation").get(call_id) is not None:
            raise ConflictError("Invocation ID was already used; choose a fresh _call_id")
        uow.repo("invocation").add(record)
        uow.commit()


def invoke(root, provider, command, arguments):
    call_id = arguments.get("_call_id")
    if not isinstance(call_id, str) or not call_id:
        raise AuthorizationError("A native PreToolUse observation is required")
    values = {k: v for k, v in arguments.items() if k != "_call_id"}
    store = database(root)
    with store.uow() as uow:
        record = uow.repo("invocation").get(call_id)
        if (
            record is None
            or record.status != "pending"
            or record.provider != provider
            or record.command != command
            or record.args_hash != digest(values)
        ):
            raise AuthorizationError("Invocation does not match the observed native call")
        if not 0 <= time.time() - float(record.observed_at) <= 600:
            raise AuthorizationError("Native invocation expired")
        actor = record.actor_id
        previous = record.revision
        record.status = "running"
        record.changed()
        uow.repo("invocation").save(record, previous)
        uow.commit()
    from neurath.application.catalog import CATALOG

    commands = {name.replace(".", "_"): name for name in [*CATALOG, "verification.prepare"]}
    operation = commands.get(command, command)
    if operation == "verification.prepare":
        from neurath.transport.verification import prepare

        result = prepare(root, actor, values)
    else:
        result = application(root).execute(operation, actor, values)
    with store.uow() as uow:
        record = uow.repo("invocation").get(call_id)
        previous = record.revision
        record.status = "consumed"
        record.changed()
        uow.repo("invocation").save(record, previous)
        uow.commit()
    if operation == "session.get":
        from neurath import __version__

        receipt = Path(root) / ".neurath/install.json"
        installed = json.loads(receipt.read_text()) if receipt.is_file() else {}
        result["runtime"] = {
            "version": __version__,
            "server": "neurath",
            "provider": provider,
            "native_invocation": call_id,
            "installed_version": installed.get("version"),
            "installed_wheel_sha256": installed.get("wheel_sha256"),
        }
    return result
