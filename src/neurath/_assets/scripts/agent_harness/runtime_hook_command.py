"""Runtime hook process를 exact repository SessionKernel application에 연결합니다."""

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from scripts.agent_harness.runtime_hook import RuntimeHookApplication
from scripts.agent_harness.session_kernel import SessionLocator, SessionRuntime

DEFAULT_ENCLAVE_MAX_BYTES = 16_384
DEFAULT_ADDITIONAL_CONTEXT_MAX_BYTES = 24_576


class RuntimeHookCommand:
    """Hook stdin과 runtime environment를 canonical repository state에 고정합니다."""

    def __init__(self, *, enclave_max_bytes: int, additional_context_max_bytes: int) -> None:
        """Process boundary가 사용할 두 context byte budget을 고정합니다.

        Args:
            enclave_max_bytes: Latest-only enclave JSON 전체의 byte 상한입니다.
            additional_context_max_bytes: Runtime hook context 출력의 byte 상한입니다.
        """
        self._enclave_max_bytes = enclave_max_bytes
        self._additional_context_max_bytes = additional_context_max_bytes

    def run(
        self,
        *,
        raw_input: str,
        environment: Mapping[str, str],
        cwd: Path,
        stdout: TextIO,
    ) -> int:
        """한 hook invocation을 처리하고 stdout에 protocol JSON 하나만 기록합니다.

        Args:
            raw_input: Vendor hook이 stdin으로 제공한 JSON 원문입니다.
            environment: Vendor identity와 wiring hint를 포함한 process environment입니다.
            cwd: Git common control root를 결정할 current worktree 경로입니다.
            stdout: Vendor hook protocol JSON을 기록할 text stream입니다.

        Returns:
            성공이면 0, invalid repository나 hook boundary 실패이면 nonzero입니다.
        """
        try:
            locator = SessionLocator.from_worktree(cwd)
            application = RuntimeHookApplication(
                locator,
                enclave_max_bytes=self._enclave_max_bytes,
                additional_context_max_bytes=self._additional_context_max_bytes,
            )
            result = application.run(raw_input, environment)
        except OSError, subprocess.CalledProcessError:
            stdout.write("{}\n")
            return 1
        stdout.write(f"{result.stdout}\n")
        stdout.flush()
        application.acknowledge(result)
        return result.exit_code


class RuntimeHookCli:
    """Vendor wiring argument를 validated environment hint로 변환하는 CLI입니다."""

    def run(self, arguments: list[str]) -> int:
        """CLI argument와 process streams를 RuntimeHookCommand에 전달합니다.

        Args:
            arguments: Program name을 제외한 command-line argument입니다.

        Returns:
            Hook application의 process exit code입니다.
        """
        parser = argparse.ArgumentParser(description="Run Neurath exact-session lifecycle hook.")
        parser.add_argument(
            "--runtime",
            choices=tuple(runtime.value for runtime in SessionRuntime),
            required=True,
        )
        namespace = parser.parse_args(arguments)
        environment = dict(os.environ)
        environment["NEURATH_HOOK_RUNTIME"] = str(namespace.runtime)
        command = RuntimeHookCommand(
            enclave_max_bytes=DEFAULT_ENCLAVE_MAX_BYTES,
            additional_context_max_bytes=DEFAULT_ADDITIONAL_CONTEXT_MAX_BYTES,
        )
        return command.run(
            raw_input=sys.stdin.read(),
            environment=environment,
            cwd=Path.cwd(),
            stdout=sys.stdout,
        )


if __name__ == "__main__":
    raise SystemExit(RuntimeHookCli().run(sys.argv[1:]))
