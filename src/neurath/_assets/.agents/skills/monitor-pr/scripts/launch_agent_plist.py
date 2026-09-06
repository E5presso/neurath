"""Runtime-derived local monitor LaunchAgent plist를 생성합니다."""

import argparse
import json
import os
import plistlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import mkstemp

from monitor_runtime_lock import (
    MonitorRuntimeCommitConflict,
    MonitorRuntimeCommitLock,
    monitor_runtime_target_is_claimed,
)
from monitor_runtime_resources import MonitorRuntimeResources


class LaunchAgentPlistWriter:
    """Exact runtime worktree 안에 crash-restarting LaunchAgent receipt를 씁니다."""

    def __init__(self, resources: MonitorRuntimeResources) -> None:
        """Caller가 선택할 수 없는 runtime resource handle을 보관합니다.

        Args:
            resources: Session과 Git worktree에서 검증된 local resource handle입니다.
        """
        self._resources = resources

    def write(self, *, label: str, command: Sequence[str]) -> Path:
        """Non-zero monitor exit만 재시작하는 plist를 atomic replace합니다.

        Args:
            label: Worktree-local LaunchAgent resource를 식별하는 검증 대상 label입니다.
            command: LaunchAgent가 exact worktree에서 실행할 비어 있지 않은 argv입니다.

        Returns:
            Atomic replace를 마친 runtime-derived plist 경로입니다.

        Raises:
            ValueError: Label이 안전하지 않거나 command에 빈 인자가 있을 때 발생합니다.
            MonitorRuntimeCommitConflict: Prepared handoff가 같은 plist path를 claim 중이면
                발생합니다.
        """
        output = self._resources.launch_plist_path(label)
        exact_command = list(command)
        if not exact_command or any(not part for part in exact_command):
            raise ValueError("launch agent command must contain non-empty arguments")
        payload = {
            "Label": label,
            "ProgramArguments": [
                "/bin/bash",
                "-c",
                'cd "$1"; shift; exec "$@"',
                "_",
                str(self._resources.worktree),
                *exact_command,
            ],
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 5,
            "ProcessType": "Background",
            "StandardOutPath": str(self._resources.stdout_path),
            "StandardErrorPath": str(self._resources.stderr_path),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = mkstemp(
            dir=output.parent,
            prefix=f".{output.name}.",
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                plistlib.dump(payload, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            with MonitorRuntimeCommitLock(output.parent):
                if monitor_runtime_target_is_claimed(output.parent, output.name):
                    raise MonitorRuntimeCommitConflict(
                        f"monitor runtime target is claimed by prepared handoff: {output}"
                    )
                os.replace(temporary_name, output)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
        return output


class LaunchAgentPlistApplication:
    """Path-free CLI를 current runtime resource writer에 연결합니다."""

    def parser(self) -> argparse.ArgumentParser:
        """Label과 exact command만 받는 parser를 반환합니다.

        Returns:
            Caller-selected 경로 없이 launch policy만 받는 parser입니다.
        """
        parser = argparse.ArgumentParser(
            description="Write one runtime-bound Neurath monitor LaunchAgent plist."
        )
        parser.add_argument("--label", required=True)
        parser.add_argument("command", nargs=argparse.REMAINDER)
        return parser

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> Path:
        """Current runtime env와 Git cwd에서 plist를 생성합니다.

        Args:
            arguments: Launch label과 monitor command를 담은 public CLI 인자입니다.
            environment: Exact session identity를 소유하는 runtime 환경입니다.
            cwd: Canonical worktree를 파생할 현재 Git 경로입니다.

        Returns:
            Current worktree에 atomic하게 생성한 plist 경로입니다.
        """
        namespace = self.parser().parse_args(tuple(arguments))
        command = list(namespace.command)
        if command[:1] == ["--"]:
            command.pop(0)
        resources = MonitorRuntimeResources.resolve(cwd=cwd, environment=environment)
        return LaunchAgentPlistWriter(resources).write(
            label=namespace.label,
            command=command,
        )


class LaunchAgentPlistEntrypoint:
    """Current process defaults를 path-free application에 전달합니다."""

    def run(self) -> int:
        """생성한 runtime resource receipt를 stdout에 출력합니다.

        Returns:
            Plist 생성과 receipt 출력이 끝나면 성공 종료 코드 0입니다.
        """
        path = LaunchAgentPlistApplication().run(
            tuple(sys.argv[1:]),
            os.environ,
            Path.cwd(),
        )
        print(json.dumps({"launch_plist_resource": path.name}, separators=(",", ":")))
        return 0


if __name__ == "__main__":
    raise SystemExit(LaunchAgentPlistEntrypoint().run())
