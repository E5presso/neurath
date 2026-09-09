"""Upstream publication authority never follows from installation or local fixes."""

import json
import subprocess

import pytest

from neurath.install.transaction import apply_plan, make_plan


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "private-customer-project"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    apply_plan(root, make_plan(root))
    return root


def report():
    return dict(kind="defect", component="cli.py", summary="Setup loses a selection",
                expected="Setup preserves the selected host.",
                observed="Setup replaces a selected host during an update.",
                reproduction="In an empty disposable Git repository, install then repeat setup.",
                proposal="Preserve the selected host on repeat setup.", scope="common")


def test_setup_pending_consent_and_preserved_decision(project):
    from neurath.install.setup import setup_project
    first = setup_project(project)
    assert first["reporting"]["auto_report"] is None
    assert first["reporting"]["consent_required"] is True
    assert first["reporting"]["question"]
    setup_project(project, auto_report=False)
    assert setup_project(project)["reporting"]["auto_report"] is False
    setup_project(project, auto_report=True)
    assert setup_project(project)["reporting"]["auto_report"] is True


def test_no_consent_and_revocation_block_network(project, monkeypatch):
    from neurath.reporting import Reporting
    service = Reporting(project)
    draft = service.prepare(report(), privacy_reviewed=True)
    monkeypatch.setattr(service, "_publish", lambda *_: pytest.fail("unauthorized network"))
    with pytest.raises(ValueError, match="consent"):
        service.submit(draft["id"])
    service.consent(True)
    service.consent(False)
    with pytest.raises(ValueError, match="consent"):
        service.submit(draft["id"])


def test_local_code_is_not_common(project):
    from neurath.reporting import Reporting
    service = Reporting(project)
    data = report()
    data["component"] = "customer/domain.py"
    with pytest.raises(ValueError, match="component"):
        service.prepare(data, privacy_reviewed=True)
    data = report()
    data["scope"] = "project-specific"
    with pytest.raises(ValueError, match="contribution"):
        service.prepare(data, privacy_reviewed=True)
    data["kind"] = "contribution"
    draft = service.prepare(data, privacy_reviewed=True)
    service.consent(True)
    with pytest.raises(ValueError, match="approval"):
        service.submit(draft["id"])


@pytest.mark.parametrize("private", [
    "private-customer-project", "/Users/customer/project/data.txt", "C:\\Users\\customer\\data",
    "customer@example.com", "https://private.example.com", "secret=customer-secret",
    "ghp_123456789012345678901234567890", "```python\nprivate_code()\n```",
])
def test_private_content_rejected_before_storage(project, private):
    from neurath.reporting import Reporting
    service = Reporting(project)
    data = report()
    data["observed"] = private
    with pytest.raises(ValueError, match="private|prose"):
        service.prepare(data, privacy_reviewed=True)
    assert service.list_reports() == []


def test_review_and_closed_fields_required(project):
    from neurath.reporting import Reporting
    service = Reporting(project)
    with pytest.raises(ValueError, match="review"):
        service.prepare(report())
    data = report()
    data["logs"] = "raw trace"
    with pytest.raises(ValueError, match="fields"):
        service.prepare(data, privacy_reviewed=True)


@pytest.mark.parametrize("remote,private", [
    ("https://github.com/E5presso/neurath-private-ledger.git", "neurath-private-ledger"),
    ("git@github.com:E5presso/neurath-private-ledger.git", "neurath-private-ledger"),
    ("https://private-forge.example/E5presso/neurath.git", "private-forge"),
    ("https://github.com/secret-team/E5presso/neurath.git", "secret-team"),
])
def test_upstream_lookalike_remote_stays_private(project, remote, private):
    from neurath.reporting import Reporting
    subprocess.run(["git", "-C", str(project), "remote", "add", "origin", remote], check=True)
    service = Reporting(project)
    data = report()
    data["summary"] = f"Improve {private} automation"
    with pytest.raises(ValueError, match="private"):
        service.prepare(data, privacy_reviewed=True)
    assert service.list_reports() == []


@pytest.mark.parametrize("remote", [
    "https://github.com/E5presso/neurath.git",
    "git@github.com:E5presso/neurath.git",
    "ssh://git@github.com/E5presso/neurath.git",
])
def test_exact_public_upstream_remote_is_exempt(project, remote):
    from neurath.reporting import Reporting
    subprocess.run(["git", "-C", str(project), "remote", "add", "origin", remote], check=True)
    data = report()
    data["summary"] = "Improve E5presso harness reporting"
    assert Reporting(project).prepare(data, privacy_reviewed=True)["status"] == "draft"


