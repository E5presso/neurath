"""실패 요청의 보존 경계와 Spakky 자원 격리 및 분리된 반환값을 검증한다."""

import sqlite3
import subprocess
from contextlib import closing
from dataclasses import FrozenInstanceError

import pytest
from spakky.core.application.application_context import ApplicationContext
from spakky.data.persistency.repository import EntityNotFoundError
from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.get_session_context import GetSessionContextResult
from neurath.domain.aggregates.project import Project, ProjectKind, ProjectLocation
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import ContextNotFound, ProjectIdentityConflict, RevisionConflict
from neurath.domain.observations import DirectoryObservation
from neurath.infrastructure.models.project import ProjectLocationModel
from tests.conftest import initialize_git, storage_scope
from tests.support.application import spakky_context
from tests.support.session_requests import (
    get_session_context,
    move_session,
    register_session,
    session_state,
)


def persisted_state(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        return {
            table: (connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2")).fetchall()
            for table in ("core_projects", "core_project_locations", "core_sessions")
        }


def test_self_factories_preserve_subclasses_and_results_keep_their_explicit_payloads():
    class SpecializedProject(Project):
        pass

    class SpecializedSession(HostSession):
        pass

    class SpecializedResult(GetSessionContextResult):
        pass

    project = SpecializedProject.create(DirectoryObservation(working_directory="/repo"))
    session = SpecializedSession.create(project.id, "codex", "native", "/repo")
    context = SpecializedResult(project=project, session=session)
    assert type(project) is SpecializedProject
    assert type(session) is SpecializedSession
    assert type(context) is SpecializedResult
    assert SpecializedProject.owner_of((project,)) is project
    assert SpecializedProject.owner_of(()) is None
    assert context.project is project and context.session is session
    with pytest.raises(FrozenInstanceError):
        context.project = project


async def test_mutating_returned_entities_does_not_write_outside_the_request(database, repository):
    first = await register_session(str(repository), "codex", "native", database_path=database)
    expected = session_state(first)
    loaded = await get_session_context(first.project.id, first.session.id, database_path=database)
    loaded.project.root_path = "/changed"
    loaded.session.move("/changed", loaded.session.revision)
    current = await get_session_context(first.project.id, first.session.id, database_path=database)
    assert session_state(current) == expected


def test_mixed_location_conflict_never_partially_adds_folder_alias():
    project = Project.create(
        DirectoryObservation(
            working_directory="/repo", git_common_directory="/repo/.git", primary_worktree="/repo"
        )
    )
    before = project.locations
    with pytest.raises(ProjectIdentityConflict):
        project.associate(
            (
                ProjectLocation(kind=ProjectKind.FOLDER, path="/new-alias"),
                ProjectLocation(kind=ProjectKind.GIT, path="/other/.git"),
            )
        )
    assert project.locations == before
    project.associate(before + before)
    assert project.locations == before


@pytest.mark.parametrize(
    "provider,native", [("", "id"), ("\t\n", "id"), ("codex", " "), ("codex", "\n")]
)
async def test_invalid_registration_preserves_all_existing_records(
    database, repository, provider, native
):
    first = await register_session(str(repository), "codex", "retained", database_path=database)
    before = persisted_state(database)
    with pytest.raises(ValueError):
        (await register_session(str(repository), provider, native, database_path=database))
    assert persisted_state(database) == before
    assert session_state(
        await get_session_context(first.project.id, first.session.id, database_path=database)
    ) == session_state(first)


@pytest.mark.parametrize("operation", ["read", "move"])
@pytest.mark.parametrize("missing", ["project", "session", "both"])
async def test_unknown_scope_cannot_read_or_mutate_any_records(
    database, repository, operation, missing
):
    first = await register_session(str(repository), "codex", "retained", database_path=database)
    project_id = "absent" if missing in ("project", "both") else first.project.id
    session_id = "absent" if missing in ("session", "both") else first.session.id
    before = persisted_state(database)
    expected = EntityNotFoundError if missing in ("session", "both") else ContextNotFound
    with pytest.raises(expected):
        if operation == "read":
            (await get_session_context(project_id, session_id, database_path=database))
        else:
            (await move_session(project_id, session_id, str(repository), 1, database_path=database))
    assert persisted_state(database) == before


async def test_move_to_unregistered_project_rolls_back_its_new_project_and_alias(
    database, repository, tmp_path
):
    first = await register_session(str(repository), "codex", "retained", database_path=database)
    other = tmp_path / "unregistered"
    other.mkdir()
    before = persisted_state(database)
    with pytest.raises(ContextNotFound):
        (
            await move_session(
                first.project.id, first.session.id, str(other), 1, database_path=database
            )
        )
    assert persisted_state(database) == before


async def test_stale_move_rolls_back_folder_to_git_alias_promotion(database, tmp_path):
    first = await register_session(str(tmp_path), "codex", "retained", database_path=database)
    before = persisted_state(database)
    initialize_git(tmp_path)
    with pytest.raises(RevisionConflict):
        (
            await move_session(
                first.project.id, first.session.id, str(tmp_path), 0, database_path=database
            )
        )
    assert persisted_state(database) == before
    resumed = await register_session(str(tmp_path), "codex", "retained", database_path=database)
    assert session_state(resumed) == session_state(first)
    assert len(persisted_state(database)["core_project_locations"]) == 2


async def test_aggregate_child_removal_does_not_remove_other_project_locations(database):
    first = Project.create(
        DirectoryObservation(
            working_directory="/one", git_common_directory="/one/.git", primary_worktree="/one"
        )
    )
    second = Project.create(DirectoryObservation(working_directory="/two"))
    async with storage_scope(database) as scope:
        repository = scope.get(IProjectRepository)
        first = await repository.save(first)
        (await repository.save(second))
    first.locations = (ProjectLocation(kind=ProjectKind.GIT, path="/one/.git"),)
    async with storage_scope(database) as scope:
        (await scope.get(IProjectRepository).save(first))
    async with storage_scope(database, write=False) as scope:
        repository = scope.get(IProjectRepository)
        assert (await repository.get(first.uid)).locations == first.locations
        assert (
            await scope.get(AsyncSessionManager).session.scalar(
                select(ProjectLocationModel.project_id).where(
                    ProjectLocationModel.kind == "folder", ProjectLocationModel.path == "/one"
                )
            )
            is None
        )
        assert (await repository.get(second.uid)).locations == second.locations
        assert (
            await scope.get(AsyncSessionManager).session.scalar(
                select(ProjectLocationModel.project_id).where(ProjectLocationModel.path == "/two")
            )
            == second.uid
        )


async def test_unchanged_save_issues_no_update_and_preserves_version(database, repository):
    first = await register_session(str(repository), "codex", "native", database_path=database)
    statements = []
    async with storage_scope(database) as scope:
        session = scope.get(AsyncSessionManager).session
        event.listen(
            session.get_bind(),
            "before_cursor_execute",
            lambda connection, cursor, statement, parameters, context, many: statements.append(
                statement
            ),
        )
        sessions = scope.get(ISessionRepository)
        entity = await sessions.get(first.session.id)
        version = entity.version
        updated_at = entity.updated_at
        entity.move(entity.working_directory, entity.revision)
        saved = await sessions.save(entity)
        assert saved.revision == first.session.revision
        assert saved.version == version and saved.updated_at == updated_at
    assert not any(statement.lstrip().upper().startswith("UPDATE ") for statement in statements)


async def test_nested_spakky_requests_have_independent_resources_and_cleanup(database):
    async with storage_scope(database) as outer:
        outer_session = outer.get(AsyncSessionManager).session
        async with storage_scope(database, write=False) as inner:
            inner_session = inner.get(AsyncSessionManager).session
            assert inner_session is not outer_session
            assert outer.get(IProjectRepository)._session_manager.session is outer_session
            assert inner.get(IProjectRepository)._session_manager.session is inner_session
            assert (await inner_session.scalar(text("SELECT 1"))) == 1
        assert (await outer_session.scalar(text("SELECT 2"))) == 2


async def test_spakky_bootstrap_failure_preserves_original_error_and_disposes_engine(
    database, monkeypatch
):
    disposed = []
    original_dispose = AsyncConnectionManager.dispose

    async def dispose(self):
        disposed.append(self.connection)
        await original_dispose(self)

    def fail_start(self, **kwargs):
        raise RuntimeError("bootstrap failure")

    monkeypatch.setattr(AsyncConnectionManager, "dispose", dispose)
    monkeypatch.setattr(ApplicationContext, "start", fail_start)
    before = persisted_state(database)
    with pytest.raises(RuntimeError, match="bootstrap failure"):
        async with spakky_context(database, write=True):
            pytest.fail("A failed bootstrap must not enter the request")
    assert len(disposed) == 1
    assert persisted_state(database) == before


@pytest.mark.parametrize("failure", [OSError("git missing"), subprocess.TimeoutExpired("git", 10)])
async def test_git_execution_failures_preserve_state_and_are_not_plain_folder_fallback(
    database, repository, monkeypatch, failure
):
    from neurath.domain.errors import NeurathError
    from neurath.infrastructure import directory_observer

    before = persisted_state(database)

    def fail(*arguments, **keywords):
        raise failure

    monkeypatch.setattr(directory_observer.subprocess, "run", fail)
    with pytest.raises(NeurathError, match="Cannot inspect local Git project"):
        (await register_session(str(repository), "codex", "native", database_path=database))
    assert persisted_state(database) == before


@pytest.mark.parametrize("status,output", [(128, ""), (0, ""), (0, "bare\x00")])
async def test_invalid_worktree_metadata_preserves_state(
    database, repository, monkeypatch, status, output
):
    from neurath.domain.errors import NeurathError
    from neurath.infrastructure.directory_observer import GitDirectoryObserverService

    def git_result(self, directory, *arguments):
        if arguments[0] == "rev-parse":
            return subprocess.CompletedProcess(arguments, 0, str(repository / ".git"), "")
        return subprocess.CompletedProcess(arguments, status, output, "worktree failure")

    monkeypatch.setattr(GitDirectoryObserverService, "_git", git_result)
    before = persisted_state(database)
    with pytest.raises(NeurathError):
        (await register_session(str(repository), "codex", "native", database_path=database))
    assert persisted_state(database) == before


async def test_file_path_and_unknown_project_lookup_are_rejected_without_writes(database, tmp_path):
    invalid = tmp_path / "file"
    invalid.write_text("not a directory")
    before = persisted_state(database)
    with pytest.raises(ValueError, match="must be a directory"):
        (await register_session(str(invalid), "codex", "native", database_path=database))
    with pytest.raises(EntityNotFoundError):
        async with storage_scope(database, write=False) as scope:
            (await scope.get(IProjectRepository).get("missing"))
    assert persisted_state(database) == before


def test_entity_identity_comparison_rejects_unrelated_objects():
    project = Project.create(DirectoryObservation(working_directory="/repo"))
    session = HostSession.create(project.id, "codex", "native", "/repo")
    assert project != object()
    assert session != object()
    assert project != session


async def test_unrelated_integrity_failure_is_not_misreported_as_project_ownership_conflict(
    database,
):
    from sqlalchemy.exc import IntegrityError

    before = persisted_state(database)
    with pytest.raises(IntegrityError) as failure:
        async with storage_scope(database) as scope:
            (
                await scope.get(AsyncSessionManager).session.execute(
                    text(
                        "INSERT INTO core_sessions (id, project_id, provider, host_session_id, working_directory, revision) VALUES ('invalid', 'missing-parent', 'codex', 'new', '/invalid', 1)"
                    )
                )
            )
    assert "FOREIGN KEY constraint failed" in str(failure.value.orig)
    assert persisted_state(database) == before
    async with storage_scope(database, write=False) as scope:
        assert (await scope.get(AsyncSessionManager).session.scalar(text("SELECT 1"))) == 1


async def test_incomplete_observer_fails_explicitly_without_registering_a_project(
    database, repository, monkeypatch
):
    from neurath.application.ports.services.directory_observer import IDirectoryObserverService
    from neurath.infrastructure.directory_observer import GitDirectoryObserverService

    with pytest.raises(TypeError, match="abstract"):
        IDirectoryObserverService()

    def incomplete_observe(self, working_directory):
        return IDirectoryObserverService.observe(self, working_directory)

    monkeypatch.setattr(GitDirectoryObserverService, "observe", incomplete_observe)
    before = persisted_state(database)
    with pytest.raises(NotImplementedError):
        (await register_session(str(repository), "codex", "new", database_path=database))
    assert persisted_state(database) == before


@pytest.mark.parametrize("kind", ["project-location", "native-session"])
async def test_incomplete_repository_lookup_rolls_back_registration_instead_of_returning_fake_success(
    database, repository, monkeypatch, kind
):
    original = AsyncSession.scalar

    async def failed_lookup(self, statement, *args, **kwargs):
        target = "core_projects" if kind == "project-location" else "core_sessions"
        if target in str(statement):
            raise RuntimeError("query failed")
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", failed_lookup)
    before = persisted_state(database)
    with pytest.raises(RuntimeError, match="query failed"):
        await register_session(str(repository), "codex", "new", database_path=database)
    assert persisted_state(database) == before
