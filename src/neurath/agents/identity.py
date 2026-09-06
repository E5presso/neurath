"""Resolve the caller from the existing host-bound StateHandle, including children."""

import os

from neurath.agents.store import AgentIdentity
from neurath.runtime.engine import activate


def current_agent(root):
    activate(root)
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle

    binding = RuntimeEnvironmentResolver().resolve(os.environ)
    StateHandle.attach(SessionLocator.from_worktree(root), binding).inspect()
    return AgentIdentity(
        binding.runtime.value, str(binding.session_id), str(binding.actor_id), binding.is_root
    )
