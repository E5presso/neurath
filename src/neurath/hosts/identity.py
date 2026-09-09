"""Correlate native spawn calls and scope process identity to one host tool call.

The journal contains adapter records, never a replacement for SessionKernel.
Native hook input, host transcript identity, foreground provenance and kernel CAS
are required together. Prompt text and caller-supplied actor IDs grant no authority.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import sys
import time
from pathlib import Path

SPAWN_TOOLS = {"Agent", "Task", "collaborationspawn_agent", "spawn_agent"}
MARKER = re.compile(r"<neurath-spawn-ref>([a-f0-9]{48})</neurath-spawn-ref>")


def _locator(root):
    from scripts.agent_harness.session_kernel import SessionLocator

    return SessionLocator.from_worktree(Path(root))


def _state(root, session):
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionStatus

    state = SessionKernel(_locator(root)).inspect(SessionId(session))
    if state.session.status is not SessionStatus.ACTIVE:
        raise ValueError("host identity requires an active session")
    return state


def _path(root, session):
    from scripts.agent_harness.session_kernel import SessionId

    return _locator(root).locate(SessionId(session)).directory / ".neurath-host.json"


def _database(root):
    from scripts.agent_harness.runtime_database import RuntimeDatabase
    return RuntimeDatabase(_locator(root).control_root)


def _host_data(record, session):
    data = ({"session": session, "spawns": {}, "tools": {}} if record is None
            else json.loads(record.payload))
    if not isinstance(data, dict) or data.get("session") != session:
        raise ValueError("host record belongs to a different session")
    return data


@contextlib.contextmanager
def _journal_lock(root, session):
    path = _path(root, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path


def _host_record(tx, path, session):
    """Import exact legacy metadata under its existing journal mutex."""
    record = tx.get("host-journal", session)
    if record is None and path.is_file():
        if path.is_symlink():
            raise ValueError("host journal must not be a symlink")
        content = path.read_bytes()
        data = json.loads(content)
        if not isinstance(data, dict) or data.get("session") != session:
            raise ValueError("host record belongs to a different session")
        record = tx.put("host-journal", session, content, expected_revision=None)
        tx.connection.execute(
            "UPDATE runtime_records SET legacy_path=?,legacy_digest=? WHERE namespace='host-journal' AND key=?",
            (str(path), hashlib.sha256(content).hexdigest(), session))
    return record


def snapshot(root, session):
    database = _database(root)
    with database.transaction() as tx:
        record = tx.get("host-journal", session)
    if record is None and _path(root, session).is_file():
        with _journal_lock(root, session) as path, database.transaction() as tx:
            record = _host_record(tx, path, session)
    return _host_data(record, session)


def _journal_exists(root, session):
    with _database(root).transaction() as tx:
        if tx.get("host-journal", session) is not None:
            return True
    return _path(root, session).is_file()


@contextlib.contextmanager
def journal(root, session):
    _state(root, session)
    database = _database(root)
    with _journal_lock(root, session) as path:
        with database.transaction() as tx:
            record = _host_record(tx, path, session)
            data = _host_data(record, session)
        yield data
        if data.get("session") != session:
            raise ValueError("host journal mutation changed session identity")
        with database.transaction() as tx:
            tx.put("host-journal", session,
                   json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
                   expected_revision=None if record is None else record.revision)


def _all_journals(root):
    database = _database(root)
    with database.transaction() as tx:
        sessions = [row[0] for row in tx.connection.execute(
            "SELECT key FROM runtime_records WHERE namespace='host-journal'")]
        values = [_host_data(tx.get("host-journal", session), session) for session in sessions]
    from scripts._neurath_paths import state_path
    for path in state_path(_locator(root).control_root, "runs").glob("*/.neurath-host.json"):
        if path.parent.name not in sessions:
            values.append(snapshot(root, path.parent.name))
    return values


def host_storage(host, environment):
    if host == "codex":
        return Path(environment.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    return Path(environment.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"


def _transcript(host, value, environment):
    path = Path(value).resolve()
    if not path.is_relative_to(host_storage(host, environment).resolve()):
        raise ValueError("transcript is outside host storage")
    return path


def _foreground(state):
    from scripts.agent_harness.session_kernel import ActorStatus, ForegroundTurnStatus

    actor = state.session.root_actor_id
    turn = state.foreground_turns.get(actor)
    if (
        state.actors[actor].status is not ActorStatus.ACTIVE
        or turn is None
        or turn.status is not ForegroundTurnStatus.ACTIVE
        or turn.user_prompt_receipt is None
    ):
        raise ValueError("spawn requires current root foreground prompt")
    return {
        "generation": turn.generation,
        "prompt": turn.user_prompt_receipt.prompt_digest,
        "turn": turn.vendor_turn_id,
    }


def _independent_root_source(meta):
    """App forks are independent roots, never inherited parent authority."""
    if meta.get("thread_source") in (None, "user"):
        return True
    return (meta.get("thread_source") == "agent_forked_thread"
            and isinstance(meta.get("forked_from_id"), str)
            and bool(meta["forked_from_id"].strip())
            and meta["forked_from_id"] != meta.get("id"))


def _validate_root_transcript(root, host, payload, path, data):
    """Codex can rotate rollout files while retaining the same native root.

    A filename/session argument is insufficient: only host-stored root metadata
    for this session and worktree can replace a previously registered path.
    Claude transcripts retain their existing exact-path contract.
    """
    if data.get("host") not in (None, host) or payload.get("agent_id"):
        raise ValueError("transcript is not from the registered native root")
    if data.get("transcript") in (None, str(path)):
        return
    if host == "codex":
        try:
            record = _first_record(path)
            meta = record["payload"]
            session = payload["session_id"]
            valid = (
                record["type"] == "session_meta"
                and meta["id"] == session
                and meta.get("session_id", session) == session
                and meta.get("source") in ("vscode", "cli", "exec")
                and _independent_root_source(meta)
                and not meta.get("parent_thread_id")
                and not meta.get("parent_session_id")
                and not meta.get("agent_id")
                and meta.get("agent_path") in (None, "/root")
                and Path(meta["cwd"]).resolve() == Path(payload.get("cwd", root)).resolve()
                and Path(meta["cwd"]).resolve().is_relative_to(Path(root).resolve())
            )
        except OSError, ValueError, KeyError, TypeError, AttributeError:
            valid = False
        if valid:
            return
    raise ValueError("root transcript changed without matching native root metadata")


def validate_start(root, host, payload, environment):
    """Reject foreign lifecycle provenance before the kernel mutates resume state."""
    value = payload.get("transcript_path")
    if not value:
        return
    path = _transcript(host, value, environment)
    if payload.get("agent_id"):
        raise ValueError("startup is not the registered native root")
    session = payload["session_id"]
    if _journal_exists(root, session):
        data = snapshot(root, session)
        _validate_root_transcript(root, host, payload, path, data)
        if _state(root, session).session.runtime.value != host:
            raise ValueError("startup runtime mismatch")


def record_start(root, host, payload, environment):
    # Protocol smoke payloads need not include a transcript. Those sessions
    # cannot obtain transcript-based child authority.
    value = payload.get("transcript_path")
    if not value:
        return
    path = _transcript(host, value, environment)
    session = payload["session_id"]
    with journal(root, session) as data:
        state = _state(root, session)
        if state.session.runtime.value != host or payload.get("agent_id"):
            raise ValueError("startup is not the registered native root")
        _validate_root_transcript(root, host, payload, path, data)
        data.update(host=host, transcript=str(path), connected=True, start_source=payload.get("source"))
        if payload.get("source") in {"resume", "compact"}:
            turn = state.foreground_turns.get(state.session.root_actor_id)
            data["resume_pending"] = None if turn is None else _resume_snapshot(turn)


def active_connection(root, session):
    data = snapshot(root, session)
    source = data.get("start_source")
    if "start_source" not in data and data.get("resume_pending"):
        # A running pre-newsroom installation did not persist the startup source.
        # Only its accepted kernel compact event can recover that distinction.
        lifecycle = _state(root, session).session.last_lifecycle_idempotency_key or ""
        if lifecycle.startswith("runtime-hook:compact:"):
            source = "compact"
    return data.get("connected") is not False and not (
        data.get("resume_pending") and source != "compact"
    )


def record_disconnect(root, host, payload):
    """Native process retirement is distinct from the resumable logical session."""
    session = payload.get("session_id")
    if not session or payload.get("agent_id"):
        return
    current = snapshot(root, session)
    if current.get("host") != host or not current.get("transcript"):
        return
    if payload.get("transcript_path") and str(Path(payload["transcript_path"]).resolve()) != current["transcript"]:
        raise ValueError("disconnect is not from the registered native transcript")
    with journal(root, session) as data:
        data["connected"] = False


def _resume_snapshot(turn):
    return {
        "generation": turn.generation,
        "revision": turn.revision,
        "turn": turn.vendor_turn_id,
        "prompt": None
        if turn.user_prompt_receipt is None
        else turn.user_prompt_receipt.prompt_digest,
    }


def spawn_hook(root, host, payload, environment):
    session = payload["session_id"]
    if payload.get("agent_id") is not None:
        raise ValueError("nested native spawning requires a separate parent contract")
    state = _state(root, session)
    foreground = _foreground(state)
    if state.session.runtime.value != host or (
        host == "codex" and payload.get("turn_id") != foreground["turn"]
    ):
        raise ValueError("spawn does not match the root foreground turn")
    call = payload.get("tool_use_id")
    if not isinstance(call, str) or not call:
        raise ValueError("spawn requires a native tool call id")
    with journal(root, session) as data:
        if data.get("host") != host or str(
            _transcript(host, payload["transcript_path"], environment)
        ) != data.get("transcript"):
            raise ValueError("spawn transcript does not match the root")
        if payload["hook_event_name"] == "PreToolUse":
            record = data["spawns"].get(call)
            if record is None:
                record = {
                    "foreground": foreground,
                    "nonce": secrets.token_hex(24),
                    "child": None,
                    "parent": str(state.session.root_actor_id),
                    "host": host,
                }
                data["spawns"][call] = record
                intents = [
                    (key, value)
                    for key, value in data.get("intents", {}).items()
                    if value["foreground"] == foreground and value.get("call_id") is None
                ]
                if len(intents) > 1:
                    raise ValueError("ambiguous pending delegation intents")
                if intents:
                    key, intent = intents[0]
                    intent["call_id"] = call
                    record["delegation"] = {"id": key, "assignment": intent["assignment"]}
            if record["foreground"] != foreground:
                raise ValueError("native spawn id reused across foreground turns")
            if host == "claude-code":
                inputs = payload["tool_input"]
                prompt = inputs.get("prompt")
                if not isinstance(prompt, str) or MARKER.search(prompt):
                    raise ValueError("invalid or pre-stamped Agent prompt")
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "updatedInput": {
                            **inputs,
                            "prompt": prompt
                            + "\n\n<neurath-spawn-ref>"
                            + record["nonce"]
                            + "</neurath-spawn-ref>",
                        },
                    }
                }
        elif call in data["spawns"]:
            response = payload.get("tool_response")
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                except ValueError:
                    response = None
            if isinstance(response, dict):
                data["spawns"][call]["native_path"] = response.get("task_name")
                data["spawns"][call]["returned_child"] = response.get(
                    "agent_id", response.get("agentId")
                )
    return {}


def _first_record(path):
    with path.open() as stream:
        line = stream.readline(1024 * 1024)
    return json.loads(line)


def attest_child(root, host, payload, environment):
    """Return a consumed one-child spawn witness, or no authority."""
    try:
        session, child = payload["session_id"], payload["agent_id"]
        from scripts.agent_harness.session_kernel import ActorId

        ActorId(child)  # Reject malformed/path-bearing identities before filesystem access.
        if "/" in child or "\\" in child or child in {".", ".."}:
            return None
        state = _state(root, session)
        foreground = _foreground(state)
        current = snapshot(root, session)
        if current.get("host") != host:
            return None
        supplied = _transcript(host, payload["transcript_path"], environment)
        nonce = native_path = None
        if host == "codex":
            record = _first_record(supplied)
            meta = record.get("payload", {})
            spawn = meta.get("source", {}).get("subagent", {}).get("thread_spawn", {})
            if (
                record.get("type") != "session_meta"
                or meta.get("id") != child
                or meta.get("session_id") != session
                or meta.get("parent_thread_id") != session
                or spawn.get("parent_thread_id") != session
            ):
                return None
            native_path = meta.get("agent_path")
        else:
            if str(supplied) != current.get("transcript"):
                return None
            path = supplied.parent / session / "subagents" / f"agent-{child}.jsonl"
            record = _first_record(_transcript(host, str(path), environment))
            if (
                record.get("type") != "user"
                or record.get("agentId") != child
                or record.get("sessionId") != session
                or record.get("isSidechain") is not True
            ):
                return None
            content = record.get("message", {}).get("content")
            if isinstance(content, list):
                content = "\n".join(x.get("text", "") for x in content if x.get("type") == "text")
            matches = MARKER.findall(content or "")
            if len(matches) != 1:
                return None
            nonce = matches[0]
        with journal(root, session) as data:
            matches = [
                (call, rec)
                for call, rec in data["spawns"].items()
                if rec["foreground"] == foreground
                and rec["host"] == host
                and rec["parent"] == str(state.session.root_actor_id)
                and rec.get("child") in (None, child)
                and (
                    (
                        host == "codex"
                        and rec.get("returned_child") in (None, child)
                        and (
                            rec.get("returned_child") == child
                            or (native_path and rec.get("native_path") == native_path)
                        )
                    )
                    or (host == "claude-code" and rec["nonce"] == nonce)
                )
            ]
            if len(matches) != 1:
                return None
            call, witness = matches[0]
            witness["child"] = child
            return {
                "parent": witness["parent"],
                "call_id": call,
                "revision": state.revision,
                "foreground": foreground,
            }
    except ValueError, OSError, KeyError, TypeError, AttributeError:
        return None


def issue_tool_binding(root, host, payload):
    from scripts.agent_harness.session_kernel import ActorId, ActorLineageAssurance, ActorStatus

    session = payload["session_id"]
    state = _state(root, session)
    actor = (
        ActorId(f"{host}:{payload['agent_id']}")
        if payload.get("agent_id")
        else state.session.root_actor_id
    )
    current = state.actors.get(actor)
    if (
        state.session.runtime.value != host
        or current is None
        or current.status is not ActorStatus.ACTIVE
        or (
            actor != state.session.root_actor_id
            and current.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
        )
    ):
        raise ValueError("child-identity-unverified: no active attested actor")
    call = payload.get("tool_use_id")
    if not isinstance(call, str) or not call:
        raise ValueError("tool identity requires native tool_use_id")
    with journal(root, session) as data:
        existing = data["tools"].get(call)
        if existing:
            if (
                existing["actor"] != str(actor)
                or not existing["active"]
                or existing["command"] != payload.get("tool_input", {}).get("command")
            ):
                raise ValueError("tool identity replay")
            return session + ":" + existing["nonce"]
        nonce = secrets.token_hex(24)
        data["tools"][call] = {
            "host": host,
            "actor": str(actor),
            "nonce": nonce,
            "active": True,
            "expires": time.time() + 3600,
            "command": payload.get("tool_input", {}).get("command"),
        }
    return session + ":" + nonce


def rewrite_tool(inputs, token):
    command = inputs.get("command")
    if not isinstance(command, str):
        raise TypeError("shell identity injection requires a command string")
    return {
        **inputs,
        "command": "export NEURATH_TOOL_BINDING="
        + shlex.quote(token)
        + "\n"
        + shlex.join(
            [
                sys.executable,
                "-I",
                "-m",
                "neurath.hosts.process",
                str(_locator(os.environ["NEURATH_TARGET_ROOT"]).control_root),
            ]
        )
        + " || exit $?\n:\n"
        + command,
    }


def finish_tool(root, host, payload):
    with journal(root, payload["session_id"]) as data:
        record = data["tools"].get(payload.get("tool_use_id"))
        if record and record["host"] == host:
            response = payload.get("tool_response", {})
            inputs = payload.get("tool_input", {})
            background = (
                inputs.get("run_in_background") is True
                or (
                    isinstance(response, dict)
                    and bool(response.get("backgroundTaskId") or response.get("background_task_id"))
                )
                or (
                    isinstance(response, str)
                    and response.startswith("Command running in background with ID:")
                )
            )
            if payload.get("hook_event_name") != "PostToolUse" or not background:
                record["active"] = False


def resolve_binding(environment, *, require_process=True):
    """Resolve a tool identity record supplied by the hook without changing vendor identity."""
    token = environment.get("NEURATH_TOOL_BINDING")
    if token is None:
        return None
    from scripts.agent_harness.session_kernel import (
        ActorId,
        ActorLineageAssurance,
        ActorStatus,
        SessionId,
        SessionRuntime,
    )
    from scripts.agent_harness.state_handle import RuntimeIdentityBinding

    root = os.environ.get("NEURATH_TARGET_ROOT")
    if not root or not isinstance(token, str) or ":" not in token:
        raise ValueError("invalid tool identity record")
    session, nonce = token.rsplit(":", 1)
    matches = [r for r in snapshot(root, session)["tools"].values() if r["nonce"] == nonce]
    if len(matches) != 1 or not matches[0]["active"] or matches[0]["expires"] < time.time():
        raise ValueError("expired or unknown tool identity record")
    receipt = matches[0]
    if require_process:
        from neurath.hosts.process import verify_process

        verify_process(receipt)
    host, actor = receipt["host"], ActorId(receipt["actor"])
    state = _state(root, session)
    root_actor = state.session.root_actor_id
    expected = (
        session
        if host == "claude-code" or actor == root_actor
        else str(actor).removeprefix("codex:")
    )
    vendor = "CODEX_THREAD_ID" if host == "codex" else "CLAUDE_CODE_SESSION_ID"
    other = "CLAUDE_CODE_SESSION_ID" if host == "codex" else "CODEX_THREAD_ID"
    if environment.get(vendor) != expected or other in environment:
        raise ValueError("tool identity conflicts with native process")
    overlay = tuple(
        environment.get(k)
        for k in ("NEURATH_AGENT_SESSION_ID", "NEURATH_AGENT_ACTOR_ID", "NEURATH_AGENT_RUNTIME")
    )
    if any(x is not None for x in overlay) and overlay not in (
        (session, str(actor), host),
        (session, str(root_actor), host),
    ):
        raise ValueError("tool identity conflicts with inherited overlay")
    current = state.actors.get(actor)
    if (
        state.session.runtime.value != host
        or current is None
        or current.status is not ActorStatus.ACTIVE
        or (
            actor != root_actor
            and current.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
        )
    ):
        raise ValueError("tool actor is unavailable")
    return RuntimeIdentityBinding(
        runtime=SessionRuntime(host),
        session_id=SessionId(session),
        actor_id=actor,
        root_actor_id=root_actor,
    )


def resolve_native_codex(environment):
    """Use the native child thread id only after a unique host-attested registration."""
    from scripts.agent_harness.session_kernel import (
        ActorId,
        ActorLineageAssurance,
        ActorStatus,
        SessionRuntime,
    )
    from scripts.agent_harness.state_handle import RuntimeIdentityBinding

    native = environment.get("CODEX_THREAD_ID")
    root = os.environ.get("NEURATH_TARGET_ROOT")
    if native is None or root is None:
        return None
    if "CLAUDE_CODE_SESSION_ID" in environment:
        raise ValueError("multiple native identities")
    matches = []
    for data in _all_journals(root):
        if data.get("host") == "codex" and any(
            record.get("child") == native for record in data.get("spawns", {}).values()
        ):
            matches.append(data["session"])
    if not matches:
        return None
    from scripts.agent_harness.session_kernel import SessionStateStore
    if len(matches) != 1 or SessionStateStore(
        _path(root, native).parent / ".process-state.json"
    ).exists():
        raise ValueError("ambiguous native child identity")
    state = _state(root, matches[0])
    actor_id = ActorId(f"codex:{native}")
    actor = state.actors.get(actor_id)
    if (
        state.session.runtime is not SessionRuntime.CODEX
        or actor is None
        or actor.status is not ActorStatus.ACTIVE
        or actor.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
        or actor.parent_actor_id != state.session.root_actor_id
    ):
        raise ValueError("native child is not an active attested direct child")
    overlay = tuple(
        environment.get(k)
        for k in ("NEURATH_AGENT_SESSION_ID", "NEURATH_AGENT_ACTOR_ID", "NEURATH_AGENT_RUNTIME")
    )
    if any(x is not None for x in overlay) and overlay not in (
        (str(state.session.id), str(actor_id), "codex"),
        (str(state.session.id), str(state.session.root_actor_id), "codex"),
    ):
        raise ValueError("native child conflicts with inherited identity")
    return RuntimeIdentityBinding(
        runtime=SessionRuntime.CODEX,
        session_id=state.session.id,
        actor_id=actor_id,
        root_actor_id=state.session.root_actor_id,
    )


def prepare_delegation(root, delegation_id, assignment, environment=None):
    """Root-owned intent for the next native spawn, before its child ID exists."""
    from scripts.agent_harness.session_kernel import DelegationId
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle

    DelegationId(delegation_id)
    if len(delegation_id) > 128 or not assignment.strip() or len(assignment.encode()) > 8192:
        raise ValueError("delegation id or assignment exceeds its bounds")
    binding = RuntimeEnvironmentResolver().resolve(
        os.environ if environment is None else environment
    )
    handle = StateHandle.attach(_locator(root), binding)
    return prepare_bound_delegation(root, handle, delegation_id, assignment)


def prepare_bound_delegation(root, handle, delegation_id, assignment):
    """Native-bound core operation; no environment or caller identity input."""
    from scripts.agent_harness.session_kernel import DelegationId
    DelegationId(delegation_id)
    if len(delegation_id) > 128 or not assignment.strip() or len(assignment.encode()) > 8192:
        raise ValueError("delegation id or assignment exceeds its bounds")
    if handle.actor_id != handle.inspect().session.root_actor_id:
        raise ValueError("only the current root can prepare a direct-child delegation")
    state = handle.inspect()
    foreground = _foreground(state)
    with journal(root, str(handle.session_id)) as data:
        intents = data.setdefault("intents", {})
        candidate = {"assignment": assignment, "foreground": foreground, "call_id": None}
        existing = intents.get(delegation_id)
        if existing:
            if existing["assignment"] != assignment or existing["foreground"] != foreground:
                raise ValueError("delegation intent conflicts with existing authority")
        else:
            if any(
                i["foreground"] == foreground and i.get("call_id") is None for i in intents.values()
            ):
                raise ValueError("a delegation is already waiting for the next native spawn")
            intents[delegation_id] = candidate
    return {
        "status": "prepared",
        "delegation_id": delegation_id,
        "session_id": str(handle.session_id),
    }


def attach_delegation(root, host, payload):
    """Bind an explicit root intent using the actual registered native child."""
    from scripts.agent_harness.session_kernel import (
        ActorId,
        DelegationAssigned,
        DelegationId,
        DelegationTopologyPolicy,
        SessionKernel,
    )

    session, child = payload["session_id"], payload["agent_id"]
    state = _state(root, session)
    records = [
        (call, rec)
        for call, rec in snapshot(root, session)["spawns"].items()
        if rec.get("child") == child and rec.get("delegation") and rec.get("host") == host
    ]
    if not records:
        return None
    if len(records) != 1:
        raise ValueError("ambiguous child delegation")
    call, record = records[0]
    intent = record["delegation"]
    existing = state.delegations.get(DelegationId(intent["id"]))
    if existing:
        if (
            existing.owner_actor_id != state.session.root_actor_id
            or existing.target_actor_id != ActorId(f"{host}:{child}")
            or existing.assignment != intent["assignment"]
        ):
            raise ValueError("native delegation conflicts with existing assignment")
        return intent["id"]
    if record["foreground"] != _foreground(state) or record["parent"] != str(
        state.session.root_actor_id
    ):
        raise ValueError("delegation belongs to an obsolete root foreground turn")
    intent = record["delegation"]
    SessionKernel(_locator(root)).apply(
        DelegationAssigned(
            session_id=state.session.id,
            delegation_id=DelegationId(intent["id"]),
            owner_actor_id=state.session.root_actor_id,
            target_actor_id=ActorId(f"{host}:{child}"),
            assignment=intent["assignment"],
            topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            idempotency_key=f"native-delegation:{host}:{call}",
        ),
        expected_revision=state.revision,
    )
    return intent["id"]


def _latest_codex_turn(path):
    """Find the current lifecycle beyond recall's tail budget, with bounded memory."""
    ended = set()
    for item in _reverse_native_lifecycle(path):
        turn = item.get("turn_id")
        if not isinstance(turn, str) or not turn:
            continue
        if item["type"] == "task_started":
            return "" if turn in ended else turn
        ended.add(turn)
    return "" if ended else None


