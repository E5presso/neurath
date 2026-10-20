"""표준 저장소 CRUD와 실제 프레임워크 자원 수명 및 낙관적 잠금을 검증한다."""

from datetime import UTC

import pytest
from spakky.data.persistency.aggregate_collector import AggregateCollector
from spakky.data.persistency.repository import IGenericRepository, VersionConflictError
from spakky.plugins.sqlalchemy.orm.schema_registry import SchemaRegistry
from spakky.plugins.sqlalchemy.persistency.connection_manager import ConnectionManager
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from spakky.plugins.sqlalchemy.persistency.session_manager import (
    SessionManager,
    SessionNotInitializedError,
)
from spakky.plugins.sqlalchemy.persistency.transaction import Transaction
from sqlalchemy import event, select, text

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import ContextNotFound, ProjectIdentityConflict, RevisionConflict
from neurath.domain.observations import DirectoryObservation
from neurath.infrastructure.models.project import ProjectModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.providers import DatabaseSettings, request_container
from neurath.infrastructure.repositories.project import ProjectRepository
from neurath.infrastructure.repositories.session import SessionRepository
from tests.conftest import storage_scope
from tests.support.session_requests import (
    get_session_context,
    move_session,
    register_session,
)


def test_basic_contracts_and_methods_are_inherited_without_local_reimplementation():
    for repository, port in (
        (ProjectRepository, IProjectRepository),
        (SessionRepository, ISessionRepository),
    ):
        assert issubclass(port, IGenericRepository)
        assert issubclass(repository, AbstractGenericRepository)
        for method in (
            "__init__",
            "get",
            "get_or_none",
            "contains",
            "range",
            "save",
            "save_all",
            "delete",
            "delete_all",
        ):
            assert method not in repository.__dict__
            assert getattr(repository, method) is getattr(AbstractGenericRepository, method)
        for method in (
            "get",
            "get_or_none",
            "contains",
            "range",
            "save",
            "save_all",
            "delete",
            "delete_all",
        ):
            assert method not in port.__dict__


def test_spakky_injects_standard_managers_registry_collector_and_repositories(database):
    with request_container(DatabaseSettings(database, write=True)) as scope:
        manager = scope.get(SessionManager)
        usecase = scope.get(RegisterSessionUseCase)
        projects = scope.get(IProjectRepository)
        assert usecase.projects.projects is projects
        assert usecase.sessions is scope.get(ISessionRepository)
        assert projects._session_manager is usecase.sessions._session_manager is manager
        assert projects._schema_registry is scope.get(SchemaRegistry)
        assert projects._aggregate_collector is scope.get(AggregateCollector)
        assert scope.get(SchemaRegistry).get_type(Project) is ProjectModel
        assert scope.get(SchemaRegistry).get_type(HostSession) is SessionModel
        with scope.get(Transaction):
            first_session = manager.session
            assert first_session.scalar(text("SELECT 1")) == 1
        with pytest.raises(SessionNotInitializedError):
            manager.session
    with request_container(DatabaseSettings(database, write=True)) as second:
        assert second.get(SessionManager) is not manager
        assert second.get(IProjectRepository) is not projects
        with second.get(Transaction):
            assert second.get(SessionManager).session is not first_session


def test_exception_rolls_back_and_framework_closes_without_commit(database):
    events = []
    with pytest.raises(RuntimeError, match="abort"):
        with request_container(DatabaseSettings(database, write=True)) as scope:
            engine = scope.get(ConnectionManager).connection
            event.listen(engine, "commit", lambda connection: events.append("commit"))
            event.listen(engine, "rollback", lambda connection: events.append("rollback"))
            event.listen(engine, "close", lambda connection, record: events.append("close"))
            event.listen(engine, "engine_disposed", lambda connection: events.append("disposed"))
            manager = scope.get(SessionManager)
            with scope.get(Transaction):
                manager.session.execute(
                    text("INSERT INTO core_projects (id, root_path) VALUES ('abort', '/tmp')")
                )
                raise RuntimeError("abort")
    assert events == ["rollback", "close", "disposed"]
    with pytest.raises(SessionNotInitializedError):
        manager.session
    with storage_scope(database, write=False) as scope:
        assert (
            scope.get(SessionManager).session.scalar(text("SELECT COUNT(*) FROM core_projects"))
            == 0
        )


