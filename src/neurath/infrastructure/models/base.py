"""이 패키지의 영속 레코드가 공유하는 선언적 메타데이터다."""

from sqlalchemy.orm import DeclarativeBase


class DatabaseModel(DeclarativeBase):
    """타입을 명시한 ORM 매핑의 기반이며 스키마 생성은 Alembic만 관리한다."""
