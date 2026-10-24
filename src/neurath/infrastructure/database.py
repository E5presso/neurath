"""SQLite 엔진 설정과 명시적인 Alembic 초기화를 제공한다."""

import os
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect
from sqlalchemy.engine import URL, Connection, Engine, ExceptionContext
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

from neurath.domain.errors import RevisionConflict, StorageNotReady


def user_database_path() -> Path:
    """XDG_DATA_HOME 또는 사용자 홈 아래의 neurath/core.sqlite3 경로를 반환한다.

    Returns:
        Path: XDG_DATA_HOME/neurath/core.sqlite3. 미설정·빈 값이면 ~/.local/share 아래 경로.

    Raises:
        ValueError: 홈 기호를 확장한 XDG_DATA_HOME이 절대 경로가 아닌 경우.
    """
    configured = os.environ.get("XDG_DATA_HOME")
    data_home = Path(configured).expanduser() if configured else Path.home() / ".local" / "share"
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be absolute")
    return data_home / "neurath" / "core.sqlite3"


def create_database_engine(
    path: Path | None = None,
    *,
    write: bool,
    create: bool = False,
    timeout: float = 5.0,
    migration: bool = False,
) -> AsyncEngine:
    """읽기·쓰기 정책이 연결된 NullPool SQLite 엔진을 생성한다.

    초기화용 엔진을 구성하며 스키마 호환성 검사는 여기서 활성화하지 않는다.
    호출자는 트랜잭션을 열고 정상·실패 경로 모두에서 엔진을 dispose해야 한다.

    Args:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.
        write: 연결에서 데이터 변경을 허용할지 여부.
        create: 명시적 초기화 과정에서 데이터베이스 파일을 생성할지 여부.
        timeout: SQLite가 데이터베이스 잠금을 기다리는 시간(초).
        migration: 명시적 스키마 이전 연결에서만 외래 키 검사를 Alembic의 전후 검사로 맡긴다.

    Returns:
        AsyncEngine: 사용 후 호출자가 await dispose로 정리할 비동기 엔진.
    """
    engine = create_async_engine(
        database_url(path, write=write, create=create),
        poolclass=NullPool,
        connect_args={"timeout": timeout},
    )
    configure_sqlite_engine(engine.sync_engine, write=write, migration=migration)
    return engine


def database_url(path: Path | None = None, *, write: bool, create: bool = False) -> URL:
    """파일 경로를 이스케이프하고 rwc·rw·ro 접근 모드를 지정한 SQLite URI를 만든다.

    Args:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.
        write: 쓰기 연결을 허용할지 여부.
        create: 명시적 초기화에서만 파일을 생성할지 여부.

    Returns:
        URL: 파일 경로의 특수 문자를 인코딩한 SQLite 연결 주소.

    Raises:
        StorageNotReady: create=False인 요청의 경로에 DB 파일이 없는 경우. 스키마는 검사하지 않는다.
    """
    path = (path if path is not None else user_database_path()).expanduser().resolve()
    if not create and not path.is_file():
        raise StorageNotReady("Database is missing; initialize it explicitly")
    mode = "rwc" if create else ("rw" if write else "ro")
    return sqlite_url(path, mode)


def sqlite_url(path: Path, mode: str) -> URL:
    """파일을 열지 않고 SQLite 연결 URI만 구성한다.

    Args:
        path: 연결할 SQLite 파일 경로.
        mode: SQLite의 rw·ro·rwc 연결 모드.

    Returns:
        URL: 파일 생성이나 연결을 수행하지 않은 접속 주소.
    """
    path = path.expanduser().resolve()
    return URL.create(
        "sqlite+aiosqlite",
        database="file:" + quote(str(path), safe="/"),
        query={"mode": mode, "uri": "true"},
    )


