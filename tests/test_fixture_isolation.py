"""빠른 시험 fixture가 DB·요청·앱 수명과 실패 경계를 유지하는지 검증한다."""

import asyncio
import sqlite3
from contextlib import closing

import pytest
from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.sqlalchemy.persistency.session_manager import (
    AsyncSessionManager,
    SessionNotInitializedError,
)
from spakky.plugins.sqlalchemy.persistency.transaction import AsyncTransaction
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from tests.support import application as helpers
from tests.support.database import copy_empty_database


def test_database_copies_preserve_schema_and_do_not_share_rows(empty_database_template, tmp_path):
    first = copy_empty_database(empty_database_template, tmp_path / "one.sqlite3")
    second = copy_empty_database(empty_database_template, tmp_path / "two.sqlite3")
    with (
        closing(sqlite3.connect(first)) as one,
        closing(sqlite3.connect(second)) as two,
        closing(sqlite3.connect(empty_database_template.as_uri() + "?mode=ro", uri=True)) as source,
    ):
        expected = source.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall()
        assert (
            one.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            == expected
        )
        assert (
            two.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            == expected
        )
        assert (
            one.execute("SELECT * FROM core_schema_revision").fetchall()
            == source.execute("SELECT * FROM core_schema_revision").fetchall()
        )
        one.execute("CREATE TABLE isolation_probe (value TEXT)")
        one.execute("INSERT INTO isolation_probe VALUES ('only first')")
        one.commit()
        assert not two.execute(
            "SELECT 1 FROM sqlite_master WHERE name='isolation_probe'"
        ).fetchall()
        assert (
            source.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            == expected
        )
        assert one.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert two.execute("PRAGMA foreign_key_check").fetchall() == []


async def test_sequential_requests_reuse_app_but_open_and_close_distinct_sessions(database):
    async with helpers.request_application_lifetime():
        async with helpers.request_context(database) as first:
            manager = first.get(AsyncSessionManager)
            with pytest.raises(SessionNotInitializedError):
                _ = manager.session
            async with first.get(AsyncTransaction):
                session = manager.session
                assert await session.scalar(text("SELECT 1")) == 1
            with pytest.raises(SessionNotInitializedError):
                _ = manager.session
        async with helpers.request_context(database) as second:
            assert second is first
            assert second.get(AsyncSessionManager) is manager
            async with second.get(AsyncTransaction):
                assert manager.session is not session
                assert await manager.session.scalar(text("SELECT 1")) == 1
            with pytest.raises(SessionNotInitializedError):
                _ = manager.session


async def test_read_policy_and_database_path_never_share_application(
    database, empty_database_template, tmp_path
):
    other = copy_empty_database(empty_database_template, tmp_path / "other.sqlite3")
    async with helpers.request_application_lifetime():
        async with helpers.request_context(database) as writer:
            async with writer.get(AsyncTransaction):
                await writer.get(AsyncSessionManager).session.execute(
                    text("CREATE TABLE isolation_probe (value TEXT)")
                )
        async with helpers.request_context(database, write=False) as reader:
            assert reader is not writer
            with pytest.raises(OperationalError, match="readonly"):
                async with reader.get(AsyncTransaction):
                    await reader.get(AsyncSessionManager).session.execute(
                        text("INSERT INTO isolation_probe VALUES ('blocked')")
                    )
        async with helpers.request_context(other) as separate:
            assert separate is not writer and separate is not reader
            async with separate.get(AsyncTransaction):
                assert (
                    await separate.get(AsyncSessionManager).session.scalar(
                        text("SELECT COUNT(*) FROM sqlite_master WHERE name='isolation_probe'")
                    )
                    == 0
                )


async def test_overlapping_and_nested_requests_keep_active_sessions_independent(database):
    async with helpers.request_application_lifetime():
        async with helpers.request_context(database, write=False) as outer:
            async with outer.get(AsyncTransaction):
                active = outer.get(AsyncSessionManager).session
                async with helpers.request_context(database, write=False) as nested:
                    assert nested is not outer
                    async with nested.get(AsyncTransaction):
                        assert nested.get(AsyncSessionManager).session is not active
                        assert (
                            await nested.get(AsyncSessionManager).session.scalar(text("SELECT 1"))
                            == 1
                        )

                async def concurrent():
                    async with helpers.request_context(database, write=False) as sibling:
                        assert sibling is not outer
                        async with sibling.get(AsyncTransaction):
                            assert (
                                await sibling.get(AsyncSessionManager).session.scalar(
                                    text("SELECT 1")
                                )
                                == 1
                            )

                await asyncio.create_task(concurrent())
                assert outer.get(AsyncSessionManager).session is active
                assert await active.scalar(text("SELECT 1")) == 1


async def test_different_event_loop_uses_fresh_app_and_closes_it(database):
    async with helpers.request_application_lifetime():
        async with helpers.request_context(database) as original:
            pass

        async def foreign():
            async with helpers.request_context(database) as separate:
                assert separate is not original
                async with separate.get(AsyncTransaction):
                    assert (
                        await separate.get(AsyncSessionManager).session.scalar(text("SELECT 1"))
                        == 1
                    )
                return separate

        first = await asyncio.to_thread(lambda: asyncio.run(foreign()))
        second = await asyncio.to_thread(lambda: asyncio.run(foreign()))
        assert first is not second
        async with helpers.request_context(database) as restored:
            assert restored is original


async def test_application_lifetimes_dispose_resources_on_failure_and_do_not_share_instances(
    database,
):
    disposed = []
    with pytest.raises(RuntimeError, match="test failure"):
        async with helpers.request_application_lifetime():
            async with helpers.request_context(database) as first:
                engine = first.get(AsyncConnectionManager).connection
                event.listen(
                    engine.sync_engine, "engine_disposed", lambda engine: disposed.append(engine)
                )
            assert disposed == []
            raise RuntimeError("test failure")
    assert disposed == [engine.sync_engine]
    async with helpers.request_application_lifetime():
        async with helpers.request_context(database) as second:
            assert second is not first


async def test_failed_startup_is_not_cached(database, monkeypatch):
    original = helpers.create_application
    calls = []

    def start():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("startup failed")
        return original()

    monkeypatch.setattr(helpers, "create_application", start)
    async with helpers.request_application_lifetime():
        with pytest.raises(RuntimeError, match="startup failed"):
            async with helpers.request_context(database):
                pytest.fail("a failed application must not be yielded")
        async with helpers.request_context(database):
            pass
        async with helpers.request_context(database):
            pass
    assert len(calls) == 2


async def test_explicit_fresh_contexts_ignore_request_application_pool(database):
    async with helpers.request_application_lifetime():
        async with helpers.request_context(database) as pooled:
            pass
        async with helpers.spakky_context(database) as first:
            pass
        async with helpers.spakky_context(database) as second:
            pass
    assert first is not pooled and second is not first


async def test_shared_request_failure_keeps_original_error_and_releases_borrow(database):
    async with helpers.request_application_lifetime() as applications:
        with pytest.raises(ValueError, match="request failed"):
            async with helpers.request_context(database) as first:
                raise ValueError("request failed")
        assert applications.active_requests == set()
        async with helpers.request_context(database) as second:
            assert first is second


def test_database_copy_never_overwrites_an_existing_test_database(
    empty_database_template, tmp_path
):
    destination = tmp_path / "existing.sqlite3"
    destination.write_bytes(b"existing test state")
    with pytest.raises(FileExistsError):
        copy_empty_database(empty_database_template, destination)
    assert destination.read_bytes() == b"existing test state"