def _reverse_native_lifecycle(path):
    kinds = {"task_started", "task_complete", "task_completed", "turn_aborted"}
    for event in _reverse_native_records(path, kinds):
        item = event.get("payload")
        if (event.get("type") == "event_msg" and isinstance(item, dict)
                and item.get("type") in kinds):
            yield item


def _reverse_native_records(path, needles):
    """Scan complete lines backwards; huge message records cannot hide lifecycle.

    Lifecycle envelopes are small. Oversized non-lifecycle lines are skipped as
    whole records, never parsed from a fragment. No transcript tail limit applies.
    """
    needles = tuple(('"' + kind + '"').encode() for kind in needles)

    def parse(line):
        if len(line) > 1024 * 1024:
            return {"type": "oversized_native_record"}
        if not any(word in line for word in needles):
            return None
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return None
        return event if isinstance(event, dict) else None

    with Path(path).open("rb") as stream:
        position = stream.seek(0, 2)
        tail, skipping = b"", False
        while position:
            size = min(position, 65536)
            position -= size
            stream.seek(position)
            parts = stream.read(size).split(b"\n")
            if len(parts) == 1:
                if skipping or len(parts[0]) + len(tail) > 1024 * 1024:
                    tail, skipping = b"", True
                else:
                    tail = parts[0] + tail
                continue
            if skipping:
                yield {"type": "oversized_native_record"}
            else:
                item = parse(parts[-1] + tail)
                if item is not None:
                    yield item
            for line in reversed(parts[1:-1]):
                item = parse(line)
                if item is not None:
                    yield item
            tail, skipping = parts[0], False
        if skipping:
            yield {"type": "oversized_native_record"}
        else:
            item = parse(tail)
            if item is not None:
                yield item


