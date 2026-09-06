#!/usr/bin/env python3
"""Runtime-derived process-local monitor observation을 live receipt로 검증합니다."""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from monitor_runtime_resources import MonitorRuntimeResources

from scripts.agent_harness.monitor_liveness import (
    MonitorLease,
    MonitorLivenessValidator,
    read_monitor_observation,
)


class ExpectedMonitorRuntime:
    """이번 launch가 요구하는 exact session workflow runtime identity입니다."""

    __slots__ = (
        "manager_pid",
        "minimum_heartbeat_at_epoch",
        "pid",
        "poll_interval_seconds",
        "pr_number",
        "repo",
        "resume_adapter",
        "runtime_id",
        "workflow_id",
    )

    def __init__(
        self,
        *,
        repo: str,
        pr_number: int,
        workflow_id: str,
        runtime_id: str,
        resume_adapter: str,
        pid: int | None,
        manager_pid: int | None,
        minimum_heartbeat_at_epoch: float,
        poll_interval_seconds: int,
    ) -> None:
        """검증할 immutable runtime prerequisites를 보관합니다.

        Args:
            repo: Observation이 보고해야 하는 exact GitHub repository입니다.
            pr_number: Observation이 추적해야 하는 pull request 번호입니다.
            workflow_id: Subscription을 결속할 canonical workflow identity입니다.
            runtime_id: 이번 monitor launch에서 생성한 고유 runtime identity입니다.
            resume_adapter: Collector가 보고해야 하는 resume capability 상태입니다.
            pid: Manager가 이미 알고 있으면 일치시킬 monitor process ID입니다.
            manager_pid: Detached supervisor가 있으면 생존을 검증할 process ID입니다.
            minimum_heartbeat_at_epoch: 이번 launch보다 오래된 cache를 거부할 경계입니다.
            poll_interval_seconds: Heartbeat freshness window를 계산할 poll interval입니다.
        """
        object.__setattr__(self, "repo", repo)
        object.__setattr__(self, "pr_number", pr_number)
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "runtime_id", runtime_id)
        object.__setattr__(self, "resume_adapter", resume_adapter)
        object.__setattr__(self, "pid", pid)
        object.__setattr__(self, "manager_pid", manager_pid)
        object.__setattr__(self, "minimum_heartbeat_at_epoch", minimum_heartbeat_at_epoch)
        object.__setattr__(self, "poll_interval_seconds", poll_interval_seconds)

    repo: str
    """Read-back observation이 추적해야 하는 exact GitHub repository입니다."""
    pr_number: int
    """Read-back observation이 추적해야 하는 pull request 번호입니다."""
    workflow_id: str
    """Subscription evidence를 소유하는 canonical workflow identity입니다."""
    runtime_id: str
    """다른 monitor instance의 cache를 거부하는 launch identity입니다."""
    resume_adapter: str
    """Monitor가 실제로 구성한 resume capability 상태입니다."""
    pid: int | None
    """Manager receipt가 특정한 경우 일치해야 하는 monitor process ID입니다."""
    manager_pid: int | None
    """Detached supervisor를 사용한 경우 생존해야 하는 manager process ID입니다."""
    minimum_heartbeat_at_epoch: float
    """이 시각보다 오래된 observation을 이전 launch 잔여물로 판정합니다."""
    poll_interval_seconds: int
    """Heartbeat의 최대 허용 age를 계산할 configured poll interval입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 expected identity mutation을 거부합니다.

        Args:
            name: 변경을 시도한 prerequisite attribute 이름입니다.
            value: Immutable identity에 새로 지정하려 한 값입니다.

        Raises:
            AttributeError: 생성 이후 어떤 attribute든 변경하려 할 때 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class MonitorRuntimeReadback:
    """Local observation cache와 실제 process 생존을 exact route로 검증합니다."""

    def __init__(
        self,
        resources: MonitorRuntimeResources,
        expected: ExpectedMonitorRuntime,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Runtime resource handle과 expected identity를 보관합니다.

        Args:
            resources: Current session과 worktree에 고정된 local resource handle입니다.
            expected: Observation과 process가 반드시 일치해야 하는 launch identity입니다.
            clock: Heartbeat age를 계산할 caller-owned clock입니다.
        """
        self._resources = resources
        self._expected = expected
        self._observation_path = resources.observation_path
        self._clock = clock
        self._liveness = MonitorLivenessValidator()

    def receipt(self) -> dict[str, object]:
        """모든 identity, heartbeat, process 조건을 통과한 receipt를 반환합니다.

        Returns:
            Exact route, live PID, fresh heartbeat를 증명한 canonical read-back receipt입니다.

        Raises:
            TypeError: Heartbeat 또는 observation baseline shape가 올바르지 않을 때 발생합니다.
            ValueError: Identity, PID, freshness, process 생존 검증이 실패할 때 발생합니다.
        """
        state = read_monitor_observation(self._observation_path)
        lease = MonitorLease(
            provider="local-pr-monitor",
            repo=self._expected.repo,
            pr_number=self._expected.pr_number,
            session_id=self._resources.session_id,
            workflow_id=self._expected.workflow_id,
            runtime_id=self._expected.runtime_id,
            worktree_id=self._resources.worktree_id,
            resume_adapter=self._expected.resume_adapter,
            pid=self._expected.pid,
            manager_pid=self._expected.manager_pid,
            poll_interval_seconds=self._expected.poll_interval_seconds,
            minimum_heartbeat_at_epoch=self._expected.minimum_heartbeat_at_epoch,
        )
        receipt = self._liveness.validate(lease, state, now_epoch=self._clock())
        last_seen = state.get("last_observed")
        if not isinstance(last_seen, Mapping):
            last_seen = state.get("last_seen")
        if not isinstance(last_seen, Mapping):
            raise TypeError("monitor runtime observation baseline is missing")
        receipt["observation_resource"] = self._resources.observation_resource()
        receipt["last_seen"] = dict(last_seen)
        return receipt

    def bundle(
        self,
        *,
        manager: Mapping[str, object],
        poll_interval_seconds: int,
    ) -> dict[str, object]:
        """Validated observation과 manager receipt를 subscription bundle로 결합합니다.

        Args:
            manager: Process manager가 current session resource에서 발행한 live receipt입니다.
            poll_interval_seconds: Durable subscription에 기록할 monitor polling 주기입니다.

        Returns:
            외부 저장용 subscription과 진단용 전체 receipt를 함께 담은 bundle입니다.

        Raises:
            ValueError: Manager의 session, worktree, observation resource가 다를 때 발생합니다.
        """
        if poll_interval_seconds != self._expected.poll_interval_seconds:
            raise ValueError("monitor runtime poll interval conflicts with launch expectation")
        receipt = self.receipt()
        if manager.get("session_id") != self._resources.session_id:
            raise ValueError("monitor manager session identity mismatch")
        if manager.get("worktree_id") != self._resources.worktree_id:
            raise ValueError("monitor manager worktree identity mismatch")
        if manager.get("observation_resource") != self._resources.observation_resource():
            raise ValueError("monitor manager observation resource mismatch")
        subscription = {
            **receipt,
            "poll_interval_seconds": poll_interval_seconds,
            "launcher": manager.get("launcher"),
        }
        for field in (
            "manager_pid",
            "launch_label",
            "launch_plist_resource",
            "keep_alive_on_failure",
        ):
            if field in manager:
                subscription[field] = manager[field]
        return {
            "receipt": {**dict(manager), **subscription},
            "subscription": subscription,
        }


