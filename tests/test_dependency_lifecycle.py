"""표준 저장소 CRUD와 실제 프레임워크 자원 수명 및 낙관적 잠금을 검증한다."""

from datetime import UTC

import pytest
from spakky.data.persistency.aggregate_collector import AggregateCollector
from spakky.data.persistency.repository import (
    EntityNotFoundError,
    IAsyncGenericRepository,
    VersionConflictError,
)
from spakky.plugins.sqlalchemy.orm.schema_registry import SchemaRegistry
from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from spakky.plugins.sqlalchemy.persistency.session_manager import (
    AsyncSessionManager,
    SessionNotInitializedError,
)
from spakky.plugins.sqlalchemy.persistency.transaction import AsyncTransaction
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession
from neurath.domain.observations import DirectoryObservation
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.repositories.project import SQLAlchemyProjectRepository
from neurath.infrastructure.repositories.session import SQLAlchemySessionRepository
from tests.conftest import storage_scope
from tests.support.application import spakky_context
from tests.support.session_requests import (
    get_session_context,
    move_session,
    register_session,
)


def test_basic_contracts_and_methods_are_inherited_without_local_reimplementation():
    for repository, port in (
        (SQLAlchemyProjectRepository, IProjectRepository),
        (SQLAlchemySessionRepository, ISessionRepository),
    ):
        assert issubclass(port, IAsyncGenericRepository)
        assert issubclass(repository, AbstractAsyncGenericRepository)
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
            assert getattr(repository, method) is getattr(AbstractAsyncGenericRepository, method)
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


async def test_spakky_injects_standard_managers_registry_collector_and_repositories(database):
    async with spakky_context(database, write=True) as scope:
        manager = scope.get(AsyncSessionManager)
        usecase = scope.get(RegisterSessionUseCase)
        projects = scope.get(IProjectRepository)
        assert usecase.projects is projects
        assert usecase.sessions is scope.get(ISessionRepository)
        assert projects._session_manager is usecase.sessions._session_manager is manager
        assert projects._schema_registry is scope.get(SchemaRegistry)
        assert projects._aggregate_collector is scope.get(AggregateCollector)
        assert scope.get(SchemaRegistry).get_type(Project) is ProjectModel
        assert scope.get(SchemaRegistry).get_type(HostSession) is SessionModel
        async with scope.get(AsyncTransaction):
            first_session = manager.session
            assert (await first_session.scalar(text("SELECT 1"))) == 1
        with pytest.raises(SessionNotInitializedError):
            manager.session
    async with spakky_context(database, write=True) as second:
        assert second.get(AsyncSessionManager) is not manager
        assert second.get(IProjectRepository) is not projects
        async with second.get(AsyncTransaction):
            assert second.get(AsyncSessionManager).session is not first_session


async def test_package_scan_discovers_all_current_usecases_repositories_and_models(database):
    import importlib
    import inspect
    import pkgutil

    from spakky.core.pod.annotations.pod import Pod
    from spakky.plugins.sqlalchemy.orm.table import Table

    import neurath.application.usecases as usecases
    import neurath.infrastructure.models as models
    import neurath.infrastructure.repositories as repositories

    async with spakky_context(database) as context:
        for package in (usecases, repositories, models):
            for item in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
                module = importlib.import_module(item.name)
                for _, component in inspect.getmembers(module, inspect.isclass):
                    if component.__module__ != module.__name__:
                        continue
                    if Pod.exists(component):
                        assert context.contains(component), component
                    if Table.exists(component):
                        assert Table.get(component) in context.tags


async def test_exception_rolls_back_and_framework_closes_without_commit(database):
    events = []
    with pytest.raises(RuntimeError, match="abort"):
        async with spakky_context(database, write=True) as scope:
            engine = scope.get(AsyncConnectionManager).connection
            event.listen(engine.sync_engine, "commit", lambda connection: events.append("commit"))
            event.listen(
                engine.sync_engine, "rollback", lambda connection: events.append("rollback")
            )
            event.listen(
                engine.sync_engine, "close", lambda connection, record: events.append("close")
            )
            event.listen(
                engine.sync_engine, "engine_disposed", lambda connection: events.append("disposed")
            )
            manager = scope.get(AsyncSessionManager)
            async with scope.get(AsyncTransaction):
                (
                    await manager.session.execute(
                        text("INSERT INTO core_projects (id, root_path) VALUES ('abort', '/tmp')")
                    )
                )
                raise RuntimeError("abort")
    assert events == ["rollback", "close", "disposed"]
    with pytest.raises(SessionNotInitializedError):
        manager.session
    async with storage_scope(database, write=False) as scope:
        assert (
            await scope.get(AsyncSessionManager).session.scalar(
                text("SELECT COUNT(*) FROM core_projects")
            )
        ) == 0


