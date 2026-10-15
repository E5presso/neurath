"""Behavior of the new core; every DB is isolated from installed/user state."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError, OperationalError

from neurath.domain.core import ContextNotFound, CoreError, StorageNotReady
from neurath.infrastructure.core_database import CoreDatabase, user_database_path
from neurath.infrastructure.core_schema import sessions
from neurath.transport.core_requests import build_core


def git(folder, *args):
    return subprocess.run(
        ["git", "-C", str(folder), *args],
        capture_output=True,
        text=True,
        check=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    ).stdout.strip()


@pytest.fixture
def database(tmp_path):
    database = CoreDatabase(tmp_path / "user" / "core.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "initial",
    )
    return repo


# Independent process calls the composition boundary used by either adapter.
# No fixture passes an in-memory Core, SQLAlchemy connection, or context cache.
PROCESS = """
import json,sys
from pathlib import Path
from dataclasses import asdict
from neurath.transport.core_requests import build_core
from neurath.domain.core import RevisionConflict
core = build_core(Path(sys.argv[1]))
mode = sys.argv[2]
try:
    if mode == "open":
        result = core.open_session(sys.argv[3], sys.argv[4], sys.argv[5])
    elif mode == "get":
        result = core.get_context(sys.argv[3], sys.argv[4])
    elif mode == "move":
        result = core.move_session(sys.argv[3],sys.argv[4],sys.argv[5],int(sys.argv[6]))
    print(json.dumps(asdict(result)))
except RevisionConflict:
    print(json.dumps({"conflict": True}))
