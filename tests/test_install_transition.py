"""공유 rules와 실제 구형 manifest 형식의 소유 영역을 보존형 설치로 검증한다."""

import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from neurath.domain.enums.provider_kind import ProviderKind
from neurath.infrastructure.services.installation import PosixInstallationService
from neurath.infrastructure.services.skill_catalog import PosixSkillCatalogService


def legacy_project(root):
    root.mkdir()
    (root / ".neurath").mkdir()
    launcher = root / ".neurath/run"
    launcher.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -I -m neurath --root {shlex.quote(str(root))} "$@"\n'
    )
    launcher.chmod(0o755)
    (root / "AGENTS.md").write_text(
        "User policy before.\n<!-- neurath:managed -->\n## Neurath\nUse MCP server neurath. Call lease.acquire and harness_bypass.\n<!-- /neurath:managed -->\nUser policy after.\n"
    )
    (root / "CLAUDE.md").symlink_to("AGENTS.md")
    paths = [launcher, root / "AGENTS.md"]
    for provider in ProviderKind:
        config = root / (".codex" if provider is ProviderKind.CODEX else ".claude")
        config.mkdir()
        alias = "codex" if provider is ProviderKind.CODEX else "claude-code"
        command = f"{shlex.quote(str(launcher))} hook --provider {alias}"
        path = config / ("hooks.json" if provider is ProviderKind.CODEX else "settings.json")
        path.write_text(
            json.dumps(
                {
                    "custom": "preserve",
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "matcher": "*",
                                "custom": "group policy",
                                "hooks": [
                                    {"type": "command", "command": command},
                                    {"type": "command", "command": "/bin/true", "timeout": 7},
                                ],
                            }
                        ],
                        "Stop": [{"hooks": [{"type": "command", "command": command}]}],
                        "OldEvent": [{"hooks": [{"type": "command", "command": command}]}],
                    },
                }
            )
        )
        paths.append(path)
    codex = root / ".codex/config.toml"
    codex.write_text(
        f'user = "preserve"\n[mcp_servers.neurath]\ncommand = {json.dumps(str(launcher))}\nargs = ["mcp", "--provider", "codex"]\n[mcp_servers.other]\ncommand = "other-extension"\n'
    )
    claude = root / ".mcp.json"
    claude.write_text(
        json.dumps(
            {
                "custom": "preserve",
                "mcpServers": {
                    "neurath": {
                        "command": str(launcher),
                        "args": ["mcp", "--provider", "claude-code"],
                    },
                    "other": {"command": "other-extension"},
                },
            }
        )
    )
    paths.extend([codex, claude])
    manifest = {
        "server": "neurath",
        "version": "0.3.1",
        "python": sys.executable,
        "wheel_sha256": "historical-fixture",
        "native_activation": "not current evidence",
        "files": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        },
    }
    (root / ".neurath/install.json").write_text(json.dumps(manifest))
    (root / ".neurath/project.json").write_text('{"schema":1,"documents":{},"verification":{}}')
    with sqlite3.connect(root / ".neurath/runtime.sqlite3") as db:
        db.execute("CREATE TABLE unfinished_work(body TEXT)")
        db.execute("INSERT INTO unfinished_work VALUES('Preserve old work')")
    return manifest


def guided_command(root, provider):
    rules = root / ("AGENTS.md" if provider is ProviderKind.CODEX else "CLAUDE.md")
    relative = re.search(rf"- {provider.value}: .*?\]\(<([^>]+)>\)", rules.read_text())[1]
    assert not Path(relative).is_absolute()
    body = (root / relative).read_text()
    command = shlex.split(re.search(r"Use this installed command: `([^`]+)`", body)[1])[0]
    skills = re.findall(r"\]\(<([^>]+/SKILL\.md)>\)", body)
    assert len(skills) == 14
    expected = root / (".agents/skills" if provider is ProviderKind.CODEX else ".claude/skills")
    assert all(Path(path).is_relative_to(expected) and Path(path).is_file() for path in skills)
    return command


