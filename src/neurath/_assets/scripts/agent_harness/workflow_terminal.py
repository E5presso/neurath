"""모든 workflow writer가 공유할 phase 종료 projection과 watchdog 경계입니다."""

import math
from collections.abc import Mapping

EVALUATION_WATCHDOG_SECONDS = 90 * 60


class WorkflowTerminalError(ValueError):
    """Aggregate와 내부 phase의 종료 상태가 서로 모순됩니다."""


class WorkflowTerminalPolicy:
    """성공과 비성공 종료가 내부 phase 기록을 모순되게 남기지 못하게 합니다."""

    def validate_transition(
        self,
        current: Mapping[str, object],
        candidate: Mapping[str, object],
    ) -> None:
        """단계와 과거 결과를 보존하고 현재 pending 단계 하나의 진행만 허용합니다.

        다른 namespace 갱신, legacy policy 보정과 마지막 단계의 원자적 종료는
        차단하지 않습니다. 단계 삭제·재배열·과거 결과 수정은 모든 writer에서 거부합니다.

        Args:
            current: 현재 저장된 workflow payload입니다.
            candidate: 같은 workflow에 제출한 다음 payload입니다.

        Raises:
            WorkflowTerminalError: 단계나 과거 결과를 바꾸거나 순서 밖으로 진행합니다.
        """
        previous = current.get("phase_run")
        phase = candidate.get("phase_run")
        if previous == phase:
            return
        if not isinstance(previous, Mapping) or not isinstance(phase, Mapping):
            raise WorkflowTerminalError("workflow transition must preserve its phase projection")
        if "phases" not in previous:
            raise WorkflowTerminalError("legacy workflow policy must be preserved exactly")
        for key in ("schema_version", "skill", "run_id", "started_at_epoch", "north_star"):
            if phase.get(key) != previous.get(key):
                raise WorkflowTerminalError("workflow transition cannot replace phase identity")
        old_rows = previous.get("phases")
        new_rows = phase.get("phases")
        if (
            not isinstance(old_rows, list)
            or not isinstance(new_rows, list)
            or not old_rows
            or len(old_rows) != len(new_rows)
            or any(not isinstance(row, Mapping) for row in (*old_rows, *new_rows))
        ):
            raise WorkflowTerminalError("workflow transition must preserve every phase")
        expected_current = previous.get("current_phase_id")
        for index, (old, new) in enumerate(zip(old_rows, new_rows, strict=True)):
            if old.get("id") != new.get("id") or old.get("name") != new.get("name"):
                raise WorkflowTerminalError(
                    "workflow transition must preserve phase identity and order"
                )
            if old == new:
                continue
            if (
                old.get("id") != previous.get("current_phase_id")
                or old.get("status") != "pending"
                or new.get("status") not in {"completed", "skipped", "failed", "blocked"}
            ):
                raise WorkflowTerminalError("only the current pending phase may change")
            expected_current = (
                new_rows[index + 1].get("id")
                if new.get("status") in {"completed", "skipped"} and index + 1 < len(new_rows)
                else None
            )
        if phase.get("current_phase_id") != expected_current:
            raise WorkflowTerminalError(
                "workflow transition must advance the current phase in order"
            )

    def validate_phase(
        self,
        current: Mapping[str, object],
        candidate: Mapping[str, object],
        *,
        completed: bool,
    ) -> None:
        """기존 phase identity를 보존하고 terminal marker와 모든 phase 상태를 대조합니다.

        Args:
            current: Writer가 바꿀 수 없는 저장된 원본 workflow payload입니다.
            candidate: Final event가 저장하려는 새 payload입니다.
            completed: Aggregate가 성공 종료인지 실패 종료인지 구분합니다.

        Raises:
            ValueError: Phase 삭제, identity 변경 또는 내부 종료 상태의 모순입니다.
        """
        self.validate_transition(current, candidate)
        previous = current.get("phase_run")
        phase = candidate.get("phase_run")
        if previous is None and phase is None:
            return
        if not isinstance(previous, Mapping) or not isinstance(phase, Mapping):
            raise WorkflowTerminalError("workflow finalization must preserve its phase projection")
        if "schema_version" not in previous or (
            previous.get("schema_version") == 1
            and set(previous).issubset({"schema_version", "adaptive_control_required"})
        ):
            if phase != previous:
                raise WorkflowTerminalError("legacy workflow policy must be preserved exactly")
            return
        for key in ("schema_version", "skill", "run_id", "started_at_epoch"):
            if phase.get(key) != previous.get(key):
                raise ValueError("workflow finalization cannot replace phase identity")
        terminal = phase.get("terminal_state")
        phases = phase.get("phases")
        if (
            not isinstance(terminal, str)
            or not terminal
            or phase.get("current_phase_id") is not None
            or not isinstance(phases, list)
            or not phases
            or any(not isinstance(item, Mapping) for item in phases)
        ):
            raise ValueError("terminal workflow requires a terminal phase projection")
        statuses = tuple(item.get("status") for item in phases)
        if completed:
            if terminal in {"failed", "blocked"} or any(
                status not in {"completed", "skipped"} for status in statuses
            ):
                raise ValueError("completed workflow has incomplete or failed phases")
        elif terminal not in {"failed", "blocked"} or terminal not in statuses:
            raise ValueError("failed workflow requires a matching failed or blocked phase")

    def watchdog_expired(
        self,
        kind: str,
        current: Mapping[str, object],
        now: float,
    ) -> bool:
        """현재 저장된 시작 시각에만 실제 경과 시간을 대조합니다.

        Args:
            kind: 생성 시 고정된 workflow 종류입니다.
            current: Candidate가 아닌 저장된 phase 시작 시각의 소유자입니다.
            now: Admission boundary에서 읽은 현재 시각입니다.

        Returns:
            evaluate-harness의 유효한 시작 시각에서 90분을 초과했을 때만 참입니다.
        """
        phase = current.get("phase_run")
        if kind != "evaluate-harness" or not isinstance(phase, Mapping):
            return False
        started = phase.get("started_at_epoch")
        return (
            isinstance(started, int | float)
            and not isinstance(started, bool)
            and math.isfinite(started)
            and math.isfinite(now)
            and now - started > EVALUATION_WATCHDOG_SECONDS
        )