def test_dedup_and_exact_contribution_approval(project, monkeypatch):
    from neurath.reporting import Reporting, UPSTREAM
    service = Reporting(project)
    data = report()
    data.update(kind="contribution", scope="project-specific")
    first = service.prepare(data, privacy_reviewed=True)
    assert service.prepare(data, privacy_reviewed=True)["id"] == first["id"]
    service.approve(first["id"], decision=True)
    calls = []
    url = f"https://github.com/{UPSTREAM}/issues/12"
    monkeypatch.setattr(service, "_publish", lambda draft: calls.append(draft) or url)
    assert service.submit(first["id"])["url"] == url
    assert service.submit(first["id"])["url"] == url
    assert len(calls) == 1
    data["proposal"] = "Use another generic strategy."
    second = service.prepare(data, privacy_reviewed=True)
    with pytest.raises(ValueError, match="approval"):
        service.submit(second["id"])


def test_uncertain_send_never_automatically_retries(project, monkeypatch):
    from neurath.reporting import Reporting
    service = Reporting(project)
    service.consent(True)
    draft = service.prepare(report(), privacy_reviewed=True)
    calls = []
    def failed(_):
        calls.append(True)
        raise TimeoutError("response lost")
    monkeypatch.setattr(service, "_publish", failed)
    assert service.submit(draft["id"])["status"] == "uncertain"
    assert service.submit(draft["id"])["status"] == "uncertain"
    assert len(calls) == 1


def test_dry_run_does_not_save_consent(project):
    from neurath.install.setup import setup_project
    from neurath.reporting import Reporting
    setup_project(project, dry_run=True, auto_report=True)
    assert Reporting(project).status()["auto_report"] is None


def test_settings_stay_out_of_checkout(project):
    from neurath.reporting import Reporting
    service = Reporting(project)
    service.consent(True)
    assert service.path.is_relative_to(project / ".git")
    assert "auto_report" not in (project / ".neurath/project.json").read_text()
    assert service._read()["auto_report"] is True
    assert not service.path.exists()
    database = service.state_store._database().path
    assert subprocess.run(["git", "check-ignore", "-q", str(database)], cwd=project).returncode == 0


def test_modified_projected_skill_requires_contribution(project):
    from neurath.reporting import Reporting
    service = Reporting(project)
    data = report()
    data["component"] = "_assets/.agents/skills/investigate/SKILL.md"
    service.prepare(data, privacy_reviewed=True)
    (project / ".agents/skills/debug/SKILL.md").write_text("Custom project workflow")
    with pytest.raises(ValueError, match="customized"):
        service.prepare(data, privacy_reviewed=True)
    data.update(kind="contribution", scope="project-specific")
    assert service.prepare(data, privacy_reviewed=True)["approved"] is False


def test_draft_tampering_cannot_reuse_approval(project):
    from neurath.reporting import Reporting
    service = Reporting(project)
    data = report()
    data["kind"] = "contribution"
    draft = service.prepare(data, privacy_reviewed=True)
    service.approve(draft["id"], decision=True)
    state = service._read()
    state["reports"][draft["id"]]["body"] += "A changed proposal"
    service._save(state)
    with pytest.raises(ValueError, match="content changed"):
        service.submit(draft["id"])


def test_fresh_clone_does_not_inherit_consent(project, tmp_path):
    from neurath.reporting import Reporting
    Reporting(project).consent(True)
    clone = tmp_path / "fresh-clone"
    subprocess.run(["git", "clone", "-q", str(project), str(clone)], check=True)
    assert Reporting(clone).status()["consent_required"] is True


def test_read_only_status_has_no_writes_and_corruption_fails_closed(project):
    from neurath.reporting import Reporting
    service = Reporting(project)
    assert not service.directory.exists()
    service.status()
    assert not service.directory.exists()
    service.consent(True)
    import hashlib
    raw = b'{"schema":1,"auto_report":"yes","reports":{}}'
    with service.state_store._database().connection() as db:
        db.execute("UPDATE runtime_records SET payload=?,digest=? WHERE namespace=? AND key=?",
                   (raw, hashlib.sha256(raw).hexdigest(), "reporting", service.state_store.key))
    with pytest.raises(ValueError, match="invalid"):
        service.status()


