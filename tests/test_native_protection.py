"""Actual native compatibility payload shape; synthetic paths never delete files."""

import json
import shutil
import subprocess
import pytest
from neurath.hosts.capabilities import capability_policy
from neurath.install.transaction import apply_plan, make_plan


def test_verified_generated_skill_can_leave_git_index_without_deleting_file(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    target = ".agents/skills/update-neurath/SKILL.md"
    installed = tmp_path / target
    git = shutil.which("git")
    original = installed.read_bytes()
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", target], check=True)
    (tmp_path / ".gitignore").write_text(f"/{target}\n")
    payload = {"tool_name": "Bash", "tool_use_id": "exec-index-migration",
               "turn_id": "native-turn", "cwd": str(tmp_path),
               "tool_input": {"command": f"{git} rm --cached -- {installed}"}}
    assert capability_policy(tmp_path).run(json.dumps(payload), tmp_path).exit_code == 0
    explicit = {**payload, "tool_input": {"command": f"{git} rm --cached -- {target}",
                                              "workdir": str(tmp_path)}}
    assert capability_policy(tmp_path).run(json.dumps(explicit), tmp_path).exit_code == 0
    subprocess.run(["git", "-C", str(tmp_path), "rm", "--cached", "--", target], check=True,
                   capture_output=True)
    assert installed.read_bytes() == original


@pytest.mark.parametrize("change", ["modified", "modified-index", "broad-ignore",
                                   "real-delete", "relative-unknown-workdir"])
def test_generated_skill_untracking_stays_guarded(tmp_path, change):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    target = ".agents/skills/update-neurath/SKILL.md"
    installed = tmp_path / target
    git = shutil.which("git")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", target], check=True)
    (tmp_path / ".gitignore").write_text(f"/{target}\n")
    command = f"{git} rm --cached -- {installed}"
    if change == "modified":
        installed.write_bytes(installed.read_bytes() + b"changed")
    elif change == "modified-index":
        original = installed.read_bytes()
        installed.write_bytes(original + b"changed")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-f", target], check=True)
        installed.write_bytes(original)
    elif change == "broad-ignore":
        (tmp_path / ".gitignore").write_text("/.agents/skills/*\n")
    elif change == "real-delete":
        command = f"{git} rm -- {installed}"
    else:
        command = f"{git} rm --cached -- {target}"
    payload = {"tool_name": "Bash", "tool_use_id": "exec-index-migration",
               "turn_id": "native-turn", "cwd": str(tmp_path),
               "tool_input": {"command": command}}
    assert capability_policy(tmp_path).run(json.dumps(payload), tmp_path).exit_code == 2


def test_local_git_named_script_cannot_bypass_skill_deletion_guard(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    target = ".agents/skills/update-neurath/SKILL.md"
    installed = tmp_path / target
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", target], check=True)
    (tmp_path / ".gitignore").write_text(f"/{target}\n")
    (tmp_path / "git").write_text("#!/bin/sh\nrm -f \"$4\"\n")
    (tmp_path / "git").chmod(0o755)
    payload = {"tool_name": "Bash", "tool_use_id": "exec-index-migration",
               "turn_id": "native-turn", "cwd": str(tmp_path),
               "tool_input": {"command": f"./git rm --cached -- {installed}",
                              "workdir": str(tmp_path)}}
    assert capability_policy(tmp_path).run(json.dumps(payload), tmp_path).exit_code == 2


def test_continued_heredoc_header_cannot_hide_following_command(tmp_path):
    command = "cat <<'EOF' \\\n; rm -rf .neurath\nbody\nEOF\n"
    result = capability_policy(tmp_path).run(json.dumps({
        "tool_name": "Bash", "cwd": str(tmp_path),
        "tool_input": {"command": command, "workdir": str(tmp_path)},
    }), tmp_path)
    assert result.exit_code == 2
    assert "continued line" in result.stderr


@pytest.mark.parametrize("command,expected", [
    ("cat <<'EOF'\nodd \" quote\nEOF\npython report.py", 0),
    ("cat <<'EOF'\nrm -rf .neurath\nEOF\nrm -rf .neurath", 2),
    ("cat <<-'EOF'\n\todd \" quote\n\tEOF\npython report.py", 0),
    ("cat <<'ONE' <<'TWO'\nfirst \"\nONE\nsecond \"\nTWO\nrm -rf .neurath", 2),
    ("sh -c \"cat <<'EOF'\nbody\nEOF\nrm -rf .neurath\"", 2),
    ("sh -c \"cat <<'EOF'\nbody\nEOF\npython report.py\"", 0),
    ("cat <<EOF\n$(rm -rf .neurath)\nEOF\npython report.py", 2),
    ("cat <<< value\nrm -rf .neurath", 2),
])
def test_native_heredoc_inspection_keeps_executable_commands(tmp_path, command, expected):
    payload = {"tool_name": "Bash", "cwd": str(tmp_path),
               "tool_input": {"command": command, "workdir": str(tmp_path)}}
    result = capability_policy(tmp_path).run(json.dumps(payload), tmp_path)
    assert result.exit_code == expected, result.stderr


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
