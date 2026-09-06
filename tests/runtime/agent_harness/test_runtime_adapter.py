"""Coding-agent runtime identity와 capability adapter의 목표 계약입니다."""

from __future__ import annotations

import unittest

from scripts.agent_harness.runtime_adapter import (
    ClaudeCodeRuntimeAdapter,
    CodexRuntimeAdapter,
    LifecycleCause,
    RuntimeAdapterError,
    RuntimeCapability,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ResumeId,
    SessionId,
    SessionRuntime,
)


class RuntimeAdapterTest(unittest.TestCase):
    """Vendor payload를 표준 session/actor identity로 정규화하는 계약을 검증합니다."""

    def test_claude_subagent_without_parent_keeps_lineage_unattested(
        self,
    ) -> None:
        """Host parent field가 없으면 root를 immediate parent로 추론하지 않습니다."""
        envelope = ClaudeCodeRuntimeAdapter().normalize({
            "hook_event_name": "SubagentStart",
            "session_id": "claude-session-a",
            "agent_id": "worker-7",
            "agent_type": "general-purpose",
            "cwd": "/repo",
            "transcript_path": "/tmp/claude-session-a.jsonl",
        })

        self.assertEqual(SessionRuntime.CLAUDE_CODE, envelope.runtime)
        self.assertEqual(SessionId("claude-session-a"), envelope.session_id)
        self.assertIsNone(envelope.resume_id)
        self.assertEqual(ActorId("claude-code:worker-7"), envelope.actor_id)
        self.assertIsNone(envelope.parent_actor_id)
        self.assertNotEqual(str(envelope.session_id), str(envelope.actor_id))
        self.assertEqual("claude-session-a", envelope.provenance.raw_session_id)
        self.assertEqual("worker-7", envelope.provenance.raw_actor_id)
        self.assertIsNone(envelope.provenance.raw_parent_actor_id)
        self.assertIn(
            RuntimeCapability.SUBAGENT_START_ADDITIONAL_CONTEXT,
            envelope.capabilities,
        )

    def test_claude_subagent_preserves_explicit_parent_without_root_fallback(self) -> None:
        """Host가 제공한 exact parent identity만 canonical lineage로 보존합니다."""
        envelope = ClaudeCodeRuntimeAdapter().normalize({
            "hook_event_name": "SubagentStart",
            "session_id": "claude-session-a",
            "agent_id": "worker-7",
            "parent_agent_id": "session:claude-session-a",
            "agent_type": "general-purpose",
            "cwd": "/repo",
            "transcript_path": "/tmp/claude-session-a.jsonl",
        })

        self.assertEqual(
            ActorId("claude-code:session:claude-session-a"),
            envelope.parent_actor_id,
        )
        self.assertEqual(
            "session:claude-session-a",
            envelope.provenance.raw_parent_actor_id,
        )

    def test_claude_resume_uses_a_typed_resume_identity_without_inventing_an_actor(
        self,
    ) -> None:
        """Claude resume handle과 root actor를 별도 typed identity로 보존합니다."""
        envelope = ClaudeCodeRuntimeAdapter().normalize({
            "hook_event_name": "SessionStart",
            "session_id": "claude-session-a",
            "source": "resume",
            "cwd": "/repo",
            "transcript_path": "/tmp/claude-session-a.jsonl",
        })

        self.assertEqual(LifecycleCause.RESUME, envelope.cause)
        self.assertEqual(SessionId("claude-session-a"), envelope.session_id)
        self.assertEqual(ResumeId("claude-session-a"), envelope.resume_id)
        self.assertEqual(ActorId("claude-code:session:claude-session-a"), envelope.actor_id)
        self.assertIsNone(envelope.parent_actor_id)
        self.assertEqual("claude-session-a", envelope.provenance.raw_resume_id)

    def test_codex_extension_resume_keeps_session_thread_and_parent_distinct(self) -> None:
        """Synthetic extension seam을 보존하되 current official hook parity로 주장하지 않습니다."""
        envelope = CodexRuntimeAdapter().normalize({
            "hook_event_name": "SessionStart",
            "source": "resume",
            "session_id": "codex-session-root",
            "thread_id": "thread-child",
            "parent_thread_id": "thread-root",
            "resume_id": "resume-thread-child",
            "capabilities": ["session_start_additional_context"],
        })

        self.assertEqual(SessionRuntime.CODEX, envelope.runtime)
        self.assertEqual(SessionId("codex-session-root"), envelope.session_id)
        self.assertEqual(ResumeId("resume-thread-child"), envelope.resume_id)
        self.assertEqual(ActorId("codex:thread-child"), envelope.actor_id)
        self.assertEqual(ActorId("codex:thread-root"), envelope.parent_actor_id)
        self.assertEqual("codex-session-root", envelope.provenance.raw_session_id)
        self.assertEqual("resume-thread-child", envelope.provenance.raw_resume_id)
        self.assertEqual("thread-child", envelope.provenance.raw_actor_id)
        self.assertEqual("thread-root", envelope.provenance.raw_parent_actor_id)

    def test_official_codex_session_start_declares_stable_additional_context(self) -> None:
        """공식 Codex SessionStart schema만으로 stable context capability를 선언합니다."""
        envelope = CodexRuntimeAdapter().normalize({
            "hook_event_name": "SessionStart",
            "source": "compact",
            "session_id": "codex-session-a",
            "cwd": "/repo",
            "model": "gpt-5.6",
            "permission_mode": "default",
            "transcript_path": "/tmp/codex-session-a.jsonl",
        })

        self.assertEqual(LifecycleCause.COMPACT, envelope.cause)
        self.assertIn(
            RuntimeCapability.SESSION_START_ADDITIONAL_CONTEXT,
            envelope.capabilities,
        )
        self.assertNotIn(
            RuntimeCapability.EXPERIMENTAL_THREAD_INJECTION,
            envelope.capabilities,
        )
        self.assertNotIn(RuntimeCapability.SESSION_END, envelope.capabilities)

    def test_official_codex_subagent_start_normalizes_state_free_child_identity(self) -> None:
        """Official agent_id는 parent를 추정하지 않는 Codex child identity가 됩니다."""
        envelope = CodexRuntimeAdapter().normalize({
            "hook_event_name": "SubagentStart",
            "session_id": "codex-session-a",
            "turn_id": "turn-root-a",
            "agent_id": "worker-7",
            "agent_type": "explorer",
            "cwd": "/repo",
            "model": "gpt-5.6",
            "permission_mode": "default",
            "transcript_path": "/tmp/codex-session-a.jsonl",
        })

        self.assertEqual(SessionRuntime.CODEX, envelope.runtime)
        self.assertEqual(SessionId("codex-session-a"), envelope.session_id)
        self.assertEqual(ActorId("codex:worker-7"), envelope.actor_id)
        self.assertIsNone(envelope.parent_actor_id)
        self.assertEqual("worker-7", envelope.provenance.raw_actor_id)
        self.assertIsNone(envelope.provenance.raw_parent_actor_id)
        self.assertEqual("turn-root-a", envelope.provenance.raw_turn_id)
        self.assertIn(
            RuntimeCapability.SUBAGENT_START_ADDITIONAL_CONTEXT,
            envelope.capabilities,
        )

    def test_clear_is_a_new_startup_boundary(self) -> None:
        """Vendor clear source는 새 exact session을 초기화할 startup으로 정규화합니다."""
        for adapter in (ClaudeCodeRuntimeAdapter(), CodexRuntimeAdapter()):
            with self.subTest(adapter=type(adapter).__name__):
                envelope = adapter.normalize({
                    "hook_event_name": "SessionStart",
                    "source": "clear",
                    "session_id": "cleared-session",
                    "cwd": "/repo",
                    "transcript_path": "/tmp/cleared-session.jsonl",
                })
                self.assertEqual(LifecycleCause.STARTUP, envelope.cause)

    def test_codex_extension_fork_requires_source_and_provenance(self) -> None:
        """Synthetic fork extension은 paired evidence를 요구하며 live host delivery 증거가 아닙니다."""
        envelope = CodexRuntimeAdapter().normalize({
            "hook_event_name": "SessionStart",
            "source": "fork",
            "session_id": "fork-target",
            "source_session_id": "fork-source",
            "fork_provenance_id": "codex-fork:fork-source:fork-target",
            "capabilities": ["session_fork_lineage"],
        })

        self.assertEqual(LifecycleCause.FORK, envelope.cause)
        self.assertEqual(SessionId("fork-source"), envelope.fork_source_session_id)
        self.assertEqual(
            "codex-fork:fork-source:fork-target",
            envelope.fork_provenance_id,
        )
        self.assertIn(RuntimeCapability.SESSION_FORK_LINEAGE, envelope.capabilities)

        with self.assertRaises(RuntimeAdapterError):
            CodexRuntimeAdapter().normalize({
                "hook_event_name": "SessionStart",
                "source": "fork",
                "session_id": "fork-target",
                "capabilities": ["session_fork_lineage"],
            })

    def test_session_end_capability_is_available_for_both_runtime_schemas(self) -> None:
        """Claude와 Codex의 공식 SessionEnd를 exact root terminal capability로 보존합니다."""
        claude = ClaudeCodeRuntimeAdapter().normalize({
            "hook_event_name": "SessionEnd",
            "session_id": "claude-session-a",
            "cwd": "/repo",
            "transcript_path": "/tmp/claude-session-a.jsonl",
        })
        codex = CodexRuntimeAdapter().normalize({
            "hook_event_name": "SessionEnd",
            "session_id": "codex-session-a",
            "cwd": "/repo",
            "transcript_path": "/tmp/codex-session-a.jsonl",
        })

        self.assertEqual(LifecycleCause.END, claude.cause)
        self.assertEqual(LifecycleCause.END, codex.cause)
        self.assertIn(RuntimeCapability.SESSION_END, claude.capabilities)
        self.assertIn(RuntimeCapability.SESSION_END, codex.capabilities)

    def test_missing_or_ambiguous_required_identity_fails_closed(self) -> None:
        """Adapter는 다른 state를 scan할 수 없는 payload를 명시적으로 거부합니다."""
        adapter = CodexRuntimeAdapter()

        with self.assertRaises(RuntimeAdapterError):
            adapter.normalize({
                "hook_event_name": "SessionStart",
                "source": "compact",
                "thread_id": "thread-without-session",
            })
        with self.assertRaises(RuntimeAdapterError):
            adapter.normalize({
                "hook_event_name": "SessionStart",
                "source": "compact",
                "session_id": "session-a",
                "thread_id": "thread-a",
                "actor_id": "conflicting-actor",
            })


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
