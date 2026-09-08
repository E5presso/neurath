"""Project mailbox delivery through successful, identity-checked native host hooks."""

from pathlib import Path

from neurath.agents.newsroom import Newsroom
from neurath.agents.store import AgentIdentity, MessageStore
from neurath.memory.store import canonical


def native_turn(root, identity):
    from scripts.agent_harness.session_kernel import ActorId, SessionId, SessionKernel

    from neurath.hosts.identity import _locator

    state = SessionKernel(_locator(root)).inspect(SessionId(identity.session))
    turn = state.foreground_turns.get(ActorId(identity.actor))
    if turn is None or turn.status.value != "active":
        raise ValueError("task acceptance requires an active native turn")
    return canonical([turn.generation, turn.vendor_turn_id])


def lifecycle_event(store, identity, state, actor, payload):
    from neurath.agents.lifecycle import TaskLifecycle

    tasks = TaskLifecycle(store)
    event = payload.get("hook_event_name")
    turn = state.foreground_turns.get(actor.id)
    turn_key = canonical([turn.generation, turn.vendor_turn_id]) if turn else ""
    if not identity.is_root and actor.parent_actor_id is not None and turn:
        parent = state.actors.get(actor.parent_actor_id)
        if parent is not None:
            issuer = AgentIdentity(identity.host, identity.session, str(parent.id),
                                   parent.id == state.session.root_actor_id)
            # Parent lineage was attested by the host before this hook was admitted.
            store.register(issuer, status="active" if participation(state, parent)[0] else "idle")
            task = tasks.bind(issuer.address, identity.address,
                key=f"native:{identity.actor}:{turn.generation}", transport="native-subagent")
            if task["state"] == "assigned" and event not in {"SubagentStop", "SessionEnd"}:
                tasks.accept(identity.address, task["id"], turn_key)
    target_state = {"Stop": "completed", "SubagentStop": "completed", "SessionEnd": "disconnected",
                    "PermissionDenied": "waiting", "PostToolUseFailure": "error"}.get(event)
    if not target_state:
        return
    for task in tasks.active(identity.address):
        if task["transport"] not in {"native-subagent", "peer-assignment"} or task["turn"] != turn_key:
            continue
        tasks.emit(identity.address, task["id"], target_state,
                   key=canonical([event, turn_key, payload.get("tool_use_id")]),
                   detail="Observed native " + event + "; implementation correctness is not attested.")


def native_peer(root, host, payload):
    from scripts.agent_harness.session_kernel import (
        ActorId,
        ActorLineageAssurance,
        SessionId,
        SessionKernel,
    )

    from neurath.hosts.identity import _locator, snapshot

    session = payload.get("session_id")
    if not session:
        return None
    state = SessionKernel(_locator(root)).inspect(SessionId(session))
    registered = snapshot(root, session)
    if (
        state.session.runtime.value != host
        or registered.get("host") != host
        or not registered.get("transcript")
    ):
        return None
    # Only the already registered native transcript may refresh the root endpoint.
    if (payload.get("transcript_path") and not payload.get("agent_id")
            and str(Path(payload["transcript_path"]).resolve()) != registered["transcript"]):
        return None
    actor_id = (
        ActorId(f"{host}:{payload['agent_id']}")
        if payload.get("agent_id")
        else state.session.root_actor_id
    )
    actor = state.actors.get(actor_id)
    if actor is None or (
        payload.get("agent_id")
        and actor.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
    ):
        return None
    identity = AgentIdentity(host, session, str(actor_id), not bool(payload.get("agent_id")))
    return identity, state, actor


def participation(state, actor):
    turn = state.foreground_turns.get(actor.id)
    active = (state.session.status.value == "active" and actor.status.value == "active"
              and turn is not None and turn.status.value == "active")
    key = canonical([turn.generation, turn.vendor_turn_id]) if turn else "no-native-turn"
    return active, key


def peer_event(root, host, payload, output):
    peer = native_peer(root, host, payload)
    if peer is None:
        return output
    identity, state, actor = peer
    store = MessageStore(root)
    event = payload.get("hook_event_name")
    status = {"Stop": "idle", "SubagentStop": "paused", "SessionEnd": "paused"}.get(event, "active")
    store.register(identity, status=status)
    lifecycle_event(store, identity, state, actor, payload)
    active, turn = participation(state, actor)
    if event == "SessionStart" and payload.get("source") != "compact":
        active = False  # A resumed process has not yet accepted its new prompt.
    room = Newsroom(store)
    room.pulse(identity.address, active=active and status == "active", turn=turn)
    if event == "SessionEnd":
        room.retire_session(host, identity.session)
    if event not in ("SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"):
        return output
    context = store.context(identity.address)
    if active and status == "active":
        delivery = canonical([event, turn, payload.get("tool_use_id"),
                              state.foreground_turns[actor.id].revision])
        news = room.context(identity.address, delivery=delivery)
        if news:
            context += ("\n\n" if context else "") + news
    if event in ("SessionStart", "SubagentStart"):
        context = (
            f"Neurath agent address: {identity.address}. Prefer collaboration_discover to find peers.\n"
            "Newsroom is global across active project agents. Publish useful discoveries with "
            "newsroom_publish(title, body, key), title <=30 characters. "
            "Only titles are pushed; use newsroom_read for relevant bodies explicitly. "
            "Use named neurath_collaboration MCP task tools and their structured inputs. "
            "Report unavailable tools or unsupported policies without CLI replay. Do not wake inactive peers.\n"
            + context
        )
    if not context:
        return output
    result = dict(output)
    specific = dict(result.get("hookSpecificOutput", {}))
    specific.setdefault("hookEventName", event)
    previous = specific.get("additionalContext", "")
    specific["additionalContext"] = previous + ("\n\n" if previous else "") + context
    result["hookSpecificOutput"] = specific
    return result
