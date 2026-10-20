"""SQLite 엔진 설정과 명시적인 Alembic 초기화를 제공한다."""

import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

from neurath.domain.errors import StorageNotReady

SCHEMA_REVISION = "core_0003"


def user_database_path() -> Path:
    """현재 디렉터리와 독립적인 사용자 단위 데이터베이스 경로를 결정한다.

    Returns:
        Path: 작업 디렉터리와 독립적인 사용자 단위 코어 데이터베이스 경로.

    Raises:
        ValueError: 입력 경로·식별자·디렉터리가 작업에 적합하지 않은 경우.
    """
    configured = os.environ.get("XDG_DATA_HOME")
    data_home = Path(configured).expanduser() if configured else Path.home() / ".local" / "share"
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be absolute")
    return data_home / "neurath" / "core.sqlite3"


def create_database_engine(
    path: Path | None = None, *, write: bool, create: bool = False, timeout: float = 5.0
) -> Engine:
    """풀 없는 엔진을 생성하며 호출자가 Session.begin과 엔진 정리를 소유한다.

    Args:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.
        write: 쓰기를 허용하고 읽기 전에 쓰기 권한을 예약할지 여부.
        create: 명시적 초기화 과정에서 데이터베이스 파일을 생성할지 여부.
        timeout: SQLite가 데이터베이스 잠금을 기다리는 시간(초).

    Returns:
        Engine: 사용 후 호출자가 정리해야 하는 풀 없는 엔진.

    """
    engine = create_engine(
        database_url(path, write=write, create=create),
        poolclass=NullPool,
        connect_args={"timeout": timeout},
    )
    configure_sqlite_engine(engine, write=write)
    return engine


def database_url(path: Path | None = None, *, write: bool, create: bool = False) -> URL:
    """파일의 존재와 접근 모드를 보존하는 SQLite URI를 만든다.

    Args:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.
        write: 쓰기 연결을 허용할지 여부.
        create: 명시적 초기화에서만 파일을 생성할지 여부.

    Returns:
        URL: 파일 경로의 특수 문자를 인코딩한 SQLite 연결 주소.

    Raises:
        StorageNotReady: 초기화되지 않은 데이터베이스를 일반 요청에서 지정한 경우.
    """
    path = (path if path is not None else user_database_path()).expanduser().resolve()
    if not create and not path.is_file():
        raise StorageNotReady("Database is missing; initialize it explicitly")
    mode = "rwc" if create else ("rw" if write else "ro")
    return URL.create(
        "sqlite+pysqlite",
        database="file:" + quote(str(path), safe="/"),
        query={"mode": mode, "uri": "true"},
    )


def configure_sqlite_engine(engine: Engine, *, write: bool) -> None:
    """주어진 엔진의 모든 SQLite 연결에 무결성과 트랜잭션 정책을 적용한다.

    Args:
        engine: 프레임워크 또는 마이그레이션이 생성한 엔진.
        write: 상태 조회 전에 쓰기 권한을 예약할지 여부.
    """

    def configure(connection: sqlite3.Connection, record: ConnectionPoolEntry) -> None:
        """SQLAlchemy가 트랜잭션을 시작하게 하고 모든 연결에 외래 키 제약을 적용한다.

        Args:
            connection: SQLite 트랜잭션 동작을 설정할 연결.
            record: SQLAlchemy 연결 이벤트가 전달한 풀 항목.
        """
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")
        if not write:
            connection.execute("PRAGMA query_only=ON")

    def begin(connection: Connection) -> None:
        """조회·수정·저장 작업 전에 쓰기 권한을 예약한다.

        Args:
            connection: SQLite 트랜잭션 동작을 설정할 연결.
        """
        connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")

    event.listen(engine, "connect", configure)
    event.listen(engine, "begin", begin)


def initialize_database(path: Path | None = None) -> None:
    """기존 데이터베이스를 재해석하지 않고 알려진 리비전만 명시적으로 적용한다.

    Args:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.

    Raises:
        StorageNotReady: 데이터베이스가 없거나 초기화되지 않았거나 패키지와 호환되지 않는 경우.
    """
    path = (path if path is not None else user_database_path()).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(path, write=True, create=True)
    try:
        with engine.begin() as connection:
            tables = set(inspect(connection).get_table_names())
            if tables and "core_schema_revision" not in tables:
                raise StorageNotReady(
                    "Existing database is not a current store; migration required"
                )
            config = Config()
            config.set_main_option("script_location", "neurath.infrastructure:migrations")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def verify_schema(session: Session) -> None:
    """요청 중 마이그레이션을 실행하지 않고 없거나 호환되지 않는 스키마를 거부한다.

    Args:
        session: 현재 요청의 SQLAlchemy 세션.

    Raises:
        StorageNotReady: 데이터베이스가 없거나 초기화되지 않았거나 패키지와 호환되지 않는 경우.
    """
    if not inspect(session.connection()).has_table("core_schema_revision"):
        raise StorageNotReady("Schema missing; initialize or migrate explicitly")
    versions = session.scalars(text("SELECT version_num FROM core_schema_revision")).all()
    if versions != [SCHEMA_REVISION]:
        raise StorageNotReady("Schema version differs; use matching package or migrate")
