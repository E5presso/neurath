"""기존 런타임 회귀 사례에서 실제 spakky-typer 명령을 호출한다."""

import asyncio
import json

from typer import Typer
from typer.testing import CliRunner

from neurath.domain.enums.provider_kind import ProviderKind
from neurath.infrastructure.database import sqlite_url
from neurath.transport.cli.hooks import HookCliController
from tests.support.application import request_application


class HookCliClient:
    def __init__(self, provider, database):
        self.provider = ProviderKind(provider).value
        self.database = database

    async def handle(self, payload, *, bypass=False):
        arguments = [
            "hook",
            "handle",
            "--provider",
            self.provider,
        ]
        if bypass:
            arguments.append("--bypass")
        async with request_application(sqlite_url(self.database, "rw")) as application:
            response = await asyncio.to_thread(
                CliRunner().invoke,
                application.container.get(Typer),
                arguments,
                input=json.dumps(payload),
            )
        assert response.exit_code == 0, response.output
        return json.loads(response.stdout)

    def decode(self, payload):
        return HookCliController.decode(self.provider, payload)
