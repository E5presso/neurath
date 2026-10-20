"""실제 Spakky 요청별 주입와 SQLAlchemy 병합 버전 검사 및 예외 정리를 검증한다."""

from dataclasses import asdict

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import RevisionConflict
from neurath.infrastructure.database import create_database_engine
from neurath.infrastructure.providers import DatabaseSettings, request_container
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.transport.session_requests import get_session_context, move_session, register_session


def test_spakky_injects_one_session_per_request_and_closes_it(database):
    with request_container(DatabaseSettings(database, write=True)) as first:
        first_session = first.get(Session)
        project_repo = first.get(IProjectRepository)
        usecase = first.get(RegisterSessionUseCase)
        assert usecase.projects.projects is project_repo
        assert usecase.sessions is first.get(ISessionRepository)
        assert usecase.sessions.session is project_repo.session is first_session
        with first_session.begin():
            first_session.execute(text("SELECT 1"))
    with pytest.raises(InvalidRequestError, match="permanently closed"):
        first_session.execute(text("SELECT 1"))
    with request_container(DatabaseSettings(database, write=True)) as second:
        assert second.get(Session) is not first_session
        assert second.get(IProjectRepository) is not project_repo
        assert second.get(RegisterSessionUseCase) is not usecase


def test_exception_rolls_back_and_spakky_request_closes_without_commit(database):
    events = []
    with pytest.raises(RuntimeError, match="abort"):
        with request_container(DatabaseSettings(database, write=True)) as scope:
            engine = scope.get(Engine)
            event.listen(engine, "commit", lambda connection: events.append("commit"))
            event.listen(engine, "rollback", lambda connection: events.append("rollback"))
            event.listen(engine, "close", lambda connection, record: events.append("close"))
            event.listen(engine, "engine_disposed", lambda connection: events.append("disposed"))
            session = scope.get(Session)
            with session.begin():
                session.execute(text("INSERT INTO core_projects VALUES ('abort', '/tmp')"))
                raise RuntimeError("abort")
    assert events == ["rollback", "close", "disposed"]
    with pytest.raises(InvalidRequestError, match="permanently closed"):
        session.execute(text("SELECT 1"))
    verification = create_database_engine(database, write=False)
    try:
        with verification.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM core_projects")) == 0
    finally:
        verification.dispose()


def test_save_accepts_detached_entity_and_rejects_stale_independent_session(database, repository):
    context = register_session(str(repository), "codex", "native", database_path=database)
    detached = HostSession(**asdict(context.session))
    stale = HostSession(**asdict(context.session))
    engine = create_database_engine(database, write=True)
    try:
        with Session(engine) as first, first.begin():
            detached.move(str(repository / "next"), detached.revision)
            saved = SessionRepository(first).save(detached)
            assert saved.id == detached.id and saved.revision == 2
        with pytest.raises(RevisionConflict):
            with Session(engine) as second, second.begin():
                stale.move("/stale", stale.revision)
                SessionRepository(second).save(stale)
        current = get_session_context(
            context.project.id, context.session.id, database_path=database
        )
        assert current.session.revision == 2
        assert current.session.working_directory == str(repository / "next")
    finally:
        engine.dispose()


def test_real_moves_advance_version_and_same_path_is_a_noop(database, repository):
    context = register_session(str(repository), "codex", "native", database_path=database)
    engine = create_database_engine(database, write=True)
    try:
        with Session(engine) as session, session.begin():
            sessions = SessionRepository(session)
            entity = sessions.get(context.project.id, context.session.id)
            for revision in (1, 2, 3):
                target = repository / str(revision)
                target.mkdir()
                entity.move(str(target), revision)
                entity = sessions.save(entity)
                assert entity.revision == revision + 1
    finally:
        engine.dispose()
    result = move_session(
        context.project.id, context.session.id, str(repository / "3"), 4, database_path=database
    )
    assert result.session.revision == 4