def resume_child(root, host, payload, environment):
    """Reopen only an existing child whose host transcript proves a fresh live turn."""
    if host != "codex":
        return False
    from scripts.agent_harness.session_kernel import (
        ActorId, ActorLineageAssurance, ActorResumed, ActorStatus,
        ForegroundTurnPrompted, ForegroundTurnStatus, RevisionConflict, SessionKernel,
    )

    session, child = payload["session_id"], payload["agent_id"]
    state = _state(root, session)
    _foreground(state)  # The attested parent must still be executing an active turn.
    actor_id = ActorId(f"{host}:{child}")
    actor = state.actors.get(actor_id)
    turn = state.foreground_turns.get(actor_id)
    if actor is None or turn is None:
        return False
    path = _transcript(host, payload["transcript_path"], environment)
    record = _first_record(path)
    meta = record.get("payload", {})
    spawn = meta.get("source", {}).get("subagent", {}).get("thread_spawn", {})
    native_turn = payload.get("turn_id")
    if (record.get("type") != "session_meta" or meta.get("id") != child
            or meta.get("session_id") != session or meta.get("parent_thread_id") != session
            or spawn.get("parent_thread_id") != session
            or not isinstance(native_turn, str) or not native_turn
            or _latest_codex_turn(path) != native_turn):
        return False
    witnesses = [value for value in snapshot(root, session)["spawns"].values()
                 if value.get("host") == host and value.get("child") == child
                 and value.get("parent") == str(state.session.root_actor_id)
                 and (value.get("returned_child") == child
                      or (meta.get("agent_path") and value.get("native_path") == meta["agent_path"]))]
    if len(witnesses) != 1:
        return False

    def already_resumed(current, generation=None):
        _foreground(current)
        child_actor = current.actors.get(actor_id)
        child_turn = current.foreground_turns.get(actor_id)
        return (child_actor is not None and child_actor.status is ActorStatus.ACTIVE
                and child_actor.lineage_assurance is ActorLineageAssurance.HOST_ATTESTED
                and child_actor.parent_actor_id == current.session.root_actor_id
                and child_turn is not None and child_turn.status is ForegroundTurnStatus.ACTIVE
                and child_turn.vendor_turn_id == native_turn
                and (generation is None or child_turn.generation == generation)
                and _latest_codex_turn(path) == native_turn)

    if native_turn == turn.vendor_turn_id:
        return already_resumed(state)
    if actor.status is ActorStatus.ACTIVE:
        if (turn.status is not ForegroundTurnStatus.CLOSED
                or actor.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
                or actor.parent_actor_id != state.session.root_actor_id):
            return False
        # Some native follow-ups deliver PreToolUse without UserPromptSubmit.
        # The fresh host turn reopens execution, not human prompt authority.
        event = ForegroundTurnPrompted(
            session_id=state.session.id, actor_id=actor_id, vendor_turn_id=native_turn,
            prompt_digest=None, authority_context=None,
            idempotency_key=f"native-child-followup:{child}:{native_turn}")
    else:
        event = ActorResumed(session_id=state.session.id, actor_id=actor_id,
            parent_actor_id=state.session.root_actor_id, expected_turn_revision=turn.revision,
            vendor_turn_id=native_turn, idempotency_key=f"native-child-resume:{child}:{native_turn}")
    try:
        SessionKernel(_locator(root)).apply(event, expected_revision=state.revision)
    except RevisionConflict:
        return already_resumed(_state(root, session), turn.generation + 1)
    return True


