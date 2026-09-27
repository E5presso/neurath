"""Immutable phase contracts and workflow state transitions, independent of execution."""

from __future__ import annotations

import time
from dataclasses import dataclass

VALID_PHASE_STATUSES = ("completed", "skipped", "blocked", "failed")
TERMINAL_PHASE_STATUSES = ("blocked", "failed")


class PhaseRunnerError(Exception):
    """skill contract와 phase runner enforcement invariant 위반을 명시적인 domain error로 전달합니다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PhaseContract:

    id: int
    """id 값을 보관합니다."""
    name: str
    """name 값을 보관합니다."""
    min_evidence_count: int
    """min evidence count 값을 보관합니다."""
    required_evidence: tuple[str, ...]
    """required evidence 값을 보관합니다."""
    phase_file: str | None = None
    """phase file 값을 보관합니다."""
    evidence_patterns: dict[str, str] | None = None
    """evidence patterns 값을 보관합니다."""

    def as_payload(self) -> dict[str, object]:
        """현재 객체 상태를 JSON 직렬화 가능한 dict로 변환합니다.

        Returns:
            as payload 처리 결과입니다."""
        return {
            "id": self.id,
            "name": self.name,
            "min_evidence_count": self.min_evidence_count,
            "required_evidence": list(self.required_evidence),
            "phase_file": self.phase_file,
            "evidence_patterns": self.evidence_patterns or {},
        }


@dataclass(frozen=True, slots=True)
class SkillContract:

    name: str
    """name 값을 보관합니다."""
    terminal_states: tuple[str, ...]
    """terminal states 값을 보관합니다."""
    phases: tuple[PhaseContract, ...]
    """phases 값을 보관합니다."""
    adaptive_control_required: bool = False
    """새 phase run이 cross-skill adaptive control gate를 사용해야 하는지 나타냅니다."""

    def phase(self, phase_id: int) -> PhaseContract:
        for phase in self.phases:
            if phase.id == phase_id:
                return phase
        raise PhaseRunnerError("UNKNOWN_PHASE", f"{self.name} has no phase {phase_id}")

    def first_phase(self) -> PhaseContract:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Returns:
            first phase 처리 결과입니다.

        Raises:
            입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
        if not self.phases:
            raise PhaseRunnerError("CONTRACT_INVALID", f"{self.name} has no phase contracts")
        return self.phases[0]

    def next_phase_after(self, phase_id: int) -> PhaseContract | None:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            phase_id: 호출자가 넘긴 phase id 값입니다.

        Returns:
            next phase after 처리 결과입니다.

        Raises:
            입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
        for index, phase in enumerate(self.phases):
            if phase.id == phase_id:
                next_index = index + 1
                if next_index >= len(self.phases):
                    return None
                return self.phases[next_index]
        raise PhaseRunnerError("UNKNOWN_PHASE", f"{self.name} has no phase {phase_id}")


@dataclass(frozen=True, slots=True)
class PhaseRecord:

    id: int
    """id 값을 보관합니다."""
    name: str
    """name 값을 보관합니다."""
    status: str
    """status 값을 보관합니다."""
    evidence: tuple[str, ...]
    """evidence 값을 보관합니다."""
    summary: str | None
    """summary 값을 보관합니다."""
    reason: str | None
    """reason 값을 보관합니다."""
    completed_at_epoch: float | None = None
    """Phase가 완료된 epoch 시각입니다. 병목 분석용 계측 값입니다."""
    duration_seconds: float | None = None
    """직전 phase 완료(또는 run 시작)부터 이 phase 완료까지의 소요 시간입니다."""

    @classmethod
    def pending(cls, contract: PhaseContract) -> PhaseRecord:
        return cls(
            id=contract.id,
            name=contract.name,
            status="pending",
            evidence=(),
            summary=None,
            reason=None,
        )

    def complete(
        self,
        status: str,
        evidence: tuple[str, ...],
        summary: str,
        reason: str | None,
    ) -> PhaseRecord:
        return PhaseRecord(
            id=self.id,
            name=self.name,
            status=status,
            evidence=evidence,
            summary=summary,
            reason=reason,
            completed_at_epoch=self.completed_at_epoch,
            duration_seconds=self.duration_seconds,
        )

    def with_timing(self, completed_at_epoch: float, duration_seconds: float | None) -> PhaseRecord:
        """완료 시각과 소요 시간을 계측 값으로 기록합니다.

        Args:
            completed_at_epoch: Phase가 완료된 epoch 시각입니다.
            duration_seconds: 직전 완료 지점부터의 소요 시간입니다. 기준 시각이 없으면 None입니다.

        Returns:
            계측 값이 기록된 phase record입니다."""
        return PhaseRecord(
            id=self.id,
            name=self.name,
            status=self.status,
            evidence=self.evidence,
            summary=self.summary,
            reason=self.reason,
            completed_at_epoch=completed_at_epoch,
            duration_seconds=duration_seconds,
        )

    def as_payload(self) -> dict[str, object]:
        """현재 객체 상태를 JSON 직렬화 가능한 dict로 변환합니다.

        Returns:
            as payload 처리 결과입니다."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "evidence": list(self.evidence),
            "summary": self.summary,
            "reason": self.reason,
            "completed_at_epoch": self.completed_at_epoch,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class PhaseRunState:

    skill: str
    """skill 값을 보관합니다."""
    run_id: str
    """run id 값을 보관합니다."""
    north_star: str
    """작업 착수 시 고정한 최초 지시·완료 기준·비목표입니다. 매 phase 조회와 완료
    응답에 다시 노출해, 작업이 길어지거나 context가 압축돼도 목표가 흐려지는 표류를
    막습니다."""
    current_phase_id: int | None
    """current phase id 값을 보관합니다."""
    terminal_state: str | None
    """terminal state 값을 보관합니다."""
    phases: tuple[PhaseRecord, ...]
    """phases 값을 보관합니다."""
    adaptive_control_required: bool = False
    """Init 당시 contract에서 고정한 adaptive control migration boundary입니다."""
    started_at_epoch: float | None = None
    """Run이 초기화된 epoch 시각입니다. 병목 분석용 계측 값입니다."""

    @classmethod
    def initialize(cls, contract: SkillContract, run_id: str, north_star: str) -> PhaseRunState:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            contract: 호출자가 넘긴 contract 값입니다.
            run_id: 호출자가 넘긴 run id 값입니다.
            north_star: 착수 시 고정할 최초 지시·완료 기준·비목표 텍스트입니다.

        Returns:
            initialize 처리 결과입니다.

        Raises:
            PhaseRunnerError: north star가 비어 있으면 발생합니다."""
        if not north_star.strip():
            raise PhaseRunnerError(
                "NORTH_STAR_REQUIRED",
                "north star (intent, acceptance criteria, non-goals) must be non-empty",
            )
        phases = tuple(PhaseRecord.pending(phase) for phase in contract.phases)
        return cls(
            skill=contract.name,
            run_id=run_id,
            north_star=north_star,
            current_phase_id=contract.first_phase().id,
            terminal_state=None,
            phases=phases,
            adaptive_control_required=contract.adaptive_control_required,
            started_at_epoch=time.time(),
        )

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> PhaseRunState:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            payload: 호출자가 넘긴 payload 값입니다.

        Returns:
            from payload 처리 결과입니다.

        Raises:
            입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
        skill = cls._required_str(payload, "skill")
        run_id = cls._required_str(payload, "run_id")
        north_star = cls._required_str(payload, "north_star")
        current_phase_id = cls._optional_int(payload, "current_phase_id")
        terminal_state = cls._optional_str(payload, "terminal_state")
        raw_phases = payload.get("phases")
        if not isinstance(raw_phases, list):
            raise PhaseRunnerError("STATE_INVALID", "phase state must contain a phases list")
        phases = tuple(cls._phase_from_payload(item) for item in raw_phases)
        adaptive_control_required = payload.get("adaptive_control_required", False)
        if not isinstance(adaptive_control_required, bool):
            raise PhaseRunnerError(
                "STATE_INVALID",
                "adaptive_control_required must be a boolean",
            )
        return cls(
            skill=skill,
            run_id=run_id,
            north_star=north_star,
            current_phase_id=current_phase_id,
            terminal_state=terminal_state,
            phases=phases,
            adaptive_control_required=adaptive_control_required,
            started_at_epoch=cls._optional_float(payload, "started_at_epoch"),
        )

    def phase(self, phase_id: int) -> PhaseRecord:
        for phase in self.phases:
            if phase.id == phase_id:
                return phase
        raise PhaseRunnerError("STATE_INVALID", f"state has no phase {phase_id}")

    def with_completed_phase(
        self,
        contract: SkillContract,
        phase_id: int,
        status: str,
        evidence: tuple[str, ...],
        summary: str,
        reason: str | None,
    ) -> PhaseRunState:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            contract: 호출자가 넘긴 contract 값입니다.
            phase_id: 호출자가 넘긴 phase id 값입니다.
            status: 호출자가 넘긴 status 값입니다.
            evidence: 호출자가 넘긴 evidence 값입니다.
            summary: 호출자가 넘긴 summary 값입니다.
            reason: 호출자가 넘긴 reason 값입니다.

        Returns:
            with completed phase 처리 결과입니다."""
        next_phase = None
        if status not in TERMINAL_PHASE_STATUSES:
            next_phase = contract.next_phase_after(phase_id)

        now = time.time()
        completed = (
            self.phase(phase_id)
            .complete(status, evidence, summary, reason)
            .with_timing(now, self._duration_until(now))
        )
        phases = tuple(completed if phase.id == phase_id else phase for phase in self.phases)
        return PhaseRunState(
            skill=self.skill,
            run_id=self.run_id,
            north_star=self.north_star,
            current_phase_id=next_phase.id if next_phase is not None else None,
            terminal_state=self.terminal_state,
            phases=phases,
            adaptive_control_required=self.adaptive_control_required,
            started_at_epoch=self.started_at_epoch,
        )

    def _duration_until(self, now: float) -> float | None:
        """직전 완료 지점(마지막 phase 완료 또는 run 시작)부터의 소요를 계산합니다.

        Args:
            now: 현재 phase가 완료된 epoch 시각입니다.

        Returns:
            기준 시각이 기록돼 있으면 경과 초, 계측 이전 run이면 None입니다."""
        baselines = [
            phase.completed_at_epoch
            for phase in self.phases
            if phase.completed_at_epoch is not None
        ]
        if self.started_at_epoch is not None:
            baselines.append(self.started_at_epoch)
        if not baselines:
            return None
        return max(0.0, now - max(baselines))

    def with_terminal_state(self, terminal_state: str) -> PhaseRunState:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            terminal_state: 호출자가 넘긴 terminal state 값입니다.

        Returns:
            with terminal state 처리 결과입니다."""
        return PhaseRunState(
            skill=self.skill,
            run_id=self.run_id,
            north_star=self.north_star,
            current_phase_id=None,
            terminal_state=terminal_state,
            phases=self.phases,
            adaptive_control_required=self.adaptive_control_required,
            started_at_epoch=self.started_at_epoch,
        )

    def all_executable_phases_complete(self) -> bool:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Returns:
            all executable phases complete 처리 결과입니다."""
        return all(phase.status in {"completed", "skipped"} for phase in self.phases)

    def has_terminal_phase_status(self, terminal_state: str) -> bool:
        """현재 상태로 권한 또는 lifecycle 조건 충족 여부를 판정합니다.

        Args:
            terminal_state: 호출자가 넘긴 terminal state 값입니다.

        Returns:
            조건을 만족하면 True, 아니면 False를 반환합니다."""
        return any(phase.status == terminal_state for phase in self.phases)

    def as_payload(self) -> dict[str, object]:
        """현재 객체 상태를 JSON 직렬화 가능한 dict로 변환합니다.

        Returns:
            as payload 처리 결과입니다."""
        return {
            "schema_version": 1,
            "skill": self.skill,
            "run_id": self.run_id,
            "north_star": self.north_star,
            "current_phase_id": self.current_phase_id,
            "terminal_state": self.terminal_state,
            "phases": [phase.as_payload() for phase in self.phases],
            "adaptive_control_required": self.adaptive_control_required,
            "started_at_epoch": self.started_at_epoch,
        }

    @classmethod
    def _phase_from_payload(cls, payload: object) -> PhaseRecord:
        if not isinstance(payload, dict):
            raise PhaseRunnerError("STATE_INVALID", "each phase state must be an object")
        return PhaseRecord(
            id=cls._required_int(payload, "id"),
            name=cls._required_str(payload, "name"),
            status=cls._required_str(payload, "status"),
            evidence=tuple(cls._string_list(payload.get("evidence"))),
            summary=cls._optional_str(payload, "summary"),
            reason=cls._optional_str(payload, "reason"),
            completed_at_epoch=cls._optional_float(payload, "completed_at_epoch"),
            duration_seconds=cls._optional_float(payload, "duration_seconds"),
        )

    @staticmethod
    def _optional_float(payload: dict[str, object], key: str) -> float | None:
        value = payload.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PhaseRunnerError("STATE_INVALID", f"{key} must be a number or null")
        return float(value)

    @staticmethod
    def _required_int(payload: dict[str, object], key: str) -> int:
        value = payload.get(key)
        if not isinstance(value, int):
            raise PhaseRunnerError("STATE_INVALID", f"{key} must be an integer")
        return value

    @staticmethod
    def _optional_int(payload: dict[str, object], key: str) -> int | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, int):
            raise PhaseRunnerError("STATE_INVALID", f"{key} must be an integer or null")
        return value

    @staticmethod
    def _required_str(payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise PhaseRunnerError("STATE_INVALID", f"{key} must be a non-empty string")
        return value

    @staticmethod
    def _optional_str(payload: dict[str, object], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise PhaseRunnerError("STATE_INVALID", f"{key} must be a non-empty string or null")
        return value

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]