def test_orm_flush_rejects_stale_identity_map_without_refreshing_it(database, repository):
    from neurath.infrastructure.models.session import SessionModel

    context = register_session(str(repository), "codex", "native", database_path=database)
    engine = create_database_engine(database, write=True)
    try:
        with Session(engine, expire_on_commit=False) as first:
            with first.begin():
                retained_record = first.get(SessionModel, context.session.id)
                stale = retained_record.to_domain()
            with Session(engine) as second, second.begin():
                current = HostSession(**asdict(context.session))
                current.move("/winner", current.revision)
                assert SessionRepository(second).save(current).revision == 2
            assert retained_record.revision == 1
            with pytest.raises(RevisionConflict):
                with first.begin():
                    stale.move("/stale", stale.revision)
                    SessionRepository(first).save(stale)
        result = get_session_context(context.project.id, context.session.id, database_path=database)
        assert result.session.working_directory == "/winner" and result.session.revision == 2
    finally:
        engine.dispose()


def test_project_save_roundtrips_owned_locations_and_updates_the_whole_aggregate(database):
    from neurath.domain.aggregates.project import Project
    from neurath.domain.observations import DirectoryObservation
    from neurath.infrastructure.models.project import ProjectModel
    from neurath.infrastructure.repositories.project import ProjectRepository

    project = Project.create(DirectoryObservation("/repo"))
    mapped = ProjectModel.from_domain(project)
    assert mapped.to_domain().locations == project.locations
    assert mapped.locations[0].project_id == project.id
    engine = create_database_engine(database, write=True)
    try:
        with Session(engine) as session, session.begin():
            saved = ProjectRepository(session).save(project)
            assert saved.id == project.id and saved.locations == project.locations
        project.associate(Project.identify(DirectoryObservation("/linked", "/repo/.git", "/repo")))
        with Session(engine) as session, session.begin():
            saved = ProjectRepository(session).save(project)
            assert set(saved.locations) == set(project.locations)
            assert ProjectRepository(session).save(saved).locations == saved.locations
        with Session(engine) as session, session.begin():
            repository = ProjectRepository(session)
            loaded = repository.get(project.id)
            assert set(loaded.locations) == set(project.locations)
            for location in project.locations:
                assert repository.find_by_location(location).id == project.id
    finally:
        engine.dispose()


@pytest.mark.parametrize("existing_parent", [False, True])
def test_cross_owner_aggregate_save_conflict_rolls_back_parent_and_children(
    database, existing_parent
):
    from neurath.domain.aggregates.project import Project
    from neurath.domain.errors import ProjectIdentityConflict
    from neurath.domain.observations import DirectoryObservation
    from neurath.infrastructure.repositories.project import ProjectRepository

    first = Project.create(DirectoryObservation("/first"))
    conflicting = Project.create(DirectoryObservation("/second"))
    original_locations = conflicting.locations
    engine = create_database_engine(database, write=True)
    try:
        with Session(engine) as session, session.begin():
            ProjectRepository(session).save(first)
            if existing_parent:
                ProjectRepository(session).save(conflicting)
        conflicting.root_path = "/changed"
        conflicting.associate(first.locations)
        with pytest.raises(ProjectIdentityConflict):
            with Session(engine) as session, session.begin():
                ProjectRepository(session).save(conflicting)
        with Session(engine) as session, session.begin():
            count = 2 if existing_parent else 1
            assert session.scalar(text("SELECT COUNT(*) FROM core_projects")) == count
            assert session.scalar(text("SELECT COUNT(*) FROM core_project_locations")) == count
            assert ProjectRepository(session).get(first.id).locations == first.locations
            if existing_parent:
                retained = ProjectRepository(session).get(conflicting.id)
                assert retained.root_path == "/second"
                assert retained.locations == original_locations
    finally:
        engine.dispose()


def test_session_save_inserts_and_returns_stored_entity(database):
    from neurath.domain.aggregates.project import Project
    from neurath.domain.observations import DirectoryObservation
    from neurath.infrastructure.repositories.project import ProjectRepository

    project = Project.create(DirectoryObservation("/repo"))
    entity = HostSession.create(project.id, "codex", "new", "/repo")
    engine = create_database_engine(database, write=True)
    try:
        with Session(engine) as session, session.begin():
            ProjectRepository(session).save(project)
            stored = SessionRepository(session).save(entity)
            assert stored == entity and stored.revision == 1
        with Session(engine) as session, session.begin():
            assert SessionRepository(session).get(project.id, entity.id).revision == 1
    finally:
        engine.dispose()
