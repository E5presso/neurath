"""A failed probe handshake must not orphan its owned host or open evidence files."""
import importlib
import io
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast


@pytest.fixture
def host_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "tools"))
    from native_steering_probe import Host
    return importlib.import_module(Host.__module__)


class Process:
    def __init__(self, *, stubborn=False):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
        self.returncode = None
        self.stubborn = stubborn
        self.actions = []

    def wait(self, timeout):
        self.actions.append("wait")
        if self.stubborn and "kill" not in self.actions:
            raise subprocess.TimeoutExpired("owned-test-host", timeout)
        self.returncode = 0
        return 0

    def terminate(self):
        self.actions.append("terminate")

    def kill(self):
        self.actions.append("kill")


def test_failed_initial_handshake_closes_owned_process_and_evidence(host_module, tmp_path, monkeypatch):
    process = Process()
    logs = []
    def launch(*args, **kwargs):
        logs.append(kwargs["stderr"])
        return process
    monkeypatch.setattr(host_module.subprocess, "Popen", launch)
    monkeypatch.setattr(host_module.Host, "_read", lambda self: None)
    def reject(*args):
        raise RuntimeError("initialization rejected")
    monkeypatch.setattr(host_module.Host, "request", reject)
    with pytest.raises(RuntimeError, match="initialization rejected"):
        host_module.Host(tmp_path, tmp_path)
    assert process.stdin.closed
    assert process.returncode == 0
    assert logs[0].closed


def test_close_escalates_only_owned_process_and_is_idempotent(host_module, tmp_path, monkeypatch):
    process = Process(stubborn=True)
    monkeypatch.setattr(host_module.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(host_module.Host, "_read", lambda self: None)
    monkeypatch.setattr(host_module.Host, "request", lambda *args: {})
    host = host_module.Host(tmp_path, tmp_path)
    host.close()
    actions = list(process.actions)
    host.close()
    assert process.actions == actions == ["wait", "terminate", "wait", "kill", "wait"]
    assert process.stdin.closed and host.log.closed and host.stderr.closed