def reconcile_child_prompt(root, host, payload, environment):
    """Bind a verified child's actual native turn, including startup placeholders."""
    if host != "codex":
        return
    from scripts.agent_harness.session_kernel import (
        ActorId, ForegroundTurnReplaced, ForegroundTurnStatus, SessionKernel,
    )

    path = _transcript(host, payload["transcript_path"], environment)
    meta = _first_record(path).get("payload", {})
    session, child = payload["session_id"], payload["agent_id"]
    if (not isinstance(payload.get("turn_id"), str) or not payload["turn_id"]
            or meta.get("id") != child or meta.get("session_id") != session
            or meta.get("parent_thread_id") != session
            or _latest_codex_turn(path) != payload.get("turn_id")):
        raise ValueError("child prompt lacks current native turn provenance")
    state = _state(root, session)
    actor = ActorId(f"codex:{child}")
    turn = state.foreground_turns.get(actor)
    if (turn is None or turn.status is ForegroundTurnStatus.CLOSED
            or turn.vendor_turn_id in (None, payload.get("turn_id"))):
        return
    state = _settle_interrupted_action(root, state, native_turn=payload["turn_id"], actor_id=actor)
    SessionKernel(_locator(root)).apply(
        ForegroundTurnReplaced(
            session_id=state.session.id, actor_id=actor, expected_turn_revision=turn.revision,
            replacement_reference=f"codex-turn:{payload['turn_id']}",
            idempotency_key=f"native-child-turn:{child}:{turn.generation}:{turn.revision}",
        ), expected_revision=state.revision,
    )