def configure_sqlite_engine(
    engine: Engine, *, write: bool, check_schema: bool = False, migration: bool = False
) -> None:
    """외래 키·읽기 전용 설정과 트랜잭션 시작 이벤트를 엔진에 등록한다.

    조회 시 쓰기 잠금을 예약하지 않고 변경 시 SQLite의 트랜잭션을 사용한다. 읽기는
    BEGIN과 query_only를 사용한다. check_schema=True이면 시작한 트랜잭션에서
    현재 패키지의 Alembic head와 저장된 revision을 대조한다.

    Args:
        engine: 프레임워크 또는 마이그레이션이 생성한 엔진.
        write: 데이터 변경을 허용할지 여부.
        check_schema: 일반 요청의 트랜잭션에서 Alembic 스키마를 검사할지 여부.
        migration: SQLite 테이블 재생성을 위해 트랜잭션 시작 전에 외래 키 집행을 해제한다.
    """

    def configure(connection: DBAPIConnection, record: ConnectionPoolEntry) -> None:
        """일반 요청에 외래 키 제약을 적용하고 이전 연결은 Alembic 검증을 사용한다.

        Args:
            connection: SQLite 트랜잭션 동작을 설정할 연결.
            record: SQLAlchemy 연결 이벤트가 전달한 풀 항목.
        """
        engine.dialect.set_isolation_level(connection, "AUTOCOMMIT")
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=OFF" if migration else "PRAGMA foreign_keys=ON")
            if not write:
                cursor.execute("PRAGMA query_only=ON")
        finally:
            cursor.close()

    def begin(connection: Connection) -> None:
        """일반 요청은 지연 시작하고 명시적 스키마 이전만 쓰기 예약 후 실행한다.

        Args:
            connection: SQLite 트랜잭션 동작을 설정할 연결.
        """
        connection.exec_driver_sql("BEGIN IMMEDIATE" if migration else "BEGIN")
        if check_schema:
            verify_schema(connection)

    def conflict(context: ExceptionContext) -> Exception | None:
        """SQLite의 쓰기 경합을 현재 원장을 다시 읽어야 하는 충돌로 표현한다.

        Args:
            context: SQLAlchemy가 관찰한 원 드라이버 오류.

        Returns:
            Exception | None: 재조회가 필요한 충돌이며 다른 오류는 원래대로 전파한다.
        """
        code = getattr(context.original_exception, "sqlite_errorcode", None)
        if isinstance(code, int) and code & 255 in (5, 6):
            return RevisionConflict(
                "Concurrent SQLite update; reread current state and repeat this request"
            )
        return None

    event.listen(engine, "handle_error", conflict, retval=True)
    event.listen(engine, "connect", configure)
    event.listen(engine, "begin", begin)


async def initialize_database(path: Path | None = None) -> None:
    """비어 있거나 Neurath revision 표를 가진 DB에 배포된 Alembic head를 적용한다.

    부모 디렉터리와 DB 파일을 필요하면 생성하고 DDL·자료·revision을 한
    트랜잭션으로 이전한다. 실패 시 롤백하고 엔진을 정리한다. 과거 하네스 DB를
    현재 도메인 모델로 변환하는 자료 이전 기능은 아니다. 기존 DB가 현재 저장소로
    식별되지 않으면 run_sync 경계에서 발생한 StorageNotReady를 전파한다.

    Args:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.

    """
    path = (path if path is not None else user_database_path()).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(path, write=True, create=True, migration=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_upgrade_store)
    finally:
        await engine.dispose()


def _upgrade_store(connection: Connection) -> None:
    """비동기 연결의 run_sync 경계에서 Alembic의 동기 API를 실행한다.

    Args:
        connection: aiosqlite 드라이버에 연결된 SQLAlchemy의 동기 API 어댑터.

    Raises:
        StorageNotReady: 기존 DB가 현재 스키마의 저장소로 식별되지 않은 경우.
    """
    tables = set(inspect(connection).get_table_names())
    if tables and "core_schema_revision" not in tables:
        raise StorageNotReady("Existing database is not a current store; migration required")
    config = Config()
    config.set_main_option("script_location", "neurath.infrastructure:migrations")
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def verify_schema(connection: Connection) -> None:
    """요청 중 마이그레이션을 실행하지 않고 없거나 호환되지 않는 스키마를 거부한다.

    Args:
        connection: 현재 요청의 SQLAlchemy 연결.

    Raises:
        StorageNotReady: core_schema_revision 표가 없거나 DB의 heads가 배포된 migration heads와 다른 경우.
    """
    if not inspect(connection).has_table("core_schema_revision"):
        raise StorageNotReady("Schema missing; initialize or migrate explicitly")
    config = Config()
    config.set_main_option("script_location", "neurath.infrastructure:migrations")
    current_heads = MigrationContext.configure(
        connection, opts={"version_table": "core_schema_revision"}
    ).get_current_heads()
    expected_heads = ScriptDirectory.from_config(config).get_heads()
    if set(current_heads) != set(expected_heads):
        raise StorageNotReady("Schema version differs; use matching package or migrate")
