"""The packaged Codex relaunch helper refuses foreign processes and dry runs safely."""

import importlib.util
import plistlib
import subprocess
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src/neurath/_assets/.agents/skills/reconnect-host/scripts/relaunch_codex.py"
)
SPEC = importlib.util.spec_from_file_location("relaunch_codex_skill", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
relaunch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relaunch)


def app_executable(tmp_path, bundle_id):
    executable = tmp_path / "Codex.app/Contents/MacOS/Codex"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture")
    with (executable.parent.parent / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": bundle_id}, handle)
    return executable


def test_relaunch_rejects_a_pid_owned_by_another_app(tmp_path, monkeypatch):
    foreign = app_executable(tmp_path, "com.example.other")
    monkeypatch.setattr(
        relaunch.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, f"{foreign}\n", ""),
    )

    with pytest.raises(relaunch.RelaunchError, match="does not belong to the Codex app"):
        relaunch._app_executable(12345)


def test_validated_plan_does_not_create_an_agent_or_stop_the_app(tmp_path, monkeypatch):
    executable = app_executable(tmp_path, "com.openai.codex")
    calls = []

    def observed(command, **kwargs):
        calls.append(command)
        assert command[:2] == ["/bin/ps", "-p"]
        return subprocess.CompletedProcess(command, 0, f"{executable}\n", "")

    monkeypatch.setattr(relaunch.subprocess, "run", observed)
    monkeypatch.setattr(relaunch.sys, "platform", "darwin")
    monkeypatch.setattr(relaunch.Path, "home", classmethod(lambda cls: tmp_path))

    result = relaunch.schedule(
        "01a0f09e-13ad-7043-b1c8-aa5a5d0131cc", 12345, "issue-109", 45, False
    )

    assert result["status"] == "planned"
    assert len(calls) == 1
    assert not (tmp_path / "Library/LaunchAgents").exists()


def test_cleanup_without_an_owned_plan_does_not_bootout_a_foreign_job(tmp_path, monkeypatch):
    monkeypatch.setattr(relaunch.sys, "platform", "darwin")
    monkeypatch.setattr(relaunch.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        relaunch.subprocess, "run", lambda *args, **kwargs: pytest.fail("foreign launchctl call")
    )

    assert relaunch.cleanup(
        "01a0f09e-13ad-7043-b1c8-aa5a5d0131cc", "missing-plan"
    )["status"] == "absent"


def test_bootstrap_success_with_delayed_visibility_preserves_one_shot_plan(tmp_path, monkeypatch):
    executable = app_executable(tmp_path, "com.openai.codex")
    monkeypatch.setattr(relaunch.sys, "platform", "darwin")
    monkeypatch.setattr(relaunch.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(relaunch, "_app_executable", lambda pid: executable)
    calls = []

    def launchctl(*args):
        calls.append(args)
        if args[0] == "bootstrap":
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 113, "", "Could not find service")

    monkeypatch.setattr(relaunch, "_launchctl", launchctl)
    result = relaunch.schedule(
        "01a0f09e-13ad-7043-b1c8-aa5a5d0131cc", 12345, "issue-109", 45, True
    )

    assert result["status"] == "scheduled-unverified"
    assert [call[0] for call in calls] == ["bootstrap", "print"]
    assert Path(result["plist"]).exists()