def validate_tool_foreground(root, host, payload, environment):
    """Deferred human input cannot lend the previous Codex turn's tool authority."""
    if host != "codex" or payload.get("agent_id") or not payload.get("turn_id"):
        return
    session = payload.get("session_id")
    if not session:
        return
    data = snapshot(root, session)
    if not data.get("transcript"):
        return
    path = _transcript(host, payload["transcript_path"], environment)
    _validate_root_transcript(root, host, payload, path, data)
    state = _state(root, session)
    turn = state.foreground_turns.get(state.session.root_actor_id)
    if turn is None or turn.vendor_turn_id != payload["turn_id"]:
        if turn is None or not _native_peer_turn(root, path, session, payload["turn_id"]):
            raise ValueError("native tool turn is not reconciled with the foreground prompt")
        _resume_peer_foreground(root, session, path, payload["turn_id"])
    elif turn.user_prompt_receipt is None:
        from scripts.agent_harness.session_kernel import ForegroundTurnStatus

        if (turn.status is ForegroundTurnStatus.CLOSED
                or _latest_codex_turn(path) != payload["turn_id"]):
            raise ValueError("native peer turn is no longer active")


def native_root_turn(root, path, session, turn_id):
    """Read-only proof of the exact live Codex root turn."""
    try:
        record = _first_record(path)
        meta = record["payload"]
        if (record["type"] != "session_meta" or meta["id"] != session
                or meta.get("session_id", session) != session
                or meta.get("source") not in ("vscode", "cli", "exec")
                or not _independent_root_source(meta)
                or any(meta.get(k) for k in (
                    "parent_thread_id", "parent_session_id", "agent_id"))
                or meta.get("agent_path") not in (None, "/root")
                or Path(meta["cwd"]).resolve() != Path(root).resolve()
                or _latest_codex_turn(path) != turn_id):
            return False
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
    return True


