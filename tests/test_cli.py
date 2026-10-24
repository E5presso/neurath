"""실제 패키지 스캔·플러그인·콘솔 입출력과 프레임워크 수명을 검증한다."""

import asyncio
import atexit
import io
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from click import unstyle
from spakky.core.application.application import SpakkyApplication
from spakky.core.application.application_context import ApplicationContext
from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, TyperCommand
from sqlalchemy import text
from typer import Typer
from typer.testing import CliRunner

from neurath.application.ports.services.directory_observer import IDirectoryObserverService
from neurath.application.usecases.receive_hook import ReceiveHookUseCase
from neurath.domain.errors import NeurathError
from neurath.infrastructure.database import initialize_database, sqlite_url
from neurath.infrastructure.services.directory_observer import GitDirectoryObserverService
from neurath.transport.cli.hooks import HookCliController
from tests.conftest import storage_scope
from tests.support.application import scanned_application


async def invoke(database, arguments, payload=""):
    async with scanned_application(sqlite_url(database, "rw")) as app:
        return await asyncio.to_thread(
            CliRunner().invoke, app.container.get(Typer), arguments, input=payload
        )


async def test_real_spakky_controller_and_command_registration(tmp_path):
    assert CliController.exists(HookCliController)
    assert CliController.get(HookCliController).group_name == "hook"
    assert TyperCommand.get(HookCliController.handle).name == "handle"
    response = await invoke(tmp_path / "missing", ["hook", "handle", "--help"])
    assert response.exit_code == 0
    for option in ("--provider", "--bypass"):
        assert option in unstyle(response.stdout)


@pytest.mark.parametrize("payload", ["", "{broken", "[]", "null", "42"])
async def test_malformed_stdin_yields_json_without_opening_database(tmp_path, payload):
    missing = tmp_path / "missing"
    response = await invoke(missing, ["hook", "handle", "--provider", "codex"], payload)
    assert response.exit_code == 0
    assert "host tools remain available" in json.loads(response.stdout)["systemMessage"]
    assert not missing.exists()


async def test_help_and_malformed_bypass_never_open_transaction_or_call_usecase(
    tmp_path, monkeypatch
):
    async def unexpected(*args, **kwargs):
        raise AssertionError("must not execute usecase")

    monkeypatch.setattr(ReceiveHookUseCase, "run", unexpected)
    assert (await invoke(tmp_path / "missing", ["--help"])).exit_code == 0
    result = await invoke(
        tmp_path / "missing", ["hook", "handle", "--provider", "claude", "--bypass"], "{bad"
    )
    assert result.exit_code == 0
    assert "bypass" in json.loads(result.stdout)["systemMessage"]
    assert not (tmp_path / "missing").exists()


async def test_unknown_provider_is_typer_usage_error(tmp_path):
    result = await invoke(tmp_path / "missing", ["hook", "handle", "--provider", "unknown"], "{}")
    assert result.exit_code == 2
    assert "unknown" in result.output