def test_inherited_crud_batch_delete_and_missing_contracts(database):
    first = Project.create(DirectoryObservation("/first"))
    second = Project.create(DirectoryObservation("/second"))
    with storage_scope(database) as scope:
        projects = scope.get(IProjectRepository)
        assert projects.get_or_none("missing") is None
        assert not projects.contains("missing")
        saved = projects.save_all((first, second))
        assert {item.uid for item in saved} == {first.uid, second.uid}
        assert projects.contains(first.uid)
        assert {item.uid for item in projects.range((second.uid, first.uid, "missing"))} == {
            first.uid,
            second.uid,
        }
        assert projects.range(()) == []
        collector = scope.get(AggregateCollector)
        assert {item.uid for item in collector.all()} == {first.uid, second.uid}
        deleted = projects.delete_all(saved)
        assert {item.uid for item in deleted} == {first.uid, second.uid}
        assert projects.range((first.uid, second.uid)) == []
    with pytest.raises(ContextNotFound):
        with storage_scope(database, write=False) as scope:
            scope.get(IProjectRepository).get(first.uid)
    with storage_scope(database) as scope:
        projects = scope.get(IProjectRepository)
        restored = projects.save(first)
        assert projects.delete(restored).uid == first.uid
        assert projects.get_or_none(first.uid) is None
        assert (
            scope.get(SessionManager).session.scalar(
                text("SELECT COUNT(*) FROM core_project_locations")
            )
            == 0
        )


def test_save_accepts_detached_entity_and_rejects_stale_independent_session(database, repository):
    context = register_session(str(repository), "codex", "native", database_path=database)
    with storage_scope(database, write=False) as scope:
        detached = scope.get(ISessionRepository).get(context.session.id)
        stale = scope.get(ISessionRepository).get(context.session.id)
    original_version = detached.version
    detached.move(str(repository / "next"), detached.revision)
    assert detached.version != original_version
    with storage_scope(database) as scope:
        saved = scope.get(ISessionRepository).save(detached)
        assert saved.uid == detached.uid and saved.revision == 2
        assert saved.version == detached.version
        assert saved.created_at == detached.created_at
        assert saved.updated_at.tzinfo == UTC
    with pytest.raises(RevisionConflict) as failure:
        with storage_scope(database) as scope:
            stale.move("/stale", stale.revision)
            scope.get(ISessionRepository).save(stale)
    assert isinstance(failure.value.__cause__, VersionConflictError)
    current = get_session_context(context.project.id, context.session.id, database_path=database)
    assert current.session.revision == 2
    assert current.session.working_directory == str(repository / "next")


def test_real_moves_advance_version_and_same_path_is_a_noop(database, repository):
    context = register_session(str(repository), "codex", "native", database_path=database)
    with storage_scope(database) as scope:
        sessions = scope.get(ISessionRepository)
        entity = sessions.get(context.session.id)
        for revision in (1, 2, 3):
            target = repository / str(revision)
            target.mkdir()
            entity.move(str(target), revision)
            entity = sessions.save(entity)
            assert entity.revision == revision + 1
    result = move_session(
        context.project.id, context.session.id, str(repository / "3"), 4, database_path=database
    )
    assert result.session.revision == 4