def _native_context_refresh(item, turn_id):
    """Only host-classified context is not a human prompt; never inspect its text."""
    metadata = item.get("internal_chat_message_metadata_passthrough")
    if not isinstance(metadata, dict) or metadata.get("turn_id") != turn_id:
        return False
    kinds = metadata.get("content_item_kinds")
    return (isinstance(kinds, list) and bool(kinds)
            and all(isinstance(kind, str) and kind in {
                "agents_md.instructions", "environments.environment_context",
            } for kind in kinds))


def _native_peer_turn(root, path, session, turn_id):
    """Require paired host delivery records; message text grants no authority."""
    if not native_root_turn(root, path, session, turn_id):
        return False

    def delivery(item):
        if (not isinstance(item, dict) or "call_id" in item
                or item.get("name") != "send_message_to_thread"
                or item.get("namespace") != "codex_app"
                or not isinstance(item.get("id"), str)
                or not item["id"].startswith("fco_")
                or not isinstance(item.get("output"), str)):
            return None
        return item["id"], hashlib.sha256(item["output"].encode()).hexdigest()

    completed, verified = None, False
    for record in _reverse_native_records(path, {
        "task_started", "item_completed", "function_call_output", "message",
    }):
        if record.get("type") == "oversized_native_record":
            return False  # Its size cannot hide an unreconciled human prompt.
        item = record.get("payload")
        if not isinstance(item, dict):
            continue
        if record.get("type") == "event_msg":
            if item.get("type") == "task_started":
                return verified and item.get("turn_id") == turn_id
            native = item.get("item")
            if (item.get("type") == "item_completed"
                    and item.get("thread_id") == session and item.get("turn_id") == turn_id
                    and isinstance(native, dict) and native.get("type") == "FunctionCallOutput"):
                completed = delivery(native)
        elif record.get("type") == "response_item":
            if (item.get("type") == "message" and item.get("role") == "user"
                    and not _native_context_refresh(item, turn_id)):
                return False  # A deferred human prompt still needs its own reconciliation.
            metadata = item.get("internal_chat_message_metadata_passthrough")
            if (item.get("type") == "function_call_output"
                    and isinstance(metadata, dict) and metadata.get("turn_id") == turn_id
                    and completed is not None and delivery(item) == completed):
                verified = True
    return False


