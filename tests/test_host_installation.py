"""실제 사용자 설정·DB의 보존과 설치 실패의 복구 경계를 검증한다."""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from click import unstyle

from neurath.domain.enums.provider_kind import ProviderKind
from neurath.infrastructure.services.installation import PosixInstallationService
from neurath.infrastructure.services.skill_catalog import PosixSkillCatalogService


@pytest.mark.parametrize("provider", list(ProviderKind))
@pytest.mark.parametrize("color", [False, True], ids=["plain", "color"])
async def test_install_preserves_user_content_and_is_idempotent(tmp_path, provider, color):
    root = tmp_path / "project"
    root.mkdir()
    config = root / (".codex" if provider is ProviderKind.CODEX else ".claude")
    config.mkdir()
    rule = root / ("AGENTS.md" if provider is ProviderKind.CODEX else "CLAUDE.md")
    rule.write_text("User's original instructions\n")
    hooks = config / ("hooks.json" if provider is ProviderKind.CODEX else "settings.json")
    hooks.write_text(
        json.dumps(
            {
                "custom": "preserve",
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "user-owned"}]}]},
            }
        )
    )
    original = hooks.read_bytes()
    service = PosixInstallationService(PosixSkillCatalogService())
    installed = await service.install(provider, str(root), str(tmp_path / "data"))
    assert installed.changed_files and len(installed.backups) == 2
    assert rule.read_text().startswith("User's original instructions\n")
    assert "custom" in json.loads(hooks.read_text())
    assert json.loads(hooks.read_text())["hooks"]["Stop"][0]["hooks"][0]["command"] == "user-owned"
    assert any(Path(path).read_bytes() == original for path in installed.backups)
    assert "trust hashes" in installed.host_action
    before = {p: p.read_bytes() for p in (rule, hooks, Path(installed.command))}
    again = await service.install(provider, str(root), str(tmp_path / "data"))
    assert again.changed_files == ()
    assert {p: p.read_bytes() for p in before} == before
    assert len(again.backups) == 1
    with sqlite3.connect(again.database) as db, sqlite3.connect(again.backups[0]) as backup:
        assert (
            db.execute("SELECT * FROM core_schema_revision").fetchall()
            == backup.execute("SELECT * FROM core_schema_revision").fetchall()
        )
    skills = root / (".agents/skills" if provider is ProviderKind.CODEX else ".claude/skills")
    assert len(list(skills.glob("*/SKILL.md"))) == 14
    env = dict(os.environ)
    for name in (
        "NO_COLOR",
        "FORCE_COLOR",
        "PY_COLORS",
        "GITHUB_ACTIONS",
        "_TYPER_FORCE_DISABLE_TERMINAL",
    ):
        env.pop(name, None)
    env["TERM"] = "xterm-256color" if color else "dumb"
    if color:
        env["GITHUB_ACTIONS"] = "true"
    result = subprocess.run(
        [installed.command, "context", "show", "--help"],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert ("\x1b[" in result.stdout) is color
    assert "--section" in unstyle(result.stdout)


@pytest.mark.parametrize(
    "kind",
    [
        "executable",
        "skill",
        "hooks-array",
        "groups-object",
        "broken-marker",
        "reversed-marker",
        "duplicate-marker",
    ],
)
async def test_invalid_install_plan_leaves_user_files_and_database_unchanged(tmp_path, kind):
    config = tmp_path / ".codex"
    config.mkdir()
    if kind == "executable":
        path = config / "neurath/neurath"
        content = "#!/bin/sh\n# user's own executable\n"
    elif kind == "skill":
        path = tmp_path / ".agents/skills/qa/SKILL.md"
        content = "My QA skill"
    elif kind in ("hooks-array", "groups-object"):
        path = config / "hooks.json"
        content = "[]" if kind == "hooks-array" else '{"hooks":{"Stop":{}}}'
    else:
        path = tmp_path / "AGENTS.md"
        content = {
            "broken-marker": "<!-- neurath:begin -->",
            "reversed-marker": "<!-- neurath:end --> x <!-- neurath:begin -->",
            "duplicate-marker": "<!-- neurath:begin --> <!-- neurath:begin --> <!-- neurath:end -->",
        }[kind]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    service = PosixInstallationService(PosixSkillCatalogService())
    if kind == "skill":
        result = await service.install(ProviderKind.CODEX, str(tmp_path), str(tmp_path / "data"))
        assert result.skill_overrides == {"qa": str(path.resolve())}
        assert Path(result.command).is_file()
        assert (tmp_path / "data/neurath/core.sqlite3").exists()
    else:
        with pytest.raises((ValueError, FileExistsError)):
            await service.install(ProviderKind.CODEX, str(tmp_path), str(tmp_path / "data"))
        assert not (tmp_path / "data/neurath/core.sqlite3").exists()
    assert path.read_text() == content


async def test_install_rollback_restores_previous_settings(tmp_path, monkeypatch):
    original = tmp_path / "AGENTS.md"
    original.write_text("user instructions")
    calls = []
    replace = os.replace

    def fail_second(source, target):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("disk unavailable")
        return replace(source, target)

    monkeypatch.setattr(os, "replace", fail_second)
    with pytest.raises(OSError, match="disk unavailable"):
        await PosixInstallationService(PosixSkillCatalogService()).install(
            ProviderKind.CODEX, str(tmp_path), str(tmp_path / "data")
        )
    assert original.read_text() == "user instructions"
    assert not (tmp_path / ".codex/neurath/neurath").exists()
    assert not list(tmp_path.rglob("*.tmp-*"))


async def test_initialize_preserves_corrupt_database_and_supports_user_default(tmp_path):
    service = PosixInstallationService(PosixSkillCatalogService())
    default = Path(await service.initialize(None))
    assert default.exists()
    assert await service.initialize(str(default)) == str(default)
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"unrelated original data")
    with pytest.raises(Exception):
        await service.initialize(str(corrupt))
    assert corrupt.read_bytes() == b"unrelated original data"
    file = tmp_path / "not-a-directory"
    file.write_text("user file")
    with pytest.raises(ValueError, match="directory"):
        await service.install(ProviderKind.CODEX, str(file), None)


