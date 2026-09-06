"""Project mailbox delivery through successful, identity-checked native host hooks."""

from pathlib import Path

from neurath.agents.newsroom import Newsroom
from neurath.agents.store import AgentIdentity, MessageStore
from neurath.memory.store import canonical


def native_peer(root, host, payload):
    from neurath.hosts.identity import _locator, snapshot
    from scripts.agent_harness.session_kernel import (
        ActorId, ActorLineageAssurance, SessionId, SessionKernel,
    )

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
    if payload.get("transcript_path") and not payload.get("agent_id"):
        if str(Path(payload["transcript_path"]).resolve()) != registered["transcript"]:
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
            f"Neurath agent address: {identity.address}. Discover peers with .neurath/run agent discover.\n"
            "Newsroom is global across active project agents. Publish useful discoveries with "
            "newsroom publish --title TITLE --body BODY --key KEY (title <=30 characters). "
            "Only titles are pushed; read relevant articles explicitly. Use .neurath/run or "
            "the neurath_collaboration agent tool with argv. Do not wake inactive peers.\n"
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
