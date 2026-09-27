"""WebSocket framing and JSON-RPC transport for the Codex app-server."""

import base64
import hashlib
import json
import os
import socket
import struct
from pathlib import Path
from typing import Any, Self


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


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
