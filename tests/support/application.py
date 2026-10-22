"""운영과 같은 패키지 스캔을 사용하되 테스트별 DB 설정과 앱 수명을 격리한다."""

import os
from contextlib import asynccontextmanager
from threading import RLock
from unittest.mock import patch

from spakky.plugins.sqlalchemy.common.constants import SPAKKY_SQLALCHEMY_CONFIG_ENV_PREFIX
from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager

from neurath.bootstrap import create_application
from neurath.infrastructure.database import configure_sqlite_engine, database_url

_configuration_lock = RLock()


@asynccontextmanager
async def scanned_application(url, *, write=True):
    # 각 테스트 앱의 설정 생성만 직렬화한다. 실제 DB 동작·경합은 잠금 밖에서 실행한다.
    environment = {
        f"{SPAKKY_SQLALCHEMY_CONFIG_ENV_PREFIX}CONNECTION_STRING": url.render_as_string(
            hide_password=False
        ),
        "SPAKKY_DATA__SUPPORT_ASYNC_MODE": "true",
    }
    with _configuration_lock, patch.dict(os.environ, environment):
        application = create_application()
        manager = application.container.get(AsyncConnectionManager)
        try:
            configure_sqlite_engine(manager.connection.sync_engine, write=write, check_schema=True)
            application.start()
        except BaseException:
            await manager.dispose()
            raise
    try:
        yield application
    finally:
        try:
            application.stop()
        finally:
            await manager.dispose()


@asynccontextmanager
async def spakky_context(path=None, *, write=True):
    async with scanned_application(database_url(path, write=write), write=write) as application:
        yield application.container
