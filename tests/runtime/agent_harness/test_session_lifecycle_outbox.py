"""Explicit lifecycle transition과 bounded transactional outbox를 검증합니다."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.session_kernel import (
    ActorId,
    EffectAcknowledged,
    EffectId,
    EffectKind,
    OutboxEffect,
    ResumeId,
    SessionCompacted,
    SessionEnded,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionResumed,
    SessionRuntime,
    SessionStarted,
    TransitionRejected,
)


class SessionLifecycleOutboxTest(TestCase):
    """H11과 A15의 crash/retry-safe delivery contract를 검증합니다."""

    def setUp(self) -> None:
        """각 test가 독립 session registry를 사용하게 합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.locator = SessionLocator(Path(self.temporary_directory.name))
        self.kernel = SessionKernel(self.locator)
        self.session_id = SessionId("session-a")
        self.root_actor_id = ActorId("codex:session:session-a")

    def _effect(self, suffix: str, kind: EffectKind) -> OutboxEffect:
        """Deterministic lifecycle delivery effect를 만듭니다."""
        return OutboxEffect(
            effect_id=EffectId(f"effect-{suffix}"),
            actor_id=self.root_actor_id,
            kind=kind,
            delivery_key=f"delivery-{suffix}",
            payload={"cause": suffix},
        )

    def _start(self, effect: OutboxEffect | None = None) -> None:
        """Optional startup delivery와 함께 exact session을 초기화합니다."""
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume-start"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.root_actor_id,
                idempotency_key="lifecycle-start",
                effect=effect,
            )
        )

    def _acknowledge(self, effect: OutboxEffect, suffix: str) -> None:
        """Runtime adapter가 effect를 실행한 뒤 exact pending effect를 ACK합니다."""
        self.kernel.apply(
            EffectAcknowledged(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                effect_id=effect.id,
                idempotency_key=f"ack-{suffix}",
            )
        )

    def test_startup_effect_is_pending_once_and_retry_does_not_duplicate_it(self) -> None:
        """동일 startup lifecycle retry는 outbox effect를 중복하지 않습니다."""
        effect = self._effect("startup", EffectKind.CONTEXT_INJECTION)
        event = SessionStarted(
            session_id=self.session_id,
            resume_id=ResumeId("resume-start"),
            runtime=SessionRuntime.CODEX,
            root_actor_id=self.root_actor_id,
            idempotency_key="lifecycle-start",
            effect=effect,
        )

        first = self.kernel.apply(event)
        second = self.kernel.apply(event)

        self.assertTrue(first.outbox[effect.id].same_snapshot(second.outbox[effect.id]))
        self.assertEqual({effect.id}, set(second.outbox))
        self.assertEqual(first.revision, second.revision)

    def test_ack_removes_pending_effect_and_same_lifecycle_retry_does_not_recreate_it(self) -> None:
        """ACK history를 누적하지 않으면서 같은 lifecycle retry는 effect를 되살리지 않습니다."""
        effect = self._effect("startup", EffectKind.CONTEXT_INJECTION)
        self._start(effect)
        self._acknowledge(effect, "startup")

        after_ack = self.kernel.inspect(self.session_id)
        after_retry = self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume-start"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.root_actor_id,
                idempotency_key="lifecycle-start",
                effect=effect,
            )
        )

        self.assertEqual({}, after_ack.outbox)
        self.assertEqual({}, after_retry.outbox)
        self.assertEqual(after_ack.revision, after_retry.revision)

    def test_resume_updates_opaque_handle_and_commits_delivery_before_ack(self) -> None:
        """Resume은 explicit transition이며 matching effect를 같은 snapshot에 기록합니다."""
        self._start()
        effect = self._effect("resume", EffectKind.CONTEXT_INJECTION)

        resumed = self.kernel.apply(
            SessionResumed(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                resume_id=ResumeId("resume-next"),
                lifecycle_provenance_id="vendor-resume-event-1",
                idempotency_key="lifecycle-resume-1",
                effect=effect,
            )
        )

        self.assertEqual(ResumeId("resume-next"), resumed.session.resume_id)
        self.assertEqual("lifecycle-resume-1", resumed.session.last_lifecycle_idempotency_key)
        self.assertEqual(effect, resumed.outbox[effect.id])

    def test_compact_retry_after_ack_is_idempotent_and_outbox_remains_bounded(self) -> None:
        """A15: same compact event의 retry는 ACK된 delivery history를 재누적하지 않습니다."""
        self._start()
        effect = self._effect("compact", EffectKind.CONTEXT_INJECTION)
        compact = SessionCompacted(
            session_id=self.session_id,
            actor_id=self.root_actor_id,
            lifecycle_provenance_id="vendor-compact-event-1",
            idempotency_key="lifecycle-compact-1",
            effect=effect,
        )

        first = self.kernel.apply(compact)
        self._acknowledge(effect, "compact")
        second = self.kernel.apply(compact)

        self.assertIn(effect.id, first.outbox)
        self.assertEqual({}, second.outbox)

    def test_wrong_actor_cannot_resume_compact_or_ack_root_delivery(self) -> None:
        """Lifecycle/outbox authority를 session identity와 혼동하지 않습니다."""
        self._start()
        effect = self._effect("compact", EffectKind.CONTEXT_INJECTION)
        wrong_actor = ActorId("codex:not-root")
        wrong_effect = OutboxEffect(
            effect_id=EffectId("effect-wrong-actor"),
            actor_id=wrong_actor,
            kind=EffectKind.CONTEXT_INJECTION,
            delivery_key="delivery-wrong-actor",
            payload={"cause": "compact"},
        )
        compact = SessionCompacted(
            session_id=self.session_id,
            actor_id=wrong_actor,
            lifecycle_provenance_id="vendor-compact-event-1",
            idempotency_key="lifecycle-compact-1",
            effect=wrong_effect,
        )

        with self.assertRaisesRegex(TransitionRejected, "root actor"):
            self.kernel.apply(compact)

        self.kernel.apply(
            SessionCompacted(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                lifecycle_provenance_id="vendor-compact-event-1",
                idempotency_key="lifecycle-compact-1",
                effect=effect,
            )
        )
        with self.assertRaisesRegex(TransitionRejected, "effect actor"):
            self.kernel.apply(
                EffectAcknowledged(
                    session_id=self.session_id,
                    actor_id=ActorId("codex:not-root"),
                    effect_id=effect.id,
                    idempotency_key="ack-wrong-actor",
                )
            )

    def test_terminal_session_rejects_resume_and_compact(self) -> None:
        """A13: ended session은 lifecycle rehydration effect를 새로 만들지 않습니다."""
        self._start()
        self.kernel.apply(
            SessionEnded(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                idempotency_key="lifecycle-end",
            )
        )
        for event in (
            SessionResumed(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                resume_id=ResumeId("resume-after-end"),
                lifecycle_provenance_id="resume-after-end",
                idempotency_key="lifecycle-resume-after-end",
                effect=self._effect("resume-after-end", EffectKind.CONTEXT_INJECTION),
            ),
            SessionCompacted(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                lifecycle_provenance_id="compact-after-end",
                idempotency_key="lifecycle-compact-after-end",
                effect=self._effect("compact-after-end", EffectKind.CONTEXT_INJECTION),
            ),
        ):
            with (
                self.subTest(event=type(event).__name__),
                self.assertRaisesRegex(TransitionRejected, "terminal session"),
            ):
                self.kernel.apply(event)
