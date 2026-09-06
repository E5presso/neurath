"""Actual native compatibility payload shape; synthetic paths never delete files."""

import json
import pytest
from neurath.hosts.capabilities import capability_policy


@pytest.mark.parametrize(
    "command,expected",
    [
        ("true && rm skills/neurath-explore-ui/__native_denial_probe_absent__", 2),
        ("rm unrelated-name", 2),
        ("rm SKILL.md", 2),
        ("rm /tmp/unrelated-native-probe", 0),
        ("rm /tmp/unrelated-native-probe*", 0),
        ("rm {root}/.agents/skills/neurath-explore-ui/*", 2),
        ("rm {root}/.agents/skills/neurath-explore-*", 2),
        ("rm {root}/.agent*", 2),
        ('printf "%s" "rm skills/neurath-explore-ui/probe"', 0),
        ("rg -n protected .", 0),
    ],
)
def test_codex_omitted_workdir_and_absolute_globs(tmp_path, command, expected):
    payload = {
        "tool_name": "Bash",
        "tool_use_id": "exec-native-probe",
        "turn_id": "native-turn",
        "cwd": str(tmp_path),
        "tool_input": {"command": command.format(root=tmp_path)},
    }
    result = capability_policy(tmp_path).run(json.dumps(payload), tmp_path)
    assert result.exit_code == expected, result.stderr


@pytest.mark.parametrize(
    "workdir,target,expected",
    [
        (".agents", "skills/neurath-explore-ui/probe", 2),
        (".agents/skills/neurath-explore-ui", "probe", 2),
        (".agents", "skills/explore-ui/probe", 2),
        (".agents/skills/explore-ui", "probe", 2),
        (".claude/skills", "explore-ui/probe", 2),
        (".agents/skills", "design-ui/probe", 2),
        (".claude/skills", "qa/probe", 2),
        (".agents", "unrelated/probe", 0),
    ],
)
def test_explicit_workdir_remains_authoritative(tmp_path, workdir, target, expected):
    payload = {
        "tool_name": "Bash",
        "tool_use_id": "exec-native-probe",
        "turn_id": "native-turn",
        "cwd": str(tmp_path),
        "tool_input": {"command": f"true && rm {target}", "workdir": str(tmp_path / workdir)},
    }
    assert capability_policy(tmp_path).run(json.dumps(payload), tmp_path).exit_code == expected


@pytest.mark.parametrize("prefix,suffix", [
    ("if ", "; then :; fi"), ("while ", "; do break; done"),
    ("until ", "; do break; done"), ("env -i ", ""),
    ("env --ignore-environment ", ""), ("env -u NAME ", ""),
    ("command -p ", ""), ("sudo -n ", ""), ("sudo -u root ", ""),
    ("env -i command -p ", ""),
])
def test_standard_shell_prefixes_preserve_protected_path_denial(tmp_path, prefix, suffix):
    for target, expected in ((".neurath/guard-fixture", 2), ("ordinary-fixture", 0)):
        payload = {
            "tool_name": "Bash", "tool_use_id": "prefix-probe", "cwd": str(tmp_path),
            "tool_input": {"command": f"{prefix}rm {target}{suffix}", "workdir": str(tmp_path)},
        }
        assert capability_policy(tmp_path).run(json.dumps(payload), tmp_path).exit_code == expected


@pytest.mark.parametrize("prefix", ["env -C", "env --chdir", "sudo -D", "sudo --chdir"])
def test_prefix_directory_controls_relative_deletion_target(tmp_path, prefix):
    for directory, expected in ((".neurath", 2), ("ordinary", 0)):
        payload = {"tool_name": "Bash", "tool_use_id": "cwd-probe", "cwd": str(tmp_path),
                   "tool_input": {"command": f"{prefix} {directory} rm guard-fixture",
                                  "workdir": str(tmp_path)}}
        assert capability_policy(tmp_path).run(json.dumps(payload), tmp_path).exit_code == expected


@pytest.mark.parametrize("command", [
    "env -S 'rm .neurath/guard-fixture'",
    "env --split-string='rm .neurath/guard-fixture'",
    "env -S'rm .neurath/guard-fixture'",
    "sudo -R other-root rm fixture",
])
def test_uninterpreted_execution_options_fail_closed(tmp_path, command):
    payload = {"tool_name": "Bash", "tool_use_id": "option-probe", "cwd": str(tmp_path),
               "tool_input": {"command": command, "workdir": str(tmp_path)}}
    assert capability_policy(tmp_path).run(json.dumps(payload), tmp_path).exit_code == 2


@pytest.mark.parametrize("command,expected", [
    ("cd .neurath && rm fixture", 2),
    ("cd ordinary && rm fixture", 0),
    ("(cd .neurath); rm fixture", 0),
    ("(cd .neurath; rm fixture)", 2),
    ("cd ordinary; (cd ../.neurath; rm fixture)", 2),
    ("cd ordinary; (cd ../.neurath); rm fixture", 0),
    ("cd ../elsewhere || rm .neurath/fixture", 2),
    ("cd .neurath || true; rm fixture", 2),
    ("cd .neurath || exit 1; rm fixture", 2),
    ("cd .neurath || cd .. && rm fixture", 2),
])
def test_literal_cd_preserves_command_and_subshell_scope(tmp_path, command, expected):
    payload = {"tool_name": "Bash", "tool_use_id": "cd-probe", "cwd": str(tmp_path),
               "tool_input": {"command": command, "workdir": str(tmp_path)}}
    assert capability_policy(tmp_path).run(json.dumps(payload), tmp_path).exit_code == expected
