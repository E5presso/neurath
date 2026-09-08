"""Adapt process disconnects to the durable, resumable Neurath session lifetime."""

import json

from scripts.agent_harness.runtime_adapter import RuntimeCapability
from scripts.agent_harness.runtime_hook import (
    RuntimeHookApplication,
    RuntimeHookDiagnostic,
    RuntimeHookFailure,
)
from scripts.agent_harness.session_kernel import SessionLocator, SessionStatus


class HostLifecycleApplication(RuntimeHookApplication):
    def _resolve_codex_turn_lineage(self, envelope):
        from scripts.agent_harness.runtime_adapter import LifecycleCause, RuntimeEnvelope
        from scripts.agent_harness.session_kernel import ActorId

        from neurath.hosts.identity import attest_child

        if envelope.cause is LifecycleCause.SUBAGENT_START:
            proof = attest_child(
                self._locator.control_root,
                envelope.runtime.value,
                self.host_payload,
                self.host_environment,
            )
            if proof:
                declared_parent = envelope.provenance.raw_parent_actor_id
                if declared_parent is not None and declared_parent != str(envelope.session_id):
                    raise RuntimeHookFailure(
                        RuntimeHookDiagnostic.STATE_CONFLICT,
                        "native parent contradicts attested root",
                    )
                return RuntimeEnvelope(
                    runtime=envelope.runtime,
                    session_id=envelope.session_id,
                    resume_id=envelope.resume_id,
                    actor_id=envelope.actor_id,
                    parent_actor_id=ActorId(proof["parent"]),
                    cause=envelope.cause,
                    capabilities=envelope.capabilities,
                    provenance=envelope.provenance,
                    fork_source_session_id=envelope.fork_source_session_id,
                    fork_provenance_id=envelope.fork_provenance_id,
                ), proof["revision"]
        return envelope, None

    def _apply_end(self, envelope):
        # Native SessionEnd means that a host process closed. The host can resume
        # its conversation later. Explicit kernel SessionEnded still retires a
        # logical session permanently; never resurrect such a session here.
        if RuntimeCapability.SESSION_END not in envelope.capabilities:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.LIFECYCLE_UNAVAILABLE, "missing SessionEnd capability"
            )
        state = self._kernel.inspect(envelope.session_id)
        if (
            state.session.runtime is not envelope.runtime
            or state.session.root_actor_id != envelope.actor_id
            or state.session.status is not SessionStatus.ACTIVE
        ):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.STATE_CONFLICT, "disconnect is not an active root session"
            )
        # The kernel already commits each mutation durably. Keep enclave,
        # delegations, ownership, and in-flight actions for typed resume recovery.


def lifecycle_hook(root, raw, environment):
    application = HostLifecycleApplication(
        SessionLocator.from_worktree(root),
        enclave_max_bytes=16384,
        additional_context_max_bytes=24576,
    )
    application.host_payload = json.loads(raw)
    application.host_environment = environment
    result = application.run(raw, environment)
    if result.exit_code or result.diagnostic:
        diagnostic = str(result.diagnostic or "runtime lifecycle rejected")
        return 2, {}, diagnostic
    payload = json.loads(raw)
    if payload.get("hook_event_name") == "SubagentStart":
        from scripts.agent_harness.session_kernel import ActorId, SessionId

        state = application._kernel.inspect(SessionId(payload["session_id"]))
        actor = ActorId(f"{environment['NEURATH_HOOK_RUNTIME']}:{payload.get('agent_id', '')}")
        if actor not in state.actors:
            return (
                0,
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SubagentStart",
                        "additionalContext": "Neurath child identity is pending host transcript delivery; it will be verified before stateful tool execution.",
                    }
                },
                "",
            )
        from neurath.hosts.identity import attach_delegation

        attach_delegation(root, environment["NEURATH_HOOK_RUNTIME"], payload)
    application.acknowledge(result)
    return 0, json.loads(result.stdout), ""


def ensure_child(root, host, payload, environment):
    from scripts.agent_harness.session_kernel import (
        ActorId,
        ActorLineageAssurance,
        ActorStatus,
        ForegroundTurnStatus,
        SessionId,
        SessionKernel,
    )

    kernel = SessionKernel(SessionLocator.from_worktree(root))
    session = SessionId(payload["session_id"])
    actor_id = ActorId(f"{host}:{payload['agent_id']}")
    state = kernel.inspect(session)
    if actor_id not in state.actors:
        code, _, _ = lifecycle_hook(
            root, json.dumps({**payload, "hook_event_name": "SubagentStart"}), environment
        )
        if code:
            return False
        state = kernel.inspect(session)
    actor = state.actors.get(actor_id)
    turn = state.foreground_turns.get(actor_id)
    if actor is not None and (actor.status is ActorStatus.STOPPED
            or host == "codex" and actor.status is ActorStatus.ACTIVE and turn is not None
                and turn.status is ForegroundTurnStatus.CLOSED):
        from neurath.hosts.identity import resume_child
        from scripts.agent_harness.session_kernel import TransitionRejected

        try:
            if not resume_child(root, host, payload, environment):
                return False
            state = kernel.inspect(session)
            actor = state.actors.get(actor_id)
        except (ValueError, OSError, KeyError, TransitionRejected):
            return False
    verified = (
        actor is not None
        and actor.status is ActorStatus.ACTIVE
        and actor.lineage_assurance is ActorLineageAssurance.HOST_ATTESTED
    )
    if verified:
        from neurath.hosts.identity import attach_delegation

        attach_delegation(root, host, payload)
    return verified
