"""Session enclave의 latest-only, authority, size 계약을 검증합니다."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.enclave_store import (
    EnclaveAuthorityError,
    EnclaveBudgetExceeded,
    EnclaveConflict,
    EnclaveFact,
    EnclaveSnapshot,
    EnclaveSourceKind,
    EnclaveStore,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ProcessState,
    ResumeId,
    SessionEnded,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    SessionStatus,
    TurnId,
)


class CompareCommitInterleaving:
    """Enclave commit 진입과 test가 먼저 확정할 state event 사이를 동기화합니다."""

    def __init__(
        self,
        test_case: TestCase,
        entered: Event,
        allowed: Event,
        original: Callable[
            [Path, SessionId, ProcessState, str, EnclaveSnapshot, bytes],
            EnclaveSnapshot,
        ],
    ) -> None:
        """원래 commit과 양방향 interleaving signal을 보존합니다.

        Args:
            test_case: Timeout을 test failure로 노출할 unittest case입니다.
            entered: Commit 준비가 끝났음을 알릴 signal입니다.
            allowed: Test state event 뒤 commit을 재개할 signal입니다.
            original: Signal 뒤 호출할 실제 compare-and-commit method입니다.
        """
        self._test_case = test_case
        self._entered = entered
        self._allowed = allowed
        self._original = original

    def __call__(
        self,
        enclave_path: Path,
        session_id: SessionId,
        expected_authority: ProcessState,
        expected_digest: str,
        candidate: EnclaveSnapshot,
        serialized: bytes,
    ) -> EnclaveSnapshot:
        """Commit mutex 전에 test가 SessionEnded를 확정할 때까지 기다립니다.

        Args:
            enclave_path: Exact session enclave path입니다.
            session_id: Mutation 대상 exact session입니다.
            expected_authority: Candidate 계산 전 authority snapshot입니다.
            expected_digest: Candidate 원본 enclave digest입니다.
            candidate: Lock 밖에서 계산된 enclave snapshot입니다.
            serialized: Lock 밖에서 준비된 candidate bytes입니다.

        Returns:
            Test interleaving 뒤 실제 commit 결과입니다.
        """
        self._entered.set()
        if not self._allowed.wait(timeout=5):
            self._test_case.fail("timed out waiting for SessionEnded interleaving")
        return self._original(
            enclave_path,
            session_id,
            expected_authority,
            expected_digest,
            candidate,
            serialized,
        )


class SerializationInterleaving:
    """Candidate 직렬화와 concurrent state mutation 사이를 동기화합니다."""

    def __init__(
        self,
        test_case: TestCase,
        prepared: Event,
        allowed: Event,
        original: Callable[[EnclaveSnapshot], bytes],
        timeout_message: str,
    ) -> None:
        """원래 serializer와 양방향 interleaving signal을 보존합니다.

        Args:
            test_case: Timeout을 test failure로 노출할 unittest case입니다.
            prepared: Candidate 직렬화가 끝났음을 알릴 signal입니다.
            allowed: Concurrent mutation 뒤 caller를 재개할 signal입니다.
            original: Signal 전에 호출할 실제 serializer입니다.
            timeout_message: Interleaving이 수렴하지 않을 때의 test failure입니다.
        """
        self._test_case = test_case
        self._prepared = prepared
        self._allowed = allowed
        self._original = original
        self._timeout_message = timeout_message

    def __call__(self, snapshot: EnclaveSnapshot) -> bytes:
        """Candidate를 준비한 뒤 concurrent mutation 완료까지 기다립니다.

        Args:
            snapshot: Lock 밖에서 직렬화할 candidate입니다.

        Returns:
            Concurrent mutation 전에 준비된 canonical bytes입니다.
        """
        serialized = self._original(snapshot)
        self._prepared.set()
        if not self._allowed.wait(timeout=5):
            self._test_case.fail(self._timeout_message)
        return serialized


class EnclaveStoreAcceptanceTest(TestCase):
    """H07의 session-local current-fact 저장소 불변식을 검증합니다."""

    def setUp(self) -> None:
        """Root actor가 있는 canonical session과 bounded enclave store를 준비합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.control_root = Path(self.temporary_directory.name)
        self.locator = SessionLocator(self.control_root)
        self.kernel = SessionKernel(self.locator)
        self.session_id = SessionId("enclave-session")
        self.root_actor_id = ActorId("codex:root")
        self.subagent_id = ActorId("codex:subagent")
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("opaque-resume"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.root_actor_id,
                idempotency_key="session-started:enclave-session",
            )
        )
        self.store = EnclaveStore(self.locator, max_bytes=1_024)

    @staticmethod
    def fact(value: str, turn_id: str) -> EnclaveFact:
        """User-provenance를 가진 현재 session fact를 만듭니다."""
        return EnclaveFact(
            value=value,
            source_kind=EnclaveSourceKind.USER,
            source_turn_id=TurnId(turn_id),
        )

    def test_set_overwrites_same_key_without_history_or_version_metadata(self) -> None:
        """같은 key의 두 번째 set은 이전 fact를 완전히 교체하고 history를 남기지 않습니다."""
        self.store.set(
            self.session_id,
            self.root_actor_id,
            "browser-policy",
            self.fact("브라우저 실측 금지", "turn-1"),
        )

        snapshot = self.store.set(
            self.session_id,
            self.root_actor_id,
            "browser-policy",
            self.fact("브라우저 실측 허용", "turn-2"),
        )
        payload = snapshot.to_payload()
        facts_payload = payload["facts"]
        if not isinstance(facts_payload, dict):
            self.fail("enclave facts payload must be an object")
        fact_payload = facts_payload["browser-policy"]
        if not isinstance(fact_payload, dict):
            self.fail("enclave fact payload must be an object")

        self.assertEqual("브라우저 실측 허용", snapshot.facts["browser-policy"].value)
        self.assertEqual("turn-2", fact_payload["source_turn_id"])
        self.assertEqual({"schema", "session_id", "facts"}, set(payload))
        self.assertEqual(
            {"value", "source_kind", "source_turn_id"},
            set(fact_payload),
        )
        serialized = json.dumps(self.store.read(self.session_id).to_payload(), ensure_ascii=False)
        for forbidden in (
            "브라우저 실측 금지",
            "history",
            "previous",
            "revision",
            "superseded_by",
            "tombstone",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_delete_removes_fact_without_tombstone_or_history(self) -> None:
        """Delete는 key와 과거 값을 완전히 제거하고 tombstone을 남기지 않습니다."""
        self.store.set(
            self.session_id,
            self.root_actor_id,
            "temporary-policy",
            self.fact("나중에 제거", "turn-1"),
        )

        snapshot = self.store.delete(
            self.session_id,
            self.root_actor_id,
            "temporary-policy",
        )
        serialized = json.dumps(self.store.read(self.session_id).to_payload(), ensure_ascii=False)

        self.assertEqual({}, snapshot.facts)
        self.assertNotIn("temporary-policy", serialized)
        self.assertNotIn("나중에 제거", serialized)
        self.assertNotIn("tombstone", serialized)
        self.assertNotIn("history", serialized)

    def test_subagent_cannot_directly_mutate_session_wide_enclave(self) -> None:
        """Subagent는 proposal 경계를 우회해 root-authoritative enclave를 직접 확정할 수 없습니다."""
        enclave_before = self.store.read(self.session_id).to_payload()

        with self.assertRaises(EnclaveAuthorityError):
            self.store.set(
                self.session_id,
                self.subagent_id,
                "unauthorized-fact",
                self.fact("직접 mutation", "turn-subagent"),
            )

        self.assertEqual(
            enclave_before,
            self.store.read(self.session_id).to_payload(),
        )

    def test_oversized_mutation_fails_closed_without_changing_existing_enclave(self) -> None:
        """Byte budget을 넘는 set은 거부되고 직전 canonical enclave를 그대로 보존합니다."""
        self.store.set(
            self.session_id,
            self.root_actor_id,
            "stable-fact",
            self.fact("유지되어야 함", "turn-1"),
        )
        canonical_before = self.store.read(self.session_id).to_payload()

        with self.assertRaises(EnclaveBudgetExceeded):
            self.store.set(
                self.session_id,
                self.root_actor_id,
                "oversized-fact",
                self.fact("x" * 4_096, "turn-2"),
            )

        self.assertEqual(canonical_before, self.store.read(self.session_id).to_payload())
        self.assertEqual(
            {"stable-fact"},
            set(self.store.read(self.session_id).facts),
        )

    def test_stale_expected_digest_rejects_mutation_without_overwriting_newer_fact(self) -> None:
        """오래된 원본 digest를 제출한 writer는 최신 enclave를 덮어쓰지 못합니다."""
        original = self.store.read(self.session_id)
        current = self.store.set(
            self.session_id,
            self.root_actor_id,
            "current-policy",
            self.fact("최신 지시", "turn-2"),
            expected_digest=original.digest,
        )

        with self.assertRaises(EnclaveConflict):
            self.store.set(
                self.session_id,
                self.root_actor_id,
                "stale-policy",
                self.fact("낡은 지시", "turn-1"),
                expected_digest=original.digest,
            )

        persisted = self.store.read(self.session_id)
        self.assertEqual(current.digest, persisted.digest)
        self.assertEqual({"current-policy"}, set(persisted.facts))

    def test_implicit_writers_retry_from_latest_digest_without_lost_updates(self) -> None:
        """Concurrent implicit set은 짧은 CAS conflict 후 latest snapshot에서 다시 계산합니다."""
        concurrent_store = EnclaveStore(self.locator, max_bytes=32_768)
        keys = tuple(f"concurrent-{index}" for index in range(24))

        def set_fact(key: str) -> None:
            """Concurrent writer 하나의 implicit optimistic set을 수행합니다.

            Args:
                key: 다른 writer와 겹치지 않는 stable enclave key입니다.
            """
            concurrent_store.set(
                self.session_id,
                self.root_actor_id,
                key,
                self.fact(f"value-{key}", f"turn-{key}"),
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            tuple(executor.map(set_fact, keys))

        snapshot = concurrent_store.read(self.session_id)
        self.assertEqual(set(keys), set(snapshot.facts))

    def test_session_end_winning_set_commit_fence_rejects_late_fact(self) -> None:
        """Set commit보다 SessionEnded가 먼저 확정되면 terminal session에 fact를 쓰지 않습니다."""
        commit_entered = Event()
        allow_commit = Event()
        self.addCleanup(allow_commit.set)
        interleaving = CompareCommitInterleaving(
            self,
            commit_entered,
            allow_commit,
            self.store._compare_and_commit,
        )

        with (
            patch.object(
                self.store,
                "_compare_and_commit",
                side_effect=interleaving,
            ),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            mutation = executor.submit(
                self.store.set,
                self.session_id,
                self.root_actor_id,
                "late-fact",
                self.fact("must not survive SessionEnded", "turn-late"),
            )
            self.assertTrue(commit_entered.wait(timeout=5))
            ended = self.kernel.apply(
                SessionEnded(
                    session_id=self.session_id,
                    actor_id=self.root_actor_id,
                    idempotency_key="end-before-enclave-set-commit",
                )
            )
            allow_commit.set()

            with self.assertRaises(EnclaveAuthorityError):
                mutation.result(timeout=5)

        self.assertIs(SessionStatus.ENDED, ended.session.status)
        self.assertNotIn("late-fact", self.store.read(self.session_id).facts)

    def test_session_end_winning_noop_delete_fence_rejects_terminal_mutation(self) -> None:
        """No-op delete도 final authority fence를 건너뛰어 terminal success를 반환하지 않습니다."""
        candidate_prepared = Event()
        allow_commit = Event()
        self.addCleanup(allow_commit.set)
        interleaving = SerializationInterleaving(
            self,
            candidate_prepared,
            allow_commit,
            self.store._serialize,
            "timed out waiting for SessionEnded interleaving",
        )

        with (
            patch.object(self.store, "_serialize", side_effect=interleaving),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            mutation = executor.submit(
                self.store.delete,
                self.session_id,
                self.root_actor_id,
                "already-absent",
            )
            self.assertTrue(candidate_prepared.wait(timeout=5))
            ended = self.kernel.apply(
                SessionEnded(
                    session_id=self.session_id,
                    actor_id=self.root_actor_id,
                    idempotency_key="end-before-enclave-delete-commit",
                )
            )
            allow_commit.set()

            with self.assertRaises(EnclaveAuthorityError):
                mutation.result(timeout=5)

        self.assertIs(SessionStatus.ENDED, ended.session.status)
        self.assertEqual({}, self.store.read(self.session_id).facts)

    def test_explicit_noop_set_rechecks_digest_after_candidate_preparation(self) -> None:
        """Explicit no-op set은 final mutex 전에 바뀐 enclave를 stale success로 반환하지 않습니다."""
        fact = self.fact("stable", "turn-stable")
        expected = self.store.set(
            self.session_id,
            self.root_actor_id,
            "stable-fact",
            fact,
        )
        candidate_prepared = Event()
        allow_commit = Event()
        self.addCleanup(allow_commit.set)
        interleaving = SerializationInterleaving(
            self,
            candidate_prepared,
            allow_commit,
            self.store._serialize,
            "timed out waiting for concurrent enclave mutation",
        )

        with (
            patch.object(
                self.store,
                "_serialize",
                side_effect=interleaving,
            ),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            mutation = executor.submit(
                self.store.set,
                self.session_id,
                self.root_actor_id,
                "stable-fact",
                fact,
                expected_digest=expected.digest,
            )
            self.assertTrue(candidate_prepared.wait(timeout=5))
            EnclaveStore(self.locator, max_bytes=1_024).set(
                self.session_id,
                self.root_actor_id,
                "concurrent-fact",
                self.fact("newer", "turn-newer"),
            )
            allow_commit.set()

            with self.assertRaises(EnclaveConflict):
                mutation.result(timeout=5)

        self.assertEqual(
            {"stable-fact", "concurrent-fact"},
            set(self.store.read(self.session_id).facts),
        )

    def test_explicit_noop_delete_rechecks_digest_after_candidate_preparation(self) -> None:
        """Explicit no-op delete도 final mutex에서 concurrent enclave digest를 비교합니다."""
        expected = self.store.read(self.session_id)
        candidate_prepared = Event()
        allow_commit = Event()
        self.addCleanup(allow_commit.set)
        interleaving = SerializationInterleaving(
            self,
            candidate_prepared,
            allow_commit,
            self.store._serialize,
            "timed out waiting for concurrent enclave mutation",
        )

        with (
            patch.object(
                self.store,
                "_serialize",
                side_effect=interleaving,
            ),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            mutation = executor.submit(
                self.store.delete,
                self.session_id,
                self.root_actor_id,
                "already-absent",
                expected_digest=expected.digest,
            )
            self.assertTrue(candidate_prepared.wait(timeout=5))
            EnclaveStore(self.locator, max_bytes=1_024).set(
                self.session_id,
                self.root_actor_id,
                "concurrent-fact",
                self.fact("newer", "turn-newer"),
            )
            allow_commit.set()

            with self.assertRaises(EnclaveConflict):
                mutation.result(timeout=5)

        self.assertEqual(
            {"concurrent-fact"},
            set(self.store.read(self.session_id).facts),
        )

    def test_implicit_noop_set_and_delete_remain_idempotent_after_commit_fence(self) -> None:
        """Implicit no-op은 final fence를 통과하되 enclave content를 바꾸지 않습니다."""
        fact = self.fact("stable", "turn-stable")
        original = self.store.set(
            self.session_id,
            self.root_actor_id,
            "stable-fact",
            fact,
        )

        after_set = self.store.set(
            self.session_id,
            self.root_actor_id,
            "stable-fact",
            fact,
        )
        after_delete = self.store.delete(
            self.session_id,
            self.root_actor_id,
            "already-absent",
        )

        self.assertEqual(original.digest, after_set.digest)
        self.assertEqual(original.digest, after_delete.digest)
        self.assertEqual(original.digest, self.store.read(self.session_id).digest)


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    import unittest

    unittest.main()
