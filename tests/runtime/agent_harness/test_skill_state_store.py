"""Workflow payload 안 skill-specific state의 optimistic store 계약을 검증합니다."""

import unittest
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock
from unittest import TestCase

from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStarted,
    SessionKernel,
    SessionLocator,
    WorkflowFinalized,
    WorkflowId,
    WorkflowStarted,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import (
    InvalidSkillState,
    SkillStateAuthorityError,
    SkillStateConflict,
    SkillStateReservedNamespaceError,
    SkillStateStore,
    SkillStateWorkflowNotFound,
    SkillStateWorkflowTerminal,
)
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle


class IncrementMutation:
    """Barrier로 첫 두 transform을 겹치게 만드는 pure counter mutation입니다."""

    def __init__(self, barrier: Barrier, key: str) -> None:
        """Concurrency 경계를 공유하는 key increment를 준비합니다."""
        self._barrier = barrier
        self._key = key
        self._calls = 0
        self._lock = Lock()

    @property
    def calls(self) -> int:
        """Retry를 포함해 transformer가 실행된 횟수를 반환합니다."""
        with self._lock:
            return self._calls

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current counter를 하나 높인 새 object를 반환합니다."""
        with self._lock:
            self._calls += 1
            call = self._calls
        if call == 1:
            self._barrier.wait()
        value = current.get(self._key, 0)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("counter fixture requires an integer")
        return {**current, self._key: value + 1}


class BlockingNoOpMutation:
    """Competing workflow commit이 끝날 때까지 no-op transform 반환을 지연합니다."""

    def __init__(self, started: Event, release: Event) -> None:
        """Transform 진입과 반환 허용 신호를 공유합니다."""
        self._started = started
        self._release = release

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """원본 object를 그대로 반환하되 competing commit 뒤까지 대기합니다."""
        self._started.set()
        if not self._release.wait(timeout=5):
            raise TimeoutError("no-op mutation was not released")
        return current


class SkillStateStoreTest(TestCase):
    """StateHandle-bound workflow namespace의 read, CAS, retry를 검증합니다."""

    def _make_fixture(
        self,
        *,
        kind: str = "process-ticket",
    ) -> tuple[SessionLocator, StateHandle, WorkflowId, SkillStateStore]:
        """Root-owned active workflow와 unrelated phase payload를 준비합니다.

        Args:
            kind: Store 경계만 검증할 때 선택하는 workflow의 실제 실행 종류입니다.

        Returns:
            격리 locator, owner, workflow identity와 해당 namespace store입니다.
        """
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        locator = SessionLocator(Path(directory.name))
        resolver = RuntimeEnvironmentResolver()
        root_binding = resolver.resolve({"CODEX_THREAD_ID": "skill-state-session"})
        handle = StateHandle.initialize(locator, root_binding)
        workflow_id = WorkflowId("process-ticket-42")
        handle.apply(
            WorkflowStarted(
                session_id=handle.session_id,
                workflow_id=workflow_id,
                owner_actor_id=handle.actor_id,
                kind=kind,
                goal="Issue #42를 완료한다",
                payload={
                    "phase_run": {"phase": 3, "status": "active"},
                    "skill_state": {"ticket": 42},
                },
                idempotency_key="workflow-started:process-ticket-42",
            )
        )
        return locator, handle, workflow_id, SkillStateStore(handle, workflow_id)

    def test_read_returns_exact_active_workflow_namespace_and_revision(self) -> None:
        """Read는 path fallback 없이 bound workflow의 object skill_state만 반환합니다."""
        _locator, _handle, workflow_id, store = self._make_fixture()

        snapshot = store.read()

        self.assertEqual(workflow_id, snapshot.workflow_id)
        self.assertEqual(0, snapshot.workflow_revision)
        self.assertEqual({"ticket": 42}, snapshot.skill_state)

    def test_public_surface_is_bound_to_handle_and_workflow_without_state_path(self) -> None:
        """Store DX는 StateHandle과 WorkflowId 외 manual file selector를 노출하지 않습니다."""
        _locator, _handle, _workflow_id, store = self._make_fixture()

        self.assertEqual(
            ("handle", "workflow_id", "max_retries"),
            tuple(signature(SkillStateStore).parameters),
        )
        self.assertEqual((), tuple(signature(store.read).parameters))
        self.assertEqual(("mutation",), tuple(signature(store.update).parameters))
        self.assertEqual(
            ("expected_workflow_revision", "mutation"),
            tuple(signature(store.compare_and_update).parameters),
        )
        self.assertFalse(hasattr(store, "path"))
        self.assertFalse(hasattr(store, "state_path"))

    def test_update_preserves_unrelated_payload_namespace(self) -> None:
        """Skill-state 갱신은 같은 workflow의 phase_run과 다른 payload를 그대로 보존합니다."""
        _locator, handle, workflow_id, store = self._make_fixture()

        updated = store.update({"status": "monitoring"})
        workflow = handle.inspect().workflows[workflow_id]

        self.assertEqual(
            {"ticket": 42, "status": "monitoring"},
            updated.skill_state,
        )
        self.assertEqual({"phase": 3, "status": "active"}, workflow.payload["phase_run"])
        self.assertEqual(updated.workflow_revision, workflow.revision)

    def test_generic_mutation_cannot_create_reserved_adaptive_state(self) -> None:
        """SkillStateStore generic mutation는 adaptive_control namespace를 생성하지 못합니다."""
        _locator, _handle, _workflow_id, store = self._make_fixture()
        with self.assertRaises(SkillStateReservedNamespaceError):
            store.update({"adaptive_control": {"fabricated": True}})

    def test_update_does_not_persist_retry_or_operation_metadata(self) -> None:
        """Optimistic retry는 revision을 쓰며 workflow payload에 별도 marker를 남기지 않습니다."""
        _locator, handle, workflow_id, store = self._make_fixture()

        store.update({"status": "monitoring"})

        payload = handle.inspect().workflows[workflow_id].payload
        self.assertEqual({"phase_run", "skill_state"}, set(payload))

    def test_explicit_compare_and_update_does_not_hide_stale_revision(self) -> None:
        """Explicit workflow CAS는 stale 원본을 재시도하거나 overwrite하지 않습니다."""
        _locator, _handle, _workflow_id, store = self._make_fixture()
        stale = store.read()
        store.update({"status": "published"})

        with self.assertRaises(SkillStateConflict):
            store.compare_and_update(
                stale.workflow_revision,
                {"status": "stale-overwrite"},
            )

        self.assertEqual("published", store.read().skill_state["status"])

    def test_explicit_no_op_rechecks_revision_after_competing_commit(self) -> None:
        """Explicit no-op CAS도 transform 중 바뀐 workflow revision을 conflict로 거부합니다."""
        _locator, _handle, _workflow_id, store = self._make_fixture()
        original = store.read()
        started = Event()
        release = Event()
        mutation = BlockingNoOpMutation(started, release)

        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                store.compare_and_update,
                original.workflow_revision,
                mutation,
            )
            self.assertTrue(started.wait(timeout=5))
            committed = store.update({"status": "published"})
            self.assertEqual(original.workflow_revision + 1, committed.workflow_revision)
            release.set()

            with self.assertRaises(SkillStateConflict):
                pending.result(timeout=5)

        latest = store.read()
        self.assertEqual(committed.workflow_revision, latest.workflow_revision)
        self.assertEqual("published", latest.skill_state["status"])

    def test_current_explicit_and_implicit_no_ops_do_not_advance_revision(self) -> None:
        """Revision이 일치하는 explicit·implicit no-op은 current snapshot을 그대로 둡니다."""
        _locator, _handle, _workflow_id, store = self._make_fixture()
        original = store.read()

        explicit = store.compare_and_update(original.workflow_revision, {})
        implicit = store.update({})
        latest = store.read()

        self.assertEqual(original.workflow_revision, explicit.workflow_revision)
        self.assertEqual(original.workflow_revision, implicit.workflow_revision)
        self.assertEqual(original.workflow_revision, latest.workflow_revision)
        self.assertEqual(original.skill_state, latest.skill_state)

    def test_concurrent_different_key_updates_do_not_lose_either_change(self) -> None:
        """같은 원본에서 겹친 서로 다른 key mutation은 latest snapshot에 재적용됩니다."""
        _locator, _handle, _workflow_id, store = self._make_fixture()
        barrier = Barrier(2)
        left = IncrementMutation(barrier, "comments_seen")
        right = IncrementMutation(barrier, "checks_seen")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    lambda mutation: store.update(mutation),
                    (left, right),
                )
            )

        latest = store.read()
        self.assertEqual(1, latest.skill_state["comments_seen"])
        self.assertEqual(1, latest.skill_state["checks_seen"])
        self.assertEqual({1, 2}, {result.workflow_revision for result in results})
        self.assertEqual(3, left.calls + right.calls)

    def test_concurrent_same_key_updates_retry_deterministically(self) -> None:
        """동일 counter key의 충돌은 pure transform 재실행으로 두 increment를 모두 보존합니다."""
        _locator, _handle, _workflow_id, store = self._make_fixture()
        barrier = Barrier(2)
        left = IncrementMutation(barrier, "attempts")
        right = IncrementMutation(barrier, "attempts")

        with ThreadPoolExecutor(max_workers=2) as executor:
            tuple(
                executor.map(
                    lambda mutation: store.update(mutation),
                    (left, right),
                )
            )

        self.assertEqual(2, store.read().skill_state["attempts"])
        self.assertEqual(3, left.calls + right.calls)

    def test_missing_wrong_owner_and_terminal_workflows_fail_closed(self) -> None:
        """Missing workflow, 다른 owner, terminal aggregate는 모두 skill mutation을 거부합니다."""
        locator, handle, workflow_id, store = self._make_fixture(kind="checkpoint")
        missing = SkillStateStore(handle, WorkflowId("missing"))
        with self.assertRaises(SkillStateWorkflowNotFound):
            missing.read()

        worker_id = ActorId("codex:worker")
        handle.apply(
            ActorStarted(
                session_id=handle.session_id,
                actor_id=worker_id,
                parent_actor_id=handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor-started:worker",
            )
        )
        worker_workflow_id = WorkflowId("worker-workflow")
        SessionKernel(locator).apply(
            WorkflowStarted(
                session_id=handle.session_id,
                workflow_id=worker_workflow_id,
                owner_actor_id=worker_id,
                kind="investigate",
                goal=None,
                payload={"skill_state": {}},
                idempotency_key="workflow-started:worker-workflow",
            )
        )
        with self.assertRaises(SkillStateAuthorityError):
            SkillStateStore(handle, worker_workflow_id).update({"forbidden": True})

        current = store.read()
        handle.apply(
            WorkflowFinalized(
                session_id=handle.session_id,
                workflow_id=workflow_id,
                actor_id=handle.actor_id,
                expected_workflow_revision=current.workflow_revision,
                terminal_status=WorkflowStatus.FAILED,
                payload=handle.inspect().workflows[workflow_id].payload,
                idempotency_key="workflow-finalized:process-ticket-42",
            )
        )
        with self.assertRaises(SkillStateWorkflowTerminal):
            store.update({"forbidden": True})

    def test_missing_or_non_object_skill_state_is_rejected(self) -> None:
        """Workflow payload의 skill_state namespace가 없거나 object가 아니면 fail closed합니다."""
        _locator, handle, _workflow_id, _store = self._make_fixture()
        cases = (
            (WorkflowId("missing-namespace"), {"phase_run": {"phase": 1}}),
            (WorkflowId("scalar-namespace"), {"skill_state": "invalid"}),
        )
        for workflow_id, payload in cases:
            with self.subTest(workflow_id=workflow_id):
                handle.apply(
                    WorkflowStarted(
                        session_id=handle.session_id,
                        workflow_id=workflow_id,
                        owner_actor_id=handle.actor_id,
                        kind="process-ticket",
                        goal=None,
                        payload=payload,
                        idempotency_key=f"workflow-started:{workflow_id}",
                    )
                )
                with self.assertRaises(InvalidSkillState):
                    SkillStateStore(handle, workflow_id).read()


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
