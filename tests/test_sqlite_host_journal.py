"""Host metadata commits in SQLite without changing native identity semantics."""
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture
def host_root(tmp_path, monkeypatch):
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness import session_kernel as sk
    from neurath.hosts import identity
    locator = sk.SessionLocator(tmp_path)
    monkeypatch.setattr(identity, "_locator", lambda root: locator)
    sk.SessionKernel(locator).apply(sk.SessionStarted(session_id=sk.SessionId("one"),
        resume_id=sk.ResumeId("resume"), root_actor_id=sk.ActorId("owner"),
        runtime=sk.SessionRuntime.CODEX, idempotency_key="start"))
    return tmp_path, identity


def test_host_journal_uses_sqlite_and_preserves_current_metadata(host_root):
    root, identity = host_root
    with identity.journal(root, "one") as data:
        data.update(host="codex", connected=True, transcript="observed")
    assert identity.snapshot(root, "one")["transcript"] == "observed"
    assert not list(root.glob("**/.neurath-host.json"))
    assert identity.snapshot(root, "other") == {"session": "other", "spawns": {}, "tools": {}}


def test_host_journal_failure_does_not_publish_partial_metadata(host_root):
    root, identity = host_root
    with identity.journal(root, "one") as data:
        data["host"] = "codex"
    with pytest.raises(RuntimeError):
        with identity.journal(root, "one") as data:
            data["host"] = "wrong"
            raise RuntimeError("interrupted")
    assert identity.snapshot(root, "one")["host"] == "codex"


def test_host_journal_concurrent_updates_preserve_every_change(host_root):
    root, identity = host_root
    def add(index):
        with identity.journal(root, "one") as data:
            data["spawns"][str(index)] = {"child": str(index)}
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(add, range(8)))
    assert len(identity.snapshot(root, "one")["spawns"]) == 8
