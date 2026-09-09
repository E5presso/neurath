"""PR monitor가 Codex app-server와 GitHub 상태를 연결하는 실행 흐름입니다."""

import argparse
import fcntl
from contextlib import contextmanager
import base64
import ctypes
import ctypes.util
import hashlib
import json
import os
import shlex
import shutil
import signal
import socket
import struct
import subprocess
from subprocess import Popen
from time import time as _wall_time
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self

from monitor_runtime_resources import MonitorRuntimeResources
from scripts.agent_harness.runtime_database import RuntimeDatabase, StoredRecord
from scripts.agent_harness.session_kernel import SessionLocator

APP_SERVER_NAMESPACE = "managed-app-server"

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TURN_LIST_READ_ERRORS = (RuntimeError, TimeoutError, TypeError, IndexError)


class AppServerResumeApplication:
    """Runtime-owned session과 Git-derived worktree를 app-server options에 결속합니다."""

    def parser(self) -> argparse.ArgumentParser:
        """Path, thread selector가 없는 behavior-only parser를 반환합니다.

        Returns:
            Current runtime에서 허용하는 resume 동작만 노출하는 parser입니다.
        """
        parser = argparse.ArgumentParser(
            description="Resume the current Codex task via app-server."
        )
        parser.add_argument(
            "--turn-timeout-seconds",
            type=int,
            default=int(os.environ.get("NEURATH_CODEX_TURN_TIMEOUT_SECONDS", "180")),
        )
        parser.add_argument("--probe", action="store_true")
        parser.add_argument("--inspect-turn-id")
        parser.add_argument("--find-claim-id")
        parser.add_argument("--find-event-id")
        parser.add_argument("--expected-head-sha")
        parser.add_argument("--terminate-managed-server", action="store_true")
        return parser

    def resolve(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> argparse.Namespace:
        """Current runtime resource에서 exact thread, cwd, socket을 파생합니다.

        Args:
            arguments: Resume 동작과 timeout을 지정하는 public CLI 인자입니다.
            environment: Vendor가 소유한 현재 session identity 환경입니다.
            cwd: Git이 canonical worktree를 판정할 현재 작업 경로입니다.

        Returns:
            Runtime-owned session과 worktree-local socket이 주입된 option namespace입니다.
        """
        namespace = self.parser().parse_args(tuple(arguments))
        resources = MonitorRuntimeResources.resolve(cwd=cwd, environment=environment)
        namespace.thread_id = resources.session_id
        namespace.cwd = str(resources.worktree)
        namespace.socket_path = str(resources.app_server_socket_path)
        return namespace


def monitor_delivery_marker(claim_id: str, event_id: str) -> str:
    """Turn history에서 exact monitor delivery를 찾을 machine marker를 반환합니다.

    Args:
        claim_id: Atomic mailbox claim identity입니다.
        event_id: Claimed monitor event identity입니다.

    Returns:
        User message에 포함할 exact delivery marker입니다.

    Raises:
        ValueError: Claim 또는 event identity가 비어 있을 때 발생합니다.
    """
    if not claim_id or not event_id:
        raise ValueError("monitor delivery marker requires claim and event identity")
    return f'<!-- neurath-monitor-delivery claim_id="{claim_id}" event_id="{event_id}" -->'


class AppServerClient:
    """PR monitor가 GitHub comment, check, review snapshot을 Codex resume 요청으로 변환하는 흐름을 캡슐화합니다."""

    def __init__(self, socket_path: Path) -> None:
        """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

        Args:
            socket_path: socket_path 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다."""
        self._socket_path = socket_path
        self._socket: socket.socket | None = None
        self._next_id = 1

    def __enter__(self) -> Self:
        """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

        Returns:
            monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(30)
        self._socket.connect(str(self._socket_path))
        self._handshake()
        return self

    def __exit__(self, *_exc: object) -> None:
        """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다."""
        if self._socket is not None:
            self._socket.close()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

        Args:
            method: method 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
            params: params 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

        Returns:
            monitor가 저장하거나 read-back할 resume 결과를 반환합니다.

        Raises:
            선언된 실패 조건에서 예외를 발생시킵니다."""
        request_id = self._next_id
        self._next_id += 1
        self._send_json({"id": request_id, "method": method, "params": params})
        while True:
            message = self._receive_json()
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                result = message.get("result", {})
                return result if isinstance(result, dict) else {"result": result}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

        Args:
            method: method 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
            params: params 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다."""
        self._send_json({"method": method, "params": params})

    def receive_message(self, timeout_seconds: float) -> dict[str, Any]:
        """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

        Args:
            timeout_seconds: timeout_seconds 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

        Returns:
            monitor가 저장하거나 read-back할 resume 결과를 반환합니다.

        Raises:
            선언된 실패 조건에서 예외를 발생시킵니다."""
        if self._socket is None:
            raise RuntimeError("socket is not connected")
        previous_timeout = self._socket.gettimeout()
        self._socket.settimeout(timeout_seconds)
        try:
            return self._receive_json()
        finally:
            self._socket.settimeout(previous_timeout)

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self._raw_send(request)
        response = self._raw_recv_until(b"\r\n\r\n")
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest())
        if b"101 Switching Protocols" not in response or accept not in response:
            raise RuntimeError(response.decode("utf-8", errors="replace"))

    def _send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend((0x80 | 126, *struct.pack("!H", length)))
        else:
            header.extend((0x80 | 127, *struct.pack("!Q", length)))
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self._raw_send(bytes(header) + masked)

    def _receive_json(self) -> dict[str, Any]:
        while True:
            first, second = self._raw_recv_exact(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._raw_recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._raw_recv_exact(8))[0]
            data = self._raw_recv_exact(length)
            if opcode == 0x8:
                raise RuntimeError("app-server websocket closed")
            if opcode == 0x1:
                decoded = json.loads(data.decode("utf-8"))
                return decoded if isinstance(decoded, dict) else {"result": decoded}

    def _raw_send(self, data: bytes) -> None:
        if self._socket is None:
            raise RuntimeError("socket is not connected")
        self._socket.sendall(data)

    def _raw_recv_exact(self, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            if self._socket is None:
                raise RuntimeError("socket is not connected")
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise RuntimeError("app-server socket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _raw_recv_until(self, marker: bytes) -> bytes:
        data = bytearray()
        while marker not in data:
            if self._socket is None:
                raise RuntimeError("socket is not connected")
            chunk = self._socket.recv(4096)
            if not chunk:
                raise RuntimeError("app-server socket closed")
            data.extend(chunk)
        return bytes(data)


def default_socket_path(cwd: str) -> Path:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        cwd: cwd 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    return Path(cwd).expanduser().resolve() / ".monitor-pr/app-server.sock"


def select_codex_binary() -> Path:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다.

    Raises:
        선언된 실패 조건에서 예외를 발생시킵니다."""
    candidates = [os.environ.get("CODEX_APP_SERVER_BIN", "")]
    candidates.extend(
        str(path)
        for path in sorted(
            Path.home().glob(".vscode/extensions/openai.chatgpt-*/bin/*/codex"),
            reverse=True,
        )
    )
    candidates.extend([
        "/Applications/Codex.app/Contents/Resources/codex",
        shutil.which("codex") or "",
    ])
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK):
            return Path(candidate)
    raise RuntimeError("codex app-server binary not found")


