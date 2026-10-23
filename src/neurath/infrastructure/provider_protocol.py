"""추론 요청 없이 설치된 Codex·Claude의 초기화·모델 조회 프로토콜을 읽는다."""

import json
import selectors
import subprocess
import time
from typing import cast


def discover_models(provider: str) -> tuple[str, ...]:
    """호스트 제어 프로토콜로 현재 지원 모델을 조회하고 프로세스를 정리한다.

    Args:
        provider: codex 또는 claude.

    Returns:
        tuple[str, ...]: 호스트가 실제 반환한 모델 ID.

    Raises:
        ValueError: 지원하지 않는 공급자인 경우.
        RuntimeError: 모델 목록이 없거나 초기화가 실패한 경우.
        TimeoutError: 제한 시간 안에 모델 목록을 받지 못한 경우.
    """
    if provider not in ("codex", "claude"):
        raise ValueError("Unsupported provider")
    args = (
        ["codex", "app-server"]
        if provider == "codex"
        else [
            "claude",
            "--safe-mode",
            "--print",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
    )
    initial: dict[str, object] = (
        {
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "neurath", "version": "0.3.1"}, "capabilities": {}},
        }
        if provider == "codex"
        else {"type": "control_request", "request_id": "1", "request": {"subtype": "initialize"}}
    )
    with subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write((json.dumps(initial) + "\n").encode())
        deadline = time.monotonic() + 30
        buffer = b""
        models: list[str] = []
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                while time.monotonic() < deadline:
                    if not selector.select(0.5):
                        continue
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        raise RuntimeError("Provider exited before model discovery")
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        data = cast(dict[str, object], json.loads(line))
                        if "error" in data:
                            raise RuntimeError(str(data["error"]))
                        if provider == "codex" and data.get("id") == 1:
                            process.stdin.write(
                                b'{"method":"initialized"}\n{"id":2,"method":"model/list","params":{"limit":100}}\n'
                            )
                        if provider == "codex" and data.get("id") == 2:
                            result = cast(dict[str, object], data["result"])
                            models.extend(
                                str(item["model"])
                                for item in cast(list[dict[str, object]], result["data"])
                            )
                            cursor = result.get("nextCursor")
                            if cursor:
                                process.stdin.write(
                                    (
                                        json.dumps(
                                            {
                                                "id": 2,
                                                "method": "model/list",
                                                "params": {"cursor": cursor, "limit": 100},
                                            }
                                        )
                                        + "\n"
                                    ).encode()
                                )
                                continue
                            if not models:
                                raise RuntimeError("Provider returned no models")
                            return tuple(dict.fromkeys(models))
                        if provider == "claude" and data.get("type") == "control_response":
                            response = cast(dict[str, object], data["response"])
                            if response.get("subtype") != "success":
                                raise RuntimeError(str(response))
                            result = cast(dict[str, object], response["response"])
                            models.extend(
                                str(item.get("resolvedModel", item["value"]))
                                for item in cast(list[dict[str, object]], result["models"])
                            )
                            if not models:
                                raise RuntimeError("Provider returned no models")
                            return tuple(dict.fromkeys(models))
                raise TimeoutError("Provider model discovery timed out")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
