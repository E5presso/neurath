"""프로세스·범위·트랜잭션·Git 변경에 걸친 요청의 관찰 가능한 행동을 검증한다."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_project import (
    RegisterProjectCommand,
    RegisterProjectUseCase,
)
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import (
    ContextNotFound,
    NeurathError,
    ProjectIdentityConflict,
    RevisionConflict,
)
from neurath.domain.observations import DirectoryObservation
from neurath.infrastructure.database import create_database_engine
from neurath.infrastructure.models.project import ProjectModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.repositories.session import SQLAlchemySessionRepository
from tests.conftest import git, initialize_git, storage_scope
from tests.support.application import spakky_context
from tests.support.session_requests import (
    get_session_context,
    move_session,
    register_session,
    session_state,
)

PROCESS = """
import asyncio, json, sys
from pathlib import Path
from tests.support.session_requests import register_session, get_session_context, move_session, session_state
from neurath.domain.errors import RevisionConflict
path = Path(sys.argv[1])
mode = sys.argv[2]
async def main():
    try:
        if mode == "register":
            result = await register_session(sys.argv[3], sys.argv[4], sys.argv[5], database_path=path)
        elif mode == "read":
            result = await get_session_context(sys.argv[3], sys.argv[4], database_path=path)
        elif mode == "move":
            result = await move_session(sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6]), database_path=path)
        else:
            raise ValueError(mode)
        print(json.dumps(session_state(result)))
    except RevisionConflict:
        print(json.dumps({"conflict": True}))