async def test_install_preserves_instruction_symlink_and_uses_default_data_home(tmp_path):
    original = tmp_path / "shared-instructions.md"
    original.write_text("shared user instruction")
    link = tmp_path / "AGENTS.md"
    link.symlink_to(original)
    installed = await PosixInstallationService(PosixSkillCatalogService()).install(
        ProviderKind.CODEX, str(tmp_path), None
    )
    assert link.is_symlink() and original.read_text().startswith("shared user instruction")
    assert Path(installed.database).is_file()


@pytest.mark.parametrize(
    "group",
    [None, {}, {"hooks": []}, {"hooks": ["not-a-record"]}, {"hooks": [{"command": "different"}]}],
)
def test_foreign_hook_groups_are_never_claimed(group):
    assert not PosixInstallationService._managed_hook(group, "owned")


async def test_maintenance_cli_initializes_and_installs_current_package(tmp_path):
    from tests.test_host_flow import invoke

    initialized = await invoke(
        tmp_path / "unused.db",
        ["maintenance", "initialize", "--database", str(tmp_path / "managed.db")],
    )
    assert initialized
    installed = await invoke(
        tmp_path / "unused.db",
        [
            "maintenance",
            "install",
            "--provider",
            "codex",
            "--directory",
            str(tmp_path),
            "--data-home",
            str(tmp_path / "private-data"),
        ],
    )
    assert Path(installed["command"]).exists()
    assert Path(installed["database"]).exists()


async def test_module_entrypoint_defers_initialization_until_main(tmp_path, monkeypatch, capsys):
    import atexit
    import runpy
    import sys

    callbacks = []
    monkeypatch.setattr(atexit, "register", callbacks.append)
    monkeypatch.delenv("SPAKKY_SQLALCHEMY__CONNECTION_STRING", raising=False)
    namespace = runpy.run_module("neurath.entrypoint", run_name="fixture_import")
    assert "cli" not in namespace
    monkeypatch.setattr(sys, "argv", ["neurath", "--help"])
    try:
        with pytest.raises(SystemExit) as stopped:
            runpy.run_module("neurath.entrypoint", run_name="__main__")
        assert stopped.value.code == 0
        assert "context" in capsys.readouterr().out
    finally:
        for callback in callbacks:
            callback()
        sys.modules.pop("neurath.cli", None)
