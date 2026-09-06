"""Verifier와 validator의 owned process group을 bounded lifecycle로 실행합니다.

같은 group 또는 inherited ``NEURATH_BOUNDED_PROCESS_TOKEN``을 유지한 descendant는 정상
leader exit에서도 정리하며 survivor가 있었던 successful command는 125로 실패시킵니다.
이 primitive는 same-user hostile-code sandbox가 아닙니다. Allowed verifier는 token을
지우고 새 session으로 daemonize해서는 안 되며 그런 의도적 escape는 verifier contract
위반입니다.
"""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

_PROCESS_TOKEN_ENV = "NEURATH_BOUNDED_PROCESS_TOKEN"
_PROC_ROOT = Path("/proc")


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    """Process-group 종료 뒤 얻은 exact exit와 captured byte streams입니다."""

    returncode: int
    """Normal exit, timeout 124 또는 leaked descendant cleanup 125 status입니다."""

    stdout: bytes
    """Process group 종료 뒤 수집한 stdout bytes입니다."""

    stderr: bytes
    """Process group 종료 뒤 수집한 stderr bytes입니다."""

    timed_out: bool
    """Wall-clock watchdog이 process group을 종료했으면 참입니다."""


def run_bounded_process(
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    environment: Mapping[str, str] | None = None,
    input_bytes: bytes | None = None,
    merge_stderr: bool = False,
) -> BoundedProcessResult:
    """새 process group을 실행하고 owned/tagged descendant를 bounded하게 종료합니다.

    Args:
        arguments: Shell expansion 없이 실행할 non-empty argv입니다.
        cwd: Process가 실행될 existing directory입니다.
        timeout_seconds: Group 전체에 적용할 positive wall-clock watchdog입니다.
        environment: Optional exact process environment입니다.
        input_bytes: Optional stdin bytes입니다.
        merge_stderr: Stderr를 stdout stream에 합칠지 결정합니다.

    Returns:
        Group terminalization 뒤의 bounded process result입니다.

    Raises:
        ValueError: Arguments 또는 timeout이 invalid하면 발생합니다.
        OSError: Cwd 또는 executable을 사용할 수 없으면 발생합니다.
    """
    if not arguments or any(not isinstance(item, str) or not item for item in arguments):
        raise ValueError("bounded process arguments must be non-empty strings")
    if timeout_seconds <= 0:
        raise ValueError("bounded process timeout_seconds must be positive")
    if not cwd.is_dir():
        raise OSError("bounded process cwd must be an existing directory")
    process_token = secrets.token_hex(24)
    process_environment = dict(os.environ if environment is None else environment)
    process_environment[_PROCESS_TOKEN_ENV] = process_token
    process = subprocess.Popen(
        tuple(arguments),
        cwd=cwd,
        env=process_environment,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        start_new_session=True,
    )
    previous_sigterm: signal.Handlers | int | Callable[[int, FrameType | None], Any] | None = None
    owns_signal_handler = threading.current_thread() is threading.main_thread()
    if owns_signal_handler:
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def terminate_on_signal(signum: int, _frame: object) -> None:
            """External termination에서도 owned process tree를 먼저 닫습니다.

            Args:
                signum: 전달된 POSIX signal 번호입니다.
                _frame: Signal 시점의 optional interpreter frame이며 사용하지 않습니다.

            Raises:
                SystemExit: Owned process tree를 정리한 뒤 signal-derived status로 종료합니다.
            """
            _terminate_process_tree(process, process_token)
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, terminate_on_signal)
    try:
        try:
            stdout, stderr = process.communicate(input=input_bytes, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as timeout:
            _terminate_process_tree(process, process_token)
            try:
                stdout, stderr = process.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                stdout = timeout.output or b""
                stderr = timeout.stderr or b""
                _close_process_pipes(process)
            return BoundedProcessResult(
                returncode=124,
                stdout=stdout,
                stderr=b"" if stderr is None else stderr,
                timed_out=True,
            )
        except BaseException:
            _terminate_process_tree(process, process_token)
            raise
        cleaned_survivor = _terminate_process_tree(process, process_token)
        return BoundedProcessResult(
            returncode=(
                125 if process.returncode == 0 and cleaned_survivor else process.returncode
            ),
            stdout=stdout,
            stderr=b"" if stderr is None else stderr,
            timed_out=False,
        )
    finally:
        if owns_signal_handler and previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    process_token: str,
) -> bool:
    """Owned group과 inherited execution token을 가진 descendant를 종료합니다."""
    try:
        os.killpg(process.pid, signal.SIGSTOP)
    except OSError:
        pass
    descendants = set(_descendant_process_ids(process.pid))
    descendants.update(_process_ids_with_token(process_token))
    descendants.discard(os.getpid())
    live_descendants = {pid for pid in descendants if _process_exists(pid)}
    for pid in sorted(live_descendants, reverse=True):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    _wait_for_process_exit(live_descendants, timeout_seconds=0.5)
    return bool(live_descendants)


