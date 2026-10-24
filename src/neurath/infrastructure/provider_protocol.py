"""추론 없이 모델을 조회하는 호스트 제어 메시지와 프로세스 수명을 처리한다."""

import json
import selectors
import subprocess
import time
from collections.abc import Generator
from contextlib import closing
from typing import cast

from spakky.core.common.mutability import immutable

from neurath.domain.enums.provider_kind import ProviderKind


@immutable
class ModelPage:
    """한 제어 응답에서 얻은 모델과 다음 페이지 위치다.

    Attributes:
        models: 응답이 실제 반환한 모델 ID.
        cursor: 다음 페이지가 있을 때의 원 서버 커서.
    """

    models: tuple[str, ...]
    cursor: str | None = None


def discover_models(provider: ProviderKind) -> tuple[str, ...]:
    """모델 조회 전용 프로세스를 열고 성공·실패 모두에서 정리한다.

    Args:
        provider: 지원하는 설치 공급자.

    Returns:
        tuple[str, ...]: 실제 호스트가 반환한 모델 ID.
    """
    kind = ProviderKind(provider)
    with subprocess.Popen(
        _discovery_arguments(kind),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    ) as process:
        try:
            _send(process, _initial_request(kind))
            return _read_catalog(process, kind)
        finally:
            _stop_process(process)


def _discovery_arguments(provider: ProviderKind) -> list[str]:
    """사용자 훅을 실행하지 않는 공급자별 조회 명령을 선택한다.

    Args:
        provider: 확인한 공급자 종류.

    Returns:
        list[str]: 추론 프롬프트가 없는 CLI 인자.

    Raises:
        ValueError: 지원하지 않는 공급자 값이 전달된 경우.
    """
    match provider:
        case ProviderKind.CODEX:
            return ["codex", "app-server"]
        case ProviderKind.CLAUDE:
            return [
                "claude",
                "--safe-mode",
                "--print",
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--verbose",
            ]
        case _:
            raise ValueError("Unsupported provider")


def _initial_request(provider: ProviderKind) -> dict[str, object]:
    """공급자의 제어 프로토콜 초기화 요청을 만든다.

    Args:
        provider: 확인한 공급자 종류.

    Returns:
        dict[str, object]: 모델 턴을 만들지 않는 초기화 메시지.

    Raises:
        ValueError: 지원하지 않는 공급자 값이 전달된 경우.
    """
    match provider:
        case ProviderKind.CODEX:
            return {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "neurath", "version": "0.3.1"},
                    "capabilities": {},
                },
            }
        case ProviderKind.CLAUDE:
            return {
                "type": "control_request",
                "request_id": "1",
                "request": {"subtype": "initialize"},
            }
        case _:
            raise ValueError("Unsupported provider")


def _send(process: subprocess.Popen[bytes], request: dict[str, object]) -> None:
    """완전한 JSON 메시지 하나를 호스트 표준입력에 쓴다.

    Args:
        process: 표준입력 파이프를 가진 조회 프로세스.
        request: 보낼 제어 메시지.
    """
    assert process.stdin is not None
    process.stdin.write((json.dumps(request) + "\n").encode())


def _read_messages(process: subprocess.Popen[bytes]) -> Generator[dict[str, object]]:
    """부분 수신을 줄 단위로 합치며 하나의 제한 시간 안에서만 응답을 읽는다.

    Args:
        process: 표준출력 파이프를 가진 조회 프로세스.

    Yields:
        dict[str, object]: 완전히 수신한 호스트 메시지.

    Raises:
        RuntimeError: 모델 조회 전에 호스트가 종료한 경우.
        TimeoutError: 제한 시간 안에 모델 목록을 받지 못한 경우.
    """
    assert process.stdout is not None
    deadline = time.monotonic() + 30
    buffer = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            if not selector.select(0.5):
                continue
            chunk = process.stdout.read(65536)
            if not chunk:
                raise RuntimeError("Provider exited before model discovery")
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                yield cast(dict[str, object], json.loads(line))
        raise TimeoutError("Provider model discovery timed out")


def _read_catalog(process: subprocess.Popen[bytes], provider: ProviderKind) -> tuple[str, ...]:
    """초기화·페이지 이동을 처리하고 마지막 모델 페이지에서 조회를 마친다.

    Args:
        process: 열린 조회 프로세스.
        provider: 응답 해석 규격.

    Returns:
        tuple[str, ...]: 중복을 제거한 실제 모델 목록.

    Raises:
        RuntimeError: 호스트가 오류를 반환하거나 모델 목록이 빈 경우.
    """
    models: list[str] = []
    with closing(_read_messages(process)) as messages:
        while True:
            message = next(messages)
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            if provider is ProviderKind.CODEX and message.get("id") == 1:
                _send(process, {"method": "initialized"})
                _request_codex_page(process, None)
                continue
            page = _parse_page(provider, message)
            if page is None:
                continue
            models.extend(page.models)
            if page.cursor is not None:
                _request_codex_page(process, page.cursor)
                continue
            if not models:
                raise RuntimeError("Provider returned no models")
            return tuple(dict.fromkeys(models))


def _request_codex_page(process: subprocess.Popen[bytes], cursor: str | None) -> None:
    """같은 모델 조회 요청의 다음 페이지만 요청한다.

    Args:
        process: 초기화한 Codex 제어 프로세스.
        cursor: 원 서버가 반환한 커서이며 최초 페이지면 None.
    """
    _send(process, {"id": 2, "method": "model/list", "params": {"cursor": cursor, "limit": 100}})


def _parse_page(provider: ProviderKind, message: dict[str, object]) -> ModelPage | None:
    """조회 결과만 모델 페이지로 읽고 무관한 알림은 건너뛴다.

    Args:
        provider: 공급자별 제어 응답 규격.
        message: 완전히 수신한 메시지.

    Returns:
        ModelPage | None: 모델 조회 응답 또는 무관한 알림의 None.

    Raises:
        ValueError: 지원하지 않는 공급자 값이 전달된 경우.
        RuntimeError: Claude 초기화가 실패한 경우.
    """
    match provider:
        case ProviderKind.CODEX:
            if message.get("id") != 2:
                return None
            result = cast(dict[str, object], message["result"])
            entries = cast(list[dict[str, object]], result["data"])
            return ModelPage(
                models=tuple(str(entry["model"]) for entry in entries),
                cursor=cast(str | None, result.get("nextCursor")),
            )
        case ProviderKind.CLAUDE:
            if message.get("type") != "control_response":
                return None
            response = cast(dict[str, object], message["response"])
            if response.get("subtype") != "success":
                raise RuntimeError(str(response))
            result = cast(dict[str, object], response["response"])
            entries = cast(list[dict[str, object]], result["models"])
            return ModelPage(
                models=tuple(str(entry.get("resolvedModel", entry["value"])) for entry in entries)
            )
        case _:
            raise ValueError("Unsupported provider")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """정상 종료 요청에 응답하지 않는 조회 프로세스도 제한 시간 후 정리한다.

    Args:
        process: 이 조회에서 만든 프로세스.
    """
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
