"""독립 평가 루프를 exact workflow의 optimistic skill state로 강제합니다."""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TextIO

from scripts.agent_harness.session_kernel import (
    SessionKernelError,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.skill_state_store import SkillStateSnapshot, SkillStateStore
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)

VERDICTS = frozenset({"accept", "reject", "defer"})
OUTCOMES = frozenset({"findings-clear", "approach-change-required"})
LOOP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
ROOT_CAUSE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
FINDING_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EVALUATE_HARNESS_MAX_WALL_CLOCK_SECONDS = 90 * 60


class EvaluationLoopError(ValueError):
    """평가 루프 기록 또는 command가 domain contract를 위반했습니다."""


class Finding:
    """평가자가 낸 지적 하나와 그에 대한 immutable 심판 판정입니다."""

    __slots__ = ("finding_id", "reason", "root_cause", "verdict")

    def __init__(
        self,
        finding_id: str,
        root_cause: str,
        verdict: str,
        reason: str,
    ) -> None:
        """지적과 판정을 검증해 고정합니다.

        Args:
            finding_id: 평가자가 붙인 지적 식별자입니다.
            root_cause: 지적의 근본 원인 분류입니다.
            verdict: 심판 판정입니다.
            reason: 판정 사유입니다.

        Raises:
            EvaluationLoopError: 형식이 올바르지 않으면 발생합니다.
        """
        if not FINDING_PATTERN.fullmatch(finding_id):
            raise EvaluationLoopError(f"finding id 형식이 올바르지 않습니다: {finding_id}")
        if not ROOT_CAUSE_PATTERN.fullmatch(root_cause):
            raise EvaluationLoopError(f"근본 원인 분류 형식이 올바르지 않습니다: {root_cause}")
        if verdict not in VERDICTS:
            raise EvaluationLoopError(
                f"심판 판정은 {sorted(VERDICTS)} 중 하나여야 합니다: {verdict}"
            )
        if not reason.strip():
            raise EvaluationLoopError(f"판정 사유가 비어 있습니다: {finding_id}")
        object.__setattr__(self, "finding_id", finding_id)
        object.__setattr__(self, "root_cause", root_cause)
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "reason", reason.strip())

    finding_id: str
    """평가자가 부여한 회차 내 finding identity입니다."""

    root_cause: str
    """반복 여부를 판정할 근본 원인 분류입니다."""

    verdict: str
    """`accept`, `reject`, `defer` 중 하나인 심판 판정입니다."""

    reason: str
    """심판이 해당 판정을 내린 비어 있지 않은 근거입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 finding의 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Finding은 생성 뒤 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")

    @classmethod
    def parse(cls, spec: str) -> Finding:
        """`finding:root-cause:verdict:reason` 형식을 Finding으로 만듭니다.

        Args:
            spec: 콜론으로 구분한 지적 명세입니다.

        Returns:
            해석한 immutable Finding입니다.

        Raises:
            EvaluationLoopError: 필드가 모자라거나 값이 invalid하면 발생합니다.
        """
        parts = spec.split(":", 3)
        if len(parts) != 4:
            raise EvaluationLoopError(
                "지적은 finding:root-cause:verdict:reason 형식이어야 합니다: " + spec
            )
        return cls(parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3])

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Finding:
        """Persisted JSON object를 Finding으로 검증합니다.

        Args:
            payload: Workflow skill state에서 읽은 finding object입니다.

        Returns:
            검증된 immutable Finding입니다.

        Raises:
            EvaluationLoopError: Required string field가 없으면 발생합니다.
        """
        values: list[str] = []
        for key in ("finding_id", "root_cause", "verdict", "reason"):
            value = payload.get(key)
            if not isinstance(value, str):
                raise EvaluationLoopError(f"finding {key}는 string이어야 합니다")
            values.append(value)
        return cls(values[0], values[1], values[2], values[3])

    def to_payload(self) -> dict[str, str]:
        """Workflow skill state에 저장할 JSON object를 반환합니다.

        Returns:
            Finding의 모든 판정 field를 포함한 새 object입니다.
        """
        return {
            "finding_id": self.finding_id,
            "root_cause": self.root_cause,
            "verdict": self.verdict,
            "reason": self.reason,
        }


class EvaluationTimestamp:
    """Optimistic operation 전에 한 번 캡처한 timestamp value입니다."""

    __slots__ = ("value",)

    def __init__(self, value: str, label: str) -> None:
        """비어 있지 않은 timestamp를 immutable value로 고정합니다.

        Args:
            value: Operation 전체 retry에서 재사용할 timestamp입니다.
            label: Invalid input을 설명할 timestamp field 이름입니다.

        Raises:
            EvaluationLoopError: Timestamp가 비어 있으면 발생합니다.
        """
        if not value.strip():
            raise EvaluationLoopError(f"{label} timestamp가 비어 있습니다")
        object.__setattr__(self, "value", value)

    value: str
    """한 optimistic operation의 모든 retry가 공유하는 timestamp입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 timestamp의 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Timestamp는 생성 뒤 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class EvaluationLoop:
    """완료 조건, 회차, 심판 판정을 함께 보관하는 local domain aggregate입니다."""

    __slots__ = ("_payload",)

    def __init__(self, payload: Mapping[str, object]) -> None:
        """JSON-compatible payload의 private working copy를 만듭니다.

        Args:
            payload: 새 aggregate가 독립적으로 소유할 루프 기록입니다.

        Raises:
            EvaluationLoopError: Payload가 JSON object가 아니면 발생합니다.
        """
        self._payload = self._copy_payload(payload)

    @property
    def payload(self) -> dict[str, object]:
        """호출자가 내부 aggregate를 변경할 수 없는 payload copy를 반환합니다.

        Returns:
            JSON-compatible evaluation loop object입니다.
        """
        return self.to_payload()

    @property
    def loop_id(self) -> str:
        """Aggregate의 stable loop identity를 반환합니다.

        Returns:
            Workflow-local evaluation loop key입니다.
        """
        return self._required_text("loop_id")

    @classmethod
    def open(
        cls,
        loop_id: str,
        goal: str,
        acceptance: tuple[str, ...],
        opened_at: str,
    ) -> EvaluationLoop:
        """완료 조건과 외부에서 캡처한 timestamp로 새 루프를 만듭니다.

        Args:
            loop_id: 루프 식별자입니다.
            goal: 이 루프가 무엇을 판정하는지입니다.
            acceptance: 발행 가능 판정을 내릴 완료 조건입니다.
            opened_at: Optimistic transform 밖에서 한 번 캡처한 timestamp입니다.

        Returns:
            새로 만든 local aggregate입니다.

        Raises:
            EvaluationLoopError: 식별자, 목표, 완료 조건, timestamp가 invalid하면
                발생합니다.
        """
        if not LOOP_ID_PATTERN.fullmatch(loop_id):
            raise EvaluationLoopError(f"loop id 형식이 올바르지 않습니다: {loop_id}")
        if not goal.strip():
            raise EvaluationLoopError("루프 목표가 비어 있습니다")
        cleaned = tuple(item.strip() for item in acceptance if item.strip())
        if len(cleaned) < 2:
            raise EvaluationLoopError("완료 조건은 최소 두 개를 루프 시작 전에 적어야 합니다")
        timestamp = EvaluationTimestamp(opened_at, "opened_at")
        return cls({
            "loop_id": loop_id,
            "goal": goal.strip(),
            "acceptance": list(cleaned),
            "opened_at": timestamp.value,
            "rounds": [],
            "outcome": None,
            "summary": None,
        })

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> EvaluationLoop:
        """Workflow skill state의 object를 검증된 aggregate로 복원합니다.

        Args:
            payload: `skill_state.evaluation_loops` 아래 저장된 loop object입니다.

        Returns:
            Persisted object와 중첩 collection을 공유하지 않는 aggregate입니다.

        Raises:
            EvaluationLoopError: Persisted domain shape가 invalid하면 발생합니다.
        """
        loop = cls(payload)
        loop._validate()
        return loop

    @property
    def rounds(self) -> list[dict[str, object]]:
        """Aggregate가 소유한 회차 working list를 반환합니다.

        Returns:
            회차 기록 목록입니다.

        Raises:
            EvaluationLoopError: 기록이 list가 아니면 발생합니다.
        """
        rounds = self._payload.get("rounds")
        if not isinstance(rounds, list):
            raise EvaluationLoopError("회차 목록이 깨졌습니다")
        if any(not isinstance(entry, dict) for entry in rounds):
            raise EvaluationLoopError("회차 기록은 object여야 합니다")
        return rounds

    @property
    def is_closed(self) -> bool:
        """루프가 terminal outcome을 가졌는지 반환합니다.

        Returns:
            닫혔으면 참입니다.
        """
        return self._payload.get("outcome") is not None

    def recurring_root_causes(self) -> tuple[str, ...]:
        """두 회차 이상에서 채택된 근본 원인을 반환합니다.

        Returns:
            반복된 근본 원인 분류입니다.
        """
        seen: dict[str, set[int]] = {}
        for entry in self.rounds:
            number = self._round_number(entry)
            for finding in self._round_findings(entry):
                if finding.verdict != "accept":
                    continue
                seen.setdefault(finding.root_cause, set()).add(number)
        return tuple(sorted(key for key, value in seen.items() if len(value) > 1))

    def recurrence_warnings(self) -> tuple[str, ...]:
        """반복된 근본 원인에 대한 agent 판단 경고를 반환합니다.

        Returns:
            반복이 있으면 경고 한 줄, 없으면 빈 tuple입니다.
        """
        recurring = self.recurring_root_causes()
        if not recurring:
            return ()
        return (
            "warning: 같은 근본 원인이 두 회차 이상에서 채택됐습니다. 개별 수정이 원인을 "
            "없애는지 다시 보고, 접근을 바꿀지 근거와 함께 판단하세요: " + ", ".join(recurring),
        )

    def record_round(
        self,
        number: int,
        findings: tuple[Finding, ...],
        recorded_at: str,
    ) -> tuple[str, ...]:
        """외부 timestamp를 사용해 회차 하나의 지적과 판정을 기록합니다.

        Args:
            number: 회차 번호입니다.
            findings: 그 회차의 지적과 판정입니다.
            recorded_at: Optimistic transform 밖에서 한 번 캡처한 timestamp입니다.

        Returns:
            근본 원인 반복에 대한 경고 목록입니다.

        Raises:
            EvaluationLoopError: 루프가 닫혔거나 회차 번호 또는 timestamp가 invalid하면
                발생합니다.
        """
        if self.is_closed:
            raise EvaluationLoopError("닫힌 루프에는 회차를 더할 수 없습니다")
        expected = len(self.rounds) + 1
        if number != expected:
            raise EvaluationLoopError(f"회차 번호는 {expected}이어야 합니다: {number}")
        timestamp = EvaluationTimestamp(recorded_at, "recorded_at")
        self.rounds.append({
            "number": number,
            "recorded_at": timestamp.value,
            "findings": [finding.to_payload() for finding in findings],
        })
        return self.recurrence_warnings()

    def close(
        self,
        outcome: str,
        summary: str,
        closed_at: str,
    ) -> tuple[str, ...]:
        """외부 timestamp를 사용해 finding 종료 또는 접근 변경 outcome으로 닫습니다.

        Args:
            outcome: `findings-clear` 또는 `approach-change-required`입니다.
            summary: 닫는 근거입니다.
            closed_at: Optimistic transform 밖에서 한 번 캡처한 timestamp입니다.

        Returns:
            근본 원인 반복에 대한 경고 목록입니다.

        Raises:
            EvaluationLoopError: Finding 종료 조건 또는 lifecycle invariant를 위반하면 발생합니다.
        """
        if self.is_closed:
            raise EvaluationLoopError("이미 닫힌 루프입니다")
        if outcome not in OUTCOMES:
            raise EvaluationLoopError(f"outcome은 {sorted(OUTCOMES)} 중 하나여야 합니다: {outcome}")
        if not summary.strip():
            raise EvaluationLoopError("닫는 근거가 비어 있습니다")
        if not self.rounds:
            raise EvaluationLoopError("회차 없이 루프를 닫을 수 없습니다")
        if outcome == "findings-clear":
            accepted = tuple(
                finding
                for finding in self._round_findings(self.rounds[-1])
                if finding.verdict == "accept"
            )
            if accepted:
                raise EvaluationLoopError(
                    "마지막 회차에 채택된 지적이 남아 있으면 수렴이 아닙니다: "
                    + ", ".join(finding.finding_id for finding in accepted)
                )
        timestamp = EvaluationTimestamp(closed_at, "closed_at")
        self._payload["outcome"] = outcome
        self._payload["summary"] = summary.strip()
        self._payload["closed_at"] = timestamp.value
        return self.recurrence_warnings()

    def receipt(self) -> str:
        """닫힌 루프의 phase evidence receipt를 반환합니다.

        Returns:
            Outcome, 회차, verdict count, 반복 원인을 포함한 receipt입니다.

        Raises:
            EvaluationLoopError: 루프가 닫히지 않았으면 발생합니다.
        """
        if not self.is_closed:
            raise EvaluationLoopError("닫히지 않은 루프는 receipt를 낼 수 없습니다")
        accepted = 0
        rejected = 0
        deferred = 0
        for entry in self.rounds:
            for finding in self._round_findings(entry):
                if finding.verdict == "accept":
                    accepted += 1
                elif finding.verdict == "reject":
                    rejected += 1
                else:
                    deferred += 1
        recurring = self.recurring_root_causes()
        acceptance = self._acceptance()
        return (
            f"evaluation_loop_receipt: loop_id={self.loop_id} "
            f"outcome={self._payload['outcome']} rounds={len(self.rounds)} "
            f"accepted={accepted} rejected={rejected} "
            f"deferred={deferred} acceptance_count={len(acceptance)} "
            f"recurring={','.join(recurring) if recurring else 'none'}"
        )

    def to_payload(self) -> dict[str, object]:
        """Workflow skill state에 저장할 deep JSON copy를 반환합니다.

        Returns:
            다른 retry invocation과 nested object를 공유하지 않는 loop payload입니다.
        """
        return self._copy_payload(self._payload)

    def _validate(self) -> None:
        loop_id = self.loop_id
        if not LOOP_ID_PATTERN.fullmatch(loop_id):
            raise EvaluationLoopError(f"loop id 형식이 올바르지 않습니다: {loop_id}")
        if not self._required_text("goal").strip():
            raise EvaluationLoopError("루프 목표가 비어 있습니다")
        if len(self._acceptance()) < 2:
            raise EvaluationLoopError("완료 조건은 최소 두 개여야 합니다")
        EvaluationTimestamp(self._required_text("opened_at"), "opened_at")
        for expected, entry in enumerate(self.rounds, start=1):
            if self._round_number(entry) != expected:
                raise EvaluationLoopError("persisted 회차 번호가 연속적이지 않습니다")
            EvaluationTimestamp(self._entry_text(entry, "recorded_at"), "recorded_at")
            self._round_findings(entry)
        outcome = self._payload.get("outcome")
        if outcome is None:
            if self._payload.get("summary") is not None or "closed_at" in self._payload:
                raise EvaluationLoopError("열린 루프에 terminal metadata가 있습니다")
            return
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            raise EvaluationLoopError("persisted outcome이 올바르지 않습니다")
        if not self._required_text("summary").strip():
            raise EvaluationLoopError("닫는 근거가 비어 있습니다")
        EvaluationTimestamp(self._required_text("closed_at"), "closed_at")

    def _acceptance(self) -> tuple[str, ...]:
        value = self._payload.get("acceptance")
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise EvaluationLoopError("완료 조건 목록이 깨졌습니다")
        return tuple(item.strip() for item in value)

    def _required_text(self, key: str) -> str:
        value = self._payload.get(key)
        if not isinstance(value, str):
            raise EvaluationLoopError(f"loop {key}는 string이어야 합니다")
        return value

    def _round_number(self, entry: Mapping[str, object]) -> int:
        number = entry.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise EvaluationLoopError("회차 번호는 양의 정수여야 합니다")
        return number

    def _round_findings(self, entry: Mapping[str, object]) -> tuple[Finding, ...]:
        raw_findings = entry.get("findings")
        if not isinstance(raw_findings, list):
            raise EvaluationLoopError("회차 findings는 list여야 합니다")
        findings: list[Finding] = []
        for raw_finding in raw_findings:
            if not isinstance(raw_finding, Mapping):
                raise EvaluationLoopError("persisted finding은 object여야 합니다")
            findings.append(Finding.from_payload(raw_finding))
        return tuple(findings)

    def _entry_text(self, entry: Mapping[str, object], key: str) -> str:
        value = entry.get(key)
        if not isinstance(value, str):
            raise EvaluationLoopError(f"round {key}는 string이어야 합니다")
        return value

    def _copy_payload(self, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            encoded = json.dumps(
                dict(payload),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            decoded: object = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise EvaluationLoopError(
                "evaluation loop payload는 JSON-compatible해야 합니다"
            ) from error
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise EvaluationLoopError("evaluation loop payload는 string-keyed object여야 합니다")
        return {str(key): value for key, value in decoded.items()}


class EvaluationLoopCatalog:
    """한 workflow의 evaluation loop namespace를 local copy로 편집합니다."""

    _NAMESPACE = "evaluation_loops"

    def __init__(self, skill_state: Mapping[str, object]) -> None:
        """Current skill state와 모든 persisted loop를 검증해 복사합니다.

        Args:
            skill_state: SkillStateStore transform이 전달한 read-only current object입니다.

        Raises:
            EvaluationLoopError: Namespace 또는 loop payload가 invalid하면 발생합니다.
        """
        self._skill_state = dict(skill_state)
        raw_loops = skill_state.get(self._NAMESPACE, {})
        if not isinstance(raw_loops, Mapping):
            raise EvaluationLoopError("skill_state.evaluation_loops는 object여야 합니다")
        loops: dict[str, dict[str, object]] = {}
        for loop_id, raw_loop in raw_loops.items():
            if not isinstance(loop_id, str) or not isinstance(raw_loop, Mapping):
                raise EvaluationLoopError("evaluation loop entry는 string-keyed object여야 합니다")
            loop = EvaluationLoop.from_payload(raw_loop)
            if loop.loop_id != loop_id:
                raise EvaluationLoopError(
                    f"evaluation loop key와 payload identity가 다릅니다: {loop_id}"
                )
            loops[loop_id] = loop.to_payload()
        self._loops = loops

    def add(self, loop: EvaluationLoop) -> None:
        """새 loop를 catalog에 추가합니다.

        Args:
            loop: 아직 같은 ID가 없어야 하는 새 aggregate입니다.

        Raises:
            EvaluationLoopError: 같은 workflow에 loop ID가 이미 있으면 발생합니다.
        """
        if loop.loop_id in self._loops:
            raise EvaluationLoopError(f"evaluation loop가 이미 있습니다: {loop.loop_id}")
        self._loops[loop.loop_id] = loop.to_payload()

    def require(self, loop_id: str) -> EvaluationLoop:
        """Exact loop ID의 aggregate copy를 반환합니다.

        Args:
            loop_id: 같은 workflow 안에서 찾을 loop identity입니다.

        Returns:
            Catalog storage와 nested object를 공유하지 않는 aggregate입니다.

        Raises:
            EvaluationLoopError: Exact loop가 없으면 발생합니다.
        """
        payload = self._loops.get(loop_id)
        if payload is None:
            raise EvaluationLoopError(f"evaluation loop가 없습니다: {loop_id}")
        return EvaluationLoop.from_payload(payload)

    def replace(self, loop: EvaluationLoop) -> None:
        """Existing exact loop를 새 aggregate payload로 교체합니다.

        Args:
            loop: 같은 ID의 current aggregate에서 계산한 replacement입니다.

        Raises:
            EvaluationLoopError: Exact loop가 없으면 발생합니다.
        """
        if loop.loop_id not in self._loops:
            raise EvaluationLoopError(f"evaluation loop가 없습니다: {loop.loop_id}")
        self._loops[loop.loop_id] = loop.to_payload()

    def to_skill_state(self) -> Mapping[str, object]:
        """Sibling state와 모든 loop를 보존한 replacement object를 반환합니다.

        Returns:
            SkillStateStore가 commit할 전체 skill state입니다.
        """
        return {**self._skill_state, self._NAMESPACE: dict(self._loops)}


class OpenEvaluationLoopMutation:
    """새 evaluation loop를 pure optimistic transform으로 추가합니다."""

    def __init__(self, loop: EvaluationLoop) -> None:
        """Retry마다 재사용할 immutable loop payload를 고정합니다.

        Args:
            loop: Transform 밖에서 timestamp까지 완성한 새 loop입니다.
        """
        self._payload = loop.to_payload()

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current catalog copy에 새 loop를 추가한 replacement를 반환합니다.

        Args:
            current: Latest workflow skill state입니다.

        Returns:
            Current object를 변경하지 않은 새 skill state입니다.
        """
        catalog = EvaluationLoopCatalog(current)
        catalog.add(EvaluationLoop.from_payload(self._payload))
        return catalog.to_skill_state()


class RecordEvaluationRoundMutation:
    """한 loop의 다음 회차를 pure optimistic transform으로 기록합니다."""

    def __init__(
        self,
        loop_id: str,
        number: int,
        findings: tuple[Finding, ...],
        recorded_at: str,
    ) -> None:
        """Retry 동안 바뀌지 않을 round 입력을 고정합니다.

        Args:
            loop_id: 갱신할 exact loop identity입니다.
            number: 기대하는 다음 회차 번호입니다.
            findings: Immutable finding tuple입니다.
            recorded_at: Transform 밖에서 한 번 캡처한 timestamp입니다.
        """
        self._loop_id = loop_id
        self._number = number
        self._findings = findings
        self._recorded_at = recorded_at

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Latest exact loop에 round를 적용한 replacement를 반환합니다.

        Args:
            current: Latest workflow skill state입니다.

        Returns:
            Current object를 변경하지 않은 새 skill state입니다.
        """
        catalog = EvaluationLoopCatalog(current)
        loop = catalog.require(self._loop_id)
        loop.record_round(self._number, self._findings, self._recorded_at)
        catalog.replace(loop)
        return catalog.to_skill_state()


class CloseEvaluationLoopMutation:
    """한 loop의 terminal outcome을 pure optimistic transform으로 기록합니다."""

    def __init__(
        self,
        loop_id: str,
        outcome: str,
        summary: str,
        closed_at: str,
    ) -> None:
        """Retry 동안 바뀌지 않을 close 입력을 고정합니다.

        Args:
            loop_id: 닫을 exact loop identity입니다.
            outcome: 수렴 또는 접근 변경 판정입니다.
            summary: Terminal 판정 근거입니다.
            closed_at: Transform 밖에서 한 번 캡처한 timestamp입니다.
        """
        self._loop_id = loop_id
        self._outcome = outcome
        self._summary = summary
        self._closed_at = closed_at

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Latest exact loop를 닫은 replacement를 반환합니다.

        Args:
            current: Latest workflow skill state입니다.

        Returns:
            Current object를 변경하지 않은 새 skill state입니다.
        """
        catalog = EvaluationLoopCatalog(current)
        loop = catalog.require(self._loop_id)
        loop.close(self._outcome, self._summary, self._closed_at)
        catalog.replace(loop)
        return catalog.to_skill_state()


class EvaluationLoopStore:
    """SkillStateStore 위에서 workflow-local evaluation loop collection을 제공합니다."""

    def __init__(self, skill_state: SkillStateStore) -> None:
        """Runtime-bound optimistic store에 evaluation namespace를 결속합니다.

        Args:
            skill_state: StateHandle과 exact WorkflowId에 이미 고정된 store입니다.
        """
        self._skill_state = skill_state

    def create(self, loop: EvaluationLoop) -> EvaluationLoop:
        """새 loop를 optimistic하게 추가합니다.

        Args:
            loop: 외부 timestamp까지 완성된 새 aggregate입니다.

        Returns:
            Commit된 exact loop aggregate입니다.
        """
        snapshot = self._skill_state.update(OpenEvaluationLoopMutation(loop))
        return self._loop(snapshot, loop.loop_id)

    def record_round(
        self,
        loop_id: str,
        number: int,
        findings: tuple[Finding, ...],
        recorded_at: str,
    ) -> EvaluationLoop:
        """Exact loop의 다음 round를 optimistic하게 기록합니다.

        Args:
            loop_id: 갱신할 workflow-local loop identity입니다.
            number: 기대하는 다음 회차 번호입니다.
            findings: Immutable finding tuple입니다.
            recorded_at: Transform 밖에서 캡처한 timestamp입니다.

        Returns:
            Commit된 exact loop aggregate입니다.
        """
        snapshot = self._skill_state.update(
            RecordEvaluationRoundMutation(loop_id, number, findings, recorded_at)
        )
        return self._loop(snapshot, loop_id)

    def close(
        self,
        loop_id: str,
        outcome: str,
        summary: str,
        closed_at: str,
    ) -> EvaluationLoop:
        """Exact loop를 optimistic하게 닫습니다.

        Args:
            loop_id: 닫을 workflow-local loop identity입니다.
            outcome: 수렴 또는 접근 변경 판정입니다.
            summary: Terminal 판정 근거입니다.
            closed_at: Transform 밖에서 캡처한 timestamp입니다.

        Returns:
            Commit된 exact loop aggregate입니다.
        """
        snapshot = self._skill_state.update(
            CloseEvaluationLoopMutation(loop_id, outcome, summary, closed_at)
        )
        return self._loop(snapshot, loop_id)

    def read(self, loop_id: str) -> EvaluationLoop:
        """Exact workflow의 exact evaluation loop를 읽습니다.

        Args:
            loop_id: 읽을 workflow-local loop identity입니다.

        Returns:
            Persisted state와 nested object를 공유하지 않는 aggregate입니다.
        """
        return self._loop(self._skill_state.read(), loop_id)

    def _loop(self, snapshot: SkillStateSnapshot, loop_id: str) -> EvaluationLoop:
        return EvaluationLoopCatalog(snapshot.skill_state).require(loop_id)


class EvaluationLoopClock:
    """Optimistic transform 밖에서 UTC timestamp를 공급합니다."""

    def now(self) -> str:
        """현재 UTC timestamp를 ISO 문자열로 반환합니다.

        Returns:
            한 operation 전체 retry에서 재사용할 timestamp입니다.
        """
        return datetime.now(UTC).isoformat()


class EvaluationCommand(StrEnum):
    """Evaluation CLI가 허용하는 closed operation 집합입니다."""

    OPEN = "open"
    """완료 조건을 고정한 새 loop를 생성합니다."""

    ROUND = "round"
    """Exact loop에 다음 평가 회차를 기록합니다."""

    CLOSE = "close"
    """Exact loop를 terminal outcome으로 닫습니다."""

    RECEIPT = "receipt"
    """닫힌 exact loop의 evidence receipt를 출력합니다."""


class EvaluationLoopApplication:
    """Runtime session과 workflow identity에서만 evaluation state를 선택합니다."""

    def __init__(self, clock: EvaluationLoopClock | None = None) -> None:
        """Operation timestamp provider를 주입합니다.

        Args:
            clock: 기본 UTC clock을 대체할 deterministic provider입니다.
        """
        self._clock = EvaluationLoopClock() if clock is None else clock

    def run(
        self,
        arguments: Sequence[str] | None,
        environment: Mapping[str, object],
        cwd: Path,
        stream: TextIO,
    ) -> int:
        """한 evaluation command를 exact existing session workflow에 적용합니다.

        Args:
            arguments: Manual file selector가 없는 CLI arguments입니다.
            environment: Vendor runtime이 소유한 exact session/actor identity입니다.
            cwd: SessionLocator를 결정할 current Git worktree입니다.
            stream: Human-readable command result를 쓸 output stream입니다.

        Returns:
            성공이면 0, domain 또는 state contract 위반이면 1입니다.
        """
        namespace = self._parser().parse_args(None if arguments is None else tuple(arguments))
        try:
            locator = SessionLocator.from_worktree(cwd)
            binding = RuntimeEnvironmentResolver().resolve(environment)
            handle = StateHandle.attach(locator, binding)
            workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
            loops = EvaluationLoopStore(SkillStateStore(handle, workflow_id))
            return self._dispatch(namespace, loops, stream)
        except (
            EvaluationLoopError,
            RuntimeIdentityError,
            SessionKernelError,
            subprocess.CalledProcessError,
        ) as error:
            print(f"evaluation loop error: {error}", file=stream)
            return 1

    def _dispatch(
        self,
        namespace: argparse.Namespace,
        loops: EvaluationLoopStore,
        stream: TextIO,
    ) -> int:
        operation = getattr(namespace, "operation", None)
        loop_id = self._text(namespace, "loop_id")
        if operation is EvaluationCommand.OPEN:
            acceptance = self._string_sequence(namespace, "acceptance")
            loop = EvaluationLoop.open(
                loop_id,
                self._text(namespace, "goal"),
                acceptance,
                self._clock.now(),
            )
            loops.create(loop)
            print(f"opened {loop_id} acceptance={len(acceptance)}", file=stream)
            return 0
        if operation is EvaluationCommand.ROUND:
            findings = tuple(
                Finding.parse(spec) for spec in self._string_sequence(namespace, "findings")
            )
            number = self._integer(namespace, "number")
            loop = loops.record_round(loop_id, number, findings, self._clock.now())
            self._print_warnings(loop, stream)
            print(f"round {number} findings={len(findings)}", file=stream)
            return 0
        if operation is EvaluationCommand.CLOSE:
            loop = loops.close(
                loop_id,
                self._text(namespace, "outcome"),
                self._text(namespace, "summary"),
                self._clock.now(),
            )
            self._print_warnings(loop, stream)
            print(f"closed {self._text(namespace, 'outcome')}", file=stream)
            return 0
        if operation is EvaluationCommand.RECEIPT:
            print(loops.read(loop_id).receipt(), file=stream)
            return 0
        raise EvaluationLoopError("evaluation command가 필요합니다")

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="독립 평가 루프를 exact workflow state와 수렴 조건으로 강제합니다."
        )
        parser.add_argument("--workflow-id", required=True)
        commands = parser.add_subparsers(dest="command", required=True)

        opener = commands.add_parser("open", help="완료 조건을 고정하고 루프를 엽니다")
        opener.add_argument("--loop-id", required=True)
        opener.add_argument("--goal", required=True)
        opener.add_argument("--acceptance", action="append", dest="acceptance", required=True)
        opener.set_defaults(operation=EvaluationCommand.OPEN)

        rounder = commands.add_parser("round", help="회차의 지적과 심판 판정을 기록합니다")
        rounder.add_argument("--loop-id", required=True)
        rounder.add_argument("--number", type=int, required=True)
        rounder.add_argument("--finding", action="append", dest="findings", required=True)
        rounder.set_defaults(operation=EvaluationCommand.ROUND)

        closer = commands.add_parser("close", help="루프를 닫습니다")
        closer.add_argument("--loop-id", required=True)
        closer.add_argument("--outcome", choices=tuple(sorted(OUTCOMES)), required=True)
        closer.add_argument("--summary", required=True)
        closer.set_defaults(operation=EvaluationCommand.CLOSE)

        receipt = commands.add_parser("receipt", help="phase evidence용 receipt를 출력합니다")
        receipt.add_argument("--loop-id", required=True)
        receipt.set_defaults(operation=EvaluationCommand.RECEIPT)
        return parser

    def _text(self, namespace: argparse.Namespace, key: str) -> str:
        value = getattr(namespace, key, None)
        if not isinstance(value, str) or not value.strip():
            raise EvaluationLoopError(f"{key}는 비어 있지 않은 string이어야 합니다")
        return value.strip()

    def _integer(self, namespace: argparse.Namespace, key: str) -> int:
        value = getattr(namespace, key, None)
        if not isinstance(value, int) or isinstance(value, bool):
            raise EvaluationLoopError(f"{key}는 integer여야 합니다")
        return value

    def _string_sequence(
        self,
        namespace: argparse.Namespace,
        key: str,
    ) -> tuple[str, ...]:
        value = getattr(namespace, key, None)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise EvaluationLoopError(f"{key}는 비어 있지 않은 string 목록이어야 합니다")
        return tuple(item.strip() for item in value)

    def _print_warnings(self, loop: EvaluationLoop, stream: TextIO) -> None:
        for warning in loop.recurrence_warnings():
            print(warning, file=stream)


class EvaluationLoopEntrypoint:
    """Process defaults를 evaluation application boundary에 전달합니다."""

    def run(self) -> int:
        """Current process arguments와 runtime identity로 CLI를 실행합니다.

        Returns:
            Application exit code입니다.
        """
        return EvaluationLoopApplication().run(
            tuple(sys.argv[1:]),
            os.environ,
            Path.cwd(),
            sys.stdout,
        )


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(EvaluationLoopEntrypoint().run())