def ensure_app_server(socket_path, codex_binary):
    with _managed_app_server_lifecycle(socket_path) as resources:
        _ensure_app_server_locked(*resources, codex_binary)


def _ensure_app_server_locked(database, key, socket_path, codex_binary):
    if socket_path.exists() and socket_accepts_connections(socket_path):
        _validate_managed_app_server_locked(database, key, socket_path)
        return
    _record, current = _managed_record_locked(database, key, socket_path)
    if current["status"] == "active":
        _terminate_managed_app_server_locked(database, key, socket_path)
    else:
        socket_path.unlink(missing_ok=True)
    process = Popen(
        [str(codex_binary), "app-server", "--listen", f"unix://{socket_path}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={
            **os.environ,
            "NEURATH_MANAGED_APP_SERVER": "1",
            "NEURATH_MANAGED_APP_SERVER_SOCKET": str(socket_path),
        },
    )
    _write_managed_record_locked(
        database, key, socket_path, process.pid, codex_binary)
    deadline = _wall_time() + 20
    while _wall_time() < deadline:
        if socket_path.exists() and socket_accepts_connections(socket_path):
            return
        time.sleep(0.25)
    _terminate_managed_app_server_locked(database, key, socket_path)
    raise RuntimeError(f"app-server socket unavailable: {socket_path}")


def validate_managed_app_server_identity(socket_path):
    with _managed_app_server_lifecycle(socket_path) as resources:
        pid, executable, _record = _validate_managed_app_server_locked(
            *resources)
        return pid, executable


def _validate_managed_app_server_locked(database, key, socket_path):
    pid, executable_path, record = _read_managed_identity_locked(
        database, key, socket_path)
    try:
        process_group_id = os.getpgid(pid)
    except ProcessLookupError as error:
        raise RuntimeError("managed app-server process is missing") from error
    try:
        kernel_executable = kernel_process_executable(pid)
    except (OSError, RuntimeError) as error:
        raise RuntimeError(
            "managed app-server process identity mismatch") from error
    if (
        process_group_id != pid
        or not managed_app_server_command_matches(
            pid, socket_path, executable_path)
        or kernel_executable.resolve() != executable_path
        or not process_owns_unix_socket(pid, socket_path)
    ):
        raise RuntimeError("managed app-server process identity mismatch")
    return pid, executable_path, record


def restart_managed_app_server(socket_path, codex_binary):
    with _managed_app_server_lifecycle(socket_path) as resources:
        _terminate_managed_app_server_locked(*resources)
        _ensure_app_server_locked(*resources, codex_binary)


def terminate_managed_app_server(socket_path):
    with _managed_app_server_lifecycle(socket_path) as resources:
        _terminate_managed_app_server_locked(*resources)


