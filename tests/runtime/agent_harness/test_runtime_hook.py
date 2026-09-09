"""Coding-agent runtime hook entrypoint의 목표 계약입니다."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts.agent_harness.enclave_store import (
    EnclaveFact,
    EnclaveSourceKind,
    EnclaveStore,
)
from scripts.agent_harness.material_action import (
    MaterialActionKind,
    ObservableDeltaKind,
    ObservableExpectation,
)
from scripts.agent_harness.runtime_assurance import (
    AssuranceAvailability,
    AssuranceEvidenceSource,
    RuntimeAssurance,
    RuntimeAssuranceEvidence,
    RuntimeAssuranceInventory,
    RuntimeAssuranceProfile,
    RuntimeConfigDigest,
)
from scripts.agent_harness.runtime_hook import (
    RuntimeHookApplication,
    RuntimeHookDiagnostic,
    RuntimeHookResult,
)
from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    DelegationAssigned,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationStatus,
    DelegationTopologyPolicy,
    EffectPrepared,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    ForegroundTurnStatus,
    MaterialActionPrepared,
    OutboxEffect,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    SessionStatus,
    TurnId,
)
from scripts.agent_harness.session_rehydration import RehydrationDiagnostic


class RuntimeHookApplicationTest(unittest.TestCase):
    """Runtime hook이 exact session lifecycle만 변경하고 출력하는지 검증합니다."""

    def setUp(self) -> None:
        """격리된 control root와 runtime hook application을 준비합니다."""
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.locator = SessionLocator(self.root)
        self.kernel = SessionKernel(self.locator)
        self.enclaves = EnclaveStore(self.locator, max_bytes=4096)
        self.application = RuntimeHookApplication(
            self.locator,
            enclave_max_bytes=4096,
            additional_context_max_bytes=2048,
        )

    def start_session(
        self,
        session_id: str,
        runtime: SessionRuntime,
        fact: str | None = None,
    ) -> ActorId:
        """Exact-session fixture를 public kernel과 enclave API로 초기화합니다."""
        root_actor_id = ActorId(f"{runtime.value}:session:{session_id}")
        self.kernel.apply(
            SessionStarted(
                session_id=SessionId(session_id),
                resume_id=ResumeId(session_id),
                runtime=runtime,
                root_actor_id=root_actor_id,
                idempotency_key=f"fixture-start:{session_id}",
            )
        )
        if fact is not None:
            snapshot = self.enclaves.read(SessionId(session_id))
            self.enclaves.set(
                SessionId(session_id),
                root_actor_id,
                "invariant",
                EnclaveFact(
                    value=fact,
                    source_kind=EnclaveSourceKind.USER,
                    source_turn_id=TurnId("turn-1"),
                ),
                expected_digest=snapshot.digest,
            )
        return root_actor_id

    def run_hook(
        self,
        payload: dict[str, object],
        environment: dict[str, str],
    ) -> RuntimeHookResult:
        """JSON stdin과 명시적 environment로 hook application을 실행합니다."""
        return self.application.run(
            json.dumps(payload, ensure_ascii=False),
            environment,
        )

    def host_attested_profile(self, runtime: SessionRuntime) -> RuntimeAssuranceProfile:
        """Persisted-child tests가 사용하는 explicit host-attested lineage seam을 만듭니다."""
        return RuntimeAssuranceProfile(
            runtime=runtime,
            config_path=(
                Path(".claude/settings.json")
                if runtime is SessionRuntime.CLAUDE_CODE
                else Path(".codex/hooks.json")
            ),
            config_digest=RuntimeConfigDigest(f"sha256:{'a' * 64}"),
            wired_events=frozenset({"SubagentStart"}),
            assurances=(
                RuntimeAssuranceEvidence(
                    assurance=RuntimeAssurance.IMMEDIATE_PARENT_LINEAGE,
                    availability=AssuranceAvailability.AVAILABLE,
                    evidence_source=AssuranceEvidenceSource.HOST_ATTESTATION,
                ),
            ),
        )

    def hook_specific_output(self, result: RuntimeHookResult) -> dict[str, object]:
        """Hook stdout에서 validated hookSpecificOutput object를 읽습니다."""
        raw_payload: object = json.loads(result.stdout)
        self.assertIsInstance(raw_payload, dict)
        payload = cast(dict[str, object], raw_payload)
        raw_specific = payload.get("hookSpecificOutput")
        self.assertIsInstance(raw_specific, dict)
        return cast(dict[str, object], raw_specific)

    def assert_export(self, env_file: Path, name: str, value: str) -> None:
        """Claude env file에 shell-safe export가 기록됐는지 확인합니다."""
        content = env_file.read_text(encoding="utf-8")
        escaped_value = re.escape(value)
        pattern = (
            rf"(?m)^export {re.escape(name)}="
            rf"(?:{escaped_value}|'{escaped_value}'|\"{escaped_value}\")$"
        )
        self.assertRegex(content, pattern)

    def test_claude_startup_initializes_only_exact_session_and_exports_identity(self) -> None:
        """Claude startup은 exact session/root actor를 idempotently 만들고 env를 내보냅니다."""
        env_file = self.root / "claude.env"
        environment = {
            "CLAUDE_PROJECT_DIR": str(self.root),
            "CLAUDE_ENV_FILE": str(env_file),
        }
        payload: dict[str, object] = {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "session_id": "claude-session-a",
            "cwd": str(self.root),
            "transcript_path": str(self.root / "claude-session-a.jsonl"),
        }

        first = self.run_hook(payload, environment)
        second = self.run_hook(payload, environment)
        state = self.kernel.inspect(SessionId("claude-session-a"))

        self.assertEqual(0, first.exit_code)
        self.assertEqual(0, second.exit_code)
        self.assertIsNone(first.diagnostic)
        self.assertEqual(1, state.revision)
        self.assertEqual(SessionRuntime.CLAUDE_CODE, state.session.runtime)
        self.assertEqual(
            ActorId("claude-code:session:claude-session-a"),
            state.session.root_actor_id,
        )
        self.assertEqual({}, dict(state.workflows))
        self.assertEqual({}, dict(state.delegations))
        turn = state.foreground_turns[state.session.root_actor_id]
        self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)
        self.assertEqual(1, turn.generation)
        self.assertEqual(0, turn.revision)
        self.assertIsNone(turn.vendor_turn_id)
        self.assertIsNone(turn.user_prompt_receipt)
        self.assertFalse(self.locator.locate(SessionId("unrelated")).process_state.exists())
        self.assert_export(env_file, "NEURATH_AGENT_SESSION_ID", "claude-session-a")
        self.assert_export(
            env_file,
            "NEURATH_AGENT_ACTOR_ID",
            "claude-code:session:claude-session-a",
        )
        self.assert_export(env_file, "NEURATH_AGENT_RUNTIME", "claude-code")

    def test_fresh_startup_returns_only_after_provisional_turn_can_prepare_action(self) -> None:
        """Fresh SessionStart 성공 state는 즉시 material-action intent를 받을 수 있습니다."""
        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "startup",
                "session_id": "startup-ready-turn",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "startup-ready-turn.jsonl"),
            },
            {"NEURATH_HOOK_RUNTIME": "codex"},
        )
        state = self.kernel.inspect(SessionId("startup-ready-turn"))
        actor_id = state.session.root_actor_id
        turn = state.foreground_turns[actor_id]

        prepared = self.kernel.apply(
            MaterialActionPrepared(
                session_id=state.session.id,
                actor_id=actor_id,
                batch_id="startup-ready-action",
                sequence=1,
                expected_turn_generation=turn.generation,
                expected_turn_revision=turn.revision,
                kind=MaterialActionKind.LOCAL_MUTATION,
                targets=(str(self.root / "target.py"),),
                expectations=(
                    ObservableExpectation(
                        observable_id=str(self.root / "target.py"),
                        baseline_digest=None,
                        expected_delta=ObservableDeltaKind.CREATED,
                        expected_digest=None,
                    ),
                ),
                adaptive_binding=None,
                idempotency_key="startup-ready-action:prepare",
            )
        )

        self.assertEqual(0, result.exit_code, result.diagnostic)
        self.assertIn(actor_id, state.foreground_turns)
        self.assertIn(actor_id, prepared.material_actions)

    def test_startup_effect_binds_exact_emitted_additional_context(self) -> None:
        """Startup outbox는 실제 vendor stdout에 쓴 context byte와 정확히 결속됩니다."""
        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "startup",
                "session_id": "startup-effect",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "startup-effect.jsonl"),
            },
            {"CLAUDE_PROJECT_DIR": str(self.root)},
        )
        context = self.hook_specific_output(result).get("additionalContext")

        self.assertIsInstance(context, str)
        self.assertIsNotNone(result.pending_effect)
        assert isinstance(context, str)
        assert result.pending_effect is not None
        self.assertTrue(result.pending_effect.payload["context_present"])
        self.assertEqual(
            hashlib.sha256(context.encode("utf-8")).hexdigest(),
            result.pending_effect.payload["context_sha256"],
        )

    def test_codex_compact_outputs_only_exact_session_hook_context(self) -> None:
        """공식 Codex SessionStart payload는 exact-session context만 복원합니다."""
        self.start_session("session-a", SessionRuntime.CODEX, "A 전용 사실")
        self.start_session("session-b", SessionRuntime.CODEX, "B 전용 사실")
        before_revision = self.kernel.inspect(SessionId("session-a")).revision

        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "compact",
                "session_id": "session-a",
                "cwd": str(self.root),
                "model": "gpt-5.6",
                "permission_mode": "default",
                "transcript_path": str(self.root / "session-a.jsonl"),
            },
            {
                "NEURATH_HOOK_RUNTIME": "codex",
                "CODEX_THREAD_ID": "session-a",
            },
        )
        specific = self.hook_specific_output(result)
        context = specific.get("additionalContext")

        self.assertEqual(0, result.exit_code)
        self.assertIsNone(result.diagnostic)
        self.assertEqual("SessionStart", specific.get("hookEventName"))
        self.assertIsInstance(context, str)
        self.assertIn("A 전용 사실", context)
        self.assertNotIn("B 전용 사실", context)
        pending = self.kernel.inspect(SessionId("session-a"))
        self.assertEqual(
            before_revision + 1,
            pending.revision,
        )
        self.assertIsNotNone(result.pending_effect)
        self.assertEqual(1, len(pending.outbox))

        self.application.acknowledge(result)
        acknowledged = self.kernel.inspect(SessionId("session-a"))

        self.assertEqual(before_revision + 2, acknowledged.revision)
        self.assertEqual({}, acknowledged.outbox)

    def test_compact_delivery_identity_changes_when_enclave_snapshot_changes(self) -> None:
        """새 enclave snapshot은 같은 vendor envelope에서도 새 durable effect가 됩니다."""
        root_actor_id = self.start_session(
            "session-a",
            SessionRuntime.CODEX,
            "첫 번째 사실",
        )
        payload: dict[str, object] = {
            "hook_event_name": "SessionStart",
            "source": "compact",
            "session_id": "session-a",
            "cwd": str(self.root),
            "model": "gpt-5.6",
            "permission_mode": "default",
            "transcript_path": str(self.root / "session-a.jsonl"),
        }
        environment = {
            "NEURATH_HOOK_RUNTIME": "codex",
            "CODEX_THREAD_ID": "session-a",
        }

        first = self.run_hook(payload, environment)
        self.application.acknowledge(first)
        snapshot = self.enclaves.read(SessionId("session-a"))
        self.enclaves.set(
            SessionId("session-a"),
            root_actor_id,
            "invariant",
            EnclaveFact(
                value="두 번째 사실",
                source_kind=EnclaveSourceKind.USER,
                source_turn_id=TurnId("turn-2"),
            ),
            expected_digest=snapshot.digest,
        )

        second = self.run_hook(payload, environment)

        self.assertIsNotNone(first.pending_effect)
        self.assertIsNotNone(second.pending_effect)
        assert first.pending_effect is not None
        assert second.pending_effect is not None
        self.assertNotEqual(first.pending_effect.id, second.pending_effect.id)
        self.assertIn("두 번째 사실", second.stdout)
        state = self.kernel.inspect(SessionId("session-a"))
        self.assertEqual({second.pending_effect.id}, set(state.outbox))

    def test_compact_effect_binds_exact_truncated_additional_context(self) -> None:
        """Compaction outbox는 truncation 이전이 아니라 실제 bounded output을 hash합니다."""
        self.start_session("compact-effect", SessionRuntime.CODEX, "가" * 900)
        application = RuntimeHookApplication(
            self.locator,
            enclave_max_bytes=4096,
            additional_context_max_bytes=300,
        )

        result = application.run(
            json.dumps({
                "hook_event_name": "SessionStart",
                "source": "compact",
                "session_id": "compact-effect",
                "cwd": str(self.root),
                "model": "gpt-5.6",
                "permission_mode": "default",
                "transcript_path": str(self.root / "compact-effect.jsonl"),
            }),
            {"NEURATH_HOOK_RUNTIME": "codex", "CODEX_THREAD_ID": "compact-effect"},
        )
        context = self.hook_specific_output(result).get("additionalContext")

        self.assertIsInstance(context, str)
        assert isinstance(context, str)
        self.assertIn("[neurath-context-truncated]", context)
        self.assertIsNotNone(result.pending_effect)
        assert result.pending_effect is not None
        self.assertEqual(
            hashlib.sha256(context.encode("utf-8")).hexdigest(),
            result.pending_effect.payload["context_sha256"],
        )

    def test_resume_of_missing_session_never_scans_or_initializes_a_fallback(self) -> None:
        """Resume miss는 다른 active session을 찾거나 요청 session을 새로 만들지 않습니다."""
        self.start_session("fallback", SessionRuntime.CODEX, "fallback 금지 사실")

        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "resume",
                "session_id": "missing",
                "thread_id": "missing-thread",
                "resume_id": "missing-resume",
                "capabilities": ["session_start_additional_context"],
            },
            {"CODEX_HOME": str(self.root / ".codex")},
        )

        self.assertEqual(0, result.exit_code)
        self.assertEqual(RehydrationDiagnostic.ORPHAN_SESSION, result.diagnostic)
        self.assertNotIn("fallback 금지 사실", result.stdout)
        self.assertFalse(self.locator.locate(SessionId("missing")).process_state.exists())

    def test_runtime_fork_creates_independent_target_or_blocks_unavailable(self) -> None:
        """Proven fork는 독립 target을 만들고 lineage 없는 fork는 차단합니다."""
        self.start_session("source-session", SessionRuntime.CODEX, "source-only fact")

        proven = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "fork",
                "session_id": "fork-target",
                "source_session_id": "source-session",
                "fork_provenance_id": "codex-fork:source-session:fork-target",
                "capabilities": ["session_fork_lineage"],
                "cwd": str(self.root),
                "model": "gpt-5.6",
                "permission_mode": "default",
                "transcript_path": str(self.root / "fork-target.jsonl"),
            },
            {
                "NEURATH_HOOK_RUNTIME": "codex",
                "CODEX_THREAD_ID": "fork-target",
            },
        )

        self.assertEqual(0, proven.exit_code)
        target_state = self.kernel.inspect(SessionId("fork-target"))
        self.assertEqual(SessionId("source-session"), target_state.session.parent_session_id)
        self.assertEqual(
            "codex-fork:source-session:fork-target",
            target_state.session.lifecycle_provenance_id,
        )
        self.assertIn(
            "source-only fact",
            json.dumps(
                self.enclaves.read(SessionId("fork-target")).to_payload(),
                ensure_ascii=False,
            ),
        )
        self.assertNotEqual(
            self.locator.locate(SessionId("source-session")).directory,
            self.locator.locate(SessionId("fork-target")).directory,
        )

        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "fork",
                "session_id": "unproven-target",
                "cwd": str(self.root),
                "model": "gpt-5.6",
                "permission_mode": "default",
                "transcript_path": str(self.root / "unproven-target.jsonl"),
            },
            {
                "NEURATH_HOOK_RUNTIME": "codex",
                "CODEX_THREAD_ID": "unproven-target",
            },
        )

        self.assertNotEqual(0, result.exit_code)
        self.assertEqual(RuntimeHookDiagnostic.LIFECYCLE_UNAVAILABLE, result.diagnostic)
        self.assertFalse(self.locator.locate(SessionId("unproven-target")).process_state.exists())
        self.assertEqual(
            SessionStatus.ACTIVE,
            self.kernel.inspect(SessionId("source-session")).session.status,
        )

    def test_fork_effect_binds_exact_emitted_additional_context(self) -> None:
        """Fork target도 출력 context를 pending outbox delivery로 먼저 보존합니다."""
        self.start_session("fork-source", SessionRuntime.CODEX, "forked fact")

        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "fork",
                "session_id": "fork-effect-target",
                "source_session_id": "fork-source",
                "fork_provenance_id": "fork-effect-provenance",
                "capabilities": ["session_fork_lineage"],
                "cwd": str(self.root),
                "model": "gpt-5.6",
                "permission_mode": "default",
                "transcript_path": str(self.root / "fork-effect-target.jsonl"),
            },
            {"NEURATH_HOOK_RUNTIME": "codex", "CODEX_THREAD_ID": "fork-effect-target"},
        )

        context = self.hook_specific_output(result).get("additionalContext")

        self.assertIsInstance(context, str)
        self.assertIsNotNone(result.pending_effect)
        assert isinstance(context, str)
        assert result.pending_effect is not None
        self.assertEqual(
            hashlib.sha256(context.encode("utf-8")).hexdigest(),
            result.pending_effect.payload["context_sha256"],
        )
        self.assertEqual(
            {result.pending_effect.id},
            set(self.kernel.inspect(SessionId("fork-effect-target")).outbox),
        )

    def test_fork_retry_replays_exact_pending_context_effect(self) -> None:
        """ACK 전 동일 fork retry는 exact pending context를 중복 commit하지 않습니다."""
        self.start_session("fork-retry-source", SessionRuntime.CODEX, "retry fact")
        payload: dict[str, object] = {
            "hook_event_name": "SessionStart",
            "source": "fork",
            "session_id": "fork-retry-target",
            "source_session_id": "fork-retry-source",
            "fork_provenance_id": "fork-retry-provenance",
            "capabilities": ["session_fork_lineage"],
            "cwd": str(self.root),
            "model": "gpt-5.6",
            "permission_mode": "default",
            "transcript_path": str(self.root / "fork-retry-target.jsonl"),
        }
        environment = {
            "NEURATH_HOOK_RUNTIME": "codex",
            "CODEX_THREAD_ID": "fork-retry-target",
        }

        first = self.run_hook(payload, environment)
        first_state = self.kernel.inspect(SessionId("fork-retry-target"))
        retried = self.run_hook(payload, environment)

        self.assertEqual(0, first.exit_code)
        self.assertEqual(0, retried.exit_code)
        self.assertIsNotNone(first.pending_effect)
        self.assertIsNotNone(retried.pending_effect)
        assert first.pending_effect is not None
        assert retried.pending_effect is not None
        self.assertEqual(first.pending_effect.id, retried.pending_effect.id)
        self.assertEqual(
            first_state.revision,
            self.kernel.inspect(SessionId("fork-retry-target")).revision,
        )
        self.application.acknowledge(retried)
        acknowledged = self.kernel.inspect(SessionId("fork-retry-target"))
        after_ack_retry = self.run_hook(payload, environment)

        self.assertEqual(0, after_ack_retry.exit_code)
        self.assertIsNotNone(after_ack_retry.pending_effect)
        assert after_ack_retry.pending_effect is not None
        self.assertEqual(first.pending_effect.id, after_ack_retry.pending_effect.id)
        self.assertEqual(
            acknowledged.revision + 1,
            self.kernel.inspect(SessionId("fork-retry-target")).revision,
        )

    def test_fork_retry_rejects_foreign_pending_delivery(self) -> None:
        """동일 lineage라도 foreign outbox가 있으면 fork retry로 가장하지 못합니다."""
        self.start_session("fork-foreign-source", SessionRuntime.CODEX, "source fact")
        payload: dict[str, object] = {
            "hook_event_name": "SessionStart",
            "source": "fork",
            "session_id": "fork-foreign-target",
            "source_session_id": "fork-foreign-source",
            "fork_provenance_id": "fork-foreign-provenance",
            "capabilities": ["session_fork_lineage"],
            "cwd": str(self.root),
            "model": "gpt-5.6",
            "permission_mode": "default",
            "transcript_path": str(self.root / "fork-foreign-target.jsonl"),
        }
        environment = {
            "NEURATH_HOOK_RUNTIME": "codex",
            "CODEX_THREAD_ID": "fork-foreign-target",
        }
        first = self.run_hook(payload, environment)
        assert first.pending_effect is not None
        foreign_payload = dict(first.pending_effect.payload)
        foreign_payload["context_sha256"] = "0" * 64
        foreign = OutboxEffect(
            effect_id=first.pending_effect.id,
            actor_id=first.pending_effect.actor_id,
            kind=first.pending_effect.kind,
            delivery_key=first.pending_effect.delivery_key,
            payload=foreign_payload,
        )
        self.application.acknowledge(first)
        self.kernel.apply(
            EffectPrepared(
                session_id=SessionId("fork-foreign-target"),
                actor_id=first.pending_effect.actor_id,
                effect=foreign,
                idempotency_key="fixture:foreign-fork-delivery",
            )
        )
        retried = self.run_hook(payload, environment)

        self.assertNotEqual(0, retried.exit_code)
        self.assertEqual(RuntimeHookDiagnostic.STATE_CONFLICT, retried.diagnostic)

    def test_runtime_session_end_transitions_exact_root_and_applies_retention(self) -> None:
        """Claude와 Codex SessionEnd는 exact root를 terminalize하고 enclave를 제거합니다."""
        self.start_session("claude-end", SessionRuntime.CLAUDE_CODE, "delete-on-end")

        claude_result = self.run_hook(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "claude-end",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "claude-end.jsonl"),
            },
            {
                "NEURATH_HOOK_RUNTIME": "claude-code",
                "CLAUDE_CODE_SESSION_ID": "claude-end",
                "CLAUDE_PROJECT_DIR": str(self.root),
            },
        )

        self.assertEqual(0, claude_result.exit_code)
        self.assertIsNone(claude_result.diagnostic)
        self.assertEqual(
            SessionStatus.ENDED,
            self.kernel.inspect(SessionId("claude-end")).session.status,
        )
        self.assertFalse(self.enclaves.exists(SessionId("claude-end")))

        self.start_session("codex-end", SessionRuntime.CODEX, "delete-on-end")
        codex_result = self.run_hook(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "codex-end",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "codex-end.jsonl"),
            },
            {
                "NEURATH_HOOK_RUNTIME": "codex",
                "CODEX_THREAD_ID": "codex-end",
            },
        )

        self.assertEqual(0, codex_result.exit_code)
        self.assertIsNone(codex_result.diagnostic)
        self.assertEqual(
            SessionStatus.ENDED,
            self.kernel.inspect(SessionId("codex-end")).session.status,
        )
        self.assertFalse(self.enclaves.exists(SessionId("codex-end")))

    def test_codex_session_end_rejects_non_root_actor_identity(self) -> None:
        """Synthetic child thread identity는 SessionEnd capability로 root를 terminalize하지 못합니다."""
        self.start_session("codex-child-end", SessionRuntime.CODEX, "must-remain")

        result = self.run_hook(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "codex-child-end",
                "thread_id": "child-thread",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "codex-child-end.jsonl"),
            },
            {
                "NEURATH_HOOK_RUNTIME": "codex",
                "CODEX_THREAD_ID": "child-thread",
            },
        )

        self.assertNotEqual(0, result.exit_code)
        self.assertEqual(RuntimeHookDiagnostic.STATE_CONFLICT, result.diagnostic)
        self.assertEqual(
            SessionStatus.ACTIVE,
            self.kernel.inspect(SessionId("codex-child-end")).session.status,
        )
        self.assertTrue(self.enclaves.exists(SessionId("codex-child-end")))

    def test_codex_session_start_does_not_require_a_synthetic_capability_field(self) -> None:
        """공식 Codex payload에 없는 capabilities field를 caller에게 요구하지 않습니다."""
        self.start_session("session-a", SessionRuntime.CODEX, "A 사실")
        self.start_session("session-b", SessionRuntime.CODEX, "B fallback 금지")

        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "compact",
                "session_id": "session-a",
                "cwd": str(self.root),
                "model": "gpt-5.6",
                "permission_mode": "default",
                "transcript_path": str(self.root / "session-a.jsonl"),
            },
            {
                "NEURATH_HOOK_RUNTIME": "codex",
                "CODEX_THREAD_ID": "session-a",
            },
        )

        self.assertEqual(0, result.exit_code)
        self.assertIsNone(result.diagnostic)
        self.assertIn("A 사실", result.stdout)
        self.assertNotIn("B fallback 금지", result.stdout)

    def test_explicit_runtime_hint_rejects_vendor_specific_payload_conflict(self) -> None:
        """Wiring vendor hint와 다른 vendor 전용 field가 섞이면 mutation 전에 거부합니다."""
        result = self.run_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "session-a",
                "agent_id": "claude-worker",
                "parent_agent_id": "session:session-a",
                "cwd": str(self.root),
            },
            {
                "NEURATH_HOOK_RUNTIME": "codex",
                "CODEX_THREAD_ID": "session-a",
            },
        )

        self.assertNotEqual(0, result.exit_code)
        self.assertEqual(RuntimeHookDiagnostic.RUNTIME_CONFLICT, result.diagnostic)
        self.assertFalse(self.locator.locate(SessionId("session-a")).process_state.exists())

    def test_codex_official_subagent_without_parent_returns_state_free_context(self) -> None:
        """Codex child start는 same-session context만 내고 어떤 authority도 저장하지 않습니다."""
        self.start_session("codex-session-a", SessionRuntime.CODEX, "A 전용 하위 작업 규칙")
        self.start_session("codex-session-b", SessionRuntime.CODEX, "B 외부 규칙")
        payload: dict[str, object] = {
            "hook_event_name": "SubagentStart",
            "session_id": "codex-session-a",
            "agent_id": "worker-7",
            "agent_type": "explorer",
            "cwd": str(self.root),
            "model": "gpt-5.6",
            "permission_mode": "default",
            "transcript_path": str(self.root / "codex-session-a.jsonl"),
        }
        environment = {"NEURATH_HOOK_RUNTIME": "codex"}
        before = self.kernel.inspect(SessionId("codex-session-a")).to_payload()

        first = self.run_hook(payload, environment)
        second = self.run_hook(payload, environment)
        after = self.kernel.inspect(SessionId("codex-session-a"))
        specific = self.hook_specific_output(first)
        context = specific.get("additionalContext")

        self.assertEqual(0, first.exit_code, first.diagnostic)
        self.assertEqual(0, second.exit_code, second.diagnostic)
        self.assertEqual(before, after.to_payload())
        self.assertNotIn(ActorId("codex:worker-7"), after.actors)
        self.assertIsNone(first.pending_effect)
        self.assertIsNone(second.pending_effect)
        self.assertEqual("SubagentStart", specific.get("hookEventName"))
        self.assertIsInstance(context, str)
        self.assertIn("A 전용 하위 작업 규칙", context)
        self.assertNotIn("B 외부 규칙", context)
        self.assertIn("codex-session-a", context)
        self.assertIn("codex:worker-7", context)
        self.assertNotIn("continue", result_payload := json.loads(first.stdout))
        self.assertNotIn("permissionDecision", specific)
        self.assertNotIn("permissionDecision", result_payload)

    def test_codex_turn_attested_direct_child_is_registered_without_parent_extension(self) -> None:
        """Official turn_id가 active root turn과 일치하면 direct child lineage를 증명합니다."""
        root_actor = self.start_session("codex-turn-parent", SessionRuntime.CODEX, "context")
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=SessionId("codex-turn-parent"),
                actor_id=root_actor,
                idempotency_key="turn-attested:provision",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=SessionId("codex-turn-parent"),
                actor_id=root_actor,
                vendor_turn_id="root-turn-7",
                idempotency_key="turn-attested:prompt",
            )
        )

        result = self.run_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "codex-turn-parent",
                "turn_id": "root-turn-7",
                "agent_id": "worker-turn-attested",
                "agent_type": "default",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "codex-turn-parent.jsonl"),
            },
            {"NEURATH_HOOK_RUNTIME": "codex"},
        )
        actor_id = ActorId("codex:worker-turn-attested")
        state = self.kernel.inspect(SessionId("codex-turn-parent"))

        self.assertEqual(0, result.exit_code, result.diagnostic)
        self.assertEqual(root_actor, state.actors[actor_id].parent_actor_id)
        self.assertIs(
            ActorLineageAssurance.HOST_ATTESTED,
            state.actors[actor_id].lineage_assurance,
        )
        self.assertIs(ForegroundTurnStatus.ACTIVE, state.foreground_turns[actor_id].status)
        self.assertIsNotNone(result.pending_effect)

    def test_codex_turn_attested_child_report_is_consumed_by_root_owner(self) -> None:
        """Turn-attested actor는 DIRECT_CHILD report를 제출하고 root가 consume할 수 있습니다."""
        session_id = SessionId("codex-evaluator-parent")
        root_actor = self.start_session(str(session_id), SessionRuntime.CODEX, "context")
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=session_id,
                actor_id=root_actor,
                idempotency_key="evaluator:provision",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=session_id,
                actor_id=root_actor,
                vendor_turn_id="evaluator-root-turn",
                idempotency_key="evaluator:prompt",
            )
        )
        result = self.run_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": str(session_id),
                "turn_id": "evaluator-root-turn",
                "agent_id": "evaluator-child",
                "agent_type": "default",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "evaluator.jsonl"),
            },
            {"NEURATH_HOOK_RUNTIME": "codex"},
        )
        self.assertEqual(0, result.exit_code, result.diagnostic)
        child_actor = ActorId("codex:evaluator-child")
        delegation_id = DelegationId("turn-attested-evaluation")
        self.kernel.apply(
            DelegationAssigned(
                session_id=session_id,
                delegation_id=delegation_id,
                owner_actor_id=root_actor,
                target_actor_id=child_actor,
                assignment="independently evaluate the exact candidate",
                idempotency_key="evaluator:assign",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        self.kernel.apply(
            DelegationReported(
                session_id=session_id,
                delegation_id=delegation_id,
                reporter_actor_id=child_actor,
                result=DelegationResult(
                    verdict="pass",
                    summary="candidate satisfies the frozen matrix",
                    outcome_ref="artifact:turn-attested-evaluator",
                    blocking_findings=(),
                ),
                idempotency_key="evaluator:report",
            )
        )
        consumed = self.kernel.apply(
            DelegationConsumed(
                session_id=session_id,
                delegation_id=delegation_id,
                consumer_actor_id=root_actor,
                idempotency_key="evaluator:consume",
            )
        )

        self.assertIs(DelegationStatus.CONSUMED, consumed.delegations[delegation_id].status)
        self.assertEqual("pass", consumed.delegations[delegation_id].result.verdict)

    def test_codex_missing_or_spoofed_turn_keeps_child_state_free(self) -> None:
        """Missing 또는 다른 turn_id는 parent authority를 만들지 않습니다."""
        root_actor = self.start_session("codex-turn-denied", SessionRuntime.CODEX, "context")
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=SessionId("codex-turn-denied"),
                actor_id=root_actor,
                idempotency_key="turn-denied:provision",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=SessionId("codex-turn-denied"),
                actor_id=root_actor,
                vendor_turn_id="real-root-turn",
                idempotency_key="turn-denied:prompt",
            )
        )
        before = self.kernel.inspect(SessionId("codex-turn-denied")).to_payload()

        for agent_id, turn_id in (("missing-turn", None), ("spoofed-turn", "foreign-turn")):
            payload: dict[str, object] = {
                "hook_event_name": "SubagentStart",
                "session_id": "codex-turn-denied",
                "agent_id": agent_id,
                "agent_type": "default",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "codex-turn-denied.jsonl"),
            }
            if turn_id is not None:
                payload["turn_id"] = turn_id
            result = self.run_hook(payload, {"NEURATH_HOOK_RUNTIME": "codex"})
            self.assertEqual(0, result.exit_code, result.diagnostic)
            self.assertIsNone(result.pending_effect)

        self.assertEqual(before, self.kernel.inspect(SessionId("codex-turn-denied")).to_payload())

    def test_codex_nested_turn_match_does_not_register_grandchild(self) -> None:
        """Child turn과 일치하는 nested spawn은 direct-child 계약 밖이므로 fail-closed입니다."""
        root_actor = self.start_session("codex-nested-parent", SessionRuntime.CODEX, "context")
        child_actor = ActorId("codex:existing-child")
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("codex-nested-parent"),
                actor_id=child_actor,
                parent_actor_id=root_actor,
                kind=ActorKind.SUBAGENT,
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
                idempotency_key="nested:existing-child",
            )
        )
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=SessionId("codex-nested-parent"),
                actor_id=child_actor,
                idempotency_key="nested:provision",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=SessionId("codex-nested-parent"),
                actor_id=child_actor,
                vendor_turn_id="nested-child-turn",
                idempotency_key="nested:prompt",
            )
        )
        before = self.kernel.inspect(SessionId("codex-nested-parent")).to_payload()

        result = self.run_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "codex-nested-parent",
                "turn_id": "nested-child-turn",
                "agent_id": "grandchild-denied",
                "agent_type": "default",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "nested.jsonl"),
            },
            {"NEURATH_HOOK_RUNTIME": "codex"},
        )

        self.assertEqual(0, result.exit_code, result.diagnostic)
        self.assertIsNone(result.pending_effect)
        self.assertEqual(before, self.kernel.inspect(SessionId("codex-nested-parent")).to_payload())

    def test_corrupt_exact_session_never_leaks_another_session_context(self) -> None:
        """손상된 exact state는 unrelated healthy session으로 대체되지 않습니다."""
        self.start_session("corrupt", SessionRuntime.CLAUDE_CODE, "손상 전 사실")
        self.start_session("healthy", SessionRuntime.CLAUDE_CODE, "healthy fallback 금지")
        with RuntimeDatabase(self.root).connection() as db:
            changed = db.execute(
                "UPDATE runtime_records SET payload=? "
                "WHERE namespace='session' AND key='corrupt'",
                (b"{not-json",),
            )
            self.assertEqual(1, changed.rowcount)

        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "compact",
                "session_id": "corrupt",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "corrupt.jsonl"),
            },
            {"CLAUDE_PROJECT_DIR": str(self.root)},
        )

        self.assertEqual(0, result.exit_code)
        self.assertEqual(RehydrationDiagnostic.CORRUPT_STATE, result.diagnostic)
        self.assertNotIn("손상 전 사실", result.stdout)
        self.assertNotIn("healthy fallback 금지", result.stdout)

    def test_normal_event_without_facts_is_a_valid_no_context_result(self) -> None:
        """일반 turn은 empty enclave를 재주입하지 않고 정상 hook 결과를 냅니다."""
        self.start_session("session-a", SessionRuntime.CLAUDE_CODE)

        result = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-a",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "session-a.jsonl"),
            },
            {"CLAUDE_PROJECT_DIR": str(self.root)},
        )

        self.assertEqual(0, result.exit_code)
        self.assertIsNone(result.diagnostic)
        self.assertNotIn("additionalContext", result.stdout)

    def test_claude_subagent_without_parent_returns_state_free_same_session_context(
        self,
    ) -> None:
        """Parent provenance가 없으면 context만 주고 actor topology는 저장하지 않습니다."""
        self.start_session("session-a", SessionRuntime.CLAUDE_CODE, "A 전용 하위 작업 규칙")
        self.start_session("session-b", SessionRuntime.CLAUDE_CODE, "B 외부 규칙")
        payload: dict[str, object] = {
            "hook_event_name": "SubagentStart",
            "session_id": "session-a",
            "agent_id": "worker-7",
            "agent_type": "general-purpose",
            "cwd": str(self.root),
            "transcript_path": str(self.root / "session-a.jsonl"),
        }
        environment = {"CLAUDE_PROJECT_DIR": str(self.root)}

        first = self.run_hook(payload, environment)
        first_state = self.kernel.inspect(SessionId("session-a"))
        second = self.run_hook(payload, environment)
        second_state = self.kernel.inspect(SessionId("session-a"))
        specific = self.hook_specific_output(first)
        context = specific.get("additionalContext")

        self.assertEqual(0, first.exit_code)
        self.assertEqual(0, second.exit_code)
        self.assertEqual(first_state.revision, second_state.revision)
        self.assertNotIn(ActorId("claude-code:worker-7"), second_state.actors)
        self.assertIsNone(first.pending_effect)
        self.assertIsNone(second.pending_effect)
        self.assertEqual("SubagentStart", specific.get("hookEventName"))
        self.assertIsInstance(context, str)
        self.assertIn("A 전용 하위 작업 규칙", context)
        self.assertNotIn("B 외부 규칙", context)
        self.assertIn("session-a", context)
        self.assertIn("claude-code:worker-7", context)
        self.assertLessEqual(len(context.encode("utf-8")), 2048)

    def test_claude_raw_parent_without_attestation_remains_fully_state_free(self) -> None:
        """Raw parent pointer만으로 actor, turn, outbox 또는 mutation authority를 만들지 않습니다."""
        self.start_session("explicit-parent", SessionRuntime.CLAUDE_CODE, "context")
        before = self.kernel.inspect(SessionId("explicit-parent")).to_payload()

        result = self.run_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "explicit-parent",
                "agent_id": "worker-explicit",
                "parent_agent_id": "session:explicit-parent",
                "agent_type": "general-purpose",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "explicit-parent.jsonl"),
            },
            {"CLAUDE_PROJECT_DIR": str(self.root)},
        )
        state = self.kernel.inspect(SessionId("explicit-parent"))

        self.assertEqual(0, result.exit_code)
        self.assertEqual(before, state.to_payload())
        self.assertNotIn(ActorId("claude-code:worker-explicit"), state.actors)
        self.assertNotIn(ActorId("claude-code:worker-explicit"), state.foreground_turns)
        self.assertEqual({}, dict(state.outbox))
        self.assertIsNone(result.pending_effect)

    def test_host_attested_profile_admits_exact_direct_child_authority(self) -> None:
        """Typed host assurance를 소비한 actor만 DIRECT_CHILD assignment를 받습니다."""
        root_actor = self.start_session("attested-parent", SessionRuntime.CLAUDE_CODE, "context")
        profile = self.host_attested_profile(SessionRuntime.CLAUDE_CODE)
        with patch.object(RuntimeAssuranceInventory, "profile", return_value=profile):
            result = self.run_hook(
                {
                    "hook_event_name": "SubagentStart",
                    "session_id": "attested-parent",
                    "agent_id": "worker-attested",
                    "parent_agent_id": "session:attested-parent",
                    "agent_type": "general-purpose",
                    "cwd": str(self.root),
                    "transcript_path": str(self.root / "attested-parent.jsonl"),
                },
                {"CLAUDE_PROJECT_DIR": str(self.root)},
            )
        actor_id = ActorId("claude-code:worker-attested")
        actor = self.kernel.inspect(SessionId("attested-parent")).actors[actor_id]

        self.assertEqual(0, result.exit_code)
        self.assertIs(ActorLineageAssurance.HOST_ATTESTED, actor.lineage_assurance)
        assigned = self.kernel.apply(
            DelegationAssigned(
                session_id=SessionId("attested-parent"),
                delegation_id=DelegationId("attested-direct-child"),
                owner_actor_id=root_actor,
                target_actor_id=actor_id,
                assignment="independent evaluator",
                idempotency_key="delegation:attested-direct-child",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        self.assertEqual(
            DelegationTopologyPolicy.DIRECT_CHILD,
            assigned.delegations[DelegationId("attested-direct-child")].topology_policy,
        )

    def test_subagent_effect_binds_runtime_binding_and_enclave_exactly(self) -> None:
        """Subagent outbox는 runtime binding까지 포함한 실제 output을 hash합니다."""
        self.start_session("subagent-effect", SessionRuntime.CLAUDE_CODE, "child context")

        with patch.object(
            RuntimeAssuranceInventory,
            "profile",
            return_value=self.host_attested_profile(SessionRuntime.CLAUDE_CODE),
        ):
            result = self.run_hook(
                {
                    "hook_event_name": "SubagentStart",
                    "session_id": "subagent-effect",
                    "agent_id": "worker-effect",
                    "parent_agent_id": "session:subagent-effect",
                    "agent_type": "general-purpose",
                    "cwd": str(self.root),
                    "transcript_path": str(self.root / "subagent-effect.jsonl"),
                },
                {"CLAUDE_PROJECT_DIR": str(self.root)},
            )
        context = self.hook_specific_output(result).get("additionalContext")

        self.assertIsInstance(context, str)
        self.assertIsNotNone(result.pending_effect)
        assert isinstance(context, str)
        assert result.pending_effect is not None
        self.assertIn("<neurath-runtime-binding>", context)
        self.assertEqual(
            hashlib.sha256(context.encode("utf-8")).hexdigest(),
            result.pending_effect.payload["context_sha256"],
        )

    def test_subagent_start_bootstraps_one_idempotent_active_foreground_turn(self) -> None:
        """Real SubagentStart는 별도 fixture 없이 child foreground turn을 한 번 엽니다."""
        self.start_session("subagent-turn", SessionRuntime.CLAUDE_CODE, "context")
        payload: dict[str, object] = {
            "hook_event_name": "SubagentStart",
            "session_id": "subagent-turn",
            "agent_id": "worker-turn",
            "parent_agent_id": "session:subagent-turn",
            "agent_type": "general-purpose",
            "cwd": str(self.root),
            "transcript_path": str(self.root / "subagent-turn.jsonl"),
        }

        with patch.object(
            RuntimeAssuranceInventory,
            "profile",
            return_value=self.host_attested_profile(SessionRuntime.CLAUDE_CODE),
        ):
            first = self.run_hook(payload, {"CLAUDE_PROJECT_DIR": str(self.root)})
            first_state = self.kernel.inspect(SessionId("subagent-turn"))
            second = self.run_hook(payload, {"CLAUDE_PROJECT_DIR": str(self.root)})
        second_state = self.kernel.inspect(SessionId("subagent-turn"))
        actor_id = ActorId("claude-code:worker-turn")

        self.assertEqual(0, first.exit_code)
        self.assertEqual(0, second.exit_code)
        self.assertEqual(ForegroundTurnStatus.ACTIVE, first_state.foreground_turns[actor_id].status)
        self.assertEqual(
            first_state.foreground_turns[actor_id].generation,
            second_state.foreground_turns[actor_id].generation,
        )

    def test_subagent_context_preserves_assignment_before_truncating_optional_enclave(
        self,
    ) -> None:
        """Byte budget은 load-bearing assignment를 verbatim 보존하고 optional fact부터 줄입니다."""
        root_actor = self.start_session(
            "session-a",
            SessionRuntime.CLAUDE_CODE,
            "선택적 배경 " + "가" * 900,
        )
        worker = ActorId("claude-code:worker-priority")
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("session-a"),
                actor_id=worker,
                parent_actor_id=root_actor,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:worker-priority",
            )
        )
        assignment = "정확한 acceptance criterion과 goal을 그대로 검증한다"
        self.kernel.apply(
            DelegationAssigned(
                session_id=SessionId("session-a"),
                delegation_id=DelegationId("delegation-priority"),
                owner_actor_id=root_actor,
                target_actor_id=worker,
                assignment=assignment,
                idempotency_key="delegation:priority",
            )
        )
        application = RuntimeHookApplication(
            self.locator,
            enclave_max_bytes=4096,
            additional_context_max_bytes=700,
        )

        result = application.run(
            json.dumps({
                "hook_event_name": "SubagentStart",
                "session_id": "session-a",
                "agent_id": "worker-priority",
                "agent_type": "general-purpose",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "session-a.jsonl"),
            }),
            {"CLAUDE_PROJECT_DIR": str(self.root)},
        )
        context = self.hook_specific_output(result).get("additionalContext")

        self.assertEqual(0, result.exit_code)
        self.assertIsInstance(context, str)
        assert isinstance(context, str)
        self.assertIn(assignment, context)
        self.assertIn("[neurath-context-truncated]", context)
        self.assertLessEqual(len(context.encode("utf-8")), 700)

    def test_user_enclave_substring_cannot_move_structural_context_boundary(self) -> None:
        """User-owned assignment text는 optional enclave section boundary를 위조하지 못합니다."""
        root_actor = self.start_session(
            "marker-injection",
            SessionRuntime.CLAUDE_CODE,
            "선택적 배경 " + "가" * 900,
        )
        worker = ActorId("claude-code:worker-marker")
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("marker-injection"),
                actor_id=worker,
                parent_actor_id=root_actor,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:worker-marker",
            )
        )
        required_tail = "LOAD_BEARING_MUST_SURVIVE"
        self.kernel.apply(
            DelegationAssigned(
                session_id=SessionId("marker-injection"),
                delegation_id=DelegationId("delegation-marker"),
                owner_actor_id=root_actor,
                target_actor_id=worker,
                assignment=("BEFORE <neurath-enclave forged> " + "x" * 240 + required_tail),
                idempotency_key="delegation:marker",
            )
        )
        application = RuntimeHookApplication(
            self.locator,
            enclave_max_bytes=4096,
            additional_context_max_bytes=700,
        )

        result = application.run(
            json.dumps({
                "hook_event_name": "SubagentStart",
                "session_id": "marker-injection",
                "agent_id": "worker-marker",
                "agent_type": "general-purpose",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "marker-injection.jsonl"),
            }),
            {"CLAUDE_PROJECT_DIR": str(self.root)},
        )
        context = self.hook_specific_output(result).get("additionalContext")

        self.assertEqual(0, result.exit_code)
        self.assertIsInstance(context, str)
        assert isinstance(context, str)
        self.assertIn(required_tail, context)
        self.assertIn("[neurath-context-truncated]", context)

    def test_subagent_start_blocks_when_load_bearing_assignment_exceeds_context_budget(
        self,
    ) -> None:
        """Assignment 자체가 host budget을 넘으면 잘린 prompt로 실행하지 않고 fail closed합니다."""
        root_actor = self.start_session("session-a", SessionRuntime.CLAUDE_CODE, "optional")
        worker = ActorId("claude-code:worker-overflow")
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("session-a"),
                actor_id=worker,
                parent_actor_id=root_actor,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:worker-overflow",
            )
        )
        self.kernel.apply(
            DelegationAssigned(
                session_id=SessionId("session-a"),
                delegation_id=DelegationId("delegation-overflow"),
                owner_actor_id=root_actor,
                target_actor_id=worker,
                assignment="must-preserve-" + "x" * 1000,
                idempotency_key="delegation:overflow",
            )
        )
        application = RuntimeHookApplication(
            self.locator,
            enclave_max_bytes=4096,
            additional_context_max_bytes=256,
        )

        result = application.run(
            json.dumps({
                "hook_event_name": "SubagentStart",
                "session_id": "session-a",
                "agent_id": "worker-overflow",
                "agent_type": "general-purpose",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "session-a.jsonl"),
            }),
            {"CLAUDE_PROJECT_DIR": str(self.root)},
        )

        self.assertEqual(1, result.exit_code)
        self.assertEqual(RuntimeHookDiagnostic.CONTEXT_BUDGET_EXCEEDED, result.diagnostic)
        self.assertEqual("{}", result.stdout)

    def test_conflicting_exported_identity_fails_closed_before_state_mutation(self) -> None:
        """Payload와 inherited canonical identity가 다르면 어떤 session도 만들지 않습니다."""
        result = self.run_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "startup",
                "session_id": "payload-session",
                "cwd": str(self.root),
                "transcript_path": str(self.root / "payload-session.jsonl"),
            },
            {
                "CLAUDE_PROJECT_DIR": str(self.root),
                "NEURATH_AGENT_SESSION_ID": "inherited-session",
                "NEURATH_AGENT_RUNTIME": "codex",
            },
        )

        self.assertNotEqual(0, result.exit_code)
        self.assertEqual(RuntimeHookDiagnostic.IDENTITY_CONFLICT, result.diagnostic)
        self.assertNotIn("additionalContext", result.stdout)
        self.assertFalse(self.locator.locate(SessionId("payload-session")).process_state.exists())
        self.assertFalse(self.locator.locate(SessionId("inherited-session")).process_state.exists())


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
