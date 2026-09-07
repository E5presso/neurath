"""Test real packaged engine behavior, with simulated host evidence explicitly labeled."""

import json
import os
import subprocess
import sys

import pytest

from neurath.doctor import integrity, protocol_smoke
from neurath.install.transaction import apply_plan, make_plan


def test_package_integrity_and_both_host_protocols():
    assert integrity()["status"] == "passed"
    assert all(result["status"] == "passed" for result in protocol_smoke().values())


def test_installed_contracts_ignore_target_contract_name_collision(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".agents/skills").mkdir(parents=True)
    (tmp_path / ".agents/skills/contracts.json").write_text('{"skills":{}}')
    apply_plan(tmp_path, make_plan(tmp_path))
    script = """
import json, sys
from pathlib import Path
from neurath.runtime.engine import activate
activate(Path(sys.argv[1]))
from scripts.skill_harness.phase_runner import SkillContractRepository
from scripts.agent_harness.agent_continuation_hook import AgentContinuationHookCli
repository = SkillContractRepository(Path(sys.argv[1]))
contract = repository.get('commit')
assert contract.name == 'commit'
print('contract-and-monitor-import-passed')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".agents/skills/contracts.json").read_text() == '{"skills":{}}'


def test_generic_verification_uses_configured_command_without_uv(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    (tmp_path / ".neurath/project.json").write_text(
        json.dumps(
            {
                "verification": {
                    "check": {
                        "argv": [sys.executable, "-c", "print('tested')"],
                        "success_codes": [0],
                        "stdout_contains": "tested",
                    }
                }
            }
        )
    )
    result = subprocess.run(
        [
            str(tmp_path / ".neurath/run"),
            "engine",
            "scripts.agent_harness.verification_runner",
            "check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "passed"
    assert not (tmp_path / ".venv").exists()


def test_unsupported_and_cross_repository_hook_inputs_fail_closed(tmp_path):
    from neurath.hosts.hooks import hook

    code, _payload, _diagnostic = hook(
        tmp_path,
        "codex",
        json.dumps({"hook_event_name": "PermissionDenied", "cwd": str(tmp_path)}),
        {},
    )
    assert code == 2
    code, _payload, _diagnostic = hook(
        tmp_path, "codex", json.dumps({"hook_event_name": "PreToolUse", "cwd": "/"}), {}
    )
    assert code == 2


def test_generic_capability_policy_has_no_project_connector_requirement(tmp_path):
    from neurath.hosts.capabilities import capability_policy

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "codex mcp remove penpot"},
            "cwd": str(tmp_path),
        }
    )
    assert capability_policy(tmp_path).run(payload, tmp_path).exit_code == 0
    (tmp_path / ".neurath/project.json").write_text(
        json.dumps({"protected_capabilities": {"connectors": ["penpot"]}})
    )
    assert capability_policy(tmp_path).run(payload, tmp_path).exit_code == 2


def test_tracked_installation_hooks_follow_linked_worktree(tmp_path):
    root = tmp_path / "main"
    linked = tmp_path / "linked"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    apply_plan(root.resolve(), make_plan(root))
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", str(linked)],
        check=True,
        capture_output=True,
    )
    command = json.loads((linked / ".codex/hooks.json").read_text())["hooks"]["SessionStart"][0][
        "hooks"
    ][0]["command"]
    payload = {
        "hook_event_name": "SessionStart",
        "session_id": "linked-session",
        "source": "startup",
        "cwd": str(linked),
        "permission_mode": "default",
        "transcript_path": None,
    }
    environment = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_"))
    }
    environment["CODEX_THREAD_ID"] = "linked-session"
    process = subprocess.run(
        ["sh", "-c", command],
        input=json.dumps(payload),
        cwd=linked,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert isinstance(json.loads(process.stdout), dict)


def test_original_readback_engine_supports_new_unborn_repository(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    script = """
from pathlib import Path
import sys

import pytest
from neurath.runtime.engine import activate
activate(Path(sys.argv[1]))
from scripts.agent_harness.repository_readback import RepositoryWorktreeReadback
root=Path(sys.argv[1]); reader=RepositoryWorktreeReadback(root)
before=reader.worktree_fingerprint()
(root/'new.txt').write_text('first file')
assert before != reader.worktree_fingerprint()
"""
    process = subprocess.run(
        [sys.executable, "-I", "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize(
    "command",
    [
        'rm README.md; echo "exit=$?"',
        "echo before&&rm README.md",
        "echo before\nrm README.md",
        "(rm README.md)",
        "sh -c 'rm README.md; echo done'",
        'rm "README".md; echo done',
    ],
)
def test_protected_deletion_in_compound_shell_is_denied(tmp_path, command):
    from neurath.hosts.capabilities import capability_policy

    (tmp_path / ".neurath").mkdir()
    (tmp_path / ".neurath/project.json").write_text(
        json.dumps({"protected_capabilities": {"paths": ["README.md"]}})
    )
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    result = capability_policy(tmp_path).run(payload, tmp_path)
    assert result.exit_code == 2
    assert "protected-capability" in result.stderr


@pytest.mark.parametrize(
    "command", ['echo "rm README.md; echo done"', 'rm "unrelated;file"', 'printf "%s" "&&"']
)
def test_quoted_shell_operators_are_data(tmp_path, command):
    from neurath.hosts.capabilities import capability_policy

    (tmp_path / ".neurath").mkdir()
    (tmp_path / ".neurath/project.json").write_text(
        json.dumps({"protected_capabilities": {"paths": ["README.md"]}})
    )
    assert (
        capability_policy(tmp_path)
        .run(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}), tmp_path)
        .exit_code
        == 0
    )
