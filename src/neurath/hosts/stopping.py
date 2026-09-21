"""Validate Stop without using unfinished work as an automatic retry request.

Kernel completion gates remain authoritative. A host may return a response
without marking tasks complete or granting any new execution authority.
"""

import os
from contextlib import contextmanager


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

    return guard


def dispatch_stop(root, host, request, run, environment=None):
    """Validate completion without turning a denial into a model invocation.

    A failed canonical close remains failed. Return a nonblocking hook error
    so the host can finish the response while unfinished work stays durable.
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
        guard = _admission(root, host, request, environment)
        code, output, diagnostic = run(guard)
    except Exception as error:
        diagnostic = "Neurath Stop deferred: " + clean(f"{type(error).__name__}: {error}")[:2000]
        return 1, {}, diagnostic
    if code == 0:
        return code, output, diagnostic
    # Host response delivery and canonical task completion are separate. A
    # pending task, workflow, or failed validation is not authority to ask the
    # host to spend another model turn. Preserve the failed close and explain
    # it through stderr; never emit a blocking decision or an exit-2 retry.
    reason = clean(diagnostic)[:4000] or "The completion prerequisites are unresolved."
    return 1, {}, "Neurath completion deferred; unfinished work is preserved: " + reason