async def test_console_entrypoint_default_database_and_main_cleanup(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SPAKKY_SQLALCHEMY__CONNECTION_STRING", raising=False)
    monkeypatch.delenv("SPAKKY_DATA__SUPPORT_ASYNC_MODE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    database = tmp_path / "neurath/core.sqlite3"
    await initialize_database(database)
    folder = tmp_path / "workspace"
    folder.mkdir()
    payload = json.dumps(
        dict(
            session_id="console", turn_id="one", cwd=str(folder), hook_event_name="UserPromptSubmit"
        )
    )
    result = subprocess.run(
        [str(Path(sys.executable).with_name("neurath")), "hook", "handle", "--provider", "codex"],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {}
    stopped = []
    disposed = []
    from spakky.plugins.sqlalchemy.persistency.transaction import AsyncTransaction

    execution_loops = []
    disposal_loops = []
    original_initialize = AsyncTransaction.initialize

    async def initialize(transaction):
        execution_loops.append(asyncio.get_running_loop())
        await original_initialize(transaction)

    monkeypatch.setattr(AsyncTransaction, "initialize", initialize)
    original_stop = SpakkyApplication.stop
    cleanup = []
    monkeypatch.setattr(atexit, "register", lambda callback: cleanup.append(callback))
    original_dispose = AsyncConnectionManager.dispose

    def stop(app):
        stopped.append(app)
        return original_stop(app)

    async def dispose(manager):
        disposed.append(manager)
        disposal_loops.append(asyncio.get_running_loop())
        return await original_dispose(manager)

    monkeypatch.setattr(SpakkyApplication, "stop", stop)
    monkeypatch.setattr(AsyncConnectionManager, "dispose", dispose)
    monkeypatch.setattr(sys, "argv", ["neurath", "hook", "handle", "--provider", "codex"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    namespace = runpy.run_module("neurath.cli")
    assert isinstance(namespace["cli"], Typer)
    with pytest.raises(SystemExit) as exited:
        await asyncio.to_thread(namespace["cli"])
    for callback in cleanup:
        callback()
    assert exited.value.code == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert len(stopped) == len(disposed) == 1
    assert execution_loops and all(loop is disposal_loops[0] for loop in execution_loops)
    async with storage_scope(database, write=False) as scope:
        assert (
            await scope.get(AsyncSessionManager).session.scalar(
                text("SELECT count(*) FROM core_executions")
            )
            == 1
        )


async def test_bootstrap_failure_preserves_error_before_engine_use(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SPAKKY_SQLALCHEMY__CONNECTION_STRING",
        sqlite_url(tmp_path / "missing", "rw").render_as_string(hide_password=False),
    )

    def fail(context, **kwargs):
        raise RuntimeError("startup failure")

    disposed = []
    original = AsyncConnectionManager.dispose

    async def dispose(manager):
        disposed.append(manager)
        return await original(manager)

    monkeypatch.setattr(ApplicationContext, "start", fail)
    monkeypatch.setattr(AsyncConnectionManager, "dispose", dispose)
    with pytest.raises(RuntimeError, match="startup failure"):
        await asyncio.to_thread(runpy.run_module, "neurath.cli")
    assert len(disposed) == 0


async def test_cli_reuses_registered_controller_without_leaking_transaction(database, tmp_path):
    folder = tmp_path / "workspace"
    folder.mkdir()
    payload = json.dumps(
        dict(session_id="scope", turn_id="one", cwd=str(folder), hook_event_name="UserPromptSubmit")
    )
    async with scanned_application(sqlite_url(database, "rw")) as app:
        scope = app.container

        def invoke_in_host_thread():
            first = scope.get(HookCliController)
            result = CliRunner().invoke(
                scope.get(Typer), ["hook", "handle", "--provider", "codex"], input=payload
            )
            return first, scope.get(HookCliController), result

        first, second, result = await asyncio.to_thread(invoke_in_host_thread)
        assert result.exit_code == 0 and json.loads(result.stdout) == {}
        assert first is second
        assert first.usecase is second.usecase
        from spakky.plugins.sqlalchemy.persistency.session_manager import SessionNotInitializedError

        with pytest.raises(SessionNotInitializedError):
            scope.get(AsyncSessionManager).session


def test_git_workspace_error_is_not_plain_folder(repository, monkeypatch):
    service = GitDirectoryObserverService()
    monkeypatch.setattr(
        service,
        "_git",
        lambda directory, *args: subprocess.CompletedProcess(args, 128, "", "permission denied"),
    )
    with pytest.raises(NeurathError, match="permission denied"):
        service.observe(str(repository))
    with pytest.raises(NotImplementedError):
        IDirectoryObserverService.observe(service, str(repository))


async def test_unsupported_event_is_rejected_before_usecase_or_database(tmp_path, monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("must not execute usecase")

    monkeypatch.setattr(ReceiveHookUseCase, "run", unexpected)
    missing = tmp_path / "missing"
    response = await invoke(
        missing,
        ["hook", "handle", "--provider", "codex"],
        json.dumps(
            {
                "hook_event_name": "FutureUnsupportedEvent",
                "session_id": "native",
                "cwd": str(tmp_path),
            }
        ),
    )
    assert response.exit_code == 0
    result = json.loads(response.stdout)
    assert "host tools remain available" in result["systemMessage"]
    assert "unverified" in result["systemMessage"]
    assert not missing.exists()


async def test_cli_groups_and_injected_usecases_match_memory_and_session_responsibilities(tmp_path):
    from typing import get_type_hints

    from typer.main import get_command

    from neurath.application.ports.services.graph import IGraphService
    from neurath.application.usecases.preview_session import PreviewSessionUseCase
    from neurath.application.usecases.resume_session import ResumeSessionUseCase
    from neurath.application.usecases.update_checkpoint_graph import UpdateCheckpointGraphUseCase
    from neurath.infrastructure.database import sqlite_url
    from neurath.transport.cli.memory import MemoryCliController
    from neurath.transport.cli.session import SessionCliController

    missing = tmp_path / "uninitialized.sqlite3"
    async with scanned_application(sqlite_url(missing, "rw")) as app:
        root = get_command(app.container.get(Typer))
        assert set(root.commands["memory"].commands) == {
            "read",
            "update",
            "search",
            "checkpoint",
            "propose-lesson",
            "observe-lesson",
        }
        assert set(root.commands["session"].commands) == {"preview", "resume"}
        assert {"read", "update", "search", "checkpoint", "preview", "resume"}.isdisjoint(
            root.commands
        )
    memory_dependencies = set(get_type_hints(MemoryCliController.__init__).values())
    session_dependencies = set(get_type_hints(SessionCliController.__init__).values())
    session_operations = {PreviewSessionUseCase, ResumeSessionUseCase}
    assert memory_dependencies.isdisjoint(session_operations)
    assert memory_dependencies.isdisjoint({IGraphService, UpdateCheckpointGraphUseCase})
    assert session_operations <= session_dependencies
    assert not missing.exists()


async def test_all_scanned_cli_controllers_have_explicit_groups_in_actual_command_tree(tmp_path):
    import inspect
    import pkgutil
    from importlib import import_module

    from typer import Typer
    from typer.core import TyperGroup
    from typer.main import get_command

    import neurath.transport.cli
    from neurath.infrastructure.database import sqlite_url
    from tests.support.application import scanned_application

    async with scanned_application(sqlite_url(tmp_path / "missing.sqlite3", "rw")) as app:
        root = get_command(app.container.get(Typer))
        groups = set()
        for entry in pkgutil.iter_modules(
            neurath.transport.cli.__path__, neurath.transport.cli.__name__ + "."
        ):
            for _, controller in inspect.getmembers(import_module(entry.name), inspect.isclass):
                if controller.__module__ != entry.name or not CliController.exists(controller):
                    continue
                group = CliController.get(controller).group_name
                assert isinstance(group, str) and group.strip(), controller
                groups.add(group)
                assert isinstance(root.commands[group], TyperGroup)
                assert app.container.get(controller) is not None
        assert groups <= root.commands.keys()


@pytest.mark.parametrize("exists", [False, True])
async def test_version_is_installed_metadata_without_opening_even_broken_database(tmp_path, exists):
    from importlib.metadata import version

    database = tmp_path / "unavailable.sqlite3"
    if exists:
        database.write_bytes(b"not a database")
    result = await invoke(database, ["maintenance", "version"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"name": "neurath", "version": version("neurath")}
    assert result.stderr == ""
    assert database.exists() == exists
    if exists:
        assert database.read_bytes() == b"not a database"
