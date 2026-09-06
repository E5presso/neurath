#!/usr/bin/env python3
"""Runtime-derived resources에서 PR monitor background process를 시작합니다."""

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from monitor_runtime_resources import MonitorRuntimeResources


class MonitorProcessManager:
    """Process manager 선택과 exact runtime resource receipt를 캡슐화합니다."""

    def __init__(self, resources: MonitorRuntimeResources) -> None:
        """Current runtime env와 Git cwd가 결정한 resources를 보관합니다.

        Args:
            resources: Process, log, plist 경로를 current runtime에 고정한 handle입니다.
        """
        self._resources = resources

    def launch(
        self,
        *,
        launcher: str,
        label: str,
        poll_interval_seconds: int,
        command: list[str],
        user_id: int,
        readiness_attempts: int = 50,
    ) -> dict[str, object]:
        """선택한 process manager로 monitor를 시작하고 live receipt를 반환합니다.

        Args:
            launcher: 지원되는 ``launchctl`` 또는 detached ``nohup`` 정책입니다.
            label: LaunchAgent를 선택한 경우 exact job을 식별하는 label입니다.
            poll_interval_seconds: Monitor command와 receipt가 공유할 polling 주기입니다.
            command: Supervisor가 시작하고 실패 시 재시작할 exact monitor argv입니다.
            user_id: LaunchAgent GUI domain을 결정하는 현재 사용자 ID입니다.
            readiness_attempts: LaunchAgent live PID를 확인할 최대 read-back 횟수입니다.

        Returns:
            선택된 launcher와 live process resource를 증명하는 manager receipt입니다.

        Raises:
            ValueError: Launcher, 숫자 정책, command가 process contract를 위반할 때 발생합니다.
            RuntimeError: Detached supervisor가 시작 직후 종료될 때 발생합니다.
        """
        if launcher not in {"launchctl", "nohup"}:
            raise ValueError("monitor launcher is invalid")
        if poll_interval_seconds < 1 or readiness_attempts < 1 or user_id < 0:
            raise ValueError("monitor process manager numeric inputs are invalid")
        if not command:
            raise ValueError("monitor command is required")
        if launcher == "launchctl":
            launchctl_receipt = self._launch_with_launchctl(
                label=label,
                user_id=user_id,
                readiness_attempts=readiness_attempts,
            )
            if launchctl_receipt.get("pid"):
                return {
                    **self._base_receipt(poll_interval_seconds),
                    "launcher": "launchctl",
                    "launch_label": label,
                    "launch_plist_resource": self._resources.launch_plist_path(label).name,
                    "keep_alive_on_failure": True,
                    "pid": launchctl_receipt["pid"],
                }
            fallback = self._launch_detached(
                command=self._with_launcher(command, "nohup"),
                poll_interval_seconds=poll_interval_seconds,
            )
            fallback["launchctl_failure"] = launchctl_receipt.get(
                "failure",
                "launchctl job did not expose a live PID",
            )
            return fallback
        return self._launch_detached(
            command=self._with_launcher(command, "nohup"),
            poll_interval_seconds=poll_interval_seconds,
        )

    def _base_receipt(self, poll_interval_seconds: int) -> dict[str, object]:
        return {
            "provider": "local-pr-monitor",
            "session_id": self._resources.session_id,
            "worktree_id": self._resources.worktree_id,
            "observation_resource": self._resources.observation_resource(),
            "log_resource": self._resources.stdout_path.name,
            "error_log_resource": self._resources.stderr_path.name,
            "poll_interval_seconds": poll_interval_seconds,
        }

    def _launch_with_launchctl(
        self,
        *,
        label: str,
        user_id: int,
        readiness_attempts: int,
    ) -> dict[str, object]:
        domain = f"gui/{user_id}"
        service = f"{domain}/{label}"
        self._run_launchctl(("bootout", service))
        self._run_launchctl(("remove", label))
        bootstrap = self._run_launchctl((
            "bootstrap",
            domain,
            str(self._resources.launch_plist_path(label)),
        ))
        if bootstrap.returncode == 0:
            self._run_launchctl(("kickstart", "-k", service))
            candidate_pid: int | None = None
            consecutive_live_checks = 0
            required_live_checks = min(10, max(2, readiness_attempts))
            for _attempt in range(readiness_attempts):
                listing = self._run_launchctl(("list",))
                pid = self._pid_from_launchctl_list(listing.stdout, label)
                if pid is None or pid != candidate_pid:
                    candidate_pid = pid
                    consecutive_live_checks = 1 if pid is not None else 0
                else:
                    consecutive_live_checks += 1
                if pid is not None and consecutive_live_checks >= required_live_checks:
                    return {"pid": pid}
                time.sleep(0.1)
        readback = self._run_launchctl(("print", service))
        self._run_launchctl(("bootout", service))
        self._run_launchctl(("remove", label))
        failure = (readback.stdout or readback.stderr).strip()
        if not failure:
            failure = (bootstrap.stdout or bootstrap.stderr).strip()
        return {"pid": None, "failure": self._concise_launchctl_failure(failure)}

    def _run_launchctl(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["launchctl", *arguments],
            check=False,
            capture_output=True,
            text=True,
        )

    def _pid_from_launchctl_list(self, output: str, label: str) -> int | None:
        for line in output.splitlines():
            fields = line.split()
            if len(fields) < 3 or fields[2] != label or fields[0] == "-":
                continue
            try:
                return int(fields[0])
            except ValueError:
                return None
        return None

    def _concise_launchctl_failure(self, output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        exit_lines = [line for line in lines if "last exit code" in line]
        if exit_lines:
            return exit_lines[-1]
        return (lines[-1] if lines else "launchctl job did not expose a live PID")[-500:]

    def _launch_detached(
        self,
        *,
        command: list[str],
        poll_interval_seconds: int,
    ) -> dict[str, object]:
        self._resources.state_directory.mkdir(parents=True, exist_ok=True)
        supervised_command = [
            "/bin/bash",
            "-c",
            (
                "child=''; "
                'trap \'if [ -n "$child" ]; then kill "$child" 2>/dev/null || true; '
                'wait "$child" 2>/dev/null || true; fi; exit 0\' TERM INT; '
                'while true; do "$@" & child=$!; wait "$child"; status=$?; child=\'\'; '
                'if [ "$status" -eq 0 ]; then exit 0; fi; sleep 5; done'
            ),
            "_",
            *command,
        ]
        with (
            self._resources.stdout_path.open("a", encoding="utf-8") as stdout,
            self._resources.stderr_path.open("a", encoding="utf-8") as stderr,
        ):
            process = self._popen_detached(supervised_command, stdout, stderr)
        time.sleep(0.1)
        if process.poll() is not None:
            raise RuntimeError("detached monitor process exited during launch")
        return {
            **self._base_receipt(poll_interval_seconds),
            "launcher": "nohup",
            "manager_pid": process.pid,
            "keep_alive_on_failure": True,
        }

    def _popen_detached(
        self,
        command: list[str],
        stdout: TextIO,
        stderr: TextIO,
    ) -> subprocess.Popen[str]:
        return subprocess.Popen(
            command,
            cwd=self._resources.worktree,
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )

    def _with_launcher(self, command: list[str], launcher: str) -> list[str]:
        updated = list(command)
        try:
            index = updated.index("--launcher")
        except ValueError:
            return [*updated, "--launcher", launcher]
        if index + 1 >= len(updated):
            return [*updated, launcher]
        updated[index + 1] = launcher
        return updated


class MonitorProcessManagerApplication:
    """Path-free CLI를 current runtime process manager에 연결합니다."""

    def parser(self) -> argparse.ArgumentParser:
        """Process policy와 command만 받는 parser를 반환합니다.

        Returns:
            Local resource 경로를 노출하지 않는 process-manager parser입니다.
        """
        parser = argparse.ArgumentParser()
        parser.add_argument("--launcher", choices=("launchctl", "nohup"), required=True)
        parser.add_argument("--label", required=True)
        parser.add_argument("--poll-interval-seconds", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--readiness-attempts", type=int, default=50)
        parser.add_argument("command", nargs=argparse.REMAINDER)
        return parser

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> dict[str, object]:
        """Current runtime resources에서 monitor를 시작합니다.

        Args:
            arguments: Launcher policy와 monitor command를 담은 public CLI 인자입니다.
            environment: Exact session identity를 제공하는 vendor runtime 환경입니다.
            cwd: Canonical worktree와 local resources를 파생할 현재 Git 경로입니다.

        Returns:
            실제로 시작한 manager와 runtime resources를 담은 live receipt입니다.
        """
        namespace = self.parser().parse_args(tuple(arguments))
        command = list(namespace.command)
        if command[:1] == ["--"]:
            command.pop(0)
        resources = MonitorRuntimeResources.resolve(cwd=cwd, environment=environment)
        return MonitorProcessManager(resources).launch(
            launcher=namespace.launcher,
            label=namespace.label,
            poll_interval_seconds=namespace.poll_interval_seconds,
            command=command,
            user_id=namespace.user_id,
            readiness_attempts=namespace.readiness_attempts,
        )


class MonitorProcessManagerEntrypoint:
    """Current process defaults를 path-free application에 전달합니다."""

    def run(self) -> int:
        """Live manager receipt를 stdout에 출력합니다.

        Returns:
            Process 시작과 receipt 출력이 끝나면 성공 종료 코드 0입니다.
        """
        receipt = MonitorProcessManagerApplication().run(
            tuple(sys.argv[1:]),
            os.environ,
            Path.cwd(),
        )
        print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
        return 0


if __name__ == "__main__":
    raise SystemExit(MonitorProcessManagerEntrypoint().run())