@pytest.mark.parametrize(
    "order", [(ProviderKind.CODEX, ProviderKind.CLAUDE), (ProviderKind.CLAUDE, ProviderKind.CODEX)]
)
async def test_shared_rules_route_each_host_in_both_install_orders(tmp_path, order):
    root = tmp_path / "shared project"
    root.mkdir()
    (root / "AGENTS.md").write_text("Keep the user's project policy.\n")
    (root / "CLAUDE.md").symlink_to("AGENTS.md")
    service = PosixInstallationService(PosixSkillCatalogService())
    for provider in order:
        installed = await service.install(provider, str(root), str(tmp_path / "data"))
        command = guided_command(root, provider)
        assert command == installed.command
        environment = dict(
            os.environ,
            NEURATH_SESSION_ID=f"shared-{provider.value}",
            NEURATH_PROVIDER=provider.value,
        )
        payload = {
            "session_id": f"shared-{provider.value}",
            "cwd": str(root),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Preserve this host's original work",
        }
        subprocess.run(
            [command, "hook", "handle", "--provider", provider.value],
            cwd=root,
            env=environment,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
    original = (root / "AGENTS.md").read_bytes()
    for provider in (*reversed(order), *order):
        result = await service.install(provider, str(root), str(tmp_path / "data"))
        assert result.changed_files == () and (root / "AGENTS.md").read_bytes() == original
        command = guided_command(root, provider)
        environment = dict(
            os.environ,
            NEURATH_SESSION_ID=f"shared-{provider.value}",
            NEURATH_PROVIDER=provider.value,
        )
        response = subprocess.run(
            [command, "context", "show"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(response.stdout)["host"]["provider"] == provider.value
        assert json.loads(response.stdout)["host"]["session"] == f"shared-{provider.value}"
    assert (root / "CLAUDE.md").is_symlink() and (root / "CLAUDE.md").readlink() == Path(
        "AGENTS.md"
    )
    assert str(root) not in (root / "AGENTS.md").read_text()
    assert (root / "AGENTS.md").read_text().startswith("Keep the user's project policy.")


@pytest.mark.parametrize(
    "order", [(ProviderKind.CODEX, ProviderKind.CLAUDE), (ProviderKind.CLAUDE, ProviderKind.CODEX)]
)
async def test_manifest_proven_legacy_handlers_mcp_and_rules_transition_without_user_loss(
    tmp_path, order
):
    root = (tmp_path / "legacy with spaces").resolve()
    legacy_project(root)
    raw_database = (root / ".neurath/runtime.sqlite3").read_bytes()
    rules = root / "AGENTS.md"
    rules.write_text("New user policy outside the old block.\n" + rules.read_text())
    service = PosixInstallationService(PosixSkillCatalogService())
    for provider in order:
        old_rules = rules.read_bytes()
        result = await service.install(provider, str(root), str(tmp_path / "data"))
        path = root / (
            ".codex/hooks.json" if provider is ProviderKind.CODEX else ".claude/settings.json"
        )
        document = json.loads(path.read_text())
        assert document["custom"] == "preserve"
        group = document["hooks"]["UserPromptSubmit"][0]
        assert group == {
            "matcher": "*",
            "custom": "group policy",
            "hooks": [{"type": "command", "command": "/bin/true", "timeout": 7}],
        }
        assert document["hooks"]["OldEvent"] == []
        commands = [
            handler["command"]
            for groups in document["hooks"].values()
            for group in groups
            for handler in group["hooks"]
        ]
        assert not any(str(root / ".neurath/run") in command for command in commands)
        assert len(document["hooks"]["Stop"]) == 1
        if provider is ProviderKind.CODEX:
            mcp = tomllib.loads((root / ".codex/config.toml").read_text())["mcp_servers"]
        else:
            mcp = json.loads((root / ".mcp.json").read_text())["mcpServers"]
        assert "neurath" not in mcp and mcp["other"]["command"] == "other-extension"
        if "<!-- neurath:managed -->" in old_rules.decode():
            assert any(Path(path).read_bytes() == old_rules for path in result.backups)
    text = rules.read_text()
    assert text.startswith("New user policy outside the old block.\nUser policy before.")
    assert (
        "User policy after." in text
        and "lease.acquire" not in text
        and "harness_bypass" not in text
    )
    assert "<!-- neurath:managed -->" not in text and text.count("<!-- neurath:begin -->") == 1
    assert (root / "CLAUDE.md").is_symlink()
    assert (root / ".neurath/runtime.sqlite3").read_bytes() == raw_database
    for provider in order:
        assert (
            await service.install(provider, str(root), str(tmp_path / "data"))
        ).changed_files == ()


@pytest.mark.parametrize(
    "uncertain",
    [
        "launcher-hash",
        "hooks-hash",
        "missing-manifest",
        "wrong-python",
        "wrong-root",
        "wrong-module",
    ],
)
async def test_unconfirmed_old_invocation_does_not_add_a_competing_hook(tmp_path, uncertain):
    root = tmp_path / "legacy"
    manifest = legacy_project(root)
    launcher = root / ".neurath/run"
    hooks = root / ".codex/hooks.json"
    if uncertain == "launcher-hash":
        launcher.write_text(launcher.read_text() + "# changed\n")
    elif uncertain == "hooks-hash":
        hooks.write_text(hooks.read_text() + "\n")
    elif uncertain == "missing-manifest":
        (root / ".neurath/install.json").unlink()
    else:
        if uncertain == "wrong-python":
            manifest["python"] = "/unobserved/python"
        elif uncertain == "wrong-root":
            launcher.write_text(launcher.read_text().replace(str(root), str(tmp_path / "other")))
        else:
            launcher.write_text(launcher.read_text().replace("-m neurath", "-m unrelated"))
        manifest["files"][".neurath/run"] = hashlib.sha256(launcher.read_bytes()).hexdigest()
        (root / ".neurath/install.json").write_text(json.dumps(manifest))
    before = hooks.read_bytes()
    service = PosixInstallationService(PosixSkillCatalogService())
    for preview in (True, False):
        with pytest.raises(ValueError):
            await service.install(
                ProviderKind.CODEX, str(root), str(tmp_path / "data"), preview=preview
            )
        assert hooks.read_bytes() == before
        assert not (root / ".codex/neurath/neurath").exists() and not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "invalid", ["missing-end", "duplicate", "nested", "unknown-body", "missing-owner"]
)
async def test_unclear_legacy_rules_are_preserved_without_new_conflicting_rules(tmp_path, invalid):
    root = tmp_path / "legacy"
    manifest = legacy_project(root)
    rules = root / "AGENTS.md"
    text = rules.read_text()
    if invalid == "missing-end":
        text = text.replace("<!-- /neurath:managed -->", "")
    elif invalid == "duplicate":
        text += "<!-- neurath:managed -->"
    elif invalid == "nested":
        text = text.replace(
            "## Neurath", "<!-- neurath:begin -->\n## Neurath\n<!-- neurath:end -->"
        )
    elif invalid == "unknown-body":
        text = text.replace(
            "## Neurath\nUse MCP server neurath. Call lease.acquire and harness_bypass.",
            "User content whose ownership cannot be inferred",
        )
    else:
        del manifest["files"]["AGENTS.md"]
        (root / ".neurath/install.json").write_text(json.dumps(manifest))
    rules.write_text(text)
    with pytest.raises(ValueError, match="Legacy Neurath instruction"):
        await PosixInstallationService(PosixSkillCatalogService()).install(
            ProviderKind.CODEX, str(root), str(tmp_path / "data")
        )
    assert rules.read_text() == text and not (tmp_path / "data").exists()


async def test_unowned_provider_guide_is_not_replaced(tmp_path):
    root = tmp_path / "project"
    path = root / ".codex/neurath/guide.md"
    path.parent.mkdir(parents=True)
    path.write_text("User guide")
    with pytest.raises(FileExistsError, match="provider guide"):
        await PosixInstallationService(PosixSkillCatalogService()).install(
            ProviderKind.CODEX, str(root), str(tmp_path / "data")
        )
    assert path.read_text() == "User guide" and not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        {},
        {"server": "other", "files": {}},
        {"server": "neurath", "files": []},
        {"server": "neurath", "files": {"AGENTS.md": "invalid"}},
    ],
)
async def test_unrecognized_manifest_preserves_old_rules(tmp_path, manifest):
    root = tmp_path / "legacy"
    legacy_project(root)
    (root / ".neurath/install.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="ownership"):
        await PosixInstallationService(PosixSkillCatalogService()).install(
            ProviderKind.CODEX, str(root), str(tmp_path / "data")
        )
    assert "<!-- neurath:managed -->" in (root / "AGENTS.md").read_text()


@pytest.mark.parametrize(
    "command",
    [
        "# no exec",
        "exec too few",
        'exec unknown -I -m neurath --root /other "wrong"',
        "exec one\nexec two",
    ],
)
async def test_manifest_hash_alone_does_not_establish_launcher_ownership(tmp_path, command):
    root = tmp_path / "legacy"
    manifest = legacy_project(root)
    path = root / ".neurath/run"
    path.write_text(command)
    manifest["files"][".neurath/run"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / ".neurath/install.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="competing handler"):
        await PosixInstallationService(PosixSkillCatalogService()).install(
            ProviderKind.CODEX, str(root), str(tmp_path / "data")
        )
    assert not (tmp_path / "data").exists()


async def test_old_and_current_blocks_converge_and_ambiguous_mcp_is_preserved(tmp_path):
    root = tmp_path / "legacy"
    legacy_project(root)
    rules = root / "AGENTS.md"
    rules.write_text(
        rules.read_text() + "\n<!-- neurath:begin -->\nPrior CLI guide\n<!-- neurath:end -->\n"
    )
    mcp = root / ".codex/config.toml"
    original = mcp.read_text() + "\n# user edited configuration\n"
    mcp.write_text(original)
    result = await PosixInstallationService(PosixSkillCatalogService()).install(
        ProviderKind.CODEX, str(root), str(tmp_path / "data")
    )
    assert mcp.read_text() == original and "neurath" in result.host_action.lower()
    assert "<!-- neurath:managed -->" not in rules.read_text()
    assert rules.read_text().count("<!-- neurath:begin -->") == 1


async def test_mixed_current_handlers_and_unknown_shapes_preserve_unrelated_data(tmp_path):
    root = tmp_path / "project"
    config = root / ".codex"
    config.mkdir(parents=True)
    command = f"{root}/.codex/neurath/neurath hook handle --provider codex"
    preserved = [
        None,
        {"hooks": "unknown"},
        {"hooks": []},
        {
            "hooks": [
                None,
                {"type": "prompt", "command": command},
                {"type": "command", "command": None},
                {"type": "command", "command": "'broken quote"},
            ]
        },
    ]
    path = config / "hooks.json"
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        *preserved,
                        {
                            "extra": "preserve",
                            "hooks": [
                                {"type": "command", "command": command},
                                {"type": "command", "command": "/bin/true"},
                            ],
                        },
                    ]
                }
            }
        )
    )
    await PosixInstallationService(PosixSkillCatalogService()).install(
        ProviderKind.CODEX, str(root), str(tmp_path / "data")
    )
    groups = json.loads(path.read_text())["hooks"]["Stop"]
    assert groups[:-2] == preserved
    assert groups[-2] == {
        "extra": "preserve",
        "hooks": [{"type": "command", "command": "/bin/true"}],
    }


