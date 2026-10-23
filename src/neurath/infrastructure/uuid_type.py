"""기존 SQLite UUID 문자열을 보존하면서 도메인에는 UUID 값으로 반환한다."""

from typing import override
from uuid import UUID

from sqlalchemy import String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UUIDText(TypeDecorator[UUID]):
    """기존 기본 키·외래 키 표현을 변경하지 않는 UUID 저장 타입이다.

    SQLite의 문자열 키도 uuid7의 시간 순서를 그대로 정렬한다. 이미 저장한 uuid4
    식별자와 참조는 다시 발급하거나 데이터 이전 없이 그대로 읽는다.

    Attributes:
        impl: 기존 테이블과 같은 문자열 저장 형식.
        cache_ok: 인스턴스별 설정이 없으므로 SQL 문장 캐시를 사용할 수 있다.
    """

    impl = String
    cache_ok = True

    @override
    def process_bind_param(self, value: UUID | None, dialect: Dialect) -> str | None:
        """내부 UUID를 기존 DB의 정규 문자열로 바인딩한다.

        Args:
            value: 저장·조회에 사용하는 UUID 또는 NULL.
            dialect: SQLAlchemy가 전달하는 DB 방언.

        Returns:
            str | None: 기존 키 표현과 같은 UUID 문자열 또는 NULL.
        """
        return None if value is None else str(value)

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> UUID | None:
        """과거·신규 UUID 키를 같은 타입으로 복원한다.

        Args:
            value: DB에 보존한 UUID 문자열 또는 NULL.
            dialect: SQLAlchemy가 전달하는 DB 방언.

        Returns:
            UUID | None: 버전과 값이 유지된 UUID 또는 NULL.
        """
        return None if value is None else UUID(value)
