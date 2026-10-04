"""Native payload identity, effects and stop responses share the core contract."""

import pytest

from neurath.core.domain import CoreError
from neurath.core.host_events import context_from_event, effects_for_tool, stop_response


def test_codex_child_uses_agent_id_not_parent_session_or_cwd():
    payload = {"session_id": "s", "agent_id": "child", "cwd": "/first", "tool_use_id": "tool"}
    first = context_from_event("codex", payload, "receipt")
    second = context_from_event("codex", {**payload, "cwd": "/second"}, "receipt")
    assert first == second
    assert first.actor_id == "codex:agent:child"
    assert first.session_id == "s"
    assert first != context_from_event("codex", {"session_id": "s"}, "receipt")


def test_missing_native_session_is_not_invented():
    with pytest.raises(CoreError, match="native-session-required"):
        context_from_event("claude-code", {"cwd": "/project"}, "receipt")


@pytest.mark.parametrize(
    ("name", "payload", "expected"),
    [
        ("Read", {"file_path": "README.md"}, {"read"}),
        ("apply_patch", {"command": "*** Begin Patch\n*** End Patch"}, {"edit"}),
        ("Bash", {"command": "git push origin main"}, {"publish"}),
        ("Bash", {"command": "gh pr merge 1"}, {"publish"}),
        ("Bash", {"command": "python script.py"}, {"execute"}),
        ("Bash", {"command": "git status && gh pr merge 1"}, {"read", "publish"}),
        ("Bash", {"command": "git status > tracked.txt"}, {"read", "edit"}),
        ("Bash", {"command": "python script.py && git push"}, {"execute", "publish"}),
        ("Bash", {"command": "git -C /another push"}, {"publish"}),
        ("Bash", {"command": "echo $(git push)"}, {"execute", "publish"}),
        ("Bash", {"command": "git status; rm file"}, {"read", "cleanup"}),
        ("unknown_tool", {}, {"execute"}),
    ],
)
def test_actual_effects_cannot_downgrade_known_publication(name, payload, expected):
    assert effects_for_tool(name, payload) == frozenset(expected)


def test_exact_configured_check_is_not_arbitrary_shell_prefix(tmp_path):
    command = "uv run --locked pytest -q"
    checks = ({"command": command, "cwd": str(tmp_path)},)
    assert effects_for_tool("Bash", {"command": command}, checks=checks, cwd=str(tmp_path)) == {
        "check"
    }
    assert effects_for_tool(
        "Bash", {"command": command}, checks=checks, cwd=str(tmp_path / "other")
    ) == {"execute"}
    assert effects_for_tool(
        "Bash", {"command": command + "; git push"}, checks=checks, cwd=str(tmp_path)
    ) >= {"publish"}
    mixed = ({"command": "git push", "cwd": str(tmp_path)},)
    assert effects_for_tool("Bash", {"command": "git push"}, checks=mixed, cwd=str(tmp_path)) == {
        "check",
        "publish",
    }


def test_stop_blocks_unfinished_task_without_claiming_host_shutdown_control():
    pending = {"allowed": False, "pending": [{"task_id": "task-1", "reason": "task-unfinished"}]}
    response = stop_response(pending)
    assert response["decision"] == "block"
    assert "task-1" in response["reason"]
    assert stop_response({"allowed": True, "pending": []}) == {}


def test_shell_read_commands_with_write_options_are_not_readonly():
    assert effects_for_tool("Bash", {"command": "git diff --output=result.patch"}) == {"edit"}
    assert effects_for_tool("Bash", {"command": "git remote add other url"}) == {"execute"}
    assert effects_for_tool("Bash", {"command": "git -c core.pager=script log"}) == {
        "read",
        "execute",
    }