def _resume_peer_foreground(root, session, path, turn_id):
    """Reconcile execution provenance without creating a user prompt receipt."""
    from scripts.agent_harness.session_kernel import (
        ForegroundTurnPrompted, ForegroundTurnReplaced, ForegroundTurnStatus, SessionKernel,
    )

    with journal(root, session) as data:
        if not _native_peer_turn(root, path, session, turn_id):
            raise ValueError("peer delivery changed before foreground reconciliation")
        state = _state(root, session)
        actor = state.session.root_actor_id
        turn = state.foreground_turns[actor]
        if turn.vendor_turn_id == turn_id:
            if turn.status is ForegroundTurnStatus.CLOSED:
                raise ValueError("native peer turn is no longer active")
            return
        state = _settle_interrupted_action(root, state, native_turn=turn_id)
        kernel = SessionKernel(_locator(root))
        if turn.status is not ForegroundTurnStatus.CLOSED:
            state = kernel.apply(ForegroundTurnReplaced(
                session_id=state.session.id, actor_id=actor, expected_turn_revision=turn.revision,
                replacement_reference=f"codex-turn:{turn_id}",
                idempotency_key=f"native-peer-close:{turn_id}:{turn.generation}:{turn.revision}",
            ), expected_revision=state.revision)
        kernel.apply(ForegroundTurnPrompted(
            session_id=state.session.id, actor_id=actor, vendor_turn_id=turn_id,
            prompt_digest=None, authority_context=None,
            idempotency_key=f"native-peer-turn:{turn_id}",
        ), expected_revision=state.revision)
        data.update(transcript=str(path), resume_pending=None, connected=True)