def test_gh_transport_fixed_repository_private_body_and_readback(project, monkeypatch):
    from neurath.reporting import Reporting, UPSTREAM
    from pathlib import Path
    from types import SimpleNamespace

    service = Reporting(project)
    service.consent(True)
    draft = service.prepare(report(), privacy_reviewed=True)
    url = f"https://github.com/{UPSTREAM}/issues/34"
    real_run = subprocess.run
    sends = []
    def run(argv, **kwargs):
        if argv[0] != "gh":
            return real_run(argv, **kwargs)
        assert argv[-2:] == ["--repo", "github.com/" + UPSTREAM]
        assert kwargs["env"]["GH_HOST"] == "github.com"
        assert kwargs["env"]["GH_PROMPT_DISABLED"] == "1"
        assert not Path(kwargs["cwd"]).is_relative_to(project)
        sends.append(argv)
        if argv[1:3] == ["issue", "create"]:
            body = Path(argv[argv.index("--body-file") + 1])
            assert body.read_text() == draft["body"]
            assert body.stat().st_mode & 0o777 == 0o600
            assert argv[argv.index("--title") + 1] == draft["title"]
            return SimpleNamespace(stdout=url + "\n")
        return SimpleNamespace(stdout=json.dumps(dict(url=url, title=draft["title"], body=draft["body"])))
    monkeypatch.setattr(subprocess, "run", run)
    assert service.submit(draft["id"])["status"] == "submitted"
    assert len(sends) == 2


def test_remote_identifier_is_rejected_without_echoing_it(project):
    from neurath.reporting import Reporting
    subprocess.run(["git", "-C", str(project), "remote", "add", "origin",
                    "https://github.com/secret-company/private-ledger.git"], check=True)
    data = report()
    data["summary"] = "Improve private-ledger automation"
    with pytest.raises(ValueError, match="private project content") as result:
        Reporting(project).prepare(data, privacy_reviewed=True)
    assert "private-ledger" not in str(result.value)


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_real_hook_entrypoint_displays_consent_and_scope(project, host):
    from neurath.reporting import Reporting
    from tests.test_memory_hooks import invoke
    pending = invoke(project, host, "report-onboarding", "SessionStart", source="startup")
    assert pending.returncode == 0, pending.stderr
    assert "reporting consent is pending" in pending.stdout
    Reporting(project).consent(True)
    enabled = invoke(project, host, "report-onboarding", "UserPromptSubmit",
                     prompt="Inspect the installed harness", turn_id="report-turn")
    assert enabled.returncode == 0, enabled.stderr
    assert "upstream reporting is enabled by the user" in enabled.stdout
    assert "separate user approval" in enabled.stdout
    assert Reporting(project).list_reports() == []


def test_concurrent_submits_create_only_one_issue(project, monkeypatch):
    from neurath.reporting import Reporting, UPSTREAM
    from concurrent.futures import ThreadPoolExecutor
    service = Reporting(project)
    service.consent(True)
    draft = service.prepare(report(), privacy_reviewed=True)
    calls = []
    def publish(self, value):
        calls.append(value["id"])
        return f"https://github.com/{UPSTREAM}/issues/56"
    monkeypatch.setattr(Reporting, "_publish", publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Reporting(project).submit(draft["id"]), range(2)))
    assert len(calls) == 1
    assert all(result["status"] == "submitted" for result in results)


def test_terminal_cli_full_send_with_fake_github_process(project, tmp_path):
    """Exercise parser, subprocess transport, persistence and refusal without GitHub writes."""
    import os
    import sys
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    remote = tmp_path / "remote.json"
    executable = fake_bin / "gh"
    executable.write_text(f"#!{sys.executable}\n" + '''import json, os, pathlib, sys
a = sys.argv[1:]
assert a[-2:] == ['--repo', 'github.com/E5presso/neurath']
p = pathlib.Path(os.environ['TEST_REPORT_REMOTE'])
url = 'https://github.com/E5presso/neurath/issues/78'
if a[:2] == ['issue', 'create']:
    assert not p.exists(), 'duplicate create'
    body = pathlib.Path(a[a.index('--body-file')+1]).read_text()
    p.write_text(json.dumps(dict(url=url, title=a[a.index('--title')+1], body=body)))
    print(url)
else:
    print(p.read_text())
''')
    executable.chmod(0o700)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("NEURATH_", "CODEX_", "CLAUDE_"))}
    environment.update(PATH=str(fake_bin) + ":" + environment["PATH"], TEST_REPORT_REMOTE=str(remote))
    data = tmp_path / "report.json"
    data.write_text(json.dumps(report()))
    def run(*args):
        return subprocess.run([str(project / ".neurath/run"), "report", *args],
                              env=environment, cwd=project, capture_output=True, text=True)
    draft_result = run("prepare", str(data), "--privacy-reviewed")
    assert draft_result.returncode == 0, draft_result.stderr
    draft = json.loads(draft_result.stdout)
    assert run("submit", draft["id"]).returncode != 0
    assert not remote.exists()
    assert run("consent", "yes", "--user-confirmed").returncode == 0
    sent = run("submit", draft["id"])
    assert sent.returncode == 0, sent.stderr
    assert json.loads(sent.stdout)["status"] == "submitted"
    assert run("submit", draft["id"]).returncode == 0
