"""Terminal session enclave deletion과 bounded retention 회귀 테스트입니다."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.enclave_store import (
    EnclaveAuthorityError,
    EnclaveFact,
    EnclaveSourceKind,
    EnclaveStore,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionNotFound,
    SessionRuntime,
    SessionStarted,
    TurnId,
)
from scripts.agent_harness.session_retention import (
    ActiveSessionRetentionError,
    SessionRetentionManager,
)
from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle


class MutableClock:
    """Test가 retention 경계를 결정적으로 이동시키는 monotonic wall clock입니다."""

    def __init__(self, value: float) -> None:
        """초기 epoch second를 저장합니다.

        Args:
            value: 첫 clock read가 반환할 epoch second입니다.
        """
        self.value = value

    def __call__(self) -> float:
        """현재 test epoch second를 반환합니다.

        Returns:
            Test가 마지막으로 지정한 epoch second입니다.
        """
        return self.value


class SessionRetentionAcceptanceTest(TestCase):
    """A21 terminal cleanup이 exact session 밖을 건드리지 않음을 검증합니다."""

    def setUp(self) -> None:
        """독립 control root와 root-authoritative session을 구성합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.control_root = Path(self.temporary_directory.name)
        self.locator = SessionLocator(self.control_root)
        self.session_id = SessionId("retention-session")
        self.actor_id = ActorId("codex:retention-session")
        self.kernel = SessionKernel(self.locator)
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume-retention-session"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.actor_id,
                idempotency_key="start-retention-session",
            )
        )
        self.handle = StateHandle.attach(
            self.locator,
            RuntimeIdentityBinding(
                runtime=SessionRuntime.CODEX,
                session_id=self.session_id,
                actor_id=self.actor_id,
                root_actor_id=self.actor_id,
            ),
        )

    def test_end_deletes_enclave_and_expired_state_is_collected_exactly_once(self) -> None:
        """End 즉시 enclave를 제거하고 retention 뒤 operational snapshot만 수거합니다."""
        enclaves = EnclaveStore(self.locator, max_bytes=4_096)
        current = enclaves.read(self.session_id)
        enclaves.set(
            self.session_id,
            self.actor_id,
            "current-invariant",
            EnclaveFact(
                value="must survive compaction only while session is active",
                source_kind=EnclaveSourceKind.USER,
                source_turn_id=TurnId("turn-1"),
            ),
            expected_digest=current.digest,
        )
        clock = MutableClock(1_000.0)
        manager = SessionRetentionManager(
            self.locator,
            retention_seconds=60.0,
            clock=clock,
        )

        receipt = manager.end(self.handle, idempotency_key="end-retention-session")

        paths = self.locator.locate(self.session_id)
        self.assertFalse(paths.enclave.exists())
        with self.assertRaises(EnclaveAuthorityError):
            enclaves.set(
                self.session_id,
                self.actor_id,
                "late-write",
                EnclaveFact(
                    value="must be rejected",
                    source_kind=EnclaveSourceKind.AGENT,
                    source_turn_id=TurnId("turn-after-end"),
                ),
            )
        self.assertFalse(receipt.eligible_for_gc)
        self.assertFalse(manager.collect_expired(self.session_id))
        clock.value = receipt.eligible_at_epoch
        self.assertTrue(manager.collect_expired(self.session_id))
        self.assertFalse(manager.collect_expired(self.session_id))
        with self.assertRaises(SessionNotFound):
            self.kernel.inspect(self.session_id)

    def test_active_session_is_never_a_gc_candidate(self) -> None:
        """Retention 시간이 아무리 지나도 terminal state가 아니면 수거를 거부합니다."""
        clock = MutableClock(10_000.0)
        manager = SessionRetentionManager(
            self.locator,
            retention_seconds=0.0,
            clock=clock,
        )

        with self.assertRaises(ActiveSessionRetentionError):
            manager.collect_expired(self.session_id)