async def test_inherited_crud_batch_delete_and_missing_contracts(database):
    first = Project.create(DirectoryObservation(working_directory="/first"))
    second = Project.create(DirectoryObservation(working_directory="/second"))
    async with storage_scope(database) as scope:
        projects = scope.get(IProjectRepository)
        assert (await projects.get_or_none("missing")) is None
        assert not (await projects.contains("missing"))
        saved = await projects.save_all((first, second))
        assert {item.uid for item in saved} == {first.uid, second.uid}
        assert await projects.contains(first.uid)
        assert {
            item.uid for item in (await projects.range((second.uid, first.uid, "missing")))
        } == {
            first.uid,
            second.uid,
        }
        assert (await projects.range(())) == []
        collector = scope.get(AggregateCollector)
        assert {item.uid for item in collector.all()} == {first.uid, second.uid}
        deleted = await projects.delete_all(saved)
        assert {item.uid for item in deleted} == {first.uid, second.uid}
        assert (await projects.range((first.uid, second.uid))) == []
    with pytest.raises(EntityNotFoundError):
        async with storage_scope(database, write=False) as scope:
            (await scope.get(IProjectRepository).get(first.uid))
    async with storage_scope(database) as scope:
        projects = scope.get(IProjectRepository)
        restored = await projects.save(first)
        assert (await projects.delete(restored)).uid == first.uid
        assert (await projects.get_or_none(first.uid)) is None
        assert (
            await scope.get(AsyncSessionManager).session.scalar(
                text("SELECT COUNT(*) FROM core_project_locations")
            )
        ) == 0


async def test_save_accepts_detached_entity_and_rejects_stale_independent_session(
    database, repository
):
    context = await register_session(str(repository), "codex", "native", database_path=database)
    async with storage_scope(database, write=False) as scope:
        detached = await scope.get(ISessionRepository).get(context.session.id)
        stale = await scope.get(ISessionRepository).get(context.session.id)
    original_version = detached.version
    detached.move(str(repository / "next"), detached.revision)
    assert detached.version != original_version
    async with storage_scope(database) as scope:
        saved = await scope.get(ISessionRepository).save(detached)
        assert saved.uid == detached.uid and saved.revision == 2
        assert saved.version == detached.version
        assert saved.created_at == detached.created_at
        assert saved.updated_at.tzinfo == UTC
    with pytest.raises(VersionConflictError):
        async with storage_scope(database) as scope:
            stale.move("/stale", stale.revision)
            (await scope.get(ISessionRepository).save(stale))
    current = await get_session_context(
        context.project.id, context.session.id, database_path=database
    )
    assert current.session.revision == 2
    assert current.session.working_directory == str(repository / "next")


async def test_real_moves_advance_version_and_same_path_is_a_noop(database, repository):
    context = await register_session(str(repository), "codex", "native", database_path=database)
    async with storage_scope(database) as scope:
        sessions = scope.get(ISessionRepository)
        entity = await sessions.get(context.session.id)
        for revision in (1, 2, 3):
            target = repository / str(revision)
            target.mkdir()
            entity.move(str(target), revision)
            entity = await sessions.save(entity)
            assert entity.revision == revision + 1
    result = await move_session(
        context.project.id, context.session.id, str(repository / "3"), 4, database_path=database
    )
    assert result.session.revision == 4


async def test_orm_flush_rejects_stale_identity_map_without_refreshing_it(database, repository):
    context = await register_session(str(repository), "codex", "native", database_path=database)
    with pytest.raises(VersionConflictError):
        async with spakky_context(database, write=True) as first:
            manager = first.get(AsyncSessionManager)
            (await manager.open())
            async with manager.session.begin():
                retained = await manager.session.get(SessionModel, context.session.id)
                stale = retained.to_domain()
            async with storage_scope(database) as second:
                sessions = second.get(ISessionRepository)
                current = await sessions.get(context.session.id)
                current.move("/winner", current.revision)
                assert (await sessions.save(current)).revision == 2
            assert retained.revision == 1
            async with manager.session.begin():
                stale.move("/stale", stale.revision)
                (await first.get(ISessionRepository).save(stale))
    result = await get_session_context(
        context.project.id, context.session.id, database_path=database
    )
    assert result.session.working_directory == "/winner" and result.session.revision == 2
    await manager.close()