class MonitorRuntimeReadbackApplication:
    """Path-free CLI와 current runtime observation resource를 연결합니다."""

    def parser(self) -> argparse.ArgumentParser:
        """Runtime identity와 launch receipt만 받는 parser를 반환합니다.

        Returns:
            Caller-selected local path 없이 expected launch만 받는 parser입니다.
        """
        parser = argparse.ArgumentParser()
        parser.add_argument("--repo", required=True)
        parser.add_argument("--pr-number", type=int, required=True)
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument("--runtime-id", required=True)
        parser.add_argument("--resume-adapter", required=True)
        parser.add_argument("--poll-interval-seconds", type=int, required=True)
        parser.add_argument("--minimum-heartbeat-at-epoch", type=float, required=True)
        parser.add_argument("--manager-json", required=True)
        return parser

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> dict[str, object]:
        """Runtime env와 Git cwd에서 observation subscription bundle을 만듭니다.

        Args:
            arguments: Expected workflow, runtime, manager receipt를 지정하는 CLI 인자입니다.
            environment: Current vendor session identity를 소유하는 runtime 환경입니다.
            cwd: Canonical worktree와 observation resource를 파생할 현재 Git 경로입니다.

        Returns:
            Live observation과 manager receipt가 exact route에 결속된 bundle입니다.

        Raises:
            json.JSONDecodeError: Manager receipt 인자가 JSON이 아닐 때 발생합니다.
            TypeError: Manager receipt의 JSON root가 object가 아닐 때 발생합니다.
            ValueError: PID 또는 runtime resource identity 검증이 실패할 때 발생합니다.
        """
        namespace = self.parser().parse_args(tuple(arguments))
        manager = json.loads(namespace.manager_json)
        if not isinstance(manager, Mapping):
            raise TypeError("monitor manager receipt must be an object")
        resources = MonitorRuntimeResources.resolve(cwd=cwd, environment=environment)
        expected = ExpectedMonitorRuntime(
            repo=namespace.repo,
            pr_number=namespace.pr_number,
            workflow_id=namespace.workflow_id,
            runtime_id=namespace.runtime_id,
            resume_adapter=namespace.resume_adapter,
            pid=self._optional_pid(manager.get("pid")),
            manager_pid=self._optional_pid(manager.get("manager_pid")),
            minimum_heartbeat_at_epoch=namespace.minimum_heartbeat_at_epoch,
            poll_interval_seconds=namespace.poll_interval_seconds,
        )
        return MonitorRuntimeReadback(resources, expected).bundle(
            manager=manager,
            poll_interval_seconds=namespace.poll_interval_seconds,
        )

    def _optional_pid(self, value: object) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("monitor manager PID receipt is invalid")
        return value


class MonitorRuntimeReadbackEntrypoint:
    """Current process defaults를 path-free readback application에 전달합니다."""

    def run(self) -> int:
        """Validated bundle을 출력하고 invalid evidence는 fail closed합니다.

        Returns:
            Validated receipt를 출력하면 0, evidence가 invalid하면 1입니다.
        """
        try:
            bundle = MonitorRuntimeReadbackApplication().run(
                tuple(sys.argv[1:]),
                os.environ,
                Path.cwd(),
            )
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))
        return 0


if __name__ == "__main__":
    raise SystemExit(MonitorRuntimeReadbackEntrypoint().run())
