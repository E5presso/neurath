"""Keep the current native turn running until its completion gates are met."""

import os
from contextlib import contextmanager


def _signature(state, actor_id):
    turn = state.foreground_turns.get(actor_id)
    actor = state.actors.get(actor_id)
    return (state.session.id, state.session.status, state.session.last_lifecycle_idempotency_key,
            None if actor is None else actor.to_payload(),
            None if turn is None else turn.to_payload())


def _lifecycle_signature(state, actor_id):
    turn = state.foreground_turns.get(actor_id)
    actor = state.actors.get(actor_id)
    return (state.session.status, state.session.last_lifecycle_idempotency_key,
            None if actor is None else actor.status,
            None if turn is None else (turn.generation, turn.vendor_turn_id,
                None if turn.user_prompt_receipt is None else turn.user_prompt_receipt.to_payload()))


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
    lifecycle = _lifecycle_signature(state, binding.actor_id)
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

    def current():
        from scripts.agent_harness.session_kernel import SessionKernel
        from neurath.hosts.identity import _locator

        latest = SessionKernel(_locator(root)).inspect(state.session.id)
        return (_lifecycle_signature(latest, binding.actor_id) == lifecycle
                and unchanged(snapshot(root, request["session_id"])))

    return guard, current


def dispatch_stop(root, host, request, run, environment=None):
    """Preserve a current turn's blocking denial; acknowledge superseded events."""
    from neurath.redaction import clean

    current = None
    try:
        # The read-only stale/terminal route grants no completion or retry.
        from neurath.hosts.hooks import _readonly_root_stop
        from neurath.runtime.engine import activate

        activate(root)
        readonly = _readonly_root_stop(root, host, request, environment)
        if readonly is not None:
            code, output, diagnostic = readonly
            return (0 if code == 0 else 1), output, diagnostic
        guard, current = _admission(root, host, request, environment)
        code, output, diagnostic = run(guard)
    except Exception as error:
        diagnostic = "Neurath Stop deferred: " + clean(f"{type(error).__name__}: {error}")[:2000]
        code, output = 2, {}
    if current is None:
        return 1, {}, diagnostic
    if code == 0:
        return code, output, diagnostic
    try:
        if not current():
            return 1, {}, "Neurath stale Stop acknowledged; current user activity is preserved."
    except Exception:
        # Losing readback after verified ingress cannot authorize completion.
        pass
    reason = clean(diagnostic)[:4000] or "The completion prerequisites are unresolved."
    return 2, {}, "Neurath completion blocked; continue the authorized work: " + reason


def bypass_stop(root, host, request, environment=None):
    """Bypass ancillary harness rules, not registered unfinished user tasks."""
    def check(guard):
        from pathlib import Path
        from scripts.agent_harness.runtime_database import RuntimeDatabase
        from scripts.agent_harness.session_kernel import SessionLocator, SessionRuntime, SessionStateStore
        from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle
        from scripts.agent_harness.task_service import require_settled_tasks

        locator = SessionLocator.from_worktree(Path(root))
        binding = RuntimeEnvironmentResolver().resolve_hook_actor(
            os.environ if environment is None else environment, None, request['session_id'],
            hook_runtime=SessionRuntime(host))
        handle = StateHandle.attach(locator, binding)
        state = handle.inspect()
        with guard(state, handle), RuntimeDatabase(locator.control_root).transaction() as tx:
            process = SessionStateStore(locator.locate(binding.session_id).process_state).read_transaction(
                tx, binding.session_id)
            require_settled_tasks(tx, process)
        return 0, {}, ''

    return dispatch_stop(root, host, request, check, environment)
