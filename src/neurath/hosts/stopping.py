"""Bound host continuation separately from kernel completion and tool authority.

A Stop rejection asks the host to run the model again. It is not an execution
security boundary. Unresolved work remains unresolved when control returns to
the user; only the existing domain gate can close a foreground turn.
"""

import os
from contextlib import contextmanager
from pathlib import Path


def _budget_key(actor_id, turn):
    prompt = turn.user_prompt_receipt
    return {"actor": str(actor_id), "generation": turn.generation,
            "native_turn": turn.vendor_turn_id,
            "prompt_revision": None if prompt is None else prompt.turn_revision}


def _signature(state, actor_id):
    turn = state.foreground_turns.get(actor_id)
    actor = state.actors.get(actor_id)
    return (state.session.id, state.session.status, state.session.last_lifecycle_idempotency_key,
            None if actor is None else actor.to_payload(),
            None if turn is None else turn.to_payload())


def _admission(root, host, request, environment):
    """Freeze the ingress snapshot; callers cannot supply this guard in JSON."""
    from scripts.agent_harness.agent_continuation_hook import AgentContinuationBlocked
    from scripts.agent_harness.session_kernel import SessionRuntime
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver
    from neurath.hosts.identity import _state, journal, snapshot

    binding = RuntimeEnvironmentResolver().resolve_hook_actor(
        os.environ if environment is None else environment,
        request.get("agent_id"), request.get("session_id"), hook_runtime=SessionRuntime(host),
    )
    state = _state(root, request["session_id"])
    turn = state.foreground_turns.get(binding.actor_id)
    if turn is None:
        raise ValueError("Stop ingress has no foreground turn")
    expected = _signature(state, binding.actor_id)
    initial = snapshot(root, request["session_id"])

    def unchanged(current):
        return (current.get("connected") is not False
                and all(current.get(key) == initial.get(key)
                        for key in ("host", "transcript", "connected", "resume_pending")))

    @contextmanager
    def guard(current_state, handle):
        # Lifecycle host records use the same journal lock. Hold it only for
        # canonical mutations, never across external validation. The domain close
        # additionally compares the captured kernel revision, so a later prompt
        # cannot be retired by an older Stop that has no vendor turn ID.
        with journal(root, request["session_id"]) as current:
            if (handle.actor_id != binding.actor_id
                    or _signature(current_state, binding.actor_id) != expected
                    or not unchanged(current)):
                raise AgentContinuationBlocked("Stop ingress changed before completion")
            yield

    return guard, _budget_key(binding.actor_id, turn), unchanged


def _turn_key(root, host, request, environment):
    from scripts.agent_harness.session_kernel import ActorStatus, ForegroundTurnStatus, SessionRuntime
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver

    from neurath.hosts.identity import (
        _state, _transcript, _validate_root_transcript, native_root_turn, snapshot,
    )

    binding = RuntimeEnvironmentResolver().resolve_hook_actor(
        os.environ if environment is None else environment,
        request.get("agent_id"), request.get("session_id"), hook_runtime=SessionRuntime(host),
    )
    if (not binding.is_root or request.get("hook_event_name") != "Stop"
            or any(request.get(key) is not None for key in (
                "actor_id", "parent_actor_id", "parent_thread_id", "parent_session_id"))
            or request.get("thread_id") not in (None, request.get("session_id"))
            or request.get("runtime") not in (None, host)
            or not isinstance(request.get("cwd"), str)
            or Path(request["cwd"]).resolve() != Path(root).resolve()):
        raise ValueError("Stop continuation lacks an independent root binding")
    state = _state(root, request["session_id"])
    actor = state.actors.get(binding.actor_id)
    if (state.session.runtime is not binding.runtime
            or state.session.root_actor_id != binding.actor_id
            or actor is None or actor.parent_actor_id is not None
            or actor.status not in {ActorStatus.ACTIVE, ActorStatus.IDLE}):
        raise ValueError("Stop continuation root binding changed")
    turn = state.foreground_turns.get(binding.actor_id)
    if turn is None or turn.status is not ForegroundTurnStatus.ACTIVE:
        raise ValueError("Stop continuation requires an active foreground")
    data = snapshot(root, request["session_id"])
    if data.get("host") != host or not data.get("transcript") or data.get("connected") is False:
        raise ValueError("Stop continuation requires a registered native transcript")
    path = _transcript(host, request["transcript_path"],
                       os.environ if environment is None else environment)
    _validate_root_transcript(root, host, request, path, data)
    if host == "codex" and (
        not request.get("turn_id") or turn.vendor_turn_id != request["turn_id"]
        or not native_root_turn(root, path, request["session_id"], request["turn_id"])
    ):
        raise ValueError("Stop continuation lacks the current native turn")
    return _budget_key(binding.actor_id, turn)


def _deferred(reason):
    message = "Neurath work remains incomplete. " + reason
    return 0, {"continue": False, "stopReason": message, "systemMessage": message}, message


def dispatch_stop(root, host, request, run, environment=None):
    """Permit at most one repair continuation per attested foreground turn.

The native continuation flag handles normal hosts. The locked per-turn budget
also handles duplicate events or a replay with a missing/incorrect flag. It
records a delivery budget only, never a kernel transition or ownership grant.
"""
    from neurath.memory.store import clean

    try:
        # The read-only stale/terminal route grants no completion or retry.
        from neurath.hosts.hooks import _readonly_root_stop
        from neurath.runtime.engine import activate

        activate(root)
        readonly = _readonly_root_stop(root, host, request, environment)
        if readonly is not None:
            code, output, diagnostic = readonly
            return (0 if code == 0 else 1), output, diagnostic
        guard, initial_key, unchanged = _admission(root, host, request, environment)
        code, output, diagnostic = run(guard)
    except Exception as error:
        diagnostic = "Neurath Stop deferred: " + clean(f"{type(error).__name__}: {error}")[:2000]
        return 1, {}, diagnostic
    if code == 0:
        return code, output, diagnostic
    # No malformed/foreign event or unavailable state may request another turn.
    try:
        key = _turn_key(root, host, request, environment)
        if key != initial_key:
            raise ValueError("Stop ingress changed before continuation")
    except Exception as error:
        reason = clean(f"{diagnostic}; {type(error).__name__}: {error}")[:2000]
        return 1, {}, "Neurath Stop deferred without completion or authority: " + reason
    reason = clean(diagnostic)[:4000] or "The completion prerequisites are unresolved."
    if request.get("stop_hook_active") is not False:
        return _deferred(reason)
    from neurath.hosts.identity import journal

    try:
        with journal(root, request["session_id"]) as data:
            if _turn_key(root, host, request, environment) != key or not unchanged(data):
                raise ValueError("Stop turn changed before continuation delivery")
            if data.get("stop_continuation") == key:
                return _deferred(reason)
            data["stop_continuation"] = key
    except Exception as error:
        return 1, {}, "Neurath Stop continuation deferred: " + clean(str(error))[:2000]
    return 0, {"decision": "block", "reason": reason}, ""