def resume_foreground(root, host, payload, environment):
    """Retire only an exact interrupted native turn; never complete its workflow."""
    from scripts.agent_harness.session_kernel import (
        ForegroundTurnReplaced,
        ForegroundTurnStatus,
        SessionKernel,
    )

    if payload.get("agent_id") or not isinstance(payload.get("prompt"), str):
        return
    session = payload["session_id"]
    current = snapshot(root, session)
    pending = current.get("resume_pending")
    if not pending and (not current.get("transcript") or not payload.get("transcript_path")):
        return
    path = _transcript(host, payload["transcript_path"], environment)
    if (
        pending
        and host == "codex"
        and (not isinstance(payload.get("turn_id"), str) or not payload["turn_id"])
    ):
        raise ValueError("Codex resume requires a native turn id")
    with journal(root, session) as data:
        if data.get("resume_pending") != pending or data.get("transcript") != current.get(
            "transcript"
        ):
            raise ValueError("resume state changed while validating the request")
        _validate_root_transcript(root, host, payload, path, data)
        state = _state(root, session)
        if state.session.runtime.value != host:
            raise ValueError("resume runtime mismatch")
        turn = state.foreground_turns.get(state.session.root_actor_id)
        latest = _latest_codex_turn(path) if host == "codex" else None
        if latest is not None and latest != payload.get("turn_id"):
            raise ValueError("prompt does not match the current native turn start")
        if not pending:
            # Interrupt/new-input does not necessarily emit SessionStart. Only
            # the current native task-start record can retire an unclosed turn;
            # a different ID in a replayed hook is not sufficient evidence.
            if (
                host != "codex"
                or turn is None
                or turn.status is ForegroundTurnStatus.CLOSED
                or turn.vendor_turn_id is None
                or payload.get("turn_id") in (None, turn.vendor_turn_id)
            ):
                data["transcript"] = str(path)
                return
            if latest != payload.get("turn_id"):
                raise ValueError("new foreground prompt lacks the current native turn start")
            pending = _resume_snapshot(turn)
        observed = None if turn is None else _resume_snapshot(turn)
        # Compaction may be followed by a normal Stop before the next prompt.
        # Only the exact close transition (same identity, revision +1) is stale
        # bookkeeping; newer generations or steering revisions remain invalid.
        closed_after_snapshot = (
            turn is not None
            and turn.status is ForegroundTurnStatus.CLOSED
            and observed == {**pending, "revision": pending["revision"] + 1}
        )
        if observed != pending and not closed_after_snapshot:
            if latest and latest == payload.get("turn_id") and turn is not None:
                # A live host start supersedes stale resume bookkeeping, including
                # steering accepted since the compact/resume snapshot was taken.
                pending = observed
            else:
                raise ValueError("resume event is stale for the current foreground")
        same_turn = host == "codex" and payload.get("turn_id") == pending["turn"]
        same_prompt = hashlib.sha256(payload["prompt"].encode()).hexdigest() == pending["prompt"]
        # Repeating the same words in a different native turn is still a new
        # turn. Text equality is only a fallback for hosts without turn IDs.
        replay = same_turn if host == "codex" else same_prompt
        if turn.status is not ForegroundTurnStatus.CLOSED and not replay:
            state = _settle_interrupted_action(root, state, native_turn=latest)
            replacement_reference = (
                f"{host}-turn:{latest}"
                if latest is not None
                else "claude-code-prompt:sha256:"
                + hashlib.sha256(payload["prompt"].encode()).hexdigest()
            )
            SessionKernel(_locator(root)).apply(
                ForegroundTurnReplaced(
                    session_id=state.session.id,
                    actor_id=state.session.root_actor_id,
                    expected_turn_revision=turn.revision,
                    replacement_reference=replacement_reference,
                    idempotency_key=f"native-resume:{host}:{turn.generation}:{turn.revision}",
                ),
                expected_revision=state.revision,
            )
        data.update(transcript=str(path), resume_pending=None)


def _settle_interrupted_action(root, state, *, native_turn=None, actor_id=None):
    """Keep original observations; insufficient evidence is BLOCKED, not success.

    Settlement and foreground close each use process CAS. An interruption between
    them leaves a valid resolved batch and permits retrying the exact resume.
    A verified successor can abandon an unfinished tool execution as UNKNOWN/BLOCKED.
    Without that evidence, the kernel's typed resume recovery is required.
    """
    from scripts.agent_harness.session_kernel import (
        MaterialActionAbandoned,
        MaterialActionResolved,
        MaterialActionResolution,
        MaterialActionStatus,
        SessionKernel,
    )

    actor = actor_id or state.session.root_actor_id
    batch = state.material_actions.get(actor)
    if batch is None or batch.status is not MaterialActionStatus.OPEN:
        return state
    if batch.in_flight is not None:
        if not native_turn:
            raise ValueError("resume requires recovery of the interrupted tool result")
        turn = state.foreground_turns[actor]
        return SessionKernel(_locator(root)).apply(
            MaterialActionAbandoned(
                session_id=state.session.id,
                actor_id=actor,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                expected_turn_generation=turn.generation,
                invocation_id=batch.in_flight.invocation_id,
                idempotency_key=f"native-turn-abandoned:{native_turn}:{batch.sequence}",
            ),
            expected_revision=state.revision,
        )
    resolution = (
        MaterialActionResolution.COMPLETED
        if batch.invocations and batch.delta_assessment.is_complete
        else MaterialActionResolution.BLOCKED
    )
    return SessionKernel(_locator(root)).apply(
        MaterialActionResolved(
            session_id=state.session.id,
            actor_id=actor,
            batch_id=batch.batch_id,
            expected_batch_revision=batch.revision,
            resolution=resolution,
            idempotency_key=f"native-resume-action:{batch.sequence}:{batch.revision}",
        ),
        expected_revision=state.revision,
    )


def require_process_receipt(environment):
    """A registered Claude native shell cannot drop its token to become root."""
    session = environment.get("CLAUDE_CODE_SESSION_ID")
    root = os.environ.get("NEURATH_TARGET_ROOT")
    if root and session and "NEURATH_TOOL_BINDING" not in environment:
        if _journal_exists(root, session) and snapshot(root, session).get("host") == "claude-code":
            raise ValueError("native Claude process requires its active tool identity record")
