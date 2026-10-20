"""실패 요청의 보존 경계와 Spakky 자원 격리 및 분리된 반환값을 검증한다."""

import sqlite3
import subprocess
from contextlib import closing
from dataclasses import FrozenInstanceError

import pytest
from spakky.core.application.application_context import ApplicationContext
from spakky.plugins.sqlalchemy.persistency.session_manager import SessionManager
from sqlalchemy import event, text

from neurath.application.context import SessionContext
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.project import Project, ProjectKind, ProjectLocation
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import ContextNotFound, ProjectIdentityConflict, RevisionConflict
from neurath.domain.observations import DirectoryObservation
from neurath.infrastructure import providers
from neurath.infrastructure.providers import DatabaseSettings, request_container
from neurath.transport.session_requests import get_session_context, move_session, register_session
from tests.conftest import initialize_git, storage_scope


def persisted_state(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("core_projects", "core_project_locations", "core_sessions")
        }


def test_self_factories_preserve_the_invoked_subclass_and_snapshot_independence():
    class SpecializedProject(Project):
        pass

    class SpecializedSession(HostSession):
        pass

    class SpecializedContext(SessionContext):
        pass

    project = SpecializedProject.create(DirectoryObservation("/repo"))
    session = SpecializedSession.create(project.id, "codex", "native", "/repo")
    context = SpecializedContext.from_entities(project, session)
    assert type(project) is SpecializedProject
    assert type(session) is SpecializedSession
    assert type(context) is SpecializedContext
    assert SpecializedProject.owner_of((project,)) is project
    assert SpecializedProject.owner_of(()) is None
    project.root_path = "/changed"
    session.move("/next", 1)
    assert context.project.root_path == "/repo"
    assert context.session.working_directory == "/repo"
    for value, attribute, replacement in (
        (context, "project", context.project),
        (context.project, "root_path", "/invalid"),
        (context.session, "working_directory", "/invalid"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute, replacement)


def test_mixed_location_conflict_never_partially_adds_folder_alias():
    project = Project.create(DirectoryObservation("/repo", "/repo/.git", "/repo"))
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
def test_invalid_registration_preserves_all_existing_records(
    database, repository, provider, native
):
    first = register_session(str(repository), "codex", "retained", database_path=database)
    before = persisted_state(database)
    with pytest.raises(ValueError):
        register_session(str(repository), provider, native, database_path=database)
    assert persisted_state(database) == before
    assert get_session_context(first.project.id, first.session.id, database_path=database) == first


@pytest.mark.parametrize("operation", ["read", "move"])
@pytest.mark.parametrize("missing", ["project", "session", "both"])
def test_unknown_scope_cannot_read_or_mutate_any_records(database, repository, operation, missing):
    first = register_session(str(repository), "codex", "retained", database_path=database)
    project_id = "absent" if missing in ("project", "both") else first.project.id
    session_id = "absent" if missing in ("session", "both") else first.session.id
    before = persisted_state(database)
    with pytest.raises(ContextNotFound):
        if operation == "read":
            get_session_context(project_id, session_id, database_path=database)
        else:
            move_session(project_id, session_id, str(repository), 1, database_path=database)
    assert persisted_state(database) == before


def test_move_to_unregistered_project_rolls_back_its_new_project_and_alias(
    database, repository, tmp_path
):
    first = register_session(str(repository), "codex", "retained", database_path=database)
    other = tmp_path / "unregistered"
    other.mkdir()
    before = persisted_state(database)
    with pytest.raises(ContextNotFound):
        move_session(first.project.id, first.session.id, str(other), 1, database_path=database)
    assert persisted_state(database) == before


def test_stale_move_rolls_back_folder_to_git_alias_promotion(database, tmp_path):
    first = register_session(str(tmp_path), "codex", "retained", database_path=database)
    before = persisted_state(database)
    initialize_git(tmp_path)
    with pytest.raises(RevisionConflict):
        move_session(first.project.id, first.session.id, str(tmp_path), 0, database_path=database)
    assert persisted_state(database) == before
    resumed = register_session(str(tmp_path), "codex", "retained", database_path=database)
    assert resumed == first
    assert len(persisted_state(database)["core_project_locations"]) == 2


def test_aggregate_child_removal_does_not_remove_other_project_locations(database):
    first = Project.create(DirectoryObservation("/one", "/one/.git", "/one"))
    second = Project.create(DirectoryObservation("/two"))
    with storage_scope(database) as scope:
        repository = scope.get(IProjectRepository)
        first = repository.save(first)
        repository.save(second)
    first.locations = (ProjectLocation(kind=ProjectKind.GIT, path="/one/.git"),)
    with storage_scope(database) as scope:
        scope.get(IProjectRepository).save(first)
    with storage_scope(database, write=False) as scope:
        repository = scope.get(IProjectRepository)
        assert repository.get(first.uid).locations == first.locations
        assert (
            repository.find_by_location(ProjectLocation(kind=ProjectKind.FOLDER, path="/one"))
            is None
        )
        assert repository.get(second.uid).locations == second.locations
        assert repository.find_by_location(second.locations[0]).uid == second.uid


def test_unchanged_save_issues_no_update_and_preserves_version(database, repository):
    first = register_session(str(repository), "codex", "native", database_path=database)
    statements = []
    with storage_scope(database) as scope:
        session = scope.get(SessionManager).session
        event.listen(
            session.get_bind(),
            "before_cursor_execute",
            lambda connection, cursor, statement, parameters, context, many: statements.append(
                statement
            ),
        )
        sessions = scope.get(ISessionRepository)
        entity = sessions.get(first.session.id)
        version = entity.version
        updated_at = entity.updated_at
        entity.move(entity.working_directory, entity.revision)
        saved = sessions.save(entity)
        assert saved.revision == first.session.revision
        assert saved.version == version and saved.updated_at == updated_at
    assert not any(statement.lstrip().upper().startswith("UPDATE ") for statement in statements)


def test_nested_spakky_requests_have_independent_resources_and_cleanup(database):
    with storage_scope(database) as outer:
        outer_session = outer.get(SessionManager).session
        with storage_scope(database, write=False) as inner:
            inner_session = inner.get(SessionManager).session
            assert inner_session is not outer_session
            assert outer.get(IProjectRepository)._session_manager.session is outer_session
            assert inner.get(IProjectRepository)._session_manager.session is inner_session
            assert inner_session.scalar(text("SELECT 1")) == 1
        assert outer_session.scalar(text("SELECT 2")) == 2


def test_spakky_bootstrap_failure_preserves_original_error_and_disposes_engine(
    database, monkeypatch
):
    disposed = []
    original_dispose = providers.ConnectionManager.dispose

    def dispose(self):
        disposed.append(self.connection)
        original_dispose(self)

    def fail_start(self):
        raise RuntimeError("bootstrap failure")

    monkeypatch.setattr(providers.ConnectionManager, "dispose", dispose)
    monkeypatch.setattr(ApplicationContext, "start", fail_start)
    before = persisted_state(database)
    with pytest.raises(RuntimeError, match="bootstrap failure"):
        with request_container(DatabaseSettings(database, write=True)):
            pytest.fail("A failed bootstrap must not enter the request")
    assert len(disposed) == 1
    assert persisted_state(database) == before


@pytest.mark.parametrize("failure", [OSError("git missing"), subprocess.TimeoutExpired("git", 10)])
def test_git_execution_failures_preserve_state_and_are_not_plain_folder_fallback(
    database, repository, monkeypatch, failure
):
    from neurath.domain.errors import NeurathError
    from neurath.infrastructure import directory_observer

    before = persisted_state(database)

    def fail(*arguments, **keywords):
        raise failure

    monkeypatch.setattr(directory_observer.subprocess, "run", fail)
    with pytest.raises(NeurathError, match="Cannot inspect local Git project"):
        register_session(str(repository), "codex", "native", database_path=database)
    assert persisted_state(database) == before


@pytest.mark.parametrize("status,output", [(128, ""), (0, ""), (0, "bare\x00")])
def test_invalid_worktree_metadata_preserves_state(
    database, repository, monkeypatch, status, output
):
    from neurath.domain.errors import NeurathError
    from neurath.infrastructure.directory_observer import GitDirectoryObserver

    def git_result(self, directory, *arguments):
        if arguments[0] == "rev-parse":
            return subprocess.CompletedProcess(arguments, 0, str(repository / ".git"), "")
        return subprocess.CompletedProcess(arguments, status, output, "worktree failure")

    monkeypatch.setattr(GitDirectoryObserver, "_git", git_result)
    before = persisted_state(database)
    with pytest.raises(NeurathError):
        register_session(str(repository), "codex", "native", database_path=database)
    assert persisted_state(database) == before


def test_file_path_and_unknown_project_lookup_are_rejected_without_writes(database, tmp_path):
    invalid = tmp_path / "file"
    invalid.write_text("not a directory")
    before = persisted_state(database)
    with pytest.raises(ValueError, match="must be a directory"):
        register_session(str(invalid), "codex", "native", database_path=database)
    with pytest.raises(ContextNotFound):
        with storage_scope(database, write=False) as scope:
            scope.get(IProjectRepository).get("missing")
    assert persisted_state(database) == before


def test_entity_identity_comparison_rejects_unrelated_objects():
    project = Project.create(DirectoryObservation("/repo"))
    session = HostSession.create(project.id, "codex", "native", "/repo")
    assert project != object()
    assert session != object()
    assert project != session
