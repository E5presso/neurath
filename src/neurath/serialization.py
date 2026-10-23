"""외부 JSON 경계에서 내부 UUID 식별자의 문자열 표현을 제공한다."""

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
