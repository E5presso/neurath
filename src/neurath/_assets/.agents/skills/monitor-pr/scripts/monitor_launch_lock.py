#!/usr/bin/env python3
"""PR monitor의 handoff와 launch 전체를 process 간 lock으로 직렬화합니다."""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType


def run_locked(lock_path: Path, command: list[str]) -> int:
    """Exclusive file lock을 보유한 동안 exact starter command를 실행합니다.

    Args:
        lock_path: 같은 PR monitor starter가 공유하는 lock file 경로입니다.
        command: Lock 안에서 한 번 실행할 starter command입니다.

    Returns:
        Starter command의 종료 코드입니다.

    Raises:
        ValueError: 실행할 command가 비어 있을 때 발생합니다.
    """
    if not command:
        raise ValueError("monitor starter command is required")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        process: subprocess.Popen[str] | None = None
        received_signal: int | None = None
        signal_received_at: float | None = None

        def forward_signal(signum: int, _frame: FrameType | None) -> None:
            """Wrapper signal을 현재 starter process group에 전달합니다.

            Args:
                signum: Wrapper가 받은 POSIX signal 번호입니다.
                _frame: Python signal handler가 제공하는 현재 stack frame입니다.
            """
            nonlocal received_signal, signal_received_at
            if received_signal is None:
                received_signal = signum
                signal_received_at = time.monotonic()
            if process is not None:
                _signal_process_group(process, signum)

        previous_handlers = {
            signum: signal.signal(signum, forward_signal)
            for signum in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            process = subprocess.Popen(command, start_new_session=True, text=True)
            if received_signal is not None:
                _signal_process_group(process, received_signal)
            returncode = _wait_for_starter(
                process,
                received_signal=lambda: received_signal,
                signal_received_at=lambda: signal_received_at,
            )
        finally:
            if process is not None and (received_signal is not None or process.poll() is None):
                _stop_process_group(process)
            for signum, previous_handler in previous_handlers.items():
                signal.signal(signum, previous_handler)
        if received_signal is not None:
            return 128 + received_signal
        return returncode


def _wait_for_starter(
    process: subprocess.Popen[str],
    *,
    received_signal: Callable[[], int | None],
    signal_received_at: Callable[[], float | None],
) -> int:
    """Starter 종료를 기다리고 signal grace 뒤 process group을 강제 종료합니다.

    Args:
        process: Lock 안에서 실행 중인 direct starter process입니다.
        received_signal: Wrapper가 받은 signal 번호를 반환합니다.
        signal_received_at: 첫 signal을 받은 monotonic 시각을 반환합니다.

    Returns:
        Direct starter process의 종료 코드입니다.
    """
    while True:
        try:
            return process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            signum = received_signal()
            received_at = signal_received_at()
            if signum is None or received_at is None:
                continue
            if time.monotonic() - received_at >= 2:
                _signal_process_group(process, signal.SIGKILL)


def _stop_process_group(process: subprocess.Popen[str]) -> None:
    """중단 경로에서 starter process group 전체를 끝낸 뒤 direct child를 회수합니다.

    Args:
        process: 종료하고 회수할 direct starter process입니다.

    Raises:
        RuntimeError: SIGKILL 뒤에도 starter process group이 남아 있을 때 발생합니다.
    """
    _signal_process_group(process, signal.SIGTERM)
    graceful_deadline = time.monotonic() + 2
    while _process_group_exists(process.pid) and time.monotonic() < graceful_deadline:
        if process.poll() is None:
            try:
                process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
        else:
            time.sleep(0.05)
    if _process_group_exists(process.pid):
        _signal_process_group(process, signal.SIGKILL)
    if process.poll() is None:
        process.wait()
    forced_deadline = time.monotonic() + 2
    while _process_group_exists(process.pid) and time.monotonic() < forced_deadline:
        time.sleep(0.02)
    if _process_group_exists(process.pid):
        raise RuntimeError(f"starter process group {process.pid} survived SIGKILL")


def _process_group_exists(process_group_id: int) -> bool:
    """Starter process group에 signal 가능한 process가 남아 있는지 확인합니다.

    Args:
        process_group_id: `start_new_session`으로 만든 starter process group ID입니다.

    Returns:
        Process group이 아직 존재하면 True입니다.
    """
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Starter descendant는 모두 같은 uid로 실행되므로 EPERM은 group id가
        # 남의 process로 재사용됐다는 뜻입니다. 우리 group은 이미 끝났습니다.
        return False
    return True


def _signal_process_group(process: subprocess.Popen[str], signum: int) -> None:
    """이미 끝난 process group은 무시하고 signal을 전달합니다.

    Args:
        process: Signal을 받을 process group의 leader입니다.
        signum: 전달할 POSIX signal 번호입니다.
    """
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass
    except PermissionError:
        # EPERM은 group id가 남의 process로 재사용된 경우입니다. 우리 starter
        # group은 이미 끝났으므로 signal 거부를 무시합니다.
        pass


def build_parser() -> argparse.ArgumentParser:
    """Launch lock CLI parser를 생성합니다.

    Returns:
        Lock 경로와 starter command를 검증하는 parser입니다.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock-path", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    """CLI의 starter command를 process 간 lock 안에서 실행합니다.

    Returns:
        Starter command의 종료 코드입니다.

    Raises:
        ValueError: 실행할 starter command가 비어 있을 때 발생합니다.
    """
    args = build_parser().parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return run_locked(args.lock_path, command)


if __name__ == "__main__":
    raise SystemExit(main())