def _terminate_managed_app_server_locked(database, key, socket_path):
    try:
        pid, _executable, record = _validate_managed_app_server_locked(
            database, key, socket_path)
    except RuntimeError as error:
        if str(error) != "managed app-server process is missing":
            raise
        record, value = _managed_record_locked(database, key, socket_path)
        if value["status"] != "active":
            raise RuntimeError("managed app-server receipt is absent")
        _cleanup_managed_app_server_locked(
            database, key, socket_path, record)
        return
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while process_group_is_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if process_group_is_alive(pid):
        os.killpg(pid, signal.SIGKILL)
    _cleanup_managed_app_server_locked(
        database, key, socket_path, record)


def cleanup_managed_app_server_paths(socket_path):
    with _managed_app_server_lifecycle(socket_path) as resources:
        database, key, canonical_socket = resources
        record, value = _managed_record_locked(
            database, key, canonical_socket)
        if value["status"] == "active":
            _cleanup_managed_app_server_locked(
                database, key, canonical_socket, record)
        else:
            canonical_socket.unlink(missing_ok=True)


def _cleanup_managed_app_server_locked(
    database, key, socket_path, expected_record
):
    with database.transaction() as tx:
        current = tx.get(APP_SERVER_NAMESPACE, key)
        if (
            current is None
            or current.revision != expected_record.revision
            or _decode_managed_record(current, socket_path)["status"] != "active"
        ):
            raise RuntimeError(
                "managed app-server receipt changed before cleanup")
        socket_path.unlink(missing_ok=True)
        tx.put(
            APP_SERVER_NAMESPACE,
            key,
            _canonical({
                "schema": 1,
                "status": "absent",
                "socket_path": str(socket_path),
            }),
            expected_revision=current.revision,
        )



def managed_app_server_pid_path(socket_path: Path) -> Path:
    """Worktree-local app-server process-group receipt 경로를 반환합니다.

    Args:
        socket_path: Managed app-server의 UNIX socket 경로입니다.

    Returns:
        같은 basename의 pid receipt 경로입니다.
    """
    return socket_path.with_suffix(".pid")


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _decode_managed_record(record, socket_path):
    try:
        value = json.loads(record.payload)
    except (TypeError, ValueError, UnicodeError) as error:
        raise RuntimeError("managed app-server receipt is invalid in SQLite") from error
    if not isinstance(value, dict):
        raise RuntimeError("managed app-server receipt is invalid in SQLite")
    status = value.get("status")
    required = (
        {"schema", "status", "socket_path"}
        if status == "absent"
        else {"schema", "status", "pid", "socket_path", "executable_path"}
    )
    allowed = required | {"legacy_digest"}
    if (
        not required <= set(value) <= allowed
        or value.get("schema") != 1
        or status not in {"active", "absent"}
        or value.get("socket_path") != str(socket_path)
        or ("legacy_digest" in value and (
            not isinstance(value["legacy_digest"], str)
            or len(value["legacy_digest"]) != 64
            or any(character not in "0123456789abcdef"
                   for character in value["legacy_digest"])
        ))
    ):
        raise RuntimeError("managed app-server receipt identity mismatch")
    if status == "active" and (
        not isinstance(value.get("pid"), int)
        or isinstance(value.get("pid"), bool)
        or value["pid"] <= 1
        or not isinstance(value.get("executable_path"), str)
        or not value["executable_path"].strip()
    ):
        raise RuntimeError("managed app-server receipt identity mismatch")
    return value


def _legacy_managed_record(data, socket_path):
    try:
        value = json.loads(data)
    except (TypeError, ValueError, UnicodeError) as error:
        raise RuntimeError("legacy managed app-server receipt is invalid") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"pid", "socket_path", "executable_path"}
        or not isinstance(value.get("pid"), int)
        or isinstance(value.get("pid"), bool)
        or value["pid"] <= 1
        or value.get("socket_path") != str(socket_path)
        or not isinstance(value.get("executable_path"), str)
        or not value["executable_path"].strip()
    ):
        raise RuntimeError("legacy managed app-server receipt identity mismatch")
    return {
        "schema": 1,
        "status": "active",
        "pid": value["pid"],
        "socket_path": str(socket_path),
        "executable_path": str(Path(value["executable_path"]).resolve()),
        "legacy_digest": hashlib.sha256(data).hexdigest(),
    }