"""


def request(path, mode, *args):
    result = subprocess.run(
        [sys.executable, "-c", PROCESS, str(path), mode, *map(str, args)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_same_user_path_does_not_depend_on_project_or_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    expected = tmp_path / "data" / "neurath" / "core.sqlite3"
    monkeypatch.chdir(tmp_path)
    assert user_database_path() == expected
    nested = tmp_path / "unrelated"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert CoreDatabase().path == expected
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    with pytest.raises(ValueError, match="absolute"):
        user_database_path()


def test_restart_reads_committed_context_and_updates_it(database, repository):
    opened = request(database.path, "open", repository, "codex", "same-native-id")
    project, session = opened["project"]["id"], opened["session"]["id"]
    assert request(database.path, "get", project, session) == opened
    nested = repository / "nested"
    nested.mkdir()
    changed = request(database.path, "move", project, session, nested, 1)
    assert changed["session"]["revision"] == 2
    assert request(database.path, "get", project, session) == changed
    # Repeated registration after a delayed hook cannot revert latest cwd.
    assert request(database.path, "open", repository, "codex", "same-native-id") == changed


def test_primary_linked_worktree_and_subdirectory_share_project(database, repository, tmp_path):
    linked = tmp_path / "linked"
    git(repository, "worktree", "add", "-b", "feature", str(linked))
    nested = linked / "src"
    nested.mkdir()
    core = build_core(database.path)
    values = [
        core.open_session(str(p), "codex", str(i))
        for i, p in enumerate((repository, linked, nested))
    ]
    assert len({value.project.id for value in values}) == 1
    assert len({value.session.id for value in values}) == 3
    assert [value.session.working_directory for value in values] == list(
        map(str, (repository, linked, nested))
    )


def test_clones_with_same_remote_and_session_name_are_isolated(database, repository, tmp_path):
    clone_a, clone_b = tmp_path / "a", tmp_path / "b"
    git(tmp_path, "clone", str(repository), str(clone_a))
    git(tmp_path, "clone", str(repository), str(clone_b))
    assert git(clone_a, "remote", "get-url", "origin") == git(
        clone_b, "remote", "get-url", "origin"
    )
    core = build_core(database.path)
    a, b = [core.open_session(str(p), "claude", "same") for p in (clone_a, clone_b)]
    assert a.project.id != b.project.id
    assert a.session.id != b.session.id
    with pytest.raises(ContextNotFound):
        core.get_context(a.project.id, b.session.id)
    assert core.get_context(a.project.id, a.session.id) == a
    with pytest.raises(ContextNotFound):
        core.move_session(a.project.id, a.session.id, str(clone_b), 1)
    assert core.get_context(a.project.id, a.session.id) == a


def test_git_init_keeps_project_and_dependent_records_even_from_linked_tree(database, tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    before = build_core(database.path).open_session(str(folder), "codex", "native")
    # A fixture relation models records owned by later domains. It is not a fake
    # production task/memory API: identity promotion must preserve every FK.
    with database.transaction(write=True) as work:
        work.connection.exec_driver_sql(
            "CREATE TABLE owned_fixture (project_id TEXT REFERENCES core_projects(id), value TEXT)"
        )
        work.connection.execute(
            text("INSERT INTO owned_fixture VALUES (:id, :value)"),
            {"id": before.project.id, "value": "unfinished original source"},
        )
    git(folder, "init", "--initial-branch=main")
    git(
        folder,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "init",
    )
    linked = tmp_path / "new-worktree"
    git(folder, "worktree", "add", "-b", "branch", str(linked))
    after = request(database.path, "open", linked, "codex", "another")
    assert after["project"]["id"] == before.project.id
    assert request(database.path, "get", before.project.id, before.session.id) == asdict(before)
    with database.transaction() as work:
        assert work.connection.execute(text("SELECT * FROM owned_fixture")).one() == (
            before.project.id,
            "unfinished original source",
        )


def test_host_providers_are_separate_within_project(database, repository):
    core = build_core(database.path)
    a = core.open_session(str(repository), "codex", "native")
    b = core.open_session(str(repository), "claude", "native")
    assert a.project == b.project
    assert a.session.id != b.session.id


def test_parallel_registration_deduplicates_across_processes(database, repository):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: request(database.path, "open", repository, "codex", "same"), range(8)
            )
        )
    assert all(result == results[0] for result in results)


def test_parallel_updates_have_one_winner_and_preserve_revision(database, repository):
    opened = build_core(database.path).open_session(str(repository), "codex", "native")
    dirs = [repository / "left", repository / "right"]
    for directory in dirs:
        directory.mkdir()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda path: request(
                    database.path, "move", opened.project.id, opened.session.id, path, 1
                ),
                dirs,
            )
        )
    winners = [result for result in results if "conflict" not in result]
    assert len(winners) == 1
    assert winners[0]["session"]["revision"] == 2
    assert request(database.path, "get", opened.project.id, opened.session.id) == winners[0]


def test_failed_request_rolls_back_related_changes(database, repository):
    core = build_core(database.path)
    original = core.open_session(str(repository), "codex", "one")
    with pytest.raises(RuntimeError, match="injected failure"):
        with database.transaction(write=True) as work:
            work.identities.move_session(original.session, str(repository / "new"), 1)
            work.identities.add_session(original.project.id, "codex", "two", str(repository))
            raise RuntimeError("injected failure")
    assert core.get_context(original.project.id, original.session.id) == original
    with database.transaction() as work:
        assert work.identities.find_session(original.project.id, "codex", "two") is None


def test_reader_sees_no_uncommitted_state_and_cannot_write(database, repository):
    original = build_core(database.path).open_session(str(repository), "codex", "one")
    with database.transaction(write=True) as writer:
        writer.identities.move_session(original.session, str(repository / "uncommitted"), 1)
        assert request(database.path, "get", original.project.id, original.session.id) == asdict(
            original
        )
    with database.transaction() as reader:
        with pytest.raises(OperationalError, match="readonly"):
            reader.connection.execute(text("DELETE FROM core_sessions"))


def test_connection_is_released_before_external_action(database, repository):
    first = build_core(database.path).open_session(str(repository), "codex", "one")
    # Simulated host operation performs an independent write. No original lock or
    # open transaction survives the request, including after an exception above.
    second = request(database.path, "open", repository, "codex", "external-result")
    assert second["project"]["id"] == first.project.id


def test_foreign_keys_are_enforced(database):
    with pytest.raises(IntegrityError):
        with database.transaction(write=True) as work:
            work.connection.execute(
                insert(sessions).values(
                    id="bad",
                    project_id="missing",
                    provider="codex",
                    host_session_id="x",
                    working_directory="/tmp",
                    revision=1,
                )
            )


def test_initialization_is_explicit_idempotent_and_rejects_legacy(tmp_path):
    import sqlite3

    missing = CoreDatabase(tmp_path / "missing.sqlite3")
    with pytest.raises(StorageNotReady):
        with missing.transaction():
            pass
    assert not missing.path.exists()
    missing.initialize()
    core = build_core(missing.path)
    context = core.open_session(str(tmp_path), "codex", "one")
    missing.initialize()
    assert core.get_context(context.project.id, context.session.id) == context
    legacy = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE task (source TEXT)")
        connection.execute("INSERT INTO task VALUES ('unfinished')")
    original = legacy.read_bytes()
    with pytest.raises(StorageNotReady, match="migration"):
        CoreDatabase(legacy).initialize()
    assert legacy.read_bytes() == original


def test_concurrent_initializers_and_wrong_version(tmp_path):
    path = tmp_path / "shared.sqlite3"
    script = "from neurath.infrastructure.core_database import CoreDatabase; from pathlib import Path; import sys; CoreDatabase(Path(sys.argv[1])).initialize()"
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(
            pool.map(
                lambda _: subprocess.run([sys.executable, "-c", script, str(path)], check=True),
                range(3),
            )
        )
    database = CoreDatabase(path)
    with database.transaction(write=True) as work:
        work.connection.exec_driver_sql("UPDATE core_schema_revision SET version_num = 'future'")
    with pytest.raises(StorageNotReady, match="version"):
        with database.transaction():
            pass


def test_git_environment_does_not_override_request_directory(
    database, repository, tmp_path, monkeypatch
):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_DIR", str(repository / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(repository))
    core = build_core(database.path)
    a = core.open_session(str(repository), "codex", "one")
    b = core.open_session(str(plain), "codex", "one")
    assert a.project.id != b.project.id


def test_git_failure_is_not_silently_treated_as_a_new_folder(database, repository, monkeypatch):
    from neurath.infrastructure import project_location

    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(args, 128, "", "fatal: detected dubious ownership")

    monkeypatch.setattr(project_location.subprocess, "run", fail)
    with pytest.raises(CoreError, match="dubious ownership"):
        build_core(database.path).open_session(str(repository), "codex", "one")
