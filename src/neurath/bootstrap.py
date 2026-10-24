"""패키지 스캔과 공식 플러그인으로 애플리케이션을 구성하는 실행 진입점이다."""

import os
from pathlib import Path
from tempfile import gettempdir

from spakky.core.application.application import SpakkyApplication
from spakky.core.application.application_context import ApplicationContext
from spakky.plugins.sqlalchemy.common.constants import SPAKKY_SQLALCHEMY_CONFIG_ENV_PREFIX

from neurath.infrastructure.database import sqlite_url, user_database_path


def create_application() -> SpakkyApplication:
    """환경 설정으로 플러그인을 로드하고 실제 패키지에서 Pod·테이블·Controller를 찾는다.

    개별 구성요소 목록을 유지하지 않는다. SQLAlchemy의 공식 환경 설정을 사용하며,
    미설정 시 사용자 단위 SQLite와 비동기 드라이버를 기본으로 한다. 아직 DB에 연결하거나
    스키마를 이전하지 않으므로 파일이 없어도 CLI 도움말과 우회를 사용할 수 있다.
    Alembic 실행 파일과 이 구성 루트는 애플리케이션 구성요소 스캔에서 제외한다.

    Returns:
        SpakkyApplication: 호출자가 start·stop하는 스캔된 애플리케이션.
    """
    connection_key = f"{SPAKKY_SQLALCHEMY_CONFIG_ENV_PREFIX}CONNECTION_STRING"
    if connection_key not in os.environ:
        os.environ[connection_key] = sqlite_url(user_database_path(), "rw").render_as_string(
            hide_password=False
        )
    return (
        SpakkyApplication(ApplicationContext())
        .load_plugins()
        .scan(
            "neurath",
            exclude={
                "neurath.infrastructure.migrations",
                "neurath.bootstrap",
                "neurath.cli",
                "neurath.entrypoint",
            },
        )
    )


def start_cli_application(*, management: bool) -> SpakkyApplication:
    """관리 명령은 잘못된 업무 DB 설정과 독립적으로 공식 앱을 시작한다.

    플러그인·패키지 스캔은 동일하게 유지한다. 관리 명령은 업무 연결을 사용하지 않으므로
    생성 과정에만 연결하지 않는 읽기 전용 엔진 설정을 사용한다. 진단 전에 원 환경 값을 복원해
    실제 잘못된 설정을 관찰하며 사용자 파일이나 설정을 덮어쓰지 않는다.

    Args:
        management: DB에 의존하지 않는 maintenance 그룹 진입 여부.

    Returns:
        SpakkyApplication: 공식 플러그인과 스캔으로 시작한 앱.
    """
    if not management:
        return create_application().start()
    key = f"{SPAKKY_SQLALCHEMY_CONFIG_ENV_PREFIX}CONNECTION_STRING"
    configured = os.environ.get(key)
    os.environ[key] = sqlite_url(
        Path(gettempdir()) / "neurath-management-unopened.sqlite3", "ro"
    ).render_as_string(hide_password=False)
    try:
        return create_application().start()
    finally:
        if configured is None:
            del os.environ[key]
        else:
            os.environ[key] = configured