def test_orm_flush_rejects_stale_identity_map_without_refreshing_it(database, repository):
    context = register_session(str(repository), "codex", "native", database_path=database)
    with pytest.raises(RevisionConflict) as failure:
        with request_container(DatabaseSettings(database, write=True)) as first:
            manager = first.get(SessionManager)
            manager.open()
            with manager.session.begin():
                retained = manager.session.get(SessionModel, context.session.id)
                stale = retained.to_domain()
            with storage_scope(database) as second:
                sessions = second.get(ISessionRepository)
                current = sessions.get(context.session.id)
                current.move("/winner", current.revision)
                assert sessions.save(current).revision == 2
            assert retained.revision == 1
            with manager.session.begin():
                stale.move("/stale", stale.revision)
                first.get(ISessionRepository).save(stale)
    assert isinstance(failure.value.__cause__, VersionConflictError)
    result = get_session_context(context.project.id, context.session.id, database_path=database)
    assert result.session.working_directory == "/winner" and result.session.revision == 2


def test_project_save_roundtrips_owned_locations_and_updates_the_whole_aggregate(database):
    project = Project.create(DirectoryObservation("/repo"))
    mapped = ProjectModel.from_domain(project)
    assert mapped.to_domain().locations == project.locations
    assert mapped.locations[0].project_id == project.uid
    with storage_scope(database) as scope:
        project = scope.get(IProjectRepository).save(project)
    project.associate(Project.identify(DirectoryObservation("/linked", "/repo/.git", "/repo")))
    with storage_scope(database) as scope:
        projects = scope.get(IProjectRepository)
        saved = projects.save(project)
        assert set(saved.locations) == set(project.locations)
        assert projects.save(saved).revision == saved.revision
    with storage_scope(database, write=False) as scope:
        loaded = scope.get(IProjectRepository).get(project.uid)
        assert set(loaded.locations) == set(project.locations)
        assert loaded.version == saved.version
        for location in project.locations:
            assert scope.get(IProjectRepository).find_by_location(location).uid == project.uid


@pytest.mark.parametrize("existing_parent", [False, True])
def test_cross_owner_aggregate_save_conflict_rolls_back_parent_and_children(
    database, existing_parent
):
    first = Project.create(DirectoryObservation("/first"))
    conflicting = Project.create(DirectoryObservation("/second"))
    original_locations = conflicting.locations
    with storage_scope(database) as scope:
        projects = scope.get(IProjectRepository)
        projects.save(first)
        if existing_parent:
            conflicting = projects.save(conflicting)
    conflicting.root_path = "/changed"
    conflicting.associate(first.locations)
    with pytest.raises(ProjectIdentityConflict):
        with storage_scope(database) as scope:
            scope.get(IProjectRepository).save(conflicting)
    with storage_scope(database, write=False) as scope:
        count = 2 if existing_parent else 1
        session = scope.get(SessionManager).session
        assert session.scalar(text("SELECT COUNT(*) FROM core_projects")) == count
        assert session.scalar(text("SELECT COUNT(*) FROM core_project_locations")) == count
        projects = scope.get(IProjectRepository)
        assert projects.get(first.uid).locations == first.locations
        if existing_parent:
            retained = projects.get(conflicting.uid)
            assert retained.root_path == "/second"
            assert retained.locations == original_locations


def test_session_save_inserts_and_returns_stored_entity(database):
    project = Project.create(DirectoryObservation("/repo"))
    entity = HostSession.create(project.uid, "codex", "new", "/repo")
    with storage_scope(database) as scope:
        scope.get(IProjectRepository).save(project)
        sessions = scope.get(ISessionRepository)
        stored = sessions.save(entity)
        assert stored == entity and stored.revision == 1
        assert sessions.get_or_none(entity.uid).version == entity.version
        assert sessions.find(project.uid, "codex", "new").uid == entity.uid
        assert sessions.find(project.uid, "claude", "new") is None
    with storage_scope(database, write=False) as scope:
        assert scope.get(ISessionRepository).get(entity.uid).revision == 1
        assert (
            scope.get(SessionManager).session.scalar(select(SessionModel.version)) == entity.version
        )