async def test_project_save_roundtrips_owned_locations_and_updates_the_whole_aggregate(database):
    project = Project.create(DirectoryObservation(working_directory="/repo"))
    mapped = ProjectModel.from_domain(project)
    assert mapped.to_domain().locations == project.locations
    assert mapped.locations[0].project_id == project.uid
    async with storage_scope(database) as scope:
        project = await scope.get(IProjectRepository).save(project)
    project.associate(
        Project.identify(
            DirectoryObservation(
                working_directory="/linked",
                git_common_directory="/repo/.git",
                primary_worktree="/repo",
            )
        )
    )
    async with storage_scope(database) as scope:
        projects = scope.get(IProjectRepository)
        saved = await projects.save(project)
        assert set(saved.locations) == set(project.locations)
        assert (await projects.save(saved)).revision == saved.revision
    async with storage_scope(database, write=False) as scope:
        loaded = await scope.get(IProjectRepository).get(project.uid)
        assert set(loaded.locations) == set(project.locations)
        assert loaded.version == saved.version
        for location in project.locations:
            assert (
                await scope.get(AsyncSessionManager).session.scalar(
                    select(ProjectLocationModel.project_id).where(
                        ProjectLocationModel.kind == location.kind.value,
                        ProjectLocationModel.path == location.path,
                    )
                )
                == project.uid
            )


@pytest.mark.parametrize("existing_parent", [False, True])
async def test_cross_owner_aggregate_save_conflict_rolls_back_parent_and_children(
    database, existing_parent
):
    first = Project.create(DirectoryObservation(working_directory="/first"))
    conflicting = Project.create(DirectoryObservation(working_directory="/second"))
    original_locations = conflicting.locations
    async with storage_scope(database) as scope:
        projects = scope.get(IProjectRepository)
        (await projects.save(first))
        if existing_parent:
            conflicting = await projects.save(conflicting)
    conflicting.root_path = "/changed"
    conflicting.associate(first.locations)
    with pytest.raises(IntegrityError, match="Location already belongs"):
        async with storage_scope(database) as scope:
            (await scope.get(IProjectRepository).save(conflicting))
    async with storage_scope(database, write=False) as scope:
        count = 2 if existing_parent else 1
        session = scope.get(AsyncSessionManager).session
        assert (await session.scalar(text("SELECT COUNT(*) FROM core_projects"))) == count
        assert (await session.scalar(text("SELECT COUNT(*) FROM core_project_locations"))) == count
        projects = scope.get(IProjectRepository)
        assert (await projects.get(first.uid)).locations == first.locations
        if existing_parent:
            retained = await projects.get(conflicting.uid)
            assert retained.root_path == "/second"
            assert retained.locations == original_locations


async def test_session_save_inserts_and_returns_stored_entity(database):
    project = Project.create(DirectoryObservation(working_directory="/repo"))
    entity = HostSession.create(project.uid, "codex", "new", "/repo")
    async with storage_scope(database) as scope:
        (await scope.get(IProjectRepository).save(project))
        sessions = scope.get(ISessionRepository)
        stored = await sessions.save(entity)
        assert stored == entity and stored.revision == 1
        assert (await sessions.get_or_none(entity.uid)).version == entity.version
        assert (
            await scope.get(AsyncSessionManager).session.scalar(
                select(SessionModel.id).where(
                    SessionModel.project_id == project.uid,
                    SessionModel.provider == "codex",
                    SessionModel.host_session_id == "new",
                )
            )
            == entity.uid
        )
        assert (
            await scope.get(AsyncSessionManager).session.scalar(
                select(SessionModel.id).where(SessionModel.provider == "claude")
            )
            is None
        )
    async with storage_scope(database, write=False) as scope:
        assert (await scope.get(ISessionRepository).get(entity.uid)).revision == 1
        assert (
            await scope.get(AsyncSessionManager).session.scalar(select(SessionModel.version))
        ) == entity.version


async def test_unimplemented_aggregate_lookups_fail_explicitly():
    from neurath.application.ports.repositories.execution import IExecutionRepository
    from neurath.application.ports.repositories.task import ITaskRepository
    from neurath.application.ports.repositories.workflow import IWorkflowRepository
    from neurath.application.ports.repositories.writer import IWriterRepository
    from neurath.domain.aggregates.project import ProjectKind, ProjectLocation

    operations = (
        (
            IProjectRepository.find_by_location,
            (None, ProjectLocation(kind=ProjectKind.FOLDER, path="/repo")),
        ),
        (
            ISessionRepository.find_by_project_id_and_provider_and_host_session_id,
            (None, "project", "codex", "native"),
        ),
        (IExecutionRepository.find_by_session_id_and_agent_id, (None, "session", "agent")),
        (IWriterRepository.find_by_resource, (None, "/repo")),
        (IWorkflowRepository.find_by_task_id, (None, "task")),
        (ITaskRepository.find_by_project_id, (None, "project")),
    )
    for operation, arguments in operations:
        with pytest.raises(NotImplementedError):
            await operation(*arguments)
