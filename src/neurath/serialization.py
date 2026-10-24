"""외부 JSON 경계에서 내부 UUID 식별자의 문자열 표현을 제공한다."""

import base64
from uuid import UUID


def encode_uuid(value: object) -> str:
    """UUID만 정규 문자열로 표현하고 지원하지 않는 객체는 숨기지 않는다.

    Args:
        value: 기본 JSON 인코더가 처리할 수 없는 값.

    Returns:
        str: UUID의 정규 문자열.

    Raises:
        TypeError: UUID가 아닌 지원하지 않는 객체인 경우.
    """
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Cannot encode {type(value).__name__} as JSON")


def encode_historical(value: object) -> object:
    """과거 SQLite BLOB과 현재 UUID를 손실 없는 JSON 값으로 표현한다.

    Args:
        value: 기본 JSON 인코더가 직접 처리할 수 없는 값.

    Returns:
        object: 자료형 태그가 있는 BLOB 또는 UUID 문자열.
    """
    if isinstance(value, bytes):
        return {"sqlite_blob_base64": base64.b64encode(value).decode("ascii")}
    return encode_uuid(value)
