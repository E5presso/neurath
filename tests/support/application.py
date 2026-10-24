"""운영과 같은 패키지 스캔을 사용하되 테스트별 DB 설정과 앱 수명을 격리한다."""

import os
from asyncio import AbstractEventLoop, Lock, get_running_loop
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock
from unittest.mock import patch

from spakky.core.application.application import SpakkyApplication
from spakky.plugins.sqlalchemy.common.constants import SPAKKY_SQLALCHEMY_CONFIG_ENV_PREFIX
from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from sqlalchemy.engine import URL

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


# 앱은 한 시험의 같은 이벤트 루프·DB·읽기 정책 안에서만 재사용한다.
# 동시·중첩 호출, 별도 루프·프로세스, 명시적 spakky_context는 새 앱 경로다.
# 각 유스케이스의 트랜잭션·세션 정리는 프레임워크가 기존과 동일하게 수행한다.


@dataclass
class RequestApplications:
    """한 시험의 순차 요청에만 공유하고 종료 시 모두 닫는 실제 앱 묶음이다."""

    stack: AsyncExitStack
    loop: AbstractEventLoop
    applications: dict[tuple[URL, bool], SpakkyApplication] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)
    active_requests: set[tuple[URL, bool]] = field(default_factory=set)


_request_applications: ContextVar[RequestApplications | None] = ContextVar(
    "test_request_applications", default=None
)


@asynccontextmanager
async def request_application_lifetime():
    """시험별 앱 수명을 관리하고 성공·실패 모두에서 stop과 dispose를 수행한다."""
    async with AsyncExitStack() as stack:
        applications = RequestApplications(stack=stack, loop=get_running_loop())
        token = _request_applications.set(applications)
        try:
            yield applications
        finally:
            _request_applications.reset(token)


@asynccontextmanager
async def request_application(url, *, write=True):
    """같은 루프·DB·읽기 정책의 순차 호출만 공유하며 겹치는 호출은 새 앱을 쓴다."""
    applications = _request_applications.get()
    if applications is None or applications.loop is not get_running_loop():
        async with scanned_application(url, write=write) as application:
            yield application
        return
    key = (url, write)
    async with applications.lock:
        if key not in applications.applications:
            applications.applications[key] = await applications.stack.enter_async_context(
                scanned_application(url, write=write)
            )
        application = applications.applications[key]
    if key in applications.active_requests:
        async with scanned_application(url, write=write) as nested:
            yield nested
        return
    applications.active_requests.add(key)
    try:
        yield application
    finally:
        applications.active_requests.remove(key)


@asynccontextmanager
async def request_context(path=None, *, write=True):
    """일반 유스케이스 시험의 앱 구성을 공유하고 각 run의 실제 트랜잭션을 유지한다."""
    async with request_application(database_url(path, write=write), write=write) as application:
        yield application.container
