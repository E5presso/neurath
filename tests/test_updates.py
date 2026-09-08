"""Specify consent, immutable release selection and real installer recovery first."""

import hashlib
import io
import json
import subprocess
import zipfile

import pytest

from neurath.install.transaction import apply_plan, make_plan, read_state


@pytest.mark.parametrize("requirements,accepted", [
    ([], True), (["claude-agent-sdk<0.3,>=0.2.152"], True),
    (["unrelated-package>=1"], False), (["claude-agent-sdk @ https://example.invalid/sdk.whl"], False),
])
def test_release_wheel_dependency_contract(requirements, accepted):
    from neurath.release_install import wheel_check
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as wheel:
        wheel.writestr("neurath/manifest.json", json.dumps({"schema": 1, "files": {}}))
        metadata = "Name: neurath\nVersion: 0.2.0\n" + "".join(
            "Requires-Dist: " + value + "\n" for value in requirements)
        wheel.writestr("neurath-0.2.0.dist-info/METADATA", metadata)
    data = payload.getvalue()
    offer = {"version": "0.2.0", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if accepted:
        wheel_check(data, offer)
    else:
        with pytest.raises(ValueError, match="dependency contract"):
            wheel_check(data, offer)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "private-project"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "AGENTS.md").write_text("Keep my instructions.\n")
    (root / "pyproject.toml").write_text('[project]\nname="private-project"\nversion="1"\n')
    (root / ".codex").mkdir()
    (root / ".codex/config.toml").write_text('model = "user-model"\nsandbox_mode = "read-only"\n')
    (root / ".codex/hooks.json").write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "echo keep-user-hook"}]}]}}))
    apply_plan(root, make_plan(root, hosts=["codex"], skill_prefix="neurath-"))
    return root


def release(version="0.2.0", digest=None):
    return dict(id=12, tag_name="v" + version, draft=False, prerelease=False,
                published_at="2026-09-07T00:00:00Z", body="Preserve preferences.\nImprove recovery.",
                html_url="https://github.com/E5presso/neurath/releases/tag/v" + version,
                assets=[dict(id=34, name=f"neurath-{version}-py3-none-any.whl",
                             state="uploaded", size=100,
                             digest="sha256:" + (digest or "a" * 64))])


@pytest.fixture
def service(project, monkeypatch):
    from neurath.updates import Updates
    service = Updates(project)
    monkeypatch.setattr("neurath.updates.fetch_release", lambda *args: release())
    return service


def test_announcement_once_and_choices_survive_restart(service):
    from neurath.updates import Updates
    result = service.check()
    assert result["offer"]["current"] == "0.1.0"
    assert result["offer"]["version"] == "0.2.0"
    assert result["offer"]["notes"]
    assert service.notice() is not None
    assert Updates(service.root).notice() is None
    offer = result["offer"]["id"]
    for decision in ("no", "later"):
        service.choose(offer, decision, user_confirmed=True)
        assert Updates(service.root).status()["decision"] == decision
        assert service.check(force=True)["offer"]["id"] == offer
        assert service.notice() is None
    with pytest.raises(ValueError, match="explicit"):
        service.choose(offer, "yes")
    with pytest.raises(ValueError, match="prepared"):
        service.choose(offer, "yes", user_confirmed=True)


def test_network_failure_is_cached_and_does_not_offer_stale_release(service, monkeypatch):
    service.check()
    calls = []
    def unavailable(*args):
        calls.append(args)
        raise TimeoutError("offline")
    monkeypatch.setattr("neurath.updates.fetch_release", unavailable)
    assert service.check(force=True)["status"] == "unavailable"
    assert service.check()["status"] == "unavailable"
    assert len(calls) == 1
    assert service.notice() is None


@pytest.mark.parametrize("edit", [
    {"draft": True}, {"prerelease": True}, {"tag_name": "v0.2.0rc1"},
    {"tag_name": "main"}, {"assets": []}, {"published_at": None},
    {"assets": [dict(id=34, name="neurath-0.2.0-py3-none-any.whl", state="uploaded",
                     size=100, digest=None)]},
])
def test_ineligible_release_never_offered(service, monkeypatch, edit):
    monkeypatch.setattr("neurath.updates.fetch_release", lambda *args: {**release(), **edit})
    assert service.check()["offer"] is None


