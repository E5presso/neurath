"""Actual Dishka scopes, SQLAlchemy merge versioning, and exception cleanup."""

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


def test_dishka_scopes_inject_one_session_per_request_and_close_it(database):
    container = request_container(DatabaseSettings(database, write=True))
    try:
        with container() as first:
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
        with container() as second:
            assert second.get(Session) is not first_session
            assert second.get(IProjectRepository) is not project_repo
            assert second.get(RegisterSessionUseCase) is not usecase
    finally:
        container.close()


def test_exception_rolls_back_and_di_closes_connection_without_commit(database):
    container = request_container(DatabaseSettings(database, write=True))
    events = []
    engine = container.get(Engine)
    event.listen(engine, "commit", lambda connection: events.append("commit"))
    event.listen(engine, "rollback", lambda connection: events.append("rollback"))
    event.listen(engine, "close", lambda connection, record: events.append("close"))
    event.listen(engine, "engine_disposed", lambda connection: events.append("disposed"))
    try:
        with pytest.raises(RuntimeError, match="abort"):
            with container() as scope:
                session = scope.get(Session)
                with session.begin():
                    session.execute(text("INSERT INTO core_projects VALUES ('abort', '/tmp')"))
                    raise RuntimeError("abort")
        assert events == ["rollback", "close"]
        with pytest.raises(InvalidRequestError, match="permanently closed"):
            session.execute(text("SELECT 1"))
    finally:
        container.close()
    assert events == ["rollback", "close", "disposed"]
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
