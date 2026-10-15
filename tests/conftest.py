"""Isolated filesystem, database, and Git fixtures for the candidate implementation."""

import os
import subprocess

import pytest

from neurath.infrastructure.database import SqliteDatabase


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
    database = SqliteDatabase(tmp_path / "user" / "identity.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def repository(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    initialize_git(repository)
    return repository