def _process_ids_with_token(process_token: str) -> tuple[int, ...]:
    """Re-parent되거나 새 session으로 이동한 tagged process PID를 읽습니다."""
    marker = f"{_PROCESS_TOKEN_ENV}={process_token}"
    if _PROC_ROOT.is_dir():
        marker_bytes = marker.encode()
        found = []
        for directory in _PROC_ROOT.iterdir():
            if not directory.name.isdigit():
                continue
            try:
                entries = (directory / "environ").read_bytes().split(b"\0")
            except OSError:
                continue
            if marker_bytes in entries:
                found.append(int(directory.name))
        return tuple(sorted(found))
    completed: subprocess.CompletedProcess[str] | None = None
    for arguments in (
        ("ps", "eww", "-axo", "pid=,command="),
        ("ps", "eww", "-eo", "pid=,command="),
    ):
        try:
            candidate = subprocess.run(
                arguments,
                capture_output=True,
                check=False,
                text=True,
                timeout=1.0,
            )
        except OSError, subprocess.TimeoutExpired:
            continue
        if candidate.returncode == 0:
            completed = candidate
            break
    if completed is None:
        return ()
    discovered: list[int] = []
    for line in completed.stdout.splitlines():
        pid_text, separator, command = line.strip().partition(" ")
        if not separator or not pid_text.isdigit() or marker not in command:
            continue
        discovered.append(int(pid_text))
    return tuple(discovered)


def _wait_for_process_exit(process_ids: set[int], *, timeout_seconds: float) -> None:
    """Killed descendant PID가 bounded grace 안에 OS table에서 사라지길 기다립니다."""
    pending = set(process_ids)
    deadline = time.monotonic() + timeout_seconds
    while pending and time.monotonic() < deadline:
        for pid in tuple(pending):
            if not _process_exists(pid):
                pending.remove(pid)
        if pending:
            time.sleep(0.01)


def _process_exists(pid: int) -> bool:
    """PID가 실행 가능한 process이며 zombie가 아니면 참입니다."""
    status = _proc_status(pid)
    if status is not None and status[0] == "Z":
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _descendant_process_ids(root_pid: int) -> tuple[int, ...]:
    """Current OS process table에서 root의 transitive child PID를 parent-first로 읽습니다."""
    if _PROC_ROOT.is_dir():
        children: dict[int, list[int]] = {}
        for directory in _PROC_ROOT.iterdir():
            if not directory.name.isdigit():
                continue
            status = _proc_status(int(directory.name))
            if status is not None:
                children.setdefault(status[1], []).append(int(directory.name))
        found: list[int] = []
        pending = list(children.get(root_pid, ()))
        while pending:
            pid = pending.pop()
            if pid in found:
                continue
            found.append(pid)
            pending.extend(children.get(pid, ()))
        return tuple(found)
    try:
        completed = subprocess.run(
            ("ps", "-axo", "pid=,ppid="),
            capture_output=True,
            check=False,
            text=True,
            timeout=1.0,
        )
    except OSError, subprocess.TimeoutExpired:
        return ()
    if completed.returncode != 0:
        return ()
    children: dict[int, list[int]] = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2 or not all(field.isdigit() for field in fields):
            continue
        pid, parent_pid = (int(field) for field in fields)
        children.setdefault(parent_pid, []).append(pid)
    discovered: list[int] = []
    pending = list(children.get(root_pid, ()))
    while pending:
        pid = pending.pop()
        discovered.append(pid)
        pending.extend(children.get(pid, ()))
    return tuple(discovered)


def _close_process_pipes(process: subprocess.Popen[bytes]) -> None:
    """Untrusted escaped writer가 남아도 parent pipe drain을 더 기다리지 않습니다."""
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _proc_status(pid: int) -> tuple[str, int] | None:
    """Read Linux state/parent without requiring an external process-listing utility."""
    try:
        # The comm field can itself contain spaces and closing parentheses.
        tail = (_PROC_ROOT / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return tail[0], int(tail[1])
    except (OSError, ValueError, IndexError):
        return None