def test_changed_asset_cannot_reuse_consent_or_repeat_rejected_version(service, monkeypatch):
    old = service.check()["offer"]
    service.choose(old["id"], "no", user_confirmed=True)
    monkeypatch.setattr("neurath.updates.fetch_release", lambda *args: release(digest="b" * 64))
    new = service.check(force=True)["offer"]
    assert new["id"] != old["id"]
    assert service.notice() is None
    with pytest.raises(ValueError, match="offer"):
        service.choose(old["id"], "yes", user_confirmed=True)


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_hooks_are_local_nonblocking_and_only_request_check_once(project, monkeypatch, host):
    from neurath.updates import update_event
    monkeypatch.setattr("neurath.updates.fetch_release", lambda *args: pytest.fail("network in hook"))
    event = dict(hook_event_name="SessionStart", session_id="fixture")
    output = update_event(project, host, event, {})
    assert "releases_check" in output["hookSpecificOutput"]["additionalContext"]
    assert update_event(project, host, event, {}) == {}
    assert update_event(project, host, {**event, "agent_id": "child"}, {}) == {}
    from neurath.updates import Updates
    Updates(project).path.write_text("invalid json")
    assert update_event(project, host, event, {}) == {}


def test_apply_without_consent_never_installs(service, monkeypatch):
    from neurath import release_install
    offer = service.check()["offer"]
    monkeypatch.setattr(release_install, "apply", lambda *args: pytest.fail("unauthorized install"))
    with pytest.raises(ValueError, match="consent"):
        service.apply(offer["id"])


def test_transport_has_only_fixed_public_requests(monkeypatch):
    from neurath.updates import fetch_release, API
    from io import BytesIO
    seen = []
    def open_request(request, **kwargs):
        seen.append(request)
        assert kwargs["timeout"] <= 10
        return BytesIO(json.dumps(release()).encode())
    monkeypatch.setattr("neurath.updates.urlopen", open_request)
    assert fetch_release()["id"] == 12
    assert seen[0].full_url == API + "/releases/latest"
    assert seen[0].data is None
    assert "Authorization" not in seen[0].headers


def test_download_hash_checked_before_execution(service, monkeypatch, tmp_path):
    service.check()
    monkeypatch.setattr("neurath.release_install.download_asset", lambda *args: b"bad wheel")
    before = read_state(service.root)
    with pytest.raises(ValueError, match="digest"):
        service.prepare(service.status()["offer"]["id"])
    assert read_state(service.root) == before
    assert service.status()["decision"] is None


@pytest.fixture(scope="module")
def wheel_bytes():
    """Build a real installable future-version wheel from the current package in isolation."""
    import base64
    import io
    import zipfile
    from neurath.resources import PACKAGE
    entries = {p.relative_to(PACKAGE).as_posix(): p.read_bytes() for p in PACKAGE.rglob("*")
               if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
               and p.name != "manifest.json"}
    entries["__init__.py"] = entries["__init__.py"].replace(b'"0.1.0"', b'"0.2.0"')
    entries["manifest.json"] = json.dumps(dict(schema=1, files={name: hashlib.sha256(data).hexdigest()
                                          for name, data in entries.items()})).encode()
    files = {"neurath/" + name: data for name, data in entries.items()}
    dist = "neurath-0.2.0.dist-info/"
    files[dist + "METADATA"] = b"Metadata-Version: 2.1\nName: neurath\nVersion: 0.2.0\nRequires-Python: >=3.14,<3.15\n"
    files[dist + "WHEEL"] = b"Wheel-Version: 1.0\nGenerator: neurath-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    record = "\n".join(f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')},{len(data)}"
                       for name, data in files.items()) + f"\n{dist}RECORD,,\n"
    files[dist + "RECORD"] = record.encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as wheel:
        for name, data in files.items():
            wheel.writestr(name, data)
    return stream.getvalue()