asyncio.run(main())
"""


async def request(database, mode, *arguments):
    result = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-c",
            PROCESS,
            str(database),
            mode,
            *[str(value) for value in arguments],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


async def test_independent_process_restart_reads_latest_revision(database, repository):
    first = await request(database, "register", repository, "codex", "native")
    project_id, session_id = first["project"]["uid"], first["session"]["uid"]
    assert (await request(database, "read", project_id, session_id)) == first
    child = repository / "child"
    child.mkdir()
    changed = await request(database, "move", project_id, session_id, child, 1)
    assert changed["session"]["revision"] == 2
    assert changed["session"]["working_directory"] == str(child)
    assert (await request(database, "read", project_id, session_id)) == changed
    assert (await request(database, "register", repository, "codex", "native")) == changed


async def test_worktrees_and_subfolders_share_project_but_keep_observed_directory(
    database, repository, tmp_path
):
    linked = tmp_path / "linked"
    git(repository, "worktree", "add", "-b", "feature", str(linked))
    child = linked / "child"
    child.mkdir()
    contexts = [
        (await register_session(str(folder), "codex", str(index), database_path=database))
        for index, folder in enumerate((repository, linked, child))
    ]
    assert len({context.project.id for context in contexts}) == 1
    assert len({context.session.id for context in contexts}) == 3
    assert [context.session.working_directory for context in contexts] == [
        str(repository),
        str(linked),
        str(child),
    ]


async def test_clones_same_remote_same_native_id_and_other_providers_are_scoped(
    database, repository, tmp_path
):
    clones = [tmp_path / "a", tmp_path / "b"]
    for clone in clones:
        git(tmp_path, "clone", str(repository), str(clone))
    assert git(clones[0], "remote", "get-url", "origin") == git(
        clones[1], "remote", "get-url", "origin"
    )
    first, second = [
        (await register_session(str(clone), "codex", "same", database_path=database))
        for clone in clones
    ]
    assert first.project.id != second.project.id
    with pytest.raises(ContextNotFound):
        (await get_session_context(first.project.id, second.session.id, database_path=database))
    with pytest.raises(ContextNotFound):
        (
            await move_session(
                first.project.id, first.session.id, str(clones[1]), 1, database_path=database
            )
        )
    assert session_state(
        await get_session_context(first.project.id, first.session.id, database_path=database)
    ) == session_state(first)
    other = await register_session(str(clones[0]), "claude", "same", database_path=database)
    assert other.project == first.project
    assert other.session.id != first.session.id


async def test_folder_to_git_promotion_preserves_foreign_keys_from_first_linked_request(
    database, tmp_path
):
    plain = tmp_path / "plain"
    plain.mkdir()
    before = await register_session(str(plain), "codex", "native", database_path=database)
    with closing(sqlite3.connect(database)) as connection, connection:
        (connection.execute("PRAGMA foreign_keys=ON"))
        (
            connection.execute(
                "CREATE TABLE dependent_fixture (project_id TEXT REFERENCES core_projects(id), source TEXT)"
            )
        )
        (
            connection.execute(
                "INSERT INTO dependent_fixture VALUES (?, ?)",
                (before.project.id, "unfinished original source"),
            )
        )
    initialize_git(plain)
    linked = tmp_path / "linked"
    git(plain, "worktree", "add", "-b", "branch", str(linked))
    after = await request(database, "register", linked, "codex", "another")
    assert after["project"]["uid"] == before.project.id
    assert (await request(database, "read", before.project.id, before.session.id)) == session_state(
        before
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        assert (connection.execute("SELECT * FROM dependent_fixture")).fetchall() == [
            (before.project.id, "unfinished original source")
        ]
        assert (connection.execute("PRAGMA foreign_key_check")).fetchall() == []


def test_concurrent_process_registration_returns_one_identity(database, repository):
    def register(_):
        return asyncio.run(request(database, "register", repository, "codex", "same"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        contexts = list(pool.map(register, range(8)))
    assert all(context == contexts[0] for context in contexts)


async def test_concurrent_revision_change_has_one_winner(database, repository):
    first = await register_session(str(repository), "codex", "native", database_path=database)
    folders = [repository / "left", repository / "right"]
    for folder in folders:
        folder.mkdir()

    def move(folder):
        return asyncio.run(request(database, "move", first.project.id, first.session.id, folder, 1))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(move, folders))
    winners = [result for result in results if "conflict" not in result]
    assert len(winners) == 1
    assert winners[0]["session"]["revision"] == 2
    assert (await request(database, "read", first.project.id, first.session.id)) == winners[0]


async def test_failed_registration_rolls_back_project_alias_and_session(
    database, repository, monkeypatch
):
    original_save = SQLAlchemySessionRepository.save

    async def fail_after_flush(self, session):
        await original_save(self, session)
        raise RuntimeError("after flush")

    monkeypatch.setattr(SQLAlchemySessionRepository, "save", fail_after_flush)
    with pytest.raises(RuntimeError, match="after flush"):
        (await register_session(str(repository), "codex", "native", database_path=database))
    with closing(sqlite3.connect(database)) as connection, connection:
        for table in ("core_projects", "core_project_locations", "core_sessions"):
            assert (connection.execute(f"SELECT COUNT(*) FROM {table}")).fetchone() == (0,)


async def test_related_changes_roll_back_together_using_actual_session(database, repository):
    first = await register_session(str(repository), "codex", "native", database_path=database)
    with pytest.raises(RuntimeError, match="rollback"):
        async with storage_scope(database) as scope:
            sessions = scope.get(ISessionRepository)
            changed = await sessions.get(first.session.id)
            changed.move("new-directory", 1)
            (await sessions.save(changed))
            (await sessions.save(HostSession.create(first.project.id, "codex", "second", "new")))
            raise RuntimeError("rollback")
    assert session_state(
        await get_session_context(first.project.id, first.session.id, database_path=database)
    ) == session_state(first)
    async with storage_scope(database, write=False) as scope:
        assert (
            await scope.get(AsyncSessionManager).session.scalar(
                text("SELECT COUNT(*) FROM core_sessions")
            )
        ) == 1


async def test_uncommitted_data_is_invisible_and_read_only_connection_rejects_writes(
    database, repository
):
    first = await register_session(str(repository), "codex", "native", database_path=database)
    async with storage_scope(database) as scope:
        sessions = scope.get(ISessionRepository)
        changed = await sessions.get(first.session.id)
        changed.move("uncommitted", 1)
        (await sessions.save(changed))
        assert (
            await request(database, "read", first.project.id, first.session.id)
        ) == session_state(first)
    with pytest.raises(OperationalError, match="readonly"):
        async with storage_scope(database, write=False) as scope:
            (
                await scope.get(AsyncSessionManager).session.execute(
                    text("DELETE FROM core_sessions")
                )
            )


async def test_foreign_keys_and_positive_revisions_are_enforced(database):
    engine = create_database_engine(database, write=True)
    try:
        with pytest.raises(IntegrityError):
            async with AsyncSession(engine) as session, session.begin():
                session.add(
                    SessionModel(
                        id="bad",
                        project_id="absent",
                        provider="test",
                        host_session_id="x",
                        working_directory="/tmp",
                        revision=1,
                    )
                )
        with pytest.raises(IntegrityError):
            async with AsyncSession(engine) as session, session.begin():
                session.add(ProjectModel(id="project", root_path="/tmp"))
                (await session.flush())
                (
                    await session.execute(
                        text(
                            "INSERT INTO core_sessions (id, project_id, provider, host_session_id, working_directory, revision) VALUES ('bad', 'project', 'test', 'x', '/tmp', 0)"
                        )
                    )
                )
    finally:
        (await engine.dispose())


async def test_identity_conflict_does_not_merge_or_modify_existing_aliases(database):
    async with spakky_context(database) as scope:
        projects = scope.get(RegisterProjectUseCase)
        first = await projects.run(
            RegisterProjectCommand(DirectoryObservation("/one", "/one/.git", "/one"))
        )
        second = await projects.run(RegisterProjectCommand(DirectoryObservation("/two")))
    with pytest.raises(ProjectIdentityConflict):
        async with spakky_context(database) as scope:
            (
                await scope.get(RegisterProjectUseCase).run(
                    RegisterProjectCommand(DirectoryObservation("/two", "/one/.git", "/two"))
                )
            )
    async with storage_scope(database, write=False) as scope:
        assert set(
            await scope.get(AsyncSessionManager).session.scalars(select(ProjectModel.id))
        ) == {
            first.project.id,
            second.project.id,
        }
    with pytest.raises(ProjectIdentityConflict):
        async with spakky_context(database) as scope:
            (
                await scope.get(RegisterProjectUseCase).run(
                    RegisterProjectCommand(DirectoryObservation("/one", "/different/.git", "/one"))
                )
            )


async def test_wrong_revision_and_empty_native_identifiers_fail_without_mutation(
    database, repository
):
    first = await register_session(str(repository), "codex", "native", database_path=database)
    with pytest.raises(RevisionConflict):
        (
            await move_session(
                first.project.id, first.session.id, str(repository), 0, database_path=database
            )
        )
    for provider, native in ((" ", "native"), ("codex", "")):
        with pytest.raises(ValueError):
            (await register_session(str(repository), provider, native, database_path=database))
    assert session_state(
        await get_session_context(first.project.id, first.session.id, database_path=database)
    ) == session_state(first)


async def test_git_environment_is_ignored_and_errors_are_not_folder_fallback(
    database, repository, tmp_path, monkeypatch
):
    monkeypatch.setenv("GIT_DIR", str(repository / ".git"))
    plain = tmp_path / "plain"
    plain.mkdir()
    first = await register_session(str(repository), "codex", "native", database_path=database)
    second = await register_session(str(plain), "codex", "native", database_path=database)
    assert first.project.id != second.project.id
    from neurath.infrastructure.directory_observer import GitDirectoryObserverService

    def fail(self, directory, *arguments):
        return subprocess.CompletedProcess(arguments, 128, "", "fatal: dubious ownership")

    monkeypatch.setattr(GitDirectoryObserverService, "_git", fail)
    with pytest.raises(NeurathError, match="dubious ownership"):
        (await register_session(str(repository), "codex", "new", database_path=database))


async def test_request_releases_writer_before_following_external_action(database, repository):
    first = await register_session(str(repository), "codex", "native", database_path=database)
    following = await request(database, "register", repository, "codex", "external-result")
    assert following["project"]["uid"] == first.project.id
