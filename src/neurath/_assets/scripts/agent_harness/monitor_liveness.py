"""Exact monitor route, process와 heartbeat freshness를 공유 검증합니다."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


class MonitorLivenessError(ValueError):
    """Monitor lease와 process-local observation이 live proof를 만들지 못했습니다."""


def read_monitor_observation(path: Path) -> dict[str, object]:
    """Atomic-replace observation resource를 filesystem mutation 없이 읽습니다.

    Args:
        path: Runtime resource resolver가 파생한 private observation path입니다.

    Returns:
        현재 observation JSON object입니다.

    Raises:
        OSError: Observation resource를 읽을 수 없을 때 발생합니다.
        json.JSONDecodeError: Observation JSON이 invalid하면 발생합니다.
        TypeError: Observation root가 object가 아니면 발생합니다.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


@dataclass(frozen=True, slots=True)
class MonitorLease:
    """Canonical subscription 또는 launch expectation이 고정한 monitor lease입니다."""

    provider: str
    """Observation이 보고해야 하는 exact monitor provider입니다."""
    repo: str
    """Monitor가 추적해야 하는 exact repository입니다."""
    pr_number: int
    """Monitor가 추적해야 하는 exact pull request 번호입니다."""
    session_id: str
    """Monitor route를 소유하는 exact runtime session입니다."""
    workflow_id: str
    """Monitor route를 소유하는 exact workflow입니다."""
    runtime_id: str
    """다른 launch observation을 거부하는 unique runtime identity입니다."""
    worktree_id: str
    """Observation resource를 파생한 opaque worktree identity입니다."""
    resume_adapter: str
    """Monitor가 실제로 구성한 resume capability 상태입니다."""
    pid: int | None
    """Known launch에서는 observation과 일치해야 하는 exact monitor PID입니다."""
    manager_pid: int | None
    """Detached manager가 있으면 함께 살아 있어야 하는 exact process ID입니다."""
    poll_interval_seconds: int
    """Heartbeat freshness window를 계산할 configured poll interval입니다."""
    minimum_heartbeat_at_epoch: float
    """이번 launch 또는 canonical subscription보다 오래된 cache를 거부할 경계입니다."""

    def __post_init__(self) -> None:
        """Lease field가 liveness 판정 전에 exact bounded shape인지 검증합니다.

        Raises:
            MonitorLivenessError: Identity, PID, interval 또는 heartbeat baseline이 invalid하면
                발생합니다.
        """
        for field, value in (
            ("provider", self.provider),
            ("repo", self.repo),
            ("session_id", self.session_id),
            ("workflow_id", self.workflow_id),
            ("runtime_id", self.runtime_id),
            ("worktree_id", self.worktree_id),
            ("resume_adapter", self.resume_adapter),
        ):
            if not value.strip():
                raise MonitorLivenessError(f"monitor lease {field} is missing")
        if self.provider != "local-pr-monitor":
            raise MonitorLivenessError("monitor lease provider is unsupported")
        if self.resume_adapter not in {"app-server", "command", "unavailable"}:
            raise MonitorLivenessError("monitor lease resume_adapter is invalid")
        self._positive_integer(self.pr_number, "monitor lease PR number is invalid")
        self._optional_pid(self.pid, "monitor lease PID is invalid")
        self._optional_pid(self.manager_pid, "monitor lease manager PID is invalid")
        self._positive_integer(
            self.poll_interval_seconds,
            "monitor lease poll interval is invalid",
        )
        if (
            not isinstance(self.minimum_heartbeat_at_epoch, int | float)
            or isinstance(self.minimum_heartbeat_at_epoch, bool)
            or self.minimum_heartbeat_at_epoch < 0
        ):
            raise MonitorLivenessError("monitor lease heartbeat baseline is invalid")

    def route(self) -> dict[str, object]:
        """Observation과 exact equality로 비교할 stable route를 반환합니다.

        Returns:
            Provider, repository, session, workflow와 runtime identity입니다.
        """
        return {
            "provider": self.provider,
            "repo": self.repo,
            "pr_number": self.pr_number,
            "session_id": self.session_id,
            "workflow_id": self.workflow_id,
            "runtime_id": self.runtime_id,
            "worktree_id": self.worktree_id,
            "resume_adapter": self.resume_adapter,
        }

    def _positive_integer(self, value: int, message: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise MonitorLivenessError(message)

    def _optional_pid(self, value: int | None, message: str) -> None:
        if value is not None:
            self._positive_integer(value, message)


class MonitorLivenessValidator:
    """MonitorLease와 process-local observation에서 read-only live receipt를 만듭니다."""

    _SUPPORTED_OBSERVATION_SCHEMAS = frozenset({4})
    _MAX_MISSED_POLL_INTERVALS = 2
    _HEARTBEAT_GRACE_SECONDS = 5.0
    _FUTURE_CLOCK_SKEW_SECONDS = 5.0

    def __init__(self, process_alive: Callable[[int], bool] | None = None) -> None:
        """Optional process probe를 고정합니다.

        Args:
            process_alive: PID가 current process table에 살아 있는지 읽는 optional probe입니다.
        """
        self._process_alive = process_alive or self._default_process_alive

    def validate(
        self,
        lease: MonitorLease,
        observation: Mapping[str, object],
        *,
        now_epoch: float,
    ) -> dict[str, object]:
        """Exact route, PID와 bounded heartbeat freshness를 모두 검증합니다.

        Args:
            lease: Canonical subscription 또는 current launch가 기대하는 route입니다.
            observation: Process-local monitor observation cache입니다.
            now_epoch: Freshness를 계산할 caller-owned current timestamp입니다.

        Returns:
            Exact route, process와 heartbeat를 포함한 JSON-compatible receipt입니다.

        Raises:
            MonitorLivenessError: Schema, identity, PID, process 또는 freshness가 invalid하면
                발생합니다.
        """
        if not isinstance(now_epoch, int | float) or isinstance(now_epoch, bool) or now_epoch < 0:
            raise MonitorLivenessError("monitor liveness clock is invalid")
        schema_version = observation.get("schema_version")
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version not in self._SUPPORTED_OBSERVATION_SCHEMAS
        ):
            raise MonitorLivenessError("monitor runtime observation schema is unsupported")
        expected_route = lease.route()
        for field, expected_value in expected_route.items():
            if observation.get(field) != expected_value:
                raise MonitorLivenessError(
                    f"monitor runtime {field} mismatch: "
                    f"expected {expected_value!r}, got {observation.get(field)!r}"
                )
        observed_interval = observation.get("poll_interval_seconds")
        if observed_interval != lease.poll_interval_seconds:
            raise MonitorLivenessError("monitor runtime poll_interval_seconds mismatch")
        observed_pid = self._positive_pid(
            observation.get("pid"),
            "monitor runtime pid is missing",
        )
        if lease.pid is not None and observed_pid != lease.pid:
            raise MonitorLivenessError(
                f"monitor runtime pid mismatch: expected {lease.pid!r}, got {observed_pid!r}"
            )
        heartbeat = observation.get("heartbeat_at_epoch")
        if not isinstance(heartbeat, int | float) or isinstance(heartbeat, bool):
            raise MonitorLivenessError("monitor runtime heartbeat is missing")
        heartbeat_epoch = float(heartbeat)
        if heartbeat_epoch < lease.minimum_heartbeat_at_epoch:
            raise MonitorLivenessError("monitor runtime heartbeat predates this launch")
        if heartbeat_epoch > float(now_epoch) + self._FUTURE_CLOCK_SKEW_SECONDS:
            raise MonitorLivenessError("monitor runtime heartbeat is ahead of the liveness clock")
        maximum_age = (
            lease.poll_interval_seconds * self._MAX_MISSED_POLL_INTERVALS
            + self._HEARTBEAT_GRACE_SECONDS
        )
        if float(now_epoch) - heartbeat_epoch > maximum_age:
            raise MonitorLivenessError("monitor runtime heartbeat is stale")
        self._assert_process_alive(observed_pid, "monitor runtime process is not alive")
        receipt: dict[str, object] = {
            "schema_version": schema_version,
            **expected_route,
            "pid": observed_pid,
            "heartbeat_at_epoch": heartbeat_epoch,
            "poll_interval_seconds": lease.poll_interval_seconds,
        }
        if lease.manager_pid is not None:
            self._assert_process_alive(
                lease.manager_pid,
                "monitor process manager is not alive",
            )
            receipt["manager_pid"] = lease.manager_pid
        return receipt

    def _positive_pid(self, value: object, message: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise MonitorLivenessError(message)
        return value

    def _assert_process_alive(self, pid: int, message: str) -> None:
        if not self._process_alive(pid):
            raise MonitorLivenessError(message)

    def _default_process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError, ValueError:
            return False
        return True
