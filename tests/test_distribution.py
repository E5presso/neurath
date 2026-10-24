"""실제 wheel·별도 환경·공유 DB·설정·복구·콜백의 배포 결과를 검증한다."""

import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from neurath.infrastructure.services.distribution import PosixDistributionService
from tests.conftest import git, initialize_git
from tests.test_host_flow import host as host
from tests.test_host_flow import invoke
from tools import build_release


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    root = Path(__file__).parents[1]
    work = tmp_path_factory.mktemp("distribution-wheels")
    project = work / "source"
    project.mkdir()
    shutil.copytree(root / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(root / "pyproject.toml", project / "pyproject.toml")
    (project / "tools").mkdir()
    initialize_git(project)
    git(project, "add", ".")
    git(
        project,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "Source A",
    )
    commit_a = git(project, "rev-parse", "HEAD")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(build_release, "__file__", str(project / "tools/build_release.py"))
        build_release.build(work / "a")
        (project / "src/neurath/resources/fixture.md").write_text(
            "Source B at the same semantic version\n"
        )
        git(project, "add", ".")
        git(
            project,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-m",
            "Source B",
        )
        commit_b = git(project, "rev-parse", "HEAD")
        build_release.build(work / "b")
        (project / "src/neurath/resources/cli-guide.md").write_text("stale guide")
        with pytest.raises(ValueError, match="stale"):
            build_release.build(work / "stale")
    service = PosixDistributionService()
    a = service.prepare(str(next((work / "a").glob("*.whl"))), str(work / "runtimes"), commit_a)
    b = service.prepare(str(next((work / "b").glob("*.whl"))), str(work / "runtimes"), commit_b)
    assert a["version"] == b["version"] and a["wheel_sha256"] != b["wheel_sha256"]
    return a, b


async def test_real_same_version_shared_database_update_recovery_and_guide(
    database, host, releases, tmp_path
):
    a, b = releases
    service = PosixDistributionService()
    data = tmp_path / "data"
    installations = []
    for provider in ("codex", "claude"):
        project = tmp_path / provider
        project.mkdir()
        rules = project / ("AGENTS.md" if provider == "codex" else "CLAUDE.md")
        rules.write_text("Preserve the user's instructions\n")
        skills = project / (".agents/skills" if provider == "codex" else ".claude/skills")
        (skills / "expert").mkdir(parents=True)
        (skills / "expert/SKILL.md").write_text("Preserve specialist work")
        planned = service.plan(a["candidate"], provider, str(project), str(data))
        assert planned["applied"] is False
        before_after = json.loads(Path(planned["preview"]).read_text())["files"][str(rules)]
        assert before_after["before"] == rules.read_text()
        installed = service.apply(a["candidate"], provider, str(project), str(data))
        assert installed["cli_invoked"] and "unverified" in installed["model_context"]
        assert (skills / "expert/SKILL.md").read_text() == "Preserve specialist work"
        assert rules.read_text().startswith("Preserve the user's instructions")
        installations.append(installed)
    core = data / "neurath/core.sqlite3"
    with sqlite3.connect(core) as db:
        db.execute("CREATE TABLE new_user_records(value TEXT)")
        db.execute("INSERT INTO new_user_records VALUES('New record after initial installation')")
    original = core.read_bytes()
    updated = service.apply(b["candidate"], "codex", str(tmp_path / "codex"), str(data))
    assert updated["candidate"]["version"] == a["version"]
    assert core.read_bytes() == original
    for installed, expected in [(updated, b), (installations[1], a)]:
        result = subprocess.run(
            [installed["command"], "distribution", "verify"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(result.stdout)["package_sha256"] == expected["package_sha256"]
        guide = subprocess.run(
            [installed["command"], "distribution", "guide"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert installed["command"] in json.loads(guide.stdout)["guide"]
    again = service.apply(b["candidate"], "codex", str(tmp_path / "codex"), str(data))
    assert again["changed_files"] == []
    with sqlite3.connect(core) as db:
        db.execute("INSERT INTO new_user_records VALUES('New record after update')")
    assert service.recover(updated["receipt"])["events_preserved"]
    assert service.recover(updated["receipt"])["status"] == "recovered"
    restored = subprocess.run(
        [updated["command"], "distribution", "verify"], capture_output=True, text=True, check=True
    )
    assert json.loads(restored.stdout)["package_sha256"] == a["package_sha256"]
    with sqlite3.connect(core) as db:
        assert db.execute("SELECT count(*) FROM new_user_records").fetchone()[0] == 2


async def test_distribution_cli_prepare_plan_apply_recover(database, tmp_path, releases):
    a, _ = releases
    candidate = await invoke(
        database,
        [
            "distribution",
            "prepare",
            "--wheel",
            a["wheel"],
            "--store",
            str(Path(a["candidate"]).parent),
            "--source-commit",
            a["provenance"]["source_commit"],
        ],
    )
    assert candidate["candidate"] == a["candidate"]
    args = [
        "--candidate",
        a["candidate"],
        "--provider",
        "codex",
        "--directory",
        str(tmp_path),
        "--data-home",
        str(tmp_path / "data"),
    ]
    assert (await invoke(database, ["distribution", "plan", *args]))["applied"] is False
    applied = await invoke(database, ["distribution", "apply", *args])
    assert (await invoke(database, ["distribution", "recover", "--receipt", applied["receipt"]]))[
        "status"
    ] == "recovered"
    assert not Path(applied["command"]).exists()
    assert (await invoke(database, ["distribution", "verify"]))["guide_matches"]
    assert "Default entry" in (await invoke(database, ["distribution", "guide"]))["guide"]


@pytest.mark.parametrize("mode", ["absent", "failure", "network", "available", "current"])
async def test_official_release_absence_failure_and_exact_artifact_are_distinct(
    database, tmp_path, monkeypatch, mode
):
    import urllib.request

    installed = tmp_path / "installed.json"
    installed.write_text('{"version":"0.3.1","wheel_sha256":"current"}')

    def fetch(request, **kwargs):
        if mode in {"absent", "failure"}:
            raise urllib.error.HTTPError(
                request.full_url, 404 if mode == "absent" else 503, "fixture", {}, None
            )
        if mode == "network":
            raise OSError("offline fixture")
        return io.BytesIO(
            json.dumps(
                {
                    "tag_name": "v0.3.1",
                    "assets": [
                        {
                            "name": "neurath.whl",
                            "browser_download_url": "https://github.com/E5presso/neurath/releases/download/v0.3.1/neurath.whl",
                            "digest": "sha256:" + ("current" if mode == "current" else "other"),
                        },
                        {"name": "SHA256SUMS"},
                    ],
                }
            ).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    result = await invoke(database, ["distribution", "check", "--installed", str(installed)])
    assert (
        result["status"]
        == {
            "absent": "no-release",
            "failure": "lookup-failed",
            "network": "lookup-failed",
            "available": "release-observed",
            "current": "current-artifact",
        }[mode]
    )
    assert result["installed"]["wheel_sha256"] == "current"


async def test_shared_schema_mismatch_returns_preserving_continuation_without_switch(
    database, tmp_path, releases
):
    a, _ = releases
    data = tmp_path / "data"
    (data / "neurath").mkdir(parents=True)
    shutil.copyfile(database, data / "neurath/core.sqlite3")
    core = data / "neurath/core.sqlite3"
    with sqlite3.connect(core) as db:
        db.execute("UPDATE core_schema_revision SET version_num='future-schema'")
    before = core.read_bytes()
    service = PosixDistributionService()
    plan = service.plan(a["candidate"], "codex", str(tmp_path), str(data))
    assert plan["database_transition"]["required"]
    assert any("migration recover" in step for step in plan["continuation"])
    with pytest.raises(ValueError, match="preserving transition"):
        service.apply(a["candidate"], "codex", str(tmp_path), str(data))
    assert core.read_bytes() == before and not (tmp_path / "AGENTS.md").exists()


@pytest.mark.parametrize("provider", ["codex", "claude"])
async def test_owned_legacy_mcp_only_is_removed_and_unknown_entry_is_retained(tmp_path, provider):
    from neurath.domain.enums.provider_kind import ProviderKind
    from neurath.infrastructure.services.installation import PosixInstallationService
    from neurath.infrastructure.services.skill_catalog import PosixSkillCatalogService

    root = tmp_path / "project"
    root.mkdir()
    launcher = root / ".neurath/neurath"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\n# neurath-managed legacy executable\n")
    path = root / (".codex/config.toml" if provider == "codex" else ".mcp.json")
    path.parent.mkdir(exist_ok=True)
    if provider == "codex":
        path.write_text(
            f'custom = "preserve"\n[mcp_servers.neurath]\ncommand = {json.dumps(str(launcher))}\nargs = ["mcp"]\n[mcp_servers.neurath.env]\nSAFE = "fixture"\n[mcp_servers.other]\ncommand = "other-extension"\n'
        )
    else:
        path.write_text(
            json.dumps(
                {
                    "custom": "preserve",
                    "mcpServers": {
                        "neurath": {"command": str(launcher), "args": ["mcp"]},
                        "other": {"command": "other-extension"},
                    },
                }
            )
        )
    service = PosixInstallationService(PosixSkillCatalogService())
    original = path.read_bytes()
    result = await service.install(ProviderKind(provider), str(root), str(tmp_path / "data"))
    assert "other-extension" in path.read_text() and "custom" in path.read_text()
    assert str(launcher) not in path.read_text()
    assert any(Path(backup).read_bytes() == original for backup in result.backups)
    if provider == "codex":
        path.write_text('[mcp_servers.neurath]\ncommand = "user-owned"\n')
    else:
        path.write_text('{"mcpServers":{"neurath":{"command":"user-owned"}}}')
    before = path.read_bytes()
    result = await service.install(ProviderKind(provider), str(root), str(tmp_path / "data"))
    assert path.read_bytes() == before and "ownership is unverified" in result.host_action


@pytest.mark.parametrize("failure", ["version", "identity", "command"])
def test_failed_cli_verification_restores_matching_files_without_losing_new_records(
    tmp_path, releases, monkeypatch, failure
):
    service = PosixDistributionService()
    a, b = releases
    data = tmp_path / "data"
    installed = service.apply(a["candidate"], "codex", str(tmp_path), str(data))
    rules = tmp_path / "AGENTS.md"
    original = rules.read_bytes()
    real = subprocess.run

    def fail(arguments, *args, **kwargs):
        if arguments[0] == installed["command"]:
            if failure == "command":
                raise subprocess.CalledProcessError(9, arguments)
            if arguments[1:] == (
                ["maintenance", "version"] if failure == "version" else ["distribution", "verify"]
            ):
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    json.dumps({"version": "different", "package_sha256": "different"}),
                    "",
                )
        return real(arguments, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", fail)
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            service.apply(b["candidate"], "codex", str(tmp_path), str(data))
    assert rules.read_bytes() == original
    assert (
        service._run(Path(a["python"]), ["distribution", "verify"])["package_sha256"]
        == a["package_sha256"]
    )
    marker = Path(installed["command"]).parent / "distribution.json"
    assert json.loads(marker.read_text())["wheel_sha256"] == a["wheel_sha256"]
    assert Path(installed["database"]).is_file()


def test_recovery_refuses_later_user_changes_and_incompatible_database(tmp_path, releases):
    service = PosixDistributionService()
    a, b = releases
    data = tmp_path / "data"
    service.apply(a["candidate"], "codex", str(tmp_path), str(data))
    updated = service.apply(b["candidate"], "codex", str(tmp_path), str(data))
    rules = Path(updated["command"])
    original = rules.read_bytes()
    rules.write_text(rules.read_text() + "New user instruction\n")
    with pytest.raises(ValueError, match="changed after apply"):
        service.recover(updated["receipt"])
    assert "New user instruction" in rules.read_text()
    rules.write_bytes(original)
    with sqlite3.connect(updated["database"]) as db:
        db.execute("UPDATE core_schema_revision SET version_num='future-schema'")
    with pytest.raises(ValueError, match="cannot read current records"):
        service.recover(updated["receipt"])
    assert rules.read_bytes() == original


@pytest.mark.parametrize("cancelled", [False, True])
async def test_transition_monitor_replay_uses_current_owner_and_preserves_pending_delivery(
    database, host, tmp_path, cancelled
):
    from tests.test_historical_migration import transition_service
    from tests.test_host_flow import create

    task = await create(database)
    target = host[0] / "job.jsonl"
    target.write_text('{"state":"running"}\n')
    waiting = await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "wait",
            "--task-id",
            task["id"],
            "--target",
            str(target),
            "--condition",
            "state done",
            "--resume-scope",
            "verify original result",
            "--reason",
            "Observed running",
            "--monitor",
            "output",
            "--poll-budget",
            "5",
        ],
    )
    payload = dict(host[2], prompt=waiting["monitors"][0]["callback"])
    assert (await host[1].handle(payload))["continue"] is False
    service = await transition_service(database)
    fence = service.fence(str(database), str(tmp_path / "backups"))
    queued = await invoke(database, ["hook", "handle", "--provider", "codex"], json.dumps(payload))
    assert queued["continue"] is False
    restored = tmp_path / "recovered.sqlite3"
    await invoke(
        database,
        ["migration", "recover", "--source", fence.snapshot, "--destination", str(restored)],
    )
    if cancelled:
        await invoke(
            restored,
            [
                "task",
                "update",
                "--action",
                "cancel",
                "--task-id",
                task["id"],
                "--reason",
                "Actual cancellation",
            ],
        )
    target.write_text('{"state":"running"}\n{"state":"done"}\n')
    result = await invoke(restored, ["migration", "replay", "--directory", fence.directory])
    assert result == {"applied": 1, "remaining": 0, "host_delivery": "unverified"}
    context = await invoke(restored, ["context", "show"])
    monitor = context["tasks"][0]["monitors"][0]
    assert len(monitor["events"]) == (0 if cancelled else 1)
    if not cancelled:
        assert monitor["events"][0]["notice_status"] == "written"
        assert not monitor["events"][0]["acknowledged"]
    sources = (await invoke(restored, ["context", "show", "--section", "sources"]))["sources"]
    assert not any(source["body"].startswith("NEURATH_MONITOR_TICK") for source in sources)
    (Path(fence.directory) / "applied.jsonl").unlink()
    before = restored.read_bytes()
    assert (await invoke(restored, ["migration", "replay", "--directory", fence.directory]))[
        "applied"
    ] == 1
    assert restored.read_bytes() == before


async def test_malformed_monitor_transition_event_remains_pending(database, host, tmp_path):
    from tests.test_historical_migration import transition_service

    service = await transition_service(database)
    fence = service.fence(str(database), str(tmp_path / "backup"))
    await invoke(
        database,
        ["hook", "handle", "--provider", "codex"],
        json.dumps(dict(host[2], prompt="NEURATH_MONITOR_TICK malformed")),
    )
    restored = tmp_path / "recovered.sqlite3"
    await invoke(
        database,
        ["migration", "recover", "--source", fence.snapshot, "--destination", str(restored)],
    )
    response = await invoke(
        restored, ["migration", "replay", "--directory", fence.directory], succeeds=False
    )
    assert "malformed" in str(response.exception) and len(service.pending(fence.directory)) == 1


def test_official_download_digest_and_exact_source_preparation(tmp_path, releases, monkeypatch):
    import urllib.request

    a, _ = releases
    service = PosixDistributionService()
    content = Path(a["wheel"]).read_bytes()
    url = f"https://github.com/E5presso/neurath/releases/download/v-fixture/{Path(a['wheel']).name}"
    asset = {"browser_download_url": url, "digest": "sha256:" + hashlib.sha256(content).hexdigest()}

    def fetch(request, **kwargs):
        if isinstance(request, urllib.request.Request):
            return io.BytesIO(json.dumps({"assets": [asset]}).encode())
        return io.BytesIO(content)

    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    prepared = service.prepare(
        url, str(Path(a["candidate"]).parent), a["provenance"]["source_commit"]
    )
    assert prepared["wheel_sha256"] == a["wheel_sha256"]
    with pytest.raises(ValueError, match="exact source"):
        service.prepare(a["wheel"], str(tmp_path / "no-preparation"), "different-source")
    assert not (tmp_path / "no-preparation").exists()
    with pytest.raises(ValueError, match="official"):
        service._download("https://other.invalid/neurath.whl", tmp_path)
    asset["digest"] = None
    with pytest.raises(ValueError, match="unavailable"):
        service._download(url, tmp_path)
    asset["digest"] = "sha256:different"
    with pytest.raises(ValueError, match="differs"):
        service._download(url, tmp_path)


def test_prepared_artifact_tampering_and_cli_errors_are_explicit(tmp_path, releases):
    service = PosixDistributionService()
    a, _ = releases
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    wheel = candidate / Path(a["wheel"]).name
    wheel.write_bytes(Path(a["wheel"]).read_bytes() + b"changed")
    (candidate / "candidate.json").write_text(json.dumps({**a, "wheel": str(wheel)}))
    with pytest.raises(ValueError, match="changed"):
        service._candidate(str(candidate))
    with pytest.raises(RuntimeError, match="private diagnostics"):
        service._run(Path(a["python"]), ["not-a-command"])
    assert list(Path(a["candidate"]).glob("failures/*.json"))


def test_interrupted_application_can_restore_exact_runtime_and_preserve_database(
    tmp_path, releases, monkeypatch
):
    service = PosixDistributionService()
    a, b = releases
    data = tmp_path / "data"
    initial = service.apply(a["candidate"], "codex", str(tmp_path), str(data))
    original = Path(initial["command"]).read_bytes()
    run = subprocess.run

    def interrupt(arguments, *args, **kwargs):
        if arguments[0] == initial["command"]:
            raise KeyboardInterrupt("Interrupted after candidate file application")
        return run(arguments, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", interrupt)
        with pytest.raises(KeyboardInterrupt):
            service.apply(b["candidate"], "codex", str(tmp_path), str(data))
    receipts = [
        path
        for path in Path(b["candidate"]).glob("applications/*.json")
        if json.loads(path.read_text())["status"] == "prepared"
    ]
    assert len(receipts) == 1
    with sqlite3.connect(initial["database"]) as db:
        db.execute("CREATE TABLE preserved_after_interruption(content TEXT)")
        db.execute("INSERT INTO preserved_after_interruption VALUES('new record')")
    result = service.recover(str(receipts[0]))
    assert result["status"] == "recovered" and Path(initial["command"]).read_bytes() == original
    with sqlite3.connect(initial["database"]) as db:
        assert db.execute("SELECT count(*) FROM preserved_after_interruption").fetchone()[0] == 1
    record = json.loads(receipts[0].read_text())
    record["status"] = "failed-restored"
    receipts[0].write_text(json.dumps(record))
    with pytest.raises(ValueError, match="interrupted"):
        service.recover(str(receipts[0]))


async def test_distribution_ports_and_installed_guide_readback(database, releases, monkeypatch):
    from neurath.application.ports.services.distribution import IDistributionService
    from neurath.transport.cli import distribution

    for name, arguments in [
        ("check", (None,)),
        ("prepare", ("wheel", "store", None)),
        ("plan", ("candidate", "codex", "project", "data")),
        ("apply", ("candidate", "codex", "project", "data")),
        ("recover", ("receipt",)),
    ]:
        with pytest.raises(NotImplementedError):
            getattr(IDistributionService, name)(None, *arguments)
    a, _ = releases
    installed = PosixDistributionService._run(Path(a["python"]), ["distribution", "verify"])
    with monkeypatch.context() as patch:
        patch.setattr(
            distribution,
            "__file__",
            str(Path(installed["package"]) / "transport/cli/distribution.py"),
        )
        actual = await invoke(database, ["distribution", "verify"])
    assert actual["provenance"]["source_commit"] == a["provenance"]["source_commit"]
    monkeypatch.setenv("NEURATH_PROVIDER", "claude")
    monkeypatch.setenv("NEURATH_COMMAND", "/fixture/installed/neurath")
    guide = await invoke(database, ["distribution", "guide"])
    assert "/fixture/installed/neurath" in guide["guide"] and ".claude/skills" in guide["guide"]


async def test_unfinished_monitor_observation_is_not_consumed_by_transition_replay(
    database, host, tmp_path
):
    from uuid import UUID

    from neurath.application.usecases.prepare_monitor_poll import (
        PrepareMonitorPollCommand,
        PrepareMonitorPollUseCase,
    )
    from neurath.application.usecases.read_result_context import (
        ReadResultContextQuery,
        ReadResultContextUseCase,
    )
    from neurath.application.usecases.resolve_session_context import (
        ResolveSessionContextQuery,
        ResolveSessionContextUseCase,
    )
    from neurath.infrastructure.database import sqlite_url
    from tests.support.application import request_application
    from tests.test_historical_migration import transition_service
    from tests.test_host_flow import create

    task = await create(database)
    target = host[0] / "job.jsonl"
    target.write_text('{"state":"running"}\n')
    waiting = await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "wait",
            "--task-id",
            task["id"],
            "--target",
            str(target),
            "--condition",
            "done",
            "--resume-scope",
            "verify",
            "--reason",
            "running",
            "--monitor",
            "output",
        ],
    )
    async with request_application(sqlite_url(database, "rw")) as application:
        scope = await application.container.get(ResolveSessionContextUseCase).run(
            ResolveSessionContextQuery()
        )
        work = await application.container.get(ReadResultContextUseCase).run(
            ReadResultContextQuery(
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                task_id=UUID(task["id"]),
            )
        )
        monitor = work.task.monitors[0]
        await application.container.get(PrepareMonitorPollUseCase).run(
            PrepareMonitorPollCommand(
                project_id=work.task.project_id,
                session_id=scope.session.uid,
                task_id=work.task.uid,
                monitor_number=monitor.number,
                execution_id=monitor.owner_execution_id,
                generation=monitor.generation,
            )
        )
    service = await transition_service(database)
    fence = service.fence(str(database), str(tmp_path / "backups"))
    await invoke(
        database,
        ["hook", "handle", "--provider", "codex"],
        json.dumps(dict(host[2], prompt=waiting["monitors"][0]["callback"])),
    )
    restored = tmp_path / "restored.sqlite3"
    await invoke(
        database,
        ["migration", "recover", "--source", fence.snapshot, "--destination", str(restored)],
    )
    response = await invoke(
        restored, ["migration", "replay", "--directory", fence.directory], succeeds=False
    )
    assert "observation is unfinished" in str(response.exception)
    assert len(service.pending(fence.directory)) == 1


async def test_preview_has_no_database_effect_and_ambiguous_mcp_layout_is_retained(
    database, tmp_path
):
    from neurath.domain.enums.provider_kind import ProviderKind
    from neurath.infrastructure.services.installation import PosixInstallationService

    config = tmp_path / ".codex"
    config.mkdir()
    settings = config / "config.toml"
    settings.write_text('[mcp_servers.other]\ncommand = "other"\n')
    data = tmp_path / "data"
    preview = await invoke(
        database,
        [
            "maintenance",
            "install",
            "--provider",
            "codex",
            "--directory",
            str(tmp_path),
            "--data-home",
            str(data),
            "--preview",
        ],
    )
    assert preview["planned_files"] and not data.exists() and not (tmp_path / "AGENTS.md").exists()
    launcher = tmp_path / ".neurath/neurath"
    launcher.parent.mkdir()
    launcher.write_text("# neurath-managed legacy launcher\n")
    settings.write_text(
        f'[mcp_servers]\nneurath = {{command = {json.dumps(str(launcher))}, args=["serve"]}}\n'
    )
    planned, note = PosixInstallationService._legacy_mcp(tmp_path, ProviderKind.CODEX)
    assert planned == {} and "retained" in note
    settings.write_text(
        f'[mcp_servers.neurath]\ncommand = {json.dumps(str(launcher))}\nargs=["serve"]\n'
    )
    planned, note = PosixInstallationService._legacy_mcp(tmp_path, ProviderKind.CODEX)
    assert planned[settings] == "" and not note


def test_stale_wheel_guide_is_rejected_before_host_installation(tmp_path, releases):
    import sys

    a, _ = releases
    root = Path(__file__).parents[1]
    project = tmp_path / "stale-project"
    project.mkdir()
    shutil.copytree(root / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(root / "pyproject.toml", project / "pyproject.toml")
    (project / "src/neurath/resources/cli-guide.md").write_text("Outdated CLI instructions")
    (project / "src/neurath/resources/distribution.json").write_text(json.dumps(a["provenance"]))
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path / "wheel")],
        cwd=project,
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="guide is stale"):
        PosixDistributionService().prepare(
            str(next((tmp_path / "wheel").glob("*.whl"))), str(tmp_path / "runtimes"), None
        )
    assert not list((tmp_path / "runtimes").glob("*/candidate.json"))


def test_setup_preserves_cwd_and_does_not_import_the_calling_projects_tools(tmp_path):
    root = Path(__file__).parents[1]
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/__init__.py").write_text(
        "raise AssertionError('Caller tools must not be imported')\n"
    )
    result = subprocess.run(
        [str(root / "setup"), "--help"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0 and "--provider" in result.stdout
    assert not list(tmp_path.glob(".codex"))