def test_native_input_is_not_a_human_attestation(tmp_path):
    from neurath.core.service import Context, Core

    core = Core(tmp_path)
    core.observe_actor("root", "session", "codex")
    context = Context("root", "session", "event")
    first = core.observe_input(context, "Continue", "event-1", origin="continuation")
    second = core.observe_input(context, "Continue", "event-2")
    assert first.kind == "native_input"
    assert first.id != second.id
    assert core.observe_input(context, "Continue", "event-1", origin="continuation") == first
    with pytest.raises(CoreError, match="human-attestation-required"):
        core.observe_input(context, "Approved", "event-3", origin="human")
    with pytest.raises(CoreError, match="source-conflict"):
        core.observe_input(context, "Changed", "event-1")


@pytest.mark.parametrize(
    ("command", "required"),
    [
        ("git -c push.default=current push origin HEAD", {"publish", "execute"}),
        ("find . -delete", {"cleanup"}),
        ("rg --pre=./processor.py pattern .", {"execute"}),
        ("env git push origin HEAD", {"publish"}),
    ],
)
def test_known_effects_survive_options_and_wrappers(command, required):
    assert effects_for_tool("Bash", {"command": command}) >= required


def test_program_names_inside_search_arguments_are_not_commands():
    assert effects_for_tool("Bash", {"command": "rg git src"}) == {"read"}


@pytest.mark.parametrize(
    "command",
    [
        "neurath --root /project report submit report-1",
        "/project/.neurath/run report submit report-1",
        "python -I -m neurath --root /project report submit report-1",
        "neurath --root=/project report submit report-1",
    ],
)
def test_native_report_publication_keeps_approval_gate(command):
    assert "publish" in effects_for_tool("Bash", {"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "neurath --root {target} update",
        "neurath --root={target} report submit report-1",
        "python -I -m neurath --root {target} releases apply offer-1",
        "neurath setup --profile generic {target}",
        "{target}/.neurath/run update",
    ],
)
def test_maintenance_checks_actual_target_checkout(tmp_path, command):
    from neurath.core.host_events import write_targets

    target = tmp_path / "target"
    target.mkdir()
    assert target in write_targets(
        "Bash", {"command": command.format(target=target)}, str(tmp_path)
    )


@pytest.mark.parametrize(
    "command", ["touch {path}/file", "cat README > {path}/file", "find {path} -delete"]
)
def test_shell_explicit_write_destinations_are_checked(tmp_path, command):
    from neurath.core.host_events import write_targets

    first = tmp_path / "first"
    other = tmp_path / "other"
    first.mkdir()
    other.mkdir()
    assert other in write_targets("Bash", {"command": command.format(path=other)}, str(first))


def test_shell_fd_and_null_redirections_do_not_require_file_writer():
    assert effects_for_tool("Bash", {"command": "cat README 2>&1"}) == {"read"}
    assert effects_for_tool("Bash", {"command": "cat README > /dev/null"}) == {"read"}


@pytest.mark.parametrize("command", ["/usr/bin/touch {path}/file", "git diff --output={path}/file"])
def test_absolute_program_and_final_output_option_keep_write_targets(tmp_path, command):
    from neurath.core.host_events import write_targets

    first = tmp_path / "first"
    other = tmp_path / "other"
    first.mkdir()
    other.mkdir()
    assert other in write_targets("Bash", {"command": command.format(path=other)}, str(first))


@pytest.mark.parametrize(
    "command",
    [
        "neurath report consent yes --user-confirmed",
        "neurath report approve draft-1 yes --user-confirmed",
        "neurath --root=/project releases choose offer-1 yes --user-confirmed",
        "neurath setup --auto-report=yes",
    ],
)
def test_cli_confirmation_flag_is_a_decision_effect_not_user_provenance(command):
    assert effects_for_tool("Bash", {"command": command}) == {"execute", "decision"}


@pytest.mark.parametrize(
    "command",
    ["git blame src/module.py", "ps -p 123 -o pid=,command=", "launchctl print gui/501/probe"],
)
def test_history_and_exact_process_status_are_readonly(command):
    assert effects_for_tool("Bash", {"command": command}) == {"read"}


def test_process_control_and_blame_execution_options_are_not_reads():
    assert effects_for_tool("Bash", {"command": "launchctl bootout gui/501/probe"}) == {"execute"}
    assert "execute" in effects_for_tool("Bash", {"command": "git blame --textconv src/module.py"})
