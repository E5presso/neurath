"""Persistence and authority readback ports required by phase execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from scripts.agent_harness.adaptive_control import (
    CriterionSpec,
    ExecutionStatus,
)
from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityVerification,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlReceipt,
)
from scripts.agent_harness.delegation_evidence import (
    ConsumedDelegationEvidenceSnapshot,
    FinalReviewVerification,
)


from scripts.skill_harness.phase_models import PhaseRunState


@dataclass(frozen=True, slots=True)
class AdaptiveControlPhaseReadback:
    """Current adaptive receipt, external authority, approved goal text를 한 revision에 결속합니다."""

    receipt: AdaptiveControlReceipt
    """Submitted evidence와 exact하게 대조된 current decision입니다."""
    authority: AdaptiveControlAuthorityVerification
    """Runtime-backed external authority read-back입니다."""
    contract_goal: str
    """Receipt가 파생된 persisted GoalContract.goal입니다."""


@dataclass(frozen=True, slots=True)
class AdaptiveControlTransitionReadback:
    """Nonterminal phase transition이 직접 재검증할 current adaptive state입니다."""

    receipt: AdaptiveControlReceipt
    """Persisted namespace에서 방금 계산한 current decision입니다."""
    authority: AdaptiveControlAuthorityVerification
    """같은 workflow revision에서 검증한 external authority입니다."""
    contract_goal: str
    """Decision과 같은 snapshot에 저장된 GoalContract.goal입니다."""
    criteria: tuple[CriterionSpec, ...]
    """AWAIT_USER pending identity를 해석할 immutable current criterion metadata입니다."""
    blocker_gap_ids: tuple[str, ...]
    """Current authority가 입증한 terminal clarification blocker identity입니다."""
    execution_status: ExecutionStatus
    """Current adaptive execution lifecycle의 typed terminal-failure 근거입니다."""


class PhaseRunStore(ABC):
    """PhaseRunner가 persistence topology와 무관하게 사용하는 state port입니다."""

    @abstractmethod
    def read(self) -> PhaseRunState:
        """Current phase projection을 반환합니다.

        Returns:
            PhaseRunner가 다음 transition을 계산할 현재 state입니다.
        """

    @abstractmethod
    def write(self, state: PhaseRunState) -> None:
        """Current command가 계산한 replacement projection을 commit합니다.

        Args:
            state: Initialize, phase advance 또는 terminal transition 결과입니다.
        """

    @abstractmethod
    def read_skill_state(self) -> Mapping[str, object]:
        """같은 workflow의 skill-specific operational state를 반환합니다.

        Returns:
            Phase namespace와 분리된 current skill-state object입니다.
        """

    @abstractmethod
    def verify_adaptive_control_evidence(
        self,
        evidence: Mapping[str, object],
    ) -> AdaptiveControlPhaseReadback:
        """Current workflow receipt와 runtime-backed external authority를 함께 검증합니다.

        Args:
            evidence: Phase가 제출한 canonical adaptive-control JSON receipt입니다.

        Returns:
            Current persisted state에서 재계산한 receipt와 external authority 판정입니다.
        """

    @abstractmethod
    def read_adaptive_control_transition(self) -> AdaptiveControlTransitionReadback:
        """Evidence 재제출 없이 current adaptive phase-transition state를 읽습니다.

        Returns:
            같은 workflow revision에 결속된 decision, authority, criterion metadata입니다.
        """

    @abstractmethod
    def read_review_evidence(
        self,
        expected_kind: str,
        reviewed_head_sha: str,
        *,
        delegation_id: str | None = None,
    ) -> tuple[ConsumedDelegationEvidenceSnapshot, FinalReviewVerification]:
        """Consumed delegation과 canonical review verification을 함께 읽습니다.

        Args:
            expected_kind: 현재 phase가 요구하는 exact delegation kind입니다.
            reviewed_head_sha: Assignment와 artifact가 공유해야 하는 exact commit입니다.

        Returns:
            Digest-verified immutable evidence와 shared policy의 bounded verification입니다.
        """

    @abstractmethod
    def read_consumed_delegation_evidence(
        self,
        expected_kind: str,
        reviewed_head_sha: str,
    ) -> ConsumedDelegationEvidenceSnapshot:
        """Exact workflow의 direct-child consumed delegation report를 읽습니다.

        Args:
            expected_kind: Phase가 요구하는 exact delegation kind입니다.
            reviewed_head_sha: Assignment가 결속한 exact commit입니다.

        Returns:
            Direct-child authority가 발행한 digest-verified snapshot입니다.
        """

    def read_native_wave(self, wave_id: str) -> Mapping[str, object]:
        """Read a workflow-bound native wave; legacy stores cannot certify it."""
        raise ValueError("native wave readback is unavailable")

    def read_provider_wave(self, wave_id: str) -> Mapping[str, object]:
        """Read actual consumed provider results, without granting child authority."""
        raise ValueError("provider wave readback is unavailable")

    @abstractmethod
    def validate_harness_incidents(self, worktree: Path) -> None:
        """Runtime-bound process state의 typed incident lifecycle을 검증합니다.

        Args:
            worktree: Resolution evidence가 결속된 repository root입니다.
        """
