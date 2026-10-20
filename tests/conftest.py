"""후보 구현을 위한 격리된 파일 시스템·데이터베이스·Git fixture를 제공한다."""

import os
import subprocess
from contextlib import contextmanager

import pytest
from spakky.plugins.sqlalchemy.persistency.transaction import Transaction

from neurath.infrastructure.database import initialize_database
from neurath.infrastructure.providers import DatabaseSettings, request_container


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


@pytest.fixture
def database(tmp_path):
    database = tmp_path / "user" / "identity.sqlite3"
    initialize_database(database)
    return database


@pytest.fixture
def repository(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    initialize_git(repository)
    return repository


@contextmanager
def storage_scope(database, *, write=True):
    with request_container(DatabaseSettings(database, write=write)) as scope:
        with scope.get(Transaction):
            yield scope
