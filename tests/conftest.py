"""후보 구현을 위한 격리된 파일 시스템·데이터베이스·Git fixture를 제공한다."""

import os
import sqlite3
import subprocess
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
import pytest_asyncio
from spakky.plugins.sqlalchemy.persistency.transaction import AsyncTransaction

from neurath.infrastructure.database import initialize_database
from tests.support.application import request_application_lifetime, spakky_context
from tests.support.database import copy_empty_database

# 원시 SQL 검증에서도 Uuid의 SQLite 저장 표현인 32자리 hex를 사용한다.
sqlite3.register_adapter(UUID, lambda value: value.hex)


def git(directory, *arguments):
    return subprocess.run(
        ["git", "-C", str(directory), *arguments],
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def initialize_git(directory):
    git(directory, "init", "--initial-branch=main")
    git(
        directory,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "initial",
    )


@pytest.fixture(autouse=True)
async def application_lifetime():
    async with request_application_lifetime():
        yield


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def empty_database_template(tmp_path_factory):
    template = tmp_path_factory.mktemp("empty-schema") / "template.sqlite3"
    await initialize_database(template)
    return template


@pytest.fixture
async def database(tmp_path, empty_database_template):
    return copy_empty_database(empty_database_template, tmp_path / "user" / "identity.sqlite3")


@pytest.fixture
def repository(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    initialize_git(repository)
    return repository


@asynccontextmanager
async def storage_scope(database, *, write=True):
    async with spakky_context(database, write=write) as scope:
        async with scope.get(AsyncTransaction):
            yield scope


@pytest.fixture(autouse=True)
def recovery_record_directory(tmp_path, monkeypatch):
    """시험의 고의적인 장애 기록이 사용자 상태 디렉터리에 기록되지 않게 한다."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
