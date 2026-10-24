"""공식 Typer 구성대로 스캔한 CLI 앱을 모듈 진입점으로 노출한다."""

import atexit
import sys

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from typer import Typer

from neurath.bootstrap import start_cli_application
from neurath.infrastructure.database import configure_sqlite_engine

application = start_cli_application(management=sys.argv[1:2] == ["maintenance"])
atexit.register(application.stop)
connection = application.container.get(AsyncConnectionManager)
configure_sqlite_engine(connection.connection.sync_engine, write=True, check_schema=True)
cli: Typer = application.container.get(Typer)