@pytest.fixture
def prepared(service, monkeypatch, wheel_bytes):
    value = release(digest=hashlib.sha256(wheel_bytes).hexdigest())
    value["assets"][0]["size"] = len(wheel_bytes)
    monkeypatch.setattr("neurath.updates.fetch_release", lambda *args: value)
    monkeypatch.setattr("neurath.release_install.download_asset", lambda *args: wheel_bytes)
    offer = service.check()["offer"]
    result = service.prepare(offer["id"])
    assert result["operation"]["phase"] == "prepared"
    assert read_state(service.root)["version"] == "0.1.0"
    return service, offer


def test_real_wheel_update_preserves_choices_settings_and_restores(prepared):
    import os
    from neurath.reporting import Reporting
    service, offer = prepared
    root = service.root
    original = read_state(root)
    reporting = Reporting(root)
    reporting.consent(True)
    draft = reporting.prepare(dict(kind="contribution", scope="project-specific", component="cli.py",
        summary="Improve generic setup", expected="Keep preferences", observed="Check preferences",
        reproduction="Use an empty fixture", proposal="Preserve user choices"), privacy_reviewed=True)
    reporting.approve(draft["id"], decision=True)
    report_bytes = reporting.path.read_bytes()
    service.choose(offer["id"], "later", user_confirmed=True)
    with pytest.raises(ValueError, match="consent"):
        service.apply(offer["id"])
    service.choose(offer["id"], "yes", user_confirmed=True)
    result = service.apply(offer["id"])
    assert result["operation"]["phase"] == "applied"
    assert read_state(root)["version"] == "0.2.0"
    assert read_state(root)["skill_prefix"] == "neurath-"
    assert read_state(root)["hosts"] == ["codex"]
    assert 'sandbox_mode = "read-only"' in (root / ".codex/config.toml").read_text()
    assert "keep-user-hook" in (root / ".codex/hooks.json").read_text()
    assert reporting.path.read_bytes() == report_bytes
    assert (root / "AGENTS.md").read_text().startswith("Keep my instructions.")
    assert 'name="private-project"' in (root / "pyproject.toml").read_text()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_"))}
    process = subprocess.run([root / ".neurath/run", "releases", "status"], env=env,
                              capture_output=True, text=True, check=True)
    assert json.loads(process.stdout)["current"] == "0.2.0"
    assert service.recover()["operation"]["phase"] == "recovered"
    assert read_state(root) == original
    assert reporting.path.read_bytes() == report_bytes
    assert service.notice() is None


def test_interruption_after_apply_recovers_without_reapplying(prepared, monkeypatch):
    from neurath import release_install
    service, offer = prepared
    before = read_state(service.root)
    service.choose(offer["id"], "yes", user_confirmed=True)
    apply = release_install.apply
    def interrupted(*args):
        apply(*args)
        raise KeyboardInterrupt("simulated process death after transaction commit")
    monkeypatch.setattr(release_install, "apply", interrupted)
    with pytest.raises(KeyboardInterrupt):
        service.apply(offer["id"])
    assert read_state(service.root)["version"] == "0.2.0"
    assert service.status()["operation"]["phase"] == "applying"
    assert service.recover()["operation"]["phase"] == "recovered"
    assert read_state(service.root) == before
    with pytest.raises(ValueError, match="consent"):
        service.apply(offer["id"])


def test_stale_plan_keeps_user_edits_and_recovery_conflict_is_visible(prepared):
    service, offer = prepared
    path = service.root / "AGENTS.md"
    path.write_text(path.read_text() + "A concurrent user edit.\n")
    before = read_state(service.root)
    service.choose(offer["id"], "yes", user_confirmed=True)
    with pytest.raises(ValueError, match="stale"):
        service.apply(offer["id"])
    assert read_state(service.root) == before
    assert "concurrent user edit" in path.read_text()
    # No installation committed: changes outside the candidate write set remain intact.
    assert service.recover()["operation"]["phase"] == "recovered"


