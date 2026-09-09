"""Runtime identity로 exact session state를 여는 StateHandle DX 계약입니다."""

import unittest
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStarted,
    DelegationAssigned,
    DelegationId,
    RevisionConflict,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionNotFound,
    SessionRuntime,
    SessionStateStore,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityConflict,
    RuntimeIdentityUnavailable,
    StateHandle,
    StateHandleAuthorityError,
)


class RuntimeEnvironmentResolverTest(TestCase):
    """Runtime-owned environment를 canonical session/actor binding으로 검증합니다."""

    def test_vendor_root_identity_has_codex_and_claude_parity(self) -> None:
        """Codex thread와 Claude session은 각각 exact root session/actor binding을 만듭니다."""
        resolver = RuntimeEnvironmentResolver()
        cases = (
            (
                {"CODEX_THREAD_ID": "thread-a"},
                SessionRuntime.CODEX,
                SessionId("thread-a"),
                ActorId("codex:session:thread-a"),
            ),
            (
                {"CLAUDE_CODE_SESSION_ID": "claude-session-a"},
                SessionRuntime.CLAUDE_CODE,
                SessionId("claude-session-a"),
                ActorId("claude-code:session:claude-session-a"),
            ),
        )

        for environment, runtime, session_id, actor_id in cases:
            with self.subTest(runtime=runtime):
                binding = resolver.resolve(environment)

                self.assertEqual(runtime, binding.runtime)
                self.assertEqual(session_id, binding.session_id)
                self.assertEqual(actor_id, binding.actor_id)

    def test_matching_injected_identity_can_bind_a_subagent_for_each_runtime(self) -> None:
        """Validated Neurath identity는 vendor session/runtime을 유지하며 현재 subagent만 좁힙니다."""
        resolver = RuntimeEnvironmentResolver()
        cases = (
            (
                {
                    "CODEX_THREAD_ID": "thread-a",
                    "NEURATH_AGENT_SESSION_ID": "thread-a",
                    "NEURATH_AGENT_ACTOR_ID": "codex:worker-7",
                    "NEURATH_AGENT_RUNTIME": "codex",
                },
                SessionRuntime.CODEX,
                ActorId("codex:worker-7"),
            ),
            (
                {
                    "CLAUDE_CODE_SESSION_ID": "claude-session-a",
                    "NEURATH_AGENT_SESSION_ID": "claude-session-a",
                    "NEURATH_AGENT_ACTOR_ID": "claude-code:worker-7",
                    "NEURATH_AGENT_RUNTIME": "claude-code",
                },
                SessionRuntime.CLAUDE_CODE,
                ActorId("claude-code:worker-7"),
            ),
        )

        for environment, runtime, actor_id in cases:
            with self.subTest(runtime=runtime):
                binding = resolver.resolve(environment)

                self.assertEqual(runtime, binding.runtime)
                self.assertEqual(
                    SessionId(environment["NEURATH_AGENT_SESSION_ID"]), binding.session_id
                )
                self.assertEqual(actor_id, binding.actor_id)

    def test_claude_hook_agent_id_narrows_an_inherited_root_overlay(self) -> None:
        """Official subagent hook payload는 inherited root overlay를 exact child로 좁힙니다."""
        resolver = RuntimeEnvironmentResolver()
        environment = {
            "CLAUDE_CODE_SESSION_ID": "claude-session-a",
            "NEURATH_AGENT_SESSION_ID": "claude-session-a",
            "NEURATH_AGENT_ACTOR_ID": "claude-code:session:claude-session-a",
            "NEURATH_AGENT_RUNTIME": "claude-code",
        }

        binding = resolver.resolve_hook_actor(environment, "worker-7", "claude-session-a")

        self.assertEqual(SessionRuntime.CLAUDE_CODE, binding.runtime)
        self.assertEqual(SessionId("claude-session-a"), binding.session_id)
        self.assertEqual(ActorId("claude-code:worker-7"), binding.actor_id)
        self.assertEqual(
            ActorId("claude-code:session:claude-session-a"),
            binding.root_actor_id,
        )

        with self.assertRaises(RuntimeIdentityConflict):
            resolver.resolve_hook_actor(
                {
                    **environment,
                    "NEURATH_AGENT_ACTOR_ID": "claude-code:another-worker",
                },
                "worker-7",
                "claude-session-a",
            )
        codex_child = resolver.resolve_hook_actor(
            {"CODEX_THREAD_ID": "thread-a"},
            "worker-7",
            "thread-a",
        )
        self.assertEqual(SessionRuntime.CODEX, codex_child.runtime)
        self.assertEqual(ActorId("codex:worker-7"), codex_child.actor_id)

    def test_missing_or_ambiguous_vendor_identity_fails_closed(self) -> None:
        """Vendor identity가 없거나 두 runtime이 동시에 보이면 임의 session을 선택하지 않습니다."""
        resolver = RuntimeEnvironmentResolver()

        with self.assertRaises(RuntimeIdentityUnavailable):
            resolver.resolve({})

        with self.assertRaises(RuntimeIdentityConflict):
            resolver.resolve({
                "CODEX_THREAD_ID": "thread-a",
                "CLAUDE_CODE_SESSION_ID": "claude-session-a",
            })

    def test_codex_hook_payload_is_authoritative_when_adapter_proves_runtime(self) -> None:
        """Codex hook의 필수 session_id는 비공식 env가 없어도 exact root를 결속합니다."""
        resolver = RuntimeEnvironmentResolver()

        binding = resolver.resolve_hook_actor(
            {},
            None,
            "thread-a",
            hook_runtime=SessionRuntime.CODEX,
        )

        self.assertEqual(SessionRuntime.CODEX, binding.runtime)
        self.assertEqual(SessionId("thread-a"), binding.session_id)
        self.assertEqual(ActorId("codex:session:thread-a"), binding.actor_id)

    def test_hook_payload_without_proven_runtime_still_fails_closed(self) -> None:
        """Generic caller는 payload session_id만으로 vendor runtime을 추측할 수 없습니다."""
        resolver = RuntimeEnvironmentResolver()

        with self.assertRaises(RuntimeIdentityUnavailable):
            resolver.resolve_hook_actor({}, None, "thread-a")

    def test_injected_identity_must_be_complete_and_match_vendor_authority(self) -> None:
        """Partial, cross-session, cross-runtime, cross-vendor actor overlay는 모두 거부합니다."""
        resolver = RuntimeEnvironmentResolver()
        conflicting_environments = (
            {
                "CODEX_THREAD_ID": "thread-a",
                "NEURATH_AGENT_SESSION_ID": "thread-a",
            },
            {
                "CODEX_THREAD_ID": "thread-a",
                "NEURATH_AGENT_SESSION_ID": "thread-b",
                "NEURATH_AGENT_ACTOR_ID": "codex:worker-7",
                "NEURATH_AGENT_RUNTIME": "codex",
            },
            {
                "CODEX_THREAD_ID": "thread-a",
                "NEURATH_AGENT_SESSION_ID": "thread-a",
                "NEURATH_AGENT_ACTOR_ID": "codex:worker-7",
                "NEURATH_AGENT_RUNTIME": "claude-code",
            },
            {
                "CODEX_THREAD_ID": "thread-a",
                "NEURATH_AGENT_SESSION_ID": "thread-a",
                "NEURATH_AGENT_ACTOR_ID": "claude-code:worker-7",
                "NEURATH_AGENT_RUNTIME": "codex",
            },
        )

        for environment in conflicting_environments:
            with (
                self.subTest(environment=environment),
                self.assertRaises(RuntimeIdentityConflict),
            ):
                resolver.resolve(environment)