async def test_legacy_launcher_real_path_alias_keeps_exact_target_ownership(tmp_path):
    physical = tmp_path / "physical"
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)
    physical.mkdir()
    root = alias / "project"
    legacy_project(root)
    for provider in ProviderKind:
        await PosixInstallationService(PosixSkillCatalogService()).install(
            provider, str(root), str(tmp_path / "data")
        )
        path = root / (
            ".codex/hooks.json" if provider is ProviderKind.CODEX else ".claude/settings.json"
        )
        groups = json.loads(path.read_text())["hooks"]["Stop"]
        assert len(groups) == 1 and "hook handle" in groups[0]["hooks"][0]["command"]
    assert "[mcp_servers.neurath]" not in (root / ".codex/config.toml").read_text()
    assert "neurath" not in json.loads((root / ".mcp.json").read_text())["mcpServers"]


async def test_manifest_owned_rules_symlink_outside_root_preserves_user_target(tmp_path):
    root = tmp_path / "project"
    legacy_project(root)
    rules = root / "AGENTS.md"
    shared = tmp_path / "shared-rules.md"
    rules.rename(shared)
    rules.symlink_to(shared)
    await PosixInstallationService(PosixSkillCatalogService()).install(
        ProviderKind.CODEX, str(root), str(tmp_path / "data")
    )
    assert rules.is_symlink() and shared.read_text().startswith("User policy before.")
    assert "User policy after." in shared.read_text() and "lease.acquire" not in shared.read_text()