def test_release_replaced_after_approval_fails_before_mutation(prepared, monkeypatch):
    service, offer = prepared
    service.choose(offer["id"], "yes", user_confirmed=True)
    monkeypatch.setattr("neurath.updates.fetch_release", lambda *args: release(digest="b" * 64))
    with pytest.raises(ValueError, match="release changed"):
        service.apply(offer["id"])
    assert read_state(service.root)["version"] == "0.1.0"
    assert service.status()["decision"] == "later"


def test_corrupt_runtime_does_not_execute_update(prepared):
    service, offer = prepared
    from neurath.release_install import paths
    python, _ = paths(service.directory, service.status()["operation"])
    package = next(python.parent.parent.glob("lib/python*/site-packages/neurath"))
    (package / "templates/common-report.md").write_text("corrupt fixture")
    service.choose(offer["id"], "yes", user_confirmed=True)
    with pytest.raises(ValueError, match="failed|integrity"):
        service.apply(offer["id"])
    assert read_state(service.root)["version"] == "0.1.0"


def test_busy_update_lock_never_waits_in_hook(project):
    from neurath.updates import Updates, update_event
    service = Updates(project)
    with service._locked():
        assert update_event(project, "codex", dict(hook_event_name="SessionStart"), {}) == {}


def test_mid_transaction_process_exit_uses_real_journal_recovery(prepared, monkeypatch):
    import os
    from neurath import release_install
    service, offer = prepared
    before = read_state(service.root)
    service.choose(offer["id"], "yes", user_confirmed=True)
    def crash(root, directory, selected, operation):
        python, plan_path = release_install.paths(directory, operation)
        code = '''import json, os, sys
from pathlib import Path
from neurath.install import transaction
write = transaction._write
def stop(root, relative, value):
    write(root, relative, value)
    os._exit(71)
transaction._write = stop
transaction.apply_plan(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))
'''
        env = {k: v for k, v in os.environ.items() if not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_"))}
        result = subprocess.run([python, "-I", "-c", code, root, plan_path], env=env)
        assert result.returncode == 71
        raise KeyboardInterrupt("process died during transaction")
    monkeypatch.setattr(release_install, "apply", crash)
    with pytest.raises(KeyboardInterrupt):
        service.apply(offer["id"])
    assert (service.directory.parent / "neurath-journal.json").exists()
    assert service.recover()["operation"]["phase"] == "recovered"
    assert read_state(service.root) == before
    assert not (service.directory.parent / "neurath-journal.json").exists()


def test_post_apply_diagnostic_failure_recovers_and_preserves_new_user_edit(prepared, monkeypatch):
    from neurath import release_install
    service, offer = prepared
    command = release_install.runtime_command
    def diagnostic_failure(python, root, *args):
        if args == ("doctor", "--protocol"):
            raise ValueError("injected diagnostic failure")
        return command(python, root, *args)
    monkeypatch.setattr(release_install, "runtime_command", diagnostic_failure)
    service.choose(offer["id"], "yes", user_confirmed=True)
    with pytest.raises(ValueError, match="diagnostic failure"):
        service.apply(offer["id"])
    path = service.root / ".agents/skills/neurath-debug/SKILL.md"
    path.write_text(path.read_text() + "User edit after failure\n")
    with pytest.raises((ValueError, RuntimeError), match="conflict"):
        service.recover()
    assert "User edit after failure" in path.read_text()
    assert read_state(service.root)["version"] == "0.2.0"


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_hook_protocol_entry_emits_one_due_notice(project, host):
    from tests.test_memory_hooks import invoke
    first = invoke(project, host, "update-fixture", "SessionStart", source="startup")
    assert first.returncode == 0, first.stderr
    assert "releases_check" in first.stdout
    second = invoke(project, host, "update-fixture", "UserPromptSubmit",
                    prompt="Continue the original task", turn_id="updates-turn")
    assert second.returncode == 0, second.stderr
    assert "releases_check" not in second.stdout


def test_cli_requires_explicit_choice_flag_and_original_task_failure_is_not_hidden(project):
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_"))}
    for args in (("choose", "a" * 64, "yes"), ("apply", "a" * 64)):
        result = subprocess.run([project / ".neurath/run", "releases", *args], env=env,
                                capture_output=True, text=True)
        assert result.returncode == 2
    assert read_state(project)["version"] == "0.1.0"