class StateHandleTest(TestCase):
    """Runtime-bound handle의 exact-session 조회와 actor authority를 검증합니다."""

    def _make_fixture(self) -> tuple[SessionLocator, RuntimeEnvironmentResolver]:
        """독립된 repository control root와 runtime resolver를 준비합니다."""
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        locator = SessionLocator(Path(temporary_directory.name))
        return locator, RuntimeEnvironmentResolver()

    def test_initialize_creates_only_the_exact_session_identity(self) -> None:
        """Initialize는 bound session/root actor만 만들고 workflow나 goal을 생성하지 않습니다."""
        locator, resolver = self._make_fixture()
        binding = resolver.resolve({"CODEX_THREAD_ID": "thread-a"})

        handle = StateHandle.initialize(locator, binding)
        state = handle.inspect()
        payload = state.to_payload()

        self.assertEqual(binding.session_id, state.session.id)
        self.assertEqual(binding.runtime, state.session.runtime)
        self.assertEqual(binding.actor_id, state.session.root_actor_id)
        self.assertEqual({}, state.workflows)
        self.assertNotIn("goal", payload)
        self.assertNotIn("north_star", payload)
        self.assertNotIn("goal", state.session.to_payload())
        self.assertTrue(
            SessionStateStore(
                locator.locate(binding.session_id).process_state
            ).exists()
        )

    def test_initialize_and_attach_separate_lifecycle_from_operational_access(self) -> None:
        """Lifecycle만 session을 시작하고 operational attach는 existing state만 엽니다."""
        locator, resolver = self._make_fixture()
        binding = resolver.resolve({"CODEX_THREAD_ID": "thread-a"})

        with self.assertRaises(SessionNotFound):
            StateHandle.attach(locator, binding)

        self.assertFalse(locator.locate(binding.session_id).process_state.exists())
        initialized = StateHandle.initialize(locator, binding)
        attached = StateHandle.attach(locator, binding)

        self.assertEqual(initialized.session_id, attached.session_id)
        self.assertEqual(initialized.actor_id, attached.actor_id)
        self.assertEqual(initialized.inspect().revision, attached.inspect().revision)

    def test_private_repository_readback_capability_exposes_only_bound_control_root(self) -> None:
        """Infrastructure adapter는 path selector 없이 handle에 bound된 repository root만 읽습니다."""
        locator, resolver = self._make_fixture()
        binding = resolver.resolve({"CODEX_THREAD_ID": "thread-a"})
        handle = StateHandle.initialize(locator, binding)

        repository_root = handle._repository_control_root()

        self.assertEqual(locator.control_root, repository_root)
        self.assertFalse(hasattr(handle, "repository_control_root"))

    def test_initialize_is_root_only_and_attach_never_repairs_missing_actor(self) -> None:
        """Subagent operational binding은 lifecycle registration을 우회해 새 actor를 만들지 못합니다."""
        locator, resolver = self._make_fixture()
        root_binding = resolver.resolve({"CODEX_THREAD_ID": "thread-a"})
        StateHandle.initialize(locator, root_binding)
        worker_binding = resolver.resolve({
            "CODEX_THREAD_ID": "thread-a",
            "NEURATH_AGENT_SESSION_ID": "thread-a",
            "NEURATH_AGENT_ACTOR_ID": "codex:worker-missing",
            "NEURATH_AGENT_RUNTIME": "codex",
        })

        with self.assertRaises(StateHandleAuthorityError):
            StateHandle.initialize(locator, worker_binding)
        with self.assertRaises(StateHandleAuthorityError):
            StateHandle.attach(locator, worker_binding)

        self.assertNotIn(
            ActorId("codex:worker-missing"),
            SessionKernel(locator).inspect(root_binding.session_id).actors,
        )

    def test_inspect_is_bound_to_one_session_without_cross_session_fallback(self) -> None:
        """같은 repository의 두 handle은 서로의 actor나 snapshot을 조회하지 않습니다."""
        locator, resolver = self._make_fixture()
        binding_a = resolver.resolve({"CODEX_THREAD_ID": "thread-a"})
        binding_b = resolver.resolve({"CODEX_THREAD_ID": "thread-b"})
        handle_a = StateHandle.initialize(locator, binding_a)
        handle_b = StateHandle.initialize(locator, binding_b)
        SessionKernel(locator).apply(
            ActorStarted(
                session_id=binding_a.session_id,
                actor_id=ActorId("codex:worker-a"),
                parent_actor_id=binding_a.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor-started:worker-a",
            )
        )

        state_a = handle_a.inspect()
        state_b = handle_b.inspect()

        self.assertEqual(SessionId("thread-a"), state_a.session.id)
        self.assertEqual(SessionId("thread-b"), state_b.session.id)
        self.assertIn(ActorId("codex:worker-a"), state_a.actors)
        self.assertNotIn(ActorId("codex:worker-a"), state_b.actors)

    def test_apply_rejects_an_event_bound_to_another_session(self) -> None:
        """Handle은 event의 session이 달라지면 그 exact target도 변경하지 않고 거부합니다."""
        locator, resolver = self._make_fixture()
        binding_a = resolver.resolve({"CODEX_THREAD_ID": "thread-a"})
        binding_b = resolver.resolve({"CODEX_THREAD_ID": "thread-b"})
        handle_a = StateHandle.initialize(locator, binding_a)
        handle_b = StateHandle.initialize(locator, binding_b)
        state_a_before = handle_a.inspect()
        state_b_before = handle_b.inspect()

        with self.assertRaises(StateHandleAuthorityError):
            handle_a.apply(
                ActorStarted(
                    session_id=binding_b.session_id,
                    actor_id=ActorId("codex:worker-b"),
                    parent_actor_id=binding_b.actor_id,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key="actor-started:worker-b",
                ),
                expected_revision=state_a_before.revision,
            )

        self.assertEqual(state_a_before.revision, handle_a.inspect().revision)
        self.assertEqual(state_b_before.revision, handle_b.inspect().revision)

    def test_subagent_can_mutate_as_itself_but_cannot_impersonate_another_actor(self) -> None:
        """Injected subagent authority는 자기 event를 허용하고 다른 owner의 event를 차단합니다."""
        locator, resolver = self._make_fixture()
        root_binding = resolver.resolve({"CLAUDE_CODE_SESSION_ID": "claude-session-a"})
        StateHandle.initialize(locator, root_binding)
        worker_actor_id = ActorId("claude-code:worker-7")
        SessionKernel(locator).apply(
            ActorStarted(
                session_id=root_binding.session_id,
                actor_id=worker_actor_id,
                parent_actor_id=root_binding.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor-started:worker-7",
            )
        )
        worker_binding = resolver.resolve({
            "CLAUDE_CODE_SESSION_ID": "claude-session-a",
            "NEURATH_AGENT_SESSION_ID": "claude-session-a",
            "NEURATH_AGENT_ACTOR_ID": str(worker_actor_id),
            "NEURATH_AGENT_RUNTIME": "claude-code",
        })
        worker_handle = StateHandle.attach(locator, worker_binding)

        allowed = worker_handle.apply(
            DelegationAssigned(
                session_id=worker_binding.session_id,
                delegation_id=DelegationId("worker-assignment"),
                owner_actor_id=worker_binding.actor_id,
                target_actor_id=root_binding.actor_id,
                assignment="worker-owned assignment",
                idempotency_key="delegation-assigned:worker-assignment",
            )
        )
        revision_before_spoof = allowed.revision

        self.assertIn(DelegationId("worker-assignment"), allowed.delegations)
        with self.assertRaises(StateHandleAuthorityError):
            worker_handle.apply(
                DelegationAssigned(
                    session_id=worker_binding.session_id,
                    delegation_id=DelegationId("spoofed-assignment"),
                    owner_actor_id=root_binding.actor_id,
                    target_actor_id=worker_binding.actor_id,
                    assignment="impersonated root assignment",
                    idempotency_key="delegation-assigned:spoofed-assignment",
                )
            )
        self.assertEqual(revision_before_spoof, worker_handle.inspect().revision)

    def test_apply_forwards_explicit_expected_revision_to_the_exact_session_kernel(self) -> None:
        """Public handle compare version은 exact session CAS에서 stale mutation을 거부합니다."""
        locator, resolver = self._make_fixture()
        binding = resolver.resolve({"CODEX_THREAD_ID": "thread-a"})
        handle = StateHandle.initialize(locator, binding)
        expected_revision = handle.inspect().revision
        committed_actor_id = ActorId("codex:worker-a")

        handle.apply(
            ActorStarted(
                session_id=binding.session_id,
                actor_id=committed_actor_id,
                parent_actor_id=binding.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor-started:worker-a",
            ),
            expected_revision=expected_revision,
        )

        with self.assertRaises(RevisionConflict):
            handle.apply(
                ActorStarted(
                    session_id=binding.session_id,
                    actor_id=ActorId("codex:worker-b"),
                    parent_actor_id=binding.actor_id,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key="actor-started:worker-b",
                ),
                expected_revision=expected_revision,
            )
        current = handle.inspect()
        self.assertEqual(expected_revision + 1, current.revision)
        self.assertIn(committed_actor_id, current.actors)
        self.assertNotIn(ActorId("codex:worker-b"), current.actors)

    def test_public_surface_has_no_manual_state_path(self) -> None:
        """StateHandle DX는 locator/binding 외에 path나 manual state selector를 노출하지 않습니다."""
        locator, resolver = self._make_fixture()
        binding = resolver.resolve({"CODEX_THREAD_ID": "thread-a"})
        handle = StateHandle.initialize(locator, binding)

        self.assertEqual(
            ("locator", "binding"),
            tuple(signature(StateHandle.initialize).parameters),
        )
        self.assertEqual(("locator", "binding"), tuple(signature(StateHandle.attach).parameters))
        self.assertFalse(hasattr(StateHandle, "open"))
        self.assertEqual((), tuple(signature(handle.inspect).parameters))
        self.assertEqual(
            ("event", "expected_revision"),
            tuple(signature(handle.apply).parameters),
        )
        self.assertFalse(hasattr(handle, "path"))
        self.assertFalse(hasattr(handle, "state_path"))
        self.assertFalse(hasattr(handle, "process_state_path"))


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
