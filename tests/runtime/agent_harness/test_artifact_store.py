"""Session-scoped content-addressed artifact store 회귀 테스트입니다."""

from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.artifact_store import (
    ArtifactNotFound,
    SessionArtifactStore,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStarted,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
)
from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle


class SessionArtifactStoreTest(TestCase):
    """Delegation detail이 owner workflow state를 우회하지 않고 session에 격리됨을 검증합니다."""

    def setUp(self) -> None:
        """Root와 target actor가 있는 exact session을 생성합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.control_root = Path(self.temporary_directory.name)
        self.locator = SessionLocator(self.control_root)
        self.kernel = SessionKernel(self.locator)
        self.session_id = SessionId("artifact-session")
        self.root_actor_id = ActorId("codex:artifact-session")
        self.target_actor_id = ActorId("codex:reviewer")
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume-artifact-session"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.root_actor_id,
                idempotency_key="artifact-session-start",
            )
        )
        self.kernel.apply(
            ActorStarted(
                session_id=self.session_id,
                actor_id=self.target_actor_id,
                parent_actor_id=self.root_actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="artifact-target-start",
            )
        )

    def test_target_writes_immutable_detail_and_owner_reads_by_verified_digest(self) -> None:
        """Target artifact는 digest identity로 고정되고 owner가 exact payload를 readback합니다."""
        target_store = SessionArtifactStore(self._handle(self.target_actor_id))
        owner_store = SessionArtifactStore(self._handle(self.root_actor_id))
        payload = {
            "matrix_id": "matrix-17",
            "review_findings": [],
            "verified_rows": ["correctness", "security"],
            "verdict": "pass",
        }

        first = target_store.put_json(payload)
        repeated = target_store.put_json(payload)

        self.assertEqual(first.reference, repeated.reference)
        self.assertEqual(payload, owner_store.read_json(first.reference))
        self.assertEqual("application/json", first.media_type)
        self.assertGreater(first.size_bytes, 0)
        artifact_files = tuple(
            path
            for path in self.locator.locate(self.session_id).artifacts.rglob("*.json")
            if path.is_file()
        )
        self.assertEqual(0, len(artifact_files))
        self.assertTrue(owner_store.has_artifacts())

    def test_same_reference_never_falls_back_to_another_session_directory(self) -> None:
        """같은 repository의 다른 session artifact를 digest만으로 scan하지 않습니다."""
        reference = SessionArtifactStore(self._handle(self.target_actor_id)).put_json({"ok": True})
        other_session_id = SessionId("other-artifact-session")
        other_actor_id = ActorId("codex:other-artifact-session")
        self.kernel.apply(
            SessionStarted(
                session_id=other_session_id,
                resume_id=ResumeId("resume-other-artifact-session"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=other_actor_id,
                idempotency_key="other-artifact-session-start",
            )
        )
        other_store = SessionArtifactStore(
            StateHandle.attach(
                self.locator,
                RuntimeIdentityBinding(
                    runtime=SessionRuntime.CODEX,
                    session_id=other_session_id,
                    actor_id=other_actor_id,
                    root_actor_id=other_actor_id,
                ),
            )
        )

        with self.assertRaises(ArtifactNotFound):
            other_store.read_json(reference.reference)

    def test_public_surface_has_no_state_or_artifact_path_selector(self) -> None:
        """Caller-facing constructor와 operations는 canonical path를 받지 않습니다."""
        constructor = signature(SessionArtifactStore)
        put_json = signature(SessionArtifactStore.put_json)
        read_json = signature(SessionArtifactStore.read_json)

        self.assertEqual(("handle",), tuple(constructor.parameters))
        for operation in (put_json, read_json):
            parameters = set(operation.parameters)
            self.assertNotIn("path", parameters)
            self.assertNotIn("state", parameters)
            self.assertNotIn("session_id", parameters)

    def _handle(self, actor_id: ActorId) -> StateHandle:
        return StateHandle.attach(
            self.locator,
            RuntimeIdentityBinding(
                runtime=SessionRuntime.CODEX,
                session_id=self.session_id,
                actor_id=actor_id,
                root_actor_id=self.root_actor_id,
            ),
        )