@contextmanager
def _managed_app_server_lifecycle(socket_path):
    supplied = Path(socket_path).absolute()
    worktree = supplied.parent.parent.resolve()
    canonical_socket = worktree / ".monitor-pr/app-server.sock"
    if (
        supplied != canonical_socket
        or supplied.parent.is_symlink()
        or not worktree.is_dir()
    ):
        raise RuntimeError("managed app-server socket path is not canonical")
    locator = SessionLocator.from_worktree(worktree)
    supplied.parent.mkdir(parents=True, exist_ok=True)
    lock_path = supplied.parent / ".app-server.lifecycle.lock"
    if lock_path.is_symlink():
        raise RuntimeError("managed app-server lifecycle lock must not be a symlink")
    descriptor = os.open(
        lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield RuntimeDatabase(locator.control_root), str(worktree), canonical_socket


def _managed_record_locked(database, key, socket_path):
    legacy_path = managed_app_server_pid_path(socket_path)
    if legacy_path.is_symlink():
        raise RuntimeError(
            "legacy managed app-server receipt must not be a symlink")
    with database.transaction() as tx:
        record = tx.get(APP_SERVER_NAMESPACE, key)
    if record is None:
        if legacy_path.exists() and not legacy_path.is_file():
            raise RuntimeError(
                "legacy managed app-server receipt must be a regular file")
        data = legacy_path.read_bytes() if legacy_path.is_file() else None
        value = (
            {
                "schema": 1,
                "status": "absent",
                "socket_path": str(socket_path),
            }
            if data is None
            else _legacy_managed_record(data, socket_path)
        )
        with database.transaction() as tx:
            record = tx.put(
                APP_SERVER_NAMESPACE, key, _canonical(value),
                expected_revision=None)
    value = _decode_managed_record(record, socket_path)
    legacy_digest = value.get("legacy_digest")
    if legacy_digest is None:
        if legacy_path.exists():
            raise RuntimeError(
                "legacy managed app-server receipt reappeared after cutover")
        return record, value
    if legacy_path.exists():
        if (
            not legacy_path.is_file()
            or hashlib.sha256(legacy_path.read_bytes()).hexdigest()
            != legacy_digest
        ):
            raise RuntimeError(
                "legacy managed app-server receipt changed before removal")
        legacy_path.unlink()
    completed = dict(value)
    del completed["legacy_digest"]
    with database.transaction() as tx:
        current = tx.get(APP_SERVER_NAMESPACE, key)
        if current is None or current.revision != record.revision:
            raise RuntimeError(
                "managed app-server receipt changed during legacy cutover")
        record = tx.put(
            APP_SERVER_NAMESPACE, key, _canonical(completed),
            expected_revision=current.revision)
    return record, completed


def _write_managed_record_locked(
    database, key, socket_path, pid, codex_binary
):
    record, current = _managed_record_locked(database, key, socket_path)
    if current["status"] != "absent":
        raise RuntimeError("an active managed app-server receipt already exists")
    value = {
        "schema": 1,
        "status": "active",
        "pid": pid,
        "socket_path": str(socket_path),
        "executable_path": str(codex_binary.resolve()),
    }
    _decode_managed_record(
        StoredRecord(record.revision, _canonical(value)), socket_path)
    with database.transaction() as tx:
        return tx.put(
            APP_SERVER_NAMESPACE, key, _canonical(value),
            expected_revision=record.revision)


def _read_managed_identity_locked(database, key, socket_path):
    record, value = _managed_record_locked(database, key, socket_path)
    if value["status"] != "active":
        raise RuntimeError("managed app-server receipt is absent")
    return (
        int(value["pid"]),
        Path(str(value["executable_path"])).resolve(),
        record,
    )


def write_managed_app_server_receipt(socket_path, pid, codex_binary):
    with _managed_app_server_lifecycle(socket_path) as (
        database, key, canonical_socket
    ):
        _write_managed_record_locked(
            database, key, canonical_socket, pid, codex_binary)


def read_managed_app_server_identity(socket_path):
    with _managed_app_server_lifecycle(socket_path) as (
        database, key, canonical_socket
    ):
        pid, executable, _record = _read_managed_identity_locked(
            database, key, canonical_socket)
        return pid, executable


def managed_app_server_receipt_exists(socket_path):
    with _managed_app_server_lifecycle(socket_path) as (
        database, key, canonical_socket
    ):
        _record, value = _managed_record_locked(
            database, key, canonical_socket)
        return value["status"] == "active"















def managed_app_server_command_matches(
    pid: int,
    socket_path: Path,
    expected_executable: Path,
) -> bool:
    """PID가 receipt의 exact socket을 소유한 Codex app-server인지 검증합니다.

    Args:
        pid: 검증할 process group leader pid입니다.
        socket_path: Receipt에 결속된 UNIX socket 경로입니다.
        expected_executable: Receipt에 기록된 exact Codex executable입니다.

    Returns:
        Process command가 exact managed server identity이면 True입니다.
    """
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        arguments = shlex.split(result.stdout.strip())
    except ValueError:
        return False
    if result.returncode != 0 or len(arguments) != 4:
        return False
    executable, *command_arguments = arguments
    if command_arguments[:2] != ["app-server", "--listen"]:
        return False
    listen_target = command_arguments[2]
    if not listen_target.startswith("unix://"):
        return False
    command_socket = Path(listen_target.removeprefix("unix://")).resolve()
    return (
        Path(executable).resolve() == expected_executable.resolve()
        and command_socket == socket_path.resolve()
    )


def kernel_process_executable(pid: int) -> Path:
    """Kernel process metadata에서 spoof 불가능한 executable path를 읽습니다.

    Args:
        pid: Process group leader PID입니다.

    Returns:
        Kernel이 보고한 executable의 canonical path입니다.

    Raises:
        RuntimeError: 지원하지 않는 platform이거나 identity를 읽지 못할 때 발생합니다.
        OSError: Linux procfs executable link를 읽지 못할 때 발생합니다.
    """
    if sys.platform.startswith("linux"):
        return Path(os.readlink(f"/proc/{pid}/exe")).resolve()
    if sys.platform == "darwin":
        library_path = ctypes.util.find_library("proc")
        if library_path is None:
            raise RuntimeError("libproc is unavailable")
        libproc = ctypes.CDLL(library_path, use_errno=True)
        proc_pidpath = libproc.proc_pidpath
        proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        proc_pidpath.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(4096)
        if proc_pidpath(pid, buffer, len(buffer)) <= 0:
            raise RuntimeError("kernel executable identity is unavailable")
        return Path(os.fsdecode(buffer.value)).resolve()
    raise RuntimeError(f"unsupported process identity platform: {sys.platform}")


def process_owns_unix_socket(pid: int, socket_path: Path) -> bool:
    """Kernel file table에서 PID의 exact UNIX listener 소유권을 검증합니다.

    Args:
        pid: Process group leader PID입니다.
        socket_path: Receipt에 결속된 UNIX socket 경로입니다.

    Returns:
        PID가 exact socket을 열고 있으면 True입니다.
    """
    lsof = shutil.which("lsof")
    if lsof is None and Path("/usr/sbin/lsof").is_file():
        lsof = "/usr/sbin/lsof"
    if lsof is None:
        return False
    result = subprocess.run(
        [lsof, "-a", "-p", str(pid), "-U", "-Fn"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    expected = socket_path.resolve()
    return any(
        line.startswith("n") and Path(line[1:]).resolve() == expected
        for line in result.stdout.splitlines()
        if not line.startswith("n->")
    )


def process_group_is_alive(process_group_id: int) -> bool:
    """Process group member가 하나라도 남아 있는지 확인합니다.

    Args:
        process_group_id: 확인할 POSIX process group id입니다.

    Returns:
        Group member가 남아 있으면 True입니다.
    """
    result = subprocess.run(
        ["ps", "-axo", "pgid=,state="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        members: list[str] = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0] == str(process_group_id):
                members.append(fields[1])
        return any(not state.startswith("Z") for state in members)
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True





def socket_accepts_connections(socket_path: Path) -> bool:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        socket_path: socket_path 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            probe.connect(str(socket_path))
            return True
    except OSError:
        return False


def resolve_socket_path(args: argparse.Namespace) -> Path:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        args: args 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    socket_path = args.socket_path or str(default_socket_path(args.cwd))
    return Path(socket_path).expanduser()


def resume_thread(args: argparse.Namespace, prompt: str) -> dict[str, Any]:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        args: args 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        prompt: prompt 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    if worktree_has_owner_changes(Path(args.cwd)):
        return {
            "resume_status": "pending-delivery",
            "delivery_method": "owner-worktree-dirty",
            "response": {},
            "turn_completion": {
                "status": "deferred",
                "reason": "owner-worktree-dirty",
            },
        }
    expected_head_sha = getattr(args, "expected_head_sha", None)
    owner_head_state = worktree_owner_head_state(Path(args.cwd), expected_head_sha)
    if owner_head_state == "local-ahead":
        return {
            "resume_status": "pending-delivery",
            "delivery_method": "owner-local-head-ahead",
            "response": {"owner_head_state": owner_head_state},
            "turn_completion": {
                "status": "deferred",
                "reason": "owner-local-head-ahead",
            },
        }
    socket_path = resolve_socket_path(args)
    codex_binary = select_codex_binary()
    ensure_app_server(socket_path, codex_binary)
    with AppServerClient(socket_path) as client:
        resume_response = initialize_and_resume_thread(client, args)
        if (
            thread_is_active(resume_response)
            or not managed_app_server_receipt_exists(socket_path)
        ):
            return deliver_and_wait(client, args, prompt, resume_response)
    restart_managed_app_server(socket_path, codex_binary)
    with AppServerClient(socket_path) as client:
        resume_response = initialize_and_resume_thread(client, args)
        return deliver_and_wait(client, args, prompt, resume_response)


def worktree_has_owner_changes(worktree: Path) -> bool:
    """Tracked/untracked owner 변경이 남은 동안 monitor delivery를 보류합니다.

    Args:
        worktree: Process-ticket owner의 canonical worktree입니다.

    Returns:
        Git worktree에 commit되지 않은 변경이 있으면 True입니다.
    """
    resolved = worktree.resolve()
    if not (resolved / ".git").exists():
        return False
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-C", str(resolved), "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    return result.returncode != 0 or bool(result.stdout.strip())


def worktree_owner_head_state(worktree: Path, expected_head_sha: object) -> str:
    """GitHub event HEAD와 local owner HEAD의 publication 관계를 판정합니다.

    Clean worktree만 검사하면 commit 뒤 push 전 구간을 놓칩니다. Event commit이 local
    HEAD의 ancestor이거나 local branch가 configured upstream보다 앞서 있으면 owner가
    아직 publish하지 않은 continuation을 보유한 것으로 간주합니다.

    Args:
        worktree: Process-ticket owner의 canonical Git worktree입니다.
        expected_head_sha: Monitor event가 관찰한 exact PR head OID입니다.

    Returns:
        matching, local-ahead, local-behind, diverged, unverified 중 하나입니다.
    """
    if not isinstance(expected_head_sha, str) or not expected_head_sha:
        return "unverified"
    resolved = worktree.resolve()
    if not (resolved / ".git").exists():
        return "unverified"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        """Owner worktree의 ambient Git override 없이 read-only 명령을 실행합니다.

        Args:
            arguments: Git에 전달할 read-only argument입니다.

        Returns:
            Git process의 exit code와 출력을 담은 결과입니다.
        """
        return subprocess.run(
            ["git", "-C", str(resolved), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    local_result = git("rev-parse", "--verify", "HEAD")
    if local_result.returncode != 0:
        return "unverified"
    local_head = local_result.stdout.strip()
    if local_head == expected_head_sha:
        return "matching"

    expected_exists = git("cat-file", "-e", f"{expected_head_sha}^{{commit}}")
    if (
        expected_exists.returncode == 0
        and git("merge-base", "--is-ancestor", expected_head_sha, local_head).returncode == 0
    ):
        return "local-ahead"

    upstream_result = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream_result.returncode == 0:
        upstream = upstream_result.stdout.strip()
        ahead_result = git("rev-list", "--count", f"{upstream}..{local_head}")
        if ahead_result.returncode == 0:
            try:
                if int(ahead_result.stdout.strip()) > 0:
                    return "local-ahead"
            except ValueError:
                return "unverified"

    if expected_exists.returncode != 0:
        return "unverified"
    if git("merge-base", "--is-ancestor", local_head, expected_head_sha).returncode == 0:
        return "local-behind"
    return "diverged"


def resume_params(args: argparse.Namespace) -> dict[str, Any]:
    """Bound MCP automation preserves the native thread's current policy."""
    fields: dict[str, Any] = {"threadId": args.thread_id, "cwd": args.cwd}
    if not getattr(args, "preserve_native_policy", False):
        fields.update(approvalPolicy="never", sandbox="danger-full-access")
    return fields


def initialize_and_resume_thread(
    client: AppServerClient,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Client handshake 뒤 target thread의 live activity를 읽습니다.

    Args:
        client: 연결된 worktree-local app-server client입니다.
        args: Target thread와 worktree를 담은 CLI 인자입니다.

    Returns:
        `thread/resume` live response입니다.
    """
    client.request(
        "initialize",
        {
            "clientInfo": {"name": "neurath-pr-monitor", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True, "optOutNotificationMethods": []},
        },
    )
    client.notify("initialized", {})
    return client.request(
        "thread/resume",
        resume_params(args),
    )


def deliver_and_wait(
    client: AppServerClient,
    args: argparse.Namespace,
    prompt: str,
    resume_response: dict[str, Any],
) -> dict[str, Any]:
    """한 app-server client에서 단일 prompt delivery와 completion을 처리합니다.

    Args:
        client: 연결된 worktree-local app-server client입니다.
        args: Target thread, worktree, timeout CLI 인자입니다.
        prompt: 전달할 monitor event prompt입니다.
        resume_response: 직전 `thread/resume` live response입니다.

    Returns:
        Delivery method와 completion read-back을 담은 결과입니다.

    Raises:
        RuntimeError: 복구 대상 active turn identity가 delivery 직전에 달라졌을 때 발생합니다.
    """
    delivery_method, turn_response, turn_id = deliver_prompt(client, args, prompt, resume_response)
    if delivery_method == "active-turn-deferred":
        return {
            "resume_status": "pending-delivery",
            "delivery_method": delivery_method,
            "response": summarize_response(turn_response),
            "turn_completion": {
                "status": "deferred",
                "turnId": turn_id,
            },
        }
    turn_completion = wait_for_turn_completion(
        client,
        args,
        turn_id,
        timeout_seconds=getattr(args, "turn_timeout_seconds", 180),
    )
    result: dict[str, Any] = {
        "resume_status": "invoked",
        "delivery_method": delivery_method,
        "response": summarize_response(turn_response),
        "turn_completion": turn_completion,
    }
    return result


def deliver_prompt(
    client: AppServerClient,
    args: argparse.Namespace,
    prompt: str,
    resume_response: dict[str, Any],
) -> tuple[str, dict[str, Any], str]:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        client: client 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        args: args 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        prompt: prompt 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        resume_response: resume_response 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    if thread_is_active(resume_response):
        expected_turn_id = latest_active_turn_id(client, args)
        return (
            "active-turn-deferred",
            {"turnId": expected_turn_id},
            expected_turn_id,
        )
    try:
        response = client.request("turn/start", start_params(args, prompt))
        return "turn/start", response, extract_turn_id(response)
    except RuntimeError as exc:
        if "active" not in str(exc).lower():
            raise
        expected_turn_id = latest_active_turn_id(client, args)
        return (
            "active-turn-deferred",
            {"turnId": expected_turn_id},
            expected_turn_id,
        )


def extract_turn_id(response: dict[str, Any], fallback: str | None = None) -> str:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        response: response 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        fallback: fallback 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다.

    Raises:
        선언된 실패 조건에서 예외를 발생시킵니다."""
    turn = response.get("turn")
    if isinstance(turn, dict):
        turn_id = turn.get("id")
        if isinstance(turn_id, str) and turn_id:
            return turn_id
    turn_id = response.get("turnId")
    if isinstance(turn_id, str) and turn_id:
        return turn_id
    if fallback:
        return fallback
    raise RuntimeError("turn response did not include a turn id")


def wait_for_turn_completion(
    client: AppServerClient,
    args: argparse.Namespace,
    turn_id: str,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        client: client 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        args: args 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        turn_id: turn_id 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        timeout_seconds: timeout_seconds 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            listed_turn = turn_from_list(client, args, turn_id)
            if listed_turn is not None and turn_is_finished(listed_turn):
                return {
                    "status": "completed",
                    "turnId": turn_id,
                    "turn": summarize_response(listed_turn),
                }
            return {
                "status": "timeout",
                "turnId": turn_id,
                "timeout_seconds": timeout_seconds,
            }
        try:
            message = client.receive_message(min(30.0, remaining))
        except TimeoutError:
            listed_turn = turn_from_list(client, args, turn_id)
            if listed_turn is not None and turn_is_finished(listed_turn):
                return {
                    "status": "completed",
                    "turnId": turn_id,
                    "turn": summarize_response(listed_turn),
                }
            continue
        method = message.get("method")
        if method != "turn/completed":
            continue
        params = message.get("params", {})
        if not isinstance(params, dict):
            continue
        completed_turn = params.get("turn", {})
        completed_turn_id = params.get("turnId")
        if isinstance(completed_turn, dict):
            completed_turn_id = completed_turn.get("id", completed_turn_id)
        if completed_turn_id != turn_id:
            continue
        return {
            "status": "completed",
            "turnId": turn_id,
            "turn": summarize_response(completed_turn) if isinstance(completed_turn, dict) else {},
        }


def turn_from_list(
    client: AppServerClient,
    args: argparse.Namespace,
    turn_id: str,
) -> dict[str, Any] | None:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        client: client 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        args: args 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        turn_id: turn_id 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    try:
        response = client.request("thread/turns/list", {"threadId": args.thread_id, "limit": 10})
    except TURN_LIST_READ_ERRORS:
        return None
    data = response.get("data", [])
    if not isinstance(data, list):
        return None
    for turn in data:
        if isinstance(turn, dict) and turn.get("id") == turn_id:
            return turn
    return None


def turn_is_finished(turn: dict[str, Any]) -> bool:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        turn: turn 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    status = turn.get("status")
    return isinstance(status, str) and status not in {"inProgress", "pending", "queued"}


def latest_active_turn_id(client: AppServerClient, args: argparse.Namespace) -> str:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        client: client 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        args: args 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다.

    Raises:
        선언된 실패 조건에서 예외를 발생시킵니다."""
    response = client.request("thread/turns/list", {"threadId": args.thread_id, "limit": 5})
    data = response.get("data", [])
    if not isinstance(data, list):
        raise TypeError("thread/turns/list returned invalid data")
    for turn in data:
        if isinstance(turn, dict) and turn.get("status") == "inProgress":
            turn_id = turn.get("id")
            if isinstance(turn_id, str) and turn_id:
                return turn_id
    raise RuntimeError("active thread has no in-progress turn id")


def thread_is_active(response: dict[str, Any]) -> bool:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        response: response 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    thread = response.get("thread", {})
    if not isinstance(thread, dict):
        return False
    status = thread.get("status", {})
    return isinstance(status, dict) and status.get("type") == "active"


def start_params(args: argparse.Namespace, prompt: str) -> dict[str, Any]:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        args: args 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.
        prompt: prompt 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    fields: dict[str, Any] = {
        "threadId": args.thread_id,
        "cwd": args.cwd,
        "input": [{"type": "text", "text": prompt}],
    }
    if not getattr(args, "preserve_native_policy", False):
        fields.update(approvalPolicy="never", sandboxPolicy={"type": "dangerFullAccess"})
    return fields


def summarize_response(response: dict[str, Any]) -> dict[str, Any]:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        response: response 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    summarized = dict(response)
    thread = summarized.get("thread")
    if isinstance(thread, dict):
        summarized["thread"] = {
            "id": thread.get("id"),
            "status": thread.get("status"),
            "cliVersion": thread.get("cliVersion"),
            "path": thread.get("path"),
        }
    return summarized


def probe_thread(args: argparse.Namespace) -> dict[str, Any]:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Args:
        args: args 입력을 monitor resume 요청을 만들거나 monitor state를 갱신할 때 사용합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    socket_path = resolve_socket_path(args)
    ensure_app_server(socket_path, select_codex_binary())
    with AppServerClient(socket_path) as client:
        client.request(
            "initialize",
            {
                "clientInfo": {"name": "neurath-pr-monitor", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True, "optOutNotificationMethods": []},
            },
        )
        client.notify("initialized", {})
        response = client.request(
            "thread/resume",
            resume_params(args),
        )
    thread = response.get("thread", {})
    if isinstance(thread, dict):
        return {
            "thread": {
                "id": thread.get("id"),
                "status": thread.get("status"),
                "cliVersion": thread.get("cliVersion"),
                "path": thread.get("path"),
            }
        }
    return response


def inspect_turn(args: argparse.Namespace, turn_id: str) -> dict[str, Any]:
    """Prompt를 추가하지 않고 기존 monitor delivery turn 상태를 read-back합니다.

    Args:
        args: App-server socket, thread id, cwd를 담은 CLI 인자입니다.
        turn_id: Monitor가 마지막 delivery에서 받은 turn id입니다.

    Returns:
        Observed turn summary 또는 missing marker입니다.
    """
    socket_path = resolve_socket_path(args)
    ensure_app_server(socket_path, select_codex_binary())
    with AppServerClient(socket_path) as client:
        client.request(
            "initialize",
            {
                "clientInfo": {"name": "neurath-pr-monitor", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True, "optOutNotificationMethods": []},
            },
        )
        client.notify("initialized", {})
        client.request(
            "thread/resume",
            resume_params(args),
        )
        turn = turn_from_list(client, args, turn_id)
    return {
        "inspect_status": "observed" if turn is not None else "missing",
        "turnId": turn_id,
        "turn": summarize_response(turn) if turn is not None else {},
    }


def find_claimed_turn(
    args: argparse.Namespace,
    claim_id: str,
    event_id: str,
) -> dict[str, Any]:
    """Prompt 재전달 없이 exact claim marker를 가진 persisted turn을 찾습니다.

    Args:
        args: App-server thread와 socket 설정입니다.
        claim_id: 복구할 atomic mailbox claim identity입니다.
        event_id: 복구할 monitor event identity입니다.

    Returns:
        Found, absent, pending, ambiguous 중 하나의 recovery read-back입니다.
    """
    marker = monitor_delivery_marker(claim_id, event_id)
    socket_path = resolve_socket_path(args)
    ensure_app_server(socket_path, select_codex_binary())
    with AppServerClient(socket_path) as client:
        client.request(
            "initialize",
            {
                "clientInfo": {"name": "neurath-pr-monitor", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True, "optOutNotificationMethods": []},
            },
        )
        client.notify("initialized", {})
        resumed = client.request(
            "thread/resume",
            resume_params(args),
        )
        response = client.request(
            "thread/turns/list",
            {"threadId": args.thread_id, "limit": 20, "itemsView": "full"},
        )
    turns = response.get("data", [])
    if not isinstance(turns, list):
        return {"recovery_status": "unverified", "reason": "invalid-turn-list"}
    matched = [turn for turn in turns if isinstance(turn, dict) and _turn_has_marker(turn, marker)]
    thread = resumed.get("thread", {})
    thread_status = ""
    if isinstance(thread, dict):
        status = thread.get("status", {})
        if isinstance(status, dict) and isinstance(status.get("type"), str):
            thread_status = status["type"]
    if len(matched) == 1:
        turn = matched[0]
        return {
            "recovery_status": "found",
            "thread_status": thread_status,
            "turn": {"id": turn.get("id"), "status": turn.get("status")},
        }
    if len(matched) > 1:
        return {
            "recovery_status": "ambiguous",
            "thread_status": thread_status,
            "matching_turn_ids": [turn.get("id") for turn in matched],
        }
    return {
        "recovery_status": "absent" if thread_status == "idle" else "pending",
        "thread_status": thread_status,
    }


def _turn_has_marker(turn: dict[str, Any], marker: str) -> bool:
    """Full turn payload의 user message에 exact delivery marker가 있는지 확인합니다."""
    items = turn.get("items", [])
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "userMessage":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for value in content:
            if (
                isinstance(value, dict)
                and value.get("type") == "text"
                and marker in str(value.get("text", ""))
            ):
                return True
    return False


def main() -> int:
    """PR monitor resume 요청과 app-server 응답을 실제 Codex turn 상태로 변환합니다.

    Returns:
        monitor가 저장하거나 read-back할 resume 결과를 반환합니다."""
    application = AppServerResumeApplication()
    parser = application.parser()
    args = application.resolve(tuple(sys.argv[1:]), os.environ, Path.cwd())

    if args.terminate_managed_server:
        socket_path = resolve_socket_path(args)
        if managed_app_server_receipt_exists(socket_path):
            terminate_managed_app_server(socket_path)
            status = "terminated"
        else:
            status = "absent"
        print(json.dumps({"managed_app_server_status": status}, ensure_ascii=False))
        return 0

    if args.probe:
        try:
            response = probe_thread(args)
            status = "available"
        except (RuntimeError, OSError, TimeoutError, TypeError, json.JSONDecodeError) as exc:
            response = {"error": str(exc)[-2000:]}
            status = "failed"
        print(json.dumps({"probe_status": status, "response": response}, ensure_ascii=False))
        return 0

    if bool(args.find_claim_id) != bool(args.find_event_id):
        parser.error("--find-claim-id and --find-event-id must be provided together")
    if args.find_claim_id:
        try:
            response = find_claimed_turn(args, args.find_claim_id, args.find_event_id)
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            response = {"recovery_status": "failed", "error": str(exc)}
        print(json.dumps(response, ensure_ascii=False))
        return 0
    if args.inspect_turn_id:
        try:
            response = inspect_turn(args, args.inspect_turn_id)
        except (RuntimeError, OSError, TimeoutError, TypeError, json.JSONDecodeError) as exc:
            response = {
                "inspect_status": "failed",
                "turnId": args.inspect_turn_id,
                "response": {"error": str(exc)[-2000:]},
            }
        print(json.dumps(response, ensure_ascii=False))
        return 0

    prompt = sys.stdin.read()
    try:
        response = resume_thread(args, prompt)
    except (RuntimeError, OSError, TimeoutError, TypeError, json.JSONDecodeError) as exc:
        response = {"resume_status": "failed", "response": {"error": str(exc)[-2000:]}}
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
